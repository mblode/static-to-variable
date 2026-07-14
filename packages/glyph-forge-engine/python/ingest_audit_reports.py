"""Build manifests/broken-glyphs.json from variable-gen reports + user seed lists.

Output is the union of three origins so nothing gets dropped:
  1. variable-gen audit JSON (severity-scored)
  2. The config seed lists (config.glyphs.seeds, user-flagged)
  3. circular-triage.json (existing repair strategies)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from shared import (
    MANIFEST_PATH,
    TRIAGE_MANIFEST,
    VARIABLE_GEN_REPORTS,
    Family,
    context,
    feature_tags,
    glyph_unicode,
    resolve_glyph_name,
    seeds,
    set_config,
    vf_path,
)


def audit_json_path(family: Family) -> Path:
    return VARIABLE_GEN_REPORTS / "audit" / family / f"{family}-variable-audit.json"


@dataclass
class BrokenGlyph:
    name: str
    family: Family
    features: list[str]
    sources: list[str]
    auditVerdict: str
    unicode: str | None = None
    severityScore: int | None = None
    existingStrategy: str | None = None
    priority: str | None = None
    allowFrozen: bool | None = None
    allowStaticOutline: bool | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Keep required fields (name, family, features, sources, auditVerdict) even
        # when empty; drop optional fields when unset so the JSON is compact.
        required = {"name", "family", "features", "sources", "auditVerdict"}
        return {k: v for k, v in d.items() if k in required or v not in (None, [], "")}


@dataclass
class Accumulator:
    by_name: dict[str, BrokenGlyph] = field(default_factory=dict)

    def upsert(self, glyph: BrokenGlyph) -> None:
        existing = self.by_name.get(glyph.name)
        if existing is None:
            self.by_name[glyph.name] = glyph
            return
        # Merge sources.
        for src in glyph.sources:
            if src not in existing.sources:
                existing.sources.append(src)
        # Fill gaps — don't overwrite existing truthy fields.
        for attr in (
            "unicode",
            "severityScore",
            "existingStrategy",
            "priority",
            "allowFrozen",
            "allowStaticOutline",
            "notes",
        ):
            if getattr(existing, attr) in (None, "") and getattr(glyph, attr):
                setattr(existing, attr, getattr(glyph, attr))
        # Take the more severe verdict.
        existing.auditVerdict = _more_severe(existing.auditVerdict, glyph.auditVerdict)


VERDICT_ORDER = ["unknown", "low", "medium", "high", "blocker", "tracked"]


def _more_severe(a: str, b: str) -> str:
    return max(a, b, key=lambda v: VERDICT_ORDER.index(v) if v in VERDICT_ORDER else -1)


def severity_to_verdict(score: int | None) -> str:
    if score is None or score <= 0:
        return "unknown"
    if score < 50:
        return "low"
    if score < 200:
        return "medium"
    if score < 500:
        return "high"
    return "blocker"


def load_triage(families: tuple[str, ...]) -> dict[str, dict[str, dict[str, Any]]]:
    if not TRIAGE_MANIFEST.exists():
        return {family: {} for family in families}
    with TRIAGE_MANIFEST.open() as f:
        raw = json.load(f)
    return {family: raw.get(family, {}).get("glyphs", {}) for family in families}


def load_audit_summary(family: Family) -> dict[str, int]:
    path = audit_json_path(family)
    if not path.exists():
        print(f"warn: audit report missing for {family} at {path}", file=sys.stderr)
        return {}
    with path.open() as f:
        data = json.load(f)
    summary = data.get("glyph_issue_summary", {})
    return {
        name: entry.get("severity_score", 0)
        for name, entry in summary.items()
        if entry.get("severity_score", 0) > 0
    }


def ingest_family(
    family: Family, seed: tuple[str, ...], triage: dict[str, Any]
) -> list[BrokenGlyph]:
    acc = Accumulator()
    font_path = vf_path(family)

    # 1. Audit report — severity-ranked.
    audit = load_audit_summary(family)
    for name, score in audit.items():
        resolved = resolve_glyph_name(name, font_path)
        if resolved is None:
            continue
        acc.upsert(
            BrokenGlyph(
                name=resolved,
                family=family,
                features=feature_tags(resolved),
                sources=["audit"],
                auditVerdict=severity_to_verdict(score),
                severityScore=score,
                unicode=glyph_unicode(resolved, font_path),
            )
        )

    # 2. User seed list — guaranteed to be included.
    for raw in seed:
        resolved = resolve_glyph_name(raw, font_path)
        if resolved is None:
            print(f"warn: seed glyph {raw!r} not found in {family} font", file=sys.stderr)
            continue
        acc.upsert(
            BrokenGlyph(
                name=resolved,
                family=family,
                features=feature_tags(resolved),
                sources=["user_seed"],
                auditVerdict="unknown",
                unicode=glyph_unicode(resolved, font_path),
            )
        )

    # 3. Triage manifest — overlay strategy + notes + priority.
    for name, cfg in triage.items():
        resolved = name if name in acc.by_name else resolve_glyph_name(name, font_path) or name
        if resolved not in acc.by_name:
            # If triage has a glyph not in audit or seed, still include it if it exists.
            real = resolve_glyph_name(name, font_path)
            if real is None:
                continue
            acc.upsert(
                BrokenGlyph(
                    name=real,
                    family=family,
                    features=feature_tags(real),
                    sources=["audit"],  # triage implies an audit-tracked glyph
                    auditVerdict="tracked",
                    unicode=glyph_unicode(real, font_path),
                )
            )
        entry = acc.by_name[resolved]
        entry.existingStrategy = cfg.get("strategy")
        entry.priority = cfg.get("priority")
        entry.allowFrozen = cfg.get("allow_frozen")
        entry.allowStaticOutline = cfg.get("allow_static_outline")
        note = cfg.get("notes")
        if note:
            entry.notes = note

    return sorted(acc.by_name.values(), key=lambda g: (g.family, g.name))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Path to an stv.config.json (else STV_CONFIG).")
    args = parser.parse_args()
    if args.config:
        set_config(args.config)

    families = context().families
    triage = load_triage(families)
    glyphs: list[BrokenGlyph] = []
    for family in families:
        glyphs.extend(ingest_family(family, seeds(family), triage[family]))

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("w", encoding="utf-8") as f:
        json.dump([g.to_dict() for g in glyphs], f, indent=2, ensure_ascii=False)

    by_family: dict[str, int] = {}
    by_verdict: dict[str, int] = {}
    for g in glyphs:
        by_family[g.family] = by_family.get(g.family, 0) + 1
        by_verdict[g.auditVerdict] = by_verdict.get(g.auditVerdict, 0) + 1

    print(f"wrote {MANIFEST_PATH.relative_to(MANIFEST_PATH.parents[2])}: {len(glyphs)} glyphs")
    print(f"  by family: {by_family}")
    print(f"  by verdict: {by_verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
