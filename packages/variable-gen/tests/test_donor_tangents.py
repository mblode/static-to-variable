"""The donor-tangent lookup used by the cubic refit.

Every case is synthetic geometry with a closed-form answer, so a maths mistake
fails here rather than as a shape nobody notices in a built font.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from variable_gen.reconstruct_compatible import (  # noqa: E402
    _analytic_ring,
    _match_original,
    _RingTangents,
)

K = 0.5522847498307936


def _circle(radius, cx=0.0, cy=0.0):
    """A four-segment kappa-Bezier circle as pen ops."""
    points = [(cx + radius, cy), (cx, cy + radius), (cx - radius, cy), (cx, cy - radius)]
    tangents = [(0, radius * K), (-radius * K, 0), (0, -radius * K), (radius * K, 0)]
    ops = [("moveTo", [points[0]])]
    for index in range(4):
        start, end = points[index], points[(index + 1) % 4]
        out_tan, in_tan = tangents[index], tangents[(index + 1) % 4]
        ops.append(
            (
                "curveTo",
                [
                    (start[0] + out_tan[0], start[1] + out_tan[1]),
                    (end[0] - in_tan[0], end[1] - in_tan[1]),
                    end,
                ],
            )
        )
    ops.append(("closePath", []))
    return ops


def _ring_of(contour, count=64):
    """A polyline around the contour, the way the resampler produces one."""
    samples, _total = _analytic_ring(contour)
    step = max(1, len(samples) // count)
    return [point for point, _tangent, _position in samples[::step]]


def test_analytic_ring_arclength_matches_the_circle_it_samples() -> None:
    samples, total = _analytic_ring(_circle(100))
    assert total == pytest.approx(2 * math.pi * 100, rel=1e-3)
    assert all(tangent is not None for _p, tangent, _u in samples)


def test_tangent_on_a_circle_is_perpendicular_to_its_radius() -> None:
    """The one shape whose tangent is known everywhere without fitting anything."""
    contour = _circle(100)
    ring = _ring_of(contour)
    lookup = _RingTangents(ring, contour)
    assert lookup.ok

    worst = 0.0
    for index, point in enumerate(ring):
        radial = (point[0] / 100.0, point[1] / 100.0)
        # Walking the ring forwards, the tangent is the radius turned 90 degrees.
        hint = (-radial[1], radial[0])
        tangent = lookup.at(index, point, hint)
        assert tangent is not None
        dot = abs(tangent[0] * radial[0] + tangent[1] * radial[1])
        worst = max(worst, math.degrees(math.asin(min(1.0, dot))))
    assert worst < 1.0


def test_a_ring_running_backwards_is_detected_and_still_answered() -> None:
    contour = _circle(100)
    ring = list(reversed(_ring_of(contour)))
    lookup = _RingTangents(ring, contour)
    assert lookup.ok
    for index, point in enumerate(ring):
        radial = (point[0] / 100.0, point[1] / 100.0)
        hint = (radial[1], -radial[0])
        tangent = lookup.at(index, point, hint)
        assert tangent is not None
        dot = abs(tangent[0] * radial[0] + tangent[1] * radial[1])
        assert math.degrees(math.asin(min(1.0, dot))) < 1.5


def test_two_equal_circles_are_matched_by_where_they_sit() -> None:
    """The case nearest-point matching cannot do: same size, different place."""
    left = _circle(40, cx=-200)
    right = _circle(40, cx=200)
    ring = _ring_of(right)
    assert _match_original(ring, [left, right]) is right
    assert _match_original(_ring_of(left), [left, right]) is left


def test_lookup_declines_rather_than_guessing_on_a_degenerate_ring() -> None:
    assert not _RingTangents([(0.0, 0.0), (1.0, 1.0)], _circle(50)).ok
    assert not _RingTangents(_ring_of(_circle(50)), []).ok
