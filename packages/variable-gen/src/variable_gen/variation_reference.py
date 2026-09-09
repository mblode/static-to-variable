"""Retain a reference's sparse interpolation with explicit integer residuals."""

import math
from copy import deepcopy
from dataclasses import dataclass

from fontTools.misc.roundTools import otRound
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
from fontTools.ttLib.tables.TupleVariation import TupleVariation
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.varLib.iup import iup_delta

from variable_gen.common import PipelineError
from variable_gen.iup_projection import exact_iup_deltas, project_native_iup_default

ENDPOINT_TRANSPORTS_KEY = "com.mblode.stv.endpointTransports"


def validate_endpoint_transport(name: str, recipe: dict) -> None:
    """Validate the source-bound endpoint finishing contract at the engine boundary."""
    keys = {
        "schemaVersion",
        "placement",
        "glyph",
        "glyphRowsSha256",
        "referenceSha256",
        "nativeEndpointPoints",
        "flatTextY",
        "coordinateScale",
        "maxCoordinateMove",
    }
    if recipe.get("schemaVersion") == 3:
        keys.add("nativeFixedCoordinates")
    if (
        set(recipe) != keys
        or type(recipe["schemaVersion"]) is not int
        or recipe["schemaVersion"] not in (2, 3)
        or recipe["placement"] != "semantic-partition"
        or recipe["glyph"] != name
    ):
        raise PipelineError(f"{name}: invalid endpoint transport schema")
    points = recipe["nativeEndpointPoints"]
    if (
        not isinstance(points, (list, tuple))
        or not points
        or any(type(i) is not int or i < 0 for i in points)
        or len(set(points)) != len(points)
    ):
        raise PipelineError(f"{name}: invalid native endpoint points")
    for key in ("glyphRowsSha256", "referenceSha256"):
        value = recipe[key]
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise PipelineError(f"{name}: invalid endpoint transport hash")
    if (
        type(recipe["coordinateScale"]) is not int
        or recipe["coordinateScale"] != 16
        or type(recipe["flatTextY"]) is not int
    ):
        raise PipelineError(f"{name}: invalid endpoint coordinate contract")
    move = recipe["maxCoordinateMove"]
    if type(move) not in (int, float) or not math.isfinite(move) or not 0 < move <= 1000:
        raise PipelineError(f"{name}: invalid endpoint movement bound")
    _native_fixed_coordinates(recipe.get("nativeFixedCoordinates", []))


def _native_fixed_coordinates(rows: list) -> dict[tuple[int, int], int]:
    """Parse native point landmarks in scaled candidate coordinates."""
    if not isinstance(rows, list):
        raise PipelineError("Invalid native fixed coordinates")
    result = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"point", "axis", "value"}
            or any(type(row[key]) is not int for key in row)
            or row["point"] < 0
            or row["axis"] not in (0, 1)
            or (row["point"], row["axis"]) in result
        ):
            raise PipelineError("Invalid native fixed coordinate landmark")
        result[row["point"], row["axis"]] = row["value"]
    return result


def apply_endpoint_transports(
    reference: TTFont, candidate: TTFont, recipes: dict[str, dict]
) -> dict:
    """Complete declared endpoint carriers before build fidelity checks and release."""
    staged = deepcopy(candidate)
    results = {}
    for name, recipe in sorted(recipes.items()):
        validate_endpoint_transport(name, recipe)
        helper = f"{name}.stv-semantic16x"
        if helper not in staged["glyf"]:
            raise PipelineError(f"{name}: endpoint helper is missing")
        points = staged["glyf"][helper].getCoordinates(staged["glyf"])[0]
        cap = recipe["flatTextY"] * recipe["coordinateScale"]
        fixed = {(i, 1): cap for i, point in enumerate(points) if point[1] == cap}
        if len(fixed) < 2:
            raise PipelineError(f"{name}: endpoint source has no paired flat caps")
        results[name] = restore_endpoint_iup_default(
            reference,
            staged,
            name,
            helper,
            endpoint_points=frozenset(recipe["nativeEndpointPoints"]),
            fixed_coordinates=fixed,
            scale=recipe["coordinateScale"],
            max_move=recipe["maxCoordinateMove"],
            native_fixed_coordinates=_native_fixed_coordinates(
                recipe.get("nativeFixedCoordinates", [])
            ),
        )
    for tag in ("glyf", "gvar"):
        candidate[tag] = staged[tag]
    return results


@dataclass(frozen=True)
class NativeIupTransport:
    """Point roles and endpoint locations for a true-default IUP transport."""

    native_frame_points: frozenset[int]
    text_adjustment_points: frozenset[int]
    text_locations: tuple[tuple[tuple[str, float], ...], ...]
    max_native_frame_residual: float


def restore_endpoint_iup_default(
    reference: TTFont,
    candidate: TTFont,
    name: str,
    helper_name: str,
    *,
    endpoint_points: frozenset[int],
    fixed_coordinates: dict[tuple[int, int], int],
    scale: int = 16,
    max_move: float = 1000,
    native_fixed_coordinates: dict[tuple[int, int], int] | None = None,
) -> dict:
    """Transport two native weight tuples through a single expanded helper.

    The candidate owns its authored default and all six master endpoints. The
    reference owns sparse high-weight inference at maximum optical size. The
    supported contract is deliberately narrow: two unwarped axes, one contour,
    fully explicit low-weight deltas, and collapsed additions at named native
    endpoints. Unsupported shapes fail before mutating the candidate.
    """
    _check_coordinate_space(reference, candidate)
    axes = {axis.axisTag: axis for axis in candidate["fvar"].axes}
    if set(axes) != {"wght", "opsz"} or axes["opsz"].defaultValue != axes["opsz"].minValue:
        raise PipelineError("Endpoint IUP requires weight and minimum-default optical axes")
    if "avar" in candidate or "avar" in reference:
        raise PipelineError("Endpoint IUP requires unwarped axes")
    if type(scale) is not int or scale <= 0 or not endpoint_points:
        raise PipelineError("Endpoint IUP requires an integer scale and explicit endpoints")
    weight, optical = axes["wght"], axes["opsz"]
    if not weight.minValue < weight.defaultValue < weight.maxValue:
        raise PipelineError("Endpoint IUP requires an interior weight default")
    low_support = {"wght": (-1.0, -1.0, 0.0)}
    high_support = {"wght": (0.0, 1.0, 1.0)}
    optical_support = {"opsz": (0.0, 1.0, 1.0)}
    native_variations = reference["gvar"].variations[name]
    if len(native_variations) != 2 or [v.axes for v in native_variations] != [
        low_support,
        high_support,
    ]:
        raise PipelineError("Endpoint IUP requires exactly the two native weight tuples")
    low_tuple, high_tuple = native_variations
    if any(point is None for point in low_tuple.coordinates):
        raise PipelineError("Endpoint IUP requires explicit native low-weight deltas")
    parent = candidate["glyf"][name]
    if not parent.isComposite() or len(parent.components) != 1:
        raise PipelineError("Endpoint IUP requires a single visible helper component")
    component_name, transform = parent.components[0].getComponentInfo()
    if component_name != helper_name or transform != (1 / scale, 0, 0, 1 / scale, 0, 0):
        raise PipelineError("Endpoint IUP helper transform changed")
    if candidate["gvar"].variations.get(name):
        # Metrics/component variation stays owned by the enclosing font. Movement
        # of the component itself would invalidate this helper's coordinate proof.
        for variation in candidate["gvar"].variations[name]:
            if variation.coordinates[0] not in (None, (0, 0)):
                raise PipelineError("Endpoint IUP cannot transport a moving component")
    native_glyph = reference["glyf"][name]
    if native_glyph.isComposite() or len(native_glyph.endPtsOfContours) != 1:
        raise PipelineError("Endpoint IUP currently requires one native contour")
    native_coords, native_controls = reference["glyf"]._getCoordinatesAndControls(
        name, reference["hmtx"].metrics, None
    )
    native_points = len(native_coords) - 4
    if any(
        type(index) is not int
        or not 0 <= index < native_points
        or not native_glyph.flags[index] & 1
        or high_tuple.coordinates[index] is None
        for index in endpoint_points
    ):
        raise PipelineError("Endpoint IUP additions require explicit native on-curve deltas")

    snapshots = []
    for optical_value in (optical.minValue, optical.maxValue):
        for weight_value in (weight.minValue, weight.defaultValue, weight.maxValue):
            instance = instantiateVariableFont(
                candidate, {"wght": weight_value, "opsz": optical_value}, inplace=False
            )
            helper = instance["glyf"][helper_name]
            if helper.isComposite() or len(helper.endPtsOfContours) != 1:
                raise PipelineError("Endpoint IUP requires a single simple helper contour")
            points, controls = instance["glyf"]._getCoordinatesAndControls(
                helper_name, instance["hmtx"].metrics, None
            )
            snapshots.append((list(points), controls))
    t_low, desired, t_high, d_low, d_default, d_high = [points for points, _ in snapshots]
    if any(
        controls.endPts != snapshots[0][1].endPts or controls.flags != snapshots[0][1].flags
        for _, controls in snapshots
    ):
        raise PipelineError("Endpoint IUP helper topology changes across masters")
    # Fontmake can preserve native direction while direct ufo2ft compilation
    # reverses it. Verify complete correspondence in either direction; never
    # infer direction from a partial match or permit arbitrary point reordering.
    flags = snapshots[4][1].flags
    matches_by_direction = []
    for order in (list(range(native_points)), [0, *range(native_points - 1, 0, -1)]):
        correspondence, cursor = {}, 0
        for native_index in order:
            target = tuple(value * scale for value in native_coords[native_index])
            while cursor < len(d_default) - 4:
                if tuple(d_default[cursor]) == target and (flags[cursor] & 1) == (
                    native_glyph.flags[native_index] & 1
                ):
                    break
                cursor += 1
            if cursor == len(d_default) - 4:
                break
            correspondence[cursor] = native_index
            cursor += 1
        if len(correspondence) == native_points:
            matches_by_direction.append(correspondence)
    if len(matches_by_direction) != 1:
        raise PipelineError("Endpoint IUP native contour correspondence missing or ambiguous")
    mapping = matches_by_direction[0]
    extra = {}
    for index in range(len(d_default) - 4):
        if index in mapping:
            continue
        matches = [
            point
            for point in endpoint_points
            if tuple(value * scale for value in native_coords[point]) == tuple(d_default[index])
        ]
        if len(matches) != 1:
            raise PipelineError("Endpoint IUP extra point is not an unambiguous collapsed endpoint")
        extra[index] = matches[0]
    inverse = {native_index: index for index, native_index in mapping.items()}
    full_map = [inverse[index] for index in range(native_points)] + list(
        range(len(desired) - 4, len(desired))
    )
    fixed_coordinates = dict(fixed_coordinates)
    for (point, axis), value in (native_fixed_coordinates or {}).items():
        if point not in inverse or axis not in (0, 1) or type(value) is not int:
            raise PipelineError("Endpoint IUP fixed landmark is not a native outline coordinate")
        key = (inverse[point], axis)
        if key in fixed_coordinates and fixed_coordinates[key] != value:
            raise PipelineError("Endpoint IUP fixed landmark conflicts with a flat cap")
        fixed_coordinates[key] = value
    projection = project_native_iup_default(
        list(native_coords),
        native_controls.endPts,
        [high_tuple.coordinates],
        desired,
        full_map,
        fixed_coordinates=fixed_coordinates,
        max_move=max_move,
    )

    def delta(start, end):
        return [
            tuple(b - a for a, b in zip(p, q, strict=True)) for p, q in zip(start, end, strict=True)
        ]

    low, high, optical_delta = [
        delta(projection.coordinates, target) for target in (t_low, t_high, d_default)
    ]
    low_native, high_native = delta(d_default, d_low), delta(d_default, d_high)
    for index, native_index in mapping.items():
        if high_tuple.coordinates[native_index] is None:
            high_native[index] = None
    for index, native_index in extra.items():
        high_native[index] = tuple(value * scale for value in high_tuple.coordinates[native_index])
    # New explicit endpoints must not change inferred native deltas anywhere.
    inferred = exact_iup_deltas(projection.coordinates, snapshots[0][1].endPts, high_native)
    native_inferred = exact_iup_deltas(
        native_coords, native_controls.endPts, high_tuple.coordinates
    )
    for index, native_index in {**mapping, **extra}.items():
        if inferred[index] != tuple(value * scale for value in native_inferred[native_index]):
            raise PipelineError("Expanded endpoint IUP changed native sparse inference")
        if low_native[index] != tuple(
            value * scale for value in low_tuple.coordinates[native_index]
        ):
            raise PipelineError("Expanded endpoint IUP changed the native low-weight endpoint")
    variations = [
        TupleVariation(low_support, low),
        TupleVariation(high_support, high),
        TupleVariation(optical_support, optical_delta),
        TupleVariation({**low_support, **optical_support}, delta(low, low_native)),
        TupleVariation({**high_support, **optical_support}, [tuple(-v for v in p) for p in high]),
        TupleVariation({**high_support, **optical_support}, high_native),
    ]
    # Stage the mutation only after every mapping/projection/inference check passes.
    glyph = deepcopy(candidate["glyf"][helper_name])
    glyph.recalcBounds(candidate["glyf"])
    original_x_min = glyph.xMin
    glyph.coordinates = GlyphCoordinates(projection.coordinates[:-4])
    glyph.recalcBounds(candidate["glyf"])
    if glyph.xMin != original_x_min:
        raise PipelineError("Endpoint IUP projection changed the helper phantom origin")
    candidate["glyf"][helper_name] = glyph
    candidate["gvar"].variations[helper_name] = variations
    return {
        "nativePoints": native_points,
        "endpointPoints": len(extra),
        "maximumCoordinateMovement": list(projection.maximum_movement),
        "iupConstraintCounts": list(projection.constraint_counts),
        "scale": scale,
    }


def _font_axes(font: TTFont):
    return [(a.axisTag, a.minValue, a.defaultValue, a.maxValue) for a in font["fvar"].axes]


def _check_coordinate_space(reference: TTFont, candidate: TTFont) -> None:
    if _font_axes(reference) != _font_axes(candidate):
        raise PipelineError("Reference inference requires identical axis normalization")
    avar = [
        font["avar"].compile(font) if "avar" in font else None for font in (reference, candidate)
    ]
    if avar[0] != avar[1]:
        raise PipelineError("Reference inference requires identical avar mapping")
    if reference["head"].unitsPerEm != candidate["head"].unitsPerEm:
        raise PipelineError("Reference inference requires identical units per em")


def stationary_prefix_map(original, expanded) -> tuple[int, ...]:
    """Match exact native points, allowing only stationary off/on prefix pairs."""
    if original.isComposite() or expanded.isComposite():
        raise PipelineError("Prefix mapping requires simple contours")
    if len(original.endPtsOfContours) != len(expanded.endPtsOfContours):
        raise PipelineError("Prefix mapping changed contour count")
    mapping = []
    old_start = new_start = 0

    def same(a, b):
        return all(abs(x - y) <= 1e-9 for x, y in zip(a, b, strict=True))

    for old_end, new_end in zip(original.endPtsOfContours, expanded.endPtsOfContours, strict=True):
        i, j = old_start, new_start
        while j <= new_end:
            matches = (
                i <= old_end
                and (original.flags[i] & 1) == (expanded.flags[j] & 1)
                and same(original.coordinates[i], expanded.coordinates[j])
            )
            prefix = (
                i > old_start
                and j + 1 <= new_end
                and original.flags[i - 1] & 1
                and not expanded.flags[j] & 1
                and expanded.flags[j + 1] & 1
                and same(original.coordinates[i - 1], expanded.coordinates[j])
                and same(original.coordinates[i - 1], expanded.coordinates[j + 1])
            )
            if matches and prefix:
                raise PipelineError("Ambiguous stationary prefix mapping")
            if matches:
                mapping.append(i)
                i, j = i + 1, j + 1
            elif prefix:
                mapping.extend((i - 1, i - 1))
                j += 2
            else:
                raise PipelineError("Expanded outline is not the exact native prefix program")
        if i != old_end + 1:
            raise PipelineError("Prefix mapping omitted native points")
        old_start, new_start = old_end + 1, new_end + 1
    return tuple(mapping)


def restore_reference_with_prefixes(
    reference: TTFont,
    candidate: TTFont,
    glyphs: frozenset[str],
    protected_location: dict[str, float],
) -> dict[str, int]:
    """Retain native IUP fractions in their native base-coordinate frame.

    The constant tuple restores the authored default drawing after rebasing.
    Explicit residuals preserve candidate master deltas apart from the native
    fractional inference. Callers must recheck authored fidelity and Display.
    """
    # The empty selection runs the existing shared coordinate-space checks.
    restore_reference_inference(reference, candidate, frozenset())
    protected_old = instantiateVariableFont(reference, protected_location, inplace=False)
    protected_new = instantiateVariableFont(candidate, protected_location, inplace=False)
    staged = {}
    counts = {}
    for name in sorted(glyphs):
        mapping = stationary_prefix_map(protected_old["glyf"][name], protected_new["glyf"][name])
        old, new = reference["glyf"][name], candidate["glyf"][name]
        if len(mapping) != len(new.coordinates) or len(old.coordinates) != len(
            protected_old["glyf"][name].coordinates
        ):
            raise PipelineError(f"{name}: prefix topology changed during instancing")
        original_coords, original_controls = reference["glyf"]._getCoordinatesAndControls(
            name, reference["hmtx"].metrics, getattr(reference.get("vmtx"), "metrics", None)
        )
        target_coords, _ = candidate["glyf"]._getCoordinatesAndControls(
            name, candidate["hmtx"].metrics, getattr(candidate.get("vmtx"), "metrics", None)
        )
        revised_glyph = deepcopy(new)
        revised_glyph.coordinates = GlyphCoordinates([old.coordinates[index] for index in mapping])
        revised_glyph.recalcBounds(candidate["glyf"])
        advance, lsb = candidate["hmtx"][name]
        left = revised_glyph.xMin - lsb
        top = bottom = 0
        if "vmtx" in candidate:
            vertical_advance, tsb = candidate["vmtx"][name]
            top = revised_glyph.yMax + tsb
            bottom = top - vertical_advance
        base = list(revised_glyph.coordinates) + [
            (left, 0),
            (left + advance, 0),
            (0, top),
            (0, bottom),
        ]
        constant = [
            tuple(a - b for a, b in zip(point, origin, strict=True))
            for point, origin in zip(target_coords, base, strict=True)
        ]
        # Explicit zero-peak support keeps this constant in browser rasterizers;
        # an empty support rendered differently from static instancing on macOS.
        constant_support = {candidate["fvar"].axes[0].axisTag: (-1, 0, 1)}
        revised = [TupleVariation(constant_support, constant)]
        point_map = (*mapping, *range(len(old.coordinates), len(old.coordinates) + 4))
        count = 0
        for variation in candidate["gvar"].variations[name]:
            if not variation.axes or any(delta is None for delta in variation.coordinates):
                raise PipelineError(
                    f"{name}: prefix restoration requires explicit nonconstant candidate deltas"
                )
            matches = [v for v in reference["gvar"].variations[name] if v.axes == variation.axes]
            if len(matches) > 1:
                raise PipelineError(f"{name}: ambiguous reference variation support")
            if not matches or not any(delta is None for delta in matches[0].coordinates):
                revised.append(deepcopy(variation))
                continue
            native = matches[0]
            inferred = iup_delta(native.coordinates, original_coords, original_controls.endPts)
            lifted = TupleVariation(native.axes, [native.coordinates[index] for index in point_map])
            residual = [
                tuple(
                    value - otRound(original)
                    for value, original in zip(delta, inferred[index], strict=True)
                )
                for delta, index in zip(variation.coordinates, point_map, strict=True)
            ]
            revised.extend((lifted, TupleVariation(variation.axes, residual)))
            count += 1
        staged[name] = revised_glyph, revised
        counts[name] = count
    for name, (glyph, variations) in staged.items():
        candidate["glyf"][name] = glyph
        candidate["gvar"].variations[name] = variations
    return counts


def restore_reference_true_default(
    reference: TTFont,
    candidate: TTFont,
    recipes: dict[str, NativeIupTransport],
    protected_location: dict[str, float],
) -> dict[str, dict[str, float | int]]:
    """Preserve sparse native IUP without a tuple active at the default.

    Each recipe partitions all outline and phantom points into a native frame
    and explicitly adjustable Text points. Native endpoint tuples operate in
    the unchanged native frame. Paired corner tuples cancel the Text-only
    adjustments at the protected optical location, where one final tuple
    restores the complete native base. Validation for every glyph completes
    before any candidate table is mutated.
    """
    _check_coordinate_space(reference, candidate)
    axes = {axis.axisTag: axis for axis in candidate["fvar"].axes}
    protected_support = {}
    for tag, value in protected_location.items():
        if tag not in axes:
            raise PipelineError(f"Unknown protected axis: {tag}")
        axis = axes[tag]
        if value == axis.defaultValue:
            continue
        if value != axis.maxValue:
            raise PipelineError("Protected location must use default or maximum axes")
        protected_support[tag] = (0.0, 1.0, 1.0)
    if not protected_support:
        raise PipelineError("True-default transport requires a nondefault protected location")

    staged = {}
    reports = {}
    for name, recipe in sorted(recipes.items()):
        if not isinstance(recipe, NativeIupTransport):
            raise PipelineError(f"{name}: invalid native-IUP transport recipe")
        if (
            not math.isfinite(recipe.max_native_frame_residual)
            or not 0 <= recipe.max_native_frame_residual <= 1
        ):
            raise PipelineError(f"{name}: invalid native-frame residual bound")
        old, new = reference["glyf"][name], candidate["glyf"][name]
        if old.isComposite() or new.isComposite():
            raise PipelineError(f"{name}: true-default transport requires simple contours")
        if (list(old.endPtsOfContours), list(old.flags)) != (
            list(new.endPtsOfContours),
            list(new.flags),
        ):
            raise PipelineError(f"{name}: true-default transport requires identical point topology")
        native_base, native_controls = reference["glyf"]._getCoordinatesAndControls(
            name,
            reference["hmtx"].metrics,
            getattr(reference.get("vmtx"), "metrics", None),
        )
        semantic_base, semantic_controls = candidate["glyf"]._getCoordinatesAndControls(
            name,
            candidate["hmtx"].metrics,
            getattr(candidate.get("vmtx"), "metrics", None),
        )
        if native_controls.endPts != semantic_controls.endPts:
            raise PipelineError(f"{name}: contour endpoints changed")
        point_count = len(semantic_base)
        all_points = frozenset(range(point_count))
        if recipe.native_frame_points & recipe.text_adjustment_points:
            raise PipelineError(f"{name}: native and Text point roles overlap")
        if recipe.native_frame_points | recipe.text_adjustment_points != all_points:
            raise PipelineError(f"{name}: point roles must cover outline and phantom points")
        if not recipe.native_frame_points:
            raise PipelineError(f"{name}: native frame is empty")

        base = GlyphCoordinates(
            [
                native_base[index] if index in recipe.native_frame_points else semantic_base[index]
                for index in range(point_count)
            ]
        )
        frame_residuals = [
            max(
                abs(semantic_base[index][0] - base[index][0]),
                abs(semantic_base[index][1] - base[index][1]),
            )
            for index in recipe.native_frame_points
        ]
        reference_by_support: dict[tuple, list[TupleVariation]] = {}
        for variation in reference["gvar"].variations[name]:
            reference_by_support.setdefault(tuple(sorted(variation.axes.items())), []).append(
                variation
            )

        endpoints = []
        endpoint_supports = set()
        for packed_location in recipe.text_locations:
            location = dict(packed_location)
            if len(location) != len(packed_location) or set(location) != set(axes):
                raise PipelineError(f"{name}: Text locations must name every axis once")
            varying = [
                axis for axis in axes.values() if location[axis.axisTag] != axis.defaultValue
            ]
            if len(varying) != 1:
                raise PipelineError(f"{name}: each Text location must select one endpoint")
            axis = varying[0]
            axis_value = location[axis.axisTag]
            if axis_value == axis.minValue:
                support = {axis.axisTag: (-1.0, -1.0, 0.0)}
            elif axis_value == axis.maxValue:
                support = {axis.axisTag: (0.0, 1.0, 1.0)}
            else:
                raise PipelineError(f"{name}: Text location is not an axis endpoint")
            support_key = tuple(sorted(support.items()))
            matches = reference_by_support.get(support_key, [])
            if len(matches) != 1:
                raise PipelineError(f"{name}: missing or ambiguous native endpoint support")
            if support_key in endpoint_supports:
                raise PipelineError(f"{name}: duplicate Text endpoint support")
            endpoint_supports.add(support_key)
            endpoints.append((location, support, matches[0]))
        if set(reference_by_support) != endpoint_supports:
            raise PipelineError(f"{name}: native variation program has unsupported regions")

        allowed_candidate_supports = set(endpoint_supports)
        allowed_candidate_supports.add(tuple(sorted(protected_support.items())))
        allowed_candidate_supports.update(
            tuple(sorted({**dict(support), **protected_support}.items()))
            for support in endpoint_supports
        )
        candidate_supports = [
            tuple(sorted(variation.axes.items()))
            for variation in candidate["gvar"].variations[name]
        ]
        if (
            len(candidate_supports) != len(set(candidate_supports))
            or set(candidate_supports) != allowed_candidate_supports
        ):
            raise PipelineError(f"{name}: candidate variation program has unsupported regions")

        rows = []
        ratio_errors = []
        for location, support, native in endpoints:
            inferred = iup_delta(native.coordinates, base, semantic_controls.endPts)
            native_inferred = iup_delta(native.coordinates, native_base, native_controls.endPts)
            ratio_error = max(
                max(abs(a - b) for a, b in zip(actual, expected, strict=True))
                for actual, expected in zip(inferred, native_inferred, strict=True)
            )
            if ratio_error > 1e-9:
                raise PipelineError(f"{name}: native sparse IUP ratios changed")
            target_font = instantiateVariableFont(candidate, location, inplace=False, optimize=True)
            target, _ = target_font["glyf"]._getCoordinatesAndControls(
                name,
                target_font["hmtx"].metrics,
                getattr(target_font.get("vmtx"), "metrics", None),
            )
            adjustment = []
            for index, (origin, delta, desired) in enumerate(
                zip(base, inferred, target, strict=True)
            ):
                raw = (
                    desired[0] - origin[0] - delta[0],
                    desired[1] - origin[1] - delta[1],
                )
                if index in recipe.native_frame_points:
                    frame_residuals.append(max(abs(raw[0]), abs(raw[1])))
                    point_delta = (0, 0)
                else:
                    point_delta = (round(raw[0]), round(raw[1]))
                    if any(abs(a - b) > 1e-9 for a, b in zip(raw, point_delta, strict=True)):
                        raise PipelineError(f"{name}: Text adjustment is not integral")
                adjustment.append(point_delta)
            rows.append(deepcopy(native))
            rows.append(TupleVariation(support, adjustment))
            rows.append(
                TupleVariation(
                    {**support, **protected_support},
                    [(-x, -y) for x, y in adjustment],
                )
            )
            ratio_errors.append(ratio_error)

        maximum_residual = max(frame_residuals, default=0)
        if maximum_residual > recipe.max_native_frame_residual:
            raise PipelineError(f"{name}: Text native-frame residual exceeds its bound")
        protected_delta = []
        for expected, actual in zip(native_base, base, strict=True):
            raw = (expected[0] - actual[0], expected[1] - actual[1])
            point_delta = (round(raw[0]), round(raw[1]))
            if any(abs(a - b) > 1e-9 for a, b in zip(raw, point_delta, strict=True)):
                raise PipelineError(f"{name}: protected base adjustment is not integral")
            protected_delta.append(point_delta)
        rows.append(TupleVariation(protected_support, protected_delta))

        revised = deepcopy(new)
        revised.coordinates = GlyphCoordinates(base[: len(new.coordinates)])
        revised.recalcBounds(candidate["glyf"])
        staged[name] = revised, rows
        reports[name] = {
            "nativeSparseRows": len(endpoints),
            "maximumRatioError": max(ratio_errors, default=0),
            "maximumNativeFrameResidual": maximum_residual,
        }
    for name, (glyph, variations) in staged.items():
        candidate["glyf"][name] = glyph
        candidate["gvar"].variations[name] = variations
    return reports


def restore_reference_inference(
    reference: TTFont, candidate: TTFont, glyphs: frozenset[str]
) -> dict[str, int]:
    """Restore fractional IUP behavior for explicitly selected, matching glyphs.

    This changes candidate coordinates by less than one unit. It is not a
    general geometry-preservation guarantee: a changed default can change IUP's
    coordinate frame. Callers must verify protected geometry and authored
    fidelity afterward. All validation precedes mutation.
    """

    _check_coordinate_space(reference, candidate)
    staged = {}
    counts = {}
    for name in sorted(glyphs):
        old, new = reference["glyf"][name], candidate["glyf"][name]
        if old.isComposite() or new.isComposite():
            raise PipelineError(f"{name}: reference inference requires simple contours")
        if (list(old.endPtsOfContours), list(old.flags)) != (
            list(new.endPtsOfContours),
            list(new.flags),
        ):
            raise PipelineError(f"{name}: reference inference requires identical point topology")
        coords, controls = candidate["glyf"]._getCoordinatesAndControls(
            name, candidate["hmtx"].metrics, getattr(candidate.get("vmtx"), "metrics", None)
        )
        revised = []
        count = 0
        for variation in candidate["gvar"].variations[name]:
            matches = [v for v in reference["gvar"].variations[name] if v.axes == variation.axes]
            if len(matches) > 1:
                raise PipelineError(f"{name}: ambiguous reference variation support")
            if not matches or not any(delta is None for delta in matches[0].coordinates):
                revised.append(variation)
                continue
            native = matches[0]
            if len(native.coordinates) != len(variation.coordinates) or any(
                delta is None for delta in variation.coordinates
            ):
                raise PipelineError(
                    f"{name}: reference inference requires explicit matching deltas"
                )
            inferred = iup_delta(native.coordinates, coords, controls.endPts)
            residual = [
                tuple(value - otRound(base) for value, base in zip(delta, original, strict=True))
                for delta, original in zip(variation.coordinates, inferred, strict=True)
            ]
            revised.extend([deepcopy(native), TupleVariation(variation.axes, residual)])
            count += 1
        staged[name] = revised
        counts[name] = count
    for name, variations in staged.items():
        candidate["gvar"].variations[name] = variations
    return counts
