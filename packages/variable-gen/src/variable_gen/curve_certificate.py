"""Conservative, symmetric geometric distance checks for short Bézier paths.

This certificate is independent of the parameterization used by a fitter.
It bounds geometric distance, not topology, curvature, or stroke thickness.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence

Point = tuple[float, float]


def _distance(point: complex, start: complex, end: complex) -> float:
    delta = end - start
    if not delta:
        return abs(point - start)
    t = max(0.0, min(1.0, ((point - start) * delta.conjugate()).real / abs(delta) ** 2))
    return abs(point - (start + t * delta))


def _flatten(curve: tuple[complex, ...], error: float, depth: int = 0) -> list[complex]:
    # The capsule around the chord is convex. If every control is in it,
    # every curve point is within error of the chord. Continuity of the
    # projection from first to last endpoint proves the reverse direction.
    if all(_distance(point, curve[0], curve[-1]) <= error for point in curve[1:-1]):
        return [curve[0], curve[-1]]
    if depth >= 24:
        raise ValueError("Curve distance certificate exceeded subdivision limit")
    levels = [curve]
    while len(levels[-1]) > 1:
        levels.append(tuple((a + b) / 2 for a, b in zip(levels[-1], levels[-1][1:], strict=False)))
    left = tuple(level[0] for level in levels)
    right = tuple(level[-1] for level in reversed(levels))
    return _flatten(left, error, depth + 1)[:-1] + _flatten(right, error, depth + 1)


def _polyline(curves: Sequence[Sequence[Point]], error: float, step: float) -> list[complex]:
    result: list[complex] = []
    for raw in curves:
        if len(raw) not in {3, 4} or any(
            len(point) != 2 or not all(math.isfinite(value) for value in point) for point in raw
        ):
            raise ValueError("Certificate requires finite quadratic or cubic controls")
        curve = tuple(complex(*point) for point in raw)
        if result and abs(result[-1] - curve[0]) > 1e-10:
            raise ValueError("Certificate path must be connected")
        flat = _flatten(curve, error)
        if not result:
            result.append(flat[0])
        for start, end in zip(flat, flat[1:], strict=False):
            count = max(1, math.ceil(abs(end - start) / step))
            if len(result) + count > 500_000:
                raise ValueError("Curve distance certificate exceeded point limit")
            result.extend(start + (end - start) * index / count for index in range(1, count + 1))
    return result


def _directed_within(source: list[complex], target: list[complex], radius: float) -> bool:
    cells: dict[tuple[int, int], list[tuple[complex, complex]]] = defaultdict(list)
    for start, end in zip(target, target[1:], strict=False):
        for x in range(
            math.floor(min(start.real, end.real) / radius),
            math.floor(max(start.real, end.real) / radius) + 1,
        ):
            for y in range(
                math.floor(min(start.imag, end.imag) / radius),
                math.floor(max(start.imag, end.imag) / radius) + 1,
            ):
                cells[x, y].append((start, end))
    for point in source:
        x, y = math.floor(point.real / radius), math.floor(point.imag / radius)
        if not any(
            _distance(point, start, end) <= radius
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for start, end in cells.get((x + dx, y + dy), ())
        ):
            return False
    return True


def certify_curve_distance(
    source: Sequence[Sequence[Point]], target: Sequence[Sequence[Point]], tolerance: float
) -> bool:
    """Prove symmetric path distance <= tolerance, or conservatively return False.

    Every exact path is within epsilon of its polyline, in both directions.
    Polyline vertices are tested against actual target segments. All intervening
    points are within half a maximum edge length of a tested vertex, so the
    total upper bound is radius + step/2 + 2*epsilon. A small numerical margin
    is reserved as well. This does not certify matching traversal or topology.
    """
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("Certificate tolerance must be finite and positive")
    if not source or not target:
        return False
    epsilon, step = tolerance / 32, tolerance / 4
    radius = tolerance - step / 2 - 2 * epsilon - max(1e-9, tolerance * 1e-10)
    if radius <= 0:
        return False
    left = _polyline(source, epsilon, step)
    right = _polyline(target, epsilon, step)
    return _directed_within(left, right, radius) and _directed_within(right, left, radius)
