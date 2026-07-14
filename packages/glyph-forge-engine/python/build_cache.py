"""Bulk render every (glyph × weight × source) to public-cache/svg/.

Reads manifests/broken-glyphs.json. Skips SVGs that already exist (idempotent);
pass --force to regenerate everything.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from render_glyph import render_to_svg
from shared import CACHE_DIR, MANIFEST_PATH, Family, donor_weights, set_config


def _output_path(family: Family, glyph: str, wght: int, source: str) -> Path:
    return CACHE_DIR / family / glyph / f"{wght}-{source}.svg"


def build(force: bool, limit: int | None, only_seed: bool, only_verdicts: set[str] | None) -> int:
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
    if only_verdicts:
        glyphs = [g for g in glyphs if g["auditVerdict"] in only_verdicts]
    if limit:
        glyphs = glyphs[:limit]

    start = time.monotonic()
    written = 0
    skipped = 0
    missing = 0

    for i, entry in enumerate(glyphs):
        family = entry["family"]
        name = entry["name"]
        for weight in donor_weights():
            for source in ("donor", "glide"):
                out = _output_path(family, name, weight.wght, source)
                if out.exists() and not force:
                    skipped += 1
                    continue
                svg = render_to_svg(family, name, weight.wght, source)
                if svg is None:
                    missing += 1
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(svg, encoding="utf-8")
                written += 1
        if (i + 1) % 50 == 0:
            elapsed = time.monotonic() - start
            print(
                f"  {i + 1}/{len(glyphs)} glyphs — "
                f"written {written}, skipped {skipped}, missing {missing} "
                f"({elapsed:.1f}s)",
                file=sys.stderr,
            )

    elapsed = time.monotonic() - start
    print(f"done: {written} written, {skipped} skipped, {missing} missing in {elapsed:.1f}s")
    print(f"cache root: {CACHE_DIR}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Path to an stv.config.json (else STV_CONFIG).")
    parser.add_argument("--force", action="store_true", help="Regenerate all SVGs.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N glyphs from the manifest (smoke test).",
    )
    parser.add_argument(
        "--only-seed",
        action="store_true",
        help="Only render glyphs from the config seed lists (skip audit-only glyphs).",
    )
    parser.add_argument(
        "--only-verdicts",
        nargs="+",
        choices=["blocker", "high", "medium", "low", "tracked", "unknown"],
        default=None,
        help="Filter to glyphs whose audit verdict matches any of these.",
    )
    args = parser.parse_args()
    if args.config:
        set_config(args.config)
    return build(
        force=args.force,
        limit=args.limit,
        only_seed=args.only_seed,
        only_verdicts=set(args.only_verdicts) if args.only_verdicts else None,
    )


if __name__ == "__main__":
    sys.exit(main())
