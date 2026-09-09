"""Pure semantic partitioning for authored curves and protected qCurve paths.

This module does not choose glyph policy.  It builds a shared operation basis
when an authored contour has a real straight extension at one master while
other masters retain the corresponding curved path. Semantic slots subdivide
protected quadratics exactly; endpoint spans retain their original point stream
and append collapsed capacity. Authored curves are fitted within the bound.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

Point = tuple[float, float]
Cubic = tuple[Point, Point, Point, Point]
Operation = tuple[str, tuple[Point, ...]]
SplineFitter = Callable[[Cubic, int, float], Sequence[Point] | None]


@dataclass(frozen=True)
class SemanticPartition:
    authored: tuple[Operation, ...]
    protected: tuple[Operation, ...]
    authored_curve_count: int
    protected_curve_count: int


def partition_endpoint_spans(
    authored_curves: Sequence[Cubic],
    protected_operation: Operation,
    fitter: SplineFitter,
    tolerance: float,
    *,
    extra_spans: int,
    split_fraction: float = 0.5,
    leading_start: Point | None = None,
    protected_start: Point | None = None,
) -> SemanticPartition:
    """Add authored capacity after an intact protected quadratic operation.

    The extra protected spans collapse at its explicit endpoint. None of the
    original off-curves, implied points or endpoints is subdivided or refitted.
    A single authored cubic is split at the requested parameter (default 0.5);
    two existing authored cubics retain their seam. An optional leading span
    holds a straight authored extension and collapses at the protected start.
    Sparse variation transport must still
    preserve omitted-point interpolation after compatible compilation.
    """
    kind, points = protected_operation
    if kind != "qCurveTo" or len(points) < 2:
        raise ValueError("endpoint spans require an explicit protected qCurveTo")
    if type(extra_spans) is not int or extra_spans < 1:
        raise ValueError("extra_spans must be a positive integer")
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("endpoint span tolerance must be finite and positive")
    if (
        isinstance(split_fraction, bool)
        or not isinstance(split_fraction, (int, float))
        or not math.isfinite(split_fraction)
        or not 0 < split_fraction < 1
    ):
        raise ValueError("endpoint split fraction must be finite and strictly between zero and one")
    if len(authored_curves) == 2 and split_fraction != 0.5:
        raise ValueError("an explicit authored seam cannot also specify a split fraction")
    if (leading_start is None) != (protected_start is None):
        raise ValueError("leading capacity requires both authored and protected starts")
    if len(authored_curves) not in (1, 2) or any(len(curve) != 4 for curve in authored_curves):
        raise ValueError("endpoint spans require one or two authored cubics")
    starts = () if leading_start is None else (leading_start, protected_start)
    for point in (*points, *starts, *(point for curve in authored_curves for point in curve)):
        if point is None or len(point) != 2 or not all(math.isfinite(value) for value in point):
            raise ValueError("endpoint span coordinates must be finite explicit points")
    curves = list(authored_curves)
    if len(curves) == 1:
        a, b, c, d = curves[0]

        def interpolate(left: Point, right: Point) -> Point:
            if split_fraction == 0.5:
                return ((left[0] + right[0]) / 2, (left[1] + right[1]) / 2)
            return (
                left[0] * (1 - split_fraction) + right[0] * split_fraction,
                left[1] * (1 - split_fraction) + right[1] * split_fraction,
            )

        ab, bc, cd = interpolate(a, b), interpolate(b, c), interpolate(c, d)
        abc, bcd = interpolate(ab, bc), interpolate(bc, cd)
        seam = interpolate(abc, bcd)
        curves = [(a, ab, abc, seam), (seam, bcd, cd, d)]
    elif curves[0][-1] != curves[1][0]:
        raise ValueError("authored endpoint spans have a disconnected seam")
    native_count = len(points) - 1
    authored: list[Operation] = []
    protected_prefix: tuple[Operation, ...] = ()
    if leading_start is not None:
        assert protected_start is not None
        end = curves[0][0]
        midpoint = ((leading_start[0] + end[0]) / 2, (leading_start[1] + end[1]) / 2)
        authored.append(("qCurveTo", (midpoint, end)))
        protected_prefix = (("qCurveTo", (protected_start, protected_start)),)
    for curve, count in zip(curves, (native_count, extra_spans), strict=True):
        spline = fitter(curve, count, tolerance)
        if spline is None or len(spline) != count + 2:
            raise ValueError("authored endpoint spans exceed the conversion bound")
        if spline[0] != curve[0] or spline[-1] != curve[-1]:
            raise ValueError("endpoint span fitting changed an authored endpoint")
        if any(not all(math.isfinite(value) for value in point) for point in spline):
            raise ValueError("endpoint span fitting returned nonfinite coordinates")
        authored.append(("qCurveTo", tuple(spline[1:])))
    collapsed: Operation = ("qCurveTo", (points[-1],) * (extra_spans + 1))
    return SemanticPartition(
        tuple(authored),
        (*protected_prefix, protected_operation, collapsed),
        native_count + extra_spans + len(protected_prefix),
        native_count + extra_spans + len(protected_prefix),
    )


def _point(value: Point, label: str) -> complex:
    if len(value) != 2:
        raise ValueError(f"{label} must be a two-dimensional point")
    return complex(*value)


def _bezier(points: Sequence[Point], parameter: float) -> complex:
    work = [_point(point, "Bézier point") for point in points]
    while len(work) > 1:
        work = [
            left + (right - left) * parameter for left, right in zip(work, work[1:], strict=False)
        ]
    return work[0]


def subdivide_quadratic_chain(
    start: Point, operation: Operation, subdivisions: int
) -> tuple[Point, ...]:
    """Return one exactly equivalent qCurve point stream with more spans."""
    kind, points = operation
    if kind != "qCurveTo" or len(points) < 2:
        raise ValueError("protected operation must be a nonempty qCurveTo")
    if type(subdivisions) is not int or subdivisions < 1:
        raise ValueError("subdivisions must be a positive integer")
    controls, endpoint = list(points[:-1]), points[-1]
    current = start
    expanded: list[Point] = []
    for index, control in enumerate(controls):
        end = (
            endpoint
            if index == len(controls) - 1
            else (
                (control[0] + controls[index + 1][0]) / 2,
                (control[1] + controls[index + 1][1]) / 2,
            )
        )
        for step in range(subdivisions):
            parameter = step / subdivisions
            point = _bezier((current, control, end), parameter)
            derivative = 2 * (
                (1 - parameter) * (_point(control, "control") - _point(current, "start"))
                + parameter * (_point(end, "end") - _point(control, "control"))
            )
            quadratic_control = point + derivative / (2 * subdivisions)
            expanded.append((quadratic_control.real, quadratic_control.imag))
        current = end
    return (*expanded, endpoint)


def _split_first_span(points: Sequence[Point]) -> tuple[Operation, Operation]:
    if len(points) < 3:
        raise ValueError("a semantic slot requires at least two quadratic spans")
    first, second = points[0], points[1]
    join = ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)
    return ("qCurveTo", (first, join)), ("qCurveTo", tuple(points[1:]))


def partition_semantic_curve(
    authored_curve: Cubic,
    protected_start: Point,
    protected_operation: Operation,
    fitter: SplineFitter,
    tolerance: float,
    *,
    subdivisions: int = 2,
    semantic_slot: bool = False,
    straight_extension: tuple[Point, Point] | None = None,
) -> SemanticPartition:
    """Fit an authored cubic and exactly partition its protected counterpart.

    ``semantic_slot`` reserves one leading quadratic span.  At a master with a
    real extension, that span represents the line and the curve uses the
    remaining capacity.  At masters without the extension, both authored and
    protected curves split their first fitted span at the same semantic join.
    """
    if straight_extension is not None and not semantic_slot:
        raise ValueError("a straight extension requires a semantic slot")
    if straight_extension is not None:
        line_start, line_end = straight_extension
        if line_end != authored_curve[0]:
            raise ValueError("straight extension must end at the authored curve start")
        if line_start == line_end:
            raise ValueError("straight extension must have positive length")
    protected_points = subdivide_quadratic_chain(protected_start, protected_operation, subdivisions)
    protected_count = len(protected_points) - 1
    authored_count = protected_count - (1 if straight_extension is not None else 0)
    if authored_count < 1:
        raise ValueError("semantic partition leaves no capacity for the authored curve")
    spline = fitter(authored_curve, authored_count, tolerance)
    if spline is None or len(spline) != authored_count + 2:
        raise ValueError("authored curve exceeds the semantic partition bound")
    authored_curve_operation: Operation = ("qCurveTo", tuple(spline[1:]))
    if not semantic_slot:
        return SemanticPartition(
            (authored_curve_operation,),
            (("qCurveTo", protected_points),),
            authored_count,
            protected_count,
        )
    protected_slot, protected_curve = _split_first_span(protected_points)
    authored: tuple[Operation, ...]
    if straight_extension is not None:
        line_start, line_end = straight_extension
        midpoint = ((line_start[0] + line_end[0]) / 2, (line_start[1] + line_end[1]) / 2)
        authored = (("qCurveTo", (midpoint, line_end)), authored_curve_operation)
    else:
        authored_slot, authored_remainder = _split_first_span(spline[1:])
        authored = (authored_slot, authored_remainder)
    return SemanticPartition(
        authored,
        (protected_slot, protected_curve),
        authored_count,
        protected_count,
    )
