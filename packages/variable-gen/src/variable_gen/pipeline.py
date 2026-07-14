from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__
from .common import display_path, resolve_artifact_path, write_json_report

STRATEGY_RIGOUR = {
    "manual_review": 0,
    "reference_fallback": 1,
    "weighted_fallback": 2,
    "inherit_base_contours": 3,
    "structural_fallback": 4,
    "donor_copy": 5,
    "rebuild_notdef": 6,
}

# Minimum solver-projected gain for an "upgrade" to be a worth-acting-on
# automatic decision. A more-rigorous suggestion that the solver projects no
# meaningful improvement from is not actionable, so it must not block promotion.
# Matches the default `--min-gain` of bulk_stage / forge:converge.
AUTOMATIC_MIN_GAIN = 0.1


@dataclass(frozen=True)
class Stage:
    id: str
    name: str
    kind: str
    status: str
    blocking: bool
    artifact: str
    summary: dict[str, Any]
    failures: list[str]
    observations: list[str] = field(default_factory=list)


def build_pipeline_status(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    stages = [
        _inventory_stage(repo_root),
        _raw_compatibility_stage(repo_root),
        _repair_stage(repo_root),
        _audit_stage(repo_root),
        _residual_stage(repo_root),
        _glyph_forge_stage(repo_root),
    ]
    blocking_failures = [stage for stage in stages if stage.blocking and stage.status != "pass"]
    return {
        "schema": "static_to_variable.pipeline_status.v1",
        "schema_version": 1,
        "generator": {
            "name": "variable_gen.pipeline",
            "version": __version__,
        },
        "report_type": "pipeline_status",
        "verdict": "fail" if blocking_failures else "pass",
        "hard_gates": {
            "status": "fail" if blocking_failures else "pass",
            "fields": {
                "blocking_failure_count": len(blocking_failures),
            },
            "blocking_reasons": [
                {
                    "field": "stage_status",
                    "value": stage.status,
                    "threshold": "pass",
                    "message": f"{stage.id} must pass before promotion.",
                }
                for stage in blocking_failures
            ],
        },
        "summary": {
            "stage_count": len(stages),
            "blocking_stage_count": sum(1 for stage in stages if stage.blocking),
            "blocking_failure_count": len(blocking_failures),
            "diagnostic_failure_count": sum(
                1 for stage in stages if not stage.blocking and stage.status != "pass"
            ),
            "diagnostic_observation_count": sum(
                1 for stage in stages if not stage.blocking and stage.observations
            ),
        },
        "stages": [_stage_payload(stage, repo_root) for stage in stages],
    }


def write_pipeline_status(report: dict[str, Any], output_path: str | Path) -> Path:
    return write_json_report(report, output_path)


def write_pipeline_markdown(report: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Static to variable pipeline status",
        "",
        f"- verdict: `{report['verdict']}`",
        f"- stages: `{report['summary']['stage_count']}`",
        f"- blocking failures: `{report['summary']['blocking_failure_count']}`",
        f"- diagnostic failures: `{report['summary']['diagnostic_failure_count']}`",
        f"- diagnostic observations: `{report['summary'].get('diagnostic_observation_count', 0)}`",
        "",
        "## Stages",
        "",
    ]
    for stage in report["stages"]:
        lines.extend(
            [
                f"### {stage['name']}",
                "",
                f"- id: `{stage['id']}`",
                f"- kind: `{stage['kind']}`",
                f"- status: `{stage['status']}`",
                f"- blocking: `{stage['blocking']}`",
                f"- artifact: `{stage['artifact']}`",
            ]
        )
        if stage["failures"]:
            lines.append("- failures:")
            lines.extend(f"  - {failure}" for failure in stage["failures"])
        if stage["observations"]:
            lines.append("- observations:")
            lines.extend(f"  - {observation}" for observation in stage["observations"])
        if stage["summary"]:
            lines.append("- summary:")
            for key, value in stage["summary"].items():
                lines.append(f"  - `{key}`: `{value}`")
        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n")
    return path


def _inventory_stage(repo_root: Path) -> Stage:
    path = repo_root / "packages/variable-gen/reports/donor-inventory.json"
    data, error = _read_json(path)
    if error:
        return _invalid_stage("inventory", "Donor Inventory", "blocking", path, error)
    if data is None:
        return _missing_stage("inventory", "Donor Inventory", "blocking", path)
    status = data.get("hard_gates", {}).get("status", "fail")
    summary = dict(data.get("summary", {}))
    return Stage(
        id="inventory",
        name="Donor Inventory",
        kind="blocking",
        status=status,
        blocking=True,
        artifact=path.as_posix(),
        summary=summary,
        failures=_blocking_reasons(data),
    )


def _raw_compatibility_stage(repo_root: Path) -> Stage:
    path = repo_root / "packages/variable-gen/reports/compatibility-raw.json"
    data, error = _read_json(path)
    if error:
        return _invalid_stage(
            "raw_compatibility",
            "Raw Donor Compatibility",
            "diagnostic",
            path,
            error,
            blocking=False,
        )
    if data is None:
        return _missing_stage(
            "raw_compatibility",
            "Raw Donor Compatibility",
            "diagnostic",
            path,
            blocking=False,
        )
    summary = dict(data.get("summary", {}))
    observations = _blocking_reasons(data)
    return Stage(
        id="raw_compatibility",
        name="Raw Donor Compatibility",
        kind="diagnostic",
        status="pass",
        blocking=False,
        artifact=path.as_posix(),
        summary=summary,
        failures=[],
        observations=observations,
    )


def _repair_stage(repo_root: Path) -> Stage:
    path = repo_root / "packages/variable-gen/reports/repair/repair-run-summary.json"
    data, error = _read_json(path)
    if error:
        return _invalid_stage("repair_build", "Strict Compatibility Build", "blocking", path, error)
    if data is None:
        return _missing_stage("repair_build", "Strict Compatibility Build", "blocking", path)

    failures: list[str] = []
    summary: dict[str, Any] = {}
    for family_key in ("roman", "italic"):
        family = data.get(family_key, {})
        strict = family.get("strict_audit_counts", {})
        summary[f"{family_key}_strict"] = strict
        variable_font = family.get("variable_font_path")
        summary[f"{family_key}_variable_font"] = variable_font
        for key in ("path_order", "node_count", "start", "post_write_mismatches"):
            value = int(strict.get(key, 0) or 0)
            if value:
                failures.append(f"{family_key} strict {key}={value}")
        if not variable_font or not resolve_artifact_path(repo_root, variable_font).exists():
            failures.append(f"{family_key} variable font missing")

    return Stage(
        id="repair_build",
        name="Strict Compatibility Build",
        kind="blocking",
        status="fail" if failures else "pass",
        blocking=True,
        artifact=path.as_posix(),
        summary=summary,
        failures=failures,
    )


def _audit_stage(repo_root: Path) -> Stage:
    path = repo_root / "packages/variable-gen/reports/audit/audit-run-summary.json"
    data, error = _read_json(path)
    if error:
        return _invalid_stage(
            "full_audit",
            "Full Variable Audit Diagnostics",
            "diagnostic",
            path,
            error,
            blocking=False,
        )
    if data is None:
        return _missing_stage(
            "full_audit",
            "Full Variable Audit Diagnostics",
            "diagnostic",
            path,
            blocking=False,
        )

    failures: list[str] = []
    summary: dict[str, Any] = {}
    for family_key in ("roman", "italic"):
        family_summary = data.get(family_key, {}).get("summary", {})
        problem_glyphs = int(family_summary.get("problem_glyphs", 0) or 0)
        summary[f"{family_key}_problem_glyphs"] = problem_glyphs
        summary[f"{family_key}_clean_glyphs"] = family_summary.get("clean_glyphs", 0)
        summary[f"{family_key}_interpolatable_problem_glyphs"] = family_summary.get(
            "interpolatable_problem_glyphs",
            0,
        )
        if problem_glyphs:
            failures.append(f"{family_key} problem_glyphs={problem_glyphs}")

    return Stage(
        id="full_audit",
        name="Full Variable Audit Diagnostics",
        kind="diagnostic",
        status="pass",
        blocking=False,
        artifact=path.as_posix(),
        summary=summary,
        failures=[],
        observations=failures,
    )


def _residual_stage(repo_root: Path) -> Stage:
    path = repo_root / "packages/variable-gen/reports/repair/blocker-residual-validation.md"
    verdict_path = path.with_suffix(".json")

    # Prefer the validator's authoritative JSON verdict. Its `status` mirrors the
    # validator's own exit code, so the gate cannot report `pass` for failures
    # (interpolatable errors, disallowed-frozen glyphs) that the markdown summary
    # does not surface as one of its three counter fields.
    if verdict_path.exists():
        verdict, error = _read_json(verdict_path)
        if error:
            return _invalid_stage(
                "blocker_residuals",
                "Blocker Residual Validation",
                "blocking",
                verdict_path,
                error,
            )
        failures = list(verdict.get("failures", []))
        summary: dict[str, int] = {
            "failure_count": int(verdict.get("failure_count", len(failures)))
        }
        for family, family_counts in (verdict.get("counts_by_family") or {}).items():
            for key, value in family_counts.items():
                summary[f"{family}_{key}"] = int(value)
        status = "fail" if (verdict.get("status") == "fail" or failures) else "pass"
        return Stage(
            id="blocker_residuals",
            name="Blocker Residual Validation",
            kind="blocking",
            status=status,
            blocking=True,
            artifact=path.as_posix(),
            summary=summary,
            failures=failures,
        )

    if not path.exists():
        return _missing_stage("blocker_residuals", "Blocker Residual Validation", "blocking", path)

    # Backward-compatible fallback: parse the markdown summary. Hardened to also
    # fail on `interpolatable`, which the validator treats as a hard failure.
    text = path.read_text()
    failures = []
    summary = {}
    summary_lines = _summary_lines(text)
    for expected_family in ("roman", "italic"):
        if expected_family not in summary_lines:
            failures.append(f"{expected_family} summary missing")

    for family, line in summary_lines.items():
        parsed = _parse_key_values(line)
        for key in (
            "sourceStructureFailures",
            "areaDriftFailures",
            "minSegmentFailures",
            "interpolatable",
        ):
            value = int(parsed.get(key, 0))
            summary[f"{family}_{key}"] = value
            if value:
                failures.append(f"{family} {key}={value}")
        summary[f"{family}_frozen"] = int(parsed.get("frozen", 0))

    return Stage(
        id="blocker_residuals",
        name="Blocker Residual Validation",
        kind="blocking",
        status="fail" if failures else "pass",
        blocking=True,
        artifact=path.as_posix(),
        summary=summary,
        failures=failures,
    )


def _glyph_forge_stage(repo_root: Path) -> Stage:
    manifest_path = repo_root / "packages/glyph-forge-engine/manifests/broken-glyphs.json"
    scores_path = repo_root / "packages/glyph-forge-engine/manifests/glyph-scores.json"
    solver_path = repo_root / "packages/glyph-forge-engine/manifests/solver-results.json"
    suggestions_path = repo_root / "packages/glyph-forge-engine/manifests/strategy-suggestions.json"
    broken_glyphs, broken_error = _read_json(manifest_path)
    glyph_scores, scores_error = _read_json(scores_path)
    solver_results, solver_error = _read_json(solver_path)
    suggestions, suggestions_error = _read_json(suggestions_path)
    parse_error = broken_error or scores_error or solver_error or suggestions_error
    if parse_error:
        return _invalid_stage(
            "glyph_forge",
            "Glyph QA",
            "blocking",
            manifest_path,
            parse_error,
        )
    if (
        broken_glyphs is None
        or glyph_scores is None
        or solver_results is None
        or suggestions is None
    ):
        return _missing_stage(
            "glyph_forge",
            "Glyph QA",
            "blocking",
            manifest_path,
        )

    verdict_counts = Counter(item.get("auditVerdict", "unknown") for item in broken_glyphs)
    solver_gain_count = sum(1 for item in solver_results.values() if (item.get("gain") or 0) > 0.1)
    failures: list[str] = []
    reconstruction_required = [
        item for item in broken_glyphs if _requires_reconstruction(item, solver_results)
    ]
    unresolved_reconstruction = [
        item for item in reconstruction_required if item.get("existingStrategy") != "manual_review"
    ]
    automatic_candidates = []
    automatic_action_counts: Counter[str] = Counter()
    for item in broken_glyphs:
        action_kind = _automatic_decision_kind(item, solver_results, suggestions)
        if action_kind is None:
            continue
        automatic_candidates.append(item)
        automatic_action_counts[action_kind] += 1
    automatic_verdict_counts = Counter(
        item.get("auditVerdict", "unknown") for item in automatic_candidates
    )
    blocker_count = int(verdict_counts.get("blocker", 0))
    unknown_count = int(verdict_counts.get("unknown", 0))
    unresolved_blocker_count = int(automatic_verdict_counts.get("blocker", 0))
    unresolved_unknown_count = int(automatic_verdict_counts.get("unknown", 0))
    automatic_candidate_count = len(automatic_candidates)
    unresolved_reconstruction_count = len(unresolved_reconstruction)
    if automatic_candidate_count:
        failures.append(f"unapplied automatic glyph decisions={automatic_candidate_count}")
    if unresolved_reconstruction_count:
        failures.append(
            f"unresolved reconstruction-required glyphs={unresolved_reconstruction_count}"
        )

    return Stage(
        id="glyph_forge",
        name="Glyph QA",
        kind="blocking",
        status="fail" if failures else "pass",
        blocking=True,
        artifact=manifest_path.as_posix(),
        summary={
            "broken_glyph_count": len(broken_glyphs),
            "glyph_score_count": len(glyph_scores),
            "solver_result_count": len(solver_results),
            "solver_gain_gt_0_1": solver_gain_count,
            "blocking_verdict_counts": {
                "blocker": blocker_count,
                "unknown": unknown_count,
            },
            "unresolved_blocking_verdict_counts": {
                "blocker": unresolved_blocker_count,
                "unknown": unresolved_unknown_count,
            },
            "triaged_blocking_verdict_count": blocker_count
            + unknown_count
            - unresolved_blocker_count
            - unresolved_unknown_count,
            "automatic_decision_candidate_count": automatic_candidate_count,
            "automatic_decision_action_counts": {
                str(key): value for key, value in sorted(automatic_action_counts.items())
            },
            "automatic_decision_verdict_counts": {
                str(key): value for key, value in sorted(automatic_verdict_counts.items())
            },
            "reconstruction_required_count": len(reconstruction_required),
            "unresolved_reconstruction_required_count": unresolved_reconstruction_count,
            "backlog_verdict_counts": {
                key: value
                for key, value in sorted(verdict_counts.items())
                if key not in {"blocker", "unknown"}
            },
        },
        failures=failures,
    )


def _requires_reconstruction(
    item: dict[str, Any],
    solver_results: dict[str, Any],
) -> bool:
    key = f"{item.get('family')}/{item.get('name')}"
    solver = solver_results.get(key, {})
    return bool(solver.get("requiresReconstruction") is True)


def _automatic_decision_kind(
    item: dict[str, Any],
    solver_results: dict[str, Any],
    suggestions: dict[str, Any],
) -> str | None:
    if _requires_reconstruction(item, solver_results):
        return None

    family = item.get("family")
    name = item.get("name")
    if not family or not name:
        return None

    current = item.get("existingStrategy")
    if current and (item.get("allowFrozen") is True or item.get("allowStaticOutline") is True):
        return None

    suggestion = suggestions.get(f"{family}/{name}")
    if not isinstance(suggestion, dict):
        return "untriaged" if not current else None

    proposed = suggestion.get("strategy")
    if not isinstance(proposed, str) or proposed == "manual_review":
        return "untriaged" if not current else None

    if not isinstance(current, str) or not current:
        return "untriaged"

    current_rigour = STRATEGY_RIGOUR.get(current, -1)
    proposed_rigour = STRATEGY_RIGOUR.get(proposed, -1)
    if proposed_rigour > current_rigour:
        # Only actionable if the solver projects a meaningful gain. A
        # higher-rigour suggestion with no projected benefit is a treadmill, not
        # a decision, and must not block promotion forever.
        solver_entry = solver_results.get(f"{family}/{name}")
        gain = solver_entry.get("gain") if isinstance(solver_entry, dict) else None
        if gain is not None and gain <= AUTOMATIC_MIN_GAIN:
            return None
        return "upgrade"
    return None


def _missing_stage(
    stage_id: str,
    name: str,
    kind: str,
    path: Path,
    blocking: bool = True,
) -> Stage:
    return Stage(
        id=stage_id,
        name=name,
        kind=kind,
        status="missing",
        blocking=blocking,
        artifact=path.as_posix(),
        summary={},
        failures=[f"missing artifact: {path}"],
        observations=[],
    )


def _invalid_stage(
    stage_id: str,
    name: str,
    kind: str,
    path: Path,
    error: str,
    blocking: bool = True,
) -> Stage:
    return Stage(
        id=stage_id,
        name=name,
        kind=kind,
        status="invalid",
        blocking=blocking,
        artifact=path.as_posix(),
        summary={},
        failures=[f"invalid artifact: {path}: {error}"] if blocking else [],
        observations=[f"invalid artifact: {path}: {error}"] if not blocking else [],
    )


def _stage_payload(stage: Stage, repo_root: Path) -> dict[str, Any]:
    return {
        "id": stage.id,
        "name": stage.name,
        "kind": stage.kind,
        "status": stage.status,
        "blocking": stage.blocking,
        "artifact": _display_path(Path(stage.artifact), repo_root),
        "summary": stage.summary,
        "failures": stage.failures,
        "observations": stage.observations or [],
    }


def _read_json(path: Path) -> tuple[Any | None, str | None]:
    if not path.exists():
        return None, None
    try:
        return json.loads(path.read_text()), None
    except json.JSONDecodeError as exc:
        return None, str(exc)


def _blocking_reasons(data: dict[str, Any]) -> list[str]:
    reasons = data.get("hard_gates", {}).get("blocking_reasons", [])
    return [
        f"{reason.get('field')}={reason.get('value')} threshold={reason.get('threshold')}"
        for reason in reasons
    ]


def _summary_lines(text: str) -> dict[str, str]:
    current_family: str | None = None
    summaries: dict[str, str] = {}
    for line in text.splitlines():
        if line == "## Roman":
            current_family = "roman"
        elif line == "## Italic":
            current_family = "italic"
        elif current_family and line.startswith("- summary:"):
            summaries[current_family] = line
    return summaries


def _parse_key_values(line: str) -> dict[str, int]:
    return {key: int(value) for key, value in re.findall(r"([A-Za-z]+)=([0-9]+)", line)}


def _display_path(path: Path, repo_root: Path) -> str:
    return display_path(path, repo_root)
