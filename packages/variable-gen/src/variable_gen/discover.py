from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont, TTLibError

from . import __version__
from .common import (
    display_path,
    select_families,
    sha256_file,
    sha256_text,
    write_json_report,
)
from .manifest import DonorSource, Family, StaticToVariableManifest


def build_inventory_report(
    manifest: StaticToVariableManifest,
    family_filter: str = "all",
) -> dict[str, Any]:
    selected_families = select_families(manifest.families, family_filter)
    family_reports = {
        key: _build_family_report(family) for key, family in selected_families.items()
    }

    source_hashes = _source_hashes(family_reports)
    hard_gates = _inventory_hard_gates(family_reports)

    return {
        "schema": "static_to_variable.inventory.v1",
        "schema_version": 1,
        "report_type": "inventory",
        "generator": {
            "name": "variable_gen.discover",
            "version": __version__,
        },
        "manifest_id": manifest.id,
        "manifest_hash": sha256_file(manifest.path),
        "source_hashes": source_hashes,
        "manifest": {
            "id": manifest.id,
            "version": manifest.version,
            "path": display_path(manifest.path, manifest.repo_root),
            "repo_root": display_path(manifest.repo_root, manifest.repo_root),
        },
        "axes": [
            {
                "tag": axis.tag,
                "name": axis.name,
                "minimum": axis.minimum,
                "default": axis.default,
                "maximum": axis.maximum,
                "donor_values": list(axis.donor_values),
                "output_values": list(axis.output_values),
                "map": [list(item) for item in axis.mapping],
            }
            for axis in manifest.axes
        ],
        "families": family_reports,
        "hard_gates": hard_gates,
        "summary": _build_summary(family_reports),
    }


def write_inventory_report(report: dict[str, Any], output_path: str | Path) -> Path:
    return write_json_report(report, output_path)


def _build_family_report(family: Family) -> dict[str, Any]:
    donor_reports = [_inspect_donor(donor) for donor in family.donors]
    glyph_sets = {
        donor["id"]: set(donor.get("glyph_order", []))
        for donor in donor_reports
        if donor.get("exists") and "glyph_order" in donor
    }
    cmap_sets = {
        donor["id"]: set(donor.get("cmap_codepoints", []))
        for donor in donor_reports
        if donor.get("exists") and "cmap_codepoints" in donor
    }

    return {
        "name": family.name,
        "style": family.style,
        "donor_count": len(donor_reports),
        "donors": donor_reports,
        "generated_sources": [
            {
                "id": source.id,
                "path": source.manifest_path,
                "role": source.role,
                "exists": source.path.exists(),
                "master_locations": source.master_locations,
            }
            for source in family.generated_sources
        ],
        "glyph_coverage": _coverage_summary(glyph_sets),
        "cmap_coverage": _coverage_summary(cmap_sets),
        "casefold_collisions": _casefold_collisions(glyph_sets),
        "warnings": _family_warnings(donor_reports),
    }


def _inspect_donor(donor: DonorSource) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": donor.id,
        "name": donor.name,
        "path": donor.manifest_path,
        "role": donor.role,
        "location": donor.location,
        "exists": donor.path.exists(),
    }

    if not donor.path.exists():
        return {**base, "warnings": ["file_missing"]}

    digest = sha256_file(donor.path)
    warnings: list[str] = []
    if donor.expected_sha256 and donor.expected_sha256 != digest:
        warnings.append("sha256_mismatch")

    try:
        font = TTFont(donor.path, lazy=True)
    except (OSError, TTLibError) as exc:
        return {
            **base,
            "sha256": digest,
            "readable": False,
            "warnings": ["font_unreadable"],
            "error": str(exc),
        }

    try:
        glyph_order = list(font.getGlyphOrder())
        cmap_codepoints = sorted(_best_cmap(font).keys())
        os2_weight = getattr(font.get("OS/2"), "usWeightClass", None)
        manifest_weight = donor.location.get("wght")
        if (
            os2_weight is not None
            and manifest_weight is not None
            and int(manifest_weight) != os2_weight
        ):
            warnings.append("weight_class_mismatch")

        return {
            **base,
            "sha256": digest,
            "readable": True,
            "font": {
                "family_name": _name(font, 1),
                "subfamily_name": _name(font, 2),
                "full_name": _name(font, 4),
                "postscript_name": _name(font, 6),
                "units_per_em": getattr(font.get("head"), "unitsPerEm", None),
                "os2_weight_class": os2_weight,
                "hhea_ascender": getattr(font.get("hhea"), "ascent", None),
                "hhea_descender": getattr(font.get("hhea"), "descent", None),
                "hhea_line_gap": getattr(font.get("hhea"), "lineGap", None),
                "os2_typo_ascender": getattr(font.get("OS/2"), "sTypoAscender", None),
                "os2_typo_descender": getattr(font.get("OS/2"), "sTypoDescender", None),
                "os2_typo_line_gap": getattr(font.get("OS/2"), "sTypoLineGap", None),
                "number_of_hmetrics": getattr(
                    font.get("hhea"),
                    "numberOfHMetrics",
                    None,
                ),
            },
            "glyph_count": len(glyph_order),
            "glyph_order": glyph_order,
            "glyph_order_sha256": sha256_text("\n".join(glyph_order)),
            "cmap_codepoint_count": len(cmap_codepoints),
            "cmap_codepoints": [f"U+{value:04X}" for value in cmap_codepoints],
            "cmap_sha256": sha256_text("\n".join(str(value) for value in cmap_codepoints)),
            "warnings": warnings,
        }
    finally:
        font.close()


def _coverage_summary(sets_by_id: dict[str, set[str]]) -> dict[str, Any]:
    if not sets_by_id:
        return {
            "union_count": 0,
            "intersection_count": 0,
            "missing_by_source": {},
            "unique_by_source": {},
        }

    all_sets = list(sets_by_id.values())
    union = set().union(*all_sets)
    intersection = set.intersection(*all_sets)
    unique_by_source: dict[str, list[str]] = {}
    for source_id, values in sorted(sets_by_id.items()):
        other_union = set().union(
            *(other_values for key, other_values in sets_by_id.items() if key != source_id)
        )
        unique = values - other_union
        if unique:
            unique_by_source[source_id] = sorted(unique)

    return {
        "union_count": len(union),
        "intersection_count": len(intersection),
        "missing_by_source": {
            source_id: sorted(union - values)
            for source_id, values in sorted(sets_by_id.items())
            if union - values
        },
        "unique_by_source": unique_by_source,
    }


def _casefold_collisions(glyph_sets: dict[str, set[str]]) -> dict[str, list[str]]:
    union = set().union(*glyph_sets.values()) if glyph_sets else set()
    by_casefold: dict[str, list[str]] = defaultdict(list)
    for glyph_name in sorted(union):
        by_casefold[glyph_name.casefold()].append(glyph_name)
    return {key: values for key, values in sorted(by_casefold.items()) if len(values) > 1}


def _family_warnings(donor_reports: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    if any(not donor.get("exists") for donor in donor_reports):
        warnings.append("missing_donor_files")
    if any("weight_class_mismatch" in donor.get("warnings", []) for donor in donor_reports):
        warnings.append("weight_class_mismatch")
    glyph_counts = {donor.get("glyph_count") for donor in donor_reports if donor.get("exists")}
    if len(glyph_counts) > 1:
        warnings.append("glyph_count_differs")
    cmap_counts = {
        donor.get("cmap_codepoint_count") for donor in donor_reports if donor.get("exists")
    }
    if len(cmap_counts) > 1:
        warnings.append("cmap_count_differs")
    return warnings


def _source_hashes(family_reports: dict[str, dict[str, Any]]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for family in family_reports.values():
        for donor in family.get("donors", []):
            digest = donor.get("sha256")
            if digest:
                hashes[donor["id"]] = digest
    return dict(sorted(hashes.items()))


def _inventory_hard_gates(family_reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    donor_reports = [
        donor for family in family_reports.values() for donor in family.get("donors", [])
    ]
    fields = {
        "missing_required_donors": sum(1 for donor in donor_reports if not donor.get("exists")),
        "unreadable_donors": sum(
            1 for donor in donor_reports if donor.get("exists") and donor.get("readable") is False
        ),
        "hash_mismatch": sum(
            1 for donor in donor_reports if "sha256_mismatch" in donor.get("warnings", [])
        ),
        "axis_location_missing": 0,
        "path_resolution_error": sum(1 for donor in donor_reports if not donor.get("exists")),
    }
    blocking_reasons = [
        {
            "field": field,
            "value": value,
            "threshold": 0,
            "message": f"{field} must be 0 before donor discovery can pass.",
        }
        for field, value in fields.items()
        if value
    ]
    return {
        "status": "fail" if blocking_reasons else "pass",
        "fields": fields,
        "blocking_reasons": blocking_reasons,
    }


def _build_summary(family_reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    donor_reports = [
        donor for family in family_reports.values() for donor in family.get("donors", [])
    ]
    warnings = sorted(
        {warning for family in family_reports.values() for warning in family.get("warnings", [])}
    )
    return {
        "family_count": len(family_reports),
        "donor_count": len(donor_reports),
        "missing_donor_count": sum(1 for donor in donor_reports if not donor.get("exists")),
        "warning_count": sum(len(donor.get("warnings", [])) for donor in donor_reports)
        + sum(len(family.get("warnings", [])) for family in family_reports.values()),
        "warnings": warnings,
    }


def _best_cmap(font: TTFont) -> dict[int, str]:
    cmap = font.getBestCmap()
    if cmap:
        return dict(cmap)
    if "cmap" not in font:
        return {}
    merged: dict[int, str] = {}
    for table in font["cmap"].tables:
        merged.update(table.cmap)
    return merged


def _name(font: TTFont, name_id: int) -> str | None:
    table = font.get("name")
    if table is None:
        return None
    value = table.getDebugName(name_id)
    return str(value) if value is not None else None
