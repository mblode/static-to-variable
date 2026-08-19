from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fontTools.pens.recordingPen import RecordingPen

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PACKAGE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from variable_gen.xheight import (  # noqa: E402
    BandMap,
    Contour,
    build_map,
    contours_of,
    draw_contours,
    map_contours,
    redraw_polygons,
    runs_at,
)


def _rectangle(left: float, bottom: float, right: float, top: float) -> Contour:
    points = [(left, bottom), (right, bottom), (right, top), (left, top)]
    return [("l", (points[i], points[(i + 1) % 4])) for i in range(4)]


def _map() -> BandMap:
    return build_map([_rectangle(0, 0, 100, 500)], 40, 500, 510, 700, 80)


def _cubic_point(points: tuple[tuple[float, float], ...], t: float) -> tuple[float, float]:
    p0, p1, p2, p3 = points
    u = 1 - t
    return (
        u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
        u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
    )


def _distance_to_cubic(point: tuple[float, float], curve: tuple[tuple[float, float], ...]) -> float:
    """Independent nearest-point estimate: coarse search, then golden-section refinement."""

    def distance2(t: float) -> float:
        hit = _cubic_point(curve, t)
        return (hit[0] - point[0]) ** 2 + (hit[1] - point[1]) ** 2

    steps = 128
    nearest = min(range(steps + 1), key=lambda i: distance2(i / steps))
    low = max(0.0, (nearest - 1) / steps)
    high = min(1.0, (nearest + 1) / steps)
    ratio = (5**0.5 - 1) / 2
    left = high - ratio * (high - low)
    right = low + ratio * (high - low)
    for _ in range(24):
        if distance2(left) < distance2(right):
            high, right = right, left
            left = high - ratio * (high - low)
        else:
            low, left = left, right
            right = low + ratio * (high - low)
    return distance2((low + high) / 2) ** 0.5


def test_band_map_hits_structural_heights_and_stays_monotonic() -> None:
    ymap = _map()

    assert ymap(0) == pytest.approx(0)
    assert ymap(500) == pytest.approx(540)
    assert ymap(510) == pytest.approx(550)
    assert ymap(700) == pytest.approx(700)

    samples = [ymap(y) for y in range(0, 701)]
    assert all(after > before for before, after in zip(samples, samples[1:], strict=False))
    assert max(ymap.rate(y) for y in range(1, 500)) <= 1.22 + 1e-9
    assert min(ymap.rate(y) for y in range(511, 700)) >= 0.5 - 1e-9


def test_band_map_rate_is_continuous_at_every_knot() -> None:
    ymap = _map()
    epsilon = 1e-5

    for knot in ymap.breaks:
        assert ymap.rate(knot - epsilon) == pytest.approx(ymap.rate(knot + epsilon), abs=1e-4)


def test_uniform_lower_map_matches_isotropic_scale_away_from_alignment_edges() -> None:
    scale = 525 / 474
    ymap = build_map(
        [_rectangle(0, 0, 100, 474)],
        51,
        474,
        484,
        700,
        40,
        uniform_lower=True,
    )

    assert ymap(474) == pytest.approx(525)
    for y in (50, 150, 250, 350, 425):
        assert ymap.rate(y) == pytest.approx(scale, abs=1e-6)


def test_floating_contour_follows_base_without_being_strained() -> None:
    ymap = _map()
    base = _rectangle(0, 0, 100, 500)
    accent = _rectangle(30, 550, 70, 580)

    mapped = map_contours([base, accent], ymap, 40, 510)

    assert mapped[0][1][1][1][1] == pytest.approx(540)
    assert mapped[1] == [(kind, tuple((x, y + 40) for x, y in points)) for kind, points in accent]


def test_rigid_contour_keeps_its_size_and_two_of_them_stay_equal() -> None:
    """A circle must not be strained by a map that is piecewise linear in y.

    Two identical squares at different heights stand in for the two dots of
    `divide`, which Circular draws the same size at y 104 and y 496. Straining
    each through its own stretch of the map is what shipped them 34% apart in
    area; marking them rigid must leave both the size they were drawn and equal
    to each other, while still moving them to where the raise puts them.
    """
    ymap = _map()
    base = _rectangle(0, 0, 100, 500)
    low = _rectangle(200, 100, 260, 160)
    high = _rectangle(200, 470, 260, 530)

    strained = map_contours([base, low, high], ymap, 40, 510)
    rigid = map_contours([base, low, high], ymap, 40, 510, rigid={1, 2})

    def height(contour):
        ys = [point[1] for _, points in contour for point in points]
        return max(ys) - min(ys)

    def centre(contour):
        ys = [point[1] for _, points in contour for point in points]
        return (min(ys) + max(ys)) / 2

    # The bug: strained, the two squares come out different heights.
    assert height(strained[1]) != pytest.approx(height(strained[2]), abs=0.5)

    assert height(rigid[1]) == pytest.approx(60)
    assert height(rigid[2]) == pytest.approx(60)
    # Each still lands where the map sends its own centre, so the raise still
    # happens -- rigid means unstrained, not unmoved.
    assert centre(rigid[1]) == pytest.approx(ymap(130))
    assert centre(rigid[2]) == pytest.approx(ymap(500))
    assert centre(rigid[2]) > centre(rigid[1])
    # Everything else is untouched by the flag.
    assert rigid[0] == strained[0]


def test_polygon_correction_is_noop_when_strain_preserves_stroke_weight() -> None:
    source = [_rectangle(0, 0, 100, 500)]
    ymap = _map()
    mapped = map_contours(source, ymap, 40, 510)

    assert redraw_polygons(mapped, source, ymap, 80) == mapped


def test_refit_maps_cubic_endpoints_without_turning_lines_into_curves() -> None:
    source: Contour = [
        ("l", ((0, 0), (100, 0))),
        ("c", ((100, 0), (120, 20), (120, 480), (100, 500))),
        ("l", ((100, 500), (0, 500))),
        ("l", ((0, 500), (0, 0))),
    ]

    mapped = map_contours([source], _map(), 40, 510, refit=True)[0]

    assert [kind for kind, _ in mapped] == ["l", "c", "l", "l"]
    assert mapped[1][1][0] == (100, 0)
    assert mapped[1][1][-1] == pytest.approx((100, 540))


def test_representative_refit_is_measured_against_true_mapped_curve() -> None:
    source_curve = ((100, 0), (120, 20), (120, 480), (100, 500))
    source: Contour = [
        ("l", ((0, 0), source_curve[0])),
        ("c", source_curve),
        ("l", (source_curve[-1], (0, 500))),
        ("l", ((0, 500), (0, 0))),
    ]
    ymap = _map()
    fitted = map_contours([source], ymap, 40, 510, refit=True)[0][1][1]

    errors = []
    for index in range(501):
        source_point = _cubic_point(source_curve, index / 500)
        target = (source_point[0], ymap(source_point[1]))
        errors.append(_distance_to_cubic(target, fitted))

    # Characterizes this fixture only. Production users still validate their
    # complete donor set independently because the sampled fitter metric is not
    # a mathematical bound over every possible curve.
    assert max(errors) < 0.4


def test_contours_round_trip_through_segment_pen() -> None:
    class Glyph:
        def draw(self, pen: RecordingPen) -> None:
            pen.moveTo((0, 0))
            pen.lineTo((100, 0))
            pen.curveTo((120, 20), (120, 80), (100, 100))
            pen.lineTo((0, 100))
            pen.closePath()

    contours = contours_of({"shape": Glyph()}, "shape")
    pen = RecordingPen()
    draw_contours(contours, pen)

    assert [operation for operation, _ in pen.value] == [
        "moveTo",
        "lineTo",
        "curveTo",
        "lineTo",
        "lineTo",
        "closePath",
    ]


def test_scanline_runs_use_nonzero_winding() -> None:
    segments = [segment[1] for segment in _rectangle(10, 0, 30, 20)]

    assert runs_at(segments, 10) == [(10, 30)]


def test_pin_horizontals_keeps_wide_band_from_absorbing_strain() -> None:
    # Tall stems + a wide mid bar (crossbar-like): pin should keep the bar's
    # local rate near 1 (translate) while stems stretch.
    stem = _rectangle(0, 0, 40, 500)
    bar = _rectangle(0, 220, 200, 280)
    contours = [stem, bar]
    free = build_map(contours, 50, 500, 510, 700, 40, pin_horizontals=False)
    pinned = build_map(contours, 50, 500, 510, 700, 40, pin_horizontals=True)
    # Mid-bar zone: pinned map should strain less than the free map.
    assert pinned.rate(250) < free.rate(250)
    assert pinned.rate(250) < 1.05
    assert pinned(500) == pytest.approx(550)


def _circle(cx: float, cy: float, r: float) -> Contour:
    """A four-cubic circle, which is how a bowl is drawn."""
    k = r * 0.5522847498
    on = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]
    off = [
        [(cx + k, cy - r), (cx + r, cy - k)],
        [(cx + r, cy + k), (cx + k, cy + r)],
        [(cx - k, cy + r), (cx - r, cy + k)],
        [(cx - r, cy - k), (cx - k, cy - r)],
    ]
    return [("c", (on[i], off[i][0], off[i][1], on[(i + 1) % 4])) for i in range(4)]


def _end_curvatures(curve: tuple[tuple[float, float], ...]) -> tuple[float, float]:
    """Signed curvature entering and leaving a cubic, from its control arms."""
    out = []
    for p0, p1, p2 in ((curve[0], curve[1], curve[2]), (curve[3], curve[2], curve[1])):
        ax, ay = p1[0] - p0[0], p1[1] - p0[1]
        bx, by = p2[0] - p1[0], p2[1] - p1[1]
        arm = (ax * ax + ay * ay) ** 0.5
        out.append(0.0 if arm < 1e-9 else (2 / 3) * (ax * by - ay * bx) / arm**3)
    return out[0], -out[1]


def _worst_join_step(contour: Contour) -> float:
    """Largest curvature step across a join, as a fraction of the curvature there."""
    worst = 0.0
    for index, (kind, pts) in enumerate(contour):
        previous_kind, previous = contour[index - 1]
        if kind != "c" or previous_kind != "c":
            continue
        leaving = _end_curvatures(previous)[1]
        entering = _end_curvatures(pts)[0]
        scale = max(abs(leaving), abs(entering))
        if scale > 1e-9:
            worst = max(worst, abs(leaving - entering) / scale)
    return worst


def test_end_curvature_of_a_drawn_circle_matches_its_radius() -> None:
    """The fitter's curvature reading has to be right before it can rank joins.

    A circle drawn as four cubics is itself an approximation -- the classic arm
    length holds the radius to a fraction of a percent through the middle of each
    arc and runs about 2% under at the ends -- so the tolerance here is the
    drawing's, not the formula's.
    """
    for radius in (60.0, 250.0):
        for curve in (pts for _, pts in _circle(0, 0, radius)):
            entering, leaving = _end_curvatures(curve)
            assert entering == pytest.approx(1 / radius, rel=0.03)
            assert leaving == pytest.approx(1 / radius, rel=0.03)


def test_refit_does_not_facet_a_bowl_the_way_a_positional_fit_does() -> None:
    """Splits are chosen for curvature, not only for position.

    This bowl reaches from below the baseline into the ascender region, so the
    map is genuinely non-affine across it and the refit runs rather than taking
    the direct-map shortcut. Fitting it by the longest span that holds within the
    tolerance -- the search this replaced -- leaves a curvature step of 1.83 at
    its worst join, a discontinuity nearly twice the curvature it interrupts. The
    same bowl, split by the curvature-aware search, comes back at 1.00 for the
    same seven cubics.

    The bound characterises this fixture. The fitter's real budget is measured
    against the donor set as a whole, per glyph, because a sampled metric over
    one synthetic bowl is not a bound over every curve a face is drawn with.
    """
    source = _circle(400, 320, 300)

    refitted = map_contours([source], _map(), 40, 510, refit=True)[0]

    assert all(kind == "c" for kind, _ in refitted)
    assert len(refitted) <= 7
    assert _worst_join_step(refitted) < 1.4
