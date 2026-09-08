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
from bisect import bisect_left
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
from variable_gen.curve_certificate import certify_curve_distance
from variable_gen.quadratic_semantic_partition import (
    partition_semantic_curve,
    subdivide_quadratic_chain,
)

Point = tuple[float, float]
Operation = tuple[str, tuple[Point | None, ...]]
SourceGroups = tuple[tuple[tuple[int, ...], ...], ...]
SOURCE_GROUPS_KEY = "com.mblode.stv.quadraticSourceGroups"
PADDING_PLACEMENT_KEY = "com.mblode.stv.quadraticPaddingPlacement"
BALANCED_ENDPOINTS = "balanced-endpoints"
REFERENCE_COUNT = "reference-count"
REFERENCE_COUNT_LINES = "reference-count-lines"
NATIVE_IUP_TRANSPORT = "native-iup-transport"
NATIVE_IUP_TRANSPORT_KEY = "com.mblode.stv.nativeIupTransport"
CONTINUOUS_CHAIN = "continuous-chain"
SEMANTIC_PARTITION = "semantic-partition"
SEMANTIC_PARTITION_KEY = "com.mblode.stv.quadraticSemanticPartition"
CONTINUOUS_CHAIN_SUBDIVISIONS = 4
CONTINUOUS_CHAIN_SCALE = 16


def _source_group_metadata(fonts) -> dict[str, SourceGroups]:
    """Read author-supplied groups in the same master order as the UFO sources."""
    names = {name for font in fonts for name in font.keys() if SOURCE_GROUPS_KEY in font[name].lib}
    result = {}
    for name in sorted(names):
        if not any(name in font and font[name].lib.get(OPTICAL_AUTHORSHIP_KEY) for font in fonts):
            raise PipelineError(f"{name}: source group metadata requires authored provenance")
        masters = []
        for index, font in enumerate(fonts):
            if name not in font or SOURCE_GROUPS_KEY not in font[name].lib:
                raise PipelineError(f"{name}: source group metadata is missing in master {index}")
            contours = font[name].lib[SOURCE_GROUPS_KEY]
            if not isinstance(contours, (list, tuple)) or any(
                not isinstance(counts, (list, tuple)) for counts in contours
            ):
                raise PipelineError(f"{name}: source group metadata must contain contour counts")
            masters.append(tuple(tuple(counts) for counts in contours))
        result[name] = tuple(masters)
    return result


def _padding_placement_metadata(fonts, groups: dict[str, SourceGroups]) -> dict[str, str]:
    """Read an explicit, complete opt-in for non-default compatibility placement."""
    names = {
        name for font in fonts for name in font.keys() if PADDING_PLACEMENT_KEY in font[name].lib
    }
    result = {}
    for name in sorted(names):
        if name not in groups:
            raise PipelineError(f"{name}: padding placement requires source group metadata")
        values = []
        for index, font in enumerate(fonts):
            if name not in font or PADDING_PLACEMENT_KEY not in font[name].lib:
                raise PipelineError(
                    f"{name}: padding placement metadata is missing in master {index}"
                )
            values.append(font[name].lib[PADDING_PLACEMENT_KEY])
        if any(not isinstance(value, str) for value in values):
            raise PipelineError(f"{name}: padding placement metadata must be a string")
        if len(set(values)) != 1 or values[0] not in {
            BALANCED_ENDPOINTS,
            REFERENCE_COUNT,
            REFERENCE_COUNT_LINES,
            NATIVE_IUP_TRANSPORT,
            CONTINUOUS_CHAIN,
            SEMANTIC_PARTITION,
        }:
            raise PipelineError(
                f"{name}: padding placement must be a supported consistent mode in every master"
            )
        result[name] = values[0]
    return result


def _semantic_partition_metadata(fonts, placements: dict[str, str]) -> dict[str, dict]:
    """Read a complete, source-bound semantic partition recipe."""
    names = {
        name for font in fonts for name in font.keys() if SEMANTIC_PARTITION_KEY in font[name].lib
    }
    version_one_keys = {
        "schemaVersion",
        "placement",
        "glyph",
        "glyphRowsSha256",
        "defaultSubdivisions",
        "subdivisionOverrides",
        "semanticSlots",
        "straightExtensionWeights",
    }
    version_two_keys = version_one_keys | {"pairedOperations", "protectedMatchAxes"}
    result = {}
    for name in sorted(names):
        values = []
        for index, font in enumerate(fonts):
            if name not in font or SEMANTIC_PARTITION_KEY not in font[name].lib:
                raise PipelineError(
                    f"{name}: semantic partition metadata is missing in master {index}"
                )
            values.append(font[name].lib[SEMANTIC_PARTITION_KEY])
        if any(
            not isinstance(value, dict)
            or frozenset(value) not in {frozenset(version_one_keys), frozenset(version_two_keys)}
            for value in values
        ):
            raise PipelineError(f"{name}: semantic partition metadata has an invalid schema")
        if any(value != values[0] for value in values[1:]):
            raise PipelineError(
                f"{name}: semantic partition metadata must be identical in every master"
            )
        recipe = values[0]
        overrides = recipe["subdivisionOverrides"]
        slots = recipe["semanticSlots"]
        weights = recipe["straightExtensionWeights"]
        version = recipe["schemaVersion"]
        pairs = recipe.get("pairedOperations", [])
        match_axes = recipe.get("protectedMatchAxes", [])
        valid_pairs = (
            isinstance(pairs, (list, tuple))
            and all(
                isinstance(pair, (list, tuple))
                and len(pair) == 2
                and all(type(value) is int and value >= 0 for value in pair)
                and pair[1] == pair[0] + 1
                for pair in pairs
            )
            and len({value for pair in pairs for value in pair}) == 2 * len(pairs)
            and isinstance(match_axes, (list, tuple))
            and all(isinstance(value, str) and value for value in match_axes)
            and len(set(match_axes)) == len(match_axes)
        )
        valid = (
            placements.get(name) == SEMANTIC_PARTITION
            and version in {1, 2}
            and (
                (version == 1 and set(recipe) == version_one_keys)
                or (version == 2 and set(recipe) == version_two_keys)
            )
            and recipe["placement"] == SEMANTIC_PARTITION
            and recipe["glyph"] == name
            and isinstance(recipe["glyphRowsSha256"], str)
            and len(recipe["glyphRowsSha256"]) == 64
            and all(character in "0123456789abcdef" for character in recipe["glyphRowsSha256"])
            and type(recipe["defaultSubdivisions"]) is int
            and 1 <= recipe["defaultSubdivisions"] <= 16
            and isinstance(overrides, dict)
            and all(
                isinstance(key, str) and key.isdecimal() and type(value) is int and 1 <= value <= 16
                for key, value in overrides.items()
            )
            and isinstance(slots, (list, tuple))
            and all(type(value) is int and value >= 0 for value in slots)
            and len(set(slots)) == len(slots)
            and isinstance(weights, (list, tuple))
            and all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for value in weights
            )
            and len(set(weights)) == len(weights)
            and (version == 1 or valid_pairs)
            and (version == 1 or bool(pairs and match_axes))
        )
        if not valid:
            raise PipelineError(f"{name}: semantic partition metadata is invalid")
        result[name] = recipe
    expected = {name for name, placement in placements.items() if placement == SEMANTIC_PARTITION}
    if names != expected:
        missing = ", ".join(sorted(expected - names)) or "none"
        extra = ", ".join(sorted(names - expected)) or "none"
        raise PipelineError(
            f"semantic partition recipe mismatch: missing={missing}; unexpected={extra}"
        )
    return result


def _native_iup_transport_metadata(fonts, placements: dict[str, str]) -> dict[str, dict]:
    """Require one identical source-bound recipe for each transport opt-in."""
    names = {
        name for font in fonts for name in font.keys() if NATIVE_IUP_TRANSPORT_KEY in font[name].lib
    }
    expected = {name for name, placement in placements.items() if placement == NATIVE_IUP_TRANSPORT}
    if names != expected:
        raise PipelineError("native-IUP transport placement and recipe must agree")
    result = {}
    required = {
        "schemaVersion",
        "placement",
        "glyph",
        "glyphRowsSha256",
        "referenceSha256",
        "nativeFramePoints",
        "textAdjustmentPoints",
        "textLocations",
        "protectedLocation",
        "maxNativeFrameResidual",
    }
    for name in sorted(names):
        values = []
        for index, font in enumerate(fonts):
            if name not in font or NATIVE_IUP_TRANSPORT_KEY not in font[name].lib:
                raise PipelineError(
                    f"{name}: native-IUP transport metadata is missing in master {index}"
                )
            values.append(font[name].lib[NATIVE_IUP_TRANSPORT_KEY])
        if any(value != values[0] for value in values[1:]):
            raise PipelineError(
                f"{name}: native-IUP transport metadata must be identical in every master"
            )
        recipe = values[0]
        valid = (
            isinstance(recipe, dict)
            and set(recipe) == required
            and recipe["schemaVersion"] == 1
            and recipe["placement"] == NATIVE_IUP_TRANSPORT
            and recipe["glyph"] == name
            and all(
                isinstance(recipe[key], str)
                and len(recipe[key]) == 64
                and all(character in "0123456789abcdef" for character in recipe[key])
                for key in ("glyphRowsSha256", "referenceSha256")
            )
        )
        if not valid:
            raise PipelineError(f"{name}: native-IUP transport metadata is invalid")
        result[name] = recipe
    return result


@dataclass(frozen=True)
class QuadraticReferenceReport:
    glyphs: int
    converted_glyphs: int
    exact_default_glyphs: int
    expanded_operations: int
    maximum_segments: int
    carrier_glyphs: tuple[str, ...] = ()


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


def _scaled_contours(contours: list[list[Operation]], factor: int) -> list[list[Operation]]:
    return [
        [
            (
                operation,
                tuple(
                    None if point is None else (point[0] * factor, point[1] * factor)
                    for point in points
                ),
            )
            for operation, points in contour
        ]
        for contour in contours
    ]


def _install_continuous_chain_carrier(
    font,
    name: str,
    contours: list[list[Operation]],
    *,
    protected: bool,
    authorship: str,
) -> str:
    """Carry fractional compatible points without changing visible geometry.

    TrueType rounds simple-glyph source points to integers. A 16x unencoded
    helper plus a fixed 1/16 component transform preserves the exact fractional
    subdivision used by protected outlines and keeps authored rounding below
    one sixteenth of a source unit.
    """
    helper_name = f"{name}.stv-semantic16x"
    if helper_name in font:
        raise PipelineError(f"{name}: continuous-chain carrier glyph already exists")
    scaled = _scaled_contours(contours, CONTINUOUS_CHAIN_SCALE)
    finite_points = [
        point
        for contour in scaled
        for _, points in contour
        for point in points
        if point is not None
    ]
    if any(not all(math.isfinite(value) for value in point) for point in finite_points):
        raise PipelineError(f"{name}: continuous-chain carrier has non-finite coordinates")
    if any(abs(value) > 32767.0 for point in finite_points for value in point):
        raise PipelineError(f"{name}: continuous-chain carrier exceeds TrueType coordinate range")
    if protected and any(value != round(value) for point in finite_points for value in point):
        raise PipelineError(
            f"{name}: protected continuous-chain carrier cannot represent coordinates exactly"
        )
    glyph = font[name]
    helper = font.newGlyph(helper_name)
    helper.width = glyph.width * CONTINUOUS_CHAIN_SCALE
    helper.lib[OPTICAL_AUTHORSHIP_KEY] = authorship
    _draw_contours(helper, scaled)
    glyph.clearContours()
    glyph.getPen().addComponent(
        helper_name,
        (1 / CONTINUOUS_CHAIN_SCALE, 0, 0, 1 / CONTINUOUS_CHAIN_SCALE, 0, 0),
    )
    return helper_name


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


def _reference_count_spline(curve, count: int, tolerance: float) -> list[Point] | None:
    """Fit the existing quadratic topology, then bound every residual cubic.

    Four Gauss nodes integrate the squared cubic residual exactly on each
    segment. Endpoints stay fixed; implicit quadratic joins remain smooth.
    The least-squares objective never substitutes for the geometric bound.
    """
    if count < 1 or not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("Reference-count fit requires positive count and finite tolerance")
    if len(curve) != 4 or any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in curve):
        raise ValueError("Reference-count fit requires four finite points")
    origin = _complex(curve[0])
    points = [_complex(p) - origin for p in curve]
    inner = math.sqrt((3 - 2 * math.sqrt(6 / 5)) / 7)
    outer = math.sqrt((3 + 2 * math.sqrt(6 / 5)) / 7)
    nodes = (-outer, -inner, inner, outer)
    wi, wo = (18 + math.sqrt(30)) / 36, (18 - math.sqrt(30)) / 36
    weights = (wo, wi, wi, wo)
    gram = [[0.0] * count for _ in range(count)]
    rhs = [0j] * count
    for segment in range(count):
        for node, weight in zip(nodes, weights, strict=True):
            local = (node + 1) / 2
            t = (segment + local) / count
            row = [0.0] * count
            a, b, c = (1 - local) ** 2, 2 * (1 - local) * local, local**2
            fixed = 0j
            if segment == 0:
                fixed += a * points[0]
            else:
                row[segment - 1] += a / 2
                row[segment] += a / 2
            row[segment] += b
            if segment == count - 1:
                fixed += c * points[-1]
            else:
                row[segment] += c / 2
                row[segment + 1] += c / 2
            target = (
                (1 - t) ** 3 * points[0]
                + 3 * (1 - t) ** 2 * t * points[1]
                + 3 * (1 - t) * t**2 * points[2]
                + t**3 * points[3]
            )
            for i in range(count):
                rhs[i] += weight * row[i] * (target - fixed)
                for j in range(count):
                    gram[i][j] += weight * row[i] * row[j]
    # The fixed-endpoint quadratic basis is independent: its Gram matrix is
    # positive definite. Cholesky solves both coordinates with one factor.
    lower = [[0.0] * count for _ in range(count)]
    for i in range(count):
        for j in range(i + 1):
            value = gram[i][j] - sum(lower[i][k] * lower[j][k] for k in range(j))
            lower[i][j] = math.sqrt(value) if i == j else value / lower[j][j]
    forward = [0j] * count
    controls = [0j] * count
    for i in range(count):
        forward[i] = (rhs[i] - sum(lower[i][j] * forward[j] for j in range(i))) / lower[i][i]
    for i in reversed(range(count)):
        controls[i] = (
            forward[i] - sum(lower[j][i] * controls[j] for j in range(i + 1, count))
        ) / lower[i][i]
    spline = [tuple(curve[0]), *[_point(p + origin) for p in controls], tuple(curve[-1])]
    cubic = cast(tuple[complex, complex, complex, complex], tuple(_complex(p) for p in curve))
    start = cubic[0]
    for index, part in enumerate(_uniform_cubic_parts(cubic, count)):
        control = _complex(spline[index + 1])
        end = cubic[-1] if index == count - 1 else (control + _complex(spline[index + 2])) / 2
        residual = (
            start - part[0],
            start + (control - start) * (2 / 3) - part[1],
            end + (control - end) * (2 / 3) - part[2],
            end - part[3],
        )
        if max(abs(residual[0]), abs(residual[-1])) > tolerance or not _inside_error(
            *residual, tolerance
        ):
            return None
        start = end
    return spline


def _bezier_point(curve: tuple[Point, Point, Point, Point], value: float) -> complex:
    a, b, c, d = map(_complex, curve)
    inverse = 1 - value
    return inverse**3 * a + 3 * inverse**2 * value * b + 3 * inverse * value**2 * c + value**3 * d


def _quadratic_spans(spline: list[Point]) -> list[tuple[Point, Point, Point]]:
    start, endpoint = spline[0], spline[-1]
    controls = spline[1:-1]
    result = []
    for index, control in enumerate(controls):
        end = (
            endpoint
            if index == len(controls) - 1
            else (
                (control[0] + controls[index + 1][0]) / 2,
                (control[1] + controls[index + 1][1]) / 2,
            )
        )
        result.append((start, control, end))
        start = end
    return result


def _continuous_piecewise_spline(
    curves: list[tuple[Point, Point, Point, Point]], count: int, tolerance: float
) -> list[Point] | None:
    """Fit one continuous quadratic chain to connected cubics by arc length.

    Arc length selects correspondence only. Acceptance uses the independent,
    symmetric geometric certificate below, so a sampled parameter fit cannot
    hide a loop or a bad local approximation.
    """
    if not curves or count < 1 or not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("Continuous-chain fit requires curves, count, and finite tolerance")
    if any(left[-1] != right[0] for left, right in zip(curves, curves[1:], strict=False)):
        raise PipelineError("Continuous-chain source has a disconnected join")
    dense: list[complex] = []
    cumulative = [0.0]
    for curve in curves:
        for index in range(1025):
            if dense and index == 0:
                continue
            point = _bezier_point(curve, index / 1024)
            if dense:
                cumulative.append(cumulative[-1] + abs(point - dense[-1]))
            dense.append(point)
    total = cumulative[-1]
    if total <= 0:
        return None

    def target_at(value: float) -> complex:
        distance = value * total
        high = bisect_left(cumulative, distance)
        if high <= 0:
            return dense[0]
        if high >= len(dense):
            return dense[-1]
        low = high - 1
        span = cumulative[high] - cumulative[low]
        local = 0 if span == 0 else (distance - cumulative[low]) / span
        return dense[low] + (dense[high] - dense[low]) * local

    origin = _complex(curves[0][0])
    endpoint = _complex(curves[-1][-1]) - origin
    gram = [[0.0] * count for _ in range(count)]
    rhs = [0j] * count
    for sample in range(16385):
        value = sample / 16384
        segment = min(int(value * count), count - 1)
        local = value * count - segment
        row = [0.0] * count
        base = 0j
        if segment == 0:
            base += (1 - local) ** 2 * 0j
        else:
            row[segment - 1] += 0.5 * (1 - local) ** 2
            row[segment] += 0.5 * (1 - local) ** 2
        row[segment] += 2 * (1 - local) * local
        if segment == count - 1:
            base += local**2 * endpoint
        else:
            row[segment] += 0.5 * local**2
            row[segment + 1] += 0.5 * local**2
        target = target_at(value) - origin - base
        active = [index for index, coefficient in enumerate(row) if coefficient]
        for i in active:
            rhs[i] += row[i] * target
            for j in active:
                gram[i][j] += row[i] * row[j]
    lower = [[0.0] * count for _ in range(count)]
    for i in range(count):
        for j in range(i + 1):
            value = gram[i][j] - sum(lower[i][k] * lower[j][k] for k in range(j))
            lower[i][j] = math.sqrt(value) if i == j else value / lower[j][j]
    forward = [0j] * count
    controls = [0j] * count
    for i in range(count):
        forward[i] = (rhs[i] - sum(lower[i][j] * forward[j] for j in range(i))) / lower[i][i]
    for i in reversed(range(count)):
        controls[i] = (
            forward[i] - sum(lower[j][i] * controls[j] for j in range(i + 1, count))
        ) / lower[i][i]
    spline: list[Point] = [
        curves[0][0],
        *[_point(control + origin) for control in controls],
        curves[-1][-1],
    ]
    return spline if certify_curve_distance(curves, _quadratic_spans(spline), tolerance) else None


def _subdivide_reference_chain(start: Point, operation: Operation) -> Operation:
    """Represent a native quadratic chain exactly with four times its controls."""
    kind, points = operation
    if kind != "qCurveTo":
        raise ValueError("Continuous-chain subdivision requires qCurveTo")
    controls = [_require_point(point, "reference", "qCurveTo control") for point in points[:-1]]
    endpoint = _require_point(points[-1], "reference", "qCurveTo endpoint")
    expanded: list[Point] = []
    span_start = start
    for index, control in enumerate(controls):
        span_end = (
            endpoint
            if index == len(controls) - 1
            else (
                (control[0] + controls[index + 1][0]) / 2,
                (control[1] + controls[index + 1][1]) / 2,
            )
        )
        for part in range(CONTINUOUS_CHAIN_SUBDIVISIONS):
            value = part / CONTINUOUS_CHAIN_SUBDIVISIONS
            step = 1 / CONTINUOUS_CHAIN_SUBDIVISIONS
            inverse = 1 - value
            point = (
                inverse**2 * span_start[0]
                + 2 * inverse * value * control[0]
                + value**2 * span_end[0],
                inverse**2 * span_start[1]
                + 2 * inverse * value * control[1]
                + value**2 * span_end[1],
            )
            derivative = (
                2 * (inverse * (control[0] - span_start[0]) + value * (span_end[0] - control[0])),
                2 * (inverse * (control[1] - span_start[1]) + value * (span_end[1] - control[1])),
            )
            expanded.append(
                (point[0] + step * derivative[0] / 2, point[1] + step * derivative[1] / 2)
            )
        span_start = span_end
    return "qCurveTo", (*expanded, endpoint)


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


def _partition_balanced_spline(
    spline: list[Point], prefix_count: int, reference_count: int
) -> list[Operation]:
    controls = spline[1:-1]
    endpoint = spline[-1]
    before = prefix_count // 2
    after = prefix_count - before
    counts = [1] * before + [reference_count] + [1] * after
    if sum(counts) != len(controls):
        raise AssertionError("Balanced quadratic partition does not consume its spline")
    result: list[Operation] = []
    cursor = 0
    for index, count in enumerate(counts):
        chunk = controls[cursor : cursor + count]
        cursor += count
        operation_endpoint = (
            endpoint
            if index == len(counts) - 1
            else (
                (controls[cursor - 1][0] + controls[cursor][0]) / 2,
                (controls[cursor - 1][1] + controls[cursor][1]) / 2,
            )
        )
        result.append(("qCurveTo", (*chunk, operation_endpoint)))
    return result


def _fit_piecewise_group(
    groups: list[list[tuple[Point, Point, Point, Point]]],
    reference_count: int,
    tolerance: float,
    glyph_name: str,
    placement: str = "prefix",
) -> tuple[int, list[list[Operation]]]:
    """Fit corresponding cubics around the configured intact reference operation.

    A reviewed source may use several cubics for one native operation. Keep
    each authored join explicit, and retain the reference operation's original
    off-curve count in one operation. Extra quadratics use the requested
    explicit placement around it; the protected master uses stationary curves
    in the corresponding slots.
    This is a conversion primitive, not an inferred correspondence policy.
    """
    if not groups or any(not group for group in groups):
        raise PipelineError(f"{glyph_name}: piecewise correspondence requires nonempty groups")
    if placement not in {
        "prefix",
        BALANCED_ENDPOINTS,
        REFERENCE_COUNT,
        REFERENCE_COUNT_LINES,
        NATIVE_IUP_TRANSPORT,
    }:
        raise ValueError(f"Unknown quadratic padding placement: {placement}")
    if placement in {BALANCED_ENDPOINTS, REFERENCE_COUNT, NATIVE_IUP_TRANSPORT} and any(
        len(group) != 1 for group in groups
    ):
        raise PipelineError(
            f"{glyph_name}: {placement} placement requires one authored curve per group"
        )
    if reference_count < 1 or not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("Piecewise conversion requires positive count and finite tolerance")
    for group in groups:
        for curve in group:
            if len(curve) != 4 or any(
                len(point) != 2 or not all(math.isfinite(value) for value in point)
                for point in curve
            ):
                raise PipelineError(f"{glyph_name}: piecewise source must contain finite cubics")
        if any(left[-1] != right[0] for left, right in zip(group, group[1:], strict=False)):
            raise PipelineError(f"{glyph_name}: piecewise source has a disconnected join")
    if placement in {REFERENCE_COUNT, REFERENCE_COUNT_LINES, NATIVE_IUP_TRANSPORT}:
        # Only real straight source extensions receive extra operations. Never
        # collapse a curved join or manufacture padding to rescue a failed fit.
        prefix = max(len(group) - 1 for group in groups)
        for group in groups:
            for curve in group[:-1]:
                start, a, b, end = map(_complex, curve)
                direction = end - start
                if abs(direction) == 0:
                    valid = a == b == start
                else:
                    controls = ((a - start) / direction, (b - start) / direction)
                    valid = all(abs(p.imag) <= 1e-12 for p in controls) and (
                        0 <= controls[0].real <= controls[1].real <= 1
                    )
                if not valid:
                    raise PipelineError(
                        f"{glyph_name}: reference-count extension must be a monotone straight path"
                    )
        direct = [
            _reference_count_spline(group[-1], reference_count, tolerance) for group in groups
        ]
        if any(spline is None for spline in direct):
            raise PipelineError(
                f"{glyph_name}: reference-count fit exceeds {tolerance:g}-unit bound"
            )
        fitted: list[list[Operation]] = []
        for group, spline in zip(groups, direct, strict=True):
            assert spline is not None
            source_start = group[0][0]
            direct_operations: list[Operation] = [("qCurveTo", (source_start, source_start))] * (
                prefix - len(group) + 1
            )
            for curve in group[:-1]:
                midpoint = ((curve[0][0] + curve[-1][0]) / 2, (curve[0][1] + curve[-1][1]) / 2)
                direct_operations.append(("qCurveTo", (midpoint, curve[-1])))
            direct_operations.append(("qCurveTo", tuple(spline[1:])))
            fitted.append(direct_operations)
        return prefix, fitted
    multiple = math.lcm(*(len(group) for group in groups))
    minimum = max(len(group) for group in groups) * reference_count
    initial = ((minimum + multiple - 1) // multiple) * multiple
    for total in range(initial, 101 * multiple, multiple):
        splines = [
            [_fixed_quadratic_spline(curve, total // len(group), tolerance) for curve in group]
            for group in groups
        ]
        if any(spline is None for group in splines for spline in group):
            continue
        prefix_count = total - reference_count
        result: list[list[Operation]] = []
        for fitted_group in splines:
            if placement == BALANCED_ENDPOINTS:
                spline = fitted_group[0]
                assert spline is not None
                result.append(_partition_balanced_spline(spline, prefix_count, reference_count))
                continue
            operations: list[Operation] = []
            for index, spline in enumerate(fitted_group):
                assert spline is not None
                count = len(spline) - 2
                prefix = count - (reference_count if index == len(fitted_group) - 1 else 1)
                operations.extend(_partition_spline(spline, prefix))
            result.append(operations)
        return prefix_count, result
    raise PipelineError(f"{glyph_name}: piecewise source exceeds {tolerance:g}-unit cu2qu bound")


def _piecewise_contours(
    name: str,
    originals: list[RecordingPen],
    groupings: SourceGroups,
    protected: dict[int, RecordingPen],
    reference_index: int,
    tolerance: float,
    placement: str = "prefix",
    semantic_recipe: dict | None = None,
    source_locations: tuple[dict[str, float], ...] = (),
) -> tuple[list[list[list[Operation]]], int, int]:
    """Validate explicit per-master operation groups and stage their conversion."""
    sources = [_contours(recording, name) for recording in originals]
    references = {index: _contours(recording, name) for index, recording in protected.items()}
    reference = references[reference_index]
    if (placement == SEMANTIC_PARTITION) != (semantic_recipe is not None):
        raise PipelineError(f"{name}: semantic partition placement and recipe must agree")
    if semantic_recipe is not None:
        if len(reference) != 1:
            raise PipelineError(f"{name}: semantic partition currently requires one contour")
        pairs = tuple(tuple(pair) for pair in semantic_recipe.get("pairedOperations", ()))
        paired_indexes = {value for pair in pairs for value in pair}
        configured = (
            set(semantic_recipe["semanticSlots"])
            | paired_indexes
            | {int(index) for index in semantic_recipe["subdivisionOverrides"]}
        )
        semantic_operations = reference[0][1:-1]
        invalid = {
            index
            for index in configured
            if index >= len(semantic_operations) or semantic_operations[index][0] != "qCurveTo"
        }
        if invalid:
            raise PipelineError(
                f"{name}: semantic partition references non-curve operations {sorted(invalid)}"
            )
        if paired_indexes & (
            set(semantic_recipe["semanticSlots"])
            | {int(index) for index in semantic_recipe["subdivisionOverrides"]}
        ):
            raise PipelineError(f"{name}: paired operations cannot also be slots or overrides")
        if pairs and not source_locations:
            raise PipelineError(f"{name}: paired operations require source locations")
    if len(groupings) != len(sources):
        raise PipelineError(f"{name}: piecewise groups must bind every source master")
    for source, grouping in zip(sources, groupings, strict=True):
        if len(source) != len(reference) or len(grouping) != len(reference):
            raise PipelineError(f"{name}: piecewise contour count mismatch")
        for contour, counts, target in zip(source, grouping, reference, strict=True):
            if len(counts) != len(target) or any(
                type(count) is not int or count < 1 for count in counts
            ):
                raise PipelineError(f"{name}: invalid piecewise operation counts")
            if sum(counts) != len(contour):
                raise PipelineError(f"{name}: piecewise groups must consume every source operation")
    result: list[list[list[Operation]]] = [[[] for _ in reference] for _ in sources]
    expanded = maximum = 0
    for contour_index, target in enumerate(reference):
        cursors = [0] * len(sources)
        current: list[Point] = [(0, 0)] * len(sources)
        reference_current: dict[int, Point] = {}
        paired_starts = {
            first: second for first, second in (semantic_recipe or {}).get("pairedOperations", ())
        }
        paired_ends = set(paired_starts.values())
        for operation_index, (kind, target_points) in enumerate(target):
            semantic_index = operation_index - 1
            if semantic_index in paired_ends:
                continue
            chunks = []
            for index, source in enumerate(sources):
                count = groupings[index][contour_index][operation_index]
                chunk = source[contour_index][cursors[index] : cursors[index] + count]
                cursors[index] += count
                chunks.append(chunk)
            if kind != "qCurveTo":
                if any(len(chunk) != 1 or chunk[0][0] != kind for chunk in chunks):
                    raise PipelineError(f"{name}: incompatible grouped {kind} operation")
                for index, chunk in enumerate(chunks):
                    operation = (
                        references[index][contour_index][operation_index]
                        if index in references
                        else chunk[0]
                    )
                    result[index][contour_index].append(operation)
                    if chunk[0][1]:
                        current[index] = _require_point(chunk[0][1][-1], name, kind)
                for index, contours in references.items():
                    points = contours[contour_index][operation_index][1]
                    if points:
                        reference_current[index] = _require_point(points[-1], name, kind)
                continue
            curves: list[list[tuple[Point, Point, Point, Point]]] = []
            for index, chunk in enumerate(chunks):
                group = []
                for source_kind, points in chunk:
                    start = current[index]
                    if source_kind == "lineTo" and len(points) == 1:
                        end = _require_point(points[0], name, "line endpoint")
                        controls = tuple(
                            (start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t)
                            for t in (1 / 3, 2 / 3)
                        )
                        curve = (start, controls[0], controls[1], end)
                    elif source_kind == "curveTo" and len(points) == 3:
                        a, b, end = (
                            _require_point(point, name, "cubic control") for point in points
                        )
                        curve = (start, a, b, end)
                    else:
                        raise PipelineError(
                            f"{name}: grouped curve requires cubic or straight segments"
                        )
                    group.append(curve)
                    current[index] = curve[-1]
                curves.append(group)
            reference_count = _quadratic_count(target_points, name)
            if placement == SEMANTIC_PARTITION:
                assert semantic_recipe is not None
                # Recipe indexes are semantic path operations and intentionally
                # exclude the contour's moveTo and closePath sentinels.
                if semantic_index in paired_starts:
                    second_operation_index = operation_index + 1
                    second_kind, second_target_points = target[second_operation_index]
                    if second_kind != "qCurveTo":
                        raise PipelineError(f"{name}: paired semantic operation is not quadratic")
                    second_chunks = []
                    second_curves = []
                    for index, source in enumerate(sources):
                        count = groupings[index][contour_index][second_operation_index]
                        chunk = source[contour_index][cursors[index] : cursors[index] + count]
                        cursors[index] += count
                        second_chunks.append(chunk)
                        group = []
                        for source_kind, points in chunk:
                            start = current[index]
                            if source_kind == "lineTo" and len(points) == 1:
                                end = _require_point(points[0], name, "line endpoint")
                                controls = tuple(
                                    (
                                        start[0] + (end[0] - start[0]) * value,
                                        start[1] + (end[1] - start[1]) * value,
                                    )
                                    for value in (1 / 3, 2 / 3)
                                )
                                curve = (start, controls[0], controls[1], end)
                            elif source_kind == "curveTo" and len(points) == 3:
                                a, b, end = (
                                    _require_point(point, name, "cubic control") for point in points
                                )
                                curve = (start, a, b, end)
                            else:
                                raise PipelineError(
                                    f"{name}: paired semantic group requires curves or lines"
                                )
                            group.append(curve)
                            current[index] = curve[-1]
                        second_curves.append(group)
                    subdivisions = semantic_recipe["defaultSubdivisions"]
                    second_reference_count = _quadratic_count(second_target_points, name)
                    match_axes = semantic_recipe["protectedMatchAxes"]

                    def protected_match(
                        index: int, axes: tuple[str, ...] = tuple(match_axes)
                    ) -> int:
                        matches = [
                            candidate
                            for candidate in references
                            if all(
                                source_locations[index].get(axis)
                                == source_locations[candidate].get(axis)
                                for axis in axes
                            )
                        ]
                        if len(matches) != 1:
                            raise PipelineError(
                                f"{name}: paired semantic source {index} requires exactly one "
                                "matching protected master"
                            )
                        return matches[0]

                    for index, (first_group, second_group) in enumerate(
                        zip(curves, second_curves, strict=True)
                    ):
                        protected_index = protected_match(index)
                        protected_contour = references[protected_index][contour_index]
                        raw_first_protected = protected_contour[operation_index]
                        raw_second_protected = protected_contour[second_operation_index]
                        if (
                            raw_first_protected[0] != "qCurveTo"
                            or raw_second_protected[0] != "qCurveTo"
                        ):
                            raise PipelineError(
                                f"{name}: protected paired operations must be quadratic"
                            )
                        first_protected = (
                            "qCurveTo",
                            tuple(
                                _require_point(point, name, "protected paired point")
                                for point in raw_first_protected[1]
                            ),
                        )
                        second_protected = (
                            "qCurveTo",
                            tuple(
                                _require_point(point, name, "protected paired point")
                                for point in raw_second_protected[1]
                            ),
                        )
                        if index in references:
                            first_points = subdivide_quadratic_chain(
                                reference_current[index], first_protected, subdivisions
                            )
                            second_points = subdivide_quadratic_chain(
                                _require_point(first_protected[1][-1], name, "paired seam"),
                                second_protected,
                                subdivisions,
                            )
                            result[index][contour_index].extend(
                                (("qCurveTo", first_points), ("qCurveTo", second_points))
                            )
                            reference_current[index] = _require_point(
                                second_protected[1][-1], name, "reference endpoint"
                            )
                            continue
                        first_spline = _continuous_piecewise_spline(
                            first_group, reference_count * subdivisions, tolerance
                        )
                        second_spline = _continuous_piecewise_spline(
                            second_group, second_reference_count * subdivisions, tolerance
                        )
                        if first_spline is None or second_spline is None:
                            raise PipelineError(
                                f"{name}: paired semantic fit exceeds {tolerance:g}-unit bound"
                            )
                        seam = first_spline[-1]
                        if seam != second_spline[0]:
                            raise PipelineError(f"{name}: paired semantic source seam disconnected")
                        protected_seam = _require_point(
                            first_protected[1][-1], name, "protected paired seam"
                        )
                        incoming = _complex(protected_seam) - _complex(
                            _require_point(first_protected[1][-2], name, "protected control")
                        )
                        outgoing = _complex(
                            _require_point(second_protected[1][0], name, "protected control")
                        ) - _complex(protected_seam)
                        if (
                            abs(incoming) == 0
                            or abs(outgoing) == 0
                            or abs(incoming.real * outgoing.imag - incoming.imag * outgoing.real)
                            > 1e-7 * abs(incoming) * abs(outgoing)
                            or (incoming.real * outgoing.real + incoming.imag * outgoing.imag <= 0)
                        ):
                            raise PipelineError(f"{name}: protected paired seam is not smooth")
                        ratio = abs(outgoing) / abs(incoming)
                        endpoint = _complex(seam)
                        previous = _complex(first_spline[-2])
                        following = _complex(second_spline[1])
                        vector = ((endpoint - previous) + ratio * (following - endpoint)) / (
                            1 + ratio**2
                        )
                        first_spline[-2] = _point(endpoint - vector)
                        second_spline[1] = _point(endpoint + ratio * vector)
                        if not certify_curve_distance(
                            first_group, _quadratic_spans(first_spline), tolerance
                        ) or not certify_curve_distance(
                            second_group, _quadratic_spans(second_spline), tolerance
                        ):
                            raise PipelineError(
                                f"{name}: paired seam constraint exceeds {tolerance:g}-unit bound"
                            )
                        result[index][contour_index].extend(
                            (
                                ("qCurveTo", tuple(first_spline[1:])),
                                ("qCurveTo", tuple(second_spline[1:])),
                            )
                        )
                    expanded += (reference_count + second_reference_count) * (subdivisions - 1)
                    maximum = max(
                        maximum,
                        reference_count * subdivisions,
                        second_reference_count * subdivisions,
                    )
                    continue
                slots = set(semantic_recipe["semanticSlots"])
                overrides = semantic_recipe["subdivisionOverrides"]
                subdivisions = overrides.get(
                    str(semantic_index), semantic_recipe["defaultSubdivisions"]
                )
                if semantic_index in slots:
                    if any(
                        len(chunk) not in {1, 2}
                        or (
                            len(chunk) == 2 and [item[0] for item in chunk] != ["lineTo", "curveTo"]
                        )
                        for chunk in chunks
                    ):
                        raise PipelineError(
                            f"{name}: semantic slot {operation_index} requires "
                            "a curve or line+curve"
                        )
                elif any(len(chunk) != 1 for chunk in chunks):
                    raise PipelineError(
                        f"{name}: unconfigured semantic operation {operation_index} "
                        "must be one curve"
                    )
                semantic_target = (
                    "qCurveTo",
                    tuple(
                        _require_point(point, name, "semantic reference point")
                        for point in target_points
                    ),
                )
                for index, group in enumerate(curves):
                    straight_extension = None
                    if len(group) == 2:
                        straight_extension = (group[0][0], group[0][-1])
                    partition = partition_semantic_curve(
                        group[-1],
                        reference_current[reference_index],
                        semantic_target,
                        _reference_count_spline,
                        tolerance,
                        subdivisions=subdivisions,
                        semantic_slot=semantic_index in slots,
                        straight_extension=straight_extension,
                    )
                    if index in references:
                        reference_operation = references[index][contour_index][operation_index]
                        protected_operation = (
                            "qCurveTo",
                            tuple(
                                _require_point(point, name, "semantic protected point")
                                for point in reference_operation[1]
                            ),
                        )
                        protected_partition = partition_semantic_curve(
                            group[-1],
                            reference_current[index],
                            protected_operation,
                            _reference_count_spline,
                            tolerance,
                            subdivisions=subdivisions,
                            semantic_slot=semantic_index in slots,
                        )
                        result[index][contour_index].extend(protected_partition.protected)
                        reference_current[index] = _require_point(
                            reference_operation[1][-1], name, "reference endpoint"
                        )
                    else:
                        result[index][contour_index].extend(partition.authored)
                expanded += reference_count * subdivisions - reference_count
                maximum = max(maximum, reference_count * subdivisions)
                continue
            if placement == CONTINUOUS_CHAIN and max(map(len, curves)) > 1:
                continuous_count = reference_count * CONTINUOUS_CHAIN_SUBDIVISIONS
                splines = [
                    _continuous_piecewise_spline(group, continuous_count, tolerance)
                    for group in curves
                ]
                if any(spline is None for spline in splines):
                    raise PipelineError(
                        f"{name}: continuous-chain fit exceeds {tolerance:g}-unit bound"
                    )
                expanded += continuous_count - reference_count
                maximum = max(maximum, continuous_count)
                for index, spline in enumerate(splines):
                    if index in references:
                        operation = references[index][contour_index][operation_index]
                        result[index][contour_index].append(
                            _subdivide_reference_chain(reference_current[index], operation)
                        )
                        reference_current[index] = _require_point(
                            operation[1][-1], name, "reference endpoint"
                        )
                    else:
                        assert spline is not None
                        result[index][contour_index].append(("qCurveTo", tuple(spline[1:])))
                continue
            effective_placement = (
                REFERENCE_COUNT
                if placement in {CONTINUOUS_CHAIN, NATIVE_IUP_TRANSPORT}
                else placement
            )
            prefix, fitted = _fit_piecewise_group(
                curves, reference_count, tolerance, name, effective_placement
            )
            expanded += prefix
            maximum = max(maximum, prefix + reference_count)
            for index in range(len(sources)):
                if index in references:
                    operation = references[index][contour_index][operation_index]
                    result[index][contour_index].extend(
                        _pad_reference_operation(
                            reference_current[index], operation, prefix, effective_placement
                        )
                    )
                    reference_current[index] = _require_point(
                        operation[1][-1], name, "reference endpoint"
                    )
                else:
                    result[index][contour_index].extend(fitted[index])
    return result, expanded, maximum


def _pad_reference_operation(
    start: Point,
    operation: Operation,
    prefix_count: int,
    placement: str = "prefix",
) -> list[Operation]:
    if placement == REFERENCE_COUNT:
        if prefix_count:
            raise PipelineError("Reference-count conversion cannot insert stationary padding")
        return [operation]
    if placement in {"prefix", REFERENCE_COUNT_LINES}:
        return [
            *(("qCurveTo", (start, start)) for _ in range(prefix_count)),
            operation,
        ]
    if placement != BALANCED_ENDPOINTS:
        raise ValueError(f"Unknown quadratic padding placement: {placement}")
    endpoint = _require_point(operation[1][-1], "reference", "qCurveTo endpoint")
    before = prefix_count // 2
    after = prefix_count - before
    return [
        *(("qCurveTo", (start, start)) for _ in range(before)),
        operation,
        *(("qCurveTo", (endpoint, endpoint)) for _ in range(after)),
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
    additional_reference_glyphs=None,
    force_precision: bool = False,
) -> tuple[bool, int, int]:
    quadratic = [_recording(font[name]) for font in fonts]
    default_glyph = fonts[default_index][name]
    protected_glyphs = {
        index: reference_glyph
        for index, recording in enumerate(originals)
        if recording.value == originals[default_index].value
        and fonts[index][name].width == default_glyph.width
    }
    protected_glyphs.update(additional_reference_glyphs or {})
    references = {index: _recording(glyph) for index, glyph in protected_glyphs.items()}
    reference = references[default_index]
    if not force_precision and all(
        _same_filled_path(quadratic[index], rec) for index, rec in references.items()
    ):
        for index, glyph in protected_glyphs.items():
            fonts[index][name].width = glyph.width
        return False, 0, 0

    source_contours = [_contours(recording, name) for recording in originals]
    quadratic_contours = [_contours(recording, name) for recording in quadratic]
    reference_contours = _contours(reference, name)
    protected_contours = {index: _contours(rec, name) for index, rec in references.items()}
    contour_counts = {len(contours) for contours in quadratic_contours}
    contour_counts.add(len(reference_contours))
    if len(contour_counts) != 1:
        raise PipelineError(f"{name}: reference contour count is incompatible")
    reference_signature = [
        [(op, len(points)) for op, points in contour] for contour in reference_contours
    ]
    for contours in protected_contours.values():
        if [
            [(op, len(points)) for op, points in contour] for contour in contours
        ] != reference_signature:
            raise PipelineError(f"{name}: protected reference masters have incompatible topology")

    reconciled: list[list[list[Operation]]] = [[[] for _ in reference_contours] for _ in fonts]
    protected_indices = set(protected_glyphs)
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
        reference_current = {
            index: _require_point(contours[contour_index][0][1][0], name, "reference moveTo")
            for index, contours in protected_contours.items()
        }
        for font_index in range(len(fonts)):
            reconciled[font_index][contour_index].append(
                protected_contours[font_index][contour_index][0]
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
                        protected_contours[font_index][contour_index][operation_index]
                        if font_index in protected_indices
                        else quadratic_ops[font_index][operation_index]
                    )
                    points = source_ops[font_index][operation_index][1]
                    if points:
                        current_points[font_index] = _require_point(
                            points[-1], name, "source operation endpoint"
                        )
                for index, contours in protected_contours.items():
                    points = contours[contour_index][operation_index][1]
                    if points:
                        reference_current[index] = _require_point(
                            points[-1], name, "reference operation endpoint"
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
                            reference_current[font_index],
                            protected_contours[font_index][contour_index][operation_index],
                            prefix_count,
                        )
                    )
                else:
                    reconciled[font_index][contour_index].extend(
                        _partition_spline(spline, prefix_count)
                    )
                current_points[font_index] = curves[font_index][-1]
            for index, contours in protected_contours.items():
                reference_current[index] = _require_point(
                    contours[contour_index][operation_index][1][-1],
                    name,
                    "reference qCurveTo endpoint",
                )

    for font_index, font in enumerate(fonts):
        _draw_contours(font[name], reconciled[font_index])
        if font_index in protected_indices:
            font[name].width = protected_glyphs[font_index].width
    for index, rec in references.items():
        if not _same_filled_path(_recording(fonts[index][name]), rec):
            raise PipelineError(f"{name}: protected reference geometry moved in master {index}")
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
    source_locations: tuple[dict[str, float], ...] = (),
    protected_locations: dict[int, dict[str, float]] | None = None,
    glyph_max_error: dict[str, float] | None = None,
    source_groups: dict[str, SourceGroups] | None = None,
) -> QuadraticReferenceReport:
    """Convert ``fonts`` in place while preserving a protected TT default.

    The scope is the union of glyphs carrying the engine's content-addressed
    optical-authorship marker in any source.  This avoids mutating unrelated
    donor-derived glyphs and makes the behaviour follow provenance rather than
    a font-specific glyph allow-list.
    """

    if not 0 <= default_index < len(fonts):
        raise ValueError("default_index is outside the source font list")
    if source_locations and len(source_locations) != len(fonts):
        raise ValueError("source_locations must bind every input source")
    if max_error <= 0:
        raise ValueError("max_error must be positive")
    locations = (
        {default_index: reference_location} if protected_locations is None else protected_locations
    )
    if not locations or any(
        not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(fonts)
        for index in locations
    ):
        raise ValueError("protected_locations must identify existing source masters")
    if protected_locations is not None and reference_location:
        raise ValueError("Use either reference_location or protected_locations")
    reference_index = default_index if default_index in locations else min(locations)
    _validate_topology_contract(
        fonts,
        topology_contract,
        expected_master_names=topology_contract_master_names,
        source_master_names=source_master_names,
    )
    reference_fonts = {
        index: _reference_font(reference_path, location) for index, location in locations.items()
    }
    reference = reference_fonts[reference_index]
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
    authorship = {
        name: next(
            font[name].lib[OPTICAL_AUTHORSHIP_KEY]
            for font in fonts
            if font[name].lib.get(OPTICAL_AUTHORSHIP_KEY)
        )
        for name in authored
    }
    metadata_groups = _source_group_metadata(fonts)
    if source_groups is not None and metadata_groups:
        raise PipelineError("Use either source group metadata or explicit source_groups")
    source_groups = metadata_groups if source_groups is None else source_groups
    if set(source_groups) - set(authored):
        raise PipelineError("Piecewise source correspondence requires authored glyphs")
    placements = _padding_placement_metadata(fonts, source_groups)
    semantic_recipes = _semantic_partition_metadata(fonts, placements)
    _native_iup_transport_metadata(fonts, placements)
    errors = glyph_max_error or {}
    if set(errors) - set(authored):
        raise PipelineError("Per-glyph quadratic precision requires authored glyphs")
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not 0 < value < float("inf")
        for value in errors.values()
    ):
        raise ValueError("Per-glyph quadratic precision must be finite and positive")
    protected_glyph_sets = {index: font.getGlyphSet() for index, font in reference_fonts.items()}
    reference_glyphs = protected_glyph_sets[reference_index]
    for name in authored:
        if any(name not in font for font in fonts) or any(
            name not in glyphs for glyphs in protected_glyph_sets.values()
        ):
            raise PipelineError(f"{name}: quadratic reference glyph is missing")
        for recording in originals[name]:
            _contours(recording, name)
        signatures = {
            _topology(_recording(glyphs[name]), name) for glyphs in protected_glyph_sets.values()
        }
        if len(signatures) != 1:
            raise PipelineError(f"{name}: protected reference masters have incompatible topology")
    staged_groups = {
        name: _piecewise_contours(
            name,
            originals[name],
            groups,
            {index: _recording(glyphs[name]) for index, glyphs in protected_glyph_sets.items()},
            reference_index,
            errors.get(name, max_error),
            placements.get(name, "prefix"),
            semantic_recipes.get(name),
            source_locations,
        )
        for name, groups in source_groups.items()
    }
    # Dictionaries expose the same glyph objects while excluding explicitly
    # grouped drawings from cu2qu's one-operation-per-master requirement.
    conversion_fonts = (
        [{name: font[name] for name in font.keys() if name not in source_groups} for font in fonts]
        if source_groups
        else fonts
    )
    fonts_to_quadratic(
        conversion_fonts,
        max_err=max_error,
        reverse_direction=True,
        remember_curve_type=False,
    )

    converted = exact = expanded = maximum_segments = 0
    carrier_glyphs: set[str] = set()
    for name in authored:
        if name in staged_groups:
            contours, glyph_expanded, glyph_maximum = staged_groups[name]
            for index, font in enumerate(fonts):
                _draw_contours(font[name], contours[index])
                if index in protected_glyph_sets:
                    reference_glyph = protected_glyph_sets[index][name]
                    font[name].width = reference_glyph.width
                    if not _same_filled_path(_recording(font[name]), _recording(reference_glyph)):
                        raise PipelineError(
                            f"{name}: grouped conversion moved protected reference geometry"
                        )
                if placements.get(name) in {CONTINUOUS_CHAIN, SEMANTIC_PARTITION}:
                    carrier_glyphs.add(
                        _install_continuous_chain_carrier(
                            font,
                            name,
                            contours[index],
                            protected=index in protected_glyph_sets,
                            authorship=authorship[name],
                        )
                    )
            converted += 1
            expanded += glyph_expanded
            maximum_segments = max(maximum_segments, glyph_maximum)
            continue
        changed, glyph_expanded, glyph_maximum = _reconcile_glyph(
            name,
            fonts,
            reference_index,
            originals[name],
            reference_glyphs[name],
            errors.get(name, max_error),
            additional_reference_glyphs={
                index: glyphs[name] for index, glyphs in protected_glyph_sets.items()
            },
            force_precision=name in errors,
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
        carrier_glyphs=tuple(sorted(carrier_glyphs)),
    )
