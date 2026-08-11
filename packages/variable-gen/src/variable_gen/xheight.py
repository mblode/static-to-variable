"""Font-agnostic geometry for raising a typeface x-height.

The map is derived from each glyph's own ink. This module deliberately knows
nothing about glyph classification, donor files, font metadata, or CLI policy.
"""

from __future__ import annotations

import math
from typing import Any, Literal, Protocol

from fontTools.pens.recordingPen import RecordingPen

Point = tuple[float, float]
SegmentKind = Literal["l", "c"]
Segment = tuple[SegmentKind, tuple[Point, ...]]
Contour = list[Segment]
Contours = list[Contour]
LineSegment = tuple[Point, Point]


class DrawableGlyph(Protocol):
    def draw(self, pen: Any) -> None: ...


class GlyphSet(Protocol):
    def __getitem__(self, name: str) -> DrawableGlyph: ...


class SegmentPen(Protocol):
    def moveTo(self, point: Point) -> None: ...

    def lineTo(self, point: Point) -> None: ...

    def curveTo(self, *points: Point) -> None: ...

    def closePath(self) -> None: ...


# Straining a band by k changes a stroke's perpendicular thickness by
# k*cos(t')/cos(t), where tan(t') = k*tan(t). The allocation cost inferred from
# a scanline run is 1 - (stem / width)^2.
MIN_COST = 0.05
MAX_STRAIN = 0.22
MAX_OFFSET = 7.0

__all__ = [
    "BandMap",
    "Contour",
    "Contours",
    "Point",
    "Segment",
    "build_map",
    "contours_of",
    "draw_contours",
    "flatten_contours",
    "map_contours",
    "redraw_polygons",
    "refit_contour",
    "runs_at",
    "widest_run",
]


def contours_of(glyph_set: GlyphSet, name: str) -> Contours:
    """Draw a glyph into a list of contours, each a list of ``(kind, points)``.

    ``kind`` is ``"l"`` for a line or ``"c"`` for a cubic; points always end at
    the on-curve point, so a contour is a closed ring of segments.
    """
    recording = RecordingPen()
    glyph_set[name].draw(recording)
    contours: Contours = []
    current: Contour = []
    start: Point | None = None
    here: Point | None = None
    for op, args in recording.value:
        if op == "moveTo":
            if current:
                contours.append(current)
            current, start = [], args[0]
            here = start
        elif op == "lineTo":
            if here is None:
                raise RuntimeError(f"{name}: line before moveTo")
            current.append(("l", (here, args[0])))
            here = args[0]
        elif op == "curveTo":
            if here is None:
                raise RuntimeError(f"{name}: curve before moveTo")
            current.append(("c", (here, *args)))
            here = args[-1]
        elif op == "qCurveTo":
            raise RuntimeError(f"{name}: quadratic outlines are not supported")
        elif op == "closePath" and here is not None and start is not None:
            if here != start:
                current.append(("l", (here, start)))
            here = start
        elif op == "addComponent":
            raise RuntimeError(f"{name}: unexpected component in a CFF glyph set")
    if current:
        contours.append(current)
    return contours


def _contour_is_ccw(contour):
    """Signed area test, to know which way the normal points out of the ink."""
    area = 0.0
    for _, pts in contour:
        for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
            area += x0 * y1 - x1 * y0
    return area > 0


def _ray_hit(segments, origin, direction, limit):
    """Distance from ``origin`` along ``direction`` to the first outline crossing.

    Used to measure how thick the stroke is under a point: cast inward and the
    first thing hit is the other edge.
    """
    ox, oy = origin
    dx, dy = direction
    best = None
    for (x0, y0), (x1, y1) in segments:
        ex, ey = x1 - x0, y1 - y0
        denominator = dx * ey - dy * ex
        if abs(denominator) < 1e-12:
            continue
        t = ((x0 - ox) * ey - (y0 - oy) * ex) / denominator
        if t < 0.35 or t > limit:  # skip the edge the point sits on
            continue
        u = ((x0 - ox) * dy - (y0 - oy) * dx) / denominator
        if 0.0 <= u <= 1.0 and (best is None or t < best):
            best = t
    return best


def flatten_contours(contours: Contours, steps: int = 12) -> list[LineSegment]:
    """Contours as line segments, for scanline work only."""
    segments = []
    for contour in contours:
        for kind, pts in contour:
            if kind == "l":
                segments.append((pts[0], pts[1]))
            else:
                p0, p1, p2, p3 = pts
                prev = p0
                for i in range(1, steps + 1):
                    t, u = i / steps, 1 - i / steps
                    point = (
                        u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
                        u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
                    )
                    segments.append((prev, point))
                    prev = point
    return segments


def runs_at(segments: list[LineSegment], y: float) -> list[tuple[float, float]]:
    """Ink intervals where a horizontal line at ``y`` crosses the outline.

    Uses the nonzero winding rule, matching how the outline is actually filled.
    """
    crossings = []
    for (x0, y0), (x1, y1) in segments:
        if (y0 <= y < y1) or (y1 <= y < y0):
            crossings.append((x0 + (y - y0) * (x1 - x0) / (y1 - y0), 1 if y1 > y0 else -1))
    if not crossings:
        return []
    crossings.sort()
    runs, winding, start = [], 0, None
    for x, direction in crossings:
        was_inside = winding != 0
        winding += direction
        if not was_inside and winding != 0:
            start = x
        elif was_inside and winding == 0 and start is not None:
            runs.append((start, x))
    return runs


def widest_run(segments: list[LineSegment], y: float) -> float:
    runs = runs_at(segments, y)
    return max((b - a for a, b in runs), default=0.0)


# --------------------------------------------------------------------------- #
# the map
# --------------------------------------------------------------------------- #


class BandMap:
    """Monotonic piecewise-affine y map built from one glyph's own geometry.

    Three regions, all continuous:
      * baseline to the flat x-line, which absorbs the whole rise;
      * x-line to the top of the overshoot, which translates rigidly, so a glyph
        with a flat top lands exactly on target rather than short;
      * overshoot to the ascender, which gives the rise back so the ascender
        stays put.

    The first and last are allocated by cost, not spread evenly, so the strain
    lands on vertical stems and spares horizontal strokes at either end. Before
    the ascender region was weighted it compressed uniformly, and `f`'s hook -
    the one horizontal stroke up there - lost 20% of its weight.
    """

    def __init__(
        self,
        breaks: list[float],
        shifts: list[float],
        ascender: float,
        x_top: float,
        hi: float,
    ) -> None:
        self.breaks = breaks  # ascending, from the baseline to the ascender
        self.shifts = shifts  # cumulative shift at each break
        self.ascender = ascender
        self.x_top = x_top
        self.hi = hi

    def __call__(self, y: float) -> float:
        if y <= self.breaks[0] or y >= self.breaks[-1]:
            return y + (self.shifts[0] if y <= self.breaks[0] else self.shifts[-1])
        for i in range(len(self.breaks) - 1):
            lo, high = self.breaks[i], self.breaks[i + 1]
            if y <= high:
                span = high - lo
                if span <= 0:
                    return lo + self.shifts[i]
                rate = (self.shifts[i + 1] - self.shifts[i]) / span
                return y + self.shifts[i] + (y - lo) * rate
        return y + self.shifts[-1]

    def rate(self, y: float) -> float:
        """Local dy'/dy: how hard the map strains the outline at this height."""
        if y <= self.breaks[0] or y >= self.breaks[-1]:
            return 1.0
        for i in range(len(self.breaks) - 1):
            lo, high = self.breaks[i], self.breaks[i + 1]
            if y <= high:
                span = high - lo
                return 1.0 + (self.shifts[i + 1] - self.shifts[i]) / span if span > 0 else 1.0
        return 1.0

    def point(self, p: Point) -> Point:
        return (p[0], self(p[1]))

    @property
    def levels(self) -> list[float]:
        """Where curves must be split.

        Only the structural heights. The map is smooth, so cutting at every rate
        sample is no longer needed to keep joins clean, and not cutting keeps the
        outline close to the source's original number of points.
        """
        return [self.breaks[0], self.x_top, self.hi, self.ascender]


def band_cost(segments: list[LineSegment], y: float, stem: float) -> float:
    """Distortion per unit strain at height ``y``: ``1 - (stem/W)^2``.

    ``W`` is the widest ink run, so a band is judged by its most horizontal
    stroke - the one with most to lose.
    """
    width = widest_run(segments, y)
    if width <= stem:
        return MIN_COST
    return max(MIN_COST, min(1.0, 1.0 - (stem / width) ** 2))


# Rate is sampled on this grid and then smoothed, so the map's slope changes
# gradually instead of stepping at band edges.
RATE_STEP = 12.0
SMOOTH_RADIUS = 3


def _smooth(values, weights, radius=SMOOTH_RADIUS):
    """Weighted moving average, so the rate profile has no steps in it."""
    out = []
    for i in range(len(values)):
        lo, high = max(0, i - radius), min(len(values), i + radius + 1)
        total = sum(weights[j] for j in range(lo, high))
        out.append(
            sum(values[j] * weights[j] for j in range(lo, high)) / total if total else values[i]
        )
    return out


def build_map(
    contours: Contours,
    delta: float,
    x_top: float,
    hi: float,
    ascender: float,
    stem: float,
) -> BandMap:
    """Turn one glyph's own geometry into a monotonic, smooth y map.

    Rate is allocated by cost as before, but on a fine grid and then smoothed. A
    piecewise-constant rate makes the map merely continuous: the tangent's y
    component is scaled by different amounts either side of a boundary, so
    wherever the tangent is oblique it rotates and leaves a kink. Smoothing the
    profile makes the map effectively C1, so joins stay smooth no matter where a
    curve happens to be cut.
    """
    segments = flatten_contours(contours)

    def region(lo, high, rise):
        if high - lo < 1e-6:
            return [lo, high], [0.0, rise]
        steps = max(2, int(math.ceil((high - lo) / RATE_STEP)))
        edges = [lo + (high - lo) * i / steps for i in range(steps + 1)]
        heights = [b - a for a, b in zip(edges, edges[1:], strict=False)]
        costs = [
            band_cost(segments, (a + b) / 2, stem) for a, b in zip(edges, edges[1:], strict=False)
        ]
        rates = _smooth([1.0 / c for c in costs], heights)
        moves = _allocate_smoothed(heights, rates, rise)
        shifts, running = [0.0], 0.0
        for move in moves:
            running += move
            shifts.append(running)
        shifts[-1] = rise
        return edges, shifts

    lower_edges, lower_shifts = region(0.0, x_top, delta)
    upper_edges, upper_shifts = region(hi, ascender, -delta)

    breaks = [*lower_edges, hi, *upper_edges[1:]]
    shifts = [*lower_shifts, delta, *(delta + v for v in upper_shifts[1:])]
    return BandMap(breaks, shifts, ascender, x_top, hi)


def _allocate_smoothed(heights, rates, rise, limit=None):
    """Spread ``rise`` in proportion to each band's smoothed rate weight."""
    limit = MAX_STRAIN if rise >= 0 else 0.5
    total = sum(h * r for h, r in zip(heights, rates, strict=False))
    if not total:
        return [0.0] * len(heights)
    moves = [rise * h * r / total for h, r in zip(heights, rates, strict=False)]
    for _ in range(12):
        over = [
            i
            for i, (m, h) in enumerate(zip(moves, heights, strict=False))
            if abs(m) > h * limit + 1e-9
        ]
        if not over:
            break
        spare = 0.0
        for i in over:
            capped = math.copysign(heights[i] * limit, rise)
            spare += moves[i] - capped
            moves[i] = capped
        free = [i for i in range(len(moves)) if i not in over]
        weight = sum(heights[i] * rates[i] for i in free)
        if not weight:
            break
        for i in free:
            moves[i] += spare * heights[i] * rates[i] / weight
    return moves


def map_contours(
    contours: Contours,
    ymap: BandMap,
    delta: float,
    float_hi: float,
    *,
    refit: bool = False,
    preserve_stem_joins: bool = False,
) -> Contours:
    """Apply the map. A contour floating clear of the lowercase band is an accent
    or a tittle, so it is translated whole rather than strained, keeping its shape
    and its gap above the letter.

    It travels by however far the letter underneath it travelled, not by the full
    rise. Those differ whenever the base is tall: `a` tops out at the x-height and
    moves 44, so its acute moves 44, but `l` tops out at the ascender and does not
    move at all, so the caron of `lcaron` must not move either. Translating every
    floating contour by the rise pushed that caron 44 units clear of the ascender
    it belongs to.

    ``preserve_stem_joins`` is an explicit optical correction on top of the
    mathematical map: smooth curves next to vertical stems retain their source
    tangent-arm length instead of absorbing the stem's added height.
    """
    floating = []
    base_top = None
    for contour in contours:
        ys = [p[1] for _, pts in contour for p in pts]
        is_float = bool(ys) and min(ys) > float_hi
        floating.append(is_float)
        if not is_float and ys:
            base_top = max(ys) if base_top is None else max(base_top, max(ys))

    shift = delta if base_top is None else ymap(base_top) - base_top
    out = []
    for contour, is_float in zip(contours, floating, strict=False):
        if is_float:
            out.append([(k, tuple((x, y + shift) for x, y in pts)) for k, pts in contour])
        elif refit:
            out.append(refit_contour(contour, ymap, preserve_stem_joins=preserve_stem_joins))
        else:
            out.append([(k, tuple((x, ymap(y)) for x, y in pts)) for k, pts in contour])
    return out


def _line_intersection(a0, a1, b0, b1):
    """Where two lines meet, or None when they are parallel."""
    (x1, y1), (x2, y2) = a0, a1
    (x3, y3), (x4, y4) = b0, b1
    denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denominator) < 1e-9:
        return None
    a = x1 * y2 - y1 * x2
    b = x3 * y4 - y3 * x4
    return (
        (a * (x3 - x4) - (x1 - x2) * b) / denominator,
        (a * (y3 - y4) - (y1 - y2) * b) / denominator,
    )


def redraw_polygons(
    mapped: Contours,
    source: Contours,
    ymap: BandMap,
    stem: float,
) -> Contours:
    """Restore stroke weight on contours made entirely of straight lines.

    Offsetting a Bezier by translating its control points is not a true offset,
    which is why correcting curves that way made the font measurably worse. On a
    polygon there is no such error: shifting two parallel edges apart by m changes
    the stroke's perpendicular thickness by exactly m, and the corners follow from
    intersecting the offset edges. So the correction is applied only where it is
    exact, which happens to be most of the glyphs that needed it - `k`, `<`, `>`,
    the bar of the division sign, and every other all-line form.

    The amount comes from the strain: a vertical strain k multiplies a stroke's
    perpendicular thickness by k/sqrt(cos^2(t) + k^2 sin^2(t)) for edges at angle
    t from horizontal, so each edge moves back by d(1/f - 1)/2.
    """
    out = []
    for contour, source_contour in zip(mapped, source, strict=False):
        if len(contour) < 3 or any(kind != "l" for kind, _ in contour):
            out.append(contour)
            continue
        segments = flatten_contours([contour], steps=2)
        sign = 1.0 if _contour_is_ccw(contour) else -1.0

        offsets, normals = [], []
        for (_, pts), (_, src_pts) in zip(contour, source_contour, strict=False):
            (x0, y0), (x1, y1) = pts
            length = math.hypot(x1 - x0, y1 - y0)
            if length < 1e-9:
                offsets.append(0.0)
                normals.append((0.0, 0.0))
                continue
            nx, ny = sign * (y1 - y0) / length, -sign * (x1 - x0) / length
            normals.append((nx, ny))
            # A horizontal edge is an alignment edge - a terminal or a flat - and
            # its normal is vertical, so offsetting it would move the x-line, the
            # baseline or the ascender. Leave it, and the miter against the
            # neighbouring diagonal then slides the corner along it: the stroke
            # changes thickness while its height stays exact.
            if abs(nx) < 0.2:
                offsets.append(0.0)
                continue

            mid_src = (src_pts[0][1] + src_pts[1][1]) / 2
            k = ymap.rate(mid_src)
            angle = math.atan2(src_pts[1][1] - src_pts[0][1], src_pts[1][0] - src_pts[0][0])
            f = k / math.hypot(math.cos(angle), k * math.sin(angle))
            if abs(f - 1.0) < 1e-4:
                offsets.append(0.0)
                continue
            mid = ((x0 + x1) / 2, (y0 + y1) / 2)
            thickness = _ray_hit(segments, mid, (-nx, -ny), stem * 3.0)
            if thickness is None or thickness > stem * 2.2:
                offsets.append(0.0)
                continue
            offsets.append(max(-MAX_OFFSET, min(MAX_OFFSET, thickness * (1.0 / f - 1.0) / 2.0)))

        if not any(offsets):
            out.append(contour)
            continue

        shifted = [
            (
                ((pts[0][0] + n[0] * m, pts[0][1] + n[1] * m)),
                ((pts[1][0] + n[0] * m, pts[1][1] + n[1] * m)),
            )
            for (_, pts), n, m in zip(contour, normals, offsets, strict=False)
        ]
        vertices = []
        for i in range(len(shifted)):
            previous, current = shifted[i - 1], shifted[i]
            hit = _line_intersection(previous[0], previous[1], current[0], current[1])
            if hit is None or math.dist(hit, current[0]) > stem:
                hit = current[0]  # near-parallel edges: no usable miter
            vertices.append(hit)
        out.append(
            [("l", (vertices[i], vertices[(i + 1) % len(vertices)])) for i in range(len(vertices))]
        )
    return out


# --------------------------------------------------------------------------- #
# curve fitting
# --------------------------------------------------------------------------- #

# Target deviation, in units, used by the fitter's sampled error metric. This is
# not a proven bound on the emitted curve; callers that require a hard bound must
# measure the target against the fitted outline independently.
FIT_TOLERANCE = 0.4

# Fit slightly inside the target to leave room for peaks missed between samples.
FIT_GUARD = 0.70

# Tangent turn, in degrees, above which a join is a real corner and must be kept.
CORNER_ANGLE = 28.0

# A smooth bowl leaving a straight vertical stem should turn with the same
# economy as the source drawing. The nonlinear height map can otherwise double
# its first control arm, delaying the turn and pinching the bowl-to-stem join.
STEM_JOIN_ANGLE = math.radians(10.0)
STEM_JOIN_GROWTH = 1.05

# A fixed sample count spread over a long span leaves gaps in the internal error
# metric, so samples are spaced along the chord instead.
SAMPLE_SPACING = 4.0
SAMPLES_MIN = 20
SAMPLES_MAX = 96

# Subdivision points are chosen on a grid of this many steps per source segment.
# Fixing them to a grid lets area and moment for any candidate span come from one
# prefix-sum difference instead of a fresh quadrature, which is what makes the
# search-for-the-longest-segment loop affordable.
GRID_PER_SEGMENT = 64

# Area and moment can also be matched by a curve with very long control arms,
# which passes the distance test and still bulges. Levien's mitigation: a
# ReLU-shaped penalty on arm length, in unit-chord terms, multiplying the
# measured error. The constants are his.
ARM_ELBOW = 0.65
ARM_SLOPE = 2.0


def _bezier_point(pts, t):
    p0, p1, p2, p3 = pts
    u = 1 - t
    return (
        u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
        u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
    )


def _bezier_deriv(pts, t):
    p0, p1, p2, p3 = pts
    u = 1 - t
    return (
        3 * (u * u * (p1[0] - p0[0]) + 2 * u * t * (p2[0] - p1[0]) + t * t * (p3[0] - p2[0])),
        3 * (u * u * (p1[1] - p0[1]) + 2 * u * t * (p2[1] - p1[1]) + t * t * (p3[1] - p2[1])),
    )


def _normalise(v):
    length = math.hypot(*v)
    return (v[0] / length, v[1] / length) if length > 1e-12 else (0.0, 0.0)


def _raise_line(start, end):
    """A chord as a cubic, for spans a curve cannot be fitted to."""
    return (
        start,
        (start[0] + (end[0] - start[0]) / 3.0, start[1] + (end[1] - start[1]) / 3.0),
        (end[0] - (end[0] - start[0]) / 3.0, end[1] - (end[1] - start[1]) / 3.0),
        end,
    )


# --------------------------------------------------------------------------- #
# polynomial roots
# --------------------------------------------------------------------------- #


def _solve_quadratic(c0, c1, c2):
    """Real roots of ``c2 x^2 + c1 x + c0``, in the numerically stable form."""
    if c2 == 0.0:
        return [] if c1 == 0.0 else [-c0 / c1]
    sc0, sc1 = c0 / c2, c1 / c2
    arg = sc1 * sc1 - 4.0 * sc0
    if arg < 0.0:
        return []
    if arg == 0.0:
        return [-0.5 * sc1]
    # Taking the root with the sign of sc1 avoids cancellation; the other follows
    # from the product of the roots.
    root = -0.5 * (sc1 + math.copysign(math.sqrt(arg), sc1))
    return [root, sc0 / root] if root != 0.0 else [0.0, -sc1]


def _solve_cubic(c0, c1, c2, c3):
    """Real roots of ``c3 x^3 + c2 x^2 + c1 x + c0`` (Blinn's discriminant form)."""
    if c3 == 0.0:
        return _solve_quadratic(c0, c1, c2)
    third = 1.0 / 3.0
    a2, a1, a0 = c2 * third / c3, c1 * third / c3, c0 / c3
    if not (math.isfinite(a0) and math.isfinite(a1) and math.isfinite(a2)):
        return _solve_quadratic(c0, c1, c2)
    d0 = a1 - a2 * a2
    d1 = a0 - a1 * a2
    d2 = a2 * a0 - a1 * a1
    discriminant = 4.0 * d0 * d2 - d1 * d1
    depressed = d1 - 2.0 * a2 * d0
    if discriminant < 0.0:
        root = -0.5 * depressed
        offset = math.sqrt(-0.25 * discriminant)
        return [math.cbrt(root + offset) + math.cbrt(root - offset) - a2]
    if discriminant == 0.0:
        t = math.copysign(math.sqrt(-d0), depressed)
        return [t - a2, -2.0 * t - a2]
    angle = math.atan2(math.sqrt(discriminant), -depressed) * third
    scale = 2.0 * math.sqrt(-d0)
    sin3, cos1 = math.sin(angle) * math.sqrt(3.0), math.cos(angle)
    return [
        scale * cos1 - a2,
        scale * 0.5 * (-cos1 + sin3) - a2,
        scale * 0.5 * (-cos1 - sin3) - a2,
    ]


def _quartic_roots(a3, a2, a1, a0):
    """Complex roots of the monic quartic ``x^4 + a3 x^3 + a2 x^2 + a1 x + a0``.

    Durand-Kerner. Degree four with a monic normalisation converges in a few
    dozen iterations from the standard spiral start, and the caller validates
    every root against the curve anyway, so robustness matters more than speed.
    """
    coefficients = (1.0, a3, a2, a1, a0)
    roots = [complex(0.4, 0.9) ** i for i in range(4)]
    for _ in range(60):
        shift = 0.0
        for i in range(4):
            value = 0j
            for coefficient in coefficients:
                value = value * roots[i] + coefficient
            denominator = 1 + 0j
            for j in range(4):
                if j != i:
                    denominator *= roots[i] - roots[j]
            if denominator == 0:
                continue
            step = value / denominator
            roots[i] -= step
            shift = max(shift, abs(step))
        if shift < 1e-13:
            break
    return roots


# --------------------------------------------------------------------------- #
# Levien's area-and-moment cubic fit
# --------------------------------------------------------------------------- #


def _mod_2pi(angle):
    turns = angle / (2 * math.pi)
    return 2 * math.pi * (turns - round(turns))


def _arm_lengths(th0, th1, area, moment):
    """Control-arm lengths of every cubic with the given area and first moment.

    Working in the frame where the chord runs from (0,0) to (1,0), a cubic is
    fixed by its two end tangent angles and its two arm lengths d0, d1. Levien
    (*Fitting cubic Bezier curves*, 2021) integrates the segment's signed area
    and its first moment about the chord in closed form:

        area = 3/20 (2 d0 sin th0 + 2 d1 sin th1 - d0 d1 sin(th0 + th1))

        moment_x = 1/280 ( 34 d0 sin th0
                         + 50 d1 sin th1
                         + 15 d0^2 sin th0 cos th0
                         - 15 d1^2 sin th1 cos th1
                         - d0 d1 (33 sin th0 cos th1 + 9 cos th0 sin th1)
                         - 9 d0^2 d1 sin(th0 + th1) cos th0
                         + 9 d0 d1^2 sin(th0 + th1) cos th1 )

    With the angles known, the area equation is linear in d1, so substituting it
    into the moment equation clears d1 and leaves a quartic in d0. Its real roots
    are the candidate fits; d1 comes straight back out of the area equation. The
    quartic coefficients below are Levien's own reduction, as implemented in
    kurbo's ``cubic_fit`` (kurbo/src/fit.rs), which is the reference for this.

    Two integrals of the whole segment are matched exactly rather than distance
    at sampled points minimised, which is why a 90-degree arc comes back as one
    cubic instead of two.
    """
    s0, c0 = math.sin(th0), math.cos(th0)
    s1, c1 = math.sin(th1), math.cos(th1)
    a4 = (
        -9.0
        * c0
        * (
            ((2.0 * s1 * c1 * c0 + s0 * (2.0 * c1 * c1 - 1.0)) * c0 - 2.0 * s1 * c1) * c0
            - c1 * c1 * s0
        )
    )
    a3 = 12.0 * (
        (
            (
                (c1 * (30.0 * area * c1 - s1) - 15.0 * area) * c0
                + 2.0 * s0
                - c1 * s0 * (c1 + 30.0 * area * s1)
            )
            * c0
            + c1 * (s1 - 15.0 * area * c1)
        )
        * c0
        - s0 * c1 * c1
    )
    a2 = 12.0 * (
        (
            (
                (70.0 * moment + 15.0 * area) * s1 * s1
                + c1 * (9.0 * s1 - 70.0 * c1 * moment - 5.0 * c1 * area)
            )
            * c0
            - 5.0 * s0 * s1 * (3.0 * s1 - 4.0 * c1 * (7.0 * moment + area))
        )
        * c0
        - c1 * (9.0 * s1 - 70.0 * c1 * moment - 5.0 * c1 * area)
    )
    a1 = 16.0 * (
        (
            (12.0 * s0 - 5.0 * c0 * (42.0 * moment - 17.0 * area)) * s1
            - 70.0 * c1 * (3.0 * moment - area) * s0
            - 75.0 * c0 * c1 * area * area
        )
        * s1
        - 75.0 * c1 * c1 * area * area * s0
    )
    a0 = 80.0 * s1 * (42.0 * s1 * moment - 25.0 * area * (s1 - c1 * area))

    epsilon = 1e-12
    if abs(a4) > epsilon:
        # A complex conjugate pair often brackets a near-root, so its real part
        # is kept as a candidate too; the distance metric throws it out if not.
        candidates = [root.real for root in _quartic_roots(a3 / a4, a2 / a4, a1 / a4, a0 / a4)]
    elif abs(a3) > epsilon:
        candidates = _solve_cubic(a0, a1, a2, a3)
    elif abs(a2) > epsilon or abs(a1) > epsilon or abs(a0) > epsilon:
        candidates = _solve_quadratic(a0, a1, a2)
    else:
        return [(1.0 / 3.0, 1.0 / 3.0)]  # fully degenerate: the chord itself

    s01 = s0 * c1 + s1 * c0
    out = []
    for d0 in candidates:
        if not math.isfinite(d0):
            continue
        if d0 > 0.0:
            denominator = 0.5 * d0 * s01 - s1
            d1 = (d0 * s0 - area * (10.0 / 3.0)) / denominator if denominator else -1.0
            if d1 <= 0.0:
                d0, d1 = (s1 / s01, 0.0) if s01 else (0.0, 0.0)
        else:
            d0, d1 = 0.0, (s0 / s01 if s01 else 0.0)
        if d0 >= 0.0 and d1 >= 0.0 and math.isfinite(d1):
            out.append((d0, d1))
    return out


class _MappedRun:
    """The true mapped curve over a run of source cubics, parameterised on [0, 1].

    The map moves y only, so the mapped point is exact and its derivative is the
    source derivative with the y component scaled by the map's local rate. Area
    and moment are therefore integrals of the real target rather than of a polygon
    approximating it, and the end tangents handed to the fit are exact.

    Integrals are accumulated once per run on a fixed grid, so asking for the area
    and moment of any span of grid nodes is a subtraction.
    """

    def __init__(self, segments, ymap):
        self.segments = tuple(segments)
        self.ymap = ymap
        self.count = len(self.segments)
        self.grid = GRID_PER_SEGMENT * self.count
        self._prefix = self._integrate()

    def point_deriv(self, t):
        scaled = t * self.count
        index = min(int(scaled), self.count - 1)
        pts = self.segments[index]
        point = _bezier_point(pts, scaled - index)
        dx, dy = _bezier_deriv(pts, scaled - index)
        rate = self.ymap.rate(point[1])
        return (point[0], self.ymap(point[1])), (dx * self.count, dy * rate * self.count)

    def point(self, t):
        return self.point_deriv(t)[0]

    def tangent(self, t, sign):
        """Unit tangent, stepping off a source cusp in the direction of travel."""
        for nudge in (0.0, 1e-5, 1e-4, 1e-3):
            _, d = self.point_deriv(min(1.0, max(0.0, t + sign * nudge)))
            if math.hypot(*d) > 1e-9:
                return _normalise(d)
        return (1.0, 0.0)

    def _integrate(self):
        """Prefix sums of the integrals of y dx, x y dx and y^2 dx, by Simpson."""

        def terms(t):
            (px, py), (dx, _) = self.point_deriv(t)
            weight = dx * py
            return weight, px * weight, py * weight

        step = 1.0 / self.grid
        prefix = [(0.0, 0.0, 0.0)]
        low = terms(0.0)
        for i in range(self.grid):
            middle = terms((i + 0.5) * step)
            high = terms((i + 1) * step)
            last = prefix[-1]
            prefix.append(
                tuple(last[k] + step / 6.0 * (low[k] + 4.0 * middle[k] + high[k]) for k in range(3))
            )
            low = high
        return prefix

    def moments(self, i0, i1):
        a, b = self._prefix[i0], self._prefix[i1]
        return b[0] - a[0], b[1] - a[1], b[2] - a[2]


class _CurveDist:
    """How far a candidate cubic sits from the true curve, by Levien's ray metric.

    A ray is cast from each sample of the true curve along its normal, and the
    nearest crossing of the candidate is the corresponding point. That measures
    distance between points that correspond, which is what Frechet distance means:
    a curve that wanders and doubles back can be near the true curve everywhere
    and still be the wrong shape. Where curvature varies enough that the ray can
    match the wrong place, correspondence by arc length is measured as well.
    """

    SPICY = 0.2  # tangent turn between neighbouring samples, as a ratio

    def __init__(self, run, t0, t1, span):
        self.run = run
        self.range = (t0, t1)
        self.count = min(SAMPLES_MAX, max(SAMPLES_MIN, int(span / SAMPLE_SPACING)))
        self.samples = []
        self.spicy = False
        self._arc = None
        step = (t1 - t0) / (self.count + 1)
        previous = None
        for i in range(self.count + 2):
            t = t0 + i * step
            tangent = run.tangent(t, 1.0)
            if previous is not None:
                cross = abs(tangent[0] * previous[1] - tangent[1] * previous[0])
                dot = abs(tangent[0] * previous[0] + tangent[1] * previous[1])
                if cross > self.SPICY * dot:
                    self.spicy = True
            previous = tangent
            if 0 < i < self.count + 1:
                self.samples.append((run.point(t), tangent))

    def evaluate(self, curve, limit):
        """Squared error, or None once it is past ``limit`` (also squared)."""
        error = self._by_ray(curve, limit)
        if error is None or not self.spicy:
            return error
        return self._by_arc(curve, limit)

    def _by_ray(self, curve, limit):
        p0, p1, p2, p3 = curve
        b1 = (3 * (p1[0] - p0[0]), 3 * (p1[1] - p0[1]))
        b2 = (3 * p2[0] - 6 * p1[0] + 3 * p0[0], 3 * p2[1] - 6 * p1[1] + 3 * p0[1])
        b3 = (p3[0] - p0[0] - 3 * (p2[0] - p1[0]), p3[1] - p0[1] - 3 * (p2[1] - p1[1]))
        worst = 0.0
        for point, tangent in self.samples:
            roots = _solve_cubic(
                (p0[0] - point[0]) * tangent[0] + (p0[1] - point[1]) * tangent[1],
                b1[0] * tangent[0] + b1[1] * tangent[1],
                b2[0] * tangent[0] + b2[1] * tangent[1],
                b3[0] * tangent[0] + b3[1] * tangent[1],
            )
            best = None
            for t in roots:
                if -1e-9 <= t <= 1.0 + 1e-9:
                    hit = _bezier_point(curve, min(1.0, max(0.0, t)))
                    error = (hit[0] - point[0]) ** 2 + (hit[1] - point[1]) ** 2
                    if best is None or error < best:
                        best = error
            if best is None or best > limit:
                return None  # the ray misses the candidate entirely
            worst = max(worst, best)
        return worst

    def _by_arc(self, curve, limit):
        if self._arc is None:
            self._arc = self._arc_parameters()
        table = _arclen_table(curve)
        worst = 0.0
        for (point, _), fraction in zip(self.samples, self._arc, strict=False):
            hit = _bezier_point(curve, _at_arclen(table, fraction))
            error = (hit[0] - point[0]) ** 2 + (hit[1] - point[1]) ** 2
            if error > limit:
                return None
            worst = max(worst, error)
        return worst

    def _arc_parameters(self):
        """Arc length at each sample of the true curve, as a fraction of the whole."""
        t0, t1 = self.range
        step = (t1 - t0) / (self.count + 1)
        substeps = 10
        travelled, out = 0.0, []
        for i in range(self.count + 1):
            for j in range(substeps):
                t = t0 + step * (i + (j + 0.5) / substeps)
                travelled += math.hypot(*self.run.point_deriv(t)[1]) * step / substeps
            if i < self.count:
                out.append(travelled)
        return [d / travelled for d in out] if travelled else [0.0] * self.count


def _arclen_table(curve, steps=48):
    """Cumulative chord length along a cubic, normalised to end at 1."""
    table, travelled = [0.0], 0.0
    previous = curve[0]
    for i in range(1, steps + 1):
        point = _bezier_point(curve, i / steps)
        travelled += math.dist(previous, point)
        table.append(travelled)
        previous = point
    return [d / travelled for d in table] if travelled else table


def _at_arclen(table, fraction):
    steps = len(table) - 1
    for i in range(steps):
        if fraction <= table[i + 1]:
            span = table[i + 1] - table[i]
            local = (fraction - table[i]) / span if span > 1e-12 else 0.0
            return (i + local) / steps
    return 1.0


def _arm_penalty(d):
    return 1.0 + max(0.0, d - ARM_ELBOW) * ARM_SLOPE


def _fit_cubic(run, i0, i1, tolerance, best_effort=False):
    """The best cubic over grid nodes ``i0..i1``, or None if none is close enough."""
    t0, t1 = i0 / run.grid, i1 / run.grid
    start, end = run.point(t0), run.point(t1)
    chord_x, chord_y = end[0] - start[0], end[1] - start[1]
    chord2 = chord_x * chord_x + chord_y * chord_y
    accuracy2 = (tolerance * FIT_GUARD) ** 2
    if chord2 <= accuracy2:
        # Too short for the chord frame to be stable, and a closed run starts and
        # ends in the same place, so try the degenerate answer instead.
        line = _fit_line(run, t0, t1, start, end, accuracy2)
        if line or not best_effort:
            return line
        return _raise_line(start, end), accuracy2

    heading = math.atan2(chord_y, chord_x)
    tan0, tan1 = run.tangent(t0, 1.0), run.tangent(t1, -1.0)
    th0 = _mod_2pi(math.atan2(tan0[1], tan0[0]) - heading)
    th1 = _mod_2pi(heading - math.atan2(tan1[1], tan1[0]))

    # Green's-theorem integrals of the run, less the chord's own contribution, so
    # what is left is the area and moment of the closed segment-plus-chord region.
    # Invariant under translation and rotation, then scaled to a unit chord.
    area, moment_x, moment_y = run.moments(i0, i1)
    x0, y0 = start
    area -= chord_x * (y0 + 0.5 * chord_y)
    third = chord_y / 3.0
    moment_x -= chord_x * (x0 * y0 + 0.5 * (x0 * chord_y + y0 * chord_x) + third * chord_x)
    moment_y -= chord_x * (y0 * y0 + y0 * chord_y + third * chord_y)
    moment_x -= x0 * area
    moment_y = 0.5 * moment_y - y0 * area
    moment = chord_x * moment_x + chord_y * moment_y
    unit_area = area / chord2
    unit_moment = moment / (chord2 * chord2)

    chord = math.sqrt(chord2)
    cos_h, sin_h = chord_x / chord, chord_y / chord

    def place(px, py):
        return (
            x0 + chord * (px * cos_h - py * sin_h),
            y0 + chord * (px * sin_h + py * cos_h),
        )

    distance = _CurveDist(run, t0, t1, chord)
    best, best_error = None, None
    for d0, d1 in _arm_lengths(th0, th1, unit_area, unit_moment):
        curve = (
            start,
            place(d0 * math.cos(th0), d0 * math.sin(th0)),
            place(1.0 - d1 * math.cos(th1), d1 * math.sin(th1)),
            end,
        )
        error = distance.evaluate(curve, accuracy2)
        if error is None:
            continue
        error *= max(_arm_penalty(d0), _arm_penalty(d1)) ** 2
        if error < accuracy2 and (best_error is None or error < best_error):
            best, best_error = curve, error
    if best is not None:
        return best, best_error
    # Over a span short enough that the true curve barely leaves its chord, the
    # quartic is ill conditioned and its roots are noise. The chord itself is a
    # legitimate cubic there, and it is held to the same tolerance.
    line = _fit_line(run, t0, t1, start, end, accuracy2)
    if line is not None or not best_effort:
        return line
    return _raise_line(start, end), accuracy2


def _fit_line(run, t0, t1, start, end, accuracy2):
    """A chord raised to a cubic, when the true curve never leaves it."""
    x0, y0 = start
    dx, dy = end[0] - x0, end[1] - y0
    length2 = dx * dx + dy * dy
    worst = 0.0
    for i in range(1, 8):
        point = run.point(t0 + (t1 - t0) * i / 8.0)
        along = ((point[0] - x0) * dx + (point[1] - y0) * dy) / length2 if length2 else 0.0
        along = min(1.0, max(0.0, along))
        error = (x0 + along * dx - point[0]) ** 2 + (y0 + along * dy - point[1]) ** 2
        if error > accuracy2:
            return None
        worst = max(worst, error)
    return _raise_line(start, end), worst


def _fit_chain(run, tolerance):
    """Fit the run with as few cubics as the tolerance allows.

    Each cubic takes the longest span it can hold: double the reach until it
    fails, then bisect. Doubling stops at the first failure rather than searching
    the whole run, which keeps the search honest on a closed run, where a span
    approaching the full loop shrinks back towards a zero-length chord and would
    otherwise look feasible again.
    """
    cache = {}

    def fit(i0, i1):
        if (i0, i1) not in cache:
            cache[(i0, i1)] = _fit_cubic(run, i0, i1, tolerance)
        return cache[(i0, i1)]

    out, i0 = [], 0
    while i0 < run.grid:
        whole = fit(i0, run.grid)
        if whole is not None:
            out.append(whole[0])
            break
        reach, step = i0, 1
        while i0 + step < run.grid and fit(i0, i0 + step) is not None:
            reach = i0 + step
            step *= 2
        high = min(run.grid, i0 + step)
        reach = max(reach, i0 + 1)
        while high - reach > 1:
            middle = (reach + high) // 2
            if fit(i0, middle) is not None:
                reach = middle
            else:
                high = middle
        found = fit(i0, reach) or _fit_cubic(run, i0, reach, tolerance, best_effort=True)
        out.append(found[0])
        i0 = reach
    return out


def refit_contour(
    contour: Contour,
    ymap: BandMap,
    tolerance: float = FIT_TOLERANCE,
    *,
    preserve_stem_joins: bool = False,
) -> Contour:
    """Map a contour by transporting the curve itself, then refitting it.

    Transforming control points is only exact when the map is affine, which is
    why a piecewise map had to be split at every band edge and still faceted.
    Instead the true mapped curve is fitted by a chain of cubics that match its
    area and first moment, with candidates checked against the fitter's sampled
    error metric. The point count returns to roughly what the face was drawn with.

    Straight segments are mapped endpoint to endpoint and stay straight: a
    diagonal would otherwise bow under a non-linear map, and a stem that was
    drawn straight has to stay straight. Real corners are detected first and
    preserved, so only smooth runs are fitted.
    """
    if not contour:
        return contour

    # Corners: where the outline genuinely turns, and where a line meets a curve.
    corner = []
    for i, (kind, pts) in enumerate(contour):
        previous_kind, previous = contour[i - 1]
        incoming = _normalise((pts[0][0] - previous[-2][0], pts[0][1] - previous[-2][1]))
        outgoing = _normalise((pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]))
        dot = max(-1.0, min(1.0, incoming[0] * outgoing[0] + incoming[1] * outgoing[1]))
        turn = math.degrees(math.acos(dot))
        corner.append(turn > CORNER_ANGLE or kind == "l" or previous_kind == "l")

    out: Contour = []
    index = 0
    count = len(contour)
    while index < count:
        kind, pts = contour[index]
        if kind == "l":
            out.append(("l", (ymap.point(pts[0]), ymap.point(pts[1]))))
            index += 1
            continue
        run = [index]
        run_start = index
        while (
            index + 1 < count and not corner[(index + 1) % count] and contour[index + 1][0] == "c"
        ):
            index += 1
            run.append(index)
        mapped = _MappedRun([contour[i][1] for i in run], ymap)
        fitted = [list(curve) for curve in _fit_chain(mapped, tolerance)]
        if preserve_stem_joins:
            _preserve_stem_join_arms(
                fitted,
                [contour[i][1] for i in run],
                contour[run_start - 1],
                contour[(index + 1) % count],
            )
        for curve in fitted:
            out.append(("c", tuple(curve)))
        index += 1
    return out


def _preserve_stem_join_arms(fitted, source, previous, following):
    """Cap tangent-arm growth where a smooth bowl joins a vertical stem.

    The straight stem itself may lengthen, but letting the adjacent curve's
    vertical control arm lengthen by the same amount postpones its turn into the
    bowl. That removes side-bearing from the shoulder and creates the pinched
    join visible in `u`, `n`, and related glyphs. Preserve the source arm when
    it is adjacent and tangent to a vertical line; shorter fitted arms are left
    alone because they already turn sooner.
    """
    if not fitted:
        return

    previous_kind, previous_points = previous
    if previous_kind == "l" and _is_smooth_vertical_join(
        previous_points[0], previous_points[1], source[0][0], source[0][1]
    ):
        source_length = math.dist(source[0][0], source[0][1])
        _cap_arm(fitted[0], 0, 1, source_length)

    following_kind, following_points = following
    if following_kind == "l" and _is_smooth_vertical_join(
        source[-1][-2], source[-1][-1], following_points[0], following_points[1]
    ):
        source_length = math.dist(source[-1][-2], source[-1][-1])
        _cap_arm(fitted[-1], 3, 2, source_length)


def _is_smooth_vertical_join(a, join, curve_join, curve_handle):
    line = (join[0] - a[0], join[1] - a[1])
    tangent = (curve_handle[0] - curve_join[0], curve_handle[1] - curve_join[1])
    line_length = math.hypot(*line)
    tangent_length = math.hypot(*tangent)
    if line_length <= 1e-9 or tangent_length <= 1e-9:
        return False
    if abs(line[0]) > line_length * math.sin(STEM_JOIN_ANGLE):
        return False
    dot = (line[0] * tangent[0] + line[1] * tangent[1]) / (line_length * tangent_length)
    return dot >= math.cos(STEM_JOIN_ANGLE)


def _cap_arm(curve, endpoint_index, handle_index, source_length):
    endpoint = curve[endpoint_index]
    handle = curve[handle_index]
    dx, dy = handle[0] - endpoint[0], handle[1] - endpoint[1]
    length = math.hypot(dx, dy)
    if length <= source_length * STEM_JOIN_GROWTH or length <= 1e-9:
        return
    curve[handle_index] = (
        endpoint[0] + dx * source_length / length,
        endpoint[1] + dy * source_length / length,
    )


def draw_contours(contours: Contours, pen: SegmentPen) -> None:
    for contour in contours:
        if not contour:
            continue
        pen.moveTo(contour[0][1][0])
        for kind, pts in contour:
            if kind == "l":
                pen.lineTo(pts[1])
            else:
                pen.curveTo(pts[1], pts[2], pts[3])
        pen.closePath()
