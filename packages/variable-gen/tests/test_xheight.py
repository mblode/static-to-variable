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


def test_floating_contour_follows_base_without_being_strained() -> None:
    ymap = _map()
    base = _rectangle(0, 0, 100, 500)
    accent = _rectangle(30, 550, 70, 580)

    mapped = map_contours([base, accent], ymap, 40, 510)

    assert mapped[0][1][1][1][1] == pytest.approx(540)
    assert mapped[1] == [(kind, tuple((x, y + 40) for x, y in points)) for kind, points in accent]


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
