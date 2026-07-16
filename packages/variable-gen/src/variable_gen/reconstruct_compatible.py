#!/usr/bin/env python3
"""Glyph compatibility reconstruction engine.

Given a glyph's outlines at several weights drawn as INDEPENDENT statics (so they
disagree on contour count / order / start point / node count — like the Circular
XX cut, where 477/755 glyphs are structurally incompatible), produce per-master
outlines that share ONE point structure, so they interpolate into a variable
font, while each master still matches its own weight's shape.

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
    fully interpolation-compatible result. If masters disagree on contour COUNT,
    first unions overlapping contours per master (handles glyphs like $ / ¢ whose
    separate bar stubs merge into the body at heavy weights)."""
    if _already_compatible(outlines_by_pos) and _starts_aligned(outlines_by_pos):
        # normalise contour order first — donor order can flip across weights and
        # still pass signature(), then interpolate to the wrong contour (B).
        ordered = _order_normalize(outlines_by_pos, reference_pos)
        if (
            ordered is not None
            and _already_compatible(ordered)
            and _starts_aligned(ordered)
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
    if cc is not None and _struct_ok(cc) and not _quality_offenders(cc, outlines_by_pos):
        return cc, {"stage": "reconstructed", "note": "counter-closing"}

    # each variant is (outlines, reference_pos)
    variants = [(outlines_by_pos, reference_pos)]
    counts = {len(c) for c in outlines_by_pos.values()}
    if len(counts) > 1:
        unioned = {pos: union_overlaps(c) for pos, c in outlines_by_pos.items()}
        if all(u is not None for u in unioned.values()):
            variants.append((unioned, reference_pos))
        # merge-to-min: light weights of $ / ¢ / r.ss03 carry extra disjoint
        # contours (bar stubs / a single-weight stray) that join the body at
        # other weights. Bridge each master's contours down to the global-min
        # count so every master shares one topology, then reconstruct. Anchor the
        # reference on a master that NATIVELY has the min count (clean) — not a
        # bridged one, whose zero-width bridges would pollute every master.
        target = min(counts)
        merged = {pos: _to_n_contours(c, target) for pos, c in outlines_by_pos.items()}
        if all(m is not None for m in merged.values()):
            native = [p for p, c in outlines_by_pos.items() if len(c) == target]
            mref = min(native, key=lambda p: abs(p - reference_pos)) if native else reference_pos
            variants.append((merged, mref))

    last = {"stage": None, "note": "no angle worked"}
    for vi, (variant, vref) in enumerate(variants):
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
                tags = []
                if vi == 1:
                    tags.append("union")
                elif vi >= 2:
                    tags.append("merge-to-min")
                if angle != CORNER_ANGLE_SWEEP[0]:
                    tags.append(f"angle={round(math.degrees(angle))}")
                if tags:
                    info["note"] = "+".join(tags)
                return out, info
            last = info
    # Last resort before giving up: UNIFORM arc-length resampling — ignore corner
    # anchors and place dense, evenly-spaced points from a canonical (topmost)
    # start on every contour. Corner-anchored runs can mis-correspond across
    # masters (k's diagonal) and collapse at in-between weights; uniform
    # arc-length correspondence interpolates cleanly (corners stay sharp enough at
    # this density). Last because it rounds corners very slightly.
    uni = _uniform(outlines_by_pos, reference_pos)
    if (
        uni is not None
        and _struct_ok(uni)
        and not _quality_offenders(uni, outlines_by_pos)
        and _interp_ok(uni)
    ):
        return uni, {"stage": "reconstructed", "note": "uniform"}
    return None, last


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
    total = 0.0
    for con in contours:
        ring = to_ring(con)[0]
        total += abs(_signed_area(ring))
    return total


def _quality_offenders(out, donor):
    bad = {}
    for pos, contours in out.items():
        da = _glyph_area(donor[pos])
        if da <= 0:
            continue
        ra = _glyph_area(contours)
        dev = abs(ra / da - 1.0)
        if dev > QUALITY_AREA_TOL:
            bad[pos] = round(dev, 2)
    return bad or None


def _struct_ok(out):
    """All masters share contour count and per-contour point count."""
    cs = {tuple(len(c) for c in contours) for contours in out.values()}
    return len(cs) == 1


def _contour_pts(con):
    """On/off-curve point list of a (op,[pts]) contour, in order."""
    pts = []
    for op, p in con:
        pts.extend(p)
    return pts


def _interp_ok(out, tol=0.18):
    """A point-compatible reconstruction can still interpolate badly if point
    correspondence across masters is wrong (e.g. k's diagonal): the masters look
    fine but the in-between weights collapse. Lerp the points of each adjacent
    master pair at t=0.5 and require the midpoint ink area to stay near the mean
    of the two endpoints — a collapse (points crossing) spikes it away."""
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
    for s in range(nslot):
        present = sorted(p for p in positions if p in fams[s])
        if not present:
            return None
        missing = [p for p in positions if p not in fams[s]]
        if not missing:
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
    combined = {pos: [] for pos in positions}
    for s in range(nslot):
        fam = {pos: fams[s][pos][0] for pos in positions}
        out = _reconstruct_single_family(fam, positions, lightest)
        if out is None:
            return None
        for pos in positions:
            combined[pos].append(out[pos])
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


def _to_n_contours(contours, target):
    """Bridge a master's contours down to `target` count: repeatedly splice the
    smallest-area contour into its nearest neighbour with a zero-width bridge
    (invisible under keep-overlaps), until `target` remain. Returns polyline
    contours, or None if it can't (target larger than count)."""
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
        rings[ti] = _bridge_rings(rings[ti], small)
    return [_as_line_contour(r) for r in rings]


def _bridge_rings(a, b):
    """Splice ring b into ring a at their closest point pair, forming one ring."""
    best = (0, 0, float("inf"))
    for i, pa in enumerate(a):
        for j, pb in enumerate(b):
            d = _dist(pa, pb)
            if d < best[2]:
                best = (i, j, d)
    ia, ib, _ = best
    return a[: ia + 1] + b[ib:] + b[: ib + 1] + a[ia:]


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
        # place anchors at the reference's arc-length fractions on this master
        anchor_idx = _idx_at_fracs(nd, ref_fracs)
        pts_out = []
        for r in range(k):
            a = anchor_idx[r]
            b = anchor_idx[(r + 1) % k]
            seg = _run_slice(nd, a, b)
            pts_out.append(nd[a])
            pts_out.extend(_resample_polyline(seg, run_counts[r]))
        result[pos] = _as_line_contour(pts_out)
    return result


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
