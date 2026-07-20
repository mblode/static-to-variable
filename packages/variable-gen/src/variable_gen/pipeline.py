from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__
from .common import display_path, write_json_report


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
        _repair_stage(repo_root),
        _audit_stage(repo_root),
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


def _repair_stage(repo_root: Path) -> Stage:
    path = repo_root / "packages/variable-gen/reports/reconstruction-report.json"
    data, error = _read_json(path)
    if error:
        return _invalid_stage("repair_build", "Compatible Master Rebuild", "blocking", path, error)
    if data is None:
        return _missing_stage("repair_build", "Compatible Master Rebuild", "blocking", path)

    failures: list[str] = []
    summary: dict[str, Any] = {}
    if not data:
        failures.append("reconstruction report contains no styles")
    for style_key, stats in data.items():
        if not isinstance(stats, dict):
            failures.append(f"{style_key} rebuild stats malformed")
            continue
        for key in ("donor", "reconstructed", "sampled", "frozen"):
            summary[f"{style_key}_{key}"] = stats.get(key, 0)
        frozen_incompatible = stats.get("frozen_incompatible") or []
        summary[f"{style_key}_frozen_incompatible"] = len(frozen_incompatible)

    return Stage(
        id="repair_build",
        name="Compatible Master Rebuild",
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
    for family_key, family in data.items():
        family_summary = family.get("summary", {}) if isinstance(family, dict) else {}
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


def _display_path(path: Path, repo_root: Path) -> str:
    return display_path(path, repo_root)
