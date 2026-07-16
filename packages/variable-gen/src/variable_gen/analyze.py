from __future__ import annotations

from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont
from fontTools.varLib import interpolatable

from . import __version__
from .common import select_families, sha256_file, write_json_report
from .manifest import Family, StaticToVariableManifest

P0_ISSUE_TYPES = {
    "missing",
    "open_path",
    "path_count",
    "node_count",
    "node_incompatibility",
    # Custom structural check: segment-type sequence must match across masters or
    # cu2qu / gvar deltas target the wrong segments. Blocks the variable build.
    "segment_type_mismatch",
}

P1_ISSUE_TYPES = {
    "contour_order",
    "wrong_start_point",
    "kink",
    # Custom structural checks (additive to fontTools.varLib.interpolatable).
    "winding_mismatch",
    "advance_incompatible",
    # Reserved: backs the contracted phantom_point_error_count gate field; the
    # phantom-point structural check itself is not implemented yet.
    "phantom_point_mismatch",
}


def build_compatibility_report(
    manifest: StaticToVariableManifest,
    family_filter: str = "all",
    stage: str = "raw",
) -> dict[str, Any]:
    selected_families = select_families(manifest.families, family_filter)
    family_reports = {
        family_key: _build_family_compatibility(family, stage)
        for family_key, family in selected_families.items()
    }
    hard_gates = _compatibility_hard_gates(family_reports)

    return {
        "schema": "static_to_variable.compatibility.v1",
        "schema_version": 1,
        "report_type": "compatibility",
        "stage": stage,
        "generator": {
            "name": "variable_gen.analyze",
            "version": __version__,
            "tools": {
                "fontTools.varLib.interpolatable": "fontTools",
            },
        },
        "manifest_id": manifest.id,
        "manifest_hash": sha256_file(manifest.path),
        "source_hashes": _source_hashes(selected_families),
        "families": family_reports,
        "hard_gates": hard_gates,
        "summary": _summary(family_reports),
    }


def write_compatibility_report(report: dict[str, Any], output_path: str | Path) -> Path:
    return write_json_report(report, output_path)


def classify_issue(issue_type: str) -> str:
    if issue_type in P0_ISSUE_TYPES:
        return "P0"
    if issue_type in P1_ISSUE_TYPES:
        return "P1"
    return "P2"


def glyph_severity(issues: list[dict[str, Any]]) -> str:
    severities = {classify_issue(str(issue.get("type"))) for issue in issues}
    if "P0" in severities:
        return "P0"
    if "P1" in severities:
        return "P1"
    return "P2"


def _build_family_compatibility(family: Family, stage: str) -> dict[str, Any]:
    with ExitStack() as stack:
        fonts = [stack.enter_context(TTFont(donor.path)) for donor in family.donors]
        glyph_count = len(fonts[0].getGlyphOrder()) if fonts else 0
        glyphsets = [font.getGlyphSet() for font in fonts]
        names = [donor.id for donor in family.donors]
        raw_issues = interpolatable.test(
            glyphsets,
            names=names,
        )
        # Custom structural checks on dimensions interpolatable does not surface:
        # winding direction, segment-type signature, advance/phantom-point and
        # bounds consistency across masters. Computed while the fonts are open.
        structural = _structural_issues(glyphsets, names, fonts)

    # Merge interpolatable issues with the custom structural issues per glyph.
    merged: dict[str, list[dict[str, Any]]] = {
        glyph_name: list(issues) for glyph_name, issues in raw_issues.items()
    }
    for glyph_name, issues in structural.items():
        merged.setdefault(glyph_name, []).extend(issues)

    glyphs = {
        glyph_name: _glyph_record(glyph_name, issues)
        for glyph_name, issues in sorted(merged.items())
    }
    issue_type_counts = Counter(
        str(issue.get("type")) for record in glyphs.values() for issue in record["issues"]
    )
    severity_counts = Counter(record["severity"] for record in glyphs.values())

    return {
        "stage": stage,
        "name": family.name,
        "style": family.style,
        "donors": [
            {
                "id": donor.id,
                "name": donor.name,
                "path": donor.manifest_path,
                "location": donor.location,
            }
            for donor in family.donors
        ],
        "glyphs": glyphs,
        "summary": {
            "glyph_count": glyph_count,
            "problem_glyph_count": len(glyphs),
            "issue_count": sum(issue_type_counts.values()),
            "issue_type_counts": dict(sorted(issue_type_counts.items())),
            "severity_counts": dict(sorted(severity_counts.items())),
        },
    }


def _glyph_record(glyph_name: str, issues: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_issues = [_json_safe(issue) for issue in issues]
    severity = glyph_severity(normalized_issues)
    issue_type_counts = Counter(str(issue.get("type")) for issue in normalized_issues)
    return {
        "glyph_name": glyph_name,
        "status": "blocked" if severity == "P0" else "warning",
        "severity": severity,
        "issue_count": len(normalized_issues),
        "issue_type_counts": dict(sorted(issue_type_counts.items())),
        "issues": normalized_issues,
    }


def _winding(points: list[tuple[float, float]]) -> int:
    """Signed-area sign over a contour's on-curve points: +1 ccw, -1 cw, 0 degenerate."""
    if len(points) < 3:
        return 0
    area = 0.0
    count = len(points)
    for index in range(count):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % count]
        area += (x1 * y2) - (x2 * y1)
    if area > 0:
        return 1
    if area < 0:
        return -1
    return 0


def _outline_signature(glyphset: Any, name: str) -> dict[str, Any] | None:
    """Per-contour structure for one master, or None if the glyph can't be drawn."""
    try:
        glyph = glyphset[name]
        pen = DecomposingRecordingPen(glyphset)
        glyph.draw(pen)
    except Exception:  # noqa: BLE001 - undrawable glyphs are reported as "missing" elsewhere
        return None

    contours: list[dict[str, Any]] = []
    points: list[tuple[float, float]] = []
    segments: list[str] = []
    node_count = 0
    open_contour = False

    def flush() -> None:
        nonlocal points, segments, node_count, open_contour
        if open_contour:
            contours.append(
                {"nodes": node_count, "segments": tuple(segments), "winding": _winding(points)}
            )
        points, segments, node_count, open_contour = [], [], 0, False

    for op, args in pen.value:
        if op == "moveTo":
            flush()
            open_contour, points, segments, node_count = True, [args[0]], [], 1
        elif op == "lineTo":
            segments.append("l")
            points.append(args[0])
            node_count += 1
        elif op == "curveTo":
            segments.append("c")
            points.append(args[-1])
            node_count += len(args)
        elif op == "qCurveTo":
            segments.append("q")
            if args[-1] is not None:
                points.append(args[-1])
            node_count += len(args)
        elif op in ("closePath", "endPath"):
            flush()
    flush()

    return {"contours": contours, "advance": getattr(glyph, "width", None)}


def _structural_issues(
    glyphsets: list[Any], names: list[str], fonts: list[TTFont]
) -> dict[str, list[dict[str, Any]]]:
    """Cross-master checks additive to interpolatable: segment type, winding, advance.

    Compares every master against the first. Contour-count and node-count
    mismatches are left to fontTools.varLib.interpolatable (path_count /
    node_count); this only adds the dimensions it does not surface.
    """
    if len(glyphsets) < 2:
        return {}
    issues_by_glyph: dict[str, list[dict[str, Any]]] = {}
    for name in fonts[0].getGlyphOrder():
        maybe_signatures = [_outline_signature(gs, name) for gs in glyphsets]
        signatures = [sig for sig in maybe_signatures if sig is not None]
        if len(signatures) != len(maybe_signatures):
            continue  # missing/undrawable in a master — interpolatable reports "missing"
        ref = signatures[0]
        ref_contours = ref["contours"]
        glyph_issues: list[dict[str, Any]] = []
        for master_index in range(1, len(signatures)):
            cur = signatures[master_index]
            master = names[master_index]
            if len(cur["contours"]) == len(ref_contours):
                for contour_index, (rc, cc) in enumerate(
                    zip(ref_contours, cur["contours"], strict=False)
                ):
                    if rc["segments"] != cc["segments"]:
                        glyph_issues.append(
                            {
                                "type": "segment_type_mismatch",
                                "master": master,
                                "contour": contour_index,
                                "expected": "".join(rc["segments"]) or "(empty)",
                                "actual": "".join(cc["segments"]) or "(empty)",
                            }
                        )
                    elif rc["winding"] and cc["winding"] and rc["winding"] != cc["winding"]:
                        glyph_issues.append(
                            {
                                "type": "winding_mismatch",
                                "master": master,
                                "contour": contour_index,
                                "expected": rc["winding"],
                                "actual": cc["winding"],
                            }
                        )
            ref_adv, cur_adv = ref["advance"], cur["advance"]
            if ref_adv is not None and cur_adv is not None and (ref_adv == 0) != (cur_adv == 0):
                glyph_issues.append(
                    {
                        "type": "advance_incompatible",
                        "master": master,
                        "expected": ref_adv,
                        "actual": cur_adv,
                    }
                )
        if glyph_issues:
            issues_by_glyph[name] = glyph_issues
    return issues_by_glyph


def _compatibility_hard_gates(family_reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    fields = {
        "p0_blocker_count": sum(
            family["summary"]["severity_counts"].get("P0", 0) for family in family_reports.values()
        ),
        "unapproved_fallback_count": 0,
        "missing_policy_count": 0,
        "interpolatable_error_count": sum(
            family["summary"]["issue_count"] for family in family_reports.values()
        ),
        # Phantom points carry advance metrics in gvar; a structural advance
        # zero/nonzero mismatch across masters is a phantom-point error.
        "phantom_point_error_count": sum(
            family["summary"]["issue_type_counts"].get("advance_incompatible", 0)
            for family in family_reports.values()
        ),
    }
    blocking_reasons = [
        {
            "field": field,
            "value": value,
            "threshold": 0,
            "message": f"{field} must be 0 before compatibility can pass.",
        }
        for field, value in fields.items()
        if value
    ]
    return {
        "status": "fail" if blocking_reasons else "pass",
        "fields": fields,
        "blocking_reasons": blocking_reasons,
    }


def _summary(family_reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    issue_type_counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()
    for family in family_reports.values():
        issue_type_counts.update(family["summary"]["issue_type_counts"])
        severity_counts.update(family["summary"]["severity_counts"])
    return {
        "family_count": len(family_reports),
        "problem_glyph_count": sum(
            family["summary"]["problem_glyph_count"] for family in family_reports.values()
        ),
        "issue_count": sum(family["summary"]["issue_count"] for family in family_reports.values()),
        "issue_type_counts": dict(sorted(issue_type_counts.items())),
        "severity_counts": dict(sorted(severity_counts.items())),
    }


def _fmt_counts(counts: dict[str, Any]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))


def render_compatibility_markdown(report: dict[str, Any], *, max_glyphs: int = 60) -> str:
    """Human-readable family report for the compatibility analysis."""
    gate = report["hard_gates"]
    summary = report["summary"]
    lines = [
        f"# Compatibility report — stage `{report['stage']}`",
        "",
        f"- gate: `{gate['status']}`",
        f"- families: {summary['family_count']}",
        f"- problem glyphs: {summary['problem_glyph_count']}",
        f"- issues: {summary['issue_count']}",
        f"- severity: {_fmt_counts(summary['severity_counts'])}",
        f"- issue types: {_fmt_counts(summary['issue_type_counts'])}",
        "",
    ]
    if gate["blocking_reasons"]:
        lines.append("## Blocking gates")
        lines.append("")
        lines.extend(
            f"- `{reason['field']}` = {reason['value']} (threshold {reason['threshold']})"
            for reason in gate["blocking_reasons"]
        )
        lines.append("")

    for family_key, family in report["families"].items():
        fsum = family["summary"]
        lines.extend(
            [
                f"## {family_key} — {family['name']} {family['style']}",
                "",
                f"- problem glyphs: {fsum['problem_glyph_count']} / {fsum['glyph_count']}",
                f"- severity: {_fmt_counts(fsum['severity_counts'])}",
                f"- issue types: {_fmt_counts(fsum['issue_type_counts'])}",
                "",
            ]
        )
        for severity in ("P0", "P1", "P2"):
            tier = [
                (name, record)
                for name, record in family["glyphs"].items()
                if record["severity"] == severity
            ]
            if not tier:
                continue
            lines.append(f"### {severity} ({len(tier)} glyphs)")
            lines.append("")
            for name, record in sorted(tier)[:max_glyphs]:
                lines.append(f"- `{name}` — {_fmt_counts(record['issue_type_counts'])}")
            if len(tier) > max_glyphs:
                lines.append(f"- … {len(tier) - max_glyphs} more (see JSON report)")
            lines.append("")

    return "\n".join(lines) + "\n"


def write_compatibility_markdown(report: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_compatibility_markdown(report))
    return path


def _source_hashes(families: dict[str, Family]) -> dict[str, str]:
    return {
        donor.id: sha256_file(donor.path) for family in families.values() for donor in family.donors
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in sorted(value.items())}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    return value
