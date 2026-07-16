#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

from manifest_tools import expand_manifest

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = SCRIPT_DIR.parent
DEFAULT_MANIFEST = PACKAGE_DIR / "manifests/circular-triage.json"
DEFAULT_REPORT_DIR = PACKAGE_DIR / "reports/repair"
DEFAULT_OUTPUT = DEFAULT_REPORT_DIR / "tracked-residual-review.md"
DEFAULT_SOLVER_RESULTS = PACKAGE_DIR.parent / "glyph-forge-engine" / "manifests/solver-results.json"
PRIORITY_CHOICES = ("blocker", "high", "medium", "low")
PRIORITY_RANK = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "blocker": 4,
}
FROZEN_ALLOW_FIELDS = ("allow_frozen", "allow_static_outline")
FROZEN_REASON_FIELDS = (
    "allow_frozen_reason",
    "allow_static_outline_reason",
    "frozen_outline_reason",
    "static_outline_reason",
)


def parse_repair_buckets(values: list[str] | None) -> set[str] | None:
    if values is None:
        return None

    buckets = {bucket.strip() for value in values for bucket in value.split(",") if bucket.strip()}
    return buckets or None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate tracked residual glyphs and emit a compact review packet."
    )
    parser.add_argument(
        "--family",
        choices=("roman", "italic", "all"),
        default="all",
        help="Which family to validate.",
    )
    parser.add_argument(
        "--min-priority",
        choices=PRIORITY_CHOICES,
        help="Only validate glyphs with at least this manifest priority.",
    )
    parser.add_argument(
        "--repair-bucket",
        dest="repair_buckets",
        action="append",
        help="Only validate glyphs in these repair buckets. Repeat or comma-separate values.",
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="Path to the residual manifest JSON.",
    )
    parser.add_argument(
        "--report-dir",
        default=str(DEFAULT_REPORT_DIR),
        help="Directory containing repair reports.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Markdown output path.",
    )
    parser.add_argument(
        "--solver-results",
        default=str(DEFAULT_SOLVER_RESULTS),
        help="Path to glyph-forge solver-results.json for reconstruction-required exemptions.",
    )
    parser.add_argument(
        "--max-area-drift",
        type=float,
        default=25.0,
        help="Fail when a tracked glyph exceeds this exact-master area drift percentage.",
    )
    parser.add_argument(
        "--min-segment-threshold",
        type=float,
        default=0.0,
        help="Optional minimum sampled segment threshold. Set above 0 to enforce.",
    )
    args = parser.parse_args()
    raw_repair_buckets = args.repair_buckets
    args.repair_buckets = parse_repair_buckets(args.repair_buckets)
    if raw_repair_buckets is not None and args.repair_buckets is None:
        parser.error("--repair-bucket requires at least one non-empty bucket")
    return args


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def load_solver_results(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    payload = load_json(path)
    return payload if isinstance(payload, dict) else {}


def priority_matches(manifest_entry: dict[str, object], min_priority: str | None) -> bool:
    if min_priority is None:
        return True

    priority = manifest_entry.get("priority")
    priority_rank = PRIORITY_RANK.get(str(priority)) if priority is not None else None
    return priority_rank is not None and priority_rank >= PRIORITY_RANK[min_priority]


def repair_bucket_matches(
    manifest_entry: dict[str, object],
    repair_buckets: set[str] | None,
) -> bool:
    if repair_buckets is None:
        return True
    return manifest_entry.get("repair_bucket") in repair_buckets


def frozen_outline_allowance(manifest_entry: dict[str, object]) -> tuple[bool, bool]:
    explicitly_allowed = any(manifest_entry.get(field) is True for field in FROZEN_ALLOW_FIELDS)
    if not explicitly_allowed:
        return False, False

    has_reason = any(
        bool(str(manifest_entry.get(field, "")).strip()) for field in FROZEN_REASON_FIELDS
    )
    return has_reason, not has_reason


def build_family_review(
    family_key: str,
    manifest: dict[str, object],
    report_dir: Path,
    max_area_drift: float,
    min_segment_threshold: float,
    min_priority: str | None,
    repair_buckets: set[str] | None,
    solver_results: dict[str, object],
) -> tuple[list[str], dict[str, int], list[str]]:
    source_payload = load_json(report_dir / f"{family_key}-source-report.json")
    interpolatable_payload = load_json(report_dir / f"{family_key}-designspace-interpolatable.json")
    instance_payload = load_json(report_dir / f"{family_key}-instance-risk-report.json")
    validation_payload = load_json(report_dir / f"{family_key}-master-validation.json")

    source_index = {entry["glyph_name"]: entry for entry in source_payload["glyphs"]}
    tracked = manifest[family_key]["glyphs"]
    lines = [f"## {family_key.title()}", ""]
    counts = {
        "tracked": 0,
        "reconstruction_required": 0,
        "frozen": 0,
        "interpolatable": 0,
        "area_drift_failures": 0,
        "min_segment_failures": 0,
        "source_structure_failures": 0,
    }
    failures: list[str] = []

    for glyph_name in sorted(tracked):
        entry = source_index.get(glyph_name)
        manifest_entry = tracked[glyph_name]
        if not priority_matches(manifest_entry, min_priority) or not repair_bucket_matches(
            manifest_entry,
            repair_buckets,
        ):
            continue
        if not entry:
            failures.append(f"{family_key}:{glyph_name}: missing source report entry")
            continue

        counts["tracked"] += 1
        manifest_marks_reconstruction = (
            manifest_entry.get("strategy") == "manual_review"
            and manifest_entry.get("repair_bucket") == "reconstruction_required"
        )
        solver_entry = solver_results.get(f"{family_key}/{glyph_name}")
        solver_marks_reconstruction = (
            isinstance(solver_entry, dict) and solver_entry.get("requiresReconstruction") is True
        )
        is_reconstruction_required = manifest_marks_reconstruction and solver_marks_reconstruction
        if manifest_marks_reconstruction and not solver_marks_reconstruction:
            failures.append(
                f"{family_key}:{glyph_name}: manifest marks reconstruction but solver does not"
            )
        if is_reconstruction_required:
            counts["reconstruction_required"] += 1
        issues = interpolatable_payload.get(glyph_name, [])
        risky_weights = []
        min_segment = None
        for weight, payload in instance_payload.get("weights", {}).items():
            metrics = payload.get("risky_glyphs", {}).get(glyph_name)
            if not metrics:
                continue
            risky_weights.append(int(weight))
            value = metrics.get("min_segment_length")
            if value is not None:
                min_segment = value if min_segment is None else min(min_segment, value)

        area_diffs = []
        for payload in validation_payload.get("weights", {}).values():
            value = payload.get("worst_area_diffs_pct", {}).get(glyph_name)
            if value is not None:
                area_diffs.append(float(value))
        max_area = max(area_diffs) if area_diffs else None

        source_path_order_issues = int(entry.get("source_path_order_issues") or 0)
        source_node_count_issues = int(entry.get("source_node_count_issues") or 0)
        source_start_issues = int(entry.get("source_start_issues") or 0)
        source_direction_issues = int(entry.get("source_direction_issues") or 0)
        source_structure_total = (
            source_path_order_issues
            + source_node_count_issues
            + source_start_issues
            + source_direction_issues
        )

        frozen_allowed = False
        if entry.get("same_outline_across_masters"):
            counts["frozen"] += 1
            frozen_allowed, missing_frozen_reason = frozen_outline_allowance(manifest_entry)
            if not frozen_allowed:
                message = f"{family_key}:{glyph_name}: exact-outline frozen"
                if missing_frozen_reason:
                    message += " (allowlist reason required)"
                failures.append(message)
        if issues:
            counts["interpolatable"] += 1
            if not is_reconstruction_required:
                failures.append(f"{family_key}:{glyph_name}: interpolatable={len(issues)}")
        if source_structure_total > 0:
            if not is_reconstruction_required:
                counts["source_structure_failures"] += 1
                failures.append(
                    f"{family_key}:{glyph_name}: source structure "
                    f"pathOrder={source_path_order_issues} "
                    f"nodeCount={source_node_count_issues} "
                    f"start={source_start_issues} "
                    f"direction={source_direction_issues}"
                )
        if (
            not is_reconstruction_required
            and not frozen_allowed
            and max_area is not None
            and max_area > max_area_drift
        ):
            counts["area_drift_failures"] += 1
            failures.append(f"{family_key}:{glyph_name}: area drift {round(max_area, 2)}%")
        if (
            not is_reconstruction_required
            and not frozen_allowed
            and min_segment_threshold > 0
            and min_segment is not None
            and min_segment < min_segment_threshold
        ):
            counts["min_segment_failures"] += 1
            failures.append(f"{family_key}:{glyph_name}: min segment {round(min_segment, 2)}")

        manifest_strategy = manifest_entry.get("strategy")
        source_strategy = entry.get("strategy")
        strategy_note = source_strategy
        if manifest_strategy and manifest_strategy != source_strategy:
            strategy_note = f"{source_strategy}->{manifest_strategy}"

        lines.append(
            "- "
            f"`{glyph_name}` strategy={strategy_note} class={entry['classification']} "
            f"group={entry.get('group_name') or manifest_entry.get('group_name')} "
            f"inherits={entry.get('inherits_from') or manifest_entry.get('inherits_from')} "
            f"brace={entry.get('generated_brace_weights', [])} "
            f"frozen={entry['same_outline_across_masters']} "
            f"interpolatable={len(issues)} "
            f"sourceAudit={source_path_order_issues}/{source_node_count_issues}"
            f"/{source_start_issues}/{source_direction_issues} "
            f"riskyWeights={risky_weights} "
            f"maxAreaDrift={None if max_area is None else round(max_area, 2)}"
        )

    lines.append("")
    lines.append(
        "- summary: "
        f"tracked={counts['tracked']} "
        f"reconstructionRequired={counts['reconstruction_required']} "
        f"frozen={counts['frozen']} "
        f"interpolatable={counts['interpolatable']} "
        f"sourceStructureFailures={counts['source_structure_failures']} "
        f"areaDriftFailures={counts['area_drift_failures']} "
        f"minSegmentFailures={counts['min_segment_failures']}"
    )
    lines.append("")
    return lines, counts, failures


def main() -> int:
    args = parse_args()
    manifest = expand_manifest(Path(args.manifest))
    report_dir = Path(args.report_dir)
    output_path = Path(args.output)
    solver_results = load_solver_results(Path(args.solver_results))

    selected = ["roman", "italic"] if args.family == "all" else [args.family]
    lines = ["# Tracked Residual Review", ""]
    all_failures: list[str] = []
    counts_by_family: dict[str, dict[str, int]] = {}

    for family_key in selected:
        family_lines, family_counts, failures = build_family_review(
            family_key=family_key,
            manifest=manifest,
            report_dir=report_dir,
            max_area_drift=args.max_area_drift,
            min_segment_threshold=args.min_segment_threshold,
            min_priority=args.min_priority,
            repair_buckets=args.repair_buckets,
            solver_results=solver_results,
        )
        lines.extend(family_lines)
        all_failures.extend(failures)
        counts_by_family[family_key] = family_counts

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n")

    # Authoritative machine-readable verdict for the pipeline aggregator.
    # The markdown summary only exposes a subset of failure categories, so a
    # consumer that re-derives pass/fail from it can miss interpolatable and
    # disallowed-frozen failures and report a false green. This sidecar is the
    # single source of truth: status mirrors this script's exit code exactly.
    verdict_path = output_path.with_suffix(".json")
    verdict_path.write_text(
        json.dumps(
            {
                "status": "fail" if all_failures else "pass",
                "failure_count": len(all_failures),
                "failures": all_failures,
                "counts_by_family": counts_by_family,
                "thresholds": {
                    "max_area_drift": args.max_area_drift,
                    "min_segment_threshold": args.min_segment_threshold,
                },
            },
            indent=2,
        )
        + "\n"
    )

    if all_failures:
        print("Residual validation failures:")
        for failure in all_failures:
            print(f"  - {failure}")
        print(f"review={output_path}")
        return 1
    print(f"review={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
