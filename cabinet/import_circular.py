#!/usr/bin/env python3
"""
import_circular.py — Replace all glyph outlines in Glide variable font sources
with outlines from the Lineto Circular typeface.

Preserves all Glide metadata: axes, instances, features, kerning, metrics,
and custom parameters. Only glyph outlines and advance widths are replaced.

Circular weight → Glide master mapping:
    book   (400)  →  Regular
    medium (500)  →  Medium
    bold   (700)  →  Bold
    black  (900)  →  Black

Output files:
    glide-variable.glyphs        →  glide-circular.glyphs
    glide-variable-italic.glyphs →  glide-circular-italic.glyphs

Usage:
    .venv/bin/python import_circular.py [--dry-run]
"""

import argparse
from collections import Counter
from pathlib import Path

import glyphsLib
from fontTools.pens.pointPen import SegmentToPointPen
from fontTools.pens.qu2cuPen import Qu2CuPen
from fontTools.pens.recordingPen import DecomposingRecordingPen, RecordingPen, replayRecording
from fontTools.ttLib import TTFont
from glyphsLib.pens import LayerPointPen

BASE_DIR = Path(__file__).parent
CIRCULAR_DIR = BASE_DIR / "circular"

ROMAN_TTF = {
    400: "lineto-circular-book.ttf",
    500: "lineto-circular-medium.ttf",
    700: "lineto-circular-bold.ttf",
    900: "lineto-circular-black.ttf",
}

ITALIC_TTF = {
    400: "lineto-circular-bookItalic.ttf",
    500: "lineto-circular-mediumItalic.ttf",
    700: "lineto-circular-boldItalic.ttf",
    900: "lineto-circular-blackItalic.ttf",
}

FILES = [
    ("glide-variable.glyphs", "glide-circular.glyphs", ROMAN_TTF),
    ("glide-variable-italic.glyphs", "glide-circular-italic.glyphs", ITALIC_TTF),
]


def load_ttf(ttf_path: Path):
    """Return (TTFont, cmap, glyphset, upm)."""
    font = TTFont(str(ttf_path))
    return font, font.getBestCmap() or {}, font.getGlyphSet(), font["head"].unitsPerEm


# ---------------------------------------------------------------------------
# Contour sorting
# ---------------------------------------------------------------------------

def sort_contours(ops: list) -> list:
    """
    Sort closed contours by (n_points, start_x, start_y).
    Ensures consistent contour ordering across masters when the Circular static
    weights were drawn with different contour order (e.g. OE, uniFB03).
    """
    contours, current = [], []
    for op, args in ops:
        current.append((op, args))
        if op in ("closePath", "endPath"):
            contours.append(current)
            current = []
    if current:
        contours.append(current)

    def key(c):
        for op, a in c:
            if op == "moveTo":
                return (a[0][0], a[0][1])
        return (0.0, 0.0)

    contours.sort(key=key)
    return [item for contour in contours for item in contour]


# ---------------------------------------------------------------------------
# Effective structure (using DecomposingRecordingPen for composites)
# ---------------------------------------------------------------------------

def effective_structure(glyph_name: str, glyphset) -> tuple | None:
    """
    Sorted tuple of per-contour point counts after full decomposition.
    Uses DecomposingRecordingPen so composites are always flattened.
    """
    if glyph_name not in glyphset:
        return None
    rec = DecomposingRecordingPen(glyphset)
    try:
        glyphset[glyph_name].draw(rec)
    except Exception:
        return None
    contours, cur = [], 0
    for op, args in rec.value:
        if op == "moveTo":
            cur = 0
        elif op == "lineTo":
            cur += 1
        elif op == "qCurveTo":
            cur += len(args)
        elif op in ("closePath", "endPath"):
            contours.append(cur)
            cur = 0
    return tuple(sorted(contours))


# ---------------------------------------------------------------------------
# Glyph recording
# ---------------------------------------------------------------------------


def contour_bbox(contour: list) -> tuple:
    """Return (xmin, ymin, xmax, ymax) bounding box of a contour ops list."""
    xs, ys = [], []
    for op, args in contour:
        if op in ("moveTo", "lineTo"):
            xs.append(args[0][0]); ys.append(args[0][1])
        elif op == "curveTo":
            for pt in args:
                xs.append(pt[0]); ys.append(pt[1])
    if not xs:
        return 0.0, 0.0, 0.0, 0.0
    return min(xs), min(ys), max(xs), max(ys)


def match_contours_to_reference(ref_contours: list, other_contours: list) -> list:
    """
    Reorder other_contours so contour k in the result best corresponds to
    ref_contours[k], using bounding-box area + centre as the similarity metric.

    This handles the case where independently drawn Circular weights have the same
    contours but in a different sequence (e.g. tilde before N-body in one weight,
    N-body first in another).
    """
    def bbox_features(c):
        x1, y1, x2, y2 = contour_bbox(c)
        area = (x2 - x1) * (y2 - y1)
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        return area, cx, cy

    ref_feats = [bbox_features(c) for c in ref_contours]
    other_feats = [bbox_features(c) for c in other_contours]

    used: set = set()
    mapping: list = []
    for ra, rcx, rcy in ref_feats:
        best_j, best_score = None, float("inf")
        ref_scale = max(ra ** 0.5, 1.0)
        for j, (oa, ocx, ocy) in enumerate(other_feats):
            if j in used:
                continue
            score = ((rcx - ocx) ** 2 + (rcy - ocy) ** 2) ** 0.5 / ref_scale
            score += abs(ra - oa) / max(ra, 1.0)
            if score < best_score:
                best_score = score
                best_j = j
        mapping.append(best_j)
        used.add(best_j)

    return [other_contours[j] for j in mapping]


def record_glyph(glyph_name: str, glyphset) -> list | None:
    """
    Draw glyph through DecomposingRecordingPen → Qu2CuPen → RecordingPen.
    Returns minimal-node cubic ops (curveTo, lineTo, moveTo, closePath only).
    Qu2CuPen merges compatible quadratic splines into fewer cubics, exactly as
    Glyphs.app does when opening a TrueType font — no node explosion.
    Returns None on failure or empty glyph.
    """
    if glyph_name not in glyphset:
        return None
    rec_q = DecomposingRecordingPen(glyphset)
    try:
        glyphset[glyph_name].draw(rec_q)
    except Exception as exc:
        print(f"    WARNING: error drawing {glyph_name!r}: {exc}")
        return None
    if not rec_q.value:
        return None
    rec_c = RecordingPen()
    qu2cu = Qu2CuPen(rec_c, max_err=0.5, all_cubic=True)
    try:
        replayRecording(rec_q.value, qu2cu)
    except Exception as exc:
        print(f"    WARNING: Qu2CuPen failed for {glyph_name!r}: {exc}")
        return None
    return rec_c.value if rec_c.value else None


def write_ops_to_layer(ops: list, layer) -> None:
    """Write cubic ops directly to Glyphs layer (ops are already cubic from record_glyph)."""
    layer_pen = LayerPointPen(layer)
    replayRecording(ops, SegmentToPointPen(layer_pen))


# ---------------------------------------------------------------------------
# Phantom-point normalization
# ---------------------------------------------------------------------------

def parse_contours(ops: list) -> list:
    """Split flat RecordingPen ops list into a list-of-contour-ops-lists."""
    contours, current = [], []
    for op, args in ops:
        current.append((op, args))
        if op in ("closePath", "endPath"):
            contours.append(current)
            current = []
    if current:
        contours.append(current)
    return contours


def count_segments(contour: list) -> int:
    """
    Count drawable segments (lineTo + curveTo) in a cubic contour ops list.
    Equal segment counts → equal cubic node counts (since ops are already cubic).
    """
    return sum(1 for op, _ in contour if op in ("lineTo", "curveTo"))


def _prev_on_curve(contour: list, idx: int):
    """Return the on-curve point immediately before op at index idx."""
    for j in range(idx - 1, -1, -1):
        op, args = contour[j]
        if op == "moveTo":
            return args[0]
        elif op == "lineTo":
            return args[0]
        elif op == "curveTo":
            return args[-1]  # last point in curveTo is the on-curve endpoint
    return None


def add_one_segment(contour: list) -> list | None:
    """
    Add exactly 1 segment by splitting an existing segment at t=0.5.

    Prefers splitting curveTo (cubic de Casteljau) to keep curve/line type consistency.
    Falls back to splitting lineTo at midpoint when no curveTo is available.
    After add_one_segment + unify_op_types, the op types are reconciled across masters.

    Returns new contour, or None if no splittable segment is found.
    """
    # First pass: split a curveTo (preferred)
    for i, (op, args) in enumerate(contour):
        if op == "curveTo" and len(args) == 3:
            prev = _prev_on_curve(contour, i)
            if prev is None:
                continue
            p0, p1, p2, p3 = prev, args[0], args[1], args[2]
            # Cubic de Casteljau at t=0.5
            m01  = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
            m12  = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
            m23  = ((p2[0] + p3[0]) / 2, (p2[1] + p3[1]) / 2)
            m012 = ((m01[0] + m12[0]) / 2, (m01[1] + m12[1]) / 2)
            m123 = ((m12[0] + m23[0]) / 2, (m12[1] + m23[1]) / 2)
            mid  = ((m012[0] + m123[0]) / 2, (m012[1] + m123[1]) / 2)
            return (contour[:i]
                    + [("curveTo", (m01, m012, mid)), ("curveTo", (m123, m23, p3))]
                    + contour[i + 1:])
    # Second pass: split a lineTo at its midpoint
    for i, (op, args) in enumerate(contour):
        if op == "lineTo":
            prev = _prev_on_curve(contour, i)
            if prev is None:
                continue
            on = args[0]
            mid = ((prev[0] + on[0]) / 2, (prev[1] + on[1]) / 2)
            return (contour[:i]
                    + [("lineTo", (mid,)), ("lineTo", (on,))]
                    + contour[i + 1:])
    return None


def convert_lines_to_degenerate_curves(ops: list) -> list:
    """
    Two transformations to ensure cubic node count consistency across masters:

    1. Replace every lineTo(on) with degenerate qCurveTo(midpoint, on).
       A midpoint control point lies on the line p0→on, so the visual result is
       identical to a straight line but is a curve op → cubic node count is 3
       (not 1), matching other masters that use qCurveTo for the same segment.

    2. Make implicit closePath edges explicit.
       TrueType paths close implicitly: if the last on-curve before closePath is
       NOT the same point as moveTo, fontTools' SegmentToPointPen writes the
       moveTo as an extra "line" type node (+1 node). By inserting a degenerate
       qCurveTo(midpoint, moveTo) before closePath, we make the closing edge
       explicit so SegmentToPointPen needs no extra node.
       This fixes masters that stored paths with a different starting on-curve.
    """
    result = []
    prev_on = None
    contour_start = None
    for op, args in ops:
        if op == "moveTo":
            result.append((op, args))
            prev_on = args[0]
            contour_start = args[0]
        elif op == "lineTo":
            on = args[0]
            if prev_on is not None:
                mid = ((prev_on[0] + on[0]) / 2, (prev_on[1] + on[1]) / 2)
            else:
                mid = on
            result.append(("qCurveTo", (mid, on)))
            prev_on = on
        elif op == "qCurveTo":
            result.append((op, args))
            prev_on = args[-1]
        elif op == "closePath":
            # If the last on-curve ≠ contour start, the closing edge is implicit.
            # Make it explicit so SegmentToPointPen doesn't add a spurious node.
            if (prev_on is not None and contour_start is not None
                    and prev_on != contour_start):
                mid = ((prev_on[0] + contour_start[0]) / 2,
                       (prev_on[1] + contour_start[1]) / 2)
                result.append(("qCurveTo", (mid, contour_start)))
            result.append((op, args))
            prev_on = None
            contour_start = None
        elif op == "endPath":
            result.append((op, args))
            prev_on = None
            contour_start = None
        else:
            result.append((op, args))
    return result


def rotate_contour_to_align(contour: list, target: tuple) -> list:
    """
    Rotate a closed contour's ops so the on-curve point closest to `target`
    becomes the new moveTo start point.

    Handles both implicit close (last on-curve ≠ moveTo) and explicit close.
    When the contour has an implicit close, an explicit straight-line curveTo is
    inserted for the closing edge so SegmentToPointPen does not write the moveTo
    as an extra "line" node (which would add +1 node vs masters with explicit close).
    """
    if not contour or contour[0][0] != "moveTo" or contour[-1][0] != "closePath":
        return contour  # open path or malformed — leave unchanged

    moveto_pt = contour[0][1][0]
    segments  = contour[1:-1]   # ops between moveTo and closePath
    close_op  = contour[-1]

    # Collect (point, segment_index) for every on-curve in the contour.
    # The moveTo itself is included as index -1 (before any segment).
    on_curves = [(moveto_pt, -1)]
    for i, (op, args) in enumerate(segments):
        if op in ("lineTo", "curveTo"):
            on_curves.append((args[-1], i))

    if len(on_curves) < 2:
        return contour

    def dist_sq(p):
        return (p[0] - target[0]) ** 2 + (p[1] - target[1]) ** 2

    best_k = min(range(len(on_curves)), key=lambda k: dist_sq(on_curves[k][0]))

    # Does the original contour have an implicit closing edge?
    # (i.e. the last on-curve before closePath ≠ moveTo)
    last_on = on_curves[-1][0]
    has_implicit_close = (last_on != moveto_pt)

    if best_k == 0:
        # No rotation needed. But if there's an implicit close, make it explicit so
        # SegmentToPointPen won't add an extra "line" node for the wrap-around edge.
        if not has_implicit_close:
            return contour
        p_n = last_on
        p0  = moveto_pt
        dx, dy = p0[0] - p_n[0], p0[1] - p_n[1]
        c1 = (p_n[0] + dx / 3,       p_n[1] + dy / 3)
        c2 = (p_n[0] + 2 * dx / 3,   p_n[1] + 2 * dy / 3)
        return contour[:-1] + [("curveTo", (c1, c2, p0))] + [close_op]

    best_seg_idx = on_curves[best_k][1]   # index of the segment that ends at new start

    # Build the rotated segment sequence:
    #   [segs after the new-start segment]
    #   [lineTo(original moveTo) — only if the original had an implicit close]
    #   [segs up to and including the new-start segment]
    after_k = list(segments[best_seg_idx + 1:])
    up_to_k  = list(segments[:best_seg_idx + 1])

    if has_implicit_close:
        # Make the wrap-around closing edge explicit as a straight-line curveTo.
        # Using curveTo (not lineTo) keeps node counts consistent: each segment = 3 nodes.
        # The handles lie at 1/3 and 2/3 of the chord so the cubic IS a straight line.
        p_n = last_on
        p0  = moveto_pt
        dx, dy = p0[0] - p_n[0], p0[1] - p_n[1]
        c1 = (p_n[0] + dx / 3,       p_n[1] + dy / 3)
        c2 = (p_n[0] + 2 * dx / 3,   p_n[1] + 2 * dy / 3)
        after_k.append(("curveTo", (c1, c2, p0)))

    new_start = on_curves[best_k][0]
    return [("moveTo", (new_start,))] + after_k + up_to_k + [close_op]


def _line_to_degenerate_curve(prev_pt: tuple, on_pt: tuple) -> tuple:
    """Convert a lineTo endpoint to a degenerate curveTo with handles at 1/3 and 2/3."""
    dx, dy = on_pt[0] - prev_pt[0], on_pt[1] - prev_pt[1]
    c1 = (prev_pt[0] + dx / 3,       prev_pt[1] + dy / 3)
    c2 = (prev_pt[0] + 2 * dx / 3,   prev_pt[1] + 2 * dy / 3)
    return ("curveTo", (c1, c2, on_pt))


def unify_op_types(master_contours: dict) -> dict:
    """
    Ensure all masters use the same op type at every segment position.

    After equalization, all masters have the same segment count per contour,
    but some positions may have curveTo in one master and lineTo in another.
    Glyphs.app requires identical node types: 1 lineTo = 1 node, 1 curveTo = 3 nodes.
    If counts differ, the font won't export as a variable font.

    Rule: if ANY master uses curveTo at position i, ALL must — convert lineTo to a
    degenerate curveTo with handles at 1/3 and 2/3 of the chord (visually straight).
    """
    mids = list(master_contours)
    n_contours = len(master_contours[mids[0]])

    for k in range(n_contours):
        # Extract inner segments (between moveTo and closePath)
        inner: dict[str, list] = {}
        for mid in mids:
            c = master_contours[mid][k]
            inner[mid] = list(c[1:-1])

        n_segs = max(len(s) for s in inner.values()) if inner else 0
        changed = False

        for i in range(n_segs):
            ops_at_i = {mid: inner[mid][i][0] for mid in mids if i < len(inner[mid])}
            if "curveTo" in ops_at_i.values() and "lineTo" in ops_at_i.values():
                # Mixed types — upgrade all lineTos to degenerate curveTos
                for mid, op_type in ops_at_i.items():
                    if op_type == "lineTo":
                        on_pt = inner[mid][i][1][0]
                        # Find the preceding on-curve
                        if i == 0:
                            prev_pt = master_contours[mid][k][0][1][0]  # moveTo
                        else:
                            prev_op, prev_args = inner[mid][i - 1]
                            prev_pt = prev_args[-1]
                        inner[mid][i] = _line_to_degenerate_curve(prev_pt, on_pt)
                        changed = True

        if changed:
            for mid in mids:
                c = master_contours[mid][k]
                master_contours[mid][k] = [c[0]] + inner[mid] + [c[-1]]

    return master_contours


def normalize_master_ops(master_ops: dict) -> dict:
    """
    Normalize all masters so corresponding contours have the same cubic segment count
    and identical op types.

    Input ops are already cubic (curveTo, lineTo) from record_glyph → Qu2CuPen.

    Process:
    1. Parse into per-contour lists.
    2. Match contours across masters by bounding-box area + centre.
       This handles independently drawn Circular weights that store the same contours
       in different sequence orders (e.g. Ntilde has tilde before N in some weights,
       N before tilde in others).
    3. Rotate each non-reference master's contours so their start point aligns with
       the reference master's start point (prevents point-index misalignment during
       Glyphs.app interpolation, which caused the "double outline" artifact).
    4. Equalize segment counts by splitting curveTo segments (cubic de Casteljau t=0.5).
    5. Unify op types: where any master uses curveTo, all must — convert lineTo to
       degenerate curveTo so Glyphs.app cubic node counts are equal across masters.

    After normalization, all masters produce an identical cubic node sequence
    per contour → Glyphs.app compatibility guaranteed.
    """
    # Step 1 — parse into per-contour lists
    master_contours_raw = {mid: parse_contours(ops) for mid, ops in master_ops.items()}

    # Step 2 — match contours across masters to the reference (first master)
    mids = list(master_contours_raw)
    ref_mid = mids[0]
    ref_contours = master_contours_raw[ref_mid]

    master_contours: dict = {ref_mid: ref_contours}
    for mid in mids[1:]:
        other = master_contours_raw[mid]
        if len(other) == len(ref_contours):
            master_contours[mid] = match_contours_to_reference(ref_contours, other)
        else:
            master_contours[mid] = other  # contour count mismatch → outer fallback handles it

    n_contours = len(ref_contours)

    # Step 3 — rotate all masters' contour start points to align with reference.
    # Also applied to the reference itself to make any implicit closing edge explicit
    # (prevents SegmentToPointPen from writing moveTo as an extra "line" node).
    for k in range(n_contours):
        ref_start = ref_contours[k][0][1][0]   # moveTo point of reference contour k
        for mid in mids:
            master_contours[mid][k] = rotate_contour_to_align(
                master_contours[mid][k], ref_start
            )

    # Step 4 — equalize segment counts per contour position
    for k in range(n_contours):
        segs = {mid: count_segments(master_contours[mid][k]) for mid in master_contours}
        max_segs = max(segs.values())
        for mid in master_contours:
            for _ in range(max_segs - segs[mid]):
                result = add_one_segment(master_contours[mid][k])
                if result is not None:
                    master_contours[mid][k] = result
        # If any master still has fewer segments, normalization failed (e.g. all-lineTo
        # contour that cannot accept a curve insertion). Signal caller to fall back.
        final_segs = {count_segments(master_contours[mid][k]) for mid in master_contours}
        if len(final_segs) > 1:
            return None

    # Step 5 — unify op types so cubic node counts are equal across masters.
    master_contours = unify_op_types(master_contours)

    return {
        mid: [item for contour in contours for item in contour]
        for mid, contours in master_contours.items()
    }


# ---------------------------------------------------------------------------
# Cubic node-count verification (actual Glyphs.app compatibility metric)
# ---------------------------------------------------------------------------

def cubic_node_counts(ops: list) -> list:
    """
    Count Glyphs-compatible nodes per contour for cubic ops.
    Glyphs.app counts:
      - closed contour with N curveTo: 3N nodes (2 off-curve handles + 1 on-curve each)
      - lineTo: 1 node
      - open contour: 1 extra node for the moveTo on-curve
    Ops are already cubic (from record_glyph → Qu2CuPen) — no conversion needed.
    Returns a list with one integer per contour.
    """
    result = []
    cur_curves = cur_lines = 0
    for op, _ in ops:
        if op == "moveTo":
            cur_curves = cur_lines = 0
        elif op == "curveTo":
            cur_curves += 1
        elif op == "lineTo":
            cur_lines += 1
        elif op == "endPath":
            result.append(3 * cur_curves + cur_lines + 1)  # +1 for open-path moveTo node
        elif op == "closePath":
            result.append(3 * cur_curves + cur_lines)
    return result


def verify_cubic_compat(master_ops: dict) -> bool:
    """
    Return True iff all masters produce identical cubic node counts per contour.
    This is the real compatibility predicate Glyphs.app uses — NOT quadratic segment counts.
    """
    all_counts = [tuple(cubic_node_counts(ops)) for ops in master_ops.values()]
    return len(set(all_counts)) == 1


# ---------------------------------------------------------------------------
# Layer writing
# ---------------------------------------------------------------------------

def replace_layer_outlines(layer, ops: list, upm_scale: float) -> None:
    """Clear layer shapes and write new ops (width already set by caller)."""
    layer.shapes = []
    write_ops_to_layer(ops, layer)


# ---------------------------------------------------------------------------
# Glyph name lookup
# ---------------------------------------------------------------------------

def find_ttf_glyph(glyph, cmap: dict, glyphset) -> str | None:
    """Find the Circular TTF glyph name for a glyphsLib GSGlyph."""
    # 1. Unicode codepoint lookup (glyph.unicodes is a list of hex strings)
    for cp_str in glyph.unicodes:
        cp = int(cp_str, 16)
        if cp in cmap:
            name = cmap[cp]
            if name in glyphset:
                return name

    # 2. Direct glyph name match
    if glyph.name in glyphset:
        return glyph.name

    # 3. Strip suffix (fi.1 → fi, a.ss02 → a) and try base name
    if "." in glyph.name:
        base = glyph.name.rsplit(".", 1)[0]
        if base in glyphset:
            return base

    return None


# ---------------------------------------------------------------------------
# Main font processing
# ---------------------------------------------------------------------------

def process_font(
    input_path: Path,
    output_path: Path,
    weight_to_ttf: dict[int, str],
    dry_run: bool,
) -> None:
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Loading: {input_path.name}")
    font = glyphsLib.load(str(input_path))
    glide_upm: int = font.upm

    # Load all Circular TTFs keyed by master ID
    master_data: dict[str, tuple] = {}  # master_id → (ttf_font, cmap, glyphset, upm_scale)

    for master in font.masters:
        weight = int(master.axes[0])
        if weight not in weight_to_ttf:
            print(f"  WARN: no Circular TTF for weight {weight}, skipping {master.name!r}")
            continue
        ttf_path = CIRCULAR_DIR / weight_to_ttf[weight]
        if not ttf_path.exists():
            print(f"  WARN: TTF not found: {ttf_path}")
            continue
        ttf_font, cmap, glyphset, circ_upm = load_ttf(ttf_path)
        upm_scale = glide_upm / circ_upm
        if upm_scale != 1.0:
            print(f"  UPM scale {master.name!r}: {glide_upm}/{circ_upm} = {upm_scale:.4f}")
        master_data[master.id] = (ttf_font, cmap, glyphset, upm_scale)

    print(f"  Masters loaded: {len(master_data)}/{len(font.masters)}")

    replaced = skipped = fallback_count = total_layers = 0
    fallback_glyphs: list[str] = []

    for glyph in font.glyphs:
        # --- Determine TTF name per master ---
        master_ttf_names: dict[str, str | None] = {}
        for mid, (_, cmap, glyphset, _) in master_data.items():
            master_ttf_names[mid] = find_ttf_glyph(glyph, cmap, glyphset)

        # --- Compute decomposed structures ---
        master_structs: dict[str, tuple | None] = {}
        for mid, ttf_name in master_ttf_names.items():
            if ttf_name:
                _, _, glyphset, _ = master_data[mid]
                master_structs[mid] = effective_structure(ttf_name, glyphset)
            else:
                master_structs[mid] = None

        # --- Check contour count compatibility ---
        valid_structs = [s for s in master_structs.values() if s is not None]
        contour_counts = {len(s) for s in valid_structs}
        use_fallback = len(contour_counts) > 1

        if use_fallback:
            # Contour count differs (cent, dollar, r.ss03, etc.)
            # Use the most common contour structure as canonical source
            majority_struct = Counter(
                tuple(s) for s in valid_structs
            ).most_common(1)[0][0]
            canonical_mid = next(
                mid for mid, s in master_structs.items()
                if s is not None and tuple(s) == majority_struct
            )
            canonical_name = master_ttf_names[canonical_mid]
            _, _, canonical_gs, _ = master_data[canonical_mid]
            fallback_ops = record_glyph(canonical_name, canonical_gs)
            if fallback_ops:
                fallback_count += 1
                fallback_glyphs.append(glyph.name)
            master_norm_ops: dict[str, list | None] = {}
        else:
            # Same contour count — record all masters and normalize point counts
            master_raw_ops: dict[str, list] = {}
            for mid, ttf_name in master_ttf_names.items():
                if ttf_name and mid in master_data:
                    _, _, glyphset, _ = master_data[mid]
                    ops = record_glyph(ttf_name, glyphset)
                    if ops:
                        master_raw_ops[mid] = ops

            # If any master is missing from the TTF, we cannot produce a consistent
            # variable-font layer set. Trigger fallback so all masters get the same
            # canonical outline rather than leaving missing layers with old shapes.
            missing_mids = [mid for mid in master_data if mid not in master_raw_ops]
            if missing_mids and master_raw_ops:
                # Use the majority structure from available masters as canonical
                avail_structs = [master_structs[mid] for mid in master_raw_ops
                                 if master_structs.get(mid) is not None]
                if avail_structs:
                    canon_struct = Counter(tuple(s) for s in avail_structs).most_common(1)[0][0]
                    canonical_mid = next(
                        mid for mid in master_raw_ops
                        if master_structs.get(mid) is not None
                        and tuple(master_structs[mid]) == canon_struct
                    )
                    canonical_name = master_ttf_names[canonical_mid]
                    _, _, canonical_gs, _ = master_data[canonical_mid]
                    fallback_ops = record_glyph(canonical_name, canonical_gs)
                    use_fallback = True
                    fallback_count += 1
                    fallback_glyphs.append(glyph.name)
                    master_norm_ops = {}
                # else: no valid structs, fall through to single-master or no-op
            elif len(master_raw_ops) > 1:
                master_norm_ops = normalize_master_ops(master_raw_ops)
                # Also verify cubic node counts are actually equal — normalize_master_ops
                # checks quadratic segment counts but Glyphs cares about cubic nodes.
                if master_norm_ops is not None and not verify_cubic_compat(master_norm_ops):
                    master_norm_ops = None  # treat as normalization failure
                if master_norm_ops is None:
                    # Normalization failed (e.g. all-lineTo contour with segment mismatch,
                    # or cubic node count mismatch after conversion).
                    # Fall back to the majority-structure canonical source.
                    majority_struct = Counter(
                        tuple(master_structs[mid]) for mid in master_raw_ops
                        if master_structs.get(mid) is not None
                    ).most_common(1)[0][0]
                    canonical_mid = next(
                        mid for mid in master_raw_ops
                        if master_structs.get(mid) is not None
                        and tuple(master_structs[mid]) == majority_struct
                    )
                    canonical_name = master_ttf_names[canonical_mid]
                    _, _, canonical_gs, _ = master_data[canonical_mid]
                    fallback_ops = record_glyph(canonical_name, canonical_gs)
                    use_fallback = True
                    fallback_count += 1
                    fallback_glyphs.append(glyph.name)
                    master_norm_ops = {}
                else:
                    fallback_ops = None
            else:
                master_norm_ops = master_raw_ops
                fallback_ops = None

        # --- Write to each master layer ---
        for layer in glyph.layers:
            if layer.layerId not in master_data:
                continue
            total_layers += 1
            ttf_name = master_ttf_names.get(layer.layerId)
            if ttf_name is None and not use_fallback:
                # No TTF glyph for this master and no fallback — skip (leave unchanged).
                skipped += 1
                continue

            _, _, glyphset, upm_scale = master_data[layer.layerId]
            if not dry_run:
                layer.shapes = []
                try:
                    layer.width = round(glyphset[ttf_name].width * upm_scale)
                except Exception:
                    pass

                if use_fallback:
                    ops_to_use = fallback_ops
                else:
                    ops_to_use = master_norm_ops.get(layer.layerId)
                    if ops_to_use is None and master_norm_ops:
                        print(f"  WARNING: no normalized ops for {glyph.name!r} "
                              f"layer {layer.name!r} (id {layer.layerId[:8]}…) — layer will be empty")

                if ops_to_use:
                    write_ops_to_layer(ops_to_use, layer)
            replaced += 1

    print(f"  Glyphs: {len(font.glyphs)} total, {total_layers} master layers")
    print(f"  Replaced: {replaced}  |  Skipped: {skipped}  |  Static fallback: {fallback_count}")
    if fallback_glyphs:
        print(f"  Fallback glyphs ({len(fallback_glyphs)}): {', '.join(fallback_glyphs)}")

    if not dry_run:
        font.save(str(output_path))
        print(f"  Saved → {output_path.name}")
    else:
        print(f"  Would save → {output_path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Glide → Circular glyph importer")
    for src_name, dst_name, weight_map in FILES:
        src = BASE_DIR / src_name
        dst = BASE_DIR / dst_name
        if not src.exists():
            print(f"\nWARN: {src_name} not found, skipping")
            continue
        process_font(src, dst, weight_map, dry_run=args.dry_run)
    print("\nDone.")


if __name__ == "__main__":
    main()
