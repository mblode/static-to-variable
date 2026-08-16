"""Reference-master-preserving cubic to TrueType quadratic conversion.

Variable TrueType compilation normally converts every cubic master as one
group.  Adding an independently drawn master can therefore change the chosen
quadratic segmentation and rounding of an otherwise untouched default master.
This module makes the already-shipped TrueType default the authority instead:

* source UFOs are converted together with the normal cu2qu error bound;
* only provenance-marked authored glyphs are reconciled;
* the reference ``glyf`` outline and advance remain exact at the default;
* other masters are fitted to compatible quadratic topology; and
* extra non-reference segments are represented by zero-length default-master
  prefixes, so no rounded re-approximation can move the protected outline.

The zero-length prefixes are a compatibility device, not visible geometry.
They are used only when an authored master genuinely needs more quadratic
segments than the protected reference.  The compiled variation can still use
those points away from the default location.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pathops
from fontTools.cu2qu.ufo import CURVE_TYPE_LIB_KEY, fonts_to_quadratic
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.reverseContourPen import ReverseContourPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

from variable_gen.authorship import OPTICAL_AUTHORSHIP_KEY
from variable_gen.common import PipelineError

Point = tuple[float, float]
Operation = tuple[str, tuple[Point | None, ...]]


@dataclass(frozen=True)
class QuadraticReferenceReport:
    glyphs: int
    converted_glyphs: int
    exact_default_glyphs: int
    expanded_operations: int
    maximum_segments: int


def _recording(glyph) -> RecordingPen:
    pen = RecordingPen()
    glyph.draw(pen)
    return pen


def _reverse_recording(glyph) -> RecordingPen:
    pen = RecordingPen()
    reverse = ReverseContourPen(pen)
    glyph.draw(reverse)
    return pen


def _contours(recording: RecordingPen, glyph_name: str) -> list[list[Operation]]:
    result: list[list[Operation]] = []
    contour: list[Operation] = []
    for operation, points in recording.value:
        if operation == "addComponent":
            raise PipelineError(
                f"{glyph_name}: quadratic reference requires decomposed authored glyphs"
            )
        if operation == "moveTo":
            if contour:
                raise PipelineError(f"{glyph_name}: nested moveTo in authored outline")
            contour = [(operation, tuple(points))]
            continue
        if not contour:
            if operation in {"closePath", "endPath"}:
                raise PipelineError(f"{glyph_name}: contour closes before moveTo")
            if operation == "qCurveTo" and points and points[-1] is None:
                raise PipelineError(
                    f"{glyph_name}: all-off-curve contours need an explicit start point"
                )
            raise PipelineError(f"{glyph_name}: outline operation before moveTo")
        contour.append((operation, tuple(points)))
        if operation == "endPath":
            raise PipelineError(f"{glyph_name}: quadratic reference requires closed contours")
        if operation == "closePath":
            result.append(contour)
            contour = []
    if contour:
        raise PipelineError(f"{glyph_name}: unterminated authored contour")
    return result


def _draw_contours(glyph, contours: list[list[Operation]]) -> None:
    glyph.clearContours()
    pen = glyph.getPen()
    for contour in contours:
        for operation, points in contour:
            if operation == "moveTo":
                pen.moveTo(points[0])
            elif operation == "lineTo":
                pen.lineTo(points[0])
            elif operation == "qCurveTo":
                pen.qCurveTo(*points)
            elif operation == "closePath":
                pen.closePath()
            elif operation == "endPath":
                pen.endPath()
            else:
                raise AssertionError(operation)


def _filled_path(recording: RecordingPen) -> pathops.Path:
    path = pathops.Path()
    recording.replay(path.getPen())
    path.simplify()
    return path


def _same_filled_path(left: RecordingPen, right: RecordingPen) -> bool:
    left_path = _filled_path(left)
    right_path = _filled_path(right)
    difference = pathops.op(left_path, right_path, pathops.PathOp.XOR)
    return difference.area == 0


def _reference_font(path: Path, location: dict[str, float]) -> TTFont:
    font = TTFont(str(path), recalcTimestamp=False)
    if "glyf" not in font:
        raise PipelineError(f"quadratic reference must contain glyf: {path}")
    if "fvar" not in font:
        if location:
            raise PipelineError(f"static quadratic reference does not accept a location: {path}")
        return font
    axes = {axis.axisTag: axis for axis in font["fvar"].axes}
    unknown = sorted(set(location) - set(axes))
    if unknown:
        raise PipelineError(f"quadratic reference has no axis tag(s): {', '.join(unknown)}")
    resolved = {tag: axis.defaultValue for tag, axis in axes.items()}
    resolved.update(location)
    return instantiateVariableFont(
        font,
        resolved,
        inplace=False,
        optimize=True,
        updateFontNames=False,
    )


def _complex(point: Point) -> complex:
    return complex(point[0], point[1])


def _point(value: complex) -> Point:
    return (value.real, value.imag)


def _require_point(value: Point | None, glyph_name: str, context: str) -> Point:
    if value is None:
        raise PipelineError(f"{glyph_name}: {context} needs an explicit point")
    return value


def _line_intersection(a: complex, b: complex, c: complex, d: complex) -> complex | None:
    ab = b - a
    cd = d - c
    denominator = (ab * 1j * cd.conjugate()).real
    if abs(denominator) < 1e-15:
        if b == c and (a == b or c == d):
            return b
        return None
    numerator = (ab * 1j * (a - c).conjugate()).real
    return c + cd * (numerator / denominator)


def _inside_error(p0: complex, p1: complex, p2: complex, p3: complex, tolerance: float) -> bool:
    if abs(p2) <= tolerance and abs(p1) <= tolerance:
        return True
    midpoint = (p0 + 3 * (p1 + p2) + p3) * 0.125
    if abs(midpoint) > tolerance:
        return False
    derivative = (p3 + p2 - p1 - p0) * 0.125
    return _inside_error(
        p0,
        (p0 + p1) * 0.5,
        midpoint - derivative,
        midpoint,
        tolerance,
    ) and _inside_error(
        midpoint,
        midpoint + derivative,
        (p2 + p3) * 0.5,
        p3,
        tolerance,
    )


def _split_cubic(curve: tuple[complex, complex, complex, complex], t: float):
    p0, p1, p2, p3 = curve
    p01 = p0 + (p1 - p0) * t
    p12 = p1 + (p2 - p1) * t
    p23 = p2 + (p3 - p2) * t
    p012 = p01 + (p12 - p01) * t
    p123 = p12 + (p23 - p12) * t
    point = p012 + (p123 - p012) * t
    return (p0, p01, p012, point), (point, p123, p23, p3)


def _uniform_cubic_parts(
    curve: tuple[complex, complex, complex, complex], count: int
) -> list[tuple[complex, complex, complex, complex]]:
    parts = []
    remaining = curve
    for index in range(count - 1):
        local_t = 1.0 / (count - index)
        left, remaining = _split_cubic(remaining, local_t)
        parts.append(left)
    parts.append(remaining)
    return parts


def _approx_control(t: float, p0: complex, p1: complex, p2: complex, p3: complex) -> complex:
    first = p0 + (p1 - p0) * 1.5
    second = p3 + (p2 - p3) * 1.5
    return first + (second - first) * t


def _fixed_quadratic_spline(
    curve: tuple[Point, Point, Point, Point], count: int, tolerance: float
) -> list[Point] | None:
    """The fontTools cu2qu fit at one explicit quadratic segment count."""

    cubic = cast(
        tuple[complex, complex, complex, complex],
        tuple(_complex(point) for point in curve),
    )
    if count == 1:
        control = _line_intersection(cubic[0], cubic[1], cubic[2], cubic[3])
        if control is None or math.isnan(control.imag):
            return None
        c1 = cubic[0] + (control - cubic[0]) * (2 / 3)
        c2 = cubic[3] + (control - cubic[3]) * (2 / 3)
        if not _inside_error(0j, c1 - cubic[1], c2 - cubic[2], 0j, tolerance):
            return None
        return [_point(cubic[0]), _point(control), _point(cubic[3])]

    parts = _uniform_cubic_parts(cubic, count)
    next_cubic = parts[0]
    next_control = _approx_control(0, *next_cubic)
    endpoint = cubic[0]
    prior_delta = 0j
    spline = [cubic[0], next_control]
    for index in range(1, count + 1):
        c0, c1, c2, c3 = next_cubic
        start = endpoint
        control = next_control
        if index < count:
            next_cubic = parts[index]
            next_control = _approx_control(index / (count - 1), *next_cubic)
            spline.append(next_control)
            endpoint = (control + next_control) * 0.5
        else:
            endpoint = c3
        current_delta = endpoint - c3
        if abs(current_delta) > tolerance or not _inside_error(
            prior_delta,
            start + (control - start) * (2 / 3) - c1,
            endpoint + (control - endpoint) * (2 / 3) - c2,
            current_delta,
            tolerance,
        ):
            return None
        prior_delta = current_delta
    spline.append(cubic[3])
    return [_point(point) for point in spline]


def _quadratic_count(points: tuple[Point | None, ...], glyph_name: str) -> int:
    if not points or points[-1] is None:
        raise PipelineError(f"{glyph_name}: reference qCurveTo needs an explicit endpoint")
    return len(points) - 1


def _fit_all(
    curves: list[tuple[Point, Point, Point, Point]],
    initial_count: int,
    tolerance: float,
    glyph_name: str,
) -> tuple[int, list[list[Point]]]:
    for count in range(initial_count, 101):
        fitted = [_fixed_quadratic_spline(curve, count, tolerance) for curve in curves]
        if all(spline is not None for spline in fitted):
            return count, [spline for spline in fitted if spline is not None]
    raise PipelineError(f"{glyph_name}: authored cubic exceeds {tolerance:g}-unit cu2qu bound")


def _partition_spline(spline: list[Point], prefix_count: int) -> list[Operation]:
    controls = spline[1:-1]
    endpoint = spline[-1]
    result: list[Operation] = []
    for index in range(prefix_count):
        next_endpoint = (
            (controls[index][0] + controls[index + 1][0]) / 2,
            (controls[index][1] + controls[index + 1][1]) / 2,
        )
        result.append(("qCurveTo", (controls[index], next_endpoint)))
    result.append(("qCurveTo", (*controls[prefix_count:], endpoint)))
    return result


def _pad_reference_operation(
    start: Point,
    operation: Operation,
    prefix_count: int,
) -> list[Operation]:
    return [
        *(("qCurveTo", (start, start)) for _ in range(prefix_count)),
        operation,
    ]


def _topology(recording: RecordingPen, glyph_name: str) -> tuple[tuple[tuple[str, int], ...], ...]:
    """Return a coordinate-free, contour-stable source topology signature."""

    return tuple(
        tuple((operation, len(points)) for operation, points in contour)
        for contour in _contours(recording, glyph_name)
    )


def _validate_topology_contract(
    fonts, contract, *, expected_master_names: tuple[str, ...], source_master_names: tuple[str, ...]
) -> None:
    """Fail before cu2qu if an explicitly authored source topology drifted.

    This intentionally validates only operation kinds and arities. It never
    copies coordinates, rewrites start points, or changes provenance scope.
    Every configured source must carry the glyph's existing authorship marker;
    normal reconciliation remains the union of all provenance-marked glyphs.
    """

    if not contract:
        return
    if not expected_master_names:
        raise PipelineError("topology contract requires expected master names")
    if source_master_names != expected_master_names:
        raise PipelineError(
            "topology contract master inputs differ from the configured authored master set"
        )
    if len(source_master_names) != len(fonts):
        raise PipelineError("topology contract source master names do not bind every input")
    for name, expected in sorted(contract.items()):
        for index, font in enumerate(fonts):
            if name not in font:
                raise PipelineError(
                    f"{name}: topology contract glyph is missing from master {index}"
                )
            glyph = font[name]
            if not glyph.lib.get(OPTICAL_AUTHORSHIP_KEY):
                raise PipelineError(
                    f"{name}: topology contract requires authored provenance in master {index}"
                )
            actual = _topology(_recording(glyph), name)
            if actual != expected:
                raise PipelineError(
                    f"{name}: topology contract mismatch in master {index}; "
                    "source contours must be explicitly reauthored"
                )


def _reconcile_glyph(
    name: str,
    fonts,
    default_index: int,
    originals: list[RecordingPen],
    reference_glyph,
    max_error: float,
) -> tuple[bool, int, int]:
    quadratic = [_recording(font[name]) for font in fonts]
    reference = _recording(reference_glyph)
    reference_width = reference_glyph.width
    default_glyph = fonts[default_index][name]
    if _same_filled_path(quadratic[default_index], reference):
        default_glyph.width = reference_width
        return False, 0, 0

    source_contours = [_contours(recording, name) for recording in originals]
    quadratic_contours = [_contours(recording, name) for recording in quadratic]
    reference_contours = _contours(reference, name)
    contour_counts = {len(contours) for contours in quadratic_contours}
    contour_counts.add(len(reference_contours))
    if len(contour_counts) != 1:
        raise PipelineError(f"{name}: reference contour count is incompatible")

    reconciled: list[list[list[Operation]]] = [[[] for _ in reference_contours] for _ in fonts]
    protected_indices = {
        index
        for index, recording in enumerate(originals)
        if recording.value == originals[default_index].value
        and fonts[index][name].width == default_glyph.width
    }
    expanded = 0
    maximum_segments = 0
    for contour_index, reference_contour in enumerate(reference_contours):
        quadratic_ops = [contours[contour_index] for contours in quadratic_contours]
        source_ops = [contours[contour_index] for contours in source_contours]
        if not all(len(ops) == len(reference_contour) for ops in (*quadratic_ops, *source_ops)):
            raise PipelineError(
                f"{name}: reference operation count is incompatible in contour {contour_index}"
            )
        current_points = [_require_point(ops[0][1][0], name, "source moveTo") for ops in source_ops]
        reference_current = _require_point(reference_contour[0][1][0], name, "reference moveTo")
        for font_index in range(len(fonts)):
            reconciled[font_index][contour_index].append(
                reference_contour[0]
                if font_index in protected_indices
                else quadratic_ops[font_index][0]
            )
        for operation_index in range(1, len(reference_contour)):
            reference_operation = reference_contour[operation_index]
            kind = reference_operation[0]
            quadratic_kinds = {ops[operation_index][0] for ops in quadratic_ops}
            source_kinds = {ops[operation_index][0] for ops in source_ops}
            expected_source = "curveTo" if kind == "qCurveTo" else kind
            if quadratic_kinds != {kind} or source_kinds != {expected_source}:
                raise PipelineError(
                    f"{name}: reference operation {contour_index}:{operation_index} is incompatible"
                )
            if kind != "qCurveTo":
                for font_index in range(len(fonts)):
                    reconciled[font_index][contour_index].append(
                        reference_operation
                        if font_index in protected_indices
                        else quadratic_ops[font_index][operation_index]
                    )
                    points = source_ops[font_index][operation_index][1]
                    if points:
                        current_points[font_index] = _require_point(
                            points[-1], name, "source operation endpoint"
                        )
                if reference_operation[1]:
                    reference_current = _require_point(
                        reference_operation[1][-1], name, "reference operation endpoint"
                    )
                continue

            reference_count = _quadratic_count(reference_operation[1], name)
            curves = []
            for font_index, ops in enumerate(source_ops):
                control_points = ops[operation_index][1]
                if len(control_points) != 3 or any(point is None for point in control_points):
                    raise PipelineError(
                        f"{name}: authored source operation "
                        f"{contour_index}:{operation_index} is not cubic"
                    )
                cubic_points = cast(tuple[Point, Point, Point], control_points)
                curves.append((current_points[font_index], *cubic_points))
            segment_count, splines = _fit_all(
                curves,
                # The protected reference is the topology authority. Start at
                # its segment count and expand only when the authored cubics
                # cannot satisfy the configured geometric error bound. The
                # preliminary independent cu2qu result is deliberately not a
                # lower bound: it may choose a more conservative segmentation
                # even when the complete compatible source set fits the
                # protected program exactly.
                reference_count,
                max_error,
                name,
            )
            prefix_count = segment_count - reference_count
            expanded += prefix_count
            maximum_segments = max(maximum_segments, segment_count)
            for font_index, spline in enumerate(splines):
                if font_index in protected_indices:
                    reconciled[font_index][contour_index].extend(
                        _pad_reference_operation(
                            reference_current, reference_operation, prefix_count
                        )
                    )
                else:
                    reconciled[font_index][contour_index].extend(
                        _partition_spline(spline, prefix_count)
                    )
                current_points[font_index] = curves[font_index][-1]
            reference_current = _require_point(
                reference_operation[1][-1], name, "reference qCurveTo endpoint"
            )

    for font_index, font in enumerate(fonts):
        _draw_contours(font[name], reconciled[font_index])
        if font_index in protected_indices:
            font[name].width = reference_width
    if not _same_filled_path(_recording(default_glyph), reference):
        raise PipelineError(f"{name}: protected reference geometry moved during reconciliation")
    return True, expanded, maximum_segments


def preserve_quadratic_reference(
    fonts,
    *,
    default_index: int,
    reference_path: Path,
    reference_location: dict[str, float],
    max_error: float = 1.0,
    topology_contract: dict[str, tuple[tuple[tuple[str, int], ...], ...]] | None = None,
    topology_contract_master_names: tuple[str, ...] = (),
    source_master_names: tuple[str, ...] = (),
) -> QuadraticReferenceReport:
    """Convert ``fonts`` in place while preserving a protected TT default.

    The scope is the union of glyphs carrying the engine's content-addressed
    optical-authorship marker in any source.  This avoids mutating unrelated
    donor-derived glyphs and makes the behaviour follow provenance rather than
    a font-specific glyph allow-list.
    """

    if not 0 <= default_index < len(fonts):
        raise ValueError("default_index is outside the source font list")
    if max_error <= 0:
        raise ValueError("max_error must be positive")
    _validate_topology_contract(
        fonts,
        topology_contract,
        expected_master_names=topology_contract_master_names,
        source_master_names=source_master_names,
    )
    reference = _reference_font(reference_path, reference_location)
    reference_upem = reference["head"].unitsPerEm
    source_upems = {font.info.unitsPerEm for font in fonts if font.info.unitsPerEm is not None}
    if len(source_upems) != 1 or reference_upem not in source_upems:
        values = ", ".join(str(value) for value in sorted(source_upems)) or "unset"
        raise PipelineError(
            "quadratic reference unitsPerEm must match every source: "
            f"reference={reference_upem}, sources={values}"
        )
    authored = sorted(
        {
            name
            for font in fonts
            for name in font.keys()
            if font[name].lib.get(OPTICAL_AUTHORSHIP_KEY)
        }
    )
    originals = {name: [_reverse_recording(font[name]) for font in fonts] for name in authored}
    reference_glyphs = reference.getGlyphSet()
    for name in authored:
        if any(name not in font for font in fonts) or name not in reference_glyphs:
            raise PipelineError(f"{name}: quadratic reference glyph is missing")
        for recording in originals[name]:
            _contours(recording, name)
        _contours(_recording(reference_glyphs[name]), name)
    fonts_to_quadratic(
        fonts,
        max_err=max_error,
        reverse_direction=True,
        remember_curve_type=False,
    )

    converted = exact = expanded = maximum_segments = 0
    for name in authored:
        changed, glyph_expanded, glyph_maximum = _reconcile_glyph(
            name,
            fonts,
            default_index,
            originals[name],
            reference_glyphs[name],
            max_error,
        )
        if changed:
            converted += 1
        else:
            exact += 1
        expanded += glyph_expanded
        maximum_segments = max(maximum_segments, glyph_maximum)

    for font in fonts:
        font.lib[CURVE_TYPE_LIB_KEY] = "quadratic"
    return QuadraticReferenceReport(
        glyphs=len(authored),
        converted_glyphs=converted,
        exact_default_glyphs=exact,
        expanded_operations=expanded,
        maximum_segments=maximum_segments,
    )
