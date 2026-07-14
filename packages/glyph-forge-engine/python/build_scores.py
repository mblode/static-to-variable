"""Bulk scorer: walks the manifest × 8 weights, writes per-cell + per-glyph scores.

Outputs:
- manifests/cell-scores.json   — {family/glyph/wght: {void, irregularity, drift, composite}}
- manifests/glyph-scores.json  — {family/glyph: {worstWght, worstComposite, avgComposite, missingCells}}
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from score_glyph import score_cell
from shared import MANIFEST_PATH, PACKAGE_ROOT, donor_weights, set_config

CELL_SCORES_PATH = PACKAGE_ROOT / "manifests" / "cell-scores.json"
GLYPH_SCORES_PATH = PACKAGE_ROOT / "manifests" / "glyph-scores.json"


def build(only_seed: bool, limit: int | None) -> int:
    if not MANIFEST_PATH.exists():
        print(
            f"error: manifest not found at {MANIFEST_PATH}; run ingest_audit_reports.py first",
            file=sys.stderr,
        )
        return 1

    with MANIFEST_PATH.open() as f:
        glyphs = json.load(f)
    if only_seed:
        glyphs = [g for g in glyphs if "user_seed" in g["sources"]]
    if limit:
        glyphs = glyphs[:limit]

    cells: dict[str, dict[str, float]] = {}
    aggregates: dict[str, dict[str, float | int | None]] = {}
    start = time.monotonic()
    computed = 0
    skipped = 0

    for i, entry in enumerate(glyphs):
        family = entry["family"]
        name = entry["name"]
        composites: list[tuple[int, float]] = []
        missing = 0
        for weight in donor_weights():
            key = f"{family}/{name}/{weight.wght}"
            s = score_cell(family, name, weight.wght)
            if s is None:
                missing += 1
                skipped += 1
                continue
            cells[key] = s.to_dict()
            composites.append((weight.wght, s.composite))
            computed += 1
        if composites:
            comps = [c for _, c in composites]
            worst_w, worst_c = min(composites, key=lambda x: x[1])
            aggregates[f"{family}/{name}"] = {
                "worstWght": worst_w,
                "worstComposite": round(worst_c, 4),
                "avgComposite": round(sum(comps) / len(comps), 4),
                "missingCells": missing,
            }
        else:
            aggregates[f"{family}/{name}"] = {
                "worstWght": None,
                "worstComposite": None,
                "avgComposite": None,
                "missingCells": missing,
            }
        if (i + 1) % 50 == 0:
            elapsed = time.monotonic() - start
            print(
                f"  {i + 1}/{len(glyphs)} — scored {computed}, skipped {skipped} ({elapsed:.1f}s)",
                file=sys.stderr,
            )

    CELL_SCORES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CELL_SCORES_PATH.open("w", encoding="utf-8") as f:
        json.dump(cells, f, indent=0, ensure_ascii=False)
    with GLYPH_SCORES_PATH.open("w", encoding="utf-8") as f:
        json.dump(aggregates, f, indent=0, ensure_ascii=False)

    elapsed = time.monotonic() - start
    print(
        f"done: {computed} cells scored, {skipped} skipped, "
        f"{len(aggregates)} glyphs aggregated in {elapsed:.1f}s"
    )
    print(f"cell scores: {CELL_SCORES_PATH.relative_to(PACKAGE_ROOT.parent)}")
    print(f"glyph scores: {GLYPH_SCORES_PATH.relative_to(PACKAGE_ROOT.parent)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Path to an stv.config.json (else STV_CONFIG).")
    parser.add_argument("--only-seed", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    if args.config:
        set_config(args.config)
    return build(only_seed=args.only_seed, limit=args.limit)


if __name__ == "__main__":
    sys.exit(main())
