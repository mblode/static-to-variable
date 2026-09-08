"""Pure semantic partitioning for authored curves and protected qCurve paths.

This module does not choose glyph policy.  It builds a shared operation basis
when an authored contour has a real straight extension at one master while
other masters retain the corresponding curved path.  The protected quadratic
is subdivided exactly; the authored curve is fitted with the resulting capacity.
"""

from __future__ import annotations

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
