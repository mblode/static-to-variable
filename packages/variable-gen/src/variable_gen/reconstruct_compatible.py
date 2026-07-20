#!/usr/bin/env python3
"""Glyph compatibility reconstruction engine.

Given a glyph's outlines at several weights drawn as INDEPENDENT statics (so they
disagree on contour count / order / start point / node count — common when donor
weights are drawn separately and many glyphs are structurally incompatible),
produce per-master outlines that share ONE point structure, so they interpolate
into a variable font, while each master still matches its own weight's shape.

Contours use the donor_outline format from variable_gen.outlines:
    contours = [ [ (op, [pt,...]), ... ], ... ]   op in moveTo/lineTo/curveTo/
    qCurveTo/closePath/endPath; pts are (x, y) float tuples.

Stage A (this module) is deterministic, applied cheapest-first and re-checked, so
a glyph stops as soon as it is compatible:
  1. (decompose — already done upstream by donor_outline)
  2. winding normalization
  3. contour-order match to a reference master
  4. start-point rotation to align contours
  5. corner-anchored arc-length resampling for contours whose node counts still
     differ (only those contours; compatible contours keep their exact curves)

`reconstruct(outlines_by_pos)` returns (compatible_outlines_by_pos, info). If the
glyph cannot be reconciled deterministically (e.g. a contour has a different
number of CORNERS across weights — a genuine structural difference), it returns
(None, info) so the caller can route to the AI fallback (ai_reconstruct.py).
"""

from __future__ import annotations

import math

from variable_gen.outlines import signature

CORNER_ANGLE = math.radians(28)  # tangent break above this = corner anchor
RESAMPLE_STEP = 18  # target units between resampled points (dense
# enough that curves stay smooth at display sizes)
MIN_RUN_PTS = 1  # min interior points per inter-corner run


# ---------------------------------------------------------------------------
# contour <-> flat point ring
# ---------------------------------------------------------------------------


def _cubic(p0, p1, p2, p3, t):
    u = 1 - t
    return (
        u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
        u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1],
    )


def _implied_oncurve_contour(contour):
    """Expand an all-off-curve TrueType quadratic contour into explicit on-curve
    nodes so :func:`to_ring` can parse it.

    Such a contour is recorded (by DecomposingRecordingPen) as a single leading
    ``qCurveTo`` of off-curve points ending in an implied ``None`` on-curve point,
    with NO ``moveTo`` — common for round glyphs (o, O, zero) in TrueType donors
    like Titillium. Its real on-curve points sit at the midpoints of consecutive
    off-curve points. Contours that already start on-curve (a ``moveTo``) are
    returned unchanged, so normal glyphs are untouched."""
    if not contour or contour[0][0] == "moveTo":
        return contour
    offs = [p for op, pts in contour if op == "qCurveTo" for p in pts if p is not None]
    k = len(offs)
    if k < 2:
        return contour
    mids = [
        ((offs[i][0] + offs[(i + 1) % k][0]) / 2, (offs[i][1] + offs[(i + 1) % k][1]) / 2)
        for i in range(k)
    ]
    out = [("moveTo", [mids[-1]])]
    for i in range(k):
        out.append(("qCurveTo", [offs[i], mids[i]]))
    out.append(("closePath", []))
    return out


def to_ring(contour, corner_angle=CORNER_ANGLE):
    """Flatten a contour to an ordered ring of on-curve nodes, returning
    (nodes, seg_samples, corners). `seg_samples[i]` are the densely-sampled curve
    points on the segment INTO node i (for arc-length resampling). A corner is an
    on-curve node where the real curve tangent breaks — computed from the adjacent
    off-curve HANDLES (not neighbour nodes), so a smooth circle node is not a
    corner even though its neighbours sit at 90 degrees.

    Two-pass: first build the closed node ring with one EDGE descriptor per
    consecutive node pair (kind + control points), then derive per-node tangents
    and samples from the edges."""
    contour = _implied_oncurve_contour(contour)
    start = contour[0][1][0]
    nodes = [start]
    edges = []  # edge i connects nodes[i] -> nodes[i+1]; (kind, controls)
    cur = start
    for op, pts in contour[1:]:
        if op == "lineTo":
            nodes.append(pts[0])
            edges.append(("line", None))
            cur = pts[0]
        elif op == "curveTo":
            c1, c2, end = pts
            nodes.append(end)
            edges.append(("cubic", (c1, c2)))
            cur = end
        elif op == "qCurveTo":
            off = list(pts[:-1])
            last = pts[-1]
            prev = cur
            for i, c in enumerate(off):
                nxt = (
                    last
                    if i == len(off) - 1
                    else ((c[0] + off[i + 1][0]) / 2, (c[1] + off[i + 1][1]) / 2)
                )
                nodes.append(nxt)
                edges.append(("quad", (c,)))
                prev = nxt
            cur = last
        elif op in ("closePath", "endPath"):
            pass
    # fold an explicit duplicate closing node back onto node 0
    if len(nodes) > 1 and _dist(nodes[-1], nodes[0]) < 1e-6:
        nodes.pop()
    n = len(nodes)
    if n < 2:
        return nodes, [None] * n, [True] * n
    # if the path didn't return to start, the implicit closing edge is a line
    if len(edges) < n:
        edges.append(("line", None))
    edges = edges[:n]  # edge i: nodes[i] -> nodes[(i+1)%n]

    seg_samples = [None] * n  # interior samples on edge i (node i -> node i+1)
    out_tan = [None] * n  # tangent leaving node i        (edge i)
    in_tan = [None] * n  # tangent arriving at node i     (edge i-1)
    for i in range(n):
        a, b = nodes[i], nodes[(i + 1) % n]
        kind, ctrl = edges[i]
        if kind == "line":
            out_tan[i] = _unit(a, b)
            in_tan[(i + 1) % n] = _unit(a, b)
            seg_samples[i] = []
        elif kind == "cubic":
            c1, c2 = ctrl
            out_tan[i] = _unit(a, c1) if _dist(a, c1) > 1e-6 else _unit(a, c2)
            in_tan[(i + 1) % n] = _unit(c2, b) if _dist(c2, b) > 1e-6 else _unit(c1, b)
            steps = max(2, int(_dist(a, c1) + _dist(c1, c2) + _dist(c2, b)) // 24)
            seg_samples[i] = [_cubic(a, c1, c2, b, j / steps) for j in range(1, steps)]
        else:  # quad
            c = ctrl[0]
            out_tan[i] = _unit(a, c)
            in_tan[(i + 1) % n] = _unit(c, b)
            steps = max(2, int(_dist(a, c) + _dist(c, b)) // 24)
            seg_samples[i] = [_quad(a, c, b, j / steps) for j in range(1, steps)]
    corners = _corner_flags_tan(in_tan, out_tan, corner_angle)
    # Build a DENSE ring: each on-curve node followed by its outgoing edge's curve
    # samples. Corner flags mark only the true on-curve corner nodes. Resampling
    # the dense ring (not the sparse nodes) keeps round shapes round.
    dense, dense_corner = [], []
    for i in range(n):
        dense.append(nodes[i])
        dense_corner.append(corners[i])
        for s in seg_samples[i]:
            dense.append(s)
            dense_corner.append(False)
    return dense, None, dense_corner


def _quad(p0, p1, p2, t):
    u = 1 - t
    return (
        u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
        u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
    )


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _unit(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    m = math.hypot(dx, dy)
    return (dx / m, dy / m) if m > 1e-9 else (0.0, 0.0)


def _corner_flags_tan(in_tan, out_tan, corner_angle=CORNER_ANGLE):
    """Corner = node where the incoming and outgoing curve tangents break by more
    than corner_angle. Tangents come from the curve handles, so smooth nodes
    (collinear handles) are never corners regardless of node spacing."""
    flags = []
    for it, ot in zip(in_tan, out_tan, strict=False):
        if it is None or ot is None or (it == (0.0, 0.0)) or (ot == (0.0, 0.0)):
            flags.append(True)
            continue
        cosang = max(-1.0, min(1.0, it[0] * ot[0] + it[1] * ot[1]))
        flags.append(math.acos(cosang) > corner_angle)
    return flags


def _signed_area(pts):
    n = len(pts)
    return 0.5 * sum(
        pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n)
    )


def _centroid(pts):
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


# ---------------------------------------------------------------------------
# reconstruction
# ---------------------------------------------------------------------------


def _already_compatible(outlines):
    sigs = {pos: signature(c) for pos, c in outlines.items()}
    return len(set(sigs.values())) == 1


def _starts_aligned(outlines, tol=0.12):
    """signature() only checks op-sequence + winding, which CANNOT detect a
    contour that starts at a different node across masters (all-curve shapes like
    C/o have an identical all-curveTo op-sequence from ANY start). Such drift
    interpolates node->wrong-node and collapses the glyph at in-between weights.
    Here we verify the start node sits at a consistent position (normalised to the
    contour bbox) across masters; if not, the glyph must be reconstructed."""
    positions = sorted(outlines)
    n = len(outlines[positions[0]])
    for ci in range(n):
        norm = []
        for p in positions:
            ring = to_ring(outlines[p][ci])[0]
            if len(ring) < 2:
                return False
            xs = [q[0] for q in ring]
            ys = [q[1] for q in ring]
            w = max(xs) - min(xs)
            h = max(ys) - min(ys)
            if w <= 0 or h <= 0:
                continue
            norm.append(((ring[0][0] - min(xs)) / w, (ring[0][1] - min(ys)) / h))
        if not norm:
            continue
        if (
            max(p[0] for p in norm) - min(p[0] for p in norm) > tol
            or max(p[1] for p in norm) - min(p[1] for p in norm) > tol
        ):
            return False
    return True


# Corner detection sits near a threshold for a few glyphs, so the corner COUNT
# can flicker by one across weights (e.g. 12 vs 11). Sweep a few angles and keep
# the first where reconstruction succeeds, before declaring an AI-fallback case.
# Corner detection sits near a threshold for some glyphs, so the corner COUNT can
# flicker by one across weights. A dense sweep (incl. low angles 8-12°, where a
# straddling corner stabilises so all masters AGREE and the clean resample path
# is used instead of projection) lets us reconstruct glyphs like italic f / fl.
CORNER_ANGLE_SWEEP = [
    math.radians(a) for a in (28, 24, 32, 20, 36, 16, 40, 12, 44, 10, 48, 8, 14, 26)
]


def reconstruct(outlines_by_pos, reference_pos=400):
    """outlines_by_pos: {axis_pos: contours}. Returns (compatible|None, info).
    Tries a sweep of corner-detection thresholds; returns the first that yields a
    fully interpolation-compatible result, then (for 3+ masters) swaps in the
    rotation-aligned uniform resample when it predicts the interior master
    better — see _interior_dev. If masters disagree on contour COUNT, first
    unions overlapping contours per master (handles glyphs like $ / ¢ whose
    separate bar stubs merge into the body at heavy weights)."""
    out, info = _reconstruct_base(outlines_by_pos, reference_pos)
    return _ink_tournament(out, info, outlines_by_pos, reference_pos)


# A candidate whose best-available coarse ink-defect ratio exceeds this is
# catastrophically broken at in-between weights (contours swapping places, e.g.
# dieresisacute's dots at 2.7, Neuton Ecircumflex at 1.9, Titillium onehalf's
# folding "1" at 1.54); freeze rather than ship it. Deliberately high: features
# that legitimately TRAVEL far between masters (Poppins' quote ticks quadruple
# in size: 1.05, Mukta's ellipsis dots: 1.46, Titillium's circumflex: 0.96)
# leak past the fixed blur while rendering fine, so sub-threshold scores only
# ever decide the RELATIVE choice between candidates, never a freeze.
INK_FREEZE_TOL = 1.5
# Raster resolution for the ink-defect measure. 72px keeps a ±2px blur at
# roughly stroke-modulation scale, so legitimate weight gain scores 0.0.
INK_RES = 72


def _ink_tournament(out, info, outlines_by_pos, reference_pos):
    """Pick between the winning reconstruction and the rotation-aligned uniform
    candidate by what the eye actually sees mid-axis.

    Corner-anchored resampling and reference projection can pass every
    point-space gate yet still carry subtly wrong correspondence: Barlow's v/w
    wobble, Barlow Condensed's G loses its spur, Crimson's A/W apexes notch —
    all clean AT the masters, broken only BETWEEN them, and too local for the
    area/perimeter gates. The honest measure is raster ink: at span midpoints, a
    defect is ink that both endpoint masters have but the midpoint loses, or ink
    appearing beyond both (see _ink_defect). Legitimate interpolation scores 0.0
    at the coarse (±2px) blur, so any nonzero coarse score is suspicious;
    wobble too fine for the coarse scale still separates at ±1px, where
    candidates are compared RELATIVELY (absolute fine scores also pick up
    legitimate stroke-edge shift, so no absolute fine threshold exists).
    Whichever candidate keeps mid-axis ink closest to its endpoints wins; a
    coarse tie breaks on the fine score, and a full tie keeps the original
    (corner-anchored results keep corners crisper). If even the winner is
    severely broken, freeze clean instead of shipping it."""
    if out is None:
        return out, info
    cross = _disjoint_cross(out)
    coarse = _ink_defect(out, blur=2)
    chosen, chosen_info, chosen_coarse, chosen_cross = out, info, coarse, cross
    if cross or not info.get("note", "").startswith("uniform"):
        aligned = _uniform_aligned(outlines_by_pos, reference_pos)
        if (
            aligned is not None
            and _struct_ok(aligned)
            and _cu2qu_safe(aligned)
            and not _quality_offenders(aligned, outlines_by_pos)
            and _interp_ok(aligned)
        ):
            a_cross = _disjoint_cross(aligned)
            a_coarse = _ink_defect(aligned, blur=2)
            better = (cross and not a_cross) or (cross == a_cross and a_coarse < coarse - 1e-9)
            if not better and cross == a_cross and abs(a_coarse - coarse) <= 1e-9:
                better = _ink_defect(aligned, blur=1) < _ink_defect(out, blur=1) - 1e-9
            if better:
                chosen = aligned
                chosen_info = {"stage": "reconstructed", "note": "uniform-aligned (ink)"}
                chosen_coarse, chosen_cross = a_coarse, a_cross
    if chosen_cross:
        # separate pieces passing through each other mid-axis (Titillium's quote
        # ticks merging into one blob): no ink is lost so the defect ratio can't
        # see it — freeze clean instead.
        return None, {"stage": None, "note": "ink gate: contour cross"}
    if chosen_coarse > INK_FREEZE_TOL:
        return None, {"stage": None, "note": f"ink gate: {chosen_coarse:.3f}"}
    return chosen, chosen_info


def _disjoint_cross(out):
    """True if any two contours that are cleanly separate at BOTH ends of a span
    overlap at its midpoint — pieces travelling through each other (a swapped
    quote-tick pair renders as one blob mid-axis). Counters always overlap
    their body's bbox at the endpoints too, so they are never flagged."""
    positions = sorted(out)
    for a, b in zip(positions, positions[1:], strict=False):
        ca, cb = out[a], out[b]
        n = min(len(ca), len(cb))
        if n < 2:
            continue
        pts_a = [_contour_pts(c) for c in ca[:n]]
        pts_b = [_contour_pts(c) for c in cb[:n]]
        boxes_a = [_pts_bbox(p) for p in pts_a]
        boxes_b = [_pts_bbox(p) for p in pts_b]
        boxes_m = []
        for pa, pb in zip(pts_a, pts_b, strict=False):
            if len(pa) != len(pb):
                boxes_m.append(None)
                continue
            mid = [((p[0] + q[0]) / 2, (p[1] + q[1]) / 2) for p, q in zip(pa, pb, strict=False)]
            boxes_m.append(_pts_bbox(mid))
        for i in range(n):
            for j in range(i + 1, n):
                if boxes_m[i] is None or boxes_m[j] is None:
                    continue
                if (
                    _boxes_overlap(boxes_m[i], boxes_m[j], margin=-2.0)
                    and not _boxes_overlap(boxes_a[i], boxes_a[j], margin=1.0)
                    and not _boxes_overlap(boxes_b[i], boxes_b[j], margin=1.0)
                ):
                    # bbox overlap alone is too coarse: an accent legitimately
                    # closing its vertical gap to the letter (udieresis at heavy
                    # weights) trips it without the pieces ever touching.
                    # Confirm with actual ink: rasterize both mid contours on a
                    # shared grid and require real shared pixels.
                    mid_i = [
                        ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
                        for p, q in zip(pts_a[i], pts_b[i], strict=False)
                    ]
                    mid_j = [
                        ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
                        for p, q in zip(pts_a[j], pts_b[j], strict=False)
                    ]
                    bbox = (
                        min(boxes_m[i][0], boxes_m[j][0]),
                        min(boxes_m[i][1], boxes_m[j][1]),
                        max(boxes_m[i][2], boxes_m[j][2]),
                        max(boxes_m[i][3], boxes_m[j][3]),
                    )
                    gi = _rasterize([mid_i], bbox)
                    gj = _rasterize([mid_j], bbox)
                    if sum((ri & rj).bit_count() for ri, rj in zip(gi, gj, strict=False)) >= 3:
                        return True
    return False


def _pts_bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _boxes_overlap(a, b, margin=0.0):
    """Axis-aligned overlap test; positive margin inflates the boxes (detects
    near-touching), negative margin requires real interpenetration."""
    return (
        a[0] - margin < b[2]
        and b[0] - margin < a[2]
        and a[1] - margin < b[3]
        and b[1] - margin < a[3]
    )


def _ink_defect(out, blur):
    """Worst-case mid-axis ink defect ratio across adjacent master spans.

    For each span, rasterize both endpoint masters (nonzero winding) on a shared
    bbox grid, then rasterize the point-lerp at several interior t. Defective
    pixels are ink present in the (blur-eroded) intersection of both endpoints
    but absent from the (blur-dilated) midpoint — a feature vanishing mid-axis —
    plus midpoint ink beyond the (blur-dilated) union — a fold poking out.
    Returned as a fraction of the endpoints' shared ink."""
    positions = sorted(out)
    worst = 0.0
    for a, b in zip(positions, positions[1:], strict=False):
        rings_a = [_contour_pts(c) for c in out[a]]
        rings_b = [_contour_pts(c) for c in out[b]]
        xs = [p[0] for r in rings_a + rings_b for p in r]
        ys = [p[1] for r in rings_a + rings_b for p in r]
        if not xs:
            continue
        bbox = (min(xs), min(ys), max(xs), max(ys))
        ga = _rasterize(rings_a, bbox)
        gb = _rasterize(rings_b, bbox)
        inter = [ra & rb for ra, rb in zip(ga, gb, strict=False)]
        union = [ra | rb for ra, rb in zip(ga, gb, strict=False)]
        union_count = sum(row.bit_count() for row in union)
        for _ in range(blur):
            inter = _erode(inter)
            union = _dilate(union)
        # thin strokes can erode the endpoints' shared ink to almost nothing,
        # which would let a few noise pixels explode the ratio — floor the
        # denominator at a fraction of the (pre-blur) union ink instead.
        denom = max(sum(row.bit_count() for row in inter), union_count // 10, 1)
        for t in (0.25, 0.5, 0.75):
            mid_rings = [
                [
                    (p[0] * (1 - t) + q[0] * t, p[1] * (1 - t) + q[1] * t)
                    for p, q in zip(ra, rb, strict=False)
                ]
                for ra, rb in zip(rings_a, rings_b, strict=False)
                if len(ra) == len(rb)
            ]
            gm = _rasterize(mid_rings, bbox)
            gm_d = list(gm)
            for _ in range(blur):
                gm_d = _dilate(gm_d)
            lost = sum((i & ~m).bit_count() for i, m in zip(inter, gm_d, strict=False))
            gained = sum((m & ~u).bit_count() for m, u in zip(gm, union, strict=False))
            ratio = (lost + gained) / denom
            if ratio > worst:
                worst = ratio
    return worst


_INK_MASK = (1 << INK_RES) - 1


def _rasterize(rings, bbox):
    """Nonzero-winding scanline raster of point rings onto an INK_RES grid.
    Each row is an int bitmask (bit c set = ink at column c)."""
    x0, y0, x1, y1 = bbox
    s = (INK_RES - 2) / (max(x1 - x0, y1 - y0) or 1.0)
    rows = [0] * INK_RES
    for row in range(INK_RES):
        yy = y0 + (row + 0.5) / s
        crossings = []
        for ring in rings:
            n = len(ring)
            for i in range(n):
                ax, ay = ring[i]
                bx, by = ring[(i + 1) % n]
                if (ay <= yy < by) or (by <= yy < ay):
                    t = (yy - ay) / (by - ay)
                    crossings.append((ax + (bx - ax) * t, 1 if by > ay else -1))
        crossings.sort()
        wind = 0
        prev = 0.0
        bits = 0
        for x, w in crossings:
            if wind != 0:
                c0 = max(0, int((prev - x0) * s))
                c1 = min(INK_RES - 1, int((x - x0) * s))
                if c1 >= c0:
                    bits |= ((1 << (c1 - c0 + 1)) - 1) << c0
            wind += w
            prev = x
        rows[row] = bits
    return rows


def _erode(rows):
    n = len(rows)
    out = [0] * n
    for r in range(1, n - 1):
        bits = rows[r]
        out[r] = bits & (bits >> 1) & (bits << 1) & rows[r - 1] & rows[r + 1] & _INK_MASK
    return out


def _dilate(rows):
    n = len(rows)
    out = [0] * n
    for r in range(n):
        bits = rows[r]
        if r > 0:
            bits |= rows[r - 1]
        if r < n - 1:
            bits |= rows[r + 1]
        out[r] = (bits | (bits >> 1) | (bits << 1)) & _INK_MASK
    return out


def _reconstruct_base(outlines_by_pos, reference_pos=400):
    if _already_compatible(outlines_by_pos) and _starts_aligned(outlines_by_pos):
        # normalise contour order first — donor order can flip across weights and
        # still pass signature(), then interpolate to the wrong contour (B).
        ordered = _order_normalize(outlines_by_pos, reference_pos)
        if (
            ordered is not None
            and _already_compatible(ordered)
            and _starts_aligned(ordered)
            and _cu2qu_safe(ordered)
            and _interp_ok(ordered)
            and not _quality_offenders(ordered, outlines_by_pos)
        ):
            return ordered, {"stage": "compatible", "note": ""}
        # else fall through to full reconstruction

    # Counter-closing glyphs ($ ¢ etc.): their contour count drops at heavy
    # weights because the COUNTERS (negative-area holes) fill in. Splitting into
    # body + counter families, synthesising the closed counters, and
    # reconstructing each family independently preserves the shape far better
    # than bridging — try it first (gated on quality below).
    cc = _counter_closing(outlines_by_pos, reference_pos)
    if (
        cc is not None
        and _struct_ok(cc)
        and _cu2qu_safe(cc)
        and not _quality_offenders(cc, outlines_by_pos)
        and _interp_ok(cc)
    ):
        return cc, {"stage": "reconstructed", "note": "counter-closing"}

    # each variant is (outlines, reference_pos, tag)
    variants = [(outlines_by_pos, reference_pos, "")]
    counts = {len(c) for c in outlines_by_pos.values()}
    if len(counts) > 1:
        unioned = {pos: union_overlaps(c) for pos, c in outlines_by_pos.items()}
        if all(u is not None for u in unioned.values()):
            variants.append((unioned, reference_pos, "union"))
        # merge-to-min: light weights of $ / ¢ / r.ss03 carry extra disjoint
        # contours (bar stubs / a single-weight stray) that join the body at
        # other weights. Bridge each master's contours down to the global-min
        # count so every master shares one topology, then reconstruct. Anchor the
        # reference on a master that NATIVELY has the min count (clean) — not a
        # bridged one, whose zero-width bridges would pollute every master.
        # split-to-max first: when both directions can equalise the topology, a
        # cut that liberates REAL geometry (K's leg, p's bowl) beats a synthetic
        # zero-width bridge whose placement is a guess.
        target_max = max(counts)
        native_max = [p for p, c in outlines_by_pos.items() if len(c) == target_max]
        sref = min(native_max, key=lambda p: abs(p - reference_pos))
        template = outlines_by_pos[sref]
        split = {pos: _split_to_n(c, template) for pos, c in outlines_by_pos.items()}
        if all(s is not None for s in split.values()):
            variants.append((split, sref, "split-to-max"))
        target = min(counts)
        native = [p for p, c in outlines_by_pos.items() if len(c) == target]
        mref = min(native, key=lambda p: abs(p - reference_pos)) if native else reference_pos
        merged_seen = set()
        for pick in range(7):
            merged = {pos: _to_n_contours(c, target, pick) for pos, c in outlines_by_pos.items()}
            if any(m is None for m in merged.values()):
                continue

            # different picks can land on the same bridge — dedup on a light
            # ORDER-sensitive fingerprint (all picks share the same point
            # multiset and start point; only the splice position, and therefore
            # the point sequence, differs)
            def _fp_contour(con):
                pts = _contour_pts(con)
                return (len(pts), pts[len(pts) // 3], pts[(2 * len(pts)) // 3])

            fp = tuple(
                (pos, tuple(_fp_contour(con) for con in cons))
                for pos, cons in sorted(merged.items())
            )
            if fp in merged_seen:
                continue
            merged_seen.add(fp)
            variants.append((merged, mref, "merge-to-min" if pick == 0 else f"merge-to-min@{pick}"))

    last = {"stage": None, "note": "no angle worked"}
    for variant, vref, tag in variants:
        for angle in CORNER_ANGLE_SWEEP:
            out, info = _reconstruct_at(variant, vref, angle)
            if out is not None:
                # quality gate: the reconstructed outline must preserve each
                # master's ink area (a collapsed S-counter or bad bridge shows up
                # as a big area swing). If it degrades, reject and try the next
                # variant; if none pass, the caller freezes the glyph (clean,
                # unvarying) instead of shipping a deformed one.
                bad = _quality_offenders(out, outlines_by_pos)
                if bad:
                    last = {"stage": None, "note": f"quality gate: {bad}"}
                    continue
                # also require clean INTERPOLATION between masters: the area at the
                # midpoint of each adjacent pair must be close to the mean of the
                # two (a collapse from mismatched point correspondence spikes it).
                if not _interp_ok(out):
                    last = {"stage": None, "note": "interp gate: midpoint collapse"}
                    continue
                # cu2qu gate: corresponding segments must share an identical
                # (op, point-count) structure across masters, or fontmake's
                # interpolatable cu2qu rejects the glyph and build.py freezes it.
                # Fall through (to a denser angle, then the uniform all-line
                # resample) rather than ship a curve set cu2qu can't reconcile.
                if not _cu2qu_safe(out):
                    last = {"stage": None, "note": "cu2qu gate: segment regroup"}
                    continue
                tags = []
                if tag:
                    tags.append(tag)
                if angle != CORNER_ANGLE_SWEEP[0]:
                    tags.append(f"angle={round(math.degrees(angle))}")
                if tags:
                    info["note"] = "+".join(tags)
                return out, info
            last = info
    # Last resort before giving up: UNIFORM arc-length resampling — ignore corner
    # anchors and place dense, evenly-spaced points from a canonical (topmost)
    # start on every contour, then cyclically rotate each master's ring to the
    # offset that best matches the reference (least-squares). The rotation step
    # matters beyond round contours: any glyph whose topmost node DRIFTS across
    # masters (m's three near-level arch tops, a 2-node vs 5-node oval) otherwise
    # interpolates node->wrong-node and goes lumpy at mid-weights, while a glyph
    # whose anchoring already agrees gets rotation 0 and is unchanged. Plain
    # topmost-anchored uniform stays as the final fallback for shapes where the
    # least-squares rotation itself mis-locks. Last resorts because resampling
    # rounds corners very slightly.
    # Run the uniform fallbacks over every topology variant, not just the donor
    # outlines: a split-to-max body (p's cut bowl) can carry corner counts too
    # different for the corner paths, yet resample perfectly uniformly. With
    # several bridge placements in play the first passing candidate isn't
    # necessarily the right one — keep the passer whose mid-axis ink defect is
    # lowest.
    best_uni = None  # (ink score, out, note)
    for v_outlines, vref, tag in variants:
        for fn, note in ((_uniform_aligned, "uniform-aligned"), (_uniform, "uniform")):
            uni = fn(v_outlines, vref)
            if (
                uni is not None
                and _struct_ok(uni)
                and _cu2qu_safe(uni)
                and not _quality_offenders(uni, outlines_by_pos)
                and _interp_ok(uni)
            ):
                ink = _ink_defect(uni, blur=2)
                full = f"{note}+{tag}" if tag else note
                if best_uni is None or ink < best_uni[0] - 1e-9:
                    best_uni = (ink, uni, full)
                break  # aligned passed for this variant; skip its plain uniform
    if best_uni is not None:
        return best_uni[1], {"stage": "reconstructed", "note": best_uni[2]}
    return None, last


def _line_pts(contour):
    """Ordered point list of an all-line (moveTo + lineTo*) contour."""
    return [p[0] for op, p in contour if op in ("moveTo", "lineTo")]


def _best_rotation(pts, ref):
    """Cyclic offset r minimising sum |pts[(i+r)%n] - ref[i]|^2."""
    n = len(pts)
    best_r, best_cost = 0, None
    for r in range(n):
        cost = sum(
            (pts[(i + r) % n][0] - ref[i][0]) ** 2 + (pts[(i + r) % n][1] - ref[i][1]) ** 2
            for i in range(n)
        )
        if best_cost is None or cost < best_cost:
            best_cost, best_r = cost, r
    return best_r


def _uniform_aligned(outlines_by_pos, reference_pos):
    uni = _uniform(outlines_by_pos, reference_pos)
    if uni is None:
        return None
    positions = sorted(uni)
    ref = reference_pos if reference_pos in uni else positions[len(positions) // 2]
    ncon = len(uni[ref])
    out = {p: [] for p in positions}
    for ci in range(ncon):
        ref_pts = _line_pts(uni[ref][ci])
        for p in positions:
            pts = _line_pts(uni[p][ci])
            if len(pts) != len(ref_pts):
                return None
            if p == ref:
                out[p].append(_as_line_contour(pts))
                continue
            r = _best_rotation(pts, ref_pts)
            out[p].append(_as_line_contour(pts[r:] + pts[:r]))
    return out


def _uniform(outlines_by_pos, reference_pos):
    positions = sorted(outlines_by_pos)
    if len({len(outlines_by_pos[p]) for p in positions}) != 1:
        return None
    ref = reference_pos if reference_pos in outlines_by_pos else positions[len(positions) // 2]
    ncon = len(outlines_by_pos[positions[0]])
    out = {p: [] for p in positions}
    for ci in range(ncon):
        # force the smooth path: zero corner flags so _resample_contour_set
        # anchors on the topmost point and resamples the whole ring uniformly.
        per = {}
        for p in positions:
            nodes, seg, _ = to_ring(outlines_by_pos[p][ci])
            per[p] = (nodes, seg, [False] * len(nodes))
        rebuilt = _resample_contour_set(per, positions, ref)
        if rebuilt is None:
            return None
        for p in positions:
            out[p].append(rebuilt[p])
    return out


# Max |reconstructed/donor - 1| allowed at any master. The base path lands <6%;
# a few counter-closing glyphs (cent, iogonek) land 7-10% from the all-line
# resampling + synthetic counter. Genuinely-deformed reconstructions are >20%
# (with nothing in the 10-20% band), so 10% admits the good ones and freezes the
# deformed ones clean.
QUALITY_AREA_TOL = 0.10


def _glyph_area(contours):
    """Containment-aware ink area: a contour nested at odd depth (a counter)
    subtracts, everything else adds. Summing |area| per contour would make the
    same shape measure differently depending on topology — an open-bowl p drawn
    as ONE ring vs its split body+counter form — and summing SIGNED areas
    trusts drawn winding, which donors don't keep consistent (Neuton's
    ExtraBold winds the grave accent opposite to its lighter masters; a
    disjoint piece renders identically either way under nonzero fill, so the
    measure must not care)."""
    rings = [to_ring(con)[0] for con in contours]
    boxes = [_pts_bbox(r) if len(r) >= 3 else None for r in rings]
    total = 0.0
    for i, ring in enumerate(rings):
        if len(ring) < 3:
            continue
        a = abs(_signed_area(ring))
        # nested = wholly inside another ring (bbox containment + centroid
        # test). A single boundary-point probe is unstable for ATTACHED pieces
        # (an ogonek overlapping its A): donor and reconstruction would
        # classify differently and the quality ratio would lie.
        c = _centroid(ring)
        depth = 0
        for j, other in enumerate(rings):
            if j == i or len(other) < 3 or boxes[j] is None or boxes[i] is None:
                continue
            bi, bj = boxes[i], boxes[j]
            if (
                bi[0] >= bj[0] - 1
                and bi[1] >= bj[1] - 1
                and bi[2] <= bj[2] + 1
                and bi[3] <= bj[3] + 1
                and _point_in_ring(c, other)
            ):
                depth += 1
        total += a if depth % 2 == 0 else -a
    return abs(total)


def _point_in_ring(pt, ring):
    """Even-odd crossing test: is pt inside the closed polyline ring?"""
    x, y = pt
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 <= y < y2) or (y2 <= y < y1):
            if x < x1 + (y - y1) / (y2 - y1) * (x2 - x1):
                inside = not inside
    return inside


def _quality_offenders(out, donor):
    """Per-master ink comparison between reconstruction and donor, measured by
    RASTERIZING both with nonzero winding on a shared grid — exactly what the
    renderer does. Analytic per-contour area needs to classify which contours
    are counters, and no classification (drawn winding, containment heuristics)
    survives donors with flipped windings or attached/overlapping pieces
    (Neuton's opposite-wound grave, Devanagari conjunct parts); pixel counts
    just match reality, and quantization cancels because both sides share the
    same bbox and resolution."""
    bad = {}
    for pos, contours in out.items():
        # to_ring, not _contour_pts: donors carry curves, and rasterizing their
        # control polygon instead of sampled curve points would skew the ratio
        d_rings = [to_ring(c)[0] for c in donor[pos]]
        o_rings = [to_ring(c)[0] for c in contours]
        xs = [p[0] for r in d_rings + o_rings for p in r]
        ys = [p[1] for r in d_rings + o_rings for p in r]
        if not xs:
            continue
        bbox = (min(xs), min(ys), max(xs), max(ys))
        da = sum(row.bit_count() for row in _rasterize(d_rings, bbox))
        if da <= 0:
            continue
        ra = sum(row.bit_count() for row in _rasterize(o_rings, bbox))
        dev = abs(ra / da - 1.0)
        if dev > QUALITY_AREA_TOL:
            bad[pos] = round(dev, 2)
    return bad or None


def _struct_ok(out):
    """All masters share contour count and per-contour point count."""
    cs = {tuple(len(c) for c in contours) for contours in out.values()}
    return len(cs) == 1


def _cu2qu_safe(out):
    """Every master shares an identical per-contour SEGMENT structure — the same
    sequence of (op, point-count).

    ``signature()`` compares only op TYPES and ``_struct_ok`` only per-contour
    TOTAL point counts, so a glyph whose off-curve points regroup across masters
    (e.g. e's ``Q3 Q3 Q4`` vs ``Q3 Q3 Q3`` — identical total) passes both yet is
    rejected by fontmake's interpolatable cu2qu, which then makes build.py freeze
    it to one weight. Requiring the finer structure forces such glyphs through the
    uniform all-line resample instead, which is cu2qu-safe by construction."""
    shapes = {
        tuple(tuple((op, len(pts)) for op, pts in con) for con in contours)
        for contours in out.values()
    }
    return len(shapes) == 1


def _ring_perimeter(pts):
    n = len(pts)
    return sum(_dist(pts[i], pts[(i + 1) % n]) for i in range(n))


def _contour_pts(con):
    """On/off-curve point list of a (op,[pts]) contour, in order. All-off-curve
    TrueType contours carry an implied-on-curve ``None`` in their qCurveTo (and
    no moveTo) — expand them first so every entry is a real point."""
    pts = []
    for op, p in _implied_oncurve_contour(con):
        pts.extend(p)
    return pts


def _interp_ok(out, tol=0.18, perim_tol=0.83):
    """A point-compatible reconstruction can still interpolate badly if point
    correspondence across masters is wrong (e.g. k's diagonal): the masters look
    fine but the in-between weights collapse. Lerp the points of each adjacent
    master pair at t=0.5 and require the midpoint ink area to stay near the mean
    of the two endpoints — a collapse (points crossing) spikes it away.

    Area alone misses a TWIST that conserves ink (Taviraj K's counter-closing
    bridge): mis-corresponded points fold the midpoint ring onto itself without
    much net area change. The fold shows in the midpoint PERIMETER, which by the
    triangle inequality can only shrink relative to the mean of the endpoints —
    a clean interpolation stays near 1.0, a fold drops sharply. Calibrated over
    the showcase families: visually-broken twists sit <= ~0.82, healthy glyphs
    >= ~0.85, so 0.83 freezes the egregious ones and spares the rest."""
    positions = sorted(out)
    for a, b in zip(positions, positions[1:], strict=False):
        ca, cb = out[a], out[b]
        area_a = _glyph_area(ca)
        area_b = _glyph_area(cb)
        mean = (area_a + area_b) / 2
        if mean <= 0:
            continue
        mid = []
        for con_a, con_b in zip(ca, cb, strict=False):
            pa, pb = _contour_pts(con_a), _contour_pts(con_b)
            if len(pa) != len(pb):
                return False
            midpts = [
                ((pa[i][0] + pb[i][0]) / 2, (pa[i][1] + pb[i][1]) / 2) for i in range(len(pa))
            ]
            if len(midpts) >= 3:
                pm = _ring_perimeter(midpts)
                pmean = (_ring_perimeter(pa) + _ring_perimeter(pb)) / 2
                # ignore tiny contours (accent dots): a few units of rounding
                # would dominate the ratio
                if pmean > 500 and pm / pmean < perim_tol:
                    return False
            con = (
                [("moveTo", [midpts[0]])]
                + [("lineTo", [p]) for p in midpts[1:]]
                + [("closePath", [])]
            )
            mid.append(con)
        if abs(_glyph_area(mid) / mean - 1.0) > tol:
            return False
        # per-contour safety net: a single contour CROSSING itself (e.g. the %
        # slash twisting into a bowtie) barely moves the total area but collapses
        # its own to near-zero. Only flag a severe collapse (< 45% of the mean) so
        # counters that legitimately shrink with weight (8, 0) aren't false-failed.
        for con_a, con_b, con_m in zip(ca, cb, mid, strict=False):
            cm = (abs(_signed_area(to_ring(con_a)[0])) + abs(_signed_area(to_ring(con_b)[0]))) / 2
            if cm > 1500 and _glyph_area([con_m]) / cm < 0.45:
                return False
    return True


def _reconstruct_single_family(family, positions, ref):
    """Reconstruct ONE contour (per master) to a shared structure: anchor on each
    master's corners when counts agree. When corner counts DISAGREE, prefer
    UNIFORM arc-length correspondence (zero corner flags -> topmost anchor, full
    ring resample) over reference projection: projection mis-corresponds the
    bar-through-bowl runs and self-intersects ($ body sliver, cent body), whereas
    uniform arc-length interpolates cleanly. Fall back to projection only if
    uniform fails to produce a result."""
    per = {pos: to_ring(family[pos]) for pos in positions}
    ccounts = {pos: sum(per[pos][2]) for pos in positions}
    if len(set(ccounts.values())) == 1:
        return _resample_contour_set(per, positions, ref)
    uni_per = {p: (per[p][0], per[p][1], [False] * len(per[p][0])) for p in positions}
    uni = _resample_contour_set(uni_per, positions, ref)
    if uni is not None:
        return uni
    return _project_contour_set(per, positions, ref)


COUNTER_TAPER = 0.45  # geometric area shrink per extra missing-master step
MIN_COUNTER_FRAC = 5e-4  # synth counter area floor as a fraction of the body


def _map_bbox_point(pt, from_ring, to_ring_pts):
    """Map a point through the affine transform between two rings' bboxes."""
    fx = [p[0] for p in from_ring]
    fy = [p[1] for p in from_ring]
    tx = [p[0] for p in to_ring_pts]
    ty = [p[1] for p in to_ring_pts]
    fw = (max(fx) - min(fx)) or 1.0
    fh = (max(fy) - min(fy)) or 1.0
    return (
        min(tx) + (pt[0] - min(fx)) / fw * ((max(tx) - min(tx)) or 1.0),
        min(ty) + (pt[1] - min(fy)) / fh * ((max(ty) - min(ty)) or 1.0),
    )


def _synth_counter(template_ring, scale, center):
    """A tiny counter ring: shrink a template counter toward `center` by `scale`,
    keeping its shape/winding so it stays point-compatible with the real ones."""
    tc = _centroid(template_ring)
    return [
        (center[0] + (x - tc[0]) * scale, center[1] + (y - tc[1]) * scale)
        for (x, y) in template_ring
    ]


def _counter_area_target(present_pairs):
    """Area to aim for at the first missing master, extrapolating the donor
    counter-area slope of the last two present masters; never below half the last
    open counter (so it tapers smoothly rather than collapsing)."""
    (p0, a0), (p1, a1) = present_pairs[-2], present_pairs[-1]
    slope = (a1 - a0) / (p1 - p0) if p1 != p0 else 0.0
    return max(a1 + slope * (p1 - p0), a1 * 0.5)


def _order_normalize(outlines_by_pos, reference_pos=400):
    """Reorder every master's contours to match the reference by centroid+area
    nearest match. Donor contour order can flip across weights (e.g. B's two
    counters swap at ExtraBlack) — that passes signature() but interpolates
    counter->wrong-counter and collapses between masters. Returns reordered
    {pos: contours}, or None if contour counts differ."""
    positions = sorted(outlines_by_pos)
    ref = reference_pos if reference_pos in outlines_by_pos else positions[len(positions) // 2]
    rings = {p: [to_ring(c) for c in outlines_by_pos[p]] for p in positions}
    if any(len(rings[p]) != len(rings[ref]) for p in positions):
        return None
    out = {}
    for p in positions:
        order = _match_order(rings[p], rings[ref])
        if order is None:
            return None
        out[p] = [outlines_by_pos[p][i] for i in order]
    return out


def _counter_closing(outlines_by_pos, reference_pos):
    """Reconstruct a glyph whose contour COUNT varies across weights because a
    piece (a counter that fills in, a bar stub or accent that merges into the
    body) appears at some weights and not others. Treat every contour as a slot;
    match each master's contours to slots by centroid WITHIN the same winding
    sign (a counter never maps to a bar slot); synthesise a slot that's missing at
    a weight by shrinking its template toward where it merged; reconstruct each
    slot family independently; recombine. Returns {pos: contours} or None if it
    isn't this pattern (or a master has more contours than the slot template).
    Generalised from the AI dollar probe (ai_dollar_probe.py)."""
    positions = sorted(outlines_by_pos)
    parts = {}  # pos -> list of (contour, ring, centroid, sign)
    for pos in positions:
        entries = []
        for con in outlines_by_pos[pos]:
            ring = to_ring(con)[0]
            if len(ring) < 3:
                return None
            sign = 1 if _signed_area(ring) >= 0 else -1
            entries.append((con, ring, _centroid(ring), sign))
        # normalise winding per master so the dominant (largest) contour is
        # always +1: donors can flip overall orientation between masters
        # (Neuton's light masters wind outers the other way), and slot matching
        # by RAW sign would then map a light outline onto the heavy COUNTER slot.
        dom = max(entries, key=lambda e: abs(_signed_area(e[1])))[3]
        entries = [(c, r, ce, s * dom) for c, r, ce, s in entries]
        parts[pos] = entries

    if len({len(parts[p]) for p in positions}) == 1:
        return None  # contour count doesn't vary — not this pattern

    # slots = the contours of the master with the MOST contours (most "open")
    sp = max(positions, key=lambda p: len(parts[p]))
    slots = parts[sp]
    nslot = len(slots)
    lightest = positions[0]

    fams = [dict() for _ in range(nslot)]  # slot -> {pos: (contour, ring, centroid)}
    for pos in positions:
        used = set()
        for entry in parts[pos]:
            cand = [s for s in range(nslot) if slots[s][3] == entry[3] and s not in used]
            if not cand:
                continue  # an extra contour with no matching slot — dropped (gate catches)
            s = min(cand, key=lambda s: _dist(entry[2], slots[s][2]))
            used.add(s)
            fams[s][pos] = (entry[0], entry[1], entry[2])

    # synthesise missing slots by shrinking the NEAREST-present ring toward its
    # OWN centroid (radial correspondence -> no sliver), with the shrink calibrated
    # to the donor area trend so the piece follows the donor's close curve instead
    # of collapsing in one step (which made $ blobby and "lost" the bar at mid
    # weights). Scale = sqrt(area_target/area_nearest) (area ~ scale^2), tapering
    # geometrically to a positive floor.
    body_ref = max(
        (
            abs(_signed_area(fams[s2][p][1]))
            for s2 in range(nslot)
            for p in positions
            if p in fams[s2]
        ),
        default=1.0,
    )
    body_slot = max(range(nslot), key=lambda s2: abs(_signed_area(slots[s2][1])))
    body_sign = slots[body_slot][3]
    for s in range(nslot):
        present = sorted(p for p in positions if p in fams[s])
        if not present:
            return None
        missing = [p for p in positions if p not in fams[s]]
        if not missing:
            continue
        near_pos = min(present, key=lambda p: min(abs(p - m) for m in missing))
        near_ring = fams[s][near_pos][1]
        near_area = abs(_signed_area(near_ring)) or 1.0
        near_c = _centroid(near_ring)
        if slots[s][3] != body_sign:
            # A HOLE that only exists at some weights (p/q/thorn's bowl counter
            # appears at ExtraBold). Unlike a bar stub, a zero-area hole is
            # invisible, so the missing masters get a NEAR-ZERO synthetic ring
            # and the hole grows from nothing across the span — the master
            # renders exactly like its donor (no phantom counter, which the
            # quality gate rightly rejected at 20-30% area deviation). Anchor it
            # inside each master's own body by mapping the template centroid
            # through the body rings' bboxes, so the emerging hole stays inside
            # the lighter, narrower bowl.
            for mp in missing:
                center = near_c
                if mp in fams[body_slot] and near_pos in fams[body_slot]:
                    center = _map_bbox_point(
                        near_c, fams[body_slot][near_pos][1], fams[body_slot][mp][1]
                    )
                ring = _synth_counter(near_ring, 0.02, near_c)
                ring = [(p[0] - near_c[0] + center[0], p[1] - near_c[1] + center[1]) for p in ring]
                fams[s][mp] = (_as_line_contour(ring), ring, center)
            continue
        pairs = [(p, abs(_signed_area(fams[s][p][1]))) for p in present]
        heaviest = present[-1]
        near_ring = fams[s][heaviest][1]
        near_area = abs(_signed_area(near_ring)) or 1.0
        target = _counter_area_target(pairs) if len(pairs) >= 2 else near_area * 0.5
        first_scale = min(math.sqrt(max(target, 1.0) / near_area), 0.95)
        floor_scale = math.sqrt(max(MIN_COUNTER_FRAC * body_ref, 1.0) / near_area)
        near_c = _centroid(near_ring)
        for i, mp in enumerate(sorted(missing)):
            scale = max(first_scale * (COUNTER_TAPER**i), floor_scale)
            ring = _synth_counter(near_ring, scale, near_c)
            fams[s][mp] = (_as_line_contour(ring), ring, near_c)

    # reconstruct each slot family to a shared structure (light ref keeps the
    # open-piece corners), then recombine in slot order
    fam_outs = []
    for s in range(nslot):
        fam = {pos: fams[s][pos][0] for pos in positions}
        out = _reconstruct_single_family(fam, positions, lightest)
        if out is None:
            return None
        fam_outs.append(out)

    # family resampling aligns winding WITHIN each family to its own reference,
    # which can leave a hole slot wound the same way as the body — under
    # nonzero winding that renders with no hole at all. Re-orient hole families
    # against the body's output winding (reversing every master together keeps
    # the family's point correspondence intact).
    def _out_sign(out):
        return 1 if _signed_area(to_ring(out[lightest])[0]) >= 0 else -1

    body_out_sign = _out_sign(fam_outs[body_slot])
    for s in range(nslot):
        if slots[s][3] != body_sign and _out_sign(fam_outs[s]) == body_out_sign:
            fam_outs[s] = {
                pos: _as_line_contour(list(reversed(_contour_pts(con))))
                for pos, con in fam_outs[s].items()
            }
    combined = {pos: [] for pos in positions}
    for s in range(nslot):
        for pos in positions:
            combined[pos].append(fam_outs[s][pos])
    return combined


# ---------------------------------------------------------------------------
# open-bar: design change — $ / ¢ keep the bar's TOP and BOTTOM stubs (protruding
# above/below the S/c) but drop the part that crosses through the MIDDLE. Body =
# the donor bare letter (S/c, one clean positive contour at every weight); the bar
# becomes two short overlapping nubs (keep-overlaps unions them onto the letter).
# ---------------------------------------------------------------------------

# Which glyphs use this strategy, and with which bare-letter donor/anchor, is
# declared per-project in stv.config.json (glyphs.strategies["<name>"] with
# strategy "open_bar" and params letter/anchor).
# how far each nub reaches INTO the letter's stroke (font units) so it joins the
# S/c spine without leaving a gap; and the minimum stub protrusion beyond the
# letter (the donor ¢ has no bottom protrusion and the $ top is short, so we make
# the two stubs symmetric at the larger protrusion, floored here).
NUB_OVERLAP = 30
MIN_PROTRUDE = 70


def _largest_positive(contours):
    best = None
    for con in contours:
        ring = to_ring(con)[0]
        if _signed_area(ring) >= 0 and (
            best is None or abs(_signed_area(ring)) > abs(_signed_area(to_ring(best)[0]))
        ):
            best = con
    return best


def _measure_bar(donor_contours):
    """Measure the donor through-bar of $/¢ from the body silhouette: within ~40u
    of the extreme top/bottom only the bar is present, so its x-band there gives
    the bar's top/bottom corners. Returns (bx0,bx1,tx0,tx1,ymin,ymax) where
    ymin/ymax are the bar's (= body's) full vertical extent."""
    ring = to_ring(_largest_positive(donor_contours))[0]
    ymax = max(p[1] for p in ring)
    ymin = min(p[1] for p in ring)
    topb = [p for p in ring if p[1] > ymax - 40]
    botb = [p for p in ring if p[1] < ymin + 40]
    return (
        min(p[0] for p in botb),
        max(p[0] for p in botb),
        min(p[0] for p in topb),
        max(p[0] for p in topb),
        ymin,
        ymax,
    )


def _ink_span_at_x(ring, x):
    """(min_y, max_y) where a vertical line at `x` crosses the ring, or None."""
    ys = []
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        if (x0 <= x < x1) or (x1 <= x < x0):
            ys.append(y0 + (x - x0) / (x1 - x0) * (y1 - y0))
    return (min(ys), max(ys)) if ys else None


def _ink_span_at_y(ring, y):
    """(min_x, max_x) where a horizontal line at `y` crosses the ring, or None."""
    xs = []
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        if (y0 <= y < y1) or (y1 <= y < y0):
            xs.append(x0 + (y - y0) / (y1 - y0) * (x1 - x0))
    return (min(xs), max(xs)) if xs else None


def _bar_nubs(body_contour, bar_geom):
    """Two stubs in the BODY's coordinate space: a TOP stub above the letter and a
    BOTTOM stub below it, each connected to the spine and SYMMETRIC (both protrude
    by the same amount = the larger of the donor's top/bottom protrusions, floored
    by MIN_PROTRUDE — the donor ¢ has no bottom protrusion and the $ top is short).
    Width is taken from the donor bar's top band (the only band that reliably
    isolates the bar, since the bottom band of ¢ is the c's curve). The bar x is
    traced from the body spine at top/bottom, so it sits on the spine and follows
    the italic slant. The through-middle is omitted."""
    ring = to_ring(body_contour)[0]
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    bym, byx = min(ys), max(ys)
    h = byx - bym
    bx0, bx1, tx0, tx1, dymin, dymax = bar_geom
    w = tx1 - tx0  # reliable bar width (top band)
    protrude = max(dymax - byx, bym - dymin, MIN_PROTRUDE)

    def spine_x(y):
        s = _ink_span_at_y(ring, y)
        return (s[0] + s[1]) / 2.0 if s else (min(xs) + max(xs)) / 2.0

    top_sy, bot_sy = byx - 0.08 * h, bym + 0.08 * h
    sxt, sxb = spine_x(top_sy), spine_x(bot_sy)
    slant = (sxt - sxb) / (top_sy - bot_sy) if top_sy != bot_sy else 0.0

    def barx(y):
        return sxb + slant * (y - bot_sy)

    vt = _ink_span_at_x(ring, sxt)
    vb = _ink_span_at_x(ring, sxb)
    shi = vt[1] if vt else byx
    slo = vb[0] if vb else bym
    top_y, bot_y = byx + protrude, bym - protrude
    lo, hi = shi - NUB_OVERLAP, slo + NUB_OVERLAP
    top = [
        (barx(lo) - w / 2, lo),
        (barx(lo) + w / 2, lo),
        (barx(top_y) + w / 2, top_y),
        (barx(top_y) - w / 2, top_y),
    ]
    bot = [
        (barx(bot_y) - w / 2, bot_y),
        (barx(bot_y) + w / 2, bot_y),
        (barx(hi) + w / 2, hi),
        (barx(hi) - w / 2, hi),
    ]
    return [_as_line_contour(p if _signed_area(p) >= 0 else p[::-1]) for p in (top, bot)]


def open_bar(glyph_outlines_by_pos, letter_outlines_by_pos, anchor, reference_pos=400):
    """Build open-bar masters for $/¢: bare-letter body (reconstructed to a shared
    structure) + top & bottom bar nubs (no through-middle). Returns
    {pos: [body, top_nub, bottom_nub]} or None. Caller validates with _struct_ok +
    _interp_ok only (bypasses the donor area gate — intentionally not the donor
    shape)."""
    positions = sorted(glyph_outlines_by_pos)
    ref = reference_pos if reference_pos in positions else positions[len(positions) // 2]
    key = (
        (lambda i, r: (r[i][0], r[i][1])) if anchor == "left" else (lambda i, r: (r[i][1], r[i][0]))
    )
    bar_geom = {}
    letter_by_pos = {}
    for pos in positions:
        body = _largest_positive(letter_outlines_by_pos[pos])
        if body is None:
            return None
        letter_by_pos[pos] = [body]
        bar_geom[pos] = _measure_bar(glyph_outlines_by_pos[pos])

    # Body = the bare letter (S/c). Align it with the SAME reconstruct() aligner
    # the plain S/c glyphs use, so $/¢ interpolate exactly as cleanly as the
    # letters do. The old _resample_contour_set path established correspondence by
    # resampling each master independently, which drifts over the wide 3-master
    # spacing and produced the visible bumps on the S/c curve at mid-weights.
    body_out = None
    rec, _info = reconstruct(letter_by_pos, reference_pos=ref)
    if rec is not None and all(len(rec[pos]) == 1 for pos in positions):
        body_out = {pos: rec[pos][0] for pos in positions}

    if body_out is None:
        # fallback: the original independent resampler (no worse than before)
        per = {}
        for pos in positions:
            ring = to_ring(letter_by_pos[pos][0])[0]
            k = min(range(len(ring)), key=lambda i: key(i, ring))
            ring = ring[k:] + ring[:k]
            per[pos] = (ring, None, [i == 0 for i in range(len(ring))])
        body_out = _resample_contour_set(per, positions, ref)
        if body_out is None:
            return None
    return {pos: [body_out[pos], *_bar_nubs(body_out[pos], bar_geom[pos])] for pos in positions}


def _to_n_contours(contours, target, bridge_pick=0):
    """Bridge a master's contours down to `target` count: repeatedly splice the
    smallest-area contour into its nearest neighbour with a zero-width bridge
    (invisible under keep-overlaps), until `target` remain. Returns polyline
    contours, or None if it can't (target larger than count).

    `bridge_pick` selects the bridge LOCATION for the final splice: 0 is the
    closest point pair, higher values pick successively different spots around
    the spliced ring. Where the bridge lands decides the merged ring's
    correspondence with the other masters (a p bridged through the stem side
    folds against a light master whose bowl opens elsewhere), and the caller
    can't know the right spot a priori — it tries a few and lets the gates and
    the ink score choose."""
    if len(contours) == target:
        return contours
    if len(contours) < target:
        return None
    rings = [to_ring(c)[0] for c in contours]  # dense point rings
    rings = [r for r in rings if len(r) >= 2]
    if len(rings) < target:
        return None
    while len(rings) > target:
        # smallest-area ring merges into its nearest other ring
        si = min(range(len(rings)), key=lambda i: abs(_signed_area(rings[i])))
        small = rings.pop(si)
        sc = _centroid(small)
        ti = min(range(len(rings)), key=lambda i: _dist(sc, _centroid(rings[i])))
        pick = bridge_pick if len(rings) == target else 0
        bridged = _bridge_rings(rings[ti], small, pick)
        if bridged is None:
            return None
        rings[ti] = bridged
    return [_as_line_contour(r) for r in rings]


def _bridge_rings(a, b, pick=0):
    """Splice ring b into ring a, forming one ring. `pick` 0 uses the closest
    point pair; higher values use the closest pair anchored at successively
    different spots around ring b (its points bucketed into arcs), giving the
    caller distinct bridge locations to try. Returns None when `pick` exceeds
    the distinct locations available."""
    nb = len(b)
    if pick == 0:
        buckets = [range(nb)]
    else:
        k = 6  # distinct arcs around the spliced ring
        if pick > k:
            return None
        step = max(1, nb // k)
        buckets = [range((pick - 1) * step, min(pick * step, nb))]
    best = (0, 0, float("inf"))
    for j_range in buckets:
        for j in j_range:
            pb = b[j]
            for i, pa in enumerate(a):
                d = _dist(pa, pb)
                if d < best[2]:
                    best = (i, j, d)
    ia, ib, _ = best
    if best[2] == float("inf"):
        return None
    return a[: ia + 1] + b[ib:] + b[: ib + 1] + a[ia:]


# A neck must be narrower than this fraction of the ring's bbox diagonal to cut
# there. Generous on purpose: an ink-trap channel (p/q's bowl) is hairline, but
# K's leg-stem contact is a real junction; bad cuts are vetoed by the quality
# gates and the ink tournament downstream.
NECK_MAX_FRAC = 0.16
# Each side of the cut must carry at least this fraction of the ring's points,
# so serif clefts and corner notches (tiny arcs) are never treated as necks.
NECK_MIN_ARC = 0.15


def _split_to_n(contours, target_contours):
    """Split a master's contours UP to the target master's count by cutting one
    ring across a neck: the inverse of _to_n_contours, for glyphs whose piece is
    only attached at light weights (p/q/thorn's bowl reaches the stem through a
    hairline channel, K's leg touches the stem). The cut CANNOT be chosen by
    narrowness alone — in a thin master every stroke is a "neck", and cutting
    across a stem slices the glyph in half. Instead the TARGET master (which
    natively draws the pieces separately) defines what a correct split looks
    like: candidate necks are scored by how well the resulting pieces' winding
    signs and area fractions match the target's contours (an aperture cut yields
    body + opposite-wound counter, a junction cut two same-wound pieces), and
    the best-matching cut wins. Returns polyline contours, or None."""
    target = len(target_contours)
    if len(contours) == target:
        return contours
    if len(contours) != target - 1:
        return None  # only a single-split difference is supported
    rings = [to_ring(c)[0] for c in contours]
    if any(len(r) < 8 for r in rings):
        return None
    t_sig = _area_signature([to_ring(c)[0] for c in target_contours])
    best = None  # (score, ring index, i, j)
    for ri, ring in enumerate(rings):
        for width, i, j in _neck_candidates(ring):
            pieces = [ring[i : j + 1], ring[j:] + ring[: i + 1]]
            if any(len(p) < 3 for p in pieces):
                continue
            cand = rings[:ri] + pieces + rings[ri + 1 :]
            score = _signature_distance(_area_signature(cand), t_sig)
            if score is not None and (best is None or score < best[0]):
                best = (score, ri, i, j)
    if best is None:
        return None
    _, ri, i, j = best
    ring = rings.pop(ri)
    rings.insert(ri, ring[i : j + 1])
    rings.insert(ri + 1, ring[j:] + ring[: i + 1])
    return [_as_line_contour(r) for r in rings]


def _area_signature(rings):
    """Sorted (sign, |area| fraction) per ring; the glyph's topology fingerprint."""
    areas = [_signed_area(r) for r in rings]
    total = sum(abs(a) for a in areas) or 1.0
    return sorted(((1 if a >= 0 else -1), abs(a) / total) for a in areas)


def _signature_distance(sig, target_sig):
    """Distance between two area signatures, or None if the winding-sign
    patterns differ (in both global polarities)."""
    if len(sig) != len(target_sig):
        return None
    for flip in (1, -1):
        flipped = sorted((s * flip, f) for s, f in sig)
        if [s for s, _ in flipped] == [s for s, _ in target_sig]:
            return sum(abs(f1 - f2) for (_, f1), (_, f2) in zip(flipped, target_sig, strict=False))
    return None


def _neck_candidates(ring):
    """(width, i, j) neck candidates of a dense ring: pairs whose connecting cut
    is short relative to the ring's size while BOTH arcs stay substantial,
    deduplicated to local minima, narrowest first. NOT capped: in a thin master
    every stroke is narrow, so stroke cuts flood the narrow end of the list —
    the aperture/junction cut the caller wants is often WIDER and only survives
    on its piece-signature score, which is why every deduped candidate stays."""
    n = len(ring)
    min_arc = max(3, int(n * NECK_MIN_ARC))
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    limit = diag * NECK_MAX_FRAC
    cands = []
    for i in range(n):
        for j in range(i + min_arc, n):
            if n - j + i < min_arc:  # arc that wraps past index 0
                continue
            d = _dist(ring[i], ring[j])
            if d <= limit:
                cands.append((d, i, j))
    cands.sort()
    kept = []
    for d, i, j in cands:
        # skip candidates whose endpoints sit next to an already-kept narrower
        # cut — they are the same neck a few samples over
        near = int(n * 0.04) + 1
        if any(
            min(abs(i - ki), n - abs(i - ki)) <= near and min(abs(j - kj), n - abs(j - kj)) <= near
            for _, ki, kj in kept
        ):
            continue
        kept.append((d, i, j))
    return kept


def union_overlaps(contours):
    """Merge overlapping contours within a single master via a boolean union
    (skia-pathops), returning contours in the standard format, or None on error.
    Used only as a fallback for contour-count mismatches — it removes overlaps for
    that one glyph, which is preferable to freezing it."""
    try:
        import pathops
    except Exception:  # noqa: BLE001
        return None
    try:
        path = pathops.Path()
        pen = path.getPen()
        for con in contours:
            for op, pts in con:
                if op == "moveTo":
                    pen.moveTo(pts[0])
                elif op == "lineTo":
                    pen.lineTo(pts[0])
                elif op == "curveTo":
                    pen.curveTo(*pts)
                elif op == "qCurveTo":
                    pen.qCurveTo(*pts)
                elif op == "closePath":
                    pen.closePath()
                elif op == "endPath":
                    pen.endPath()
        path.simplify()
        rec = []
        cur = None
        for op, pts in path.segments:
            if op == "moveTo":
                cur = [("moveTo", [tuple(pts[0])])]
            elif op == "lineTo":
                cur.append(("lineTo", [tuple(pts[0])]))
            elif op in ("curveTo", "qCurveTo"):
                cur.append((op, [tuple(p) for p in pts]))
            elif op in ("closePath", "endPath"):
                cur.append((op, []))
                rec.append(cur)
                cur = None
        return rec or None
    except Exception:  # noqa: BLE001
        return None


def _reconstruct_at(outlines_by_pos, reference_pos, corner_angle):
    info = {"stage": None, "note": ""}
    positions = sorted(outlines_by_pos)
    ref = reference_pos if reference_pos in outlines_by_pos else positions[len(positions) // 2]

    # flatten every master to rings (one ring per contour)
    rings = {}  # pos -> list of (nodes, corners) per contour
    for pos, contours in outlines_by_pos.items():
        rings[pos] = [to_ring(c, corner_angle) for c in contours]

    # contour count must match the reference (decompose already ran); if not, fail
    ref_n = len(rings[ref])
    if any(len(r) != ref_n for r in rings.values()):
        info["note"] = "contour-count mismatch"
        return None, info

    # 3. contour-order match: reorder each master's contours to the reference by
    #    centroid+area nearest match.
    order = {}
    for pos in positions:
        order[pos] = _match_order(rings[pos], rings[ref])
        if order[pos] is None:
            info["note"] = "contour pairing failed"
            return None, info
    rings = {pos: [rings[pos][i] for i in order[pos]] for pos in positions}
    contours_ord = {pos: [outlines_by_pos[pos][i] for i in order[pos]] for pos in positions}

    # 4 + 5. per contour: align winding + start corner, then resample by corner runs
    out = {pos: [] for pos in positions}
    for ci in range(ref_n):
        # corner counts per master for this contour must agree to reconcile
        per = {pos: rings[pos][ci] for pos in positions}
        ccounts = {pos: sum(per[pos][2]) for pos in positions}
        if len(set(ccounts.values())) == 1:
            # all masters agree on corner count: anchor on each master's own
            # corners (best fidelity). ccount==0 (round contour) handled inside.
            rebuilt = _resample_contour_set(per, positions, ref)
        else:
            # corner counts disagree (threshold-straddling vertex): fall back to
            # reference projection — place the REFERENCE master's anchors onto
            # every master by arc length, so no corner agreement is needed.
            rebuilt = _project_contour_set(per, positions, ref)
        if rebuilt is None:
            info["note"] = f"resample/project failed on contour {ci} ({ccounts})"
            return None, info
        for pos in positions:
            out[pos].append(rebuilt[pos])

    info["stage"] = "reconstructed"
    return out, info


def _match_order(master_rings, ref_rings):
    """Greedy nearest match of master contours to reference contours by centroid
    distance with same-sign area preference."""
    ref_feats = [(_centroid(r[0]), _signed_area(r[0])) for r in ref_rings]
    m_feats = [(_centroid(r[0]), _signed_area(r[0])) for r in master_rings]
    used = set()
    order = [None] * len(ref_rings)
    for ri, (rc, ra) in enumerate(ref_feats):
        best, bestd = None, None
        for mi, (mc, ma) in enumerate(m_feats):
            if mi in used:
                continue
            d = _dist(rc, mc) + (0 if (ra >= 0) == (ma >= 0) else 400)
            if bestd is None or d < bestd:
                best, bestd = mi, d
        if best is None:
            return None
        used.add(best)
        order[ri] = best
    return order


def _rotate_to_start(nodes, corners, start_idx, reverse):
    if reverse:
        nodes = [nodes[0]] + nodes[1:][::-1]
        corners = [corners[0]] + corners[1:][::-1]
        start_idx = (len(nodes) - start_idx) % len(nodes)
    nodes = nodes[start_idx:] + nodes[:start_idx]
    corners = corners[start_idx:] + corners[:start_idx]
    return nodes, corners


def _resample_contour_set(per, positions, ref):
    """Align winding + start corner across masters for one contour, then resample
    each inter-corner run to a shared point count (max across masters) by arc
    length. Returns {pos: contour} as a pure-polyline contour (all lineTo)."""
    ref_nodes, _, ref_corners = per[ref]
    ref_area = _signed_area(ref_nodes)
    smooth = sum(ref_corners) == 0  # no corners: round contour (o, bowl)

    def _topmost(nodes):
        return max(range(len(nodes)), key=lambda i: (nodes[i][1], nodes[i][0]))

    ref_cidx = [i for i, c in enumerate(ref_corners) if c]
    ref_cpts = [ref_nodes[i] for i in ref_cidx]

    aligned = {}
    for pos in positions:
        nodes, _, corners = per[pos]
        reverse = (_signed_area(nodes) >= 0) != (ref_area >= 0)
        cand_nodes, cand_corners = (nodes, corners)
        if reverse:
            cand_nodes = [nodes[0]] + nodes[1:][::-1]
            cand_corners = [corners[0]] + corners[1:][::-1]
        if smooth:
            # anchor at the topmost point (stable across weights for round shapes)
            start_idx = _topmost(cand_nodes)
        else:
            corner_idxs = [i for i, c in enumerate(cand_corners) if c]
            if not corner_idxs or len(corner_idxs) != len(ref_cidx):
                return None
            # CYCLIC alignment: rotate this master's corner sequence to the rotation
            # that best matches the reference's corners overall (min total distance).
            # Robust where a single "extreme corner" rule drifts — fixes the % slash
            # bowtie without breaking the near-symmetric corners of 8.
            cpts = [cand_nodes[i] for i in corner_idxs]
            k = len(cpts)
            best_r, best_cost = 0, None
            for r in range(k):
                cost = sum(_dist(cpts[(j + r) % k], ref_cpts[j]) for j in range(k))
                if best_cost is None or cost < best_cost:
                    best_cost, best_r = cost, r
            start_idx = corner_idxs[best_r]
        n = cand_nodes[start_idx:] + cand_nodes[:start_idx]
        c = cand_corners[start_idx:] + cand_corners[:start_idx]
        # for smooth contours the single anchor is the (rotated) start node 0
        if smooth:
            c = [i == 0 for i in range(len(c))]
        aligned[pos] = (n, c)

    # anchor index lists (positions in the rotated ring); must be equal length
    corner_positions = {pos: [i for i, c in enumerate(aligned[pos][1]) if c] for pos in positions}
    k = len(corner_positions[ref])
    if k == 0 or any(len(corner_positions[pos]) != k for pos in positions):
        return None

    # for each run between consecutive corners, pick a shared interior count
    run_counts = []
    for r in range(k):
        maxpts = 0
        for pos in positions:
            nodes = aligned[pos][0]
            cps = corner_positions[pos]
            a = cps[r]
            b = cps[(r + 1) % k]
            seg = _run_slice(nodes, a, b)
            arclen = sum(_dist(seg[i], seg[i + 1]) for i in range(len(seg) - 1))
            pts = max(MIN_RUN_PTS, int(arclen // RESAMPLE_STEP))
            maxpts = max(maxpts, pts)
        run_counts.append(maxpts)

    # build each master's contour: corner anchor + resampled interior per run
    result = {}
    for pos in positions:
        nodes = aligned[pos][0]
        cps = corner_positions[pos]
        pts_out = []
        for r in range(k):
            a = cps[r]
            b = cps[(r + 1) % k]
            seg = _run_slice(nodes, a, b)
            pts_out.append(nodes[a])  # the corner anchor
            pts_out.extend(_resample_polyline(seg, run_counts[r]))  # interior pts
        result[pos] = _as_line_contour(pts_out)
    return result


def _project_contour_set(per, positions, ref):
    """Corner counts disagree across masters for this contour. Use the REFERENCE
    master's anchors as the canonical structure and place them on every master at
    the same normalised arc-length positions, then resample the runs between them.
    No per-master corner agreement required."""
    ref_nodes, _, ref_corners = per[ref]
    ref_area = _signed_area(ref_nodes)
    smooth = sum(ref_corners) == 0

    def _topmost(nodes):
        return max(range(len(nodes)), key=lambda i: (nodes[i][1], nodes[i][0]))

    # reference anchors as normalised arc-length fractions around the ring
    ref_start = _topmost(ref_nodes) if smooth else ref_corners.index(True)
    rn = ref_nodes[ref_start:] + ref_nodes[:ref_start]
    rc = (
        ([True] + [False] * (len(rn) - 1))
        if smooth
        else (ref_corners[ref_start:] + ref_corners[:ref_start])
    )
    ref_fracs = _anchor_fracs(rn, [i for i, c in enumerate(rc) if c])
    k = len(ref_fracs)
    if k == 0:
        return None
    # shared interior point budget per run (from the reference run arc lengths)
    cum, total = _cumlen(rn)
    run_counts = []
    for r in range(k):
        f0 = ref_fracs[r]
        f1 = ref_fracs[(r + 1) % k] + (1.0 if r == k - 1 else 0.0)
        run_counts.append(max(MIN_RUN_PTS, int(total * (f1 - f0) // RESAMPLE_STEP)))

    result = {}
    for pos in positions:
        nodes, _, corners = per[pos]
        reverse = (_signed_area(nodes) >= 0) != (ref_area >= 0)
        nd = ([nodes[0]] + nodes[1:][::-1]) if reverse else nodes
        # start the target ring at the point nearest the reference's first anchor
        ref_first = rn[0]
        start = min(range(len(nd)), key=lambda i: _dist(nd[i], ref_first))
        nd = nd[start:] + nd[:start]
        # place anchors at the reference's EXACT arc-length fractions: inserting
        # interpolated points (rather than snapping to the nearest existing node,
        # which COLLIDES when the reference's corners cluster — serif corners a
        # few units apart snap to the same node, and slicing runs between
        # colliding indices spliced a full extra ring loop, multiplying the ink
        # area). Exact positions cannot collide while the reference fracs are
        # distinct; a genuinely duplicated frac just yields an empty run, which
        # keeps its point budget as repeats of the anchor.
        aug, anchor_idx = _insert_at_fracs(nd, ref_fracs)
        pts_out = []
        for r in range(k):
            a = anchor_idx[r]
            b = anchor_idx[(r + 1) % k]
            seg = _run_slice(aug, a, b) if a != b else [aug[a], aug[a]]
            pts_out.append(aug[a])
            pts_out.extend(_resample_polyline(seg, run_counts[r]))
        result[pos] = _as_line_contour(pts_out)
    return result


def _insert_at_fracs(nodes, fracs):
    """Insert interpolated points into a closed ring at the given arc-length
    fractions. Returns (augmented ring, index of each frac's anchor point)."""
    cum, total = _cumlen(nodes)
    n = len(nodes)
    # (arc position, original index) for every existing node
    events = [(cum[i], 0, i) for i in range(n)]
    for fi, f in enumerate(fracs):
        events.append((min(f, 1.0) * total, 1, fi))
    events.sort()
    aug = []
    anchor_idx = [0] * len(fracs)
    for arc, kind, idx in events:
        if kind == 0:
            aug.append(nodes[idx])
        else:
            # interpolate the point at this arc position
            i = 1
            while i <= n and cum[i] < arc:
                i += 1
            i = min(i, n)
            span = cum[i] - cum[i - 1]
            t = 0.0 if span <= 0 else (arc - cum[i - 1]) / span
            a = nodes[i - 1]
            b = nodes[i % n]
            anchor_idx[idx] = len(aug)
            aug.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return aug, anchor_idx


def _cumlen(nodes):
    cum = [0.0]
    n = len(nodes)
    for i in range(1, n + 1):
        cum.append(cum[-1] + _dist(nodes[i - 1], nodes[i % n]))
    return cum, cum[-1]


def _anchor_fracs(nodes, anchor_indices):
    cum, total = _cumlen(nodes)
    if total <= 0:
        return []
    return [cum[i] / total for i in anchor_indices]


def _idx_at_fracs(nodes, fracs):
    cum, total = _cumlen(nodes)
    out = []
    for f in fracs:
        target = f * total
        i = 0
        while i < len(nodes) and cum[i] < target:
            i += 1
        out.append(min(i, len(nodes) - 1))
    return out


def _run_slice(nodes, a, b):
    """Inclusive slice of the ring from index a to b (cyclic). a == b means the
    whole ring (single-anchor smooth contour)."""
    if a == b:
        return nodes[a:] + nodes[:a] + [nodes[a]]
    if a < b:
        return nodes[a : b + 1]
    return nodes[a:] + nodes[: b + 1]


def _resample_polyline(seg, count):
    """Return `count` interior points evenly spaced by arc length along seg
    (excludes both endpoints, which are corner anchors handled by neighbours)."""
    if count <= 0 or len(seg) < 2:
        return []
    cum = [0.0]
    for i in range(1, len(seg)):
        cum.append(cum[-1] + _dist(seg[i - 1], seg[i]))
    total = cum[-1]
    if total <= 0:
        return [seg[0]] * count
    out = []
    for j in range(1, count + 1):
        target = total * j / (count + 1)
        i = 1
        while i < len(cum) and cum[i] < target:
            i += 1
        i = min(i, len(seg) - 1)
        span = cum[i] - cum[i - 1]
        t = 0 if span <= 0 else (target - cum[i - 1]) / span
        out.append(
            (
                seg[i - 1][0] + (seg[i][0] - seg[i - 1][0]) * t,
                seg[i - 1][1] + (seg[i][1] - seg[i - 1][1]) * t,
            )
        )
    return out


def _as_line_contour(points):
    con = [("moveTo", [points[0]])]
    for p in points[1:]:
        con.append(("lineTo", [p]))
    con.append(("closePath", []))
    return con
