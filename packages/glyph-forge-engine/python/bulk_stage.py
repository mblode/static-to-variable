"""Bulk-stage solver winners into pending-triage-edits.json.

Use this to fill the triage queue for a whole bucket of glyphs in one go,
instead of clicking through 100+ loupes. You still review on /triage and
apply via `npm run apply`.

Selection options (combinable):
  --family FAM           Limit to roman or italic
  --verdict VERDICT      Limit to one or more audit verdicts
  --min-gain N           Only stage glyphs where solver projects a gain of at least N (default 0.1)
  --strategy-source SRC  Use solver winners or heuristic suggestions (default solver)
  --only-untriaged       Skip glyphs that already have an existing triage strategy
  --names FILE           Explicit list — one glyph per line (leading '/' stripped).
  --source LABEL         Source tag stored on the edit (default: 'suggestion')
  --include-reconstruction
                         Deprecated. Use --reconstruction-review instead.
  --reconstruction-review
                         Stage only solver-flagged reconstruction cases as manual_review.
  --dry-run              Print what would be staged without writing

Safety:
- Skips glyphs that already have a pending edit (won't clobber manual review)
- Skips glyphs with no solver verdict or gain < min_gain
- Always skips solver-flagged reconstruction cases in automatic modes
- --no-downgrade: never replace a more-comprehensive existing strategy with a
  lighter one (e.g. structural_fallback → weighted_fallback). Catches the case
  where the solver's raster simulation under-estimates what a vector strategy
  actually does for compatibility.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from shared import MANIFEST_PATH, PACKAGE_ROOT

# Rigour ordering — higher index means more comprehensive repair.
# Staging a lower-rigour strategy over a higher one is a potential regression.
STRATEGY_RIGOUR = {
    "manual_review": 0,
    "reference_fallback": 1,
    "weighted_fallback": 2,
    "inherit_base_contours": 3,
    "structural_fallback": 4,
    "donor_copy": 5,
    "rebuild_notdef": 6,
}

PENDING_PATH = PACKAGE_ROOT / "manifests" / "pending-triage-edits.json"
SOLVER_PATH = PACKAGE_ROOT / "manifests" / "solver-results.json"
SUGGESTIONS_PATH = PACKAGE_ROOT / "manifests" / "strategy-suggestions.json"


def _load(path: Path):
    if not path.exists():
        return None
    with path.open() as f:
        return json.load(f)


def _read_names_file(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8")
    out: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line.lstrip("/"))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=["roman", "italic"])
    parser.add_argument(
        "--verdict",
        action="append",
        choices=["blocker", "unknown", "high", "medium", "low", "tracked"],
        help="Limit to one audit verdict. Repeat to include multiple verdicts.",
    )
    parser.add_argument("--min-gain", type=float, default=0.1)
    parser.add_argument(
        "--strategy-source",
        choices=["solver", "suggestion"],
        default="solver",
        help="Stage solver winners or heuristic strategy suggestions.",
    )
    parser.add_argument(
        "--only-untriaged",
        action="store_true",
        help="Skip glyphs that already have an existing triage strategy.",
    )
    parser.add_argument("--names", type=Path)
    parser.add_argument("--source", default="suggestion")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--include-reconstruction",
        action="store_true",
        help="Deprecated. Use --reconstruction-review for solver-flagged reconstruction cases.",
    )
    parser.add_argument(
        "--reconstruction-review",
        action="store_true",
        help="Stage reconstruction-required glyphs as manual_review with reconstruction metadata.",
    )
    parser.add_argument(
        "--no-downgrade",
        action="store_true",
        help="Skip glyphs whose existing triage strategy is more comprehensive than the solver winner.",
    )
    args = parser.parse_args()
    if args.include_reconstruction and not args.reconstruction_review:
        parser.error(
            "--include-reconstruction is not supported for automatic staging; "
            "use --reconstruction-review to stage reconstruction-required glyphs."
        )

    manifest = _load(MANIFEST_PATH) or []
    solver = _load(SOLVER_PATH) or {}
    suggestions = _load(SUGGESTIONS_PATH) or {}
    pending = _load(PENDING_PATH) or []
    if not isinstance(pending, list):
        pending = []

    existing_keys = {f"{e['family']}/{e['glyph']}" for e in pending}

    name_filter: set[str] | None = None
    if args.names:
        names = _read_names_file(args.names)
        name_filter = set(names)
        print(f"filtering by {len(name_filter)} names from {args.names}")

    candidates = []
    downgrades_skipped = 0
    verdict_filter = set(args.verdict or [])
    for entry in manifest:
        fam = entry["family"]
        name = entry["name"]
        if args.family and fam != args.family:
            continue
        if verdict_filter and entry.get("auditVerdict") not in verdict_filter:
            continue
        if args.only_untriaged and entry.get("existingStrategy"):
            continue
        if name_filter is not None and name not in name_filter:
            continue
        key = f"{fam}/{name}"
        v = solver.get(key)
        suggestion = suggestions.get(key)
        if args.reconstruction_review:
            if not v or v.get("requiresReconstruction") is not True:
                continue
            strategy = "manual_review"
            gain = v.get("gain")
            current_worst = v.get("currentWorst")
            projected = v.get("bestProjected")
            worst_wght = v.get("bestWorstWght")
            candidates.append(
                (
                    entry,
                    {
                        "best": strategy,
                        "gain": gain,
                        "currentWorst": current_worst,
                        "bestProjected": projected,
                        "bestWorstWght": worst_wght,
                        "reason": v.get("reconstructionReason"),
                        "manifestPatch": {
                            "repair_bucket": "reconstruction_required",
                            "priority": "blocker",
                        },
                    },
                )
            )
            continue
        if v and v.get("requiresReconstruction") is True:
            continue
        if args.strategy_source == "suggestion":
            if not suggestion or suggestion.get("strategy") is None:
                continue
            strategy = suggestion["strategy"]
            if strategy == "manual_review":
                continue
            gain = v.get("gain") if v else None
            current_worst = v.get("currentWorst") if v else None
            projected = v.get("bestProjected") if v else None
            worst_wght = v.get("bestWorstWght") if v else None
        else:
            if v is None or v.get("best") is None or v.get("gain") is None:
                continue
            if v["gain"] < args.min_gain:
                continue
            strategy = v["best"]
            gain = v["gain"]
            current_worst = v.get("currentWorst")
            projected = v.get("bestProjected")
            worst_wght = v.get("bestWorstWght")
        if f"{fam}/{name}" in existing_keys:
            continue
        current_strategy = entry.get("existingStrategy")
        if current_strategy == strategy:
            continue
        if current_strategy and (
            entry.get("allowFrozen") is True or entry.get("allowStaticOutline") is True
        ):
            downgrades_skipped += 1
            continue
        if args.no_downgrade:
            current_rigour = STRATEGY_RIGOUR.get(current_strategy or "", -1)
            proposed_rigour = STRATEGY_RIGOUR.get(strategy, -1)
            if current_rigour > proposed_rigour:
                downgrades_skipped += 1
                continue
        candidates.append(
            (
                entry,
                {
                    "best": strategy,
                    "gain": gain,
                    "currentWorst": current_worst,
                    "bestProjected": projected,
                    "bestWorstWght": worst_wght,
                    "reason": suggestion.get("reason") if suggestion else None,
                },
            )
        )

    if args.no_downgrade and downgrades_skipped:
        print(f"  (--no-downgrade) skipped {downgrades_skipped} glyphs where current strategy is more rigorous")

    print(f"would stage {len(candidates)} glyphs (min_gain={args.min_gain})")
    if not candidates:
        return 0

    # Summary by winner
    by_winner: dict[str, int] = {}
    for _, v in candidates:
        by_winner[v["best"]] = by_winner.get(v["best"], 0) + 1
    print("  by winner:", by_winner)

    for entry, v in candidates[:10]:
        current = v["currentWorst"]
        projected = v["bestProjected"]
        metric = (
            f"{current:.2f} → {projected:.2f}"
            if isinstance(current, (int, float)) and isinstance(projected, (int, float))
            else "suggestion"
        )
        print(
            f"    {entry['family']}/{entry['name']:26s} "
            f"{metric}  ({v['best']})"
        )
    if len(candidates) > 10:
        print(f"    … {len(candidates) - 10} more")

    if args.dry_run:
        print("\n(dry-run, no writes)")
        return 0

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for entry, v in candidates:
        edit = {
            "family": entry["family"],
            "glyph": entry["name"],
            "strategy": v["best"],
            "source": args.source,
            "notes": (
                format_note(args.strategy_source, v)
            ),
            "stagedAt": now,
            "previousStrategy": entry.get("existingStrategy"),
        }
        manifest_patch = v.get("manifestPatch")
        if isinstance(manifest_patch, dict):
            edit["manifestPatch"] = manifest_patch
        pending.append(edit)

    pending.sort(key=lambda e: (e["family"], e["glyph"]))
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PENDING_PATH.open("w", encoding="utf-8") as f:
        json.dump(pending, f, indent=2, ensure_ascii=False)
    print(f"\nwrote {len(pending)} total pending edits to {PENDING_PATH.name}")
    return 0


def format_note(strategy_source: str, verdict: dict[str, object]) -> str:
    reason = verdict.get("reason")
    if strategy_source == "suggestion":
        return (
            f"Bulk-staged by heuristic suggestion: {reason}"
            if reason
            else "Bulk-staged by heuristic suggestion."
        )

    projected = verdict.get("bestProjected")
    current = verdict.get("currentWorst")
    gain = verdict.get("gain")
    worst_wght = verdict.get("bestWorstWght")
    if all(isinstance(value, (int, float)) for value in (projected, current, gain)):
        return (
            f"Bulk-staged by solver: projected {int(projected * 100)}"
            f" from {int(current * 100)} at wght {worst_wght}"
            f" (gain +{int(gain * 100)})"
        )
    return "Bulk-staged by solver."


if __name__ == "__main__":
    sys.exit(main())
