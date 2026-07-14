"""Merge manifests/pending-triage-edits.json into variable-gen/manifests/circular-triage.json.

Safety rails:
- Default is --dry-run (prints the diff only)
- On mutation: writes a .bak alongside circular-triage.json
- Preserves all existing fields on each glyph entry (notes, priority, brace_weights, base_glyph...)
- Overwrites `strategy` plus whitelisted `manifestPatch` fields
- Clears the pending file only after a successful mutation
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from shared import PACKAGE_ROOT, TRIAGE_MANIFEST

PENDING_PATH = PACKAGE_ROOT / "manifests" / "pending-triage-edits.json"
PATCH_FIELDS = {
    "repair_bucket",
    "base_glyph",
    "brace_weights",
    "priority",
    "deferred",
    "defer_reason",
}


@dataclass
class Change:
    family: str
    glyph: str
    before: str | None
    after: str
    source: str
    notes: str | None
    patch: dict[str, object]
    patch_changed: bool

    @property
    def key(self) -> str:
        return f"{self.family}/{self.glyph}"

    @property
    def changes_state(self) -> bool:
        return self.before != self.after or self.patch_changed or bool(self.notes)


def load_pending() -> list[dict]:
    if not PENDING_PATH.exists():
        return []
    with PENDING_PATH.open() as f:
        data = json.load(f)
    if not isinstance(data, list):
        return []
    return data


def load_triage() -> dict:
    if not TRIAGE_MANIFEST.exists():
        return {}
    with TRIAGE_MANIFEST.open() as f:
        return json.load(f)


def diff(pending: list[dict], triage: dict) -> list[Change]:
    changes: list[Change] = []
    for entry in pending:
        family = entry["family"]
        glyph = entry["glyph"]
        after = entry["strategy"]
        before = (
            triage.get(family, {}).get("glyphs", {}).get(glyph, {}).get("strategy")
        )
        existing = triage.get(family, {}).get("glyphs", {}).get(glyph, {})
        patch = sanitize_patch(entry.get("manifestPatch", {}))
        changes.append(
            Change(
                family=family,
                glyph=glyph,
                before=before,
                after=after,
                source=entry.get("source", "unknown"),
                notes=entry.get("notes"),
                patch=patch,
                patch_changed=any(existing.get(key) != value for key, value in patch.items()),
            )
        )
    return changes


def sanitize_patch(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if key in PATCH_FIELDS}


def apply_changes(triage: dict, changes: list[Change]) -> tuple[int, int]:
    created = 0
    updated = 0
    for c in changes:
        fam = triage.setdefault(
            c.family,
            {"source_path": "", "reference_master_name": "Regular", "glyphs": {}},
        )
        fam.setdefault("glyphs", {})
        existing = fam["glyphs"].get(c.glyph)
        if existing is None:
            fam["glyphs"][c.glyph] = {"strategy": c.after, **c.patch}
            if c.notes:
                fam["glyphs"][c.glyph]["notes"] = c.notes
            created += 1
        else:
            existing["strategy"] = c.after
            existing.update(c.patch)
            if c.notes:
                # Append to notes so manual context isn't lost.
                old_notes = existing.get("notes")
                existing["notes"] = (
                    f"{old_notes}\n\n[staged] {c.notes}" if old_notes else c.notes
                )
            updated += 1
    return created, updated


def write_triage(triage: dict) -> Path:
    backup = TRIAGE_MANIFEST.with_suffix(".json.bak")
    if TRIAGE_MANIFEST.exists():
        shutil.copy2(TRIAGE_MANIFEST, backup)
    with TRIAGE_MANIFEST.open("w", encoding="utf-8") as f:
        json.dump(triage, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return backup


def format_change(c: Change) -> str:
    patch = (
        " "
        + " ".join(f"{key}={value!r}" for key, value in sorted(c.patch.items()))
        if c.patch
        else ""
    )
    if c.before is None:
        return f"  + {c.key:40s}  (new)                → {c.after}{patch}  [{c.source}]"
    if c.before == c.after:
        label = "metadata" if c.changes_state else "no change"
        return f"  = {c.key:40s}  {c.before}{patch}  ({label})  [{c.source}]"
    return f"  ~ {c.key:40s}  {c.before}  →  {c.after}{patch}  [{c.source}]"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the diff but don't write to circular-triage.json or clear the pending file.",
    )
    parser.add_argument(
        "--keep-pending",
        action="store_true",
        help="After applying, keep pending-triage-edits.json instead of emptying it.",
    )
    args = parser.parse_args()

    pending = load_pending()
    if not pending:
        print("No pending edits to apply.")
        return 0

    triage = load_triage()
    changes = diff(pending, triage)
    no_change = [c for c in changes if not c.changes_state]
    real_changes = [c for c in changes if c.changes_state]

    print(f"{len(changes)} pending edit(s) — {len(real_changes)} would change state, {len(no_change)} no-ops")
    for c in changes:
        print(format_change(c))

    if args.dry_run:
        print("\n(dry-run, no files modified)")
        return 0

    if not real_changes:
        print("\nNothing to apply (all pending edits match current state).")
        return 0

    created, updated = apply_changes(triage, changes)
    backup = write_triage(triage)
    print(
        f"\napplied: {created} new entries, {updated} updated. "
        f"backup: {backup.relative_to(PACKAGE_ROOT.parent.parent) if backup.exists() else '(none)'}"
    )

    if not args.keep_pending:
        with PENDING_PATH.open("w", encoding="utf-8") as f:
            f.write("[]\n")
        print(f"cleared {PENDING_PATH.relative_to(PACKAGE_ROOT.parent)}")

    print("\nNext: re-run the repair engine so the new strategies take effect:")
    print("  .venv/bin/python packages/variable-gen/scripts/repair_circular_sources.py --font all")
    return 0


if __name__ == "__main__":
    sys.exit(main())
