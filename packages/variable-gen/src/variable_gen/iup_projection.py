"""Project an authored integer default onto a native sparse-IUP coordinate frame.

Only mapped native points are constrained here. A caller adding contour points
must separately qualify its expanded sparse tuples and rendered variable font.
"""

import math
from dataclasses import dataclass
from fractions import Fraction

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from variable_gen.common import PipelineError


@dataclass(frozen=True)
class IupProjection:
    coordinates: tuple[tuple[int, int], ...]
    maximum_movement: tuple[float, float]
    constraint_counts: tuple[int, int]


def _integer(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer)):
        raise PipelineError("IUP projection requires integer coordinates and indexes")
    if not math.isfinite(value) or int(value) != value:
        raise PipelineError("IUP projection requires finite integer coordinates")
    return int(value)


def _points(values):
    result = []
    for point in values:
        if len(point) != 2:
            raise PipelineError("IUP projection requires two-dimensional coordinates")
        result.append(tuple(_integer(value) for value in point))
    return result


def exact_iup_deltas(coordinates, contour_ends, deltas):
    """Infer integer gvar inputs with rational arithmetic, including phantoms.

    This checks interpolation semantics without confusing floating evaluation
    order with a changed ratio. Rendered/binary fidelity remains a separate gate.
    """
    points = _points(coordinates)
    ends = [_integer(value) for value in contour_ends]
    if (
        not ends
        or ends != sorted(set(ends))
        or ends[0] < 0
        or ends[-1] != len(points) - 5
        or len(deltas) != len(points)
    ):
        raise PipelineError("Exact IUP inference requires valid contours and four phantoms")
    sparse = [None if point is None else _points([point])[0] for point in deltas]
    result = [(Fraction(0), Fraction(0)) for _ in points]
    start = 0
    for end in [*ends, *range(len(points) - 4, len(points))]:
        anchors = [i for i in range(start, end + 1) if sparse[i] is not None]
        if len(anchors) == 1:
            point = sparse[anchors[0]]
            assert point is not None
            result[start : end + 1] = [(Fraction(point[0]), Fraction(point[1]))] * (end + 1 - start)
        elif anchors:
            for position, before in enumerate(anchors):
                after = anchors[(position + 1) % len(anchors)]
                point = sparse[before]
                assert point is not None
                result[before] = (Fraction(point[0]), Fraction(point[1]))
                omitted = (
                    range(before + 1, after)
                    if before < after
                    else (*range(before + 1, end + 1), *range(start, after))
                )
                for index in omitted:
                    values = []
                    for axis in (0, 1):
                        a, b = before, after
                        if points[a][axis] > points[b][axis]:
                            a, b = b, a
                        xa, xb, x = points[a][axis], points[b][axis], points[index][axis]
                        delta_a, delta_b = sparse[a], sparse[b]
                        assert delta_a is not None and delta_b is not None
                        da, db = delta_a[axis], delta_b[axis]
                        if xa == xb:
                            value = Fraction(da if da == db else 0)
                        elif x <= xa:
                            value = Fraction(da)
                        elif x >= xb:
                            value = Fraction(db)
                        else:
                            value = Fraction(da) + Fraction((x - xa) * (db - da), xb - xa)
                        values.append(value)
                    result[index] = (values[0], values[1])
        start = end + 1
    return result


def project_native_iup_default(
    native_coordinates,
    contour_ends,
    variations,
    desired_coordinates,
    native_to_candidate,
    *,
    fixed_coordinates=None,
    max_move=1000.0,
    time_limit=45.0,
) -> IupProjection:
    """Minimize maximum, then total, movement while retaining native IUP ratios.

    Coordinate arrays include four phantom points. The mapping is injective and
    covers every native point; the last four map to the candidate's last four.
    Phantom coordinates remain fixed. Additional fixed landmarks are supplied
    as ``{(candidate_index, axis): integer_coordinate}`` by the drawing owner.
    Every sparse variation is constrained, independently for both coordinates.
    No font or input array is mutated. Infeasibility and solver limits fail closed.
    """
    if any(
        isinstance(value, bool) or not math.isfinite(value) or value <= 0
        for value in (max_move, time_limit)
    ):
        raise PipelineError("IUP projection limits must be finite and positive")
    native = _points(native_coordinates)
    desired = _points(desired_coordinates)
    ends = [_integer(value) for value in contour_ends]
    mapping = [_integer(value) for value in native_to_candidate]
    count = len(desired)
    if (
        len(native) < 5
        or count < 5
        or not ends
        or ends != sorted(set(ends))
        or ends[0] < 0
        or ends[-1] != len(native) - 5
        or len(mapping) != len(native)
        or len(set(mapping)) != len(mapping)
        or any(index < 0 or index >= count for index in mapping)
        or mapping[-4:] != list(range(count - 4, count))
    ):
        raise PipelineError("Invalid IUP contour ends or complete native point mapping")
    sparse = []
    for variation in variations:
        if len(variation) != len(native):
            raise PipelineError("Sparse IUP tuple does not cover the native point array")
        sparse.append([None if point is None else _points([point])[0] for point in variation])
    if not sparse:
        raise PipelineError("IUP projection requires at least one sparse variation")
    fixed = {(i, axis): desired[i][axis] for i in range(count - 4, count) for axis in (0, 1)}
    for key, value in (fixed_coordinates or {}).items():
        if not isinstance(key, tuple) or len(key) != 2:
            raise PipelineError("Fixed IUP landmarks require (point index, axis) keys")
        index, axis = (_integer(part) for part in key)
        value = _integer(value)
        if index < 0 or index >= count or axis not in (0, 1):
            raise PipelineError("Invalid fixed IUP landmark")
        if (index, axis) in fixed and fixed[index, axis] != value:
            raise PipelineError("Fixed IUP landmark changes a phantom coordinate")
        fixed[index, axis] = value
    if any(not -32768 <= value <= 32767 for point in desired for value in point):
        raise PipelineError("Desired IUP coordinates exceed the signed 16-bit frame")
    if any(not -32768 <= value <= 32767 for value in fixed.values()):
        raise PipelineError("Fixed IUP landmark exceeds the signed 16-bit frame")

    # Discover brackets per contour, including wraparound, without unbounded scans.
    brackets: list[tuple[int, int, int, list]] = []
    for variation in sparse:
        start = 0
        for end in ends:
            anchors = [i for i in range(start, end + 1) if variation[i] is not None]
            if len(anchors) > 1:
                for position, before in enumerate(anchors):
                    after = anchors[(position + 1) % len(anchors)]
                    omitted = (
                        range(before + 1, after)
                        if before < after
                        else (*range(before + 1, end + 1), *range(start, after))
                    )
                    brackets.extend((i, before, after, variation) for i in omitted)
            start = end + 1

    projected = np.array(desired, dtype=float)
    movements, counts = [], []
    for axis in (0, 1):
        rows: list[np.ndarray] = []
        lows: list[float] = []
        highs: list[float] = []

        def add(coefficients, low, high, rows=rows, lows=lows, highs=highs):
            row = np.zeros(count + 1)
            for index, coefficient in coefficients.items():
                row[index] = coefficient
            rows.append(row)
            lows.append(low)
            highs.append(high)

        for i, a, b, variation in brackets:
            if native[a][axis] > native[b][axis]:
                a, b = b, a
            if variation[a][axis] == variation[b][axis]:
                continue  # Equal deltas are independent of coordinates.
            xa, xb, xi = native[a][axis], native[b][axis], native[i][axis]
            if xa == xb:
                # Equal-position unequal-delta anchors infer zero at every point.
                add({mapping[a]: 1, mapping[b]: -1}, 0, 0)
                continue
            if xi <= xa:
                add({mapping[i]: 1, mapping[a]: -1}, -np.inf, 0)
            elif xi >= xb:
                add({mapping[i]: 1, mapping[b]: -1}, 0, np.inf)
            else:
                add({mapping[i]: xb - xa, mapping[a]: -(xb - xi), mapping[b]: -(xi - xa)}, 0, 0)
            add({mapping[a]: 1, mapping[b]: -1}, -np.inf, -1)
        counts.append(len(rows))
        for i in range(count):
            for sign in (-1, 1):
                add({i: sign, count: -1}, -np.inf, sign * desired[i][axis])
        lower = np.full(count + 1, -32768.0)
        upper = np.full(count + 1, 32767.0)
        lower[-1], upper[-1] = 0, max_move
        for (index, dimension), value in fixed.items():
            if dimension == axis:
                lower[index] = upper[index] = value
        objective = np.zeros(count + 1)
        objective[-1] = 1
        first = milp(
            objective,
            integrality=np.r_[np.ones(count), 0],
            bounds=Bounds(lower, upper),
            constraints=LinearConstraint(np.array(rows), lows, highs),
            options={"time_limit": time_limit, "mip_rel_gap": 0},
        )
        if not first.success:
            raise PipelineError(f"IUP minimax projection failed: {first.message}")
        second_rows = np.c_[rows, np.zeros((len(rows), count))].tolist()
        second_lows, second_highs = list(lows), list(highs)
        for i in range(count):
            for sign in (-1, 1):
                row = np.zeros(2 * count + 1)
                row[i], row[count + 1 + i] = sign, -1
                second_rows.append(row)
                second_lows.append(-np.inf)
                second_highs.append(sign * desired[i][axis])
        upper[-1] = first.fun + 1e-7
        second = milp(
            np.r_[np.zeros(count + 1), np.ones(count)],
            integrality=np.r_[np.ones(count), np.zeros(count + 1)],
            bounds=Bounds(np.r_[lower, np.zeros(count)], np.r_[upper, np.full(count, max_move)]),
            constraints=LinearConstraint(second_rows, second_lows, second_highs),
            options={"time_limit": time_limit, "mip_rel_gap": 0},
        )
        if not second.success:
            raise PipelineError(f"IUP minimum-total-motion projection failed: {second.message}")
        values = [int(round(value)) for value in second.x[:count]]
        # Solver tolerances are not permission to relax native rational equalities.
        for row, low, high in zip(
            rows[: counts[-1]], lows[: counts[-1]], highs[: counts[-1]], strict=True
        ):
            value = sum(
                int(coefficient) * point
                for coefficient, point in zip(row[:-1], values, strict=True)
            )
            if not low <= value <= high:
                raise PipelineError("Rounded IUP projection violates an exact native constraint")
        if any(values[i] != value for (i, dim), value in fixed.items() if dim == axis):
            raise PipelineError("Rounded IUP projection changed a fixed landmark")
        movement = max(abs(value - desired[i][axis]) for i, value in enumerate(values))
        if movement > max_move or movement > first.fun + 1e-7:
            raise PipelineError("Rounded IUP projection exceeds the minimax movement budget")
        projected[:, axis] = values
        movements.append(float(movement))
    return IupProjection(
        tuple((int(x), int(y)) for x, y in projected),
        (movements[0], movements[1]),
        (counts[0], counts[1]),
    )
