"""Reference-master-preserving cubic to TrueType quadratic conversion.

Variable TrueType compilation normally converts every cubic master as one
group.  Adding an independently drawn master can therefore change the chosen
quadratic segmentation and rounding of an otherwise untouched default master.
This module makes the already-shipped TrueType default the authority instead:

* source UFOs are converted together with the normal cu2qu error bound;
* only provenance-marked authored glyphs are reconciled;
* the reference ``glyf`` outline and advance remain exact at the default;
* other masters are fitted to compatible quadratic topology; and
* extra non-reference segments subdivide the protected quadratic along its
  curve (1, 2, 4, 8, or 16 spans per native operation) rather than collapsing
  to a stationary start prefix. A scaled dyadic carrier keeps those points
  integer so compiled Display stays native.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

from fontTools.cu2qu.ufo import CURVE_TYPE_LIB_KEY, fonts_to_quadratic
from fontTools.pens.recordingPen import RecordingPen

from variable_gen.authorship import OPTICAL_AUTHORSHIP_KEY
from variable_gen.common import PipelineError
from variable_gen.curve_certificate import certify_curve_distance
from variable_gen.quadratic_fit import (
    ADAPTIVE_PIECEWISE,
    ADAPTIVE_PIECEWISE_KEY,
    BALANCED_ENDPOINTS,
    CONTINUOUS_CHAIN,
    CONTINUOUS_CHAIN_FULL,
    CONTINUOUS_CHAIN_FULL_SUBDIVISIONS,
    CONTINUOUS_CHAIN_SUBDIVISIONS,
    NATIVE_IUP_TRANSPORT,
    NATIVE_IUP_TRANSPORT_KEY,
    PADDING_PLACEMENT_KEY,
    REFERENCE_COUNT,
    REFERENCE_COUNT_LINES,
    SEMANTIC_PARTITION,
    SEMANTIC_PARTITION_KEY,
    SOURCE_GROUPS_KEY,
    Operation,
    Point,
    QuadraticReferenceReport,
    SourceGroups,
    _adaptive_piecewise_metadata,
    _compatible_reference_prefix,
    _complex,
    _continuous_chain_origin,
    _continuous_piecewise_spline,
    _contours,
    _draw_contours,
    _filled_path,
    _fit_all,
    _fit_piecewise_group,
    _fixed_quadratic_spline,
    _grouped_carrier_scale,
    _install_continuous_chain_carrier,
    _native_iup_transport_metadata,
    _needs_carrier,
    _padding_placement_metadata,
    _partition_spline,
    _partition_subdivided_reference_chain,
    _point,
    _quadratic_count,
    _quadratic_spans,
    _recording,
    _reference_count_spline,
    _reference_font,
    _require_point,
    _reverse_recording,
    _same_filled_path,
    _semantic_partition_metadata,
    _source_group_metadata,
    _subdivide_reference_chain,
    _subdivide_reference_chain_full,
    fit_adaptive_piecewise_group,
)
from variable_gen.quadratic_semantic_partition import (
    partition_endpoint_spans,
    partition_semantic_curve,
    subdivide_quadratic_chain,
)

__all__ = (
    "ADAPTIVE_PIECEWISE_KEY",
    "NATIVE_IUP_TRANSPORT_KEY",
    "PADDING_PLACEMENT_KEY",
    "SEMANTIC_PARTITION_KEY",
    "SOURCE_GROUPS_KEY",
    "_filled_path",
    "_fixed_quadratic_spline",
)


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
    adaptive_recipe: dict | None = None,
) -> tuple[list[list[list[Operation]]], int, int]:
    """Validate explicit per-master operation groups and stage their conversion."""
    sources = [_contours(recording, name) for recording in originals]
    references = {index: _contours(recording, name) for index, recording in protected.items()}
    reference = references[reference_index]
    if (placement == SEMANTIC_PARTITION) != (semantic_recipe is not None):
        raise PipelineError(f"{name}: semantic partition placement and recipe must agree")
    if (placement == ADAPTIVE_PIECEWISE) != (adaptive_recipe is not None):
        raise PipelineError(f"{name}: adaptive piecewise placement and recipe must agree")
    adaptive_allocations: dict[tuple[int, int], tuple[int, ...]] = {}
    if adaptive_recipe is not None:
        for key, allocation in adaptive_recipe["allocations"].items():
            contour_text, semantic_text = key.split(":")
            contour_index = int(contour_text)
            semantic_index = int(semantic_text)
            if (
                contour_index >= len(reference)
                or semantic_index + 1 >= len(reference[contour_index])
                or reference[contour_index][semantic_index + 1][0] != "qCurveTo"
            ):
                raise PipelineError(
                    f"{name}: adaptive piecewise allocation {key} does not identify a curve"
                )
            adaptive_allocations[(contour_index, semantic_index)] = tuple(allocation)
    if semantic_recipe is not None:
        semantic_contour = semantic_recipe.get("semanticContour", 0)
        if semantic_contour >= len(reference):
            raise PipelineError(f"{name}: semantic contour is outside the protected glyph")
        if semantic_recipe.get("schemaVersion") != 5 and len(reference) != 1:
            raise PipelineError(f"{name}: semantic partition currently requires one contour")
        pairs = tuple(tuple(pair) for pair in semantic_recipe.get("pairedOperations", ()))
        paired_indexes = {value for pair in pairs for value in pair}
        configured = (
            set(semantic_recipe["semanticSlots"])
            | paired_indexes
            | {int(index) for index in semantic_recipe["subdivisionOverrides"]}
            | {int(index) for index in semantic_recipe.get("endpointSpans", {})}
        )
        semantic_operations = reference[semantic_contour][1:-1]
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
        semantic_here = semantic_recipe is not None and contour_index == semantic_recipe.get(
            "semanticContour", 0
        )
        paired_starts = (
            {first: second for first, second in semantic_recipe.get("pairedOperations", ())}
            if semantic_here and semantic_recipe is not None
            else {}
        )
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
            if placement == ADAPTIVE_PIECEWISE:
                assert adaptive_recipe is not None
                allocation = adaptive_allocations.get(
                    (contour_index, semantic_index),
                    (reference_count * CONTINUOUS_CHAIN_SUBDIVISIONS,),
                )
                expected = reference_count * adaptive_recipe["subdivisions"]
                if sum(allocation) != expected:
                    raise PipelineError(
                        f"{name}: adaptive piecewise allocation for "
                        f"{contour_index}:{semantic_index} totals {sum(allocation)}, "
                        f"expected {expected}"
                    )
                if max(map(len, curves)) > 1 and (
                    (contour_index, semantic_index) not in adaptive_allocations
                ):
                    raise PipelineError(
                        f"{name}: adaptive piecewise multi-curve operation "
                        f"{contour_index}:{semantic_index} needs an explicit allocation"
                    )
                fitted = fit_adaptive_piecewise_group(curves, allocation, tolerance, name)
                expanded += expected - reference_count
                maximum = max(maximum, max(allocation))
                for index in range(len(sources)):
                    if index in references:
                        operation = references[index][contour_index][operation_index]
                        result[index][contour_index].extend(
                            _partition_subdivided_reference_chain(
                                reference_current[index], operation, allocation
                            )
                        )
                        reference_current[index] = _require_point(
                            operation[1][-1], name, "reference endpoint"
                        )
                    else:
                        result[index][contour_index].extend(fitted[index])
                continue
            if placement == SEMANTIC_PARTITION and semantic_here:
                assert semantic_recipe is not None
                # Recipe indexes are semantic path operations and intentionally
                # exclude the contour's moveTo and closePath sentinels.
                extra_spans = semantic_recipe.get("endpointSpans", {}).get(str(semantic_index))
                if extra_spans is not None:
                    leading = semantic_index in semantic_recipe["semanticSlots"]
                    target_start = reference_current[reference_index]
                    for index, group in enumerate(curves):
                        if index in references:
                            operation = references[index][contour_index][operation_index]
                            span_endpoint = _require_point(operation[1][-1], name, "endpoint span")
                            if leading:
                                start = reference_current[index]
                                result[index][contour_index].append(("qCurveTo", (start, start)))
                            result[index][contour_index].extend(
                                (
                                    operation,
                                    ("qCurveTo", (span_endpoint,) * (extra_spans + 1)),
                                )
                            )
                            reference_current[index] = span_endpoint
                        else:
                            leading_start = group[0][0] if leading else None
                            if leading and chunks[index][0][0] == "lineTo":
                                group = group[1:]
                            endpoint_target = (
                                "qCurveTo",
                                tuple(
                                    _require_point(p, name, "endpoint span") for p in target_points
                                ),
                            )
                            try:
                                partition = partition_endpoint_spans(
                                    group,
                                    endpoint_target,
                                    _reference_count_spline,
                                    tolerance,
                                    extra_spans=extra_spans,
                                    split_fraction=semantic_recipe.get("splitFraction", 0.5),
                                    leading_start=leading_start,
                                    protected_start=target_start if leading else None,
                                )
                            except ValueError as error:
                                raise PipelineError(f"{name}: {error}") from error
                            result[index][contour_index].extend(partition.authored)
                    expanded += extra_spans + int(leading)
                    maximum = max(maximum, reference_count + extra_spans + int(leading))
                    continue
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
            if placement in {CONTINUOUS_CHAIN, CONTINUOUS_CHAIN_FULL} and (
                placement == CONTINUOUS_CHAIN_FULL or max(map(len, curves)) > 1
            ):
                subdivisions = (
                    CONTINUOUS_CHAIN_FULL_SUBDIVISIONS
                    if placement == CONTINUOUS_CHAIN_FULL
                    else CONTINUOUS_CHAIN_SUBDIVISIONS
                )
                continuous_count = reference_count * subdivisions
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
                        if placement == CONTINUOUS_CHAIN_FULL:
                            result[index][contour_index].extend(
                                _subdivide_reference_chain_full(reference_current[index], operation)
                            )
                        else:
                            result[index][contour_index].append(
                                _subdivide_reference_chain(reference_current[index], operation)
                            )
                        reference_current[index] = _require_point(
                            operation[1][-1], name, "reference endpoint"
                        )
                    else:
                        assert spline is not None
                        if placement == CONTINUOUS_CHAIN_FULL:
                            result[index][contour_index].extend(
                                ("qCurveTo", (control, end))
                                for _, control, end in _quadratic_spans(spline)
                            )
                        else:
                            result[index][contour_index].append(("qCurveTo", tuple(spline[1:])))
                continue
            effective_placement = (
                REFERENCE_COUNT
                if placement
                in {
                    CONTINUOUS_CHAIN,
                    CONTINUOUS_CHAIN_FULL,
                    NATIVE_IUP_TRANSPORT,
                }
                else "prefix"
                if placement == SEMANTIC_PARTITION
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
    if placement == "prefix":
        if prefix_count == 0:
            return [operation]
        return _compatible_reference_prefix(start, operation, prefix_count)
    if placement == REFERENCE_COUNT_LINES:
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
    adaptive_recipes = _adaptive_piecewise_metadata(fonts, placements)
    transports = _native_iup_transport_metadata(fonts, placements)
    endpoint_transports = {
        name: recipe for name, recipe in transports.items() if recipe["schemaVersion"] in (2, 3)
    }
    if endpoint_transports:
        reference_hash = hashlib.sha256(reference_path.read_bytes()).hexdigest()
        if any(
            recipe["referenceSha256"] != reference_hash for recipe in endpoint_transports.values()
        ):
            raise PipelineError("Endpoint transport reference bytes changed")
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
            adaptive_recipes.get(name),
        )
        for name, groups in source_groups.items()
    }
    protected_indices = frozenset(protected_glyph_sets)
    carrier_scales = {
        name: _grouped_carrier_scale(
            name,
            contours,
            protected_indices if name not in endpoint_transports else frozenset(),
            placements.get(name, "prefix"),
        )
        for name, (contours, expanded, _) in staged_groups.items()
        if _needs_carrier(placements.get(name, "prefix"), expanded)
    }
    # Stage range validation before mutating any source font. Endpoint-IUP
    # recipes retain their native coordinate frame; only chain conversion
    # uses a translated carrier.
    carrier_origins = {
        name: _continuous_chain_origin(
            name,
            contours,
            carrier_scales[name],
        )
        for name, (contours, _, _) in staged_groups.items()
        if name in carrier_scales
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
                if name in carrier_scales:
                    carrier_glyphs.add(
                        _install_continuous_chain_carrier(
                            font,
                            name,
                            contours[index],
                            # Sparse native endpoint deltas need the mandatory
                            # post-compile transport carried in the report. The
                            # unsplit source geometry was checked exactly above.
                            protected=index in protected_glyph_sets
                            and name not in endpoint_transports,
                            authorship=authorship[name],
                            origin=carrier_origins.get(name, (0, 0)),
                            scale=carrier_scales[name],
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
        if glyph_expanded:
            contours = [_contours(_recording(font[name]), name) for font in fonts]
            scale = _grouped_carrier_scale(name, contours, protected_indices, "prefix")
            origin = _continuous_chain_origin(name, contours, scale)
            for index, font in enumerate(fonts):
                carrier_glyphs.add(
                    _install_continuous_chain_carrier(
                        font,
                        name,
                        contours[index],
                        protected=index in protected_indices,
                        authorship=authorship[name],
                        origin=origin,
                        scale=scale,
                    )
                )

    for font in fonts:
        font.lib[CURVE_TYPE_LIB_KEY] = "quadratic"
    return QuadraticReferenceReport(
        glyphs=len(authored),
        converted_glyphs=converted,
        exact_default_glyphs=exact,
        expanded_operations=expanded,
        maximum_segments=maximum_segments,
        carrier_glyphs=tuple(sorted(carrier_glyphs)),
        endpoint_transports=tuple(sorted(endpoint_transports.items())),
    )
