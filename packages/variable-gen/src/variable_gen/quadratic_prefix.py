"""Subdivide extra Display spans along the protected curve.

Default piecewise padding used to park extra Text topology as stationary
``(start, start)`` Display prefixes. Those points interpolate toward the shared
start and form mid-opsz lobes. Extra spans instead follow the protected quadratic
so compiled Display stays exact native on a 16× or 32× carrier.
"""

from __future__ import annotations

from dataclasses import replace

from fontTools.pens.recordingPen import RecordingPen

import variable_gen.quadratic_reference as qr
from variable_gen.authorship import OPTICAL_AUTHORSHIP_KEY
from variable_gen.common import PipelineError
from variable_gen.quadratic_semantic_partition import subdivide_quadratic_chain

Point = tuple[float, float]
Operation = tuple[str, tuple[Point, ...]]

_native_pad = qr._pad_reference_operation
_native_preserve = qr.preserve_quadratic_reference


def _closed(start: Point, operations: list[Operation]) -> RecordingPen:
    recording = RecordingPen()
    recording.moveTo(start)
    for kind, points in operations:
        getattr(recording, kind)(*points)
    recording.closePath()
    return recording


def _lerp(left: Point, right: Point, parameter: float) -> Point:
    return (
        left[0] * (1 - parameter) + right[0] * parameter,
        left[1] * (1 - parameter) + right[1] * parameter,
    )


def _subdivided_prefix(start: Point, operation: Operation, extra: int) -> list[Operation]:
    native = len(operation[1]) - 1
    if native == 1:
        steps = 1
        while steps < extra + 1:
            steps *= 2
        spline = [start, *subdivide_quadratic_chain(start, operation, steps)]
        operations = qr._partition_spline(spline, extra)[:-1]
        parameter = extra / steps
        control = qr._require_point(operation[1][0], "reference", "qCurveTo control")
        endpoint = qr._require_point(operation[1][-1], "reference", "qCurveTo endpoint")
        right_control = _lerp(control, endpoint, parameter)
        operations.append(("qCurveTo", (right_control, endpoint)))
    else:
        steps = 1
        while native * steps < native + extra:
            steps += 1
        operations = qr._partition_spline(
            [start, *subdivide_quadratic_chain(start, operation, steps)], extra
        )
    if ("qCurveTo", (start, start)) in operations:
        raise AssertionError("extra Display spans must not collapse to the start")
    if not qr._same_filled_path(_closed(start, [operation]), _closed(start, operations)):
        raise AssertionError("prefix subdivision moved protected Display geometry")
    return operations


def pad_reference_operation(
    start: Point,
    operation: Operation,
    prefix_count: int,
    placement: str = "prefix",
) -> list[Operation]:
    if placement != "prefix":
        return _native_pad(start, operation, prefix_count, placement)
    if prefix_count == 0:
        return [operation]
    return _subdivided_prefix(start, operation, prefix_count)


def _fractional(contours: list[list[Operation]]) -> bool:
    return any(
        value != round(value)
        for contour in contours
        for _, points in contour
        for point in points
        if point is not None
        for value in point
    )


def _carrier_scale(
    name: str, contours: list[list[list[Operation]]], protected: frozenset[int]
) -> int | None:
    try:
        return qr._grouped_carrier_scale(name, contours, protected, qr.SEMANTIC_PARTITION)
    except PipelineError:
        return None


def _install_prefix_carriers(fonts, default_index: int, protected_locations) -> tuple[str, ...]:
    protected = frozenset(
        protected_locations if protected_locations is not None else {default_index}
    )
    names = sorted(
        {
            name
            for font in fonts
            for name in font.keys()
            if font[name].lib.get(OPTICAL_AUTHORSHIP_KEY)
        }
    )
    carriers: set[str] = set()
    for name in names:
        if any(glyph.startswith(f"{name}.stv-semantic") for font in fonts for glyph in font.keys()):
            continue
        contours = [qr._contours(qr._recording(font[name]), name) for font in fonts]
        if not any(_fractional(contours[index]) for index in protected if index < len(contours)):
            continue
        scale = _carrier_scale(name, contours, protected)
        if scale is None:
            continue
        authorship = next(
            font[name].lib[OPTICAL_AUTHORSHIP_KEY]
            for font in fonts
            if name in font and font[name].lib.get(OPTICAL_AUTHORSHIP_KEY)
        )
        for index, font in enumerate(fonts):
            carriers.add(
                qr._install_continuous_chain_carrier(
                    font,
                    name,
                    contours[index],
                    protected=index in protected,
                    authorship=authorship,
                    scale=scale,
                )
            )
    return tuple(sorted(carriers))


def preserve_quadratic_reference(fonts, *, default_index: int, **kwargs):
    report = _native_preserve(fonts, default_index=default_index, **kwargs)
    if report.carrier_glyphs or report.expanded_operations == 0:
        return report
    carriers = _install_prefix_carriers(fonts, default_index, kwargs.get("protected_locations"))
    return replace(report, carrier_glyphs=carriers) if carriers else report


def install() -> None:
    qr._pad_reference_operation = pad_reference_operation
    qr.preserve_quadratic_reference = preserve_quadratic_reference


install()
