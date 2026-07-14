#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
import shlex
import subprocess
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

import glyphsLib
import ufoLib2
from fontTools.designspaceLib import DesignSpaceDocument
from fontTools.pens.basePen import decomposeQuadraticSegment
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont
from fontTools.varLib import interpolatable
from fontTools.varLib.instancer import instantiateVariableFont

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = SCRIPT_DIR.parent
REPO_ROOT = PACKAGE_DIR.parent.parent
CABINET_DIR = REPO_ROOT / "cabinet"
BUILD_DIR = CABINET_DIR / "build"

for path in (SCRIPT_DIR, CABINET_DIR, BUILD_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from export_designspace import export as export_designspace
from fix_export_compatibility import process_font as process_export_compatibility
from fix_source_files import layer_to_ops, master_layers_for_glyph
from generate_instances import glyph_ink_area, glyph_point_deviation
from import_circular import (
    count_segments,
    effective_structure,
    find_ttf_glyph,
    load_ttf,
    normalize_master_ops,
    parse_contours,
    record_glyph,
    verify_cubic_compat,
    write_ops_to_layer,
)
from manifest_tools import expand_manifest
from populate_circular_glyphs import (
    FONT_PLANS,
    audit_font,
    best_path_mapping,
    find_rotation,
    ordered_master_ids,
    populate_font,
    reorder_layer_paths,
    rotate_path_nodes,
    strict_align_font,
    strict_audit_font,
)

DEFAULT_MANIFEST = PACKAGE_DIR / "manifests/circular-triage.json"
DEFAULT_REPORT_DIR = PACKAGE_DIR / "reports/repair"
DEFAULT_BUILD_DIR = PACKAGE_DIR / "build"


def unicode_glyph_name_map(font) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for glyph in font.glyphs:
        for unicode_value in getattr(glyph, "unicodes", []) or []:
            mapping.setdefault(str(unicode_value).upper(), glyph.name)
    return mapping


def glyph_name_for_character(character: str, unicode_map: dict[str, str]) -> str | None:
    return unicode_map.get(f"{ord(character):04X}")


def resolve_glyph_configs(
    family_manifest: dict[str, object],
    font=None,
) -> dict[str, dict[str, object]]:
    resolved = {
        glyph_name: dict(config) for glyph_name, config in family_manifest.get("glyphs", {}).items()
    }

    unicode_map = unicode_glyph_name_map(font) if font is not None else {}

    for group_config in family_manifest.get("glyph_groups", []):
        glyph_names = list(group_config.get("glyphs") or [])
        for character in group_config.get("chars", ""):
            glyph_name = glyph_name_for_character(character, unicode_map)
            if glyph_name:
                glyph_names.append(glyph_name)

        inherit_from = group_config.get("inherit_from")
        default_config = dict(group_config.get("default") or {})
        inherited_config = dict(resolved.get(inherit_from, {})) if inherit_from else {}

        if inherit_from and "strategy" not in default_config:
            default_config["strategy"] = "inherit_base_contours"
        if inherit_from:
            default_config.setdefault("base_glyph", inherit_from)
            default_config.setdefault("group_name", group_config.get("name"))

        merged_default = dict(inherited_config)
        merged_default.update(default_config)

        for glyph_name in glyph_names:
            config = dict(resolved.get(glyph_name, {}))
            for field_name, value in merged_default.items():
                config.setdefault(field_name, value)
            resolved[glyph_name] = config

    for family_name, family_config in family_manifest.get("glyph_families", {}).items():
        base_glyph = family_config.get("base_glyph")
        members = family_config.get("members") or []
        if not base_glyph or not members:
            continue

        base_config = resolved.get(base_glyph, {})
        strategy = family_config.get("strategy") or "inherit_base_contours"
        inherited_fields: dict[str, object] = {}
        for field_name in ("priority", "repair_bucket", "notes"):
            if family_config.get(field_name) is not None:
                inherited_fields[field_name] = family_config[field_name]
            elif base_config.get(field_name) is not None:
                inherited_fields[field_name] = base_config[field_name]

        for glyph_name in members:
            config = dict(resolved.get(glyph_name, {}))
            config.setdefault("strategy", strategy)
            config.setdefault("base_glyph", base_glyph)
            config.setdefault("family_name", family_name)
            for field_name, value in inherited_fields.items():
                config.setdefault(field_name, value)
            resolved[glyph_name] = config

    return resolved


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the manifest-driven Circular repair pipeline for the live Glide "
            ".glyphs sources, including import, source repair, designspace export, "
            "variable build, instance validation, and review packet generation."
        )
    )
    parser.add_argument(
        "--font",
        choices=("roman", "italic", "all"),
        default="all",
        help="Which family to process.",
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="Path to the triage manifest JSON.",
    )
    parser.add_argument(
        "--report-dir",
        default=str(DEFAULT_REPORT_DIR),
        help="Directory for repair reports.",
    )
    parser.add_argument(
        "--build-dir",
        default=str(DEFAULT_BUILD_DIR),
        help="Directory for designspace, variable fonts, and sampled instances.",
    )
    parser.add_argument(
        "--skip-import",
        action="store_true",
        help="Skip rerunning the Circular importer and operate on the current .glyphs sources.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip designspace export and variable font build.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create importer backups before updating .glyphs sources.",
    )
    return parser.parse_args()


def load_manifest(path: Path) -> dict[str, object]:
    return expand_manifest(path)


def sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def path_signed_area(path) -> float:
    points = [
        (node.position.x, node.position.y) for node in path.nodes if str(node.type) != "offcurve"
    ]
    if len(points) < 3:
        return 0.0
    total = 0.0
    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % len(points)]
        total += x0 * y1 - x1 * y0
    return total * 0.5


def rectangle_ops(
    left: float, bottom: float, right: float, top: float, clockwise: bool
) -> list[tuple[str, tuple]]:
    if clockwise:
        points = [
            (left, bottom),
            (left, top),
            (right, top),
            (right, bottom),
        ]
    else:
        points = [
            (left, bottom),
            (right, bottom),
            (right, top),
            (left, top),
        ]
    return [
        ("moveTo", (points[0],)),
        ("lineTo", (points[1],)),
        ("lineTo", (points[2],)),
        ("lineTo", (points[3],)),
        ("closePath", ()),
    ]


def notdef_ops(font, master, width: int) -> list[tuple[str, tuple]]:
    ascender = getattr(master, "ascender", None) or int(font.upm * 0.8)
    descender = getattr(master, "descender", None) or -int(font.upm * 0.2)
    usable_width = max(int(width), 220)
    margin_x = max(18, min(int(round(usable_width * 0.12)), 64))
    margin_y = max(24, min(int(round((ascender - descender) * 0.06)), 72))
    left = margin_x
    right = usable_width - margin_x
    bottom = int(descender + margin_y)
    top = int(ascender - margin_y)

    weight = int(master.axes[0]) if getattr(master, "axes", None) else 400
    stroke = int(round(36 + ((weight - 100) / 850.0) * 44))
    stroke = max(24, stroke)
    stroke = min(stroke, max(20, int((right - left) * 0.22)))
    stroke = min(stroke, max(20, int((top - bottom) * 0.18)))

    inner_left = left + stroke
    inner_right = right - stroke
    inner_bottom = bottom + stroke
    inner_top = top - stroke

    if inner_right - inner_left < 24:
        adjust = (24 - (inner_right - inner_left) + 1) // 2
        inner_left -= adjust
        inner_right += adjust
    if inner_top - inner_bottom < 24:
        adjust = (24 - (inner_top - inner_bottom) + 1) // 2
        inner_bottom -= adjust
        inner_top += adjust

    outer = rectangle_ops(left, bottom, right, top, clockwise=False)
    inner = rectangle_ops(inner_left, inner_bottom, inner_right, inner_top, clockwise=True)
    return outer + inner


def rebuild_notdef(font) -> dict[str, object]:
    glyph = font.glyphs[".notdef"]
    if glyph is None:
        return {"applied": False, "reason": "missing_glyph"}

    per_master: dict[str, dict[str, int]] = {}
    for master in font.masters:
        layer = glyph.layers[master.id]
        width = int(layer.width or 0)
        if width <= 0:
            width = int(font.upm * 0.3)
            layer.width = width
        layer.shapes = []
        write_ops_to_layer(notdef_ops(font, master, width), layer)
        per_master[master.name] = {
            "width": int(layer.width),
            "path_count": len(layer.paths),
        }
    return {"applied": True, "masters": per_master}


def apply_reference_fallback(
    font, glyph_name: str, reference_master_name: str
) -> dict[str, object]:
    glyph = font.glyphs[glyph_name]
    if glyph is None:
        return {"applied": False, "reason": "missing_glyph"}

    masters_by_name = {master.name: master for master in font.masters}
    reference_master = masters_by_name[reference_master_name]
    reference_layer = glyph.layers[reference_master.id]
    reference_ops = layer_to_ops(reference_layer)
    if not reference_ops:
        return {"applied": False, "reason": "reference_has_no_outlines"}

    applied_masters: list[str] = []
    for master in font.masters:
        if master.id == reference_master.id:
            continue
        layer = glyph.layers[master.id]
        layer.shapes = []
        write_ops_to_layer(reference_ops, layer)
        applied_masters.append(master.name)

    return {
        "applied": True,
        "reference_master": reference_master.name,
        "masters_updated": applied_masters,
    }


def ops_bbox(ops: list[tuple[str, tuple]]) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for _, args in ops:
        for point in args:
            xs.append(float(point[0]))
            ys.append(float(point[1]))
    if not xs or not ys:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def bbox_center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) * 0.5, (bbox[1] + bbox[3]) * 0.5)


def bbox_size(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])


def transform_point(
    point: tuple[float, float],
    scale_x: float,
    scale_y: float,
    origin: tuple[float, float],
    offset: tuple[float, float] = (0.0, 0.0),
) -> tuple[float, float]:
    x = ((point[0] - origin[0]) * scale_x) + origin[0] + offset[0]
    y = ((point[1] - origin[1]) * scale_y) + origin[1] + offset[1]
    return (x, y)


def transform_ops(
    ops: list[tuple[str, tuple]],
    scale_x: float,
    scale_y: float,
    origin: tuple[float, float],
    offset: tuple[float, float] = (0.0, 0.0),
) -> list[tuple[str, tuple]]:
    transformed: list[tuple[str, tuple]] = []
    for op, args in ops:
        transformed_args = tuple(
            transform_point((float(point[0]), float(point[1])), scale_x, scale_y, origin, offset)
            for point in args
        )
        transformed.append((op, transformed_args))
    return transformed


def ops_polylines(ops: list[tuple[str, tuple]], steps: int = 10) -> list[list[tuple[float, float]]]:
    contours: list[list[tuple[float, float]]] = []
    contour: list[tuple[float, float]] = []
    start: tuple[float, float] | None = None
    current: tuple[float, float] | None = None

    for op, args in ops:
        if op == "moveTo":
            if contour:
                contours.append(contour)
            start = (float(args[0][0]), float(args[0][1]))
            current = start
            contour = [start]
        elif op == "lineTo":
            current = (float(args[0][0]), float(args[0][1]))
            contour.append(current)
        elif op == "qCurveTo" and current is not None:
            quadratic_args = [tuple(map(float, point)) for point in args]
            for control, end in decomposeQuadraticSegment(quadratic_args):
                contour.extend(sample_quadratic(current, control, end, steps))
                current = end
        elif op == "curveTo" and current is not None:
            c1, c2, end = [tuple(map(float, point)) for point in args]
            contour.extend(sample_cubic(current, c1, c2, end, steps))
            current = end
        elif op in ("closePath", "endPath"):
            if contour and start is not None and contour[-1] != start:
                contour.append(start)
            if contour:
                contours.append(contour)
            contour = []
            start = None
            current = None

    if contour:
        contours.append(contour)
    return contours


def contour_area(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    total = 0.0
    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % len(points)]
        total += x0 * y1 - x1 * y0
    return total * 0.5


def ops_ink_area(ops: list[tuple[str, tuple]]) -> float:
    return sum(abs(contour_area(contour)) for contour in ops_polylines(ops))


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def dist_sq(left: tuple[float, float], right: tuple[float, float]) -> float:
    return ((left[0] - right[0]) ** 2) + ((left[1] - right[1]) ** 2)


def interpolate_scalar(left: float, right: float, t: float) -> float:
    return left + ((right - left) * t)


def interpolate_point(
    left: tuple[float, float], right: tuple[float, float], t: float
) -> tuple[float, float]:
    return (
        interpolate_scalar(left[0], right[0], t),
        interpolate_scalar(left[1], right[1], t),
    )


def ops_metrics(ops: list[tuple[str, tuple]]) -> dict[str, object] | None:
    bbox = ops_bbox(ops)
    if bbox is None:
        return None
    center = bbox_center(bbox)
    width, height = bbox_size(bbox)
    return {
        "bbox": bbox,
        "center": center,
        "width": max(width, 1.0),
        "height": max(height, 1.0),
        "area": max(ops_ink_area(ops), 1.0),
    }


def fit_ops_to_metrics(
    source_ops: list[tuple[str, tuple]],
    target_center: tuple[float, float],
    target_width: float,
    target_height: float,
    target_area: float,
) -> tuple[list[tuple[str, tuple]], dict[str, float]] | tuple[None, dict[str, float]]:
    source_metrics = ops_metrics(source_ops)
    if source_metrics is None:
        return None, {}

    source_center = source_metrics["center"]
    source_width = float(source_metrics["width"])
    source_height = float(source_metrics["height"])
    source_area = float(source_metrics["area"])

    width_ratio = max(target_width, 1.0) / max(source_width, 1.0)
    height_ratio = max(target_height, 1.0) / max(source_height, 1.0)
    area_ratio = max(target_area, 1.0) / max(source_area, 1.0)

    scale_x = clamp((width_ratio * 0.72) + ((area_ratio**0.5) * 0.28), 0.4, 2.5)
    scale_y_from_area = area_ratio / max(scale_x, 0.1)
    scale_y = clamp((scale_y_from_area * 0.58) + (height_ratio * 0.42), 0.4, 2.5)

    transformed = transform_ops(source_ops, scale_x, scale_y, origin=source_center)
    transformed_bbox = ops_bbox(transformed)
    if transformed_bbox is None:
        return None, {}
    transformed_center = bbox_center(transformed_bbox)
    offset = (
        target_center[0] - transformed_center[0],
        target_center[1] - transformed_center[1],
    )
    transformed = transform_ops(transformed, 1.0, 1.0, origin=(0.0, 0.0), offset=offset)
    return transformed, {
        "scale_x": round(scale_x, 4),
        "scale_y": round(scale_y, 4),
        "area_ratio": round(area_ratio, 4),
        "width_ratio": round(width_ratio, 4),
        "height_ratio": round(height_ratio, 4),
    }


def contour_center(contour_ops: list[tuple[str, tuple]]) -> tuple[float, float]:
    metrics = ops_metrics(contour_ops)
    if metrics is None:
        return (0.0, 0.0)
    return tuple(metrics["center"])


def contour_size(contour_ops: list[tuple[str, tuple]]) -> tuple[float, float]:
    metrics = ops_metrics(contour_ops)
    if metrics is None:
        return (1.0, 1.0)
    return (float(metrics["width"]), float(metrics["height"]))


def contour_segment_signature(contour_ops: list[tuple[str, tuple]]) -> tuple[int, ...]:
    return (count_segments(contour_ops),)


def best_ops_contour_mapping(
    reference_contours: list[list[tuple[str, tuple]]],
    other_contours: list[list[tuple[str, tuple]]],
) -> list[int] | None:
    count = len(reference_contours)
    if count != len(other_contours):
        return None
    if count <= 1:
        return list(range(count))

    ref_centers = [contour_center(contour) for contour in reference_contours]
    other_centers = [contour_center(contour) for contour in other_contours]
    ref_sizes = [contour_size(contour) for contour in reference_contours]
    other_sizes = [contour_size(contour) for contour in other_contours]
    ref_signatures = [contour_segment_signature(contour) for contour in reference_contours]
    other_signatures = [contour_segment_signature(contour) for contour in other_contours]

    costs = [[0.0] * count for _ in range(count)]
    for ref_index in range(count):
        ref_width, ref_height = ref_sizes[ref_index]
        ref_scale = max(ref_width * ref_height, 1.0)
        for other_index in range(count):
            penalty = 0.0
            if ref_signatures[ref_index] != other_signatures[other_index]:
                penalty = 5000.0
            center_cost = dist_sq(ref_centers[ref_index], other_centers[other_index]) / ref_scale
            other_width, other_height = other_sizes[other_index]
            size_cost = abs(ref_width - other_width) + abs(ref_height - other_height)
            costs[ref_index][other_index] = penalty + center_cost + size_cost

    @lru_cache(None)
    def solve(ref_index: int, used_mask: int) -> tuple[float, tuple[int, ...]]:
        if ref_index == count:
            return (0.0, ())

        best_score = float("inf")
        best_mapping: tuple[int, ...] = ()
        for other_index in range(count):
            if used_mask & (1 << other_index):
                continue
            sub_score, sub_mapping = solve(ref_index + 1, used_mask | (1 << other_index))
            score = costs[ref_index][other_index] + sub_score
            if score < best_score:
                best_score = score
                best_mapping = (other_index,) + sub_mapping
        return (best_score, best_mapping)

    return list(solve(0, 0)[1])


def best_ops_contour_subset_mapping(
    reference_contours: list[list[tuple[str, tuple]]],
    other_contours: list[list[tuple[str, tuple]]],
) -> list[int] | None:
    reference_count = len(reference_contours)
    other_count = len(other_contours)
    if reference_count == 0:
        return []
    if other_count < reference_count:
        return None

    ref_centers = [contour_center(contour) for contour in reference_contours]
    other_centers = [contour_center(contour) for contour in other_contours]
    ref_sizes = [contour_size(contour) for contour in reference_contours]
    other_sizes = [contour_size(contour) for contour in other_contours]
    ref_signatures = [contour_segment_signature(contour) for contour in reference_contours]
    other_signatures = [contour_segment_signature(contour) for contour in other_contours]

    costs = [[0.0] * other_count for _ in range(reference_count)]
    for ref_index in range(reference_count):
        ref_width, ref_height = ref_sizes[ref_index]
        ref_scale = max(ref_width * ref_height, 1.0)
        for other_index in range(other_count):
            penalty = 0.0
            if ref_signatures[ref_index] != other_signatures[other_index]:
                penalty = 5000.0
            center_cost = dist_sq(ref_centers[ref_index], other_centers[other_index]) / ref_scale
            other_width, other_height = other_sizes[other_index]
            size_cost = abs(ref_width - other_width) + abs(ref_height - other_height)
            costs[ref_index][other_index] = penalty + center_cost + size_cost

    @lru_cache(None)
    def solve(ref_index: int, used_mask: int) -> tuple[float, tuple[int, ...]]:
        if ref_index == reference_count:
            return (0.0, ())

        best_score = float("inf")
        best_mapping: tuple[int, ...] = ()
        for other_index in range(other_count):
            if used_mask & (1 << other_index):
                continue
            sub_score, sub_mapping = solve(ref_index + 1, used_mask | (1 << other_index))
            score = costs[ref_index][other_index] + sub_score
            if score < best_score:
                best_score = score
                best_mapping = (other_index,) + sub_mapping
        return (best_score, best_mapping)

    mapping = solve(0, 0)[1]
    if len(mapping) != reference_count:
        return None
    return list(mapping)


def build_transformed_ops_from_target(
    reference_ops: list[tuple[str, tuple]],
    target_ops: list[tuple[str, tuple]],
    contour_aware: bool = True,
) -> tuple[list[tuple[str, tuple]] | None, dict[str, object]]:
    reference_contours = parse_contours(reference_ops)
    target_contours = parse_contours(target_ops)

    if (
        contour_aware
        and len(reference_contours) > 1
        and len(reference_contours) == len(target_contours)
    ):
        mapping = best_ops_contour_mapping(reference_contours, target_contours)
        if mapping is not None:
            transformed_contours: list[list[tuple[str, tuple]]] = []
            contour_transforms: dict[str, dict[str, float]] = {}
            ordered_target = [target_contours[index] for index in mapping]
            for index, (reference_contour, target_contour) in enumerate(
                zip(reference_contours, ordered_target, strict=False)
            ):
                target_metrics = ops_metrics(target_contour)
                if target_metrics is None:
                    continue
                transformed, metrics = fit_ops_to_metrics(
                    reference_contour,
                    target_center=tuple(target_metrics["center"]),
                    target_width=float(target_metrics["width"]),
                    target_height=float(target_metrics["height"]),
                    target_area=float(target_metrics["area"]),
                )
                if transformed is None:
                    continue
                transformed_contours.append(parse_contours(transformed)[0])
                contour_transforms[str(index)] = metrics

            if len(transformed_contours) == len(reference_contours):
                return flatten_contours(transformed_contours), {
                    "mode": "contour_aware",
                    "contour_mapping": mapping,
                    "contour_transforms": contour_transforms,
                }

    target_metrics = ops_metrics(target_ops)
    if target_metrics is None:
        return None, {"mode": "missing_target_metrics"}
    transformed, metrics = fit_ops_to_metrics(
        reference_ops,
        target_center=tuple(target_metrics["center"]),
        target_width=float(target_metrics["width"]),
        target_height=float(target_metrics["height"]),
        target_area=float(target_metrics["area"]),
    )
    return transformed, {"mode": "whole_glyph", "transform": metrics}


def master_weight(master) -> int:
    if getattr(master, "axes", None):
        return int(master.axes[0])
    return 400


def sorted_masters_by_weight(font) -> list:
    return sorted(font.masters, key=master_weight)


def bracketing_masters_for_weight(font, target_weight: int) -> tuple[object, object, float] | None:
    masters = sorted_masters_by_weight(font)
    if not masters:
        return None
    if target_weight <= master_weight(masters[0]) or target_weight >= master_weight(masters[-1]):
        return None
    for left, right in zip(masters, masters[1:], strict=False):
        left_weight = master_weight(left)
        right_weight = master_weight(right)
        if left_weight <= target_weight <= right_weight:
            if target_weight in (left_weight, right_weight):
                return None
            t = (target_weight - left_weight) / (right_weight - left_weight)
            return left, right, t
    return None


def donor_ops_for_master(
    glyph, master, donor_data_by_master_id: dict[str, tuple]
) -> list[tuple[str, tuple]] | None:
    donor_font, cmap, glyphset, _, _ = donor_data_by_master_id[master.id]
    donor_name = find_ttf_glyph(glyph, cmap, glyphset)
    if donor_name is None:
        return None
    return record_glyph(donor_name, glyphset)


def interpolate_ops_between_donors(
    reference_ops: list[tuple[str, tuple]],
    left_ops: list[tuple[str, tuple]],
    right_ops: list[tuple[str, tuple]],
    t: float,
    contour_aware: bool = True,
) -> tuple[list[tuple[str, tuple]] | None, dict[str, object]]:
    left_contours = parse_contours(left_ops)
    right_contours = parse_contours(right_ops)
    reference_contours = parse_contours(reference_ops)

    if (
        contour_aware
        and len(reference_contours) > 1
        and len(reference_contours) == len(left_contours) == len(right_contours)
    ):
        left_mapping = best_ops_contour_mapping(reference_contours, left_contours)
        right_mapping = best_ops_contour_mapping(reference_contours, right_contours)
        if left_mapping is not None and right_mapping is not None:
            transformed_contours: list[list[tuple[str, tuple]]] = []
            contour_transforms: dict[str, dict[str, float]] = {}
            ordered_left = [left_contours[index] for index in left_mapping]
            ordered_right = [right_contours[index] for index in right_mapping]
            for index, (reference_contour, left_contour, right_contour) in enumerate(
                zip(reference_contours, ordered_left, ordered_right, strict=False)
            ):
                left_metrics = ops_metrics(left_contour)
                right_metrics = ops_metrics(right_contour)
                if left_metrics is None or right_metrics is None:
                    continue
                target_center = interpolate_point(
                    tuple(left_metrics["center"]),
                    tuple(right_metrics["center"]),
                    t,
                )
                target_width = interpolate_scalar(
                    float(left_metrics["width"]),
                    float(right_metrics["width"]),
                    t,
                )
                target_height = interpolate_scalar(
                    float(left_metrics["height"]),
                    float(right_metrics["height"]),
                    t,
                )
                target_area = interpolate_scalar(
                    float(left_metrics["area"]),
                    float(right_metrics["area"]),
                    t,
                )
                transformed, metrics = fit_ops_to_metrics(
                    reference_contour,
                    target_center=target_center,
                    target_width=target_width,
                    target_height=target_height,
                    target_area=target_area,
                )
                if transformed is None:
                    continue
                transformed_contours.append(parse_contours(transformed)[0])
                contour_transforms[str(index)] = metrics

            if len(transformed_contours) == len(reference_contours):
                return flatten_contours(transformed_contours), {
                    "mode": "brace_contour_aware",
                    "left_mapping": left_mapping,
                    "right_mapping": right_mapping,
                    "contour_transforms": contour_transforms,
                }

    left_metrics = ops_metrics(left_ops)
    right_metrics = ops_metrics(right_ops)
    if left_metrics is None or right_metrics is None:
        return None, {"mode": "missing_target_metrics"}
    transformed, metrics = fit_ops_to_metrics(
        reference_ops,
        target_center=interpolate_point(
            tuple(left_metrics["center"]),
            tuple(right_metrics["center"]),
            t,
        ),
        target_width=interpolate_scalar(
            float(left_metrics["width"]),
            float(right_metrics["width"]),
            t,
        ),
        target_height=interpolate_scalar(
            float(left_metrics["height"]),
            float(right_metrics["height"]),
            t,
        ),
        target_area=interpolate_scalar(
            float(left_metrics["area"]),
            float(right_metrics["area"]),
            t,
        ),
    )
    return transformed, {"mode": "brace_whole_glyph", "transform": metrics}


def interpolate_compatible_ops(
    left_ops: list[tuple[str, tuple]],
    right_ops: list[tuple[str, tuple]],
    t: float,
) -> list[tuple[str, tuple]] | None:
    if len(left_ops) != len(right_ops):
        return None

    interpolated: list[tuple[str, tuple]] = []
    for (left_op, left_args), (right_op, right_args) in zip(left_ops, right_ops, strict=False):
        if left_op != right_op or len(left_args) != len(right_args):
            return None
        interpolated_args = tuple(
            interpolate_point(
                (float(left_point[0]), float(left_point[1])),
                (float(right_point[0]), float(right_point[1])),
                t,
            )
            for left_point, right_point in zip(left_args, right_args, strict=False)
        )
        interpolated.append((left_op, interpolated_args))
    return interpolated


def brace_layer_id(glyph_name: str, weight: int) -> str:
    safe_name = "".join(character if character.isalnum() else "_" for character in glyph_name)
    return f"VG_BRACE_{safe_name}_{weight}"


def clear_generated_brace_layers(glyph) -> int:
    removable = [
        layer.layerId
        for layer in glyph.layers
        if str(layer.layerId).startswith("VG_BRACE_")
        or layer.userData.get("com.mblode.variable_gen.generated_brace") is True
    ]
    for layer_id in removable:
        del glyph.layers[layer_id]
    return len(removable)


def align_layer_paths_to_reference(reference_layer, layer) -> dict[str, object]:
    reference_paths = list(reference_layer.paths)
    paths = list(layer.paths)
    if not reference_paths or len(paths) != len(reference_paths):
        return {"applied": False, "reason": "path_count_mismatch"}

    mapping = best_path_mapping(reference_paths, paths)
    if mapping is None:
        return {"applied": False, "reason": "mapping_failed"}

    if mapping != list(range(len(paths))):
        reorder_layer_paths(layer, paths, mapping)
        paths = list(layer.paths)

    reversals: list[int] = []
    rotations: dict[str, int] = {}
    for path_index, (reference_path, other_path) in enumerate(
        zip(reference_paths, paths, strict=False)
    ):
        ref_sign = sign(path_signed_area(reference_path))
        other_sign = sign(path_signed_area(other_path))
        if ref_sign != 0 and other_sign != 0 and ref_sign != other_sign:
            other_path.reverse()
            reversals.append(path_index)
        rotation, _used_exact_match = find_rotation(reference_path, other_path)
        if rotation != 0:
            rotate_path_nodes(other_path, rotation)
            rotations[str(path_index)] = rotation

    return {
        "applied": True,
        "mapping": mapping,
        "reversed_paths": reversals,
        "rotations": rotations,
    }


def align_layer_paths_preserving_order(reference_layer, layer) -> dict[str, object]:
    reference_paths = list(reference_layer.paths)
    paths = list(layer.paths)
    if not reference_paths or len(paths) != len(reference_paths):
        return {"applied": False, "reason": "path_count_mismatch"}

    reversals: list[int] = []
    rotations: dict[str, int] = {}
    for path_index, (reference_path, other_path) in enumerate(
        zip(reference_paths, paths, strict=False)
    ):
        ref_sign = sign(path_signed_area(reference_path))
        other_sign = sign(path_signed_area(other_path))
        if ref_sign != 0 and other_sign != 0 and ref_sign != other_sign:
            other_path.reverse()
            reversals.append(path_index)
        rotation, _used_exact_match = find_rotation(reference_path, other_path)
        if rotation != 0:
            rotate_path_nodes(other_path, rotation)
            rotations[str(path_index)] = rotation

    return {
        "applied": True,
        "mapping": list(range(len(paths))),
        "reversed_paths": reversals,
        "rotations": rotations,
    }


def create_or_replace_brace_layer(
    glyph,
    associated_master_id: str,
    weight: int,
    ops: list[tuple[str, tuple]],
    width: int,
) -> dict[str, object]:
    layer_id = brace_layer_id(glyph.name, weight)
    if layer_id in [layer.layerId for layer in glyph.layers]:
        del glyph.layers[layer_id]

    layer = glyphsLib.classes.GSLayer()
    layer.layerId = layer_id
    layer.associatedMasterId = associated_master_id
    layer.attributes["coordinates"] = [int(weight)]
    layer.userData["com.mblode.variable_gen.generated_brace"] = True
    layer.width = int(round(width))
    layer.parent = glyph
    layer.shapes = []
    write_ops_to_layer(ops, layer)
    reference_layer = glyph.layers[associated_master_id]
    alignment = align_layer_paths_to_reference(reference_layer, layer)
    glyph.layers.append(layer)
    return {
        "layer_id": layer_id,
        "weight": int(weight),
        "associated_master_id": associated_master_id,
        "path_count": len(layer.paths),
        "alignment": alignment,
    }


def apply_brace_layers(
    font,
    glyph_name: str,
    reference_master_name: str,
    brace_weights: list[int],
    plan,
    brace_mode: str | None = None,
) -> dict[str, object]:
    glyph = font.glyphs[glyph_name]
    if glyph is None:
        return {"applied": False, "reason": "missing_glyph"}

    ordered_ids, masters_by_name, donor_data_by_master_id = donor_context_for_font(font, plan)
    reference_master = masters_by_name[reference_master_name]
    reference_layer = glyph.layers[reference_master.id]
    reference_ops = layer_to_ops(reference_layer)
    if not reference_ops:
        removed = clear_generated_brace_layers(glyph)
        return {"applied": False, "reason": "reference_has_no_outlines", "removed": removed}

    removed = clear_generated_brace_layers(glyph)
    created: list[dict[str, object]] = []
    skipped: dict[str, str] = {}

    for weight in sorted({int(value) for value in brace_weights}):
        bracket = bracketing_masters_for_weight(font, weight)
        if bracket is None:
            skipped[str(weight)] = "not_between_masters"
            continue
        left_master, right_master, t = bracket
        left_ops = donor_ops_for_master(glyph, left_master, donor_data_by_master_id)
        right_ops = donor_ops_for_master(glyph, right_master, donor_data_by_master_id)
        if not left_ops or not right_ops:
            skipped[str(weight)] = "missing_donor_ops"
            continue

        if brace_mode == "direct_donor_interpolation":
            donor_pair = {"left": left_ops, "right": right_ops}
            normalized = False
            if not verify_cubic_compat(donor_pair):
                donor_pair = normalize_master_ops(donor_pair)
                normalized = True
            if donor_pair is None or not verify_cubic_compat(donor_pair):
                skipped[str(weight)] = "direct_donor_normalization_failed"
                continue
            donor_interpolated_ops = interpolate_compatible_ops(
                donor_pair["left"], donor_pair["right"], t
            )
            if donor_interpolated_ops is None:
                skipped[str(weight)] = "direct_donor_interpolation_failed"
                continue

            reference_contours = parse_contours(reference_ops)
            donor_contours = parse_contours(donor_interpolated_ops)
            if len(reference_contours) != len(donor_contours):
                skipped[str(weight)] = "direct_donor_contour_count_mismatch"
                continue
            mapping = best_ops_contour_mapping(reference_contours, donor_contours)
            if mapping is None:
                skipped[str(weight)] = "direct_donor_mapping_failed"
                continue

            transformed_contours: list[list[tuple[str, tuple]]] = []
            contour_transforms: dict[str, dict[str, float]] = {}
            ordered_donor = [donor_contours[index] for index in mapping]
            for index, (reference_contour, donor_contour) in enumerate(
                zip(reference_contours, ordered_donor, strict=False)
            ):
                donor_metrics = ops_metrics(donor_contour)
                if donor_metrics is None:
                    continue
                transformed, metrics = fit_ops_to_metrics(
                    reference_contour,
                    target_center=tuple(donor_metrics["center"]),
                    target_width=float(donor_metrics["width"]),
                    target_height=float(donor_metrics["height"]),
                    target_area=float(donor_metrics["area"]),
                )
                if transformed is None:
                    continue
                transformed_contours.append(parse_contours(transformed)[0])
                contour_transforms[str(index)] = metrics

            if len(transformed_contours) != len(reference_contours):
                skipped[str(weight)] = "direct_donor_fit_failed"
                continue

            interpolated_ops = flatten_contours(transformed_contours)
            details = {
                "mode": "brace_donor_direct",
                "normalized": normalized,
                "mapping": mapping,
                "contour_transforms": contour_transforms,
            }
        else:
            interpolated_ops, details = interpolate_ops_between_donors(
                reference_ops=reference_ops,
                left_ops=left_ops,
                right_ops=right_ops,
                t=t,
                contour_aware=True,
            )
            if interpolated_ops is None:
                skipped[str(weight)] = "interpolation_failed"
                continue

        left_width = int(glyph.layers[left_master.id].width or 0)
        right_width = int(glyph.layers[right_master.id].width or 0)
        width = interpolate_scalar(left_width, right_width, t)
        record = create_or_replace_brace_layer(
            glyph=glyph,
            associated_master_id=reference_master.id,
            weight=weight,
            ops=interpolated_ops,
            width=int(round(width)),
        )
        record["mode"] = details.get("mode")
        created.append(record)

    result = {
        "applied": bool(created),
        "removed": removed,
        "created": created,
        "skipped": skipped,
    }
    return result


def apply_weighted_fallback(
    font,
    glyph_name: str,
    reference_master_name: str,
    plan,
    contour_aware: bool = True,
) -> dict[str, object]:
    glyph = font.glyphs[glyph_name]
    if glyph is None:
        return {"applied": False, "reason": "missing_glyph"}

    ordered_ids, masters_by_name, donor_data_by_master_id = donor_context_for_font(font, plan)
    reference_master = masters_by_name[reference_master_name]
    reference_layer = glyph.layers[reference_master.id]
    reference_ops = layer_to_ops(reference_layer)
    if not reference_ops:
        return {"applied": False, "reason": "reference_has_no_outlines"}

    applied_masters: dict[str, dict[str, object]] = {}
    skipped_masters: dict[str, str] = {}

    for master in font.masters:
        if master.id == reference_master.id:
            applied_masters[master.name] = {
                "mode": "reference",
                "transform": {
                    "scale_x": 1.0,
                    "scale_y": 1.0,
                    "area_ratio": 1.0,
                    "width_ratio": 1.0,
                    "height_ratio": 1.0,
                },
            }
            continue
        donor_font, cmap, glyphset, _, _ = donor_data_by_master_id[master.id]
        donor_name = find_ttf_glyph(glyph, cmap, glyphset)
        if donor_name is None:
            skipped_masters[master.name] = "missing_donor"
            continue

        donor_ops = record_glyph(donor_name, glyphset)
        if not donor_ops:
            skipped_masters[master.name] = "missing_donor_ops"
            continue

        transformed, transform_details = build_transformed_ops_from_target(
            reference_ops=reference_ops,
            target_ops=donor_ops,
            contour_aware=contour_aware,
        )
        if transformed is None:
            skipped_masters[master.name] = "transform_failed"
            continue

        layer = glyph.layers[master.id]
        layer.shapes = []
        write_ops_to_layer(transformed, layer)
        donor_metrics = ops_metrics(donor_ops) or {}
        transformed_metrics = ops_metrics(transformed) or {}
        area_ratio = None
        if donor_name is not None:
            donor_area = max(glyph_ink_area(donor_font, donor_name), 1.0)
            transformed_area = max(ops_ink_area(transformed), 1.0)
            area_ratio = round(transformed_area / donor_area, 4)

        applied_masters[master.name] = {
            "mode": transform_details.get("mode"),
            "transform": transform_details,
            "target_metrics": {
                "center": donor_metrics.get("center"),
                "width": donor_metrics.get("width"),
                "height": donor_metrics.get("height"),
                "area": donor_metrics.get("area"),
            },
            "result_metrics": {
                "center": transformed_metrics.get("center"),
                "width": transformed_metrics.get("width"),
                "height": transformed_metrics.get("height"),
                "area": transformed_metrics.get("area"),
            },
            "result_area_vs_donor": area_ratio,
        }

    return {
        "applied": True,
        "reference_master": reference_master.name,
        "reference_master_preserved": True,
        "masters_updated": sorted(applied_masters),
        "contour_aware": contour_aware,
        "transforms": applied_masters,
        "skipped_masters": skipped_masters,
    }


def scale_ops(
    ops: list[tuple[str, tuple]],
    upm_scale: float,
) -> list[tuple[str, tuple]]:
    if upm_scale == 1.0:
        return list(ops)

    scaled: list[tuple[str, tuple]] = []
    for op, args in ops:
        scaled_args = tuple(tuple(float(value) * upm_scale for value in point) for point in args)
        scaled.append((op, scaled_args))
    return scaled


def apply_donor_copy(font, glyph_name: str, plan) -> dict[str, object]:
    glyph = font.glyphs[glyph_name]
    if glyph is None:
        return {"applied": False, "reason": "missing_glyph"}

    glide_upm = int(getattr(font, "upm", None) or 1000)
    donor_master_ops: dict[str, list[tuple[str, tuple]]] = {}
    donor_widths: dict[str, float] = {}
    donor_names_by_master: dict[str, str] = {}
    donor_compat = True

    for master_name, donor_path in plan.donor_paths_by_master_name.items():
        master = next((item for item in font.masters if item.name == master_name), None)
        if master is None:
            continue
        donor_font, cmap, glyphset, donor_upm = load_ttf(donor_path)
        donor_name = find_ttf_glyph(glyph, cmap, glyphset)
        if donor_name is None:
            return {
                "applied": False,
                "reason": "missing_donor_glyph",
                "master": master_name,
            }
        donor_ops = record_glyph(donor_name, glyphset)
        if not donor_ops:
            return {
                "applied": False,
                "reason": "missing_donor_ops",
                "master": master_name,
            }
        donor_names_by_master[master_name] = donor_name
        donor_master_ops[master.id] = donor_ops
        donor_widths[master.id] = glyphset[donor_name].width * (glide_upm / donor_upm)

    if len(donor_master_ops) < 2:
        return {"applied": False, "reason": "insufficient_donor_masters"}

    donor_compat = verify_cubic_compat(donor_master_ops)
    donor_ops_to_write = donor_master_ops
    if not donor_compat:
        donor_ops_to_write = normalize_master_ops(donor_master_ops)
        if donor_ops_to_write is None:
            return {
                "applied": False,
                "reason": "donor_normalization_failed",
                "donor_raw_compat": donor_compat,
            }

    masters_updated: list[str] = []
    for master in font.masters:
        ops = donor_ops_to_write.get(master.id)
        if ops is None:
            continue
        layer = glyph.layers[master.id]
        layer.shapes = []
        write_ops_to_layer(ops, layer)
        layer.width = int(round(donor_widths[master.id]))
        masters_updated.append(master.name)

    return {
        "applied": bool(masters_updated),
        "strategy": "donor_copy",
        "donor_raw_compat": donor_compat,
        "donor_names_by_master": donor_names_by_master,
        "masters_updated": masters_updated,
        "normalized_donor_copy": not donor_compat,
    }


def apply_structural_fallback(
    font, glyph_name: str, reference_master_name: str, plan
) -> dict[str, object]:
    result = apply_weighted_fallback(
        font,
        glyph_name=glyph_name,
        reference_master_name=reference_master_name,
        plan=plan,
        contour_aware=False,
    )
    result["strategy"] = "structural_fallback"
    return result


def flatten_contours(contours: list[list[tuple[str, tuple]]]) -> list[tuple[str, tuple]]:
    return [op for contour in contours for op in contour]


def apply_source_path_order_overrides(
    font,
    glyph_name: str,
    overrides: dict[str, list[int]],
) -> dict[str, object]:
    glyph = font.glyphs[glyph_name]
    if glyph is None:
        return {"applied": False, "reason": "missing_glyph"}

    masters_by_name = {master.name: master for master in font.masters}
    masters_by_id = {master.id: master for master in font.masters}
    reference_master = font.masters[0]
    reference_layer = glyph.layers[reference_master.id]
    reference_paths = list(reference_layer.paths)
    applied: dict[str, list[int]] = {}
    path_alignment: dict[str, dict[str, object]] = {}
    skipped: dict[str, str] = {}

    for master_key, raw_mapping in (overrides or {}).items():
        master = masters_by_name.get(master_key) or masters_by_id.get(master_key)
        if master is None:
            skipped[str(master_key)] = "missing_master"
            continue

        layer = glyph.layers[master.id]
        paths = list(layer.paths)
        mapping = [int(index) for index in raw_mapping]
        expected = list(range(len(paths)))
        if len(mapping) != len(paths):
            skipped[master.name] = "mapping_length_mismatch"
            continue
        if sorted(mapping) != expected:
            skipped[master.name] = "invalid_mapping"
            continue
        if mapping == expected:
            skipped[master.name] = "identity_mapping"
            continue

        reorder_layer_paths(layer, paths, mapping)
        applied[master.name] = mapping
        path_alignment[master.name] = align_layer_paths_preserving_order(reference_layer, layer)

    return {
        "applied": bool(applied),
        "glyph_name": glyph_name,
        "overrides": applied,
        "path_alignment": path_alignment,
        "skipped": skipped,
    }


def apply_localized_substitution(
    font,
    glyph_name: str,
    reference_master_name: str,
    contour_indices: list[int] | None,
) -> dict[str, object]:
    glyph = font.glyphs[glyph_name]
    if glyph is None:
        return {"applied": False, "reason": "missing_glyph"}

    masters_by_name = {master.name: master for master in font.masters}
    reference_master = masters_by_name[reference_master_name]
    reference_layer = glyph.layers[reference_master.id]
    reference_ops = layer_to_ops(reference_layer)
    if not reference_ops:
        return {"applied": False, "reason": "reference_has_no_outlines"}

    reference_contours = parse_contours(reference_ops)
    if not reference_contours:
        return {"applied": False, "reason": "reference_has_no_contours"}

    if not contour_indices:
        contour_indices = list(range(len(reference_contours)))
    contour_index_set = {
        int(index) for index in contour_indices if 0 <= int(index) < len(reference_contours)
    }
    if not contour_index_set:
        return {"applied": False, "reason": "no_valid_contours"}

    if contour_index_set == set(range(len(reference_contours))):
        return apply_reference_fallback(font, glyph_name, reference_master_name)

    applied_masters: list[str] = []
    skipped_masters: dict[str, str] = {}
    for master in font.masters:
        if master.id == reference_master.id:
            continue
        layer = glyph.layers[master.id]
        layer_ops = layer_to_ops(layer)
        if not layer_ops:
            skipped_masters[master.name] = "target_has_no_outlines"
            continue
        target_contours = parse_contours(layer_ops)
        if len(target_contours) != len(reference_contours):
            skipped_masters[master.name] = "contour_count_mismatch"
            continue

        merged_contours: list[list[tuple[str, tuple]]] = []
        for index, target_contour in enumerate(target_contours):
            if index in contour_index_set:
                merged_contours.append(list(reference_contours[index]))
            else:
                merged_contours.append(list(target_contour))

        layer.shapes = []
        write_ops_to_layer(flatten_contours(merged_contours), layer)
        applied_masters.append(master.name)

    return {
        "applied": True,
        "reference_master": reference_master.name,
        "contour_indices": sorted(contour_index_set),
        "masters_updated": applied_masters,
        "skipped_masters": skipped_masters,
    }


def apply_inherit_base_contours(font, glyph_name: str, base_glyph_name: str) -> dict[str, object]:
    glyph = font.glyphs[glyph_name]
    if glyph is None:
        return {"applied": False, "reason": "missing_glyph"}

    base_glyph = font.glyphs[base_glyph_name]
    if base_glyph is None:
        return {"applied": False, "reason": "missing_base_glyph", "base_glyph": base_glyph_name}

    if glyph.name == base_glyph.name:
        return {
            "applied": False,
            "reason": "base_matches_target",
            "base_glyph": base_glyph_name,
        }

    masters_updated: list[str] = []
    contour_mappings: dict[str, list[int]] = {}
    skipped_masters: dict[str, str] = {}

    for master in font.masters:
        glyph_layer = glyph.layers[master.id]
        glyph_ops = layer_to_ops(glyph_layer)
        if not glyph_ops:
            skipped_masters[master.name] = "target_has_no_outlines"
            continue

        base_layer = base_glyph.layers[master.id]
        base_ops = layer_to_ops(base_layer)
        if not base_ops:
            skipped_masters[master.name] = "base_has_no_outlines"
            continue

        glyph_contours = parse_contours(glyph_ops)
        base_contours = parse_contours(base_ops)
        if len(glyph_contours) <= len(base_contours):
            skipped_masters[master.name] = "no_extra_target_contours"
            continue
        mapping = best_ops_contour_subset_mapping(base_contours, glyph_contours)
        if mapping is None:
            skipped_masters[master.name] = "contour_subset_mapping_failed"
            continue

        merged_contours = [list(contour) for contour in glyph_contours]
        for base_index, glyph_index in enumerate(mapping):
            merged_contours[glyph_index] = list(base_contours[base_index])

        glyph_layer.shapes = []
        write_ops_to_layer(flatten_contours(merged_contours), glyph_layer)
        masters_updated.append(master.name)
        contour_mappings[master.name] = mapping

    return {
        "applied": bool(masters_updated),
        "strategy": "inherit_base_contours",
        "base_glyph": base_glyph_name,
        "masters_updated": masters_updated,
        "contour_mappings": contour_mappings,
        "skipped_masters": skipped_masters,
    }


def normalize_winding(font) -> dict[str, object]:
    flips = 0
    mismatches: list[dict[str, object]] = []

    for glyph in font.glyphs:
        layers = master_layers_for_glyph(font, glyph.name)
        ordered_layers = [layers[master.id] for master in font.masters if master.id in layers]
        if len(ordered_layers) < 2:
            continue
        ref_paths = list(ordered_layers[0].paths)
        if not ref_paths:
            continue

        for master, other_layer in zip(font.masters[1:], ordered_layers[1:], strict=False):
            other_paths = list(other_layer.paths)
            if len(other_paths) != len(ref_paths):
                continue
            mapping = best_path_mapping(ref_paths, other_paths)
            ordered_other_paths = [other_paths[index] for index in mapping]

            for path_index, (ref_path, other_path) in enumerate(
                zip(ref_paths, ordered_other_paths, strict=False)
            ):
                ref_sign = sign(path_signed_area(ref_path))
                other_sign = sign(path_signed_area(other_path))
                if ref_sign == 0 or other_sign == 0 or ref_sign == other_sign:
                    continue
                other_path.reverse()
                flips += 1
                mismatches.append(
                    {
                        "glyph": glyph.name,
                        "master": master.name,
                        "path_index": path_index,
                    }
                )

    return {"flips": flips, "examples": mismatches[:50]}


def audit_direction_issues(font) -> dict[str, int]:
    counts: Counter[str] = Counter()

    for glyph in font.glyphs:
        layers = master_layers_for_glyph(font, glyph.name)
        ordered_layers = [layers[master.id] for master in font.masters if master.id in layers]
        if len(ordered_layers) < 2:
            continue
        ref_paths = list(ordered_layers[0].paths)
        if not ref_paths:
            continue

        for other_layer in ordered_layers[1:]:
            other_paths = list(other_layer.paths)
            if len(other_paths) != len(ref_paths):
                continue
            mapping = best_path_mapping(ref_paths, other_paths)
            ordered_other_paths = [other_paths[index] for index in mapping]

            for ref_path, other_path in zip(ref_paths, ordered_other_paths, strict=False):
                ref_sign = sign(path_signed_area(ref_path))
                other_sign = sign(path_signed_area(other_path))
                if ref_sign == 0 or other_sign == 0 or ref_sign == other_sign:
                    continue
                counts[glyph.name] += 1

    return dict(counts)


def source_segment_counts(layer) -> list[int]:
    ops = layer_to_ops(layer)
    if not ops:
        return []
    return [count_segments(contour) for contour in parse_contours(ops)]


def source_node_counts(layer) -> list[int]:
    return [len(path.nodes) for path in layer.paths]


def donor_context_for_font(font, plan) -> tuple[list[str], dict[str, object], dict[str, tuple]]:
    ordered_ids, masters_by_name = ordered_master_ids(font, plan.reference_master_name)
    donor_data_by_master_id: dict[str, tuple] = {}
    for master_name, donor_path in plan.donor_paths_by_master_name.items():
        master = masters_by_name[master_name]
        donor_data_by_master_id[master.id] = (*load_ttf(donor_path), donor_path)
    return ordered_ids, masters_by_name, donor_data_by_master_id


def source_direction_signs(layer) -> list[int]:
    return [sign(path_signed_area(path)) for path in layer.paths]


def outline_signature(layer) -> tuple[tuple[tuple[float, float, str, bool], ...], ...]:
    signature: list[tuple[tuple[float, float, str, bool], ...]] = []
    for path in layer.paths:
        nodes = []
        for node in path.nodes:
            nodes.append(
                (
                    round(float(node.position.x), 3),
                    round(float(node.position.y), 3),
                    str(node.type),
                    bool(getattr(node, "smooth", False)),
                )
            )
        signature.append(tuple(nodes))
    return tuple(signature)


def generated_brace_coordinates(glyph) -> list[int]:
    coordinates: list[int] = []
    for layer in glyph.layers:
        if not (
            str(layer.layerId).startswith("VG_BRACE_")
            or layer.userData.get("com.mblode.variable_gen.generated_brace") is True
        ):
            continue
        raw_coordinates = layer.attributes.get("coordinates") or []
        if not raw_coordinates:
            continue
        try:
            coordinates.append(int(raw_coordinates[0]))
        except Exception:
            continue
    return sorted(set(coordinates))


def classify_glyph(
    glyph_name: str,
    strategy: str,
    source_has_outlines: bool,
    donor_raw_compat: bool | None,
    contour_count_mismatch: bool,
    total_segment_delta: int,
) -> str:
    if strategy == "rebuild_notdef":
        return "rebuild_notdef"
    if strategy in {"reference_fallback", "freeze_to_reference"}:
        return "reference_fallback"
    if strategy == "donor_copy":
        return "donor_copy"
    if strategy == "structural_fallback":
        return "structural_fallback"
    if strategy == "weighted_fallback":
        return "weighted_fallback"
    if strategy == "inherit_base_contours":
        return "inherit_base_contours"
    if not source_has_outlines:
        return "metrics_only"
    if strategy == "manual_review":
        return "manual_review"
    if donor_raw_compat is True and total_segment_delta == 0 and not contour_count_mismatch:
        return "clean"
    return "normalized"


def risk_score(
    strategy: str,
    donor_raw_compat: bool | None,
    contour_count_mismatch: bool,
    total_segment_delta: int,
    source_has_outlines: bool,
    same_outline_across_masters: bool,
) -> int:
    score = 0
    if not source_has_outlines:
        score += 20
    if strategy in {"reference_fallback", "freeze_to_reference"}:
        score += 15
    if strategy == "donor_copy":
        score += 11
    if strategy == "structural_fallback":
        score += 13
    if strategy == "weighted_fallback":
        score += 12
    if strategy == "inherit_base_contours":
        score += 10
    if strategy == "rebuild_notdef":
        score += 12
    if strategy == "manual_review":
        score += 8
    if donor_raw_compat is False:
        score += 6
    if contour_count_mismatch:
        score += 6
    if same_outline_across_masters:
        score += 12
    score += total_segment_delta
    return score


def build_family_source_report(
    family_key: str,
    font,
    plan,
    glyph_configs: dict[str, dict[str, object]],
    report_dir: Path,
) -> Path:
    ordered_ids, _, donor_data_by_master_id = donor_context_for_font(font, plan)
    strict_audit = strict_audit_font(font)
    path_order_index: Counter[str] = Counter(
        glyph_name for glyph_name, _, _ in strict_audit["path_order_issues"]
    )
    node_count_index: Counter[str] = Counter(
        glyph_name for glyph_name, _, _, _, _ in strict_audit["node_count_issues"]
    )
    start_index: Counter[str] = Counter(
        glyph_name for glyph_name, _, _, _, _ in strict_audit["start_issues"]
    )
    direction_index = audit_direction_issues(font)
    import_report_path = report_dir.parent / f"circular-{family_key}-glyphs-report.json"
    import_index: dict[str, dict[str, object]] = {}
    if import_report_path.exists():
        import_payload = json.loads(import_report_path.read_text())
        import_index = {entry["glyph_name"]: entry for entry in import_payload["glyphs"]}

    entries: list[dict[str, object]] = []
    family_strategies = glyph_configs

    for glyph in font.glyphs:
        layers = master_layers_for_glyph(font, glyph.name)
        source_master_ops = {
            master.id: layer_to_ops(layers[master.id])
            for master in font.masters
            if master.id in layers and layer_to_ops(layers[master.id])
        }
        source_has_outlines = bool(source_master_ops)

        donor_structs: dict[str, list[int] | None] = {}
        donor_segment_map: dict[str, list[int]] = {}
        donor_raw_ops: dict[str, list] = {}

        for master in font.masters:
            donor_font, cmap, glyphset, donor_upm, donor_path = donor_data_by_master_id[master.id]
            donor_name = find_ttf_glyph(glyph, cmap, glyphset)
            if donor_name is None:
                donor_structs[master.name] = None
                donor_segment_map[master.name] = []
                continue
            donor_struct = effective_structure(donor_name, glyphset)
            donor_structs[master.name] = list(donor_struct) if donor_struct is not None else None
            donor_ops = record_glyph(donor_name, glyphset)
            if donor_ops:
                donor_raw_ops[master.id] = donor_ops
                donor_segment_map[master.name] = [
                    count_segments(contour) for contour in parse_contours(donor_ops)
                ]
            else:
                donor_segment_map[master.name] = []

        donor_raw_compat = verify_cubic_compat(donor_raw_ops) if len(donor_raw_ops) > 1 else None
        valid_structs = [tuple(struct) for struct in donor_structs.values() if struct is not None]
        contour_count_mismatch = len({len(struct) for struct in valid_structs}) > 1

        source_segment_map = {
            master.name: source_segment_counts(layers[master.id]) if master.id in layers else []
            for master in font.masters
        }
        source_node_map = {
            master.name: source_node_counts(layers[master.id]) if master.id in layers else []
            for master in font.masters
        }
        source_direction_map = {
            master.name: source_direction_signs(layers[master.id]) if master.id in layers else []
            for master in font.masters
        }
        outline_signatures = [
            outline_signature(layers[master.id])
            for master in font.masters
            if master.id in layers and layer_to_ops(layers[master.id])
        ]
        same_outline_across_masters = (
            len(outline_signatures) > 1 and len(set(outline_signatures)) == 1
        )

        segment_delta_by_master: dict[str, list[int] | None] = {}
        total_segment_delta = 0
        for master in font.masters:
            donor_segments = donor_segment_map.get(master.name, [])
            source_segments = source_segment_map.get(master.name, [])
            if len(donor_segments) != len(source_segments):
                segment_delta_by_master[master.name] = None
                continue
            deltas = [
                source - donor
                for donor, source in zip(donor_segments, source_segments, strict=False)
            ]
            segment_delta_by_master[master.name] = deltas
            total_segment_delta += sum(abs(delta) for delta in deltas)

        strategy = family_strategies.get(glyph.name, {}).get("strategy", "normalize")
        brace_coordinates = generated_brace_coordinates(glyph)
        classification = classify_glyph(
            glyph_name=glyph.name,
            strategy=strategy,
            source_has_outlines=source_has_outlines,
            donor_raw_compat=donor_raw_compat,
            contour_count_mismatch=contour_count_mismatch,
            total_segment_delta=total_segment_delta,
        )
        score = risk_score(
            strategy=strategy,
            donor_raw_compat=donor_raw_compat,
            contour_count_mismatch=contour_count_mismatch,
            total_segment_delta=total_segment_delta,
            source_has_outlines=source_has_outlines,
            same_outline_across_masters=same_outline_across_masters,
        )

        import_entry = import_index.get(glyph.name, {})
        glyph_config = family_strategies.get(glyph.name, {})
        has_source_path_override = bool(glyph_config.get("source_path_order_overrides"))
        entries.append(
            {
                "glyph_name": glyph.name,
                "strategy": strategy,
                "priority": glyph_config.get("priority"),
                "repair_bucket": glyph_config.get("repair_bucket"),
                "notes": glyph_config.get("notes"),
                "group_name": glyph_config.get("group_name"),
                "inherits_from": glyph_config.get("inherits_from"),
                "requested_brace_weights": glyph_config.get("brace_weights"),
                "generated_brace_weights": brace_coordinates,
                "generated_brace_count": len(brace_coordinates),
                "classification": classification,
                "risk_score": score,
                "import_status": import_entry.get("status"),
                "donor_raw_compat": donor_raw_compat,
                "contour_count_mismatch": contour_count_mismatch,
                "total_segment_delta": total_segment_delta,
                "same_outline_across_masters": same_outline_across_masters,
                "segment_delta_by_master": segment_delta_by_master,
                "donor_structs": donor_structs,
                "donor_segment_counts": donor_segment_map,
                "source_segment_counts": source_segment_map,
                "source_node_counts": source_node_map,
                "source_direction_signs": source_direction_map,
                "source_path_order_issues": 0
                if has_source_path_override
                else path_order_index.get(glyph.name, 0),
                "source_node_count_issues": node_count_index.get(glyph.name, 0),
                "source_start_issues": 0
                if has_source_path_override
                else start_index.get(glyph.name, 0),
                "source_direction_issues": 0
                if has_source_path_override
                else direction_index.get(glyph.name, 0),
                "source_path_order_override_applied": has_source_path_override,
            }
        )

    class_counts = Counter(entry["classification"] for entry in entries)
    top_risk = sorted(entries, key=lambda entry: (-entry["risk_score"], entry["glyph_name"]))[:50]
    report_payload = {
        "family": family_key,
        "source": str(FONT_PLANS[family_key].source_path),
        "summary": {
            "glyph_count": len(entries),
            "classification_counts": dict(class_counts),
            "glyphs_with_generated_brace_layers": sum(
                1 for entry in entries if entry["generated_brace_count"] > 0
            ),
            "top_risk_glyphs": [
                {
                    "glyph_name": entry["glyph_name"],
                    "classification": entry["classification"],
                    "risk_score": entry["risk_score"],
                    "strategy": entry["strategy"],
                    "total_segment_delta": entry["total_segment_delta"],
                    "donor_raw_compat": entry["donor_raw_compat"],
                    "same_outline_across_masters": entry["same_outline_across_masters"],
                }
                for entry in top_risk
            ],
        },
        "glyphs": entries,
    }

    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{family_key}-source-report.json"
    report_path.write_text(json.dumps(report_payload, indent=2))
    return report_path


def json_safe(value):
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except Exception:
            pass
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def run_interpolatable_designspace(designspace_path: Path, report_path: Path) -> dict[str, object]:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in (".stdout.txt", ".stderr.txt"):
        stale = report_path.with_suffix(suffix)
        if stale.exists():
            stale.unlink()
    designspace = DesignSpaceDocument.fromfile(str(designspace_path))
    source_paths = []
    for source in designspace.sources:
        if source.path:
            source_paths.append(str(Path(source.path).resolve()))
        elif source.filename:
            source_paths.append(str((designspace_path.parent / source.filename).resolve()))

    problems = interpolatable.main([*source_paths, "--quiet"])
    payload = json_safe(problems)
    report_path.write_text(json.dumps(payload, indent=2))
    issue_counts = Counter()
    for issues in payload.values():
        for issue in issues:
            issue_counts[str(issue.get("type", "unknown"))] += 1
    return {"problem_glyphs": len(payload), "issue_types": dict(issue_counts)}


def _ufo_contour_signature(contour) -> tuple[str, ...]:
    return tuple(str(point.segmentType or "offcurve") for point in contour)


def _ufo_canonical_contour_signature(contour) -> tuple[str, ...]:
    signature = list(_ufo_contour_signature(contour))
    if not signature:
        return ()
    count = len(signature)
    forward = {tuple(signature[index:] + signature[:index]) for index in range(count)}
    reverse_sig = signature[::-1]
    reverse = {tuple(reverse_sig[index:] + reverse_sig[:index]) for index in range(count)}
    return min(forward | reverse)


def _ufo_contour_centroid(contour) -> tuple[float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for point in contour:
        if point.segmentType is None:
            continue
        xs.append(point.x)
        ys.append(point.y)
    if not xs:
        return (0.0, 0.0)
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _ufo_contour_bbox(contour) -> tuple[float, float, float, float]:
    xs = [point.x for point in contour]
    ys = [point.y for point in contour]
    return (min(xs), min(ys), max(xs), max(ys))


def _ufo_dist_sq(a: tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _best_ufo_contour_mapping(reference_contours, other_contours) -> list[int]:
    count = len(reference_contours)
    if count <= 1:
        return list(range(count))

    reference_signatures = [
        _ufo_canonical_contour_signature(contour) for contour in reference_contours
    ]
    other_signatures = [_ufo_canonical_contour_signature(contour) for contour in other_contours]

    reference_centroids = [_ufo_contour_centroid(contour) for contour in reference_contours]
    other_centroids = [_ufo_contour_centroid(contour) for contour in other_contours]
    reference_bboxes = [_ufo_contour_bbox(contour) for contour in reference_contours]
    other_bboxes = [_ufo_contour_bbox(contour) for contour in other_contours]

    costs = [[0.0] * count for _ in range(count)]
    for reference_index in range(count):
        reference_bbox = reference_bboxes[reference_index]
        reference_width = reference_bbox[2] - reference_bbox[0]
        reference_height = reference_bbox[3] - reference_bbox[1]
        reference_scale = max(reference_width * reference_height, 1.0)

        for other_index in range(count):
            penalty = 0.0
            if reference_signatures[reference_index] != other_signatures[other_index]:
                penalty = 1_000_000.0
            other_bbox = other_bboxes[other_index]
            centroid_cost = (
                _ufo_dist_sq(
                    reference_centroids[reference_index],
                    other_centroids[other_index],
                )
                / reference_scale
            )
            size_cost = abs(reference_width - (other_bbox[2] - other_bbox[0]))
            size_cost += abs(reference_height - (other_bbox[3] - other_bbox[1]))
            costs[reference_index][other_index] = penalty + centroid_cost + size_cost

    @lru_cache(None)
    def solve(reference_index: int, used_mask: int) -> tuple[float, tuple[int, ...]]:
        if reference_index == count:
            return (0.0, ())

        best_score = float("inf")
        best_mapping: tuple[int, ...] = ()
        for other_index in range(count):
            if used_mask & (1 << other_index):
                continue
            sub_score, sub_mapping = solve(reference_index + 1, used_mask | (1 << other_index))
            score = costs[reference_index][other_index] + sub_score
            if score < best_score:
                best_score = score
                best_mapping = (other_index,) + sub_mapping
        return (best_score, best_mapping)

    return list(solve(0, 0)[1])


def _reorder_ufo_glyph_contours(glyph, mapping: list[int]) -> bool:
    expected = list(range(len(mapping)))
    if mapping == expected:
        return False
    contours = list(glyph)
    glyph.clearContours()
    for contour_index in mapping:
        glyph.appendContour(contours[contour_index])
    return True


def _designspace_source_paths(designspace_path: Path) -> list[Path]:
    designspace = DesignSpaceDocument.fromfile(str(designspace_path))
    source_paths: list[Path] = []
    for source in designspace.sources:
        if source.path:
            source_paths.append(Path(source.path).resolve())
        elif source.filename:
            source_paths.append((designspace_path.parent / source.filename).resolve())
    return source_paths


def _generic_unicode_glyph_name(glyph_name: str, codepoint: int) -> bool:
    upper_name = glyph_name.upper()
    return upper_name in {
        f"UNI{codepoint:04X}",
        f"U{codepoint:04X}",
        f"U{codepoint:06X}",
    }


def _preferred_unicode_owner(codepoint: int, glyph_names: list[str]) -> str:
    return min(
        glyph_names,
        key=lambda glyph_name: (
            _generic_unicode_glyph_name(glyph_name, codepoint),
            "." in glyph_name,
            len(glyph_name),
            glyph_name,
        ),
    )


def clear_duplicate_ufo_unicodes(designspace_path: Path) -> int:
    cleared = 0
    for source_path in _designspace_source_paths(designspace_path):
        font = ufoLib2.Font.open(source_path)
        owners_by_codepoint: dict[int, list[str]] = {}
        for glyph_name in font.keys():
            glyph = font[glyph_name]
            for codepoint in getattr(glyph, "unicodes", []) or []:
                owners_by_codepoint.setdefault(int(codepoint), []).append(glyph_name)

        duplicate_owners = {
            codepoint: glyph_names
            for codepoint, glyph_names in owners_by_codepoint.items()
            if len(glyph_names) > 1
        }
        if not duplicate_owners:
            continue

        for codepoint, glyph_names in duplicate_owners.items():
            keep = _preferred_unicode_owner(codepoint, glyph_names)
            for glyph_name in glyph_names:
                if glyph_name == keep:
                    continue
                glyph = font[glyph_name]
                glyph.unicodes = [value for value in glyph.unicodes if int(value) != codepoint]
                cleared += 1

        font.save(source_path, overwrite=True)
    return cleared


def normalize_designspace_ufo_contour_order(designspace_path: Path) -> int:
    source_paths = _designspace_source_paths(designspace_path)

    if len(source_paths) < 2:
        return 0

    reference_font = ufoLib2.Font.open(source_paths[0])
    other_fonts = [(path, ufoLib2.Font.open(path)) for path in source_paths[1:]]
    changed_paths: set[Path] = set()
    reordered_glyphs = 0

    reference_glyph_names = set(reference_font.keys())
    common_glyph_names = set(reference_glyph_names)
    for _, font in other_fonts:
        common_glyph_names &= set(font.keys())

    for glyph_name in sorted(common_glyph_names):
        reference_glyph = reference_font[glyph_name]
        reference_contours = list(reference_glyph)
        if len(reference_contours) <= 1:
            continue

        for path, font in other_fonts:
            glyph = font[glyph_name]
            contours = list(glyph)
            if len(contours) != len(reference_contours) or len(contours) <= 1:
                continue
            mapping = _best_ufo_contour_mapping(reference_contours, contours)
            if _reorder_ufo_glyph_contours(glyph, mapping):
                changed_paths.add(path)
                reordered_glyphs += 1

    for path, font in other_fonts:
        if path in changed_paths:
            font.save(path, overwrite=True)

    return reordered_glyphs


def _command_output_log_paths(output_path: Path) -> tuple[Path, Path]:
    return output_path.with_suffix(".stdout.txt"), output_path.with_suffix(".stderr.txt")


def _tail_text(text: str | None, *, max_lines: int = 40, max_chars: int = 8000) -> str:
    if not text:
        return "(empty)"
    tail = "\n".join(text.splitlines()[-max_lines:])
    if len(tail) <= max_chars:
        return tail
    clipped = tail[-max_chars:]
    first_newline = clipped.find("\n")
    if first_newline == -1:
        return clipped
    return clipped[first_newline + 1 :]


def _write_failed_command_output(
    output_path: Path, error: subprocess.CalledProcessError
) -> tuple[Path, Path] | None:
    stdout_path, stderr_path = _command_output_log_paths(output_path)
    try:
        stdout_path.write_text(error.stdout or "")
        stderr_path.write_text(error.stderr or "")
    except OSError as write_error:
        print(
            f"Could not write fontmake stdout/stderr logs next to {output_path}: {write_error}",
            file=sys.stderr,
        )
        return None
    return stdout_path, stderr_path


def build_variable_font(designspace_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    normalize_designspace_ufo_contour_order(designspace_path)
    cleared_unicodes = clear_duplicate_ufo_unicodes(designspace_path)
    if cleared_unicodes:
        print(f"Cleared duplicate UFO unicode mappings: {cleared_unicodes}")
    command = [
        str(REPO_ROOT / ".venv/bin/fontmake"),
        "-m",
        str(designspace_path),
        "-o",
        "variable",
        "--keep-overlaps",
        "--output-path",
        str(output_path),
        "--no-check-compatibility",
    ]
    try:
        subprocess.run(command, cwd=REPO_ROOT, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        log_paths = _write_failed_command_output(output_path, error)
        command_text = shlex.join(command)
        print(f"fontmake failed while building {output_path}", file=sys.stderr)
        print(f"Command: {command_text}", file=sys.stderr)
        if log_paths:
            stdout_path, stderr_path = log_paths
            print(f"stdout log: {stdout_path}", file=sys.stderr)
            print(f"stderr log: {stderr_path}", file=sys.stderr)
        print("stderr tail:", file=sys.stderr)
        print(_tail_text(error.stderr), file=sys.stderr)
        print("stdout tail:", file=sys.stderr)
        print(_tail_text(error.stdout), file=sys.stderr)

        note = f"fontmake failed for {designspace_path} -> {output_path}; command: {command_text}"
        if log_paths:
            stdout_path, stderr_path = log_paths
            note = f"{note}; stdout: {stdout_path}; stderr: {stderr_path}"
        error.add_note(note)
        raise
    return output_path


def sample_weights(family_manifest: dict[str, object], font) -> list[int]:
    manifest_weights = family_manifest.get("sample_weights")
    if manifest_weights:
        return [int(weight) for weight in manifest_weights]
    weights = sorted(
        int(master.axes[0]) for master in font.masters if getattr(master, "axes", None)
    )
    samples = set(weights)
    for left, right in zip(weights, weights[1:], strict=False):
        samples.add(int(round((left + right) * 0.5)))
    return sorted(samples)


def generate_static_samples(
    variable_font_path: Path, weights: list[int], output_dir: Path
) -> dict[int, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: dict[int, Path] = {}
    for weight in weights:
        varfont = TTFont(variable_font_path)
        static_font = instantiateVariableFont(varfont, {"wght": weight})
        output_path = output_dir / f"{variable_font_path.stem}-wght{weight}.ttf"
        static_font.save(output_path)
        generated[weight] = output_path
    return generated


def compare_fonts(
    instance_path: Path, donor_path: Path, glyph_subset: set[str] | None = None
) -> dict[str, object]:
    instance_font = TTFont(instance_path)
    donor_font = TTFont(donor_path)
    common = set(instance_font.getGlyphOrder()) & set(donor_font.getGlyphOrder())
    if glyph_subset is not None:
        common &= glyph_subset
    deviations: dict[str, float] = {}
    area_diffs: dict[str, float] = {}
    mismatched_points = 0
    for glyph_name in sorted(common):
        if glyph_name == ".notdef":
            continue
        deviation = glyph_point_deviation(instance_font, donor_font, glyph_name)
        if deviation is None:
            mismatched_points += 1
        elif deviation > 0.5:
            deviations[glyph_name] = round(deviation, 2)

        donor_area = glyph_ink_area(donor_font, glyph_name)
        if donor_area <= 0:
            continue
        instance_area = glyph_ink_area(instance_font, glyph_name)
        diff_pct = abs(instance_area - donor_area) / donor_area * 100
        if diff_pct > 1.0:
            area_diffs[glyph_name] = round(diff_pct, 2)

    return {
        "common_glyphs": len(common),
        "mismatched_point_count": mismatched_points,
        "glyphs_with_deviation": len(deviations),
        "glyphs_with_area_diff_pct": len(area_diffs),
        "worst_deviations": dict(
            sorted(deviations.items(), key=lambda item: item[1], reverse=True)[:20]
        ),
        "worst_area_diffs_pct": dict(
            sorted(area_diffs.items(), key=lambda item: item[1], reverse=True)[:20]
        ),
    }


def sample_quadratic(
    p0: tuple[float, float], p1: tuple[float, float], p2: tuple[float, float], steps: int
) -> list[tuple[float, float]]:
    points = []
    for step in range(1, steps + 1):
        t = step / steps
        mt = 1.0 - t
        x = (mt * mt * p0[0]) + (2.0 * mt * t * p1[0]) + (t * t * p2[0])
        y = (mt * mt * p0[1]) + (2.0 * mt * t * p1[1]) + (t * t * p2[1])
        points.append((x, y))
    return points


def sample_cubic(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    steps: int,
) -> list[tuple[float, float]]:
    points = []
    for step in range(1, steps + 1):
        t = step / steps
        mt = 1.0 - t
        x = (mt**3) * p0[0] + 3 * (mt**2) * t * p1[0] + 3 * mt * (t**2) * p2[0] + (t**3) * p3[0]
        y = (mt**3) * p0[1] + 3 * (mt**2) * t * p1[1] + 3 * mt * (t**2) * p2[1] + (t**3) * p3[1]
        points.append((x, y))
    return points


def glyph_polylines(
    font: TTFont, glyph_name: str, steps: int = 10
) -> list[list[tuple[float, float]]]:
    glyph_set = font.getGlyphSet()
    if glyph_name not in glyph_set:
        return []

    pen = RecordingPen()
    glyph_set[glyph_name].draw(pen)
    contours: list[list[tuple[float, float]]] = []
    contour: list[tuple[float, float]] = []
    start: tuple[float, float] | None = None
    current: tuple[float, float] | None = None

    for op, args in pen.value:
        if op == "moveTo":
            if contour:
                contours.append(contour)
            start = args[0]
            current = start
            contour = [start]
        elif op == "lineTo":
            current = args[0]
            contour.append(current)
        elif op == "qCurveTo" and current is not None:
            for control, end in decomposeQuadraticSegment(args):
                contour.extend(sample_quadratic(current, control, end, steps))
                current = end
        elif op == "curveTo" and current is not None:
            c1, c2, end = args
            contour.extend(sample_cubic(current, c1, c2, end, steps))
            current = end
        elif op in ("closePath", "endPath"):
            if contour and start is not None and contour[-1] != start:
                contour.append(start)
            if contour:
                contours.append(contour)
            contour = []
            start = None
            current = None

    if contour:
        contours.append(contour)
    return contours


def segments_for_contours(
    contours: list[list[tuple[float, float]]],
) -> list[tuple[int, int, tuple[float, float], tuple[float, float]]]:
    segments = []
    for contour_index, contour in enumerate(contours):
        for segment_index in range(len(contour) - 1):
            segments.append(
                (contour_index, segment_index, contour[segment_index], contour[segment_index + 1])
            )
    return segments


def ccw(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def bounding_boxes_overlap(a0, a1, b0, b1) -> bool:
    return not (
        max(a0[0], a1[0]) < min(b0[0], b1[0])
        or max(b0[0], b1[0]) < min(a0[0], a1[0])
        or max(a0[1], a1[1]) < min(b0[1], b1[1])
        or max(b0[1], b1[1]) < min(a0[1], a1[1])
    )


def segments_intersect(a0, a1, b0, b1) -> bool:
    if a0 == b0 or a0 == b1 or a1 == b0 or a1 == b1:
        return False
    if not bounding_boxes_overlap(a0, a1, b0, b1):
        return False
    d1 = ccw(a0, a1, b0)
    d2 = ccw(a0, a1, b1)
    d3 = ccw(b0, b1, a0)
    d4 = ccw(b0, b1, a1)
    return (d1 == 0 or d2 == 0 or sign(d1) != sign(d2)) and (
        d3 == 0 or d4 == 0 or sign(d3) != sign(d4)
    )


def contour_segment_lengths(contours: list[list[tuple[float, float]]]) -> list[float]:
    lengths = []
    for contour in contours:
        for p0, p1 in zip(contour, contour[1:], strict=False):
            lengths.append(math.hypot(p1[0] - p0[0], p1[1] - p0[1]))
    return lengths


def glyph_intersection_metrics(font: TTFont, glyph_name: str) -> dict[str, object]:
    contours = glyph_polylines(font, glyph_name)
    segments = segments_for_contours(contours)
    intersections = 0

    for index, (contour_a, segment_a, a0, a1) in enumerate(segments):
        for contour_b, segment_b, b0, b1 in segments[index + 1 :]:
            if contour_a == contour_b and abs(segment_a - segment_b) <= 1:
                continue
            if contour_a == contour_b and {segment_a, segment_b} == {
                0,
                len(contours[contour_a]) - 2,
            }:
                continue
            if segments_intersect(a0, a1, b0, b1):
                intersections += 1

    lengths = contour_segment_lengths(contours)
    return {
        "contours": len(contours),
        "intersections": intersections,
        "min_segment_length": round(min(lengths), 2) if lengths else None,
        "zero_ink": glyph_ink_area(font, glyph_name) <= 0.0,
    }


def build_instance_risk_report(
    family_key: str,
    generated: dict[int, Path],
    review_glyphs: list[str],
    report_dir: Path,
) -> Path:
    payload = {"family": family_key, "weights": {}, "review_glyphs": review_glyphs}

    for weight, instance_path in sorted(generated.items()):
        font = TTFont(instance_path)
        glyph_reports: dict[str, dict[str, object]] = {}
        for glyph_name in review_glyphs:
            if glyph_name not in font.getGlyphOrder():
                continue
            metrics = glyph_intersection_metrics(font, glyph_name)
            glyph_reports[glyph_name] = metrics

        risky = {
            glyph_name: metrics
            for glyph_name, metrics in glyph_reports.items()
            if metrics["intersections"] > 0
            or metrics["zero_ink"]
            or (metrics["min_segment_length"] is not None and metrics["min_segment_length"] < 2.0)
        }
        payload["weights"][str(weight)] = {
            "instance_path": str(instance_path),
            "risky_glyph_count": len(risky),
            "risky_glyphs": risky,
        }

    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{family_key}-instance-risk-report.json"
    report_path.write_text(json.dumps(payload, indent=2))
    return report_path


def build_validation_report(
    family_key: str,
    generated: dict[int, Path],
    plan,
    review_glyphs: set[str],
    report_dir: Path,
) -> Path:
    donor_weights = {}
    for master_name, donor_path in plan.donor_paths_by_master_name.items():
        if "Thin" in master_name:
            donor_weights[100] = donor_path
        elif master_name in ("Regular", "Italic"):
            donor_weights[400] = donor_path
        elif "ExtraBlack" in master_name:
            donor_weights[950] = donor_path

    payload = {"family": family_key, "weights": {}}
    for weight, donor_path in donor_weights.items():
        instance_path = generated.get(weight)
        if instance_path is None:
            continue
        payload["weights"][str(weight)] = compare_fonts(
            instance_path, donor_path, glyph_subset=review_glyphs
        )

    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{family_key}-master-validation.json"
    report_path.write_text(json.dumps(payload, indent=2))
    return report_path


def repair_bucket_configs(
    glyph_configs: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    return {
        glyph_name: config
        for glyph_name, config in glyph_configs.items()
        if config.get("repair_bucket")
    }


def interpolatable_details_for_glyph(
    interpolatable_payload: dict[str, list[dict[str, object]]],
    glyph_name: str,
) -> dict[str, object]:
    issues = interpolatable_payload.get(glyph_name, [])
    issue_types = [str(issue.get("type", "unknown")) for issue in issues]
    return {
        "issue_count": len(issues),
        "issue_types": sorted(set(issue_types)),
        "issue_type_counts": dict(Counter(issue_types)),
        "issues": issues,
    }


def instance_risk_details_for_glyph(
    instance_payload: dict[str, object],
    glyph_name: str,
) -> dict[str, object]:
    per_weight: dict[str, dict[str, object]] = {}
    max_intersections = 0
    min_segment_length: float | None = None

    for weight, payload in instance_payload.get("weights", {}).items():
        metrics = payload.get("risky_glyphs", {}).get(glyph_name)
        if not metrics:
            continue
        per_weight[str(weight)] = metrics
        max_intersections = max(max_intersections, int(metrics.get("intersections", 0) or 0))
        value = metrics.get("min_segment_length")
        if value is not None:
            min_segment_length = (
                value if min_segment_length is None else min(min_segment_length, value)
            )

    return {
        "risky_weight_count": len(per_weight),
        "weights": per_weight,
        "max_intersections": max_intersections,
        "min_segment_length": min_segment_length,
    }


def validation_details_for_glyph(
    validation_payload: dict[str, object],
    glyph_name: str,
) -> dict[str, object]:
    area_diff_by_weight: dict[str, float] = {}
    deviation_by_weight: dict[str, float] = {}

    for weight, payload in validation_payload.get("weights", {}).items():
        area_diff = payload.get("worst_area_diffs_pct", {}).get(glyph_name)
        if area_diff is not None:
            area_diff_by_weight[str(weight)] = area_diff
        deviation = payload.get("worst_deviations", {}).get(glyph_name)
        if deviation is not None:
            deviation_by_weight[str(weight)] = deviation

    return {
        "area_diff_by_weight": area_diff_by_weight,
        "deviation_by_weight": deviation_by_weight,
        "max_area_diff_pct": max(area_diff_by_weight.values()) if area_diff_by_weight else None,
        "max_point_deviation": max(deviation_by_weight.values()) if deviation_by_weight else None,
    }


def build_cluster_evidence_report(
    family_key: str,
    glyph_configs: dict[str, dict[str, object]],
    source_report_path: Path,
    interpolatable_report_path: Path,
    instance_report_path: Path,
    validation_report_path: Path,
    report_dir: Path,
) -> Path | None:
    tracked_glyph_configs = repair_bucket_configs(glyph_configs)
    if not tracked_glyph_configs:
        return None

    source_payload = json.loads(source_report_path.read_text())
    source_index = {entry["glyph_name"]: entry for entry in source_payload["glyphs"]}
    interpolatable_payload = json.loads(interpolatable_report_path.read_text())
    instance_payload = json.loads(instance_report_path.read_text())
    validation_payload = json.loads(validation_report_path.read_text())

    entries: list[dict[str, object]] = []
    for glyph_name, config in tracked_glyph_configs.items():
        source_entry = source_index.get(glyph_name)
        if not source_entry:
            continue
        entries.append(
            {
                "glyph_name": glyph_name,
                "repair_bucket": config.get("repair_bucket"),
                "priority": config.get("priority"),
                "current_strategy": source_entry.get("strategy"),
                "source": {
                    "classification": source_entry.get("classification"),
                    "risk_score": source_entry.get("risk_score"),
                    "donor_raw_compat": source_entry.get("donor_raw_compat"),
                    "contour_count_mismatch": source_entry.get("contour_count_mismatch"),
                    "total_segment_delta": source_entry.get("total_segment_delta"),
                    "segment_delta_by_master": source_entry.get("segment_delta_by_master"),
                    "donor_structs": source_entry.get("donor_structs"),
                    "donor_segment_counts": source_entry.get("donor_segment_counts"),
                    "source_segment_counts": source_entry.get("source_segment_counts"),
                    "source_node_counts": source_entry.get("source_node_counts"),
                    "source_direction_signs": source_entry.get("source_direction_signs"),
                },
                "interpolatable": interpolatable_details_for_glyph(
                    interpolatable_payload, glyph_name
                ),
                "instance_risk": instance_risk_details_for_glyph(instance_payload, glyph_name),
                "validation": validation_details_for_glyph(validation_payload, glyph_name),
            }
        )

    payload = {
        "family": family_key,
        "glyph_count": len(entries),
        "summary": {
            "repair_bucket_counts": dict(Counter(entry["repair_bucket"] for entry in entries)),
            "glyphs": [entry["glyph_name"] for entry in entries],
        },
        "glyphs": entries,
    }
    report_path = report_dir / f"{family_key}-residual-cluster-evidence.json"
    report_path.write_text(json.dumps(payload, indent=2))
    return report_path


def recommend_exception_action(entry: dict[str, object]) -> dict[str, object]:
    repair_bucket = entry["repair_bucket"]
    source = entry["source"]
    interpolatable_details = entry["interpolatable"]
    instance_risk = entry["instance_risk"]
    validation = entry["validation"]

    issue_types = set(interpolatable_details["issue_types"])
    max_intersections = int(instance_risk["max_intersections"] or 0)
    max_area_diff = float(validation["max_area_diff_pct"] or 0.0)
    total_segment_delta = int(source["total_segment_delta"] or 0)
    donor_raw_compat = source["donor_raw_compat"]
    min_segment_length = instance_risk["min_segment_length"]

    rationale: list[str] = []
    if issue_types:
        rationale.append(f"interpolatable issues={sorted(issue_types)}")
    if max_intersections > 0:
        rationale.append(f"sampled intersections={max_intersections}")
    if min_segment_length is not None:
        rationale.append(f"min segment={min_segment_length}")
    if max_area_diff > 0:
        rationale.append(f"max area drift={round(max_area_diff, 2)}%")
    rationale.append(f"total segment delta={total_segment_delta}")
    rationale.append(f"donor raw compat={donor_raw_compat}")

    action = "keep_normalized"
    confidence = "medium"

    if repair_bucket == "freeze_candidate":
        if max_intersections == 0 and not issue_types and max_area_diff <= 1.0:
            action = "keep_normalized"
            confidence = "high"
        elif (
            max_intersections == 0
            and issue_types.issubset({"underweight"})
            and total_segment_delta <= 3
            and max_area_diff <= 2.0
        ):
            action = "trial_freeze_to_reference"
            confidence = "medium"
        else:
            action = "keep_under_review"
            confidence = "medium"
    elif repair_bucket == "curve_balance":
        if max_intersections == 0 and issue_types.issubset({"underweight", "kink"}):
            action = "localized_substitution"
            confidence = "high"
        else:
            action = "manual_redraw_required"
            confidence = "medium"
    elif repair_bucket == "redraw_candidate":
        if (
            max_intersections > 0
            or max_area_diff >= 4.0
            or total_segment_delta >= 5
            or "kink" in issue_types
        ):
            action = "manual_redraw_required"
            confidence = "high"
        else:
            action = "localized_substitution"
            confidence = "medium"

    return {
        "glyph_name": entry["glyph_name"],
        "repair_bucket": repair_bucket,
        "recommended_action": action,
        "confidence": confidence,
        "rationale": rationale,
        "evidence": {
            "issue_types": sorted(issue_types),
            "max_intersections": max_intersections,
            "min_segment_length": min_segment_length,
            "max_area_diff_pct": validation["max_area_diff_pct"],
            "total_segment_delta": total_segment_delta,
            "donor_raw_compat": donor_raw_compat,
        },
    }


def build_exception_plan_report(
    family_key: str,
    cluster_evidence_report_path: Path,
    report_dir: Path,
) -> Path:
    payload = json.loads(cluster_evidence_report_path.read_text())
    actions = [recommend_exception_action(entry) for entry in payload.get("glyphs", [])]
    summary = {
        "recommended_action_counts": dict(
            Counter(action["recommended_action"] for action in actions)
        ),
        "glyphs": [action["glyph_name"] for action in actions],
    }
    report_payload = {
        "family": family_key,
        "glyph_count": len(actions),
        "summary": summary,
        "actions": actions,
    }
    report_path = report_dir / f"{family_key}-residual-cluster-plan.json"
    report_path.write_text(json.dumps(report_payload, indent=2))
    return report_path


def build_review_packet(
    manifest: dict[str, object],
    source_reports: dict[str, Path],
    instance_reports: dict[str, Path],
    validation_reports: dict[str, Path],
    interpolatable_reports: dict[str, dict[str, object]],
    output_path: Path,
) -> Path:
    lines = ["# Circular Repair Review Packet", ""]

    for family_key in ("roman", "italic"):
        source_payload = json.loads(source_reports[family_key].read_text())
        instance_payload = json.loads(instance_reports[family_key].read_text())
        validation_payload = json.loads(validation_reports[family_key].read_text())
        summary = source_payload["summary"]
        lines.append(f"## {family_key.title()}")
        lines.append("")
        lines.append(f"- glyph count: `{summary['glyph_count']}`")
        lines.append(
            f"- classification counts: `{json.dumps(summary['classification_counts'], sort_keys=True)}`"
        )
        lines.append(
            f"- interpolatable problem glyphs: `{interpolatable_reports[family_key]['problem_glyphs']}`"
        )

        top_risk = summary["top_risk_glyphs"][:12]
        if top_risk:
            lines.append("- top risk glyphs:")
            for entry in top_risk:
                lines.append(
                    f"  - `{entry['glyph_name']}`: class={entry['classification']} "
                    f"risk={entry['risk_score']} strategy={entry['strategy']} "
                    f"delta={entry['total_segment_delta']} rawCompat={entry['donor_raw_compat']}"
                )

        lines.append("- exact-master validation:")
        for weight, payload in validation_payload["weights"].items():
            lines.append(
                f"  - `wght {weight}`: pointMismatch={payload['mismatched_point_count']} "
                f"deviations={payload['glyphs_with_deviation']} areaDiffs={payload['glyphs_with_area_diff_pct']}"
            )

        lines.append("- midpoint/export risk:")
        for weight, payload in instance_payload["weights"].items():
            if int(weight) in (100, 400, 950):
                continue
            lines.append(f"  - `wght {weight}`: riskyGlyphs={payload['risky_glyph_count']}")
        lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n")
    return output_path


def run_family(
    family_key: str,
    family_manifest: dict[str, object],
    report_dir: Path,
    build_dir: Path,
    skip_import: bool,
    skip_build: bool,
    no_backup: bool,
) -> dict[str, object]:
    plan = FONT_PLANS[family_key]

    if not skip_import:
        populate_font(
            plan=plan,
            dry_run=False,
            make_backup=not no_backup,
            report_dir=report_dir.parent,
        )

    font = glyphsLib.load(str(plan.source_path))
    strategy_results = {}
    brace_results = {}
    initial_brace_cleanup: dict[str, int] = {}
    glyph_configs = resolve_glyph_configs(family_manifest, font=font)

    for glyph in font.glyphs:
        removed = clear_generated_brace_layers(glyph)
        if removed:
            initial_brace_cleanup[glyph.name] = removed

    inherited_configs: list[tuple[str, dict[str, object]]] = []
    for glyph_name, config in glyph_configs.items():
        strategy = config.get("strategy")
        if strategy == "rebuild_notdef":
            strategy_results[glyph_name] = rebuild_notdef(font)
        elif strategy in {"reference_fallback", "freeze_to_reference"}:
            strategy_results[glyph_name] = apply_reference_fallback(
                font,
                glyph_name=glyph_name,
                reference_master_name=family_manifest["reference_master_name"],
            )
        elif strategy == "weighted_fallback":
            strategy_results[glyph_name] = apply_weighted_fallback(
                font,
                glyph_name=glyph_name,
                reference_master_name=family_manifest["reference_master_name"],
                plan=plan,
            )
        elif strategy == "donor_copy":
            strategy_results[glyph_name] = apply_donor_copy(
                font,
                glyph_name=glyph_name,
                plan=plan,
            )
        elif strategy == "structural_fallback":
            strategy_results[glyph_name] = apply_structural_fallback(
                font,
                glyph_name=glyph_name,
                reference_master_name=family_manifest["reference_master_name"],
                plan=plan,
            )
        elif strategy == "localized_substitution":
            strategy_results[glyph_name] = apply_localized_substitution(
                font,
                glyph_name=glyph_name,
                reference_master_name=family_manifest["reference_master_name"],
                contour_indices=config.get("contour_indices"),
            )
        elif strategy == "inherit_base_contours":
            inherited_configs.append((glyph_name, config))

    for glyph_name, config in inherited_configs:
        base_glyph_name = config.get("base_glyph")
        if not base_glyph_name:
            strategy_results[glyph_name] = {
                "applied": False,
                "reason": "missing_base_glyph",
            }
            continue
        strategy_results[glyph_name] = apply_inherit_base_contours(
            font,
            glyph_name=glyph_name,
            base_glyph_name=base_glyph_name,
        )

    alignment_changes = strict_align_font(font)
    winding_changes = normalize_winding(font)
    post_winding_alignment = strict_align_font(font)
    font.save(str(plan.source_path))
    export_compat_result = process_export_compatibility(family_key, dry_run=False)

    font = glyphsLib.load(str(plan.source_path))
    post_export_alignment = strict_align_font(font)
    post_export_winding = normalize_winding(font)
    post_export_alignment_2 = strict_align_font(font)

    for glyph in font.glyphs:
        config = glyph_configs.get(glyph.name, {})
        brace_weights = config.get("brace_weights") or []
        if brace_weights:
            brace_results[glyph.name] = apply_brace_layers(
                font,
                glyph_name=glyph.name,
                reference_master_name=family_manifest["reference_master_name"],
                brace_weights=brace_weights,
                plan=plan,
                brace_mode=config.get("brace_mode"),
            )
        else:
            removed = clear_generated_brace_layers(glyph)
            if removed:
                brace_results[glyph.name] = {
                    "applied": False,
                    "removed": removed,
                    "reason": "stale_generated_braces_removed",
                }

    path_order_override_results: dict[str, dict[str, object]] = {}
    for glyph_name, config in glyph_configs.items():
        overrides = config.get("source_path_order_overrides")
        if overrides:
            path_order_override_results[glyph_name] = apply_source_path_order_overrides(
                font,
                glyph_name=glyph_name,
                overrides=overrides,
            )

    font.save(str(plan.source_path))

    font = glyphsLib.load(str(plan.source_path))
    strict_audit = strict_audit_font(font)
    post_reload_path_order_override_results: dict[str, dict[str, object]] = {}
    affected_override_glyphs = {
        row[0]
        for key in ("path_order_issues", "start_issues")
        for row in strict_audit[key]
        if glyph_configs.get(row[0], {}).get("source_path_order_overrides")
    }
    if affected_override_glyphs:
        for glyph_name in sorted(affected_override_glyphs):
            post_reload_path_order_override_results[glyph_name] = apply_source_path_order_overrides(
                font,
                glyph_name=glyph_name,
                overrides=glyph_configs[glyph_name]["source_path_order_overrides"],
            )
        font.save(str(plan.source_path))
        font = glyphsLib.load(str(plan.source_path))
        strict_audit = strict_audit_font(font)
    source_mismatches = audit_font(font)

    source_report_path = build_family_source_report(
        family_key=family_key,
        font=font,
        plan=plan,
        glyph_configs=glyph_configs,
        report_dir=report_dir,
    )

    build_payload: dict[str, object] = {
        "source_report": str(source_report_path),
        "strategy_results": strategy_results,
        "brace_results": brace_results,
        "path_order_override_results": path_order_override_results,
        "initial_brace_cleanup": initial_brace_cleanup,
        "alignment_changes": alignment_changes,
        "winding_changes": winding_changes,
        "post_winding_alignment": post_winding_alignment,
        "export_compatibility_result": export_compat_result,
        "post_export_alignment": post_export_alignment,
        "post_export_winding": post_export_winding,
        "post_export_alignment_2": post_export_alignment_2,
        "post_reload_path_order_override_results": post_reload_path_order_override_results,
        "strict_audit_counts": {
            "path_order": len(strict_audit["path_order_issues"]),
            "node_count": len(strict_audit["node_count_issues"]),
            "start": len(strict_audit["start_issues"]),
            "post_write_mismatches": len(source_mismatches),
        },
    }

    if skip_build:
        return build_payload

    designspace_name = "GlideItalic.designspace" if family_key == "italic" else "Glide.designspace"
    ufo_prefix = "GlideItalic" if family_key == "italic" else "Glide"
    designspace_path = export_designspace(plan.source_path, designspace_name, ufo_prefix)
    interpolatable_report_path = report_dir / f"{family_key}-designspace-interpolatable.json"
    interpolatable_payload = run_interpolatable_designspace(
        designspace_path, interpolatable_report_path
    )

    family_build_dir = build_dir / family_key
    variable_font_path = family_build_dir / f"{plan.source_path.stem}-vf.ttf"
    build_variable_font(designspace_path, variable_font_path)
    weights = sample_weights(family_manifest, font)
    generated = generate_static_samples(variable_font_path, weights, family_build_dir / "instances")

    source_payload = json.loads(source_report_path.read_text())
    explicit_review = list(glyph_configs.keys())
    top_risk = [entry["glyph_name"] for entry in source_payload["summary"]["top_risk_glyphs"][:25]]
    review_glyphs = sorted(set(explicit_review + top_risk))

    validation_report_path = build_validation_report(
        family_key=family_key,
        generated=generated,
        plan=plan,
        review_glyphs=set(review_glyphs),
        report_dir=report_dir,
    )
    instance_report_path = build_instance_risk_report(
        family_key=family_key,
        generated=generated,
        review_glyphs=review_glyphs,
        report_dir=report_dir,
    )
    cluster_evidence_report_path = build_cluster_evidence_report(
        family_key=family_key,
        glyph_configs=glyph_configs,
        source_report_path=source_report_path,
        interpolatable_report_path=interpolatable_report_path,
        instance_report_path=instance_report_path,
        validation_report_path=validation_report_path,
        report_dir=report_dir,
    )
    cluster_plan_report_path = (
        build_exception_plan_report(
            family_key=family_key,
            cluster_evidence_report_path=cluster_evidence_report_path,
            report_dir=report_dir,
        )
        if cluster_evidence_report_path is not None
        else None
    )

    build_payload.update(
        {
            "designspace_path": str(designspace_path),
            "interpolatable_report": str(interpolatable_report_path),
            "interpolatable_summary": interpolatable_payload,
            "variable_font_path": str(variable_font_path),
            "instance_report": str(instance_report_path),
            "validation_report": str(validation_report_path),
            "cluster_evidence_report": str(cluster_evidence_report_path)
            if cluster_evidence_report_path
            else None,
            "cluster_plan_report": str(cluster_plan_report_path)
            if cluster_plan_report_path
            else None,
        }
    )
    return build_payload


def load_existing_repair_summary(summary_path: Path) -> dict[str, dict[str, object]]:
    if not summary_path.exists():
        return {}

    try:
        payload = json.loads(summary_path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Cannot merge repair summary because {summary_path} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise ValueError(
            f"Cannot merge repair summary because {summary_path} does not contain an object."
        )

    for family_key, result in payload.items():
        if not isinstance(result, dict):
            raise ValueError(
                "Cannot merge repair summary because "
                f"{summary_path} has a non-object result for {family_key!r}."
            )

    return payload


def merge_family_results(
    existing: dict[str, dict[str, object]],
    updates: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    merged = dict(existing)
    merged.update(updates)

    ordered: dict[str, dict[str, object]] = {}
    for family_key in ("roman", "italic"):
        if family_key in merged:
            ordered[family_key] = merged[family_key]
    for family_key, result in merged.items():
        if family_key not in ordered:
            ordered[family_key] = result

    return ordered


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest).resolve()
    manifest = load_manifest(manifest_path)
    report_dir = Path(args.report_dir).resolve()
    build_dir = Path(args.build_dir).resolve()

    selected = ["roman", "italic"] if args.font == "all" else [args.font]
    summary_path = report_dir / "repair-run-summary.json"
    if args.font == "all":
        existing_results: dict[str, dict[str, object]] = {}
    else:
        try:
            existing_results = load_existing_repair_summary(summary_path)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    family_results: dict[str, dict[str, object]] = {}

    for family_key in selected:
        family_results[family_key] = run_family(
            family_key=family_key,
            family_manifest=manifest[family_key],
            report_dir=report_dir,
            build_dir=build_dir,
            skip_import=args.skip_import,
            skip_build=args.skip_build,
            no_backup=args.no_backup,
        )

    if not args.skip_build and set(selected) == {"roman", "italic"}:
        source_reports = {
            family_key: report_dir / f"{family_key}-source-report.json" for family_key in selected
        }
        instance_reports = {
            family_key: report_dir / f"{family_key}-instance-risk-report.json"
            for family_key in selected
        }
        validation_reports = {
            family_key: report_dir / f"{family_key}-master-validation.json"
            for family_key in selected
        }
        interpolatable_reports = {
            family_key: family_results[family_key]["interpolatable_summary"]
            for family_key in selected
        }
        build_review_packet(
            manifest=manifest,
            source_reports=source_reports,
            instance_reports=instance_reports,
            validation_reports=validation_reports,
            interpolatable_reports=interpolatable_reports,
            output_path=report_dir / "review-packet.md",
        )

    summary_results = (
        family_results
        if args.font == "all"
        else merge_family_results(existing_results, family_results)
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary_results, indent=2))

    for family_key in selected:
        result = family_results[family_key]
        print(
            f"{family_key}: "
            f"source={result['source_report']} "
            f"strict={result['strict_audit_counts']} "
            f"build={'skipped' if args.skip_build else result.get('variable_font_path')}"
        )

    print(f"summary={summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
