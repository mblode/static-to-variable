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

import itertools
import math

from fontTools.misc.bezierTools import splitCubicAtT
from variable_gen.audit_support import segments_intersect
from variable_gen.outlines import signature

CORNER_ANGLE = math.radians(28)  # tangent break above this = corner anchor
# CFF integer rounding often collapses a cubic handle onto (or 1 unit from)
# its on-curve node. Treating that stub as a real tangent invents false corners
# (Thin ``d`` @ 532: 7 vs Book/XB's 6) and forces projection/union-heal paths
# that destroy stem tops. Fall back to the chord when a handle is this short.
MIN_HANDLE_LEN = 2.5
RESAMPLE_STEP = 18  # target units between resampled points (dense
# enough that curves stay smooth at display sizes)
# When union-heal invents short-leg cusp folds at stem/bowl joins (d), retry
# once with a coarser sample so weight still varies instead of freezing.
FOLD_RETRY_RESAMPLE_STEP = 32
MIN_RUN_PTS = 1  # min interior points per inter-corner run

# ATTEMPTED AND REVERTED: resampling small contours more finely.
#
# Diagnosis stands and is the important part. The comma-accent family is
# master-INCOMPATIBLE IN THE DONOR ITSELF -- Circular draws `undercommaaccent`
# with 8 points at Thin and 9 at ExtraBlack -- so it cannot take the
# already-compatible fast path and goes through this resampler. RESAMPLE_STEP is
# an absolute 18 units, which is right for a bowl and starves a mark whose whole
# perimeter is a few steps: a 7-segment accent came back as 25 segments at a
# curvature roughness of 257 against the donor's 7.4, inherited identically by
# every glyph carrying it.
#
# Sampling proportionally fixed exactly that -- undercommaaccent 257 -> 57,
# commaaccent 157 -> 35, and the whole Xcommaaccent family with them -- but
# finer sampling buys fidelity and pays in segment economy: 40 further glyphs
# crossed the micro-segment threshold, `a` among them, and the flagged total
# went 226 -> 259. Confining it to contours under 520 units changed nothing,
# because the affected contours are all small already. The trade is intrinsic to
# sampling density and cannot be tuned away.
#
# The correct fix is not a density knob. When masters differ by one or two
# points, insert the missing points at the corresponding positions instead of
# resampling every master onto a polyline -- compatibility by insertion rather
# than by rebuild. That preserves the donor's own node structure, which is what
# the resampler destroys, and it would address the 213 donor-inherited
# incompatibilities rather than this one family.
#
# ATTEMPTED AND REVERTED: that insertion path, built and measured.
#
# It works, and the geometry is not what defeated it. Aligning the masters'
# on-curve rings (Needleman-Wunsch over arc-length position, start-rotation
# picked per master against the reference) paired `undercommaaccent`'s nodes
# correctly and found ExtraBlack's genuinely extra one; splitting the sparse
# masters' matching segment there with `splitCubicAtT`, plus exact degree
# elevation where a line faced a curve, made all three masters share one
# structure with every enclosed area preserved to 1e-9 relative and every node
# still on the donor's own path. It reached 189 of the 332 glyphs that need
# repair and left the donor's segment counts intact instead of the resampler's
# 7 -> 25.
#
# What defeated it is `reconstruct_plan` in rebuild.py, one level up. Optical
# rows are reconstructed INDEPENDENTLY and then required to share an identical
# point structure (`_row_signature_details`), because opsz has to interpolate
# too. Glide's Text cabinet is a separate drawing from the UI/Display one for
# 121 glyphs -- all the round lowercase, a c d e g m o p q r s t and their
# accented forms. Insertion is faithful to whichever drawing it is handed, so
# those rows come out with different node counts and the build stops. The
# resampler satisfies the contract only because it is NORMALISING: it erases the
# difference between the two cabinets by rebuilding both onto the same grid.
# Faithfulness and that contract are mutually exclusive, and every one of the
# 121 casualties was a cabinet-differing glyph while every glyph the accent fix
# targets is cabinet-identical.
#
# So this cannot be gated from inside reconstruct(), which sees one row and
# cannot know whether the others were drawn the same. Anyone retrying it needs
# `reconstruct_plan` to reconcile the rows -- reconstruct the opsz grid together,
# or merge the per-row structures into their union before the signature check --
# and only then is insertion safe to switch on. Measured on the last donors that
# built green: baseline 226 flagged of 743, insertion 121 glyphs unbuildable.

# The compatibility input is an 18-unit polyline sampling of the donor, not the
# analytic curve itself. Chasing that polygon below its sub-unit chord error
# fragments smooth bowls into dozens of tiny cubics whose handle-length jumps
# show up during interpolation. A 1.5-unit fit stays visually on the donor while
# recovering the short, smooth curve chains the samples represent.
CURVE_FIT_TOLERANCE = 1.5
MIN_HANDLE_LEN = 2.5
RESAMPLE_STEP = 18  # target units between resampled points (dense
# enough that curves stay smooth at display sizes)
# When union-heal invents short-leg cusp folds at stem/bowl joins (d), retry
# once with a coarser sample so weight still varies instead of freezing.
FOLD_RETRY_RESAMPLE_STEP = 32
MIN_RUN_PTS = 1  # min interior points per inter-corner run

# ATTEMPTED AND REVERTED: resampling small contours more finely.
#
# Diagnosis stands and is the important part. The comma-accent family is
# master-INCOMPATIBLE IN THE DONOR ITSELF -- Circular draws `undercommaaccent`
# with 8 points at Thin and 9 at ExtraBlack -- so it cannot take the
# already-compatible fast path and goes through this resampler. RESAMPLE_STEP is
# an absolute 18 units, which is right for a bowl and starves a mark whose whole
# perimeter is a few steps: a 7-segment accent came back as 25 segments at a
# curvature roughness of 257 against the donor's 7.4, inherited identically by
# every glyph carrying it.
#
# Sampling proportionally fixed exactly that -- undercommaaccent 257 -> 57,
# commaaccent 157 -> 35, and the whole Xcommaaccent family with them -- but
# finer sampling buys fidelity and pays in segment economy: 40 further glyphs
# crossed the micro-segment threshold, `a` among them, and the flagged total
# went 226 -> 259. Confining it to contours under 520 units changed nothing,
# because the affected contours are all small already. The trade is intrinsic to
# sampling density and cannot be tuned away.
#
# The correct fix is not a density knob. When masters differ by one or two
# points, insert the missing points at the corresponding positions instead of
# resampling every master onto a polyline -- compatibility by insertion rather
# than by rebuild. That preserves the donor's own node structure, which is what
# the resampler destroys, and it would address the 213 donor-inherited
# incompatibilities rather than this one family.
#
# ATTEMPTED AND REVERTED: that insertion path, built and measured.
#
# It works, and the geometry is not what defeated it. Aligning the masters'
# on-curve rings (Needleman-Wunsch over arc-length position, start-rotation
# picked per master against the reference) paired `undercommaaccent`'s nodes
# correctly and found ExtraBlack's genuinely extra one; splitting the sparse
# masters' matching segment there with `splitCubicAtT`, plus exact degree
# elevation where a line faced a curve, made all three masters share one
# structure with every enclosed area preserved to 1e-9 relative and every node
# still on the donor's own path. It reached 189 of the 332 glyphs that need
# repair and left the donor's segment counts intact instead of the resampler's
# 7 -> 25.
#
# What defeated it is `reconstruct_plan` in rebuild.py, one level up. Optical
# rows are reconstructed INDEPENDENTLY and then required to share an identical
# point structure (`_row_signature_details`), because opsz has to interpolate
# too. Glide's Text cabinet is a separate drawing from the UI/Display one for
# 121 glyphs -- all the round lowercase, a c d e g m o p q r s t and their
# accented forms. Insertion is faithful to whichever drawing it is handed, so
# those rows come out with different node counts and the build stops. The
# resampler satisfies the contract only because it is NORMALISING: it erases the
# difference between the two cabinets by rebuilding both onto the same grid.
# Faithfulness and that contract are mutually exclusive, and every one of the
# 121 casualties was a cabinet-differing glyph while every glyph the accent fix
# targets is cabinet-identical.
#
# So this cannot be gated from inside reconstruct(), which sees one row and
# cannot know whether the others were drawn the same. Anyone retrying it needs
# `reconstruct_plan` to reconcile the rows -- reconstruct the opsz grid together,
# or merge the per-row structures into their union before the signature check --
# and only then is insertion safe to switch on. Measured on the last donors that
# built green: baseline 226 flagged of 743, insertion 121 glyphs unbuildable.

# The compatibility input is an 18-unit polyline sampling of the donor, not the
# analytic curve itself. Chasing that polygon below its sub-unit chord error
# fragments smooth bowls into dozens of tiny cubics whose handle-length jumps
# show up during interpolation. A 1.5-unit fit stays visually on the donor while
# recovering the short, smooth curve chains the samples represent.
CURVE_FIT_TOLERANCE = 1.5
#: Stop subdividing a run once it is this short. Nine samples is about 145 units
#: of arc at `RESAMPLE_STEP`, and a stretch that small is not a curve the fit is
#: failing to hold -- it is a corner no cubic can hold, so the recursion keeps
#: halving and re-expresses the corner as curvature across a fan of near-collinear
#: cubics. `dollar` came out with 81 segments against a donor's 12 that way, its
#: G2 break total 44.1 against the donor's 5.0. Measured over 742 glyphs: 84
#: improve, one loses two segments, 1165 segments come out of the font, and the
#: reconstruction gets faster because it recurses less.
CURVE_CORNER_ANGLE = math.radians(20)
CURVE_LINE_TOLERANCE = 0.08


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
            out_tan[i] = _cubic_out_tan(a, c1, c2, b)
            in_tan[(i + 1) % n] = _cubic_in_tan(a, c1, c2, b)
            steps = max(2, int(_dist(a, c1) + _dist(c1, c2) + _dist(c2, b)) // 24)
            seg_samples[i] = [_cubic(a, c1, c2, b, j / steps) for j in range(1, steps)]
        else:  # quad
            c = ctrl[0]
            out_tan[i] = _unit(a, c) if _dist(a, c) > MIN_HANDLE_LEN else _unit(a, b)
            in_tan[(i + 1) % n] = _unit(c, b) if _dist(c, b) > MIN_HANDLE_LEN else _unit(a, b)
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


def _cubic_out_tan(a, c1, c2, b):
    """Outgoing tangent at ``a``; ignore CFF-collapsed stub handles."""
    if _dist(a, c1) > MIN_HANDLE_LEN:
        return _unit(a, c1)
    if _dist(a, c2) > MIN_HANDLE_LEN:
        return _unit(a, c2)
    return _unit(a, b)


def _cubic_in_tan(a, c1, c2, b):
    """Incoming tangent at ``b``; ignore CFF-collapsed stub handles."""
    if _dist(c2, b) > MIN_HANDLE_LEN:
        return _unit(c2, b)
    if _dist(c1, b) > MIN_HANDLE_LEN:
        return _unit(c1, b)
    return _unit(a, b)


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


def _contour_nodes(contour):
    """The on-curve nodes of a pen-op contour, in order, with their segments.

    Returns (start, segments) where each segment ends at the next node, or None
    for anything this cannot safely take apart.
    """
    if not contour or contour[0][0] != "moveTo":
        return None
    start = contour[0][1][0]
    segments = []
    for op, pts in contour[1:]:
        if op in ("lineTo", "curveTo", "qCurveTo"):
            segments.append((op, list(pts)))
        elif op in ("closePath", "endPath"):
            continue
        else:
            return None
    if not segments:
        return None
    return start, segments


def _is_closed(contour, taken=None):
    """True when the contour's last segment lands back on its start point.

    `closePath` can stand for an edge the segment list does not carry, and every
    routine here that reorders segments needs to know which it is looking at.
    """
    taken = taken or _contour_nodes(contour)
    if taken is None:
        return False
    start, segments = taken
    return _dist(segments[-1][1][-1], start) < 1e-6


def _rotate_contour(contour, shift):
    """The same closed contour, re-emitted starting `shift` nodes further round.

    Exact: no point moves and no segment changes kind. Only which node the path
    is written from changes, which is the one thing gvar cares about and the one
    thing the donor is entitled to disagree with itself about.
    """
    taken = _contour_nodes(contour)
    if taken is None:
        return None
    start, segments = taken
    count = len(segments)
    shift %= count
    if shift == 0:
        return contour
    ends = [start] + [segment[1][-1] for segment in segments]
    if not _is_closed(contour):
        # An open run has no rotation that means the same thing.
        return None
    rotated = segments[shift:] + segments[:shift]
    new_start = ends[shift]
    out = [("moveTo", [new_start])]
    out.extend((op, list(pts)) for op, pts in rotated)
    out.append(("closePath", []))
    return out


def _contour_node_points(contour, taken=None):
    """The on-curve nodes of a closed contour, indexed the way a rotation is.

    Node i is where segment i begins, so rotating by k makes node k the start.
    Deliberately NOT `to_ring`'s dense ring: that carries curve samples whose
    count follows the curve's length, so the same four-node circle yields 32
    points at Thin and 12 at ExtraBlack, and comparing those lengths rejects
    exactly the compatible shapes this is meant to rescue.
    """
    taken = taken or _contour_nodes(contour)
    if taken is None:
        return None
    start, segments = taken
    return [start] + [segment[1][-1] for segment in segments[:-1]]


def _start_offset(ring, reference_ring):
    """Which rotation of `ring` best lines its nodes up with the reference.

    Compared in each contour's own normalised box, because the masters are
    different weights and their nodes are nowhere near each other in absolute
    terms.
    """

    def normalise(points):
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        width = (max(xs) - min(xs)) or 1.0
        height = (max(ys) - min(ys)) or 1.0
        return [((x - min(xs)) / width, (y - min(ys)) / height) for x, y in points]

    here = normalise(ring)
    there = normalise(reference_ring)
    count = len(here)
    best = (None, None)
    for shift in range(count):
        cost = sum(
            (here[(index + shift) % count][0] - there[index][0]) ** 2
            + (here[(index + shift) % count][1] - there[index][1]) ** 2
            for index in range(count)
        )
        if best[0] is None or cost < best[0]:
            best = (cost, shift)
    return best[1]


def _align_starts(outlines, reference_pos):
    """Rotate each contour so every master writes it from the same node.

    The donors disagree about where a contour begins -- Circular starts the two
    dots of `divide` at a different point round the ring in each weight -- and
    `_starts_aligned` quite rightly refuses to interpolate that. But refusing
    sends a set of outlines that are otherwise perfectly compatible through the
    full resample and refit, and that is what destroys them: the dots arrive as
    four-segment circles and leave as eight-segment shapes rippling ninety times
    the donor's own curvature. `degree` and `percent` lose their rings the same
    way, and all three are on the list of shapes a human marked as not round.

    Rotating is exact -- no point moves, no segment changes kind -- so where it
    is enough, the donor's own drawing survives intact. Returns None when it
    cannot align, leaving the existing path to deal with it.
    """
    positions = sorted(outlines)
    if reference_pos not in outlines:
        return None
    reference = outlines[reference_pos]
    out = {reference_pos: reference}
    for pos in positions:
        if pos == reference_pos:
            continue
        contours = outlines[pos]
        if len(contours) != len(reference):
            return None
        rotated = []
        for index, contour in enumerate(contours):
            nodes = _contour_node_points(contour)
            reference_nodes = _contour_node_points(reference[index])
            if nodes is None or reference_nodes is None:
                return None
            if len(nodes) != len(reference_nodes) or len(nodes) < 3:
                return None
            turned = _rotate_contour(contour, _start_offset(nodes, reference_nodes))
            if turned is None:
                return None
            rotated.append(turned)
        out[pos] = rotated
    return out


def _promote_lines_to_curves(outlines, reference_pos):
    """Raise a line to a cubic wherever another master curves in the same place.

    A line IS a cubic: put the controls a third and two thirds along the chord
    and the curve is the same straight segment, exactly. So where the masters
    agree on how many segments a contour has and disagree only about whether one
    of them is straight, that disagreement is notation, not shape. Circular does
    this constantly at the small sizes -- `c.ordn` is `CLCCCCLCCC` at Thin and
    Book and `CCCCCCLCCC` at ExtraBlack, one segment drawn straight in two
    weights and curved in the third.

    Only the mismatched segments are raised, and only when the counts already
    agree: a blanket promotion would turn every stem into a curve, and a stem
    that is a cubic is free to bow once its coordinates are rounded.

    Returns the outlines unchanged when there is nothing to do.
    """
    positions = sorted(outlines)
    reference = outlines.get(reference_pos)
    if reference is None or len(positions) < 2:
        return outlines

    parsed = {}
    for pos in positions:
        contours = outlines[pos]
        if len(contours) != len(reference):
            return outlines
        taken = [_contour_nodes(contour) for contour in contours]
        if any(item is None for item in taken):
            return outlines
        parsed[pos] = taken

    out = {pos: list(outlines[pos]) for pos in positions}
    changed = False
    for index in range(len(reference)):
        counts = {len(parsed[pos][index][1]) for pos in positions}
        if len(counts) != 1:
            continue
        length = counts.pop()
        curved = {
            step
            for step in range(length)
            for pos in positions
            if parsed[pos][index][1][step][0] == "curveTo"
        }
        straight = {
            step
            for step in range(length)
            for pos in positions
            if parsed[pos][index][1][step][0] == "lineTo"
        }
        mismatched = sorted(curved & straight)
        if not mismatched:
            continue
        for pos in positions:
            start, segments = parsed[pos][index]
            rebuilt = list(segments)
            here = start
            for step, (op, pts) in enumerate(segments):
                end = pts[-1]
                if step in mismatched and op == "lineTo":
                    rebuilt[step] = (
                        "curveTo",
                        [
                            (here[0] + (end[0] - here[0]) / 3, here[1] + (end[1] - here[1]) / 3),
                            (
                                here[0] + 2 * (end[0] - here[0]) / 3,
                                here[1] + 2 * (end[1] - here[1]) / 3,
                            ),
                            end,
                        ],
                    )
                    changed = True
                here = end
            out[pos][index] = [("moveTo", [start]), *rebuilt, ("closePath", [])]
    return out if changed else outlines


def _contour_runs(contour, taken=None):
    """A closed contour as consecutive same-kind runs, starting at a run boundary.

    Returns (runs, rotation) where each run is (kind, [segments]) and `rotation`
    is how many segments the contour was turned to make it begin at a boundary.
    A closed contour whose first and last segment share a kind has one run that
    wraps the start, so it has to be turned before the runs can be read off at
    all. Returns None for anything that cannot be decomposed.
    """
    taken = taken or _contour_nodes(contour)
    if taken is None:
        return None
    _start, segments = taken
    kinds = [op for op, _pts in segments]
    if len(set(kinds)) == 1:
        return [(kinds[0], list(segments))], 0
    turn = next(i for i in range(len(kinds)) if kinds[i] != kinds[i - 1])
    ordered = segments[turn:] + segments[:turn]
    runs = []
    for op, pts in ordered:
        if runs and runs[-1][0] == op:
            runs[-1][1].append((op, pts))
        else:
            runs.append((op, [(op, pts)]))
    return runs, turn


def _split_segment_once(op, pts, start):
    """Halve one segment exactly. Returns [(op, pts), (op, pts)] and the midpoint."""
    if op == "lineTo":
        end = pts[-1]
        mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
        return [("lineTo", [mid]), ("lineTo", [end])], mid
    if op == "curveTo" and len(pts) == 3:
        c1, c2, end = pts
        left, right = splitCubicAtT(start, c1, c2, end, 0.5)
        return (
            [("curveTo", [left[1], left[2], left[3]]), ("curveTo", [right[1], right[2], right[3]])],
            left[3],
        )
    return None, None


def _drop_redundant_line_nodes(run, start):
    """Remove interior nodes of a straight run that sit exactly on its chord.

    A node a master spends in the middle of a straight edge carries no shape:
    the run means the same thing without it. Growing every other master to match
    it would propagate a node nobody needs, so the redundant ones come out first
    and only genuine differences are made up by splitting.

    Exact by construction -- a point is removed only when it lies on the line
    between its neighbours to within a rounding error, so the ink is unchanged.
    """
    if not run or run[0][0] != "lineTo":
        return run
    points = [start] + [pts[-1] for _op, pts in run]
    kept = [points[0]]
    for index in range(1, len(points) - 1):
        before, here, after = kept[-1], points[index], points[index + 1]
        dx, dy = after[0] - before[0], after[1] - before[1]
        span = math.hypot(dx, dy)
        if span <= 1e-9:
            kept.append(here)
            continue
        offset = abs((here[0] - before[0]) * dy - (here[1] - before[1]) * dx) / span
        # Also require it to sit BETWEEN them, so a spike doubling back is kept.
        along = ((here[0] - before[0]) * dx + (here[1] - before[1]) * dy) / (span * span)
        if offset > 1e-6 or not (0.0 < along < 1.0):
            kept.append(here)
    kept.append(points[-1])
    return [("lineTo", [point]) for point in kept[1:]]


def _grow_run(run, start, target):
    """Split within one run until it has ``target`` segments. Exact, by halving.

    The longest segment goes first, which is where a master that drew the run
    with more segments almost always put its extra node, and which keeps the
    result independent of the order the splits happen in.
    """
    segments = list(run)
    heads = [start]
    for op, pts in segments[:-1]:
        heads.append(pts[-1])
    while len(segments) < target:
        lengths = [_dist(heads[i], segments[i][1][-1]) for i in range(len(segments))]
        index = max(range(len(segments)), key=lambda i: lengths[i])
        op, pts = segments[index]
        pair, mid = _split_segment_once(op, pts, heads[index])
        if pair is None:
            return None
        segments[index : index + 1] = pair
        heads[index + 1 : index + 1] = [mid]
    return segments


def _run_start_node(runs, turn, begin):
    """Where the contour starts once its run list is turned by ``turn``.

    Turning the runs moves the start with them: the new first run begins where
    the run before it ended. ``turn`` of zero leaves it where it was.
    """
    if not turn:
        return begin
    return runs[turn - 1][1][-1][1][-1]


def _unify_run_counts(outlines, reference_pos):
    """Give every master the same segment count in each run, by exact splitting.

    Circular draws the same stretch with different numbers of segments in
    different weights. `three` is `L CCCC L CCCC LLLLLL` at Thin and
    `L CCCC L CCC LLLLLL` at Book -- one curve fewer in the middle run -- and
    ExtraBlack is Book's again, turned by a node. The run STRUCTURE agrees; only
    the counts differ. 173 of the 388 glyphs that still miss the fast path are
    this case, `zero` `three` `o` `b` `p` `t` `asciitilde` among them.

    Halving a segment is exact -- de Casteljau for a cubic, the midpoint for a
    line -- so bringing the sparser masters up to the densest changes no shape at
    all. It only adds nodes, and it adds the same number to the same run in every
    master, which is what gvar requires.

    Returns None unless every master decomposes into the same runs in the same
    cyclic order, leaving a genuine drawing difference to the resampler.
    """
    positions = sorted(outlines)
    reference = outlines.get(reference_pos)
    if reference is None:
        return None

    decomposed = {}
    for pos in positions:
        contours = outlines[pos]
        if len(contours) != len(reference):
            return None
        shapes = []
        for contour in contours:
            # Parsed once and passed down: `_contour_runs`, `_contour_node_points`
            # and `_is_closed` each re-derive the same segment list otherwise.
            parsed = _contour_nodes(contour)
            if parsed is None:
                return None
            taken = _contour_runs(contour, parsed)
            nodes = _contour_node_points(contour, parsed)
            if taken is None or nodes is None:
                return None
            # An implicit closing edge means the segment list does not cover the
            # whole loop, and turning it would drop that edge on the floor.
            # `donor_outline` materialises the edge, so real donor contours
            # arrive explicitly closed; a synthetic one may not.
            if not _is_closed(contour, parsed):
                return None
            runs, turn = taken
            shapes.append((runs, nodes[turn % len(nodes)]))
        decomposed[pos] = shapes

    out = {pos: [] for pos in positions}
    for index in range(len(reference)):
        pattern = [kind for kind, _ in decomposed[reference_pos][index][0]]
        aligned = {}
        for pos in positions:
            runs, begin = decomposed[pos][index]
            if len(runs) != len(pattern):
                return None
            kinds = [kind for kind, _ in runs]
            count = len(kinds)
            # A repeating run pattern matches at more than one rotation -- the
            # `L,C,L,C` of a rounded rectangle matches at 0 and at 2 -- so the
            # first match is not necessarily the right one, and taking it can
            # correspond the far side of the contour to the near side. Score the
            # candidates by where their nodes actually sit and keep the best.
            turns = [
                t for t in range(count) if [kinds[(t + i) % count] for i in range(count)] == pattern
            ]
            if not turns:
                return None
            if len(turns) == 1:
                turn = turns[0]
            else:
                # Compare against where the REFERENCE's runs start, not where its
                # contour originally did: `_contour_runs` has already turned both
                # to begin at a run boundary.
                anchor = decomposed[reference_pos][index][1]
                turn = min(
                    turns,
                    key=lambda t: _dist(_run_start_node(runs, t, begin), anchor),
                )
            if turn:
                begin = _run_start_node(runs, turn, begin)
            aligned[pos] = (runs[turn:] + runs[:turn], begin)

        # Redundant collinear nodes come out before the counts are compared, or a
        # node one master wastes in the middle of a straight edge would be forced
        # on all the others.
        trimmed = {}
        for pos in positions:
            runs, begin = aligned[pos]
            head = begin
            per_run = []
            for _kind, run in runs:
                lean = _drop_redundant_line_nodes(run, head)
                per_run.append(lean)
                head = run[-1][1][-1]
            trimmed[pos] = per_run
        targets = [max(len(trimmed[pos][run]) for pos in positions) for run in range(len(pattern))]
        for pos in positions:
            runs, begin = aligned[pos]
            segments = []
            head = begin
            for run_index, (_kind, run) in enumerate(runs):
                grown = _grow_run(trimmed[pos][run_index], head, targets[run_index])
                if grown is None:
                    return None
                segments.extend(grown)
                head = grown[-1][1][-1]
            out[pos].append([("moveTo", [begin]), *segments, ("closePath", [])])
    return out


def _starts_correspond(outlines, reference_pos):
    """True when no rotation would line the masters up better than they already are.

    `_starts_aligned` asks an absolute question -- does the start node sit within
    a fixed fraction of the contour box in every master -- and on a letterform
    that changes proportion with weight the answer is no even when nothing is
    wrong. `H` begins at the same corner in all three weights, but as the stems
    thicken that corner slides from 0.917 of the box across to 0.693, which reads
    as drift and is not. A hundred glyphs, `A` `H` `K` `M` `N` `four` `slash`
    among them, were being sent through the resample and refit on that basis.

    The question that actually matters is relative: is this the best of the
    rotations available? If some other rotation would fit the reference
    noticeably better then the starts really have drifted and the masters would
    interpolate node onto the wrong node. If the current one is already the best,
    they correspond, however far the box has moved underneath them.
    """
    if reference_pos not in outlines:
        return False
    reference = outlines[reference_pos]
    for pos, contours in outlines.items():
        if pos == reference_pos:
            continue
        if len(contours) != len(reference):
            return False
        for index, contour in enumerate(contours):
            if not _is_closed(contour) or not _is_closed(reference[index]):
                # `_contour_node_points` drops the final node when the contour
                # closes implicitly, so the rings being compared would be a node
                # short and could agree by omission.
                return False
            nodes = _contour_node_points(contour)
            reference_nodes = _contour_node_points(reference[index])
            if nodes is None or reference_nodes is None:
                return False
            if len(nodes) != len(reference_nodes):
                return False
            if len(nodes) < 3:
                continue
            if _start_offset(nodes, reference_nodes) != 0:
                return False
    return True


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


def reconstruct(outlines_by_pos, reference_pos=400, *, _fold_retry=True):
    """outlines_by_pos: {axis_pos: contours}. Returns (compatible|None, info).
    Tries a sweep of corner-detection thresholds; returns the first that yields a
    fully interpolation-compatible result, then (for 3+ masters) swaps in the
    rotation-aligned uniform resample when it predicts the interior master
    better — see _interior_dev. If masters disagree on contour COUNT, first
    unions overlapping contours per master (handles glyphs like $ / ¢ whose
    separate bar stubs merge into the body at heavy weights)."""
    global RESAMPLE_STEP
    out, info = _reconstruct_base(outlines_by_pos, reference_pos)
    out, info = _ink_tournament(out, info, outlines_by_pos, reference_pos)
    if out is None:
        floating = _reconstruct_floating_contour(outlines_by_pos, reference_pos)
        if floating is not None:
            out = floating
            info = {"stage": "reconstructed", "note": "floating-contour"}
    if out is not None and info.get("stage") == "reconstructed":
        curved = _restore_compatible_curves(out, outlines_by_pos)
        if curved is not None and not _quality_offenders(curved, outlines_by_pos):
            if not _has_interpolated_self_intersection(curved):
                out = curved
                info = {
                    **info,
                    "note": "+".join(filter(None, (info.get("note"), "cubic-refit"))),
                }
            else:
                # Cubic refit can reintroduce bowl/stem crossings the polyline
                # masters didn't show (d at Thin/ExtraBlack). Union each master
                # then re-reconstruct so weight still varies without freezing.
                healed, hinfo = _heal_self_intersecting_curves(
                    curved, outlines_by_pos, reference_pos
                )
                if healed is not None:
                    # Union-heal+cubic-refit can pass SI yet invent short-leg
                    # cusp folds at stem/bowl joins (visible stairsteps on d).
                    # Retry once with coarser resampling; if folds remain, keep
                    # the pre-refit compatibility polyline so weight still
                    # varies — freezing to Book@400 is worse than a dense
                    # interpolating outline.
                    if _has_excess_short_folds(healed, outlines_by_pos):
                        if _fold_retry and RESAMPLE_STEP < FOLD_RETRY_RESAMPLE_STEP:
                            saved = RESAMPLE_STEP
                            try:
                                RESAMPLE_STEP = FOLD_RETRY_RESAMPLE_STEP
                                retry, rinfo = reconstruct(
                                    outlines_by_pos,
                                    reference_pos,
                                    _fold_retry=False,
                                )
                            finally:
                                RESAMPLE_STEP = saved
                            if retry is not None and not _has_excess_short_folds(
                                retry, outlines_by_pos
                            ):
                                return retry, {
                                    **rinfo,
                                    "note": "+".join(
                                        filter(
                                            None,
                                            (rinfo.get("note"), "coarse-resample"),
                                        )
                                    ),
                                }
                        info = {
                            **info,
                            "note": "+".join(
                                filter(
                                    None,
                                    (info.get("note"), "fold-gate-polyline"),
                                )
                            ),
                        }
                    else:
                        out, info = healed, hinfo
                # else keep the clean polyline result (pre-cubic-refit)
    return out, info


def _oncurve_ring(contour):
    """On-curve points of a (op, pts) contour, in draw order (open until close)."""
    pts = []
    for op, args in contour:
        if op == "moveTo":
            pts = [args[0]]
        elif op == "lineTo":
            pts.append(args[0])
        elif op == "curveTo":
            pts.append(args[2])
        elif op == "qCurveTo":
            pts.append(args[-1])
    return pts


def _short_leg_fold_count(contours, *, ang_min=120.0, leg_max=60.0) -> int:
    """Count cusp-like folds: sharp turns (≥ ang_min°) with a short adjacent leg.

    Intentional stem/bowl corners also turn sharply, but both legs are long.
    Union-heal artifacts reverse locally with one short leg — the stairstep
    visible on reconstructed ``d``.
    """
    folds = 0
    for contour in contours:
        ring = _oncurve_ring(contour)
        n = len(ring)
        if n < 3:
            continue
        for i in range(n):
            a, b, c = ring[(i - 1) % n], ring[i], ring[(i + 1) % n]
            v1 = (b[0] - a[0], b[1] - a[1])
            v2 = (c[0] - b[0], c[1] - b[1])
            n1 = math.hypot(*v1)
            n2 = math.hypot(*v2)
            if n1 < 1e-6 or n2 < 1e-6:
                continue
            cosang = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
            ang = math.degrees(math.acos(cosang))
            if ang >= ang_min and min(n1, n2) < leg_max:
                folds += 1
    return folds


def _has_excess_short_folds(outlines_by_pos, originals_by_pos) -> bool:
    """True when any master gained short-leg folds vs its donor original."""
    for pos, contours in outlines_by_pos.items():
        original = originals_by_pos.get(pos)
        if original is None:
            continue
        if _short_leg_fold_count(contours) > _short_leg_fold_count(original):
            return True
    return False


def _heal_self_intersecting_curves(curved, outlines_by_pos, reference_pos):
    """Boolean-union cubic-refit masters, then rebuild a compatible variable set."""
    unioned = {pos: union_overlaps(contours) for pos, contours in curved.items()}
    if any(contours is None for contours in unioned.values()):
        return None, None
    out, info = _reconstruct_base(unioned, reference_pos)
    out, info = _ink_tournament(out, info, unioned, reference_pos)
    if out is None or info.get("stage") != "reconstructed":
        return None, None
    if _has_interpolated_self_intersection(out):
        return None, None
    refit = _restore_compatible_curves(out, unioned)
    if (
        refit is not None
        and not _quality_offenders(refit, outlines_by_pos)
        and not _has_interpolated_self_intersection(refit)
        and _struct_ok(refit)
        and _cu2qu_safe(refit)
        and _interp_ok(refit)
    ):
        note = "+".join(filter(None, (info.get("note"), "union-heal", "cubic-refit")))
        return refit, {**info, "note": note}
    note = "+".join(filter(None, (info.get("note"), "union-heal")))
    return out, {**info, "note": note}


def _reconstruct_floating_contour(outlines_by_pos, reference_pos):
    """Reconstruct a separated top accent independently from a changing body.

    A body may change contour count while its accent remains a clean, detached
    contour (rcaron.ss03). Treating all contours as one topology can pair the
    accent with a body piece or fail the interpolation gate. This is a fallback
    only: every master must have exactly one contour wholly above all its other
    contours, and the recombined result still passes the normal gates.
    """
    body = {}
    floating = {}
    for pos, contours in outlines_by_pos.items():
        if len(contours) < 2:
            return None
        rings = [to_ring(contour)[0] for contour in contours]
        if any(len(ring) < 3 for ring in rings):
            return None
        boxes = [
            (min(point[1] for point in ring), max(point[1] for point in ring)) for ring in rings
        ]
        floating_index = max(range(len(contours)), key=lambda index: boxes[index][0])
        other_top = max(box[1] for index, box in enumerate(boxes) if index != floating_index)
        if boxes[floating_index][0] <= other_top + 1.0:
            return None
        body[pos] = [contour for index, contour in enumerate(contours) if index != floating_index]
        floating[pos] = [contours[floating_index]]

    body_out, _ = reconstruct(body, reference_pos)
    floating_out, _ = reconstruct(floating, reference_pos)
    if body_out is None or floating_out is None:
        return None
    combined = {pos: [*body_out[pos], *floating_out[pos]] for pos in outlines_by_pos}
    if (
        not _struct_ok(combined)
        or not _cu2qu_safe(combined)
        or not _interp_ok(combined)
        or _quality_offenders(combined, outlines_by_pos)
    ):
        return None
    return combined


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
    # A result that came through the compatible fast path IS the donor's own
    # drawing, so there is nothing for a resample of it to improve. It can still
    # lose: both score 0.0 coarse, the fine score is relative-only, and a denser
    # polyline wins that trivially -- `uni2088` lost at 0.00072 against 0.0 and
    # shipped as a 26-segment resample of a shape that was already correct.
    # Still challenge it when the ink is actually crossed, which is a real defect
    # wherever it comes from.
    if cross or (
        info.get("stage") != "compatible" and not info.get("note", "").startswith("uniform")
    ):
        aligned = _uniform_aligned(outlines_by_pos, reference_pos)
        if (
            aligned is not None
            and _struct_ok(aligned)
            and _cu2qu_safe(aligned)
            and _corner_correspondence_ok(aligned, outlines_by_pos)
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
        span, union_count = _span_defect(rings_a, rings_b, bbox, blur, INK_RES)
        if union_count < 500:
            # thin small glyphs (accents, quote ticks) cover too few pixels at
            # the base resolution for the ratio to mean anything — remeasure
            # with doubled resolution and proportionally scaled blur so the
            # physical tolerance stays the same.
            span, _ = _span_defect(rings_a, rings_b, bbox, blur * 2, INK_RES * 2)
        if span > worst:
            worst = span
    return worst


def _span_defect(rings_a, rings_b, bbox, blur, res):
    """Defect ratio for one span at a given raster resolution; returns
    (worst ratio over interior t, pre-blur union pixel count)."""
    ga = _rasterize(rings_a, bbox, res)
    gb = _rasterize(rings_b, bbox, res)
    inter = [ra & rb for ra, rb in zip(ga, gb, strict=False)]
    union = [ra | rb for ra, rb in zip(ga, gb, strict=False)]
    union_count = sum(row.bit_count() for row in union)
    for _ in range(blur):
        inter = _erode(inter, res)
        union = _dilate(union, res)
    # thin strokes can erode the endpoints' shared ink to almost nothing, which
    # would let a few noise pixels explode the ratio — floor the denominator at
    # a fraction of the (pre-blur) union ink instead.
    denom = max(sum(row.bit_count() for row in inter), union_count // 10, 1)
    worst = 0.0
    for t in (0.25, 0.5, 0.75):
        mid_rings = [
            [
                (p[0] * (1 - t) + q[0] * t, p[1] * (1 - t) + q[1] * t)
                for p, q in zip(ra, rb, strict=False)
            ]
            for ra, rb in zip(rings_a, rings_b, strict=False)
            if len(ra) == len(rb)
        ]
        gm = _rasterize(mid_rings, bbox, res)
        gm_d = list(gm)
        for _ in range(blur):
            gm_d = _dilate(gm_d, res)
        lost = sum((i & ~m).bit_count() for i, m in zip(inter, gm_d, strict=False))
        gained = sum((m & ~u).bit_count() for m, u in zip(gm, union, strict=False))
        ratio = (lost + gained) / denom
        if ratio > worst:
            worst = ratio
    return worst, union_count


def _rasterize(rings, bbox, res=INK_RES):
    """Nonzero-winding scanline raster of point rings onto a res-square grid.
    Each row is an int bitmask (bit c set = ink at column c)."""
    x0, y0, x1, y1 = bbox
    s = (res - 2) / (max(x1 - x0, y1 - y0) or 1.0)
    rows = [0] * res
    for row in range(res):
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
                c1 = min(res - 1, int((x - x0) * s))
                if c1 >= c0:
                    bits |= ((1 << (c1 - c0 + 1)) - 1) << c0
            wind += w
            prev = x
        rows[row] = bits
    return rows


def _erode(rows, res=INK_RES):
    mask = (1 << res) - 1
    n = len(rows)
    out = [0] * n
    for r in range(1, n - 1):
        bits = rows[r]
        out[r] = bits & (bits >> 1) & (bits << 1) & rows[r - 1] & rows[r + 1] & mask
    return out


def _dilate(rows, res=INK_RES):
    mask = (1 << res) - 1
    n = len(rows)
    out = [0] * n
    for r in range(n):
        bits = rows[r]
        if r > 0:
            bits |= rows[r - 1]
        if r < n - 1:
            bits |= rows[r + 1]
        out[r] = (bits | (bits >> 1) | (bits << 1)) & mask
    return out


def _reconstruct_base(outlines_by_pos, reference_pos=400):
    # Donor contour order can flip across weights even when each individual
    # contour keeps the same topology. Normalize before *every* reconstruction,
    # not only the already-compatible fast path: otherwise a full resample maps
    # contour 0 to a different piece at the heavy master (uni2787's circle and
    # numeral swap), then quite correctly fails the ink-quality gate.
    ordered = _order_normalize(outlines_by_pos, reference_pos)
    working = ordered if ordered is not None else outlines_by_pos
    # Order is not the only thing the donors disagree about. They also start the
    # same contour at different nodes, which `_starts_aligned` refuses -- and
    # refusing costs the whole drawing, because the fallback resamples and refits
    # a set of outlines that were compatible in every other respect. Rotating the
    # start is exact, so try it before giving up on the fast path.
    # Note the condition is on the RESULT, not on the input. Requiring the input
    # to be already-compatible is circular: a rotated start is itself what makes
    # `signature()` disagree, so the glyphs most in need of rotating are exactly
    # the ones such a guard excludes. `section` is written
    # `MLCCCCCLCCCLCCCCCLCCC` at Thin and ExtraBlack and `MCLCCCLCCCCCLCCCLCCCC`
    # at Book -- the same sequence turned by one node, and nothing else.
    # `_starts_aligned` indexes every master by the reference's contour count, so
    # it is only meaningful once they agree on how many contours there are.
    if len({len(contours) for contours in working.values()}) == 1 and not _starts_aligned(working):
        turned = _align_starts(working, reference_pos)
        # Accepted on structure alone, deliberately. Re-testing the rotated set
        # with `_starts_aligned` re-applies the absolute question the rotation
        # existed to answer, and throws away 110 glyphs' worth of exact donor
        # geometry; asking `_starts_correspond` instead is no test at all, since
        # `_align_starts` rotates by the offset that function checks for and the
        # answer is yes by construction (measured: 172 of 172). What actually
        # guards this is the gate below -- a rotation that corresponds the wrong
        # nodes fails `_interp_ok` or shows up as ink in `_quality_offenders`,
        # and falls through to reconstruction with the rotation still applied.
        if turned is not None and _already_compatible(turned):
            working = turned

    # Rotation alone cannot reconcile masters that spend different numbers of
    # segments on the same run. Splitting is exact, so bringing the sparser ones
    # up to the densest costs nothing but nodes -- and it is far cheaper than
    # what the alternative does, which is rebuild every master on a shared
    # polyline and refit the lot.
    if len({len(contours) for contours in working.values()}) == 1 and not _already_compatible(
        working
    ):
        # A line and a cubic drawn over the same chord are the same segment, so
        # normalise that away before asking whether the run patterns agree.
        unified = _unify_run_counts(_promote_lines_to_curves(working, reference_pos), reference_pos)
        # Unifying run counts gives no rotation freedom to a contour drawn
        # entirely in one kind: `_contour_runs` sees a single run and leaves the
        # start where it found it. So `threequarters` comes out with its repaired
        # `three` and a four-node fraction bar that ExtraBlack still starts two
        # nodes round, and because the gate is all-or-nothing across contours,
        # that one bar throws the whole repaired glyph away. Rotating afterwards
        # costs nothing and is now possible: unification has already made the
        # node counts equal, which is all `_align_starts` needs.
        if unified is not None and not (
            _starts_aligned(unified) or _starts_correspond(unified, reference_pos)
        ):
            returned = _align_starts(unified, reference_pos)
            if returned is not None and _already_compatible(returned):
                unified = returned
        if unified is not None and _already_compatible(unified):
            working = unified
    if (
        _already_compatible(working)
        and (_starts_aligned(working) or _starts_correspond(working, reference_pos))
        and _cu2qu_safe(working)
        and _interp_ok(working)
        and not _quality_offenders(working, outlines_by_pos)
        and not _has_interpolated_self_intersection(working)
    ):
        return working, {"stage": "compatible", "note": ""}

    # Counter-closing glyphs ($ ¢ etc.): their contour count drops at heavy
    # weights because the COUNTERS (negative-area holes) fill in. Splitting into
    # body + counter families, synthesising the closed counters, and
    # reconstructing each family independently preserves the shape far better
    # than bridging — try it first (gated on quality below).
    cc = _counter_closing(working, reference_pos)
    if (
        cc is not None
        and _struct_ok(cc)
        and _cu2qu_safe(cc)
        and not _quality_offenders(cc, outlines_by_pos)
        and _interp_ok(cc)
        and not _has_interpolated_self_intersection(cc)
    ):
        return cc, {"stage": "reconstructed", "note": "counter-closing"}

    # each variant is (outlines, reference_pos, tag)
    variants = [(working, reference_pos, "")]
    counts = {len(c) for c in working.values()}
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
    first_topology_candidate = None
    split_candidates = []
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
                if _has_interpolated_self_intersection(out):
                    last = {"stage": None, "note": "self-intersection gate"}
                    continue
                tags = []
                if tag:
                    tags.append(tag)
                if angle != CORNER_ANGLE_SWEEP[0]:
                    tags.append(f"angle={round(math.degrees(angle))}")
                if tags:
                    info["note"] = "+".join(tags)
                if len(counts) == 1:
                    return out, info
                if first_topology_candidate is None:
                    first_topology_candidate = (out, info)
                if tag == "split-to-max":
                    split_candidates.append((out, info))
                break
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
    best_relaxed = None  # interp soft, but no mid-axis SI
    best_relaxed_si = None  # last resort: weight varies even with mid SI
    for v_outlines, vref, tag in variants:
        for fn, note in ((_uniform_aligned, "uniform-aligned"), (_uniform, "uniform")):
            uni = fn(v_outlines, vref)
            if uni is None or not _struct_ok(uni) or not _cu2qu_safe(uni):
                continue
            if _quality_offenders(uni, outlines_by_pos):
                continue
            ink = _ink_defect(uni, blur=2)
            full = f"{note}+{tag}" if tag else note
            has_si = _has_interpolated_self_intersection(uni)
            clean = _interp_ok(uni) and not has_si
            if clean:
                if len(counts) > 1 and tag == "split-to-max":
                    split_candidates.append((uni, {"stage": "reconstructed", "note": full}))
                if best_uni is None or ink < best_uni[0] - 1e-9:
                    best_uni = (ink, uni, full)
                break  # aligned passed for this variant; skip its plain uniform
            # Topology-changing glyphs often fail the midpoint-area gate on every
            # corner path. Prefer weight-varying uniforms over freezing to
            # Book@400; still prefer non-SI over SI when both exist.
            slot = best_relaxed_si if has_si else best_relaxed
            if slot is None or ink < slot[0] - 1e-9:
                chosen = (ink, uni, f"{full}+relax-gates")
                if has_si:
                    best_relaxed_si = chosen
                else:
                    best_relaxed = chosen
    if first_topology_candidate is not None:
        # A contour-count change can often be represented in both directions:
        # split connected endpoint masters into real pieces, or bridge separate
        # pieces into one zero-width ring. Both preserve the masters, but a
        # bridge can open into a visible loop between them (r.ss03). Let viable
        # splits challenge the first passing repair on interpolated ink, while
        # retaining stable bridge ordering for transitions that cannot split
        # cleanly (Idieresis's 3→1→3 contour change).
        ranked = [
            candidate
            for candidate in [first_topology_candidate, *split_candidates]
            if not _has_interpolated_self_intersection(candidate[0])
        ]
        if ranked:
            return min(ranked, key=lambda candidate: _interpolation_rank(candidate[0]))
    if best_uni is not None:
        return best_uni[1], {"stage": "reconstructed", "note": best_uni[2]}
    if best_relaxed is not None:
        return best_relaxed[1], {"stage": "reconstructed", "note": best_relaxed[2]}
    if best_relaxed_si is not None:
        return best_relaxed_si[1], {"stage": "reconstructed", "note": best_relaxed_si[2]}
    return None, last


def _interpolation_rank(out):
    """Prefer clean topology, then the least mid-axis ink distortion."""
    return (
        _disjoint_cross(out),
        _has_interpolated_self_intersection(out),
        _ink_defect(out, blur=2),
        _ink_defect(out, blur=1),
    )


def _contours_self_intersect(contours) -> bool:
    """True when any outline segments cross, including across contours.

    Samples cubics/quads — a pure curveTo contour has no lineTo nodes, so using
    only on-curve move/line points was blind to real bowl/stem crossings.
    """
    rings = [_sampled_pts(contour) for contour in contours]
    segments: list[tuple[int, int, tuple[float, float], tuple[float, float]]] = []
    for contour_index, ring in enumerate(rings):
        count = len(ring)
        if count < 2:
            continue
        for segment_index in range(count):
            segments.append(
                (
                    contour_index,
                    segment_index,
                    ring[segment_index],
                    ring[(segment_index + 1) % count],
                )
            )
    for index, (contour_a, segment_a, a0, a1) in enumerate(segments):
        ring_len = len(rings[contour_a])
        for contour_b, segment_b, b0, b1 in segments[index + 1 :]:
            if contour_a == contour_b and (
                abs(segment_a - segment_b) <= 1 or {segment_a, segment_b} == {0, ring_len - 1}
            ):
                continue
            # Match check-glide-outlines / audit_support: collinear and near
            # grazes count. The stricter "proper cross" gate missed ExtraBlack
            # bowl/stem folds on d after the contrast transform.
            if segments_intersect(a0, a1, b0, b1):
                return True
    return False


def _has_interpolated_self_intersection(out):
    """Whether masters or in-between samples self-intersect (any contour pair)."""
    positions = sorted(out)
    for pos in positions:
        if _contours_self_intersect(out[pos]):
            return True
    for a, b in zip(positions, positions[1:], strict=False):
        for t in (0.25, 0.5, 0.75):
            contours = _interpolate_contours(out[a], out[b], t)
            if contours is None or _contours_self_intersect(contours):
                return True
    return False


SI_SAMPLE_STEPS = 8


def _sampled_pts(contour, steps=SI_SAMPLE_STEPS):
    """Closed-ring sample of a contour including cubic/quadratic curve chords."""
    pts: list[tuple[float, float]] = []
    cur = None
    for op, args in contour:
        if op == "moveTo":
            cur = args[0]
            pts = [cur]
        elif op == "lineTo":
            cur = args[0]
            pts.append(cur)
        elif op == "curveTo":
            c1, c2, end = args
            for i in range(1, steps + 1):
                pts.append(_cubic(cur, c1, c2, end, i / steps))
            cur = end
        elif op == "qCurveTo":
            # Explicit on-curve points only; off-curve chains are rare after
            # reconstruct (cu2qu / cubic-refit). Keep nodes for a coarse check.
            for p in args:
                if p is not None:
                    pts.append(p)
                    cur = p
    return pts


def _line_pts(contour):
    """Ordered point list of an all-line (moveTo + lineTo*) contour."""
    return [p[0] for op, p in contour if op in ("moveTo", "lineTo")]


def _outline_corner_count(contours):
    return sum(sum(corners) for contour in contours for _, _, corners in [to_ring(contour)])


def _shared_corner_candidates(outlines_by_pos, combine=min):
    """Rank polyline nodes that are sharp at the same index in every master.

    ``combine`` decides what "sharp" means across the masters. ``min`` asks
    whether every master turns there, which is the right question when the
    masters were corresponded by their own corners. ``max`` asks whether ANY of
    them does, which is the right question once `_project_contour_set` has given
    them a shared index space by construction -- see `_curve_corner_indices`.
    """
    positions = sorted(outlines_by_pos)
    if not positions:
        return []
    candidates = []
    contour_count = len(outlines_by_pos[positions[0]])
    for ci in range(contour_count):
        rings = {pos: _line_pts(outlines_by_pos[pos][ci]) for pos in positions}
        if not rings[positions[0]] or len({len(ring) for ring in rings.values()}) != 1:
            continue
        for index in range(len(rings[positions[0]])):
            score = combine(_polyline_turn(rings[pos], index) for pos in positions)
            if score > CURVE_CORNER_ANGLE:
                candidates.append((score, ci, index))
    return candidates


def _expected_corner_count(originals_by_pos):
    """Shared hard-corner budget for cubic-refit.

    Unanimous counts win. A single-corner flicker across masters (CFF stub
    inventing one false corner on Thin ``d``) uses the majority. Wider
    disagreement is a real topology difference — return None so cubic-refit
    does not invent a wrong hard-corner set.
    """
    counts = [_outline_corner_count(contours) for contours in originals_by_pos.values()]
    if not counts:
        return None
    distinct = set(counts)
    if len(distinct) == 1:
        return counts[0]
    if max(counts) - min(counts) > 1:
        return None
    return sorted(distinct, key=lambda c: (-counts.count(c), c))[0]


def _corner_correspondence_ok(candidate, originals_by_pos):
    """Reject a fallback that moves donor corners to different point indices."""
    expected = _expected_corner_count(originals_by_pos)
    return expected in (None, 0) or len(_shared_corner_candidates(candidate)) >= expected


def _reference_corner_candidates(outlines_by_pos, reference_pos=400):
    """Sharp polyline nodes on the reference master (projection-aligned structure)."""
    if reference_pos not in outlines_by_pos:
        reference_pos = sorted(outlines_by_pos)[len(outlines_by_pos) // 2]
    candidates = []
    for ci, contour in enumerate(outlines_by_pos[reference_pos]):
        pts = _line_pts(contour)
        for index in range(len(pts)):
            score = _polyline_turn(pts, index)
            if score > CURVE_CORNER_ANGLE:
                candidates.append((score, ci, index))
    return candidates


def _curve_corner_indices(outlines_by_pos, originals_by_pos):
    candidates = _shared_corner_candidates(outlines_by_pos)
    expected = _expected_corner_count(originals_by_pos) if originals_by_pos is not None else None
    if originals_by_pos is not None and expected is None and len(outlines_by_pos) > 1:
        # `_expected_corner_count` gives up when the masters disagree about how
        # many corners they have by more than one, which is `dollar` ([20, 20,
        # 12] -- the counters fill in at ExtraBlack) and `cent`. That is the case
        # where scoring an index by the MINIMUM turn is most destructive: it
        # keeps only what is sharp in the thinnest and the fattest at once, four
        # of `dollar`'s thirteen real corners, and the fitter then subdivides
        # around the nine it cannot see. Anchoring on a node that is smooth in
        # one master costs that master a node it did not need; burying a corner
        # costs a fan of cubics trying to hold it.
        union = _shared_corner_candidates(outlines_by_pos, combine=max)
        if len(union) > len(candidates):
            candidates = union
    if expected is not None and len(candidates) < expected:
        # Index-matched sharps can be empty when a false donor corner forced
        # arc-length projection: anchors share indices with the reference, but
        # other masters are smooth there. Take every master's sharps rather than
        # only the reference's -- the reference cannot know where the others
        # turn, and anchoring on its corners alone leaves theirs buried inside a
        # fit run, where the fitter subdivides trying to hold a right angle with
        # a cubic. `iogonek` arrived as 10 mostly-straight donor segments and
        # left as 32 all-curve ones that way. The union's own size is then the
        # budget: it is the set of real corners, not a count borrowed from the
        # donor.
        candidates = _shared_corner_candidates(outlines_by_pos, combine=max)
        expected = None
    if expected is not None:
        if len(candidates) < expected:
            return None
        candidates = sorted(candidates, reverse=True)[:expected]
    selected = {ci: set() for ci in range(len(outlines_by_pos[next(iter(outlines_by_pos))]))}
    for _, ci, index in candidates:
        selected[ci].add(index)
    return selected


def _stabilize_cubic_joins(contours_by_pos, hard_corners_by_pos):
    """Keep each smooth join's handle-length ratio constant across masters.

    G1 handles with a different incoming/outgoing ratio at each endpoint master
    need not remain collinear when their coordinates interpolate. Use one shared
    ratio while preserving each master's total arm length, which changes the fit
    minimally and guarantees the same tangent through every in-between weight.
    """
    positions = sorted(contours_by_pos)
    segments = {pos: contours_by_pos[pos][1:-1] for pos in positions}
    if not positions or len(segments[positions[0]]) < 2:
        return
    for index in range(len(segments[positions[0]])):
        pairs = {pos: (segments[pos][index - 1], segments[pos][index]) for pos in positions}
        if any(
            previous[0] != "curveTo" or current[0] != "curveTo"
            for previous, current in pairs.values()
        ):
            continue
        if any(
            any(_dist(previous[1][-1], point) < 1e-6 for point in hard_corners_by_pos[pos])
            for pos, (previous, _) in pairs.items()
        ):
            continue
        lengths = {}
        for pos, (previous, current) in pairs.items():
            join = previous[1][-1]
            incoming = _dist(previous[1][-2], join)
            outgoing = _dist(join, current[1][0])
            if incoming <= 1e-9 or outgoing <= 1e-9:
                break
            lengths[pos] = (incoming, outgoing)
        if len(lengths) != len(positions):
            continue
        ratio = math.exp(sum(math.log(a / b) for a, b in lengths.values()) / len(lengths))
        for pos, (previous, current) in pairs.items():
            join = previous[1][-1]
            incoming = _unit(previous[1][-2], join)
            outgoing = _unit(join, current[1][0])
            direction = (incoming[0] + outgoing[0], incoming[1] + outgoing[1])
            magnitude = math.hypot(*direction)
            if magnitude <= 1e-9:
                continue
            direction = (direction[0] / magnitude, direction[1] / magnitude)
            total = sum(lengths[pos])
            incoming_length = total * ratio / (1 + ratio)
            outgoing_length = total / (1 + ratio)
            previous[1][-2] = (
                join[0] - direction[0] * incoming_length,
                join[1] - direction[1] * incoming_length,
            )
            current[1][0] = (
                join[0] + direction[0] * outgoing_length,
                join[1] + direction[1] * outgoing_length,
            )


#: Spacing, in font units, of the analytic tangent index built from the donor.
#: Two units is the same resolution the curve-quality audit samples curvature at,
#: and it is well under the resampler's 18-unit step, so the nearest indexed
#: sample to a run endpoint is always on the right stretch of curve.
#: Fit run endpoints to the donor's own tangent instead of the polyline secant.
#:
#: MEASURED, AND OFF BY DEFAULT. `_fit_start_tangent` estimates a tangent from
#: the first chord of an 18-unit polyline. A chord is an O(h) estimator, so it is
#: wrong by degrees on a tight curve, and because `_stabilize_cubic_joins` then
#: forces the arms collinear about the node the error cannot surface as a kink --
#: it is spent entirely as curvature. That is why the audit finds no smooth-node
#: kink above half a degree while counting 1281 G2 breaks.
#:
#: Substituting the donor's own tangent confirms the diagnosis. Measured on the
#: flagged glyphs that still take the refit path after `_align_starts` has done
#: its work, as ripple at wght 950:
#:
#:     median -6.1%, 20 better, 7 worse, 4 unchanged
#:
#: The wins are large and on shapes people complain about -- `ampersand` 269.86
#: -> 18.90, `section` 38.28 -> 9.59, `uni2782` 591.14 -> 166.30, `infinity`
#: 7.88 -> 2.56. So do the losses: `currency` 1.04 -> 1.73, `uni2079` and
#: `uni2089` 22.04 -> 32.05.
#:
#: It is off because of those seven, not because of the median. The release gate
#: is a ratchet -- no glyph may score worse than its recorded baseline -- so this
#: lands as part of a change that also fixes where the splits go, and is
#: re-baselined once. On its own it would have to be argued glyph by glyph.
#:
#: The tangent is found by arc-length position around the contour, not by nearest
#: point. Nearest point was tried first and cannot work: the match is exact --
#: median distance zero -- but a run endpoint sits ON a node where two edges meet
#: with different tangents, and distance cannot say which edge this run travels
#: along. Three threshold variants each only traded one glyph against another.
#: Ordering was the missing constraint, not a tighter bound.
DONOR_TANGENTS = False

#: Sampling resolution of the donor curve, in font units.
DONOR_TANGENT_STEP = 0.25

#: A run endpoint further than this from the donor's own outline is not a point
#: on it. The resampler only ever places points on the polyline through the
#: donor's curve, so the true distance is a sagitta -- under three units on the
#: tightest curve in the family. Past this, the projection has found some other
#: stroke and its tangent would be worse than the secant it replaces.
DONOR_TANGENT_REACH = 2.0

#: A donor tangent disagreeing with the secant by more than this has not found
#: the run's own curve. The secant is a poor estimate of the ANGLE -- that is the
#: whole reason for this index -- but it is a reliable estimate of the DIRECTION,
#: because it is built from points that genuinely lie along the run. So a wide
#: disagreement means the nearest indexed sample belongs to some other stroke
#: passing close by, and taking its tangent would be worse than doing nothing.
DONOR_TANGENT_MAX_TURN = 10.0


def _analytic_ring(contour):
    """Dense samples of one donor contour: (point, tangent, arclength-so-far).

    Lines are included as well as curves. A tangent is only ever asked for on a
    curve -- straight runs never reach the fitter -- but the walk that finds
    *which* part of the curve a point belongs to has to traverse the straight
    stretches too, or it loses its place on any glyph with a flat side.
    """
    samples = []
    here = None
    total = 0.0

    def emit(point, tangent):
        nonlocal total
        if samples:
            total += math.hypot(point[0] - samples[-1][0][0], point[1] - samples[-1][0][1])
        samples.append((point, tangent, total))

    for op, pts in contour or ():
        if not pts:
            continue
        if op == "moveTo":
            here = pts[-1]
            continue
        if op == "lineTo":
            end = pts[-1]
            if here is not None:
                tangent = _unit(here, end)
                steps = max(1, int(_dist(here, end) / DONOR_TANGENT_STEP))
                for index in range(steps + 1):
                    t = index / steps
                    emit(
                        (here[0] + (end[0] - here[0]) * t, here[1] + (end[1] - here[1]) * t),
                        tangent,
                    )
            here = end
            continue
        if op == "curveTo" and here is not None and len(pts) == 3:
            c1, c2, p3 = pts
            p0 = here
            length = _dist(p0, c1) + _dist(c1, c2) + _dist(c2, p3)
            steps = max(2, int(length / DONOR_TANGENT_STEP))
            for index in range(steps + 1):
                t = index / steps
                u = 1 - t
                dx = (
                    3 * u * u * (c1[0] - p0[0])
                    + 6 * u * t * (c2[0] - c1[0])
                    + 3 * t * t * (p3[0] - c2[0])
                )
                dy = (
                    3 * u * u * (c1[1] - p0[1])
                    + 6 * u * t * (c2[1] - c1[1])
                    + 3 * t * t * (p3[1] - c2[1])
                )
                norm = math.hypot(dx, dy)
                emit(_cubic(p0, c1, c2, p3, t), (dx / norm, dy / norm) if norm > 1e-9 else None)
            here = p3
            continue
        if op == "qCurveTo":
            here = pts[-1]
    return samples, total


def _match_original(ring, originals):
    """Which donor contour this resampled ring is a polyline of.

    Contour order does not survive the reconstruction, so this is matched by
    where the contour sits and how big it is -- the same reasoning the circle
    roster uses, and for the same reason.
    """
    if not originals or not ring:
        return None
    rx = sum(point[0] for point in ring) / len(ring)
    ry = sum(point[1] for point in ring) / len(ring)
    rw = max(point[0] for point in ring) - min(point[0] for point in ring)
    rh = max(point[1] for point in ring) - min(point[1] for point in ring)
    best = None
    best_cost = None
    for contour in originals:
        points = [point for _, pts in contour for point in pts if point]
        if not points:
            continue
        cx = sum(point[0] for point in points) / len(points)
        cy = sum(point[1] for point in points) / len(points)
        cw = max(point[0] for point in points) - min(point[0] for point in points)
        ch = max(point[1] for point in points) - min(point[1] for point in points)
        cost = math.hypot(cx - rx, cy - ry) + abs(cw - rw) + abs(ch - rh)
        if best_cost is None or cost < best_cost:
            best_cost, best = cost, contour
    return best


class _RingTangents:
    """Tangents on the donor's own curve, found by position AROUND the contour.

    Matching a resampled point to the donor by nearest point alone does not
    work, and the way it fails is instructive: the match is exact -- the median
    distance is zero -- but a run endpoint sits ON a node, two edges meet there
    with different tangents, and nothing about distance says which of them this
    run travels along. Picking wrong substitutes a tangent pointing back down
    the other edge, which is worse than the secant it replaced. Thresholds
    cannot fix that, because the two candidates are equidistant by construction.

    Arc length can. The ring is a polyline of this contour and runs the same way
    around it, so a point's fraction of the way around the ring is its fraction
    of the way around the donor. That fixes an ordering, and ordering is exactly
    what distance was missing: the answer is refined to the nearest sample near
    the predicted place rather than the nearest sample anywhere.
    """

    #: Refinement window, as a fraction of the contour. Wide enough to absorb the
    #: length a polyline loses to its chords, far too narrow to reach the other
    #: side of a node.
    WINDOW = 0.02

    def __init__(self, ring, original):
        self.samples, self.total = _analytic_ring(original)
        self.ok = bool(self.samples) and self.total > 0 and len(ring) > 2
        if not self.ok:
            return
        lengths = [0.0]
        for index in range(1, len(ring)):
            lengths.append(lengths[-1] + _dist(ring[index - 1], ring[index]))
        lengths.append(lengths[-1] + _dist(ring[-1], ring[0]))
        self.ring_total = lengths[-1] or 1.0
        self.lengths = lengths
        start = min(range(len(self.samples)), key=lambda i: _dist(self.samples[i][0], ring[0]))
        self.offset = self.samples[start][2]
        # The ring may run the other way round the contour than the donor does.
        # One probe settles it: take a point a little along the ring and see
        # whether its match lies ahead of the start or behind it.
        probe = min(len(ring) - 1, max(1, len(ring) // 8))
        ahead = min(range(len(self.samples)), key=lambda i: _dist(self.samples[i][0], ring[probe]))
        delta = (self.samples[ahead][2] - self.offset) % self.total
        self.forward = delta < self.total / 2

    def at(self, index, point, hint):
        """The donor's tangent where ring point ``index`` sits, oriented by hint."""
        if not self.ok or index >= len(self.lengths):
            return None
        fraction = self.lengths[index] / self.ring_total
        travelled = fraction * self.total
        target = (
            (self.offset + travelled) % self.total
            if self.forward
            else (self.offset - travelled) % self.total
        )
        window = self.WINDOW * self.total
        best = None
        best_distance = None
        for sample, tangent, position in self.samples:
            if tangent is None:
                continue
            gap = abs(position - target)
            if min(gap, self.total - gap) > window:
                continue
            distance = _dist(sample, point)
            if best_distance is None or distance < best_distance:
                best_distance, best = distance, tangent
        if best is None:
            return None
        if best[0] * hint[0] + best[1] * hint[1] < 0:
            best = (-best[0], -best[1])
        aligned = max(-1.0, min(1.0, best[0] * hint[0] + best[1] * hint[1]))
        if math.degrees(math.acos(aligned)) > DONOR_TANGENT_MAX_TURN:
            return None
        return best


def _restore_compatible_curves(outlines_by_pos, originals_by_pos=None):
    """Replace temporary compatibility polylines with shared cubic structure.

    Resampling is useful for establishing point correspondence, but those dense
    line segments are an implementation detail, not a suitable final outline.
    Fit every corresponding master at once: a span is accepted only when it is
    within tolerance in *all* masters, and a failure splits every master at the
    same sample index.  The controls remain master-specific while the segment
    structure therefore stays interpolation-compatible.
    """
    positions = sorted(outlines_by_pos)
    if not positions or any(
        any(op not in ("moveTo", "lineTo", "closePath") for con in contours for op, _ in con)
        for contours in outlines_by_pos.values()
    ):
        return None
    contour_count = len(outlines_by_pos[positions[0]])
    if any(len(outlines_by_pos[pos]) != contour_count for pos in positions):
        return None
    selected_corners = _curve_corner_indices(outlines_by_pos, originals_by_pos)
    if selected_corners is None:
        return None

    result = {pos: [] for pos in positions}
    for ci in range(contour_count):
        rings = {pos: _line_pts(outlines_by_pos[pos][ci]) for pos in positions}
        # The fitter's own view of a run endpoint is the first chord of an
        # 18-unit polyline: an O(h) estimate of a tangent, wrong by degrees on a
        # tight curve, and spent entirely as curvature once the joins are made
        # collinear. The donor's own tangent at the same place is exact.
        donor_tangents = (
            {
                pos: _RingTangents(
                    rings[pos], _match_original(rings[pos], originals_by_pos.get(pos))
                )
                for pos in positions
            }
            if DONOR_TANGENTS and originals_by_pos
            else None
        )
        counts = {len(ring) for ring in rings.values()}
        if len(counts) != 1 or not counts or next(iter(counts)) < 3:
            return None
        count = next(iter(counts))
        hard_corners = selected_corners[ci]
        corners = sorted(hard_corners)
        # A closed smooth path cannot be fitted as one span because its endpoints
        # coincide. It needs four anchors, and WHERE they go decides whether the
        # result reads as a drawn outline.
        #
        # Arc-order quarters (0, n/4, n/2, 3n/4) are stable but arbitrary: they
        # land wherever the resampler happened to step, so a bowl comes out with
        # its nodes off the extremes and every extremum buried mid-segment. That
        # is the measured defect -- Glide's `o` carries nodes at (286.5, 460.3)
        # where the donor puts them on the axis extremes, and 415 glyphs have at
        # least one extremum with no node on it.
        #
        # The axis extremes of the reference ring are just as stable, shared
        # across masters by index like the quarters they replace, and cost no
        # extra nodes -- the same four anchors, moved to where a type designer
        # would put them. Anything the fitter still needs is added between them
        # as before.
        # Extrema anchor EVERY contour, not only the fully smooth ones. Gating
        # this on `len(corners) < 2` reached bowls and circles but skipped every
        # glyph that has a corner anywhere in it, which is most of them, and left
        # 2731 extrema with no node on them.
        # REVERTED: anchoring smooth contours at axis extremes and exact
        # turning points. It measured well in aggregate (missing extrema 2842 ->
        # 2364, curvature roughness 7.26 -> 5.43, node count slightly down) but
        # put a visible flat facet and corner into the inner notch of `tilde`,
        # and with it every tilde-bearing glyph -- 1.9% of the glyph's ink moved.
        # Three attempts to keep the gains without the damage all failed:
        # local-extrema detection shattered straight edges, per-master snapping
        # broke cross-master compatibility, and dropping the box extremes in
        # favour of exact turning points regressed 109 glyphs (`degree` 2.5 ->
        # 73.4). Node placement on a sinuous contour needs anchors chosen by
        # shape -- inflections for an S, box extremes for a bowl -- which is a
        # real piece of work, not a threshold to tune.
        #
        # `outlineGrid` in `outlines.draw_into` is kept: it only rounds
        # coordinates, changes no structure, and is measured shape-neutral.
        if len(corners) < 2:
            corners = sorted({*corners, 0, count // 4, count // 2, 3 * count // 4})
        elif 0 not in corners:
            corners = [0, *corners]

        contours = {pos: [("moveTo", [rings[pos][corners[0]]])] for pos in positions}
        for run, start in enumerate(corners):
            end = corners[(run + 1) % len(corners)]
            samples = {pos: _cyclic_slice(rings[pos], start, end) for pos in positions}
            if _shared_straight(samples):
                for pos in positions:
                    contours[pos].append(("lineTo", [samples[pos][-1]]))
                continue
            start_tangents = end_tangents = None
            if donor_tangents:
                start_tangents, end_tangents = {}, {}
                for pos in positions:
                    points = samples[pos]
                    start_hint = _fit_start_tangent(points)
                    end_hint = _fit_end_tangent(points)
                    finish = end if end > start else end + count
                    start_tangents[pos] = (
                        donor_tangents[pos].at(start, points[0], start_hint) or start_hint
                    )
                    end_tangents[pos] = (
                        donor_tangents[pos].at(finish % count, points[-1], end_hint) or end_hint
                    )
            fitted = _fit_shared_cubics(samples, CURVE_FIT_TOLERANCE, start_tangents, end_tangents)
            for pos in positions:
                contours[pos].extend(("curveTo", [c1, c2, p3]) for c1, c2, p3 in fitted[pos])
        for pos in positions:
            contours[pos].append(("closePath", []))
            result[pos].append(contours[pos])
        _stabilize_cubic_joins(
            {pos: result[pos][-1] for pos in positions},
            {pos: {rings[pos][index] for index in hard_corners} for pos in positions},
        )
    return result if _cu2qu_safe(result) else None


def _polyline_turn(points, i):
    prev = points[(i - 1) % len(points)]
    point = points[i]
    nxt = points[(i + 1) % len(points)]
    incoming = _unit(prev, point)
    outgoing = _unit(point, nxt)
    dot = max(-1.0, min(1.0, incoming[0] * outgoing[0] + incoming[1] * outgoing[1]))
    return math.acos(dot)


def _cyclic_slice(points, start, end):
    if start < end:
        return points[start : end + 1]
    return points[start:] + points[: end + 1]


def _shared_straight(samples):
    for points in samples.values():
        start, end = points[0], points[-1]
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            return False
        for point in points[1:-1]:
            distance = abs((point[0] - start[0]) * dy - (point[1] - start[1]) * dx) / length
            if distance > CURVE_LINE_TOLERANCE:
                return False
    return True


def _fit_shared_cubics(samples, tolerance, start_tangents=None, end_tangents=None):
    """Schneider-style cubic fit with synchronized split indices."""
    positions = sorted(samples)
    if len(samples[positions[0]]) <= 2:
        return {
            pos: [
                (
                    (
                        samples[pos][0][0] + (samples[pos][-1][0] - samples[pos][0][0]) / 3,
                        samples[pos][0][1] + (samples[pos][-1][1] - samples[pos][0][1]) / 3,
                    ),
                    (
                        samples[pos][0][0] + 2 * (samples[pos][-1][0] - samples[pos][0][0]) / 3,
                        samples[pos][0][1] + 2 * (samples[pos][-1][1] - samples[pos][0][1]) / 3,
                    ),
                    samples[pos][-1],
                )
            ]
            for pos in positions
        }
    if start_tangents is None:
        start_tangents = {pos: _fit_start_tangent(samples[pos]) for pos in positions}
    if end_tangents is None:
        end_tangents = {pos: _fit_end_tangent(samples[pos]) for pos in positions}

    cubics = {}
    errors = {}
    for pos in positions:
        points = samples[pos]
        params = _chord_parameters(points)
        cubic = _fit_one_cubic(points, params, start_tangents[pos], end_tangents[pos])
        for _ in range(4):
            revised = _reparameterize(points, cubic, params)
            if revised is None:
                break
            params = revised
            cubic = _fit_one_cubic(points, params, start_tangents[pos], end_tangents[pos])
        cubics[pos] = cubic
        errors[pos] = _fit_error(points, cubic, params)
    worst_pos = max(positions, key=lambda pos: errors[pos][0])
    worst_error, split = errors[worst_pos]
    if worst_error <= tolerance:
        return {pos: [(cubics[pos][1], cubics[pos][2], cubics[pos][3])] for pos in positions}

    split = min(max(split, 1), len(samples[worst_pos]) - 2)
    center = {pos: _fit_center_tangent(samples[pos], split) for pos in positions}
    left_samples = {pos: samples[pos][: split + 1] for pos in positions}
    right_samples = {pos: samples[pos][split:] for pos in positions}
    left = _fit_shared_cubics(
        left_samples,
        tolerance,
        start_tangents,
        {pos: (-center[pos][0], -center[pos][1]) for pos in positions},
    )
    right = _fit_shared_cubics(right_samples, tolerance, center, end_tangents)
    return {pos: [*left[pos], *right[pos]] for pos in positions}


def _fit_start_tangent(points):
    for point in points[1:]:
        tangent = _unit(points[0], point)
        if tangent != (0.0, 0.0):
            return tangent
    return (1.0, 0.0)


def _fit_end_tangent(points):
    for point in reversed(points[:-1]):
        tangent = _unit(points[-1], point)
        if tangent != (0.0, 0.0):
            return tangent
    return (-1.0, 0.0)


def _fit_center_tangent(points, split):
    tangent = _unit(points[split - 1], points[split + 1])
    if tangent == (0.0, 0.0):
        tangent = _fit_start_tangent(points[split:])
    return tangent


def _chord_parameters(points):
    distances = [_dist(points[i - 1], points[i]) for i in range(1, len(points))]
    total = sum(distances)
    if total <= 1e-9:
        return [i / (len(points) - 1) for i in range(len(points))]
    params = [0.0]
    for distance in distances:
        params.append(params[-1] + distance / total)
    params[-1] = 1.0
    return params


def _fit_one_cubic(points, params, start_tangent, end_tangent):
    p0, p3 = points[0], points[-1]
    c00 = c01 = c11 = x0 = x1 = 0.0
    for point, u in zip(points, params, strict=True):
        v = 1.0 - u
        b0, b1, b2, b3 = v**3, 3 * u * v**2, 3 * u**2 * v, u**3
        ax = start_tangent[0] * b1
        ay = start_tangent[1] * b1
        bx = end_tangent[0] * b2
        by = end_tangent[1] * b2
        rx = point[0] - (p0[0] * (b0 + b1) + p3[0] * (b2 + b3))
        ry = point[1] - (p0[1] * (b0 + b1) + p3[1] * (b2 + b3))
        c00 += ax * ax + ay * ay
        c01 += ax * bx + ay * by
        c11 += bx * bx + by * by
        x0 += ax * rx + ay * ry
        x1 += bx * rx + by * ry
    determinant = c00 * c11 - c01 * c01
    alpha1 = (x0 * c11 - x1 * c01) / determinant if abs(determinant) > 1e-12 else 0.0
    alpha2 = (c00 * x1 - c01 * x0) / determinant if abs(determinant) > 1e-12 else 0.0
    chord = _dist(p0, p3)
    epsilon = chord * 1e-6
    if alpha1 < epsilon or alpha2 < epsilon:
        alpha1 = alpha2 = chord / 3.0
    return (
        p0,
        (p0[0] + start_tangent[0] * alpha1, p0[1] + start_tangent[1] * alpha1),
        (p3[0] + end_tangent[0] * alpha2, p3[1] + end_tangent[1] * alpha2),
        p3,
    )


def _fit_error(points, cubic, params):
    worst = (0.0, 1)
    for i, (point, u) in enumerate(zip(points[1:-1], params[1:-1], strict=True), start=1):
        error = _dist(point, _cubic(*cubic, u))
        if error > worst[0]:
            worst = (error, i)
    # The samples-to-curve direction alone misses a fitted loop or bulge between
    # samples. Check the reverse direction too, against the corresponding
    # polyline chord; this is what prevents a numerically valid fit from losing
    # half the ink area on intricate contours such as italic aogonek.
    for i, (u0, u1) in enumerate(zip(params, params[1:], strict=False)):
        for fraction in (0.25, 0.5, 0.75):
            point = _cubic(*cubic, u0 + (u1 - u0) * fraction)
            error = _point_segment_distance(point, points[i], points[i + 1])
            if error > worst[0]:
                worst = (error, min(max(i + 1, 1), len(points) - 2))
    return worst


def _point_segment_distance(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length2 = dx * dx + dy * dy
    if length2 <= 1e-18:
        return _dist(point, start)
    t = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length2
    t = max(0.0, min(1.0, t))
    return _dist(point, (start[0] + t * dx, start[1] + t * dy))


def _reparameterize(points, cubic, params):
    revised = [0.0]
    for point, u in zip(points[1:-1], params[1:-1], strict=True):
        q = _cubic(*cubic, u)
        q1 = _cubic_derivative(cubic, u)
        q2 = _cubic_second_derivative(cubic, u)
        dx, dy = q[0] - point[0], q[1] - point[1]
        denominator = q1[0] ** 2 + q1[1] ** 2 + dx * q2[0] + dy * q2[1]
        new_u = u if abs(denominator) <= 1e-12 else u - (dx * q1[0] + dy * q1[1]) / denominator
        revised.append(max(0.0, min(1.0, new_u)))
    revised.append(1.0)
    if any(a >= b for a, b in zip(revised, revised[1:], strict=False)):
        return None
    return revised


def _cubic_derivative(cubic, t):
    p0, p1, p2, p3 = cubic
    u = 1.0 - t
    return (
        3 * u * u * (p1[0] - p0[0]) + 6 * u * t * (p2[0] - p1[0]) + 3 * t * t * (p3[0] - p2[0]),
        3 * u * u * (p1[1] - p0[1]) + 6 * u * t * (p2[1] - p1[1]) + 3 * t * t * (p3[1] - p2[1]),
    )


def _cubic_second_derivative(cubic, t):
    p0, p1, p2, p3 = cubic
    return (
        6 * ((1 - t) * (p2[0] - 2 * p1[0] + p0[0]) + t * (p3[0] - 2 * p2[0] + p1[0])),
        6 * ((1 - t) * (p2[1] - 2 * p1[1] + p0[1]) + t * (p3[1] - 2 * p2[1] + p1[1])),
    )


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
    # match contours across masters by geometry, NOT raw index: donors are free
    # to draw a quote's two ticks in opposite orders at different weights, and
    # index pairing then interpolates the pieces through each other.
    ordered = _order_normalize(outlines_by_pos, reference_pos)
    if ordered is not None:
        outlines_by_pos = ordered
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


def _interpolate_contours(contours_a, contours_b, t):
    """Interpolate compatible segment structures without flattening controls."""
    if len(contours_a) != len(contours_b):
        return None
    out = []
    for contour_a, contour_b in zip(contours_a, contours_b, strict=True):
        if len(contour_a) != len(contour_b):
            return None
        contour = []
        for (op_a, points_a), (op_b, points_b) in zip(contour_a, contour_b, strict=True):
            if op_a != op_b or len(points_a) != len(points_b):
                return None
            points = []
            for point_a, point_b in zip(points_a, points_b, strict=True):
                if point_a is None or point_b is None:
                    if point_a is not None or point_b is not None:
                        return None
                    points.append(None)
                else:
                    points.append(
                        (
                            point_a[0] * (1 - t) + point_b[0] * t,
                            point_a[1] * (1 - t) + point_b[1] * t,
                        )
                    )
            contour.append((op_a, points))
        out.append(contour)
    return out


def _interp_ok(out, tol=0.18, perim_tol=0.83):
    """A point-compatible reconstruction can still interpolate badly if point
    correspondence across masters is wrong (e.g. k's diagonal): the masters look
    fine but the in-between weights collapse. Interpolate the actual segment
    structure of each adjacent master pair at t=0.5 and require the midpoint ink
    area to stay near the mean of the two endpoints — a collapse spikes it away.
    Cubic controls remain controls here; treating them as polygon vertices rejects
    clean curves and is not the geometry the variable font renders.

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
        mid = _interpolate_contours(ca, cb, 0.5)
        if mid is None:
            return False
        for con_a, con_b, con_m in zip(ca, cb, mid, strict=True):
            ring_a = to_ring(con_a)[0]
            ring_b = to_ring(con_b)[0]
            ring_m = to_ring(con_m)[0]
            if len(ring_m) >= 3:
                pm = _ring_perimeter(ring_m)
                pmean = (_ring_perimeter(ring_a) + _ring_perimeter(ring_b)) / 2
                # ignore tiny contours (accent dots): a few units of rounding
                # would dominate the ratio
                if pmean > 500 and pm / pmean < perim_tol:
                    return False
        if abs(_glyph_area(mid) / mean - 1.0) > tol:
            return False
        # per-contour safety net: a single contour CROSSING itself (e.g. the %
        # slash twisting into a bowtie) barely moves the total area but collapses
        # its own to near-zero. Only flag a severe collapse (< 45% of the mean) so
        # counters that legitimately shrink with weight (8, 0) aren't false-failed.
        for con_a, con_b, con_m in zip(ca, cb, mid, strict=True):
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
        if not entries:
            return None
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
    slot_total_area = sum(abs(_signed_area(slot[1])) for slot in slots) or 1.0

    fams = [dict() for _ in range(nslot)]  # slot -> {pos: (contour, ring, centroid)}
    for pos in positions:
        used = set()
        entry_total_area = sum(abs(_signed_area(entry[1])) for entry in parts[pos]) or 1.0
        for entry in parts[pos]:
            cand = [s for s in range(nslot) if slots[s][3] == entry[3] and s not in used]
            if not cand:
                continue  # an extra contour with no matching slot — dropped (gate catches)
            entry_fraction = abs(_signed_area(entry[1])) / entry_total_area
            s = min(
                cand,
                key=lambda slot_index: (
                    _dist(entry[2], slots[slot_index][2])
                    + abs(
                        entry_fraction - abs(_signed_area(slots[slot_index][1])) / slot_total_area
                    )
                    * 1000
                ),
            )
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
    # Nubs intentionally overlap the body so KEEP_OVERLAPS paints a solid join.
    # Boolean-union + re-reconstruct so masters stay interpolatable and the
    # outline audit no longer sees the overlap as a self-intersection.
    overlapped = {
        pos: [body_out[pos], *_bar_nubs(body_out[pos], bar_geom[pos])] for pos in positions
    }
    unioned = {pos: union_overlaps(overlapped[pos]) for pos in positions}
    if any(contours is None for contours in unioned.values()):
        return overlapped
    rec, _info = reconstruct(unioned, reference_pos=ref)
    return rec if rec is not None else unioned


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
    if target < 1:
        return None
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
    """Match contours by centroid, winding role and relative ink area.

    Area disambiguates concentric same-winding pieces such as uni2787's outer
    circle and numeral body, whose centroids are effectively identical. Optimal
    assignment (all permutations) for small
    contour counts: greedy matching can assign a CROSSING pairing (left quote
    tick to right tick) when the ref contour it visits first sits between two
    candidates, and a crossed pairing interpolates pieces through each other.
    Greedy remains the fallback for many-contour glyphs."""

    def feats(rings):
        pts = [p for r in rings for p in r[0]]
        if not pts:
            return []
        x0, y0, x1, y1 = _pts_bbox(pts)
        w = (x1 - x0) or 1.0
        h = (y1 - y0) or 1.0
        areas = [_signed_area(r[0]) for r in rings]
        total_area = sum(abs(area) for area in areas) or 1.0
        # normalise winding so the dominant (largest) contour is +1: donors flip
        # overall orientation between masters (Neuton's ExtraBold), and raw
        # signs then steer the body to pair with a COUNTER whose flipped sign
        # happens to "match"
        dom = 1 if areas[max(range(len(rings)), key=lambda i: abs(areas[i]))] >= 0 else -1
        out = []
        for r, a in zip(rings, areas, strict=False):
            c = _centroid(r[0])
            # centroid NORMALIZED to this master's own bbox: absolute positions
            # shift with weight (g's counters travel), and absolute distance
            # then prefers a semantically crossed pairing
            out.append(
                (
                    ((c[0] - x0) / w * 1000, (c[1] - y0) / h * 1000),
                    a * dom,
                    abs(a) / total_area,
                )
            )
        return out

    ref_feats = feats(ref_rings)
    m_feats = feats(master_rings)
    n = len(ref_feats)

    def cost(ri, mi):
        (rc, ra, rf), (mc, ma, mf) = ref_feats[ri], m_feats[mi]
        return _dist(rc, mc) + abs(rf - mf) * 1000 + (0 if (ra >= 0) == (ma >= 0) else 100000)

    if n <= 7:
        best_order, best_cost = None, None
        for perm in itertools.permutations(range(n)):
            c = sum(cost(ri, mi) for ri, mi in enumerate(perm))
            if best_cost is None or c < best_cost:
                best_cost, best_order = c, list(perm)
        return best_order
    used = set()
    order = [None] * n
    for ri in range(n):
        best, bestd = None, None
        for mi in range(n):
            if mi in used:
                continue
            d = cost(ri, mi)
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
