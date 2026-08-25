"""Read-only, scale-aware kink measurements for compatible cubic outlines.

The existing reconstruction gate compares tangent angles.  Angles alone do not
describe visibility: the same angle is much more conspicuous across long
handles than short ones.  This module instead measures the on-curve node's
perpendicular distance from the chord between its adjacent controls, in font
units.  This is the geometric ``deviation`` used by
``fontTools.varLib.interpolatable``'s kink detector.

Only cubic-to-cubic joins that are smooth and forward-facing in both endpoint
masters are candidates.  Line joins, open-contour endpoints, and endpoint
corners (including intentional 180-degree reversals) are excluded deliberately;
they may be authored discontinuities rather than interpolation defects.  A new
corner or reversal at the sampled location is blocking even when its
perpendicular distance is zero.  Otherwise the threshold applies to depth
emerging beyond the linearly interpolated endpoint-depth baseline, so an
inherited slight bend is not mislabeled as a newly kinky interpolation and an
interior peak is not hidden by the deeper endpoint.  Degenerate cubic joins are returned
as blocking defects, while malformed, incompatible, or non-finite input raises
``ValueError`` so an audit cannot silently pass it.

No acceptance threshold is universal.  Callers must provide one in font units.
Glide's proposed 0.9-unit value remains provisional until calibrated against
rendered evidence.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from typing import Literal, TypeAlias

Point: TypeAlias = tuple[float, float]
PenCommand: TypeAlias = tuple[str, Sequence[Point]]
Contour: TypeAlias = Sequence[PenCommand]
Outline: TypeAlias = Sequence[Contour]
AxisCoordinates: TypeAlias = tuple[tuple[str, float], ...]
KinkReason: TypeAlias = Literal[
    "depth_exceeded",
    "degenerate_endpoint_join",
    "degenerate_interpolated_join",
    "interpolated_corner",
]

_GEOMETRY_EPSILON = 1e-12
# Same endpoint-smoothness policy as fontTools.varLib.interpolatable: roughly
# sin(6 degrees).  It is a classification tolerance, not a defect threshold.
_SMOOTH_SINE_TOLERANCE = 0.1


@dataclass(frozen=True)
class InterpolationKinkDefect:
    """One measured or unmeasurably degenerate compatible cubic join.

    ``node_index`` counts on-curve nodes from the contour's ``moveTo`` node.
    ``depth`` is the sampled node-to-control-chord distance. ``endpoint_depths``
    contains the left and right master distances, ``baseline_depth`` linearly
    interpolates those distances at the sample, and ``depth_delta`` is the
    sampled distance's non-negative excess over that baseline.  A distance is
    ``None`` when the corresponding join cannot define a chord.  Returned
    defects have ``depth_delta`` above ``threshold`` or are blocking for the
    explicit ``reason``.
    """

    glyph_name: str
    contour_index: int
    node_index: int
    location: AxisCoordinates
    interpolation_t: float
    depth: float | None
    endpoint_depths: tuple[float | None, float | None] | None
    baseline_depth: float | None
    depth_delta: float | None
    threshold: float
    reason: KinkReason

    def as_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-ready representation."""
        return {
            "glyph": self.glyph_name,
            "contour": self.contour_index,
            "node": self.node_index,
            "location": dict(self.location),
            "t": self.interpolation_t,
            "depth": self.depth,
            "endpointDepths": (
                list(self.endpoint_depths) if self.endpoint_depths is not None else None
            ),
            "baselineDepth": self.baseline_depth,
            "depthDelta": self.depth_delta,
            "threshold": self.threshold,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class _CubicJoin:
    node_index: int
    previous_control: Point
    node: Point
    next_control: Point


def _require_finite_point(point: Point, context: str) -> None:
    if len(point) != 2:
        raise ValueError(f"{context} must contain two finite coordinates")
    for value in point:
        if not isinstance(value, Real) or isinstance(value, bool):
            raise ValueError(f"{context} must contain two finite coordinates")
        try:
            finite = math.isfinite(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"{context} must contain two finite coordinates") from error
        if not finite:
            raise ValueError(f"{context} must contain two finite coordinates")


def perpendicular_kink_depth(
    previous_control: Point,
    node: Point,
    next_control: Point,
) -> float:
    """Return the node-to-control-chord distance in font units.

    Raises ``ValueError`` when coordinates are non-finite or the adjacent
    controls coincide, because no finite tangent chord can certify that join.
    """
    _require_finite_point(previous_control, "previous control")
    _require_finite_point(node, "node")
    _require_finite_point(next_control, "next control")
    chord_x = next_control[0] - previous_control[0]
    chord_y = next_control[1] - previous_control[1]
    chord_length = math.hypot(chord_x, chord_y)
    if not all(math.isfinite(value) for value in (chord_x, chord_y, chord_length)):
        raise ValueError("control chord arithmetic produced a non-finite value")
    if chord_length <= _GEOMETRY_EPSILON:
        raise ValueError("adjacent controls do not define a finite tangent chord")
    node_x = node[0] - previous_control[0]
    node_y = node[1] - previous_control[1]
    if not all(math.isfinite(value) for value in (node_x, node_y)):
        raise ValueError("node offset arithmetic produced a non-finite value")
    depth = abs(node_x * (chord_y / chord_length) - node_y * (chord_x / chord_length))
    if not math.isfinite(depth):
        raise ValueError("kink-depth arithmetic produced a non-finite value")
    return depth


def _outline_signature(outline: Outline) -> tuple[tuple[tuple[str, int], ...], ...]:
    return tuple(
        tuple((operation, len(points)) for operation, points in contour) for contour in outline
    )


def _validate_outline(outline: Outline, label: str) -> None:
    for contour_index, contour in enumerate(outline):
        if len(contour) < 2:
            raise ValueError(f"{label} contour {contour_index} is incomplete")
        for command_index, (operation, points) in enumerate(contour):
            context = f"{label} contour {contour_index} command {command_index}"
            if command_index == 0:
                if operation != "moveTo" or len(points) != 1:
                    raise ValueError(f"{context} must be one moveTo point")
            elif command_index == len(contour) - 1:
                if operation not in {"closePath", "endPath"} or points:
                    raise ValueError(f"{context} must be an empty contour terminator")
            elif operation == "lineTo":
                if len(points) != 1:
                    raise ValueError(f"{context} lineTo must have one point")
            elif operation == "curveTo":
                if len(points) != 3:
                    raise ValueError(f"{context} curveTo must have three points")
            else:
                raise ValueError(
                    f"{context} uses unsupported {operation!r}; "
                    "kink-depth analysis currently accepts cubic source contours only"
                )
            for point_index, point in enumerate(points):
                _require_finite_point(point, f"{context} point {point_index}")


def _cubic_joins(contour: Contour) -> tuple[_CubicJoin, ...]:
    start = contour[0][1][0]
    draw_commands = contour[1:-1]
    segments: list[tuple[str, Sequence[Point], Point, Point]] = []
    current = start
    for operation, points in draw_commands:
        end = points[-1]
        segments.append((operation, points, current, end))
        current = end

    joins: list[_CubicJoin] = []
    for index, (incoming, outgoing) in enumerate(zip(segments, segments[1:], strict=False)):
        incoming_operation, incoming_points, _incoming_start, node = incoming
        outgoing_operation, outgoing_points, outgoing_start, _outgoing_end = outgoing
        if outgoing_start != node:
            raise ValueError("contour commands do not form a continuous path")
        if incoming_operation == outgoing_operation == "curveTo":
            joins.append(
                _CubicJoin(
                    node_index=index + 1,
                    previous_control=incoming_points[-2],
                    node=node,
                    next_control=outgoing_points[0],
                )
            )

    # A closePath can mean an implicit line.  The start is a cubic join only
    # when the last explicit cubic actually lands back on the moveTo point.
    if (
        contour[-1][0] == "closePath"
        and segments
        and segments[-1][3] == start
        and segments[-1][0] == segments[0][0] == "curveTo"
    ):
        joins.insert(
            0,
            _CubicJoin(
                node_index=0,
                previous_control=segments[-1][1][-2],
                node=start,
                next_control=segments[0][1][0],
            ),
        )
    return tuple(joins)


def _join_state(join: _CubicJoin) -> Literal["smooth", "corner", "degenerate"]:
    incoming = (
        join.node[0] - join.previous_control[0],
        join.node[1] - join.previous_control[1],
    )
    outgoing = (
        join.next_control[0] - join.node[0],
        join.next_control[1] - join.node[1],
    )
    if not all(math.isfinite(value) for value in (*incoming, *outgoing)):
        raise ValueError("join-vector arithmetic produced a non-finite value")
    incoming_length = math.hypot(*incoming)
    outgoing_length = math.hypot(*outgoing)
    if not all(math.isfinite(value) for value in (incoming_length, outgoing_length)):
        raise ValueError("join-length arithmetic produced a non-finite value")
    if incoming_length <= _GEOMETRY_EPSILON or outgoing_length <= _GEOMETRY_EPSILON:
        return "degenerate"
    incoming_unit = (incoming[0] / incoming_length, incoming[1] / incoming_length)
    outgoing_unit = (outgoing[0] / outgoing_length, outgoing[1] / outgoing_length)
    sine = incoming_unit[0] * outgoing_unit[1] - incoming_unit[1] * outgoing_unit[0]
    dot = incoming_unit[0] * outgoing_unit[0] + incoming_unit[1] * outgoing_unit[1]
    if abs(sine) <= _SMOOTH_SINE_TOLERANCE and dot >= 0.0:
        return "smooth"
    return "corner"


def _endpoint_depth(join: _CubicJoin, state: str) -> float | None:
    if state == "degenerate":
        return None
    try:
        return perpendicular_kink_depth(
            join.previous_control,
            join.node,
            join.next_control,
        )
    except ValueError:
        return None


def _interpolate_point(left: Point, right: Point, t: float) -> Point:
    point = (
        left[0] + (right[0] - left[0]) * t,
        left[1] + (right[1] - left[1]) * t,
    )
    _require_finite_point(point, "interpolated point")
    return point


def _interpolate_join(left: _CubicJoin, right: _CubicJoin, t: float) -> _CubicJoin:
    return _CubicJoin(
        node_index=left.node_index,
        previous_control=_interpolate_point(left.previous_control, right.previous_control, t),
        node=_interpolate_point(left.node, right.node, t),
        next_control=_interpolate_point(left.next_control, right.next_control, t),
    )


def _axis_coordinates(
    left: Mapping[str, float] | Sequence[tuple[str, float]] | None,
    right: Mapping[str, float] | Sequence[tuple[str, float]] | None,
    t: float,
) -> AxisCoordinates:
    if left is None and right is None:
        return ()
    if left is None or right is None:
        raise ValueError("both endpoint locations are required when either is provided")
    left_items = tuple(left.items() if isinstance(left, Mapping) else left)
    right_items = tuple(right.items() if isinstance(right, Mapping) else right)
    if len(dict(left_items)) != len(left_items) or len(dict(right_items)) != len(right_items):
        raise ValueError("axis locations must not contain duplicate tags")
    left_values: dict[str, float] = {}
    right_values: dict[str, float] = {}
    for label, items, values in (
        ("left", left_items, left_values),
        ("right", right_items, right_values),
    ):
        for tag, value in items:
            if not isinstance(tag, str) or not tag:
                raise ValueError(f"{label} axis location tags must be non-empty strings")
            try:
                coordinate = float(value)
            except (TypeError, ValueError, OverflowError) as error:
                raise ValueError(
                    f"{label} axis location coordinates must be finite numbers"
                ) from error
            if not math.isfinite(coordinate):
                raise ValueError(f"{label} axis location coordinates must be finite numbers")
            values[tag] = coordinate
    if left_values.keys() != right_values.keys():
        raise ValueError("endpoint locations must contain the same axis tags")
    location = tuple(
        (tag, left_values[tag] + (right_values[tag] - left_values[tag]) * t)
        for tag in sorted(left_values)
    )
    if not all(math.isfinite(value) for _tag, value in location):
        raise ValueError("interpolated axis location contains a non-finite coordinate")
    return location


def interpolation_kink_defects(
    left: Outline,
    right: Outline,
    *,
    glyph_name: str,
    threshold: float,
    t: float = 0.5,
    left_location: Mapping[str, float] | Sequence[tuple[str, float]] | None = None,
    right_location: Mapping[str, float] | Sequence[tuple[str, float]] | None = None,
) -> tuple[InterpolationKinkDefect, ...]:
    """Measure newly interpolated cubic kinks between compatible masters.

    The pair may represent one row of a multi-axis grid; pass complete endpoint
    locations to retain all axis coordinates in each finding.  Call this once
    for each adjacent pair and desired ``t``.  This function does not certify
    unsampled portions of an axis interval and performs no outline mutation.
    """
    try:
        t = float(t)
        threshold = float(threshold)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("interpolation t and threshold must be finite numbers") from error
    if not math.isfinite(t) or not 0.0 < t < 1.0:
        raise ValueError("interpolation t must be finite and strictly between 0 and 1")
    if not math.isfinite(threshold) or threshold < 0.0:
        raise ValueError("kink threshold must be a finite, non-negative font-unit value")
    if not isinstance(glyph_name, str) or not glyph_name:
        raise ValueError("glyph name is required for defect context")
    _validate_outline(left, "left")
    _validate_outline(right, "right")
    if _outline_signature(left) != _outline_signature(right):
        raise ValueError("endpoint outlines are not interpolation-compatible")
    location = _axis_coordinates(left_location, right_location, t)

    defects: list[InterpolationKinkDefect] = []
    for contour_index, (left_contour, right_contour) in enumerate(zip(left, right, strict=True)):
        left_joins = _cubic_joins(left_contour)
        right_joins = _cubic_joins(right_contour)
        if tuple(join.node_index for join in left_joins) != tuple(
            join.node_index for join in right_joins
        ):
            raise ValueError("endpoint outlines do not expose corresponding cubic joins")
        for left_join, right_join in zip(left_joins, right_joins, strict=True):
            left_state = _join_state(left_join)
            right_state = _join_state(right_join)
            if "degenerate" in {left_state, right_state}:
                endpoint_depths = (
                    _endpoint_depth(left_join, left_state),
                    _endpoint_depth(right_join, right_state),
                )
                defects.append(
                    InterpolationKinkDefect(
                        glyph_name=glyph_name,
                        contour_index=contour_index,
                        node_index=left_join.node_index,
                        location=location,
                        interpolation_t=t,
                        depth=None,
                        endpoint_depths=endpoint_depths,
                        baseline_depth=None,
                        depth_delta=None,
                        threshold=threshold,
                        reason="degenerate_endpoint_join",
                    )
                )
                continue
            if left_state != "smooth" or right_state != "smooth":
                continue

            endpoint_depths = (
                perpendicular_kink_depth(
                    left_join.previous_control,
                    left_join.node,
                    left_join.next_control,
                ),
                perpendicular_kink_depth(
                    right_join.previous_control,
                    right_join.node,
                    right_join.next_control,
                ),
            )
            baseline_depth = endpoint_depths[0] + (endpoint_depths[1] - endpoint_depths[0]) * t
            if not math.isfinite(baseline_depth):
                raise ValueError("endpoint-depth interpolation produced a non-finite value")
            interpolated = _interpolate_join(left_join, right_join, t)
            interpolated_state = _join_state(interpolated)
            if interpolated_state == "degenerate":
                defects.append(
                    InterpolationKinkDefect(
                        glyph_name=glyph_name,
                        contour_index=contour_index,
                        node_index=left_join.node_index,
                        location=location,
                        interpolation_t=t,
                        depth=None,
                        endpoint_depths=endpoint_depths,
                        baseline_depth=baseline_depth,
                        depth_delta=None,
                        threshold=threshold,
                        reason="degenerate_interpolated_join",
                    )
                )
                continue
            try:
                depth = perpendicular_kink_depth(
                    interpolated.previous_control,
                    interpolated.node,
                    interpolated.next_control,
                )
            except ValueError:
                depth = None
            depth_delta = None if depth is None else max(0.0, depth - baseline_depth)
            if interpolated_state == "corner":
                defects.append(
                    InterpolationKinkDefect(
                        glyph_name=glyph_name,
                        contour_index=contour_index,
                        node_index=left_join.node_index,
                        location=location,
                        interpolation_t=t,
                        depth=depth,
                        endpoint_depths=endpoint_depths,
                        baseline_depth=baseline_depth,
                        depth_delta=depth_delta,
                        threshold=threshold,
                        reason="interpolated_corner",
                    )
                )
            elif depth_delta is not None and depth_delta > threshold:
                defects.append(
                    InterpolationKinkDefect(
                        glyph_name=glyph_name,
                        contour_index=contour_index,
                        node_index=left_join.node_index,
                        location=location,
                        interpolation_t=t,
                        depth=depth,
                        endpoint_depths=endpoint_depths,
                        baseline_depth=baseline_depth,
                        depth_delta=depth_delta,
                        threshold=threshold,
                        reason="depth_exceeded",
                    )
                )
    return tuple(defects)
