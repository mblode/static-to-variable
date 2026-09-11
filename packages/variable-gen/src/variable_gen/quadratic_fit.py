"""Fit and prefix-subdivision helpers for quadratic reference conversion."""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pathops
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.reverseContourPen import ReverseContourPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

from variable_gen.authorship import OPTICAL_AUTHORSHIP_KEY
from variable_gen.common import PipelineError
from variable_gen.curve_certificate import certify_curve_distance
from variable_gen.quadratic_semantic_partition import (
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
CONTINUOUS_CHAIN_FULL = "continuous-chain-full"
ADAPTIVE_PIECEWISE = "adaptive-piecewise"
ADAPTIVE_PIECEWISE_KEY = "com.mblode.stv.quadraticAdaptivePiecewise"
SEMANTIC_PARTITION = "semantic-partition"
SEMANTIC_PARTITION_KEY = "com.mblode.stv.quadraticSemanticPartition"
CONTINUOUS_CHAIN_SUBDIVISIONS = 4
CONTINUOUS_CHAIN_FULL_SUBDIVISIONS = 16
CONTINUOUS_CHAIN_SCALE = 16
CONTINUOUS_CHAIN_FULL_SCALE = 32
PREFIX_SUBDIVISIONS = (1, 2, 4, 8, 16)
PREFIX_CARRIER_SCALES = (16, 32, 64, 128, 256, 512)
_CARRIER_PLACEMENTS = frozenset(
    {
        CONTINUOUS_CHAIN,
        CONTINUOUS_CHAIN_FULL,
        ADAPTIVE_PIECEWISE,
        SEMANTIC_PARTITION,
    }
)


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
            CONTINUOUS_CHAIN_FULL,
            ADAPTIVE_PIECEWISE,
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
    version_three_keys = version_one_keys | {"endpointSpans"}
    version_four_keys = version_three_keys | {"splitFraction"}
    version_five_keys = version_two_keys | {"semanticContour"}
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
            or frozenset(value)
            not in {
                frozenset(version_one_keys),
                frozenset(version_two_keys),
                frozenset(version_three_keys),
                frozenset(version_four_keys),
                frozenset(version_five_keys),
            }
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
        endpoint_spans = recipe.get("endpointSpans", {})
        semantic_contour = recipe.get("semanticContour", 0)
        valid_endpoints = (
            isinstance(endpoint_spans, dict)
            and bool(endpoint_spans)
            and all(
                isinstance(key, str)
                and key.isdecimal()
                and str(int(key)) == key
                and type(value) is int
                and 1 <= value <= 64
                for key, value in endpoint_spans.items()
            )
            and recipe["defaultSubdivisions"] == 1
            and not overrides
            and (version == 4 or (not slots and not weights))
        )
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
            and type(version) is int
            and version in {1, 2, 3, 4, 5}
            and (
                (version == 1 and set(recipe) == version_one_keys)
                or (version == 2 and set(recipe) == version_two_keys)
                or (version == 3 and set(recipe) == version_three_keys)
                or (version == 4 and set(recipe) == version_four_keys)
                or (version == 5 and set(recipe) == version_five_keys)
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
            and (version not in {2, 5} or (valid_pairs and bool(pairs and match_axes)))
            and (version not in {3, 4} or valid_endpoints)
            and type(semantic_contour) is int
            and semantic_contour >= 0
            and (
                version != 4
                or (
                    set(slots) <= {int(key) for key in endpoint_spans}
                    and isinstance(recipe["splitFraction"], (int, float))
                    and not isinstance(recipe["splitFraction"], bool)
                    and math.isfinite(recipe["splitFraction"])
                    and 0 < recipe["splitFraction"] < 1
                )
            )
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


def _adaptive_piecewise_metadata(fonts, placements: dict[str, str]) -> dict[str, dict]:
    """Read fixed per-operation allocations for adaptive piecewise conversion."""
    names = {
        name for font in fonts for name in font.keys() if ADAPTIVE_PIECEWISE_KEY in font[name].lib
    }
    expected = {name for name, placement in placements.items() if placement == ADAPTIVE_PIECEWISE}
    required = {
        "schemaVersion",
        "placement",
        "glyph",
        "glyphRowsSha256",
        "subdivisions",
        "allocations",
    }
    result = {}
    for name in sorted(names):
        values = []
        for index, font in enumerate(fonts):
            if name not in font or ADAPTIVE_PIECEWISE_KEY not in font[name].lib:
                raise PipelineError(
                    f"{name}: adaptive piecewise metadata is missing in master {index}"
                )
            values.append(font[name].lib[ADAPTIVE_PIECEWISE_KEY])
        if any(value != values[0] for value in values[1:]):
            raise PipelineError(
                f"{name}: adaptive piecewise metadata must be identical in every master"
            )
        recipe = values[0]
        allocations = recipe.get("allocations") if isinstance(recipe, dict) else None
        valid = (
            isinstance(recipe, dict)
            and set(recipe) == required
            and placements.get(name) == ADAPTIVE_PIECEWISE
            and type(recipe["schemaVersion"]) is int
            and recipe["schemaVersion"] == 1
            and recipe["placement"] == ADAPTIVE_PIECEWISE
            and recipe["glyph"] == name
            and isinstance(recipe["glyphRowsSha256"], str)
            and len(recipe["glyphRowsSha256"]) == 64
            and all(character in "0123456789abcdef" for character in recipe["glyphRowsSha256"])
            and type(recipe["subdivisions"]) is int
            and recipe["subdivisions"] == CONTINUOUS_CHAIN_SUBDIVISIONS
            and isinstance(allocations, dict)
            and all(
                isinstance(key, str)
                and len(parts := key.split(":")) == 2
                and all(part.isdecimal() and str(int(part)) == part for part in parts)
                and isinstance(counts, (list, tuple))
                and len(counts) >= 2
                and all(type(count) is int and 1 <= count <= 64 for count in counts)
                and sum(counts) <= 256
                for key, counts in allocations.items()
            )
        )
        if not valid:
            raise PipelineError(f"{name}: adaptive piecewise metadata is invalid")
        result[name] = recipe
    if names != expected:
        missing = ", ".join(sorted(expected - names)) or "none"
        extra = ", ".join(sorted(names - expected)) or "none"
        raise PipelineError(
            f"adaptive piecewise recipe mismatch: missing={missing}; unexpected={extra}"
        )
    return result


def _native_iup_transport_metadata(fonts, placements: dict[str, str]) -> dict[str, dict]:
    """Require one identical source-bound recipe for each transport opt-in."""
    names = {
        name for font in fonts for name in font.keys() if NATIVE_IUP_TRANSPORT_KEY in font[name].lib
    }
    expected = {name for name, placement in placements.items() if placement == NATIVE_IUP_TRANSPORT}
    if expected - names or any(
        placements.get(name) not in {NATIVE_IUP_TRANSPORT, SEMANTIC_PARTITION} for name in names
    ):
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
        if (
            isinstance(recipe, dict)
            and type(recipe.get("schemaVersion")) is int
            and recipe["schemaVersion"] in (2, 3)
        ):
            from variable_gen.variation_reference import validate_endpoint_transport

            validate_endpoint_transport(name, recipe)
            if placements.get(name) != SEMANTIC_PARTITION or any(
                font[name].lib.get(SEMANTIC_PARTITION_KEY, {}).get("schemaVersion") != 3
                or font[name].lib[SEMANTIC_PARTITION_KEY].get("glyphRowsSha256")
                != recipe["glyphRowsSha256"]
                for font in fonts
            ):
                raise PipelineError(
                    f"{name}: endpoint transport requires matching semantic v3 metadata"
                )
            result[name] = recipe
            continue
        valid = (
            isinstance(recipe, dict)
            and set(recipe) == required
            and placements.get(name) == NATIVE_IUP_TRANSPORT
            and type(recipe["schemaVersion"]) is int
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
    endpoint_transports: tuple[tuple[str, dict], ...] = ()


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


def _continuous_chain_origin(
    name: str, masters: list[list[list[Operation]]], scale: int
) -> tuple[int, int]:
    """Choose one integer origin for every master, retaining zero when it fits."""
    points = [
        point
        for contours in masters
        for contour in contours
        for _, values in contour
        for point in values
        if point is not None
    ]
    if any(not all(math.isfinite(value) for value in point) for point in points):
        raise PipelineError(f"{name}: continuous-chain carrier has non-finite coordinates")
    origin = []
    for axis in (0, 1):
        low = min((point[axis] for point in points), default=0)
        high = max((point[axis] for point in points), default=0)
        # The component offset is itself a signed TrueType coordinate. A
        # common integer origin preserves both interpolation and exact grids.
        minimum = max(-32768, math.ceil(high - 32767 / scale))
        maximum = min(32767, math.floor(low + 32767 / scale))
        if minimum > maximum:
            raise PipelineError(
                f"{name}: continuous-chain carrier exceeds TrueType coordinate range"
            )
        origin.append(
            0 if minimum <= 0 <= maximum else max(minimum, min(maximum, round((low + high) / 2)))
        )
    return origin[0], origin[1]


def _scaled_contours(
    contours: list[list[Operation]], factor: int, origin: tuple[int, int] = (0, 0)
) -> list[list[Operation]]:
    return [
        [
            (
                operation,
                tuple(
                    None
                    if point is None
                    else ((point[0] - origin[0]) * factor, (point[1] - origin[1]) * factor)
                    for point in points
                ),
            )
            for operation, points in contour
        ]
        for contour in contours
    ]


def _protected_grid_scale(name: str, points: list[Point]) -> int:
    """Smallest dyadic carrier that represents protected subdivision points."""
    if any(not math.isfinite(value) for point in points for value in point):
        raise PipelineError(
            f"{name}: protected continuous-chain carrier has non-finite coordinates"
        )
    for scale in PREFIX_CARRIER_SCALES:
        if all(value * scale == round(value * scale) for point in points for value in point):
            return scale
    raise PipelineError(
        f"{name}: protected continuous-chain carrier cannot represent coordinates exactly"
    )


def _grouped_carrier_scale(
    name: str,
    contours: list[list[list[Operation]]],
    protected_indices: frozenset[int],
    placement: str,
) -> int:
    """Choose the smallest exact carrier grid for protected grouped geometry."""
    if placement == CONTINUOUS_CHAIN_FULL:
        return CONTINUOUS_CHAIN_FULL_SCALE
    if placement not in {ADAPTIVE_PIECEWISE, SEMANTIC_PARTITION, "prefix"}:
        return CONTINUOUS_CHAIN_SCALE

    protected_points = [
        point
        for index, master in enumerate(contours)
        if index in protected_indices
        for contour in master
        for _, points in contour
        for point in points
        if point is not None
    ]
    if placement == "prefix":
        return _protected_grid_scale(name, protected_points)
    for scale in (CONTINUOUS_CHAIN_SCALE, CONTINUOUS_CHAIN_FULL_SCALE):
        if all(
            math.isfinite(value) and value * scale == round(value * scale)
            for point in protected_points
            for value in point
        ):
            scaled_points = [
                value * scale
                for master in contours
                for contour in master
                for _, points in contour
                for point in points
                if point is not None
                for value in point
            ]
            if all(math.isfinite(value) and abs(value) <= 32767 for value in scaled_points):
                return scale
    raise PipelineError(
        f"{name}: protected continuous-chain carrier cannot represent coordinates exactly"
    )


def _install_continuous_chain_carrier(
    font,
    name: str,
    contours: list[list[Operation]],
    *,
    protected: bool,
    authorship: str,
    scale: int = CONTINUOUS_CHAIN_SCALE,
    origin: tuple[int, int] = (0, 0),
) -> str:
    """Carry fractional compatible points without changing visible geometry.

    TrueType rounds simple-glyph source points to integers. A scaled unencoded
    helper plus its inverse component transform preserves the exact fractional
    subdivision used by protected outlines and bounds authored rounding by the
    selected carrier scale.
    """
    helper_name = f"{name}.stv-semantic{scale}x"
    if helper_name in font:
        raise PipelineError(f"{name}: continuous-chain carrier glyph already exists")
    scaled = _scaled_contours(contours, scale, origin)
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
    helper.width = glyph.width * scale
    helper.lib[OPTICAL_AUTHORSHIP_KEY] = authorship
    _draw_contours(helper, scaled)
    glyph.clearContours()
    glyph.getPen().addComponent(
        helper_name,
        (1 / scale, 0, 0, 1 / scale, *origin),
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


def _partition_spline_by_counts(
    spline: list[Point], allocations: tuple[int, ...]
) -> list[Operation]:
    controls = spline[1:-1]
    endpoint = spline[-1]
    if not allocations or any(type(count) is not int or count < 1 for count in allocations):
        raise ValueError("Adaptive piecewise allocations must be positive integers")
    if sum(allocations) != len(controls):
        raise ValueError("Adaptive piecewise allocations must consume every quadratic span")
    result: list[Operation] = []
    cursor = 0
    for index, count in enumerate(allocations):
        chunk = controls[cursor : cursor + count]
        cursor += count
        operation_endpoint = (
            endpoint
            if index == len(allocations) - 1
            else (
                (controls[cursor - 1][0] + controls[cursor][0]) / 2,
                (controls[cursor - 1][1] + controls[cursor][1]) / 2,
            )
        )
        result.append(("qCurveTo", (*chunk, operation_endpoint)))
    return result


def fit_adaptive_piecewise_group(
    groups: list[list[tuple[Point, Point, Point, Point]]],
    allocations: tuple[int, ...],
    tolerance: float,
    glyph_name: str,
) -> list[list[Operation]]:
    """Fit reviewed cubic pieces to one fixed, native-derived q allocation.

    A source group may contain either one cubic, which is fit as one chain and
    split at the reviewed allocation boundaries, or one cubic per allocation.
    The latter preserves each authored join and gives difficult pieces only the
    native subdivision capacity assigned to them. Acceptance uses the symmetric
    geometric certificate over the complete group.
    """
    if not groups:
        raise ValueError("Adaptive piecewise conversion requires source groups")
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("Adaptive piecewise conversion requires a finite tolerance")
    if not allocations or any(type(count) is not int or count < 1 for count in allocations):
        raise ValueError("Adaptive piecewise allocations must be positive integers")
    fitted: list[list[Operation]] = []
    for group in groups:
        if len(group) == 1:
            spline = _reference_count_spline(group[0], sum(allocations), tolerance)
            if spline is None:
                raise PipelineError(
                    f"{glyph_name}: adaptive piecewise fit exceeds {tolerance:g}-unit bound"
                )
            operations = _partition_spline_by_counts(spline, allocations)
            spans = _quadratic_spans(spline)
        elif len(group) == len(allocations):
            splines = [
                _reference_count_spline(curve, count, tolerance)
                for curve, count in zip(group, allocations, strict=True)
            ]
            if any(spline is None for spline in splines):
                raise PipelineError(
                    f"{glyph_name}: adaptive piecewise fit exceeds {tolerance:g}-unit bound"
                )
            resolved = [spline for spline in splines if spline is not None]
            operations = [("qCurveTo", tuple(spline[1:])) for spline in resolved]
            spans = [span for spline in resolved for span in _quadratic_spans(spline)]
        else:
            raise PipelineError(
                f"{glyph_name}: adaptive piecewise group has {len(group)} curves for "
                f"{len(allocations)} allocations"
            )
        if not certify_curve_distance(group, spans, tolerance):
            raise PipelineError(
                f"{glyph_name}: adaptive piecewise certificate exceeds {tolerance:g}-unit bound"
            )
        fitted.append(operations)
    return fitted


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


def _subdivide_reference_chain_full(start: Point, operation: Operation) -> list[Operation]:
    """Interleave collapsed capacity through the protected fourfold chain.

    The authored full-chain fit distributes all of its compatible spans over
    the source curve. Keeping every collapsed protected span at the final
    endpoint makes most corresponding points travel across the entire curve
    on the optical axis. Interleaving each quarter's capacity at that quarter's
    endpoint preserves the exact protected path while keeping corresponding
    movement local.
    """
    kind, points = _subdivide_reference_chain(start, operation)
    assert kind == "qCurveTo"
    spline = [start, *[_require_point(point, "reference", "qCurveTo point") for point in points]]
    quarters: list[Operation] = [
        ("qCurveTo", (control, end)) for _, control, end in _quadratic_spans(spline)
    ]
    collapsed_per_quarter = CONTINUOUS_CHAIN_FULL_SUBDIVISIONS // CONTINUOUS_CHAIN_SUBDIVISIONS - 1
    operations: list[Operation] = []
    for quarter in quarters:
        endpoint = _require_point(quarter[1][-1], "reference", "qCurveTo endpoint")
        operations.append(quarter)
        operations.extend(("qCurveTo", (endpoint, endpoint)) for _ in range(collapsed_per_quarter))
    return operations


def _partition_subdivided_reference_chain(
    start: Point, operation: Operation, allocations: tuple[int, ...]
) -> list[Operation]:
    kind, points = _subdivide_reference_chain(start, operation)
    assert kind == "qCurveTo"
    spline = [start, *[_require_point(point, "reference", "qCurveTo point") for point in points]]
    return _partition_spline_by_counts(spline, allocations)


def _needs_carrier(placement: str, expanded: int) -> bool:
    return placement in _CARRIER_PLACEMENTS or (placement == "prefix" and expanded > 0)


def _compatible_span_totals(reference_count: int, multiple: int, minimum: int) -> list[int]:
    return [
        reference_count * subdivisions
        for subdivisions in PREFIX_SUBDIVISIONS
        if reference_count * subdivisions >= minimum
        and reference_count * subdivisions % multiple == 0
    ]


def _compatible_reference_prefix(
    start: Point, operation: Operation, prefix_count: int
) -> list[Operation]:
    """Emit extra Display spans along the native curve, never as (start, start)."""
    reference_count = _quadratic_count(operation[1], "reference")
    total = prefix_count + reference_count
    if reference_count < 1 or total % reference_count:
        raise PipelineError("Compatible Display padding requires a native span multiple")
    subdivisions = total // reference_count
    if subdivisions not in PREFIX_SUBDIVISIONS:
        raise PipelineError(
            "Compatible Display padding must use 1, 2, 4, 8, or 16 spans per native quadratic"
        )
    kind, points = operation
    explicit = tuple(_require_point(point, "reference", "qCurveTo point") for point in points)
    expanded = subdivide_quadratic_chain(start, (kind, explicit), subdivisions)
    return _partition_spline([start, *expanded], prefix_count)


def _fit_all(
    curves: list[tuple[Point, Point, Point, Point]],
    initial_count: int,
    tolerance: float,
    glyph_name: str,
) -> tuple[int, list[list[Point]]]:
    for subdivisions in PREFIX_SUBDIVISIONS:
        count = initial_count * subdivisions
        if count > 100:
            break
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
    explicit placement around it; prefix extras subdivide the protected curve
    rather than collapsing to a stationary start.
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
    if placement == "prefix":
        totals = _compatible_span_totals(reference_count, multiple, minimum)
    else:
        initial = ((minimum + multiple - 1) // multiple) * multiple
        totals = list(range(initial, 101 * multiple, multiple))
    for total in totals:
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


