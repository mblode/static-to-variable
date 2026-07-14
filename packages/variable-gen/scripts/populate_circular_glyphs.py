#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter, OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import glyphsLib
from glyphsLib import classes as glyphs_classes

REPO_ROOT = Path(__file__).resolve().parents[3]
CABINET_DIR = REPO_ROOT / "cabinet"
if str(CABINET_DIR) not in sys.path:
    sys.path.insert(0, str(CABINET_DIR))
BUILD_DIR = CABINET_DIR / "build"
if str(BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(BUILD_DIR))

from fix_source_files import layer_to_ops, master_layers_for_glyph
from import_circular import (
    effective_structure,
    find_ttf_glyph,
    load_ttf,
    normalize_master_ops,
    record_glyph,
    verify_cubic_compat,
    write_ops_to_layer,
)
from italic_variable_kerning import extract_pair_adjustments

OFFCURVE = "offcurve"
ORDER_MISMATCH_PENALTY = 1_000_000.0
FORCED_REFERENCE_FALLBACK_GLYPHS = {
    "ncommaaccent",
    "napostrophe",
}


@dataclass(frozen=True)
class FontPlan:
    key: str
    source_path: Path
    reference_master_name: str
    donor_paths_by_master_name: dict[str, Path]


FONT_PLANS = {
    "roman": FontPlan(
        key="roman",
        source_path=REPO_ROOT / "glide-variable.glyphs",
        reference_master_name="Regular",
        donor_paths_by_master_name={
            "Thin": REPO_ROOT / "cabinet/Circular/Circular/Circular-Thin.otf",
            "Regular": REPO_ROOT / "cabinet/Circular/Circular/Circular-Book.otf",
            "ExtraBlack": REPO_ROOT / "cabinet/Circular/Circular/Circular-ExtraBlack.otf",
        },
    ),
    "italic": FontPlan(
        key="italic",
        source_path=REPO_ROOT / "glide-variable-italic.glyphs",
        reference_master_name="Italic",
        donor_paths_by_master_name={
            "ThinItalic": REPO_ROOT / "cabinet/Circular/Circular Italic/Circular-ThinItalic.otf",
            "Italic": REPO_ROOT / "cabinet/Circular/Circular Italic/Circular-BookItalic.otf",
            "ExtraBlackItalic": REPO_ROOT / "cabinet/Circular/Circular Italic/Circular-ExtraBlackItalic.otf",
        },
    ),
}


def _is_path(shape) -> bool:
    return hasattr(shape, "nodes") and not hasattr(shape, "component")


def path_node_signature(path) -> tuple[str, ...]:
    return tuple(str(node.type) for node in path.nodes)


def canonical_path_signature(path) -> tuple[str, ...]:
    signature = list(path_node_signature(path))
    if not signature:
        return ()
    count = len(signature)
    forward = {tuple(signature[index:] + signature[:index]) for index in range(count)}
    reverse_sig = signature[::-1]
    reverse = {tuple(reverse_sig[index:] + reverse_sig[:index]) for index in range(count)}
    return min(forward | reverse)


def path_centroid(path) -> tuple[float, float]:
    xs = []
    ys = []
    for node in path.nodes:
        if node.type == OFFCURVE:
            continue
        xs.append(node.position.x)
        ys.append(node.position.y)
    if not xs:
        return (0.0, 0.0)
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def path_bbox(path) -> tuple[float, float, float, float]:
    xs = [node.position.x for node in path.nodes]
    ys = [node.position.y for node in path.nodes]
    return (min(xs), min(ys), max(xs), max(ys))


def dist_sq(a: tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def best_path_mapping(ref_paths, other_paths) -> list[int]:
    count = len(ref_paths)
    if count <= 1:
        return list(range(count))

    ref_signatures = [canonical_path_signature(path) for path in ref_paths]
    other_signatures = [canonical_path_signature(path) for path in other_paths]
    ref_centroids = [path_centroid(path) for path in ref_paths]
    other_centroids = [path_centroid(path) for path in other_paths]
    ref_bboxes = [path_bbox(path) for path in ref_paths]
    other_bboxes = [path_bbox(path) for path in other_paths]

    costs = [[0.0] * count for _ in range(count)]
    for ref_index in range(count):
        ref_bbox = ref_bboxes[ref_index]
        ref_width = ref_bbox[2] - ref_bbox[0]
        ref_height = ref_bbox[3] - ref_bbox[1]
        ref_scale = max(ref_width * ref_height, 1.0)

        for other_index in range(count):
            penalty = 0.0
            if ref_signatures[ref_index] != other_signatures[other_index]:
                penalty = ORDER_MISMATCH_PENALTY
            other_bbox = other_bboxes[other_index]
            centroid_cost = dist_sq(
                ref_centroids[ref_index],
                other_centroids[other_index],
            ) / ref_scale
            size_cost = abs(ref_width - (other_bbox[2] - other_bbox[0]))
            size_cost += abs(ref_height - (other_bbox[3] - other_bbox[1]))
            costs[ref_index][other_index] = penalty + centroid_cost + size_cost

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


def reorder_layer_paths(layer, current_paths, mapping) -> None:
    reordered = [current_paths[index] for index in mapping]
    shapes = list(layer.shapes)
    path_slots = [index for index, shape in enumerate(shapes) if _is_path(shape)]
    for slot, path in zip(path_slots, reordered):
        shapes[slot] = path
    layer.shapes = shapes


def rotated_signature(signature: tuple[str, ...], rotation: int) -> tuple[str, ...]:
    if not signature:
        return signature
    rotation %= len(signature)
    return signature[rotation:] + signature[:rotation]


def rotated_nodes(nodes: list, rotation: int) -> list:
    if not nodes:
        return nodes
    rotation %= len(nodes)
    return nodes[rotation:] + nodes[:rotation]


def rotations_for_signature(path, target_signature: tuple[str, ...]) -> list[int]:
    signature = path_node_signature(path)
    if len(signature) != len(target_signature):
        return []
    return [
        offset
        for offset in range(len(signature))
        if rotated_signature(signature, offset) == target_signature
    ]


def node_distance_cost(ref_nodes, other_nodes) -> float:
    total = 0.0
    for ref_node, other_node in zip(ref_nodes, other_nodes):
        total += dist_sq(
            (ref_node.position.x, ref_node.position.y),
            (other_node.position.x, other_node.position.y),
        )
    return total


def choose_group_rotations(paths: list) -> list[int] | None:
    if not paths:
        return []

    signatures = [path_node_signature(path) for path in paths]
    if len({len(signature) for signature in signatures}) != 1:
        return None

    candidate_signatures = {
        rotated_signature(signatures[0], offset)
        for offset in range(len(signatures[0]))
    }
    shared_signatures = []
    for target_signature in candidate_signatures:
        if all(rotations_for_signature(path, target_signature) for path in paths):
            shared_signatures.append(target_signature)

    if not shared_signatures:
        return None

    oncurve_first = [signature for signature in shared_signatures if signature and signature[0] != OFFCURVE]
    if oncurve_first:
        shared_signatures = oncurve_first

    base_nodes = list(paths[0].nodes)
    best_cost = float("inf")
    best_offsets: list[int] | None = None

    for target_signature in shared_signatures:
        for base_offset in rotations_for_signature(paths[0], target_signature):
            rotated_base = rotated_nodes(base_nodes, base_offset)
            offsets = [base_offset]
            total_cost = 0.0

            for path in paths[1:]:
                path_nodes = list(path.nodes)
                candidate_offsets = rotations_for_signature(path, target_signature)
                best_path_offset = min(
                    candidate_offsets,
                    key=lambda offset: node_distance_cost(
                        rotated_base,
                        rotated_nodes(path_nodes, offset),
                    ),
                )
                total_cost += node_distance_cost(
                    rotated_base,
                    rotated_nodes(path_nodes, best_path_offset),
                )
                offsets.append(best_path_offset)

            if total_cost < best_cost:
                best_cost = total_cost
                best_offsets = offsets

    return best_offsets


def rotate_path_nodes(path, rotation: int) -> None:
    if rotation == 0:
        return
    values = path.nodes.values()
    values[:] = values[rotation:] + values[:rotation]


def reference_start(ref_path) -> tuple[float, float] | None:
    for node in ref_path.nodes:
        if node.type != OFFCURVE:
            return (node.position.x, node.position.y)
    return None


def rotation_cost(ref_nodes, other_nodes, offset: int) -> float:
    total = 0.0
    count = len(ref_nodes)
    for index, ref_node in enumerate(ref_nodes):
        other_node = other_nodes[(index + offset) % count]
        total += dist_sq(
            (ref_node.position.x, ref_node.position.y),
            (other_node.position.x, other_node.position.y),
        )
    return total


def find_rotation(ref_path, other_path) -> tuple[int, bool]:
    target = reference_start(ref_path)
    if target is None:
        return (0, False)

    ref_signature = path_node_signature(ref_path)
    nodes = list(other_path.nodes)
    exact_matches: list[tuple[float, int]] = []
    fallbacks: list[tuple[float, int]] = []

    for index, node in enumerate(nodes):
        rotated_sig = tuple(str(rotated.type) for rotated in (nodes[index:] + nodes[:index]))
        if rotated_sig == ref_signature:
            exact_matches.append((rotation_cost(list(ref_path.nodes), nodes, index), index))

        if node.type == OFFCURVE:
            continue
        distance = dist_sq((node.position.x, node.position.y), target)
        fallbacks.append((distance, index))

    if exact_matches:
        exact_matches.sort()
        return (exact_matches[0][1], True)

    if not fallbacks:
        return (0, False)

    fallbacks.sort()
    return (fallbacks[0][1], False)


def strict_align_font(font) -> dict[str, int]:
    reorders = 0
    rotations = 0

    for glyph in font.glyphs:
        layers = master_layers_for_glyph(font, glyph.name)
        if len(layers) < 2:
            continue

        ordered_layers = []
        for master in font.masters:
            layer = layers.get(master.id)
            if layer is None:
                continue
            ordered_layers.append(layer)
        if len(ordered_layers) < 2:
            continue

        ref_layer = ordered_layers[0]
        ref_paths = list(ref_layer.paths)
        if not ref_paths:
            continue

        for other_layer in ordered_layers[1:]:
            other_paths = list(other_layer.paths)
            if len(other_paths) != len(ref_paths):
                continue
            mapping = best_path_mapping(ref_paths, other_paths)
            if mapping != list(range(len(mapping))):
                reorder_layer_paths(other_layer, other_paths, mapping)
                reorders += 1

        aligned_layers = [layers[master.id] for master in font.masters if master.id in layers]
        ref_paths = list(aligned_layers[0].paths)
        for path_index in range(len(ref_paths)):
            grouped_paths = [layer.paths[path_index] for layer in aligned_layers]
            offsets = choose_group_rotations(grouped_paths)
            if offsets is None:
                continue
            for path, offset in zip(grouped_paths, offsets):
                if offset != 0:
                    rotate_path_nodes(path, offset)
                    rotations += 1

    return {
        "path_reorders": reorders,
        "startpoint_rotations": rotations,
    }


def strict_audit_font(font) -> dict[str, object]:
    path_order_issues: list[tuple[str, str, list[int]]] = []
    node_count_issues: list[tuple[str, str, int | str, int, int]] = []
    start_issues: list[tuple[str, int, list[int] | str]] = []

    for glyph in font.glyphs:
        layers = master_layers_for_glyph(font, glyph.name)
        ordered_layers = [layers[master.id] for master in font.masters if master.id in layers]
        if len(ordered_layers) < 2:
            continue

        ref_paths = list(ordered_layers[0].paths)
        if not ref_paths:
            continue

        for master, other_layer in zip(font.masters[1:], ordered_layers[1:]):
            other_paths = list(other_layer.paths)
            if len(ref_paths) != len(other_paths):
                node_count_issues.append(
                    (glyph.name, master.name, "path_count", len(ref_paths), len(other_paths))
                )
                continue

            mapping = best_path_mapping(ref_paths, other_paths)
            if mapping != list(range(len(mapping))):
                path_order_issues.append((glyph.name, master.name, mapping))

            ordered_other_paths = [other_paths[index] for index in mapping]
            for path_index, (ref_path, other_path) in enumerate(zip(ref_paths, ordered_other_paths)):
                if len(ref_path.nodes) != len(other_path.nodes):
                    node_count_issues.append(
                        (glyph.name, master.name, path_index, len(ref_path.nodes), len(other_path.nodes))
                    )

        for master, other_layer in zip(font.masters[1:], ordered_layers[1:]):
            other_paths = list(other_layer.paths)
            if len(ref_paths) != len(other_paths):
                continue

            mapping = best_path_mapping(ref_paths, other_paths)
            ordered_other_paths = [other_paths[index] for index in mapping]
            for path_index, (ref_path, other_path) in enumerate(zip(ref_paths, ordered_other_paths)):
                if len(ref_path.nodes) != len(other_path.nodes):
                    continue
                rotation, used_exact_match = find_rotation(ref_path, other_path)
                if rotation != 0:
                    start_issues.append((glyph.name, master.name, path_index, rotation, used_exact_match))

    return {
        "path_order_issues": path_order_issues,
        "node_count_issues": node_count_issues,
        "start_issues": start_issues,
    }


def import_kerning(font, donor_data_by_master_id: dict[str, tuple]) -> dict[str, int]:
    font.kerning = OrderedDict()
    available_glyphs = {glyph.name for glyph in font.glyphs}
    pair_counts: dict[str, int] = {}

    for master in font.masters:
        donor_font, _, _, _, _ = donor_data_by_master_id[master.id]
        pair_map = extract_pair_adjustments(donor_font, allowed_glyphs=available_glyphs)
        pair_counts[master.name] = len(pair_map)
        for (left_name, right_name), value in pair_map.items():
            font.setKerningForPair(master.id, left_name, right_name, int(value))

    return pair_counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Populate the live Glide .glyphs sources from Circular donor OTFs, "
            "using Book as the regular reference and normalizing compatibility "
            "across Thin and ExtraBlack."
        )
    )
    parser.add_argument(
        "--font",
        choices=("roman", "italic", "all"),
        default="all",
        help="Which source file to populate.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze and report without modifying the .glyphs files.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create a .bak copy before writing in place.",
    )
    parser.add_argument(
        "--report-dir",
        default="packages/variable-gen/reports",
        help="Directory for JSON import reports.",
    )
    return parser.parse_args()


def ordered_master_ids(font, reference_master_name: str) -> tuple[list[str], dict[str, object]]:
    masters_by_name = {master.name: master for master in font.masters}
    reference_master = masters_by_name[reference_master_name]
    ordered_ids = [reference_master.id]
    ordered_ids.extend(master.id for master in font.masters if master.id != reference_master.id)
    return ordered_ids, masters_by_name


def donor_unicode_map(ttfont) -> dict[str, list[int]]:
    reverse: dict[str, list[int]] = {}
    for codepoint, glyph_name in (ttfont.getBestCmap() or {}).items():
        reverse.setdefault(glyph_name, []).append(codepoint)
    return reverse


def ensure_glyph_exists(font, glyph_name: str, master_ids: list[str], unicode_values: list[int] | None) -> object:
    glyph = font.glyphs[glyph_name]
    if glyph is None:
        glyph = glyphs_classes.GSGlyph(glyph_name)
        if unicode_values:
            glyph.unicode = f"{unicode_values[0]:04X}"
        for master_id in master_ids:
            layer = glyphs_classes.GSLayer()
            layer.layerId = master_id
            layer.associatedMasterId = master_id
            layer.width = 0
            glyph.layers.append(layer)
        font.glyphs.append(glyph)
    else:
        if unicode_values and not glyph.unicode:
            glyph.unicode = f"{unicode_values[0]:04X}"
        existing_layer_ids = {layer.layerId for layer in glyph.layers}
        for master_id in master_ids:
            if master_id in existing_layer_ids:
                continue
            layer = glyphs_classes.GSLayer()
            layer.layerId = master_id
            layer.associatedMasterId = master_id
            layer.width = 0
            glyph.layers.append(layer)
    return glyph


def append_missing_donor_glyphs(font, donor_font, master_ids: list[str]) -> list[str]:
    reverse_cmap = donor_unicode_map(donor_font)
    added: list[str] = []
    for glyph_name in donor_font.getGlyphOrder():
        if font.glyphs[glyph_name] is None:
            ensure_glyph_exists(font, glyph_name, master_ids, reverse_cmap.get(glyph_name))
            added.append(glyph_name)
    return added


def choose_canonical_master_id(
    ordered_ids: list[str],
    master_structs: dict[str, tuple | None],
    available_master_ids: list[str],
) -> str | None:
    available_structs = [
        tuple(master_structs[master_id])
        for master_id in available_master_ids
        if master_structs.get(master_id) is not None
    ]
    if not available_structs:
        return available_master_ids[0] if available_master_ids else None

    majority_struct = Counter(available_structs).most_common(1)[0][0]
    for master_id in ordered_ids:
        if master_id not in available_master_ids:
            continue
        structure = master_structs.get(master_id)
        if structure is not None and tuple(structure) == majority_struct:
            return master_id

    return available_master_ids[0] if available_master_ids else None


def audit_font(font) -> list[str]:
    mismatches: list[str] = []
    for glyph in font.glyphs:
        layers = master_layers_for_glyph(font, glyph.name)
        if len(layers) < 2:
            continue
        master_ops = {
            master_id: layer_to_ops(layer)
            for master_id, layer in layers.items()
            if layer_to_ops(layer)
        }
        if len(master_ops) < 2:
            continue
        if not verify_cubic_compat(master_ops):
            mismatches.append(glyph.name)
    return mismatches


def backup_source(source_path: Path) -> Path:
    backup_path = source_path.with_suffix(source_path.suffix + ".pre-circular-import.bak")
    if not backup_path.exists():
        shutil.copy2(source_path, backup_path)
    return backup_path


def populate_font(plan: FontPlan, dry_run: bool, make_backup: bool, report_dir: Path) -> dict[str, object]:
    font = glyphsLib.load(str(plan.source_path))
    ordered_ids, masters_by_name = ordered_master_ids(font, plan.reference_master_name)
    glide_upm = font.upm

    donor_data_by_master_id: dict[str, tuple] = {}
    donor_path_strings: dict[str, str] = {}
    for master_name, donor_path in plan.donor_paths_by_master_name.items():
        if master_name not in masters_by_name:
            raise SystemExit(f"Master {master_name!r} not found in {plan.source_path}")
        donor_font, cmap, glyphset, donor_upm = load_ttf(donor_path)
        master = masters_by_name[master_name]
        donor_data_by_master_id[master.id] = (
            donor_font,
            cmap,
            glyphset,
            glide_upm / donor_upm,
            donor_path,
        )
        donor_path_strings[master_name] = str(donor_path)

    reference_master_id = masters_by_name[plan.reference_master_name].id
    donor_reference_font = donor_data_by_master_id[reference_master_id][0]
    added_glyphs = append_missing_donor_glyphs(font, donor_reference_font, ordered_ids)
    report: dict[str, object] = {
        "font": plan.key,
        "source": str(plan.source_path),
        "reference_master": plan.reference_master_name,
        "donors": donor_path_strings,
        "glyph_count": len(font.glyphs),
        "added_glyphs": added_glyphs,
        "glyphs": [],
        "backup": None,
    }

    imported = 0
    empty_outline_glyphs = 0
    fallback_glyphs: list[str] = []
    missing_glyphs: list[str] = []

    for glyph in font.glyphs:
        layers = master_layers_for_glyph(font, glyph.name)
        if not layers:
            continue

        donor_names_by_master_id: dict[str, str] = {}
        widths_by_master_id: dict[str, int] = {}
        raw_ops_by_master_id: dict[str, list] = {}
        donor_structs_by_master_id: dict[str, tuple | None] = {}
        glyph_report = {
            "glyph_name": glyph.name,
            "status": "imported",
            "donors": {},
            "fallback_to_reference": False,
        }

        for master_id in ordered_ids:
            if master_id not in donor_data_by_master_id or master_id not in layers:
                continue
            _, cmap, glyphset, upm_scale, donor_path = donor_data_by_master_id[master_id]
            donor_name = find_ttf_glyph(glyph, cmap, glyphset)
            if donor_name is None:
                glyph_report["status"] = "missing_donor_glyph"
                glyph_report["missing_master_id"] = master_id
                glyph_report["missing_donor_path"] = str(donor_path)
                missing_glyphs.append(glyph.name)
                break
            donor_names_by_master_id[master_id] = donor_name
            glyph_report["donors"][master_id] = donor_name
            widths_by_master_id[master_id] = round(glyphset[donor_name].width * upm_scale)
            donor_structs_by_master_id[master_id] = effective_structure(donor_name, glyphset)

            ops = record_glyph(donor_name, glyphset)
            if ops is not None:
                raw_ops_by_master_id[master_id] = ops

        if glyph_report["status"] == "missing_donor_glyph":
            report["glyphs"].append(glyph_report)
            continue

        ordered_raw_ops: dict[str, list] = {}
        if reference_master_id in raw_ops_by_master_id:
            ordered_raw_ops[reference_master_id] = raw_ops_by_master_id[reference_master_id]
        for master_id in ordered_ids:
            if master_id != reference_master_id and master_id in raw_ops_by_master_id:
                ordered_raw_ops[master_id] = raw_ops_by_master_id[master_id]

        normalized_ops_by_master_id = ordered_raw_ops
        valid_structs = [structure for structure in donor_structs_by_master_id.values() if structure is not None]
        contour_count_mismatch = len({len(structure) for structure in valid_structs}) > 1
        missing_outline_master_ids = [
            master_id
            for master_id in donor_names_by_master_id
            if master_id not in ordered_raw_ops
        ]
        force_reference_fallback = glyph.name in FORCED_REFERENCE_FALLBACK_GLYPHS

        if not ordered_raw_ops:
            glyph_report["status"] = "metrics_only"
            if missing_outline_master_ids:
                glyph_report["missing_outline_master_ids"] = missing_outline_master_ids
        elif force_reference_fallback:
            glyph_report["status"] = "reference_fallback"
            glyph_report["fallback_to_reference"] = True
            glyph_report["forced_reference_fallback"] = True
            reference_ops = ordered_raw_ops.get(reference_master_id)
            if reference_ops is None:
                glyph_report["status"] = "metrics_only"
                normalized_ops_by_master_id = {}
            else:
                glyph_report["fallback_master_id"] = reference_master_id
                fallback_glyphs.append(glyph.name)
                normalized_ops_by_master_id = {
                    master_id: reference_ops for master_id in donor_names_by_master_id
                }
        elif contour_count_mismatch or missing_outline_master_ids:
            glyph_report["status"] = "reference_fallback"
            glyph_report["fallback_to_reference"] = True
            glyph_report["contour_count_mismatch"] = contour_count_mismatch
            if missing_outline_master_ids:
                glyph_report["missing_outline_master_ids"] = missing_outline_master_ids

            canonical_master_id = choose_canonical_master_id(
                ordered_ids=ordered_ids,
                master_structs=donor_structs_by_master_id,
                available_master_ids=list(ordered_raw_ops),
            )
            if canonical_master_id is None:
                glyph_report["status"] = "metrics_only"
                normalized_ops_by_master_id = {}
            else:
                fallback_ops = ordered_raw_ops.get(canonical_master_id)
                if fallback_ops is None:
                    glyph_report["status"] = "metrics_only"
                    normalized_ops_by_master_id = {}
                else:
                    glyph_report["fallback_master_id"] = canonical_master_id
                    fallback_glyphs.append(glyph.name)
                    normalized_ops_by_master_id = {
                        master_id: fallback_ops for master_id in donor_names_by_master_id
                    }
        elif len(ordered_raw_ops) > 1:
            normalized_ops_by_master_id = normalize_master_ops(ordered_raw_ops)
            if normalized_ops_by_master_id is None or not verify_cubic_compat(normalized_ops_by_master_id):
                glyph_report["status"] = "reference_fallback"
                glyph_report["fallback_to_reference"] = True
                fallback_glyphs.append(glyph.name)
                canonical_master_id = choose_canonical_master_id(
                    ordered_ids=ordered_ids,
                    master_structs=donor_structs_by_master_id,
                    available_master_ids=list(ordered_raw_ops),
                )
                if canonical_master_id is None:
                    glyph_report["status"] = "metrics_only"
                    normalized_ops_by_master_id = {}
                else:
                    fallback_ops = ordered_raw_ops.get(canonical_master_id)
                    if fallback_ops is None:
                        glyph_report["status"] = "metrics_only"
                        normalized_ops_by_master_id = {}
                    else:
                        glyph_report["fallback_master_id"] = canonical_master_id
                        normalized_ops_by_master_id = {
                            master_id: fallback_ops for master_id in donor_names_by_master_id
                        }

        if not dry_run:
            for master_id in ordered_ids:
                if master_id not in layers or master_id not in donor_data_by_master_id:
                    continue
                layer = layers[master_id]
                if master_id in widths_by_master_id:
                    layer.width = widths_by_master_id[master_id]
                layer.shapes = []
                ops = normalized_ops_by_master_id.get(master_id)
                if ops:
                    write_ops_to_layer(ops, layer)

        if normalized_ops_by_master_id:
            imported += 1
        else:
            empty_outline_glyphs += 1
            glyph_report["status"] = "metrics_only"

        report["glyphs"].append(glyph_report)

    if not dry_run and make_backup:
        report["backup"] = str(backup_source(plan.source_path))

    alignment_changes = strict_align_font(font)
    kerning_pair_counts: dict[str, int] = {}
    if not dry_run:
        kerning_pair_counts = import_kerning(font, donor_data_by_master_id)
    audit_mismatches = audit_font(font)
    strict_audit = strict_audit_font(font)
    report["summary"] = {
        "glyph_count_after": len(font.glyphs),
        "added_glyph_count": len(added_glyphs),
        "imported_glyphs": imported,
        "metrics_only_glyphs": empty_outline_glyphs,
        "fallback_glyphs": fallback_glyphs,
        "missing_glyphs": missing_glyphs,
        "post_write_mismatches": audit_mismatches,
        "alignment_changes": alignment_changes,
        "kerning_pair_counts": kerning_pair_counts,
        "strict_path_order_issues": strict_audit["path_order_issues"],
        "strict_node_count_issues": strict_audit["node_count_issues"],
        "strict_start_issues": strict_audit["start_issues"],
    }

    if not dry_run:
        font.save(str(plan.source_path))

    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"circular-{plan.key}-glyphs-report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(
        f"{plan.key}: glyphs={len(font.glyphs)} added={len(added_glyphs)} "
        f"imported={imported} metrics_only={empty_outline_glyphs} "
        f"fallbacks={len(fallback_glyphs)} missing={len(missing_glyphs)} "
        f"mismatches={len(audit_mismatches)} kerningMasters={len(kerning_pair_counts)} "
        f"report={report_path}"
    )
    return report


def main() -> int:
    args = parse_args()
    report_dir = (REPO_ROOT / args.report_dir).resolve()
    selected_keys = list(FONT_PLANS) if args.font == "all" else [args.font]

    for key in selected_keys:
        populate_font(
            plan=FONT_PLANS[key],
            dry_run=args.dry_run,
            make_backup=not args.no_backup,
            report_dir=report_dir,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
