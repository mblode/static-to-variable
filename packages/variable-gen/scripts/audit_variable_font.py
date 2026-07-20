#!/usr/bin/env python3
"""Config-driven variable-font audit gate.

Exports each style's designspace from its live ``.glyphs`` source, builds an
audit variable font, and validates all glyphs across exact masters and sampled
in-between weights. Every input (sources, donors, weights) comes from a v3
``stv.config.json``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import glyphsLib
from fontTools.ttLib import TTFont

from variable_gen.audit_support import (
    build_variable_font,
    generate_static_samples,
    glyph_ink_area,
    glyph_intersection_metrics,
    glyph_point_deviation,
    json_safe,
    run_interpolatable_designspace,
)
from variable_gen.config import ProjectConfig, Style, load_config, resolve_style_keys
from variable_gen.designspace import export_designspace

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = SCRIPT_DIR.parent

DEFAULT_CONFIG = PACKAGE_DIR.parent.parent / "examples/minimal/stv.config.json"
DEFAULT_REPORT_DIR = PACKAGE_DIR / "reports/audit"
DEFAULT_BUILD_DIR = PACKAGE_DIR / "build/audit"
DEFAULT_MIN_SEGMENT_THRESHOLD = 2.0
DEFAULT_POINT_DEVIATION_THRESHOLD = 0.5
DEFAULT_AREA_DIFF_THRESHOLD = 1.0
DEFAULT_SAMPLES_PER_SPAN = 5
DEFAULT_TOP_GLYPHS = 50


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export a variable font from each style's live .glyphs source and audit "
            "all glyphs across exact masters and sampled in-between weights."
        )
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to the v3 stv.config.json driving the audit.",
    )
    parser.add_argument(
        "--style",
        default="all",
        help="Which style to audit (a config style key, or 'all').",
    )
    parser.add_argument(
        "--report-dir",
        default=str(DEFAULT_REPORT_DIR),
        help="Directory for JSON and Markdown audit reports.",
    )
    parser.add_argument(
        "--build-dir",
        default=str(DEFAULT_BUILD_DIR),
        help="Directory for built variable fonts and sampled static instances.",
    )
    parser.add_argument(
        "--samples-per-span",
        type=int,
        default=DEFAULT_SAMPLES_PER_SPAN,
        help=("Number of interior sample weights to generate inside each adjacent master span."),
    )
    parser.add_argument(
        "--min-segment-threshold",
        type=float,
        default=DEFAULT_MIN_SEGMENT_THRESHOLD,
        help="Flag sampled glyphs with segment lengths below this value.",
    )
    parser.add_argument(
        "--point-deviation-threshold",
        type=float,
        default=DEFAULT_POINT_DEVIATION_THRESHOLD,
        help="Flag exact-master point deviations above this value.",
    )
    parser.add_argument(
        "--area-diff-threshold",
        type=float,
        default=DEFAULT_AREA_DIFF_THRESHOLD,
        help="Flag exact-master area diffs above this percentage.",
    )
    parser.add_argument(
        "--top-glyphs",
        type=int,
        default=DEFAULT_TOP_GLYPHS,
        help="How many problem glyphs to surface in the Markdown summary.",
    )
    parser.add_argument(
        "--interpolation-only",
        action="store_true",
        help=(
            "Skip exact-master donor validation and focus report summaries on "
            "interpolatable issues plus interior in-between sampled weights."
        ),
    )
    return parser.parse_args()


def donor_paths_by_weight(style: Style) -> dict[int, Path]:
    """Map each configured master's weight to its donor font path."""
    donors_by_id = {donor.id: donor for donor in style.donors}
    axis_tag = next(iter(style.masters[0].location))
    return {
        int(master.location[axis_tag]): donors_by_id[master.donor_id].path
        for master in style.masters
    }


def master_weight(master) -> int:
    if getattr(master, "axes", None):
        return int(master.axes[0])
    return 400


def slugify(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")


def audit_mode_slug(interpolation_only: bool) -> str:
    return "interpolation-only" if interpolation_only else "all"


def build_span_plan(font, samples_per_span: int) -> dict[str, object]:
    masters = sorted(
        [
            {
                "name": master.name,
                "id": master.id,
                "weight": master_weight(master),
            }
            for master in font.masters
        ],
        key=lambda entry: entry["weight"],
    )
    spans: list[dict[str, object]] = []
    ordered_weights: list[int] = []

    for left, right in zip(masters, masters[1:], strict=False):
        denominator = max(samples_per_span + 1, 1)
        span_weights: list[int] = []
        for step in range(denominator + 1):
            interpolated = left["weight"] + (
                (right["weight"] - left["weight"]) * step / denominator
            )
            weight = int(round(interpolated))
            if not span_weights or span_weights[-1] != weight:
                span_weights.append(weight)

        spans.append(
            {
                "label": f"{slugify(left['name'])}_to_{slugify(right['name'])}",
                "from_master": left["name"],
                "to_master": right["name"],
                "from_weight": left["weight"],
                "to_weight": right["weight"],
                "weights": span_weights,
                "interior_weights": span_weights[1:-1],
            }
        )
        ordered_weights.extend(span_weights)

    unique_weights: list[int] = []
    seen: set[int] = set()
    for weight in ordered_weights:
        if weight in seen:
            continue
        seen.add(weight)
        unique_weights.append(weight)

    return {
        "masters": masters,
        "spans": spans,
        "weights": unique_weights,
    }


def glyph_order_for_font(font_path: Path) -> list[str]:
    font = TTFont(font_path)
    return [glyph_name for glyph_name in font.getGlyphOrder() if glyph_name != ".notdef"]


def compare_fonts_full(
    instance_path: Path,
    donor_path: Path,
    glyph_subset: set[str] | None,
    point_deviation_threshold: float,
    area_diff_threshold: float,
) -> dict[str, object]:
    instance_font = TTFont(instance_path)
    donor_font = TTFont(donor_path)
    common = set(instance_font.getGlyphOrder()) & set(donor_font.getGlyphOrder())
    if glyph_subset is not None:
        common &= glyph_subset

    deviations: dict[str, float] = {}
    area_diffs: dict[str, float] = {}
    mismatched_points: list[str] = []

    for glyph_name in sorted(common):
        if glyph_name == ".notdef":
            continue

        deviation = glyph_point_deviation(instance_font, donor_font, glyph_name)
        if deviation is None:
            mismatched_points.append(glyph_name)
        elif deviation > point_deviation_threshold:
            deviations[glyph_name] = round(deviation, 2)

        donor_area = glyph_ink_area(donor_font, glyph_name)
        if donor_area <= 0:
            continue
        instance_area = glyph_ink_area(instance_font, glyph_name)
        diff_pct = abs(instance_area - donor_area) / donor_area * 100.0
        if diff_pct > area_diff_threshold:
            area_diffs[glyph_name] = round(diff_pct, 2)

    return {
        "common_glyphs": len(common),
        "point_deviation_threshold": point_deviation_threshold,
        "area_diff_threshold_pct": area_diff_threshold,
        "mismatched_point_count": len(mismatched_points),
        "mismatched_points": mismatched_points,
        "glyphs_with_deviation": len(deviations),
        "glyphs_with_area_diff_pct": len(area_diffs),
        "deviations": deviations,
        "area_diffs_pct": area_diffs,
        "worst_deviations": dict(
            sorted(deviations.items(), key=lambda item: item[1], reverse=True)[:20]
        ),
        "worst_area_diffs_pct": dict(
            sorted(area_diffs.items(), key=lambda item: item[1], reverse=True)[:20]
        ),
    }


def build_all_glyph_master_validation_report(
    family_key: str,
    generated: dict[int, Path],
    master_records: list[dict[str, object]],
    donor_paths: dict[int, Path],
    point_deviation_threshold: float,
    area_diff_threshold: float,
    report_dir: Path,
) -> tuple[Path, dict[str, object]]:
    payload = {
        "family": family_key,
        "point_deviation_threshold": point_deviation_threshold,
        "area_diff_threshold_pct": area_diff_threshold,
        "weights": {},
    }

    for master in master_records:
        donor_path = donor_paths.get(int(master["weight"]))
        instance_path = generated.get(int(master["weight"]))
        if donor_path is None or instance_path is None:
            continue
        payload["weights"][str(master["weight"])] = compare_fonts_full(
            instance_path=instance_path,
            donor_path=donor_path,
            glyph_subset=None,
            point_deviation_threshold=point_deviation_threshold,
            area_diff_threshold=area_diff_threshold,
        )

    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{family_key}-master-validation-all.json"
    report_path.write_text(json.dumps(payload, indent=2))
    return report_path, payload


def build_all_glyph_instance_risk_report(
    family_key: str,
    generated: dict[int, Path],
    glyph_order: list[str],
    min_segment_threshold: float,
    report_dir: Path,
) -> tuple[Path, dict[str, object]]:
    payload = {
        "family": family_key,
        "glyph_count": len(glyph_order),
        "min_segment_threshold": min_segment_threshold,
        "weights": {},
    }

    for weight, instance_path in sorted(generated.items()):
        font = TTFont(instance_path)
        risky_glyphs: dict[str, dict[str, object]] = {}
        risk_type_counts: Counter[str] = Counter()

        for glyph_name in glyph_order:
            metrics = glyph_intersection_metrics(font, glyph_name)
            has_outlines = int(metrics.get("contours", 0) or 0) > 0
            min_segment = metrics.get("min_segment_length")
            has_short_segment = (
                min_segment is not None and float(min_segment) < min_segment_threshold
            )
            has_zero_ink = has_outlines and bool(metrics.get("zero_ink"))
            has_intersections = int(metrics.get("intersections", 0) or 0) > 0

            if not (has_intersections or has_zero_ink or has_short_segment):
                continue

            risky_glyphs[glyph_name] = metrics
            if has_intersections:
                risk_type_counts["intersections"] += 1
            if has_zero_ink:
                risk_type_counts["zero_ink"] += 1
            if has_short_segment:
                risk_type_counts["short_segment"] += 1

        payload["weights"][str(weight)] = {
            "instance_path": str(instance_path),
            "risky_glyph_count": len(risky_glyphs),
            "risk_type_counts": dict(risk_type_counts),
            "risky_glyphs": risky_glyphs,
        }

    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{family_key}-instance-risk-all.json"
    report_path.write_text(json.dumps(payload, indent=2))
    return report_path, payload


def build_glyph_issue_summary(
    glyph_order: list[str],
    interpolatable_payload: dict[str, list[dict[str, object]]],
    instance_payload: dict[str, object],
    validation_payload: dict[str, object],
    span_plan: dict[str, object],
    min_segment_threshold: float,
) -> tuple[dict[str, dict[str, object]], dict[str, int]]:
    interior_span_map: dict[str, list[int]] = {
        str(span["label"]): [int(weight) for weight in span["interior_weights"]]
        for span in span_plan["spans"]
    }
    interior_weight_set: set[int] = {
        weight for weights in interior_span_map.values() for weight in weights
    }
    weights_to_spans: dict[int, list[str]] = {}
    for span_label, weights in interior_span_map.items():
        for weight in weights:
            weights_to_spans.setdefault(weight, []).append(span_label)

    glyph_summary: dict[str, dict[str, object]] = {}
    summary_counts = Counter()

    for glyph_name in glyph_order:
        interpolatable_issues = interpolatable_payload.get(glyph_name, [])
        issue_types = sorted(
            Counter(str(issue.get("type", "unknown")) for issue in interpolatable_issues).items()
        )

        risky_weights: dict[str, dict[str, object]] = {}
        span_risk_weights: dict[str, list[int]] = {
            span_label: [] for span_label in interior_span_map
        }
        max_intersections = 0
        min_segment_length: float | None = None
        zero_ink_weights: list[int] = []
        intersection_weights: list[int] = []
        short_segment_weights: list[int] = []
        interior_risky_weights: list[int] = []
        interior_zero_ink_weights: list[int] = []
        interior_intersection_weights: list[int] = []
        interior_short_segment_weights: list[int] = []
        master_sample_risky_weights: list[int] = []

        for weight, payload in instance_payload.get("weights", {}).items():
            metrics = payload.get("risky_glyphs", {}).get(glyph_name)
            if not metrics:
                continue
            numeric_weight = int(weight)
            risky_weights[str(weight)] = metrics
            is_interior_weight = numeric_weight in interior_weight_set
            if is_interior_weight:
                interior_risky_weights.append(numeric_weight)
            else:
                master_sample_risky_weights.append(numeric_weight)

            intersections = int(metrics.get("intersections", 0) or 0)
            if intersections > 0:
                intersection_weights.append(numeric_weight)
                max_intersections = max(max_intersections, intersections)
                if is_interior_weight:
                    interior_intersection_weights.append(numeric_weight)

            if bool(metrics.get("zero_ink")):
                zero_ink_weights.append(numeric_weight)
                if is_interior_weight:
                    interior_zero_ink_weights.append(numeric_weight)

            value = metrics.get("min_segment_length")
            if value is not None:
                numeric_value = float(value)
                min_segment_length = (
                    numeric_value
                    if min_segment_length is None
                    else min(min_segment_length, numeric_value)
                )
                if numeric_value < min_segment_threshold:
                    short_segment_weights.append(numeric_weight)
                    if is_interior_weight:
                        interior_short_segment_weights.append(numeric_weight)

            for span_label in weights_to_spans.get(numeric_weight, []):
                span_risk_weights[span_label].append(numeric_weight)

        master_point_deviation_by_weight: dict[str, float] = {}
        master_area_diff_by_weight: dict[str, float] = {}
        mismatched_master_points: list[str] = []
        for weight, payload in validation_payload.get("weights", {}).items():
            deviation = payload.get("deviations", {}).get(glyph_name)
            if deviation is not None:
                master_point_deviation_by_weight[str(weight)] = deviation
            area_diff = payload.get("area_diffs_pct", {}).get(glyph_name)
            if area_diff is not None:
                master_area_diff_by_weight[str(weight)] = area_diff
            if glyph_name in payload.get("mismatched_points", []):
                mismatched_master_points.append(str(weight))

        has_issue = bool(
            interpolatable_issues
            or risky_weights
            or master_point_deviation_by_weight
            or master_area_diff_by_weight
            or mismatched_master_points
        )
        if not has_issue:
            continue

        severity_score = (
            len(interpolatable_issues) * 100
            + len(intersection_weights) * 40
            + len(zero_ink_weights) * 80
            + len(short_segment_weights) * 15
            + len(master_point_deviation_by_weight) * 20
            + len(master_area_diff_by_weight) * 10
            + len(mismatched_master_points) * 50
        )

        glyph_summary[glyph_name] = {
            "glyph_name": glyph_name,
            "severity_score": severity_score,
            "interpolatable": {
                "issue_count": len(interpolatable_issues),
                "issue_types": [name for name, _ in issue_types],
                "issue_type_counts": {name: count for name, count in issue_types},
                "issues": interpolatable_issues,
            },
            "sampled_instance_risk": {
                "risky_weight_count": len(risky_weights),
                "risky_weights": sorted(int(weight) for weight in risky_weights),
                "interior_risky_weight_count": len(interior_risky_weights),
                "interior_risky_weights": sorted(interior_risky_weights),
                "master_sample_risky_weights": sorted(master_sample_risky_weights),
                "span_risk_weights": {
                    span_label: weights
                    for span_label, weights in span_risk_weights.items()
                    if weights
                },
                "intersection_weights": sorted(intersection_weights),
                "interior_intersection_weights": sorted(interior_intersection_weights),
                "zero_ink_weights": sorted(zero_ink_weights),
                "interior_zero_ink_weights": sorted(interior_zero_ink_weights),
                "short_segment_weights": sorted(short_segment_weights),
                "interior_short_segment_weights": sorted(interior_short_segment_weights),
                "max_intersections": max_intersections,
                "min_segment_length": min_segment_length,
            },
            "master_validation": {
                "point_deviation_by_weight": master_point_deviation_by_weight,
                "area_diff_by_weight_pct": master_area_diff_by_weight,
                "mismatched_point_weights": mismatched_master_points,
            },
        }

        if interpolatable_issues:
            summary_counts["interpolatable_problem_glyphs"] += 1
        if risky_weights:
            summary_counts["sampled_risky_glyphs"] += 1
        if intersection_weights:
            summary_counts["glyphs_with_intersections"] += 1
        if zero_ink_weights:
            summary_counts["glyphs_with_zero_ink"] += 1
        if short_segment_weights:
            summary_counts["glyphs_with_short_segments"] += 1
        if master_point_deviation_by_weight or mismatched_master_points:
            summary_counts["master_validation_point_problem_glyphs"] += 1
        if master_area_diff_by_weight:
            summary_counts["master_validation_area_problem_glyphs"] += 1

    summary_counts["problem_glyphs"] = len(glyph_summary)
    summary_counts["clean_glyphs"] = len(glyph_order) - len(glyph_summary)
    summary_counts["total_glyphs"] = len(glyph_order)
    return glyph_summary, dict(summary_counts)


def build_interpolation_focus_summary(
    glyph_order: list[str],
    glyph_issue_summary: dict[str, dict[str, object]],
    span_plan: dict[str, object],
) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    span_labels = [str(span["label"]) for span in span_plan["spans"]]
    focus_summary: dict[str, dict[str, object]] = {}
    summary_counts = Counter()
    span_problem_counts: Counter[str] = Counter()

    for glyph_name in glyph_order:
        entry = glyph_issue_summary.get(glyph_name)
        if entry is None:
            continue

        interpolatable_entry = entry["interpolatable"]
        sampled = entry["sampled_instance_risk"]
        interior_risky_weights = sampled["interior_risky_weights"]
        if not (interpolatable_entry["issue_count"] or interior_risky_weights):
            continue

        span_risk_weights = sampled["span_risk_weights"]
        focus_severity_score = (
            int(interpolatable_entry["issue_count"]) * 100
            + len(sampled["interior_intersection_weights"]) * 40
            + len(sampled["interior_zero_ink_weights"]) * 80
            + len(sampled["interior_short_segment_weights"]) * 15
        )
        focus_summary[glyph_name] = {
            "glyph_name": glyph_name,
            "focus_severity_score": focus_severity_score,
            "interpolatable": interpolatable_entry,
            "sampled_instance_risk": {
                "interior_risky_weight_count": sampled["interior_risky_weight_count"],
                "interior_risky_weights": sampled["interior_risky_weights"],
                "span_risk_weights": span_risk_weights,
                "interior_intersection_weights": sampled["interior_intersection_weights"],
                "interior_zero_ink_weights": sampled["interior_zero_ink_weights"],
                "interior_short_segment_weights": sampled["interior_short_segment_weights"],
                "max_intersections": sampled["max_intersections"],
                "min_segment_length": sampled["min_segment_length"],
            },
        }

        if interpolatable_entry["issue_count"]:
            summary_counts["interpolatable_problem_glyphs"] += 1
        if sampled["interior_risky_weight_count"]:
            summary_counts["sampled_risky_glyphs"] += 1
        if sampled["interior_intersection_weights"]:
            summary_counts["glyphs_with_intersections"] += 1
        if sampled["interior_zero_ink_weights"]:
            summary_counts["glyphs_with_zero_ink"] += 1
        if sampled["interior_short_segment_weights"]:
            summary_counts["glyphs_with_short_segments"] += 1

        span_count = len(span_risk_weights)
        if span_count:
            summary_counts["glyphs_with_span_risk"] += 1
            if span_count == len(span_labels):
                summary_counts["glyphs_risky_in_all_spans"] += 1
            for span_label in span_risk_weights:
                span_problem_counts[span_label] += 1

    summary_counts["problem_glyphs"] = len(focus_summary)
    summary_counts["clean_glyphs"] = len(glyph_order) - len(focus_summary)
    summary_counts["total_glyphs"] = len(glyph_order)

    return focus_summary, {
        **dict(summary_counts),
        "span_problem_glyphs": {
            span_label: int(span_problem_counts.get(span_label, 0)) for span_label in span_labels
        },
    }


def build_audit_markdown(
    family_key: str,
    payload: dict[str, object],
    report_path: Path,
    top_glyphs: int,
) -> Path:
    lines = [f"# {family_key.title()} Variable Audit", ""]
    lines.append(f"- source: `{payload['source_path']}`")
    lines.append(f"- designspace: `{payload['designspace_path']}`")
    lines.append(f"- variable font: `{payload['variable_font_path']}`")
    lines.append(f"- samples per span: `{payload['samples_per_span']}`")
    lines.append(f"- sample weights: `{payload['sample_weights']}`")
    lines.append("")

    lines.append("## Spans")
    lines.append("")
    for span in payload["span_plan"]["spans"]:
        lines.append(
            "- "
            f"`{span['label']}` {span['from_master']}({span['from_weight']}) "
            f"-> {span['to_master']}({span['to_weight']}) "
            f"weights={span['weights']}"
        )
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    summary = payload["summary"]
    for key in (
        "total_glyphs",
        "problem_glyphs",
        "clean_glyphs",
        "interpolatable_problem_glyphs",
        "sampled_risky_glyphs",
        "glyphs_with_intersections",
        "glyphs_with_zero_ink",
        "glyphs_with_short_segments",
        "master_validation_point_problem_glyphs",
        "master_validation_area_problem_glyphs",
    ):
        lines.append(f"- {key}: `{summary.get(key, 0)}`")
    lines.append("")

    lines.append("## Interpolation Focus")
    lines.append("")
    interpolation_summary = payload["interpolation_focus_summary"]
    for key in (
        "total_glyphs",
        "problem_glyphs",
        "clean_glyphs",
        "interpolatable_problem_glyphs",
        "sampled_risky_glyphs",
        "glyphs_with_span_risk",
        "glyphs_risky_in_all_spans",
        "glyphs_with_intersections",
        "glyphs_with_zero_ink",
        "glyphs_with_short_segments",
    ):
        lines.append(f"- {key}: `{interpolation_summary.get(key, 0)}`")
    lines.append(
        "- span_problem_glyphs: "
        f"`{json.dumps(interpolation_summary.get('span_problem_glyphs', {}), sort_keys=True)}`"
    )
    lines.append("")

    lines.append("## Interpolatable")
    lines.append("")
    lines.append(f"- summary: `{json.dumps(payload['interpolatable_summary'], sort_keys=True)}`")
    lines.append("")

    lines.append("## Exact Masters")
    lines.append("")
    if payload.get("interpolation_only"):
        lines.append("- skipped in `--interpolation-only` mode")
    else:
        for weight, entry in sorted(
            payload["master_validation"]["weights"].items(),
            key=lambda item: int(item[0]),
        ):
            lines.append(
                "- "
                f"`wght {weight}` pointMismatch={entry['mismatched_point_count']} "
                f"deviations={entry['glyphs_with_deviation']} "
                f"areaDiffs={entry['glyphs_with_area_diff_pct']}"
            )
    lines.append("")

    lines.append("## Sampled Weights")
    lines.append("")
    for weight, entry in sorted(
        payload["instance_risk"]["weights"].items(),
        key=lambda item: int(item[0]),
    ):
        lines.append(
            "- "
            f"`wght {weight}` riskyGlyphs={entry['risky_glyph_count']} "
            f"riskTypes={json.dumps(entry['risk_type_counts'], sort_keys=True)}"
        )
    lines.append("")

    lines.append("## Interpolation Priority Glyphs")
    lines.append("")
    focus_top_entries = sorted(
        payload["interpolation_focus_glyph_summary"].values(),
        key=lambda entry: (-int(entry["focus_severity_score"]), entry["glyph_name"]),
    )[:top_glyphs]
    for entry in focus_top_entries:
        sampled = entry["sampled_instance_risk"]
        interpolatable_entry = entry["interpolatable"]
        lines.append(
            "- "
            f"`{entry['glyph_name']}` focusSeverity={entry['focus_severity_score']} "
            f"interpolatable={interpolatable_entry['issue_count']} "
            f"issueTypes={interpolatable_entry['issue_types']} "
            f"interiorWeights={sampled['interior_risky_weights']} "
            f"spanRiskWeights={json.dumps(sampled['span_risk_weights'], sort_keys=True)} "
            f"maxIntersections={sampled['max_intersections']} "
            f"minSegment={sampled['min_segment_length']}"
        )
    lines.append("")

    if not payload.get("interpolation_only"):
        lines.append("## Top Glyphs")
        lines.append("")
        top_entries = sorted(
            payload["glyph_issue_summary"].values(),
            key=lambda entry: (-int(entry["severity_score"]), entry["glyph_name"]),
        )[:top_glyphs]
        for entry in top_entries:
            sampled = entry["sampled_instance_risk"]
            master_validation = entry["master_validation"]
            interpolatable_entry = entry["interpolatable"]
            lines.append(
                "- "
                f"`{entry['glyph_name']}` severity={entry['severity_score']} "
                f"interpolatable={interpolatable_entry['issue_count']} "
                f"issueTypes={interpolatable_entry['issue_types']} "
                f"riskyWeights={sampled['risky_weights']} "
                f"maxIntersections={sampled['max_intersections']} "
                f"minSegment={sampled['min_segment_length']} "
                f"masterDeviationWeights={sorted(master_validation['point_deviation_by_weight'])} "
                f"masterAreaWeights={sorted(master_validation['area_diff_by_weight_pct'])}"
            )
        lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n")
    return report_path


def run_family_audit(
    config: ProjectConfig,
    family_key: str,
    report_dir: Path,
    build_dir: Path,
    samples_per_span: int,
    min_segment_threshold: float,
    point_deviation_threshold: float,
    area_diff_threshold: float,
    top_glyphs: int,
    interpolation_only: bool,
) -> dict[str, object]:
    style = config.styles[family_key]
    font = glyphsLib.load(str(style.source))
    span_plan = build_span_plan(font, samples_per_span=samples_per_span)

    designspace_path = export_designspace(config, family_key)

    family_report_dir = report_dir / family_key
    family_build_dir = build_dir / family_key
    family_report_dir.mkdir(parents=True, exist_ok=True)
    family_build_dir.mkdir(parents=True, exist_ok=True)

    mode_slug = audit_mode_slug(interpolation_only)
    interpolatable_report_path = (
        family_report_dir / f"{family_key}-designspace-interpolatable-{mode_slug}.json"
    )
    interpolatable_summary = run_interpolatable_designspace(
        designspace_path=designspace_path,
        report_path=interpolatable_report_path,
    )
    interpolatable_payload = json.loads(interpolatable_report_path.read_text())

    variable_font_path = family_build_dir / f"{style.source.stem}-audit-vf.ttf"
    build_variable_font(
        designspace_path=designspace_path,
        output_path=variable_font_path,
        repo_root=config.repo_root,
    )

    generated = generate_static_samples(
        variable_font_path=variable_font_path,
        weights=[int(weight) for weight in span_plan["weights"]],
        output_dir=family_build_dir / "instances",
    )

    glyph_order = glyph_order_for_font(variable_font_path)

    if interpolation_only:
        master_validation_report_path = None
        master_validation_payload = {
            "family": family_key,
            "point_deviation_threshold": point_deviation_threshold,
            "area_diff_threshold_pct": area_diff_threshold,
            "skipped": True,
            "weights": {},
        }
    else:
        master_validation_report_path, master_validation_payload = (
            build_all_glyph_master_validation_report(
                family_key=family_key,
                generated=generated,
                master_records=span_plan["masters"],
                donor_paths=donor_paths_by_weight(style),
                point_deviation_threshold=point_deviation_threshold,
                area_diff_threshold=area_diff_threshold,
                report_dir=family_report_dir,
            )
        )
    instance_risk_report_path, instance_risk_payload = build_all_glyph_instance_risk_report(
        family_key=family_key,
        generated=generated,
        glyph_order=glyph_order,
        min_segment_threshold=min_segment_threshold,
        report_dir=family_report_dir,
    )

    glyph_issue_summary, summary = build_glyph_issue_summary(
        glyph_order=glyph_order,
        interpolatable_payload=interpolatable_payload,
        instance_payload=instance_risk_payload,
        validation_payload=master_validation_payload,
        span_plan=span_plan,
        min_segment_threshold=min_segment_threshold,
    )
    interpolation_focus_glyph_summary, interpolation_focus_summary = (
        build_interpolation_focus_summary(
            glyph_order=glyph_order,
            glyph_issue_summary=glyph_issue_summary,
            span_plan=span_plan,
        )
    )

    report_summary = interpolation_focus_summary if interpolation_only else summary

    payload = {
        "family": family_key,
        "mode": mode_slug,
        "interpolation_only": interpolation_only,
        "source_path": str(style.source),
        "designspace_path": str(designspace_path),
        "variable_font_path": str(variable_font_path),
        "samples_per_span": samples_per_span,
        "sample_weights": [int(weight) for weight in span_plan["weights"]],
        "span_plan": span_plan,
        "thresholds": {
            "min_segment": min_segment_threshold,
            "point_deviation": point_deviation_threshold,
            "area_diff_pct": area_diff_threshold,
        },
        "interpolatable_report": str(interpolatable_report_path),
        "interpolatable_summary": interpolatable_summary,
        "master_validation_report": (
            str(master_validation_report_path)
            if master_validation_report_path is not None
            else None
        ),
        "master_validation": master_validation_payload,
        "instance_risk_report": str(instance_risk_report_path),
        "instance_risk": instance_risk_payload,
        "summary": report_summary,
        "comprehensive_summary": summary,
        "interpolation_focus_summary": interpolation_focus_summary,
        "glyph_issue_summary": glyph_issue_summary,
        "interpolation_focus_glyph_summary": interpolation_focus_glyph_summary,
    }

    json_report_name = (
        f"{family_key}-variable-audit.json"
        if not interpolation_only
        else f"{family_key}-variable-audit-{mode_slug}.json"
    )
    json_report_path = family_report_dir / json_report_name
    json_report_path.write_text(json.dumps(json_safe(payload), indent=2))

    markdown_report_name = (
        f"{family_key}-variable-audit.md"
        if not interpolation_only
        else f"{family_key}-variable-audit-{mode_slug}.md"
    )
    markdown_report_path = family_report_dir / markdown_report_name
    build_audit_markdown(
        family_key=family_key,
        payload=payload,
        report_path=markdown_report_path,
        top_glyphs=top_glyphs,
    )

    return {
        "family": family_key,
        "mode": mode_slug,
        "json_report": str(json_report_path),
        "markdown_report": str(markdown_report_path),
        "variable_font_path": str(variable_font_path),
        "interpolatable_summary": interpolatable_summary,
        "summary": (interpolation_focus_summary if interpolation_only else summary),
        "comprehensive_summary": summary,
        "interpolation_focus_summary": interpolation_focus_summary,
    }


def build_overview_report(
    results: dict[str, dict[str, object]],
    report_dir: Path,
    output_name: str = "audit-overview.md",
) -> Path:
    lines = ["# Variable Audit Overview", ""]
    for family_key, result in results.items():
        summary = result["summary"]
        lines.append(f"## {family_key.title()}")
        lines.append("")
        lines.append(f"- mode: `{result['mode']}`")
        lines.append(f"- json: `{result['json_report']}`")
        lines.append(f"- markdown: `{result['markdown_report']}`")
        lines.append(f"- variable font: `{result['variable_font_path']}`")
        lines.append(
            f"- interpolatable: `{json.dumps(result['interpolatable_summary'], sort_keys=True)}`"
        )
        lines.append(
            "- interpolation_focus_summary: "
            f"`{json.dumps(result['interpolation_focus_summary'], sort_keys=True)}`"
        )
        lines.append(f"- summary: `{json.dumps(summary, sort_keys=True)}`")
        lines.append("")

    report_dir.mkdir(parents=True, exist_ok=True)
    output_path = report_dir / output_name
    output_path.write_text("\n".join(lines) + "\n")
    return output_path


def summary_report_name(interpolation_only: bool) -> str:
    mode_slug = audit_mode_slug(interpolation_only)
    return (
        "audit-run-summary.json"
        if not interpolation_only
        else f"audit-run-summary-{mode_slug}.json"
    )


def overview_report_name(interpolation_only: bool) -> str:
    mode_slug = audit_mode_slug(interpolation_only)
    return "audit-overview.md" if not interpolation_only else f"audit-overview-{mode_slug}.md"


def load_existing_run_summary(summary_path: Path) -> dict[str, dict[str, object]]:
    if not summary_path.exists():
        return {}

    try:
        payload = json.loads(summary_path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Cannot merge audit summary because {summary_path} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise ValueError(
            f"Cannot merge audit summary because {summary_path} does not contain an object."
        )

    for family_key, result in payload.items():
        if not isinstance(result, dict):
            raise ValueError(
                "Cannot merge audit summary because "
                f"{summary_path} has a non-object result for {family_key!r}."
            )

    return payload


def merge_run_summary_results(
    existing: dict[str, dict[str, object]],
    updates: dict[str, dict[str, object]],
    style_order: list[str],
) -> dict[str, dict[str, object]]:
    merged = dict(existing)
    merged.update(updates)

    ordered: dict[str, dict[str, object]] = {}
    for family_key in style_order:
        if family_key in merged:
            ordered[family_key] = merged[family_key]
    for family_key, result in merged.items():
        if family_key not in ordered:
            ordered[family_key] = result

    return ordered


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    report_dir = Path(args.report_dir).resolve()
    build_dir = Path(args.build_dir).resolve()

    selected = resolve_style_keys(config, args.style)
    summary_path = report_dir / summary_report_name(args.interpolation_only)
    overview_name = overview_report_name(args.interpolation_only)

    if args.style == "all":
        existing_results: dict[str, dict[str, object]] = {}
    else:
        try:
            existing_results = load_existing_run_summary(summary_path)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    results: dict[str, dict[str, object]] = {}

    for family_key in selected:
        results[family_key] = run_family_audit(
            config=config,
            family_key=family_key,
            report_dir=report_dir,
            build_dir=build_dir,
            samples_per_span=args.samples_per_span,
            min_segment_threshold=args.min_segment_threshold,
            point_deviation_threshold=args.point_deviation_threshold,
            area_diff_threshold=args.area_diff_threshold,
            top_glyphs=args.top_glyphs,
            interpolation_only=args.interpolation_only,
        )

    summary_results = (
        results
        if args.style == "all"
        else merge_run_summary_results(existing_results, results, list(config.styles))
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(json_safe(summary_results), indent=2))
    overview_path = build_overview_report(
        summary_results,
        report_dir,
        output_name=overview_name,
    )

    for family_key, result in results.items():
        print(
            f"{family_key}: "
            f"mode={result['mode']} "
            f"json={result['json_report']} "
            f"vf={result['variable_font_path']} "
            f"summary={json.dumps(result['summary'], sort_keys=True)}"
        )

    print(f"overview={overview_path}")
    print(f"summary={summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
