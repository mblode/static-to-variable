#!/usr/bin/env python3
"""Rebuild the web showcase variable fonts from scripts/showcase-fonts.json.

The manifest records every family's masters (all upright weights it ships on
Google Fonts) so the showcase fonts in apps/web/public/fonts can be rebuilt
reproducibly after engine changes. Runs build-showcase-font.py once per family.
Each family reconstructs on a single core, so -j runs several at once.

  uv run scripts/rebuild-showcase-fonts.py             # every family, serial
  uv run scripts/rebuild-showcase-fonts.py -j4         # up to 4 at a time
  uv run scripts/rebuild-showcase-fonts.py barlow lato # just the named ids
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = Path(__file__).resolve().parent / "showcase-fonts.json"


def _build(font: dict, out: str) -> tuple[str, int, str]:
    cmd = [
        sys.executable,
        str(ROOT / "scripts/build-showcase-font.py"),
        "--id",
        font["id"],
        "--family",
        font["family"],
        "--ofl",
        font["ofl"],
        "--default",
        str(font["default"]),
        "--out",
        str(ROOT / out),
    ]
    for style, wght in font["masters"].items():
        cmd += ["--master", f"{style}={wght}"]
    proc = subprocess.run(cmd, cwd=ROOT, check=False, capture_output=True, text=True)
    return font["family"], proc.returncode, proc.stdout + proc.stderr


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ids", nargs="*", help="font ids to build (default: all)")
    ap.add_argument("-j", "--jobs", type=int, default=1, help="families to build at once")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    manifest = json.loads(MANIFEST.read_text())
    only = set(args.ids)
    unknown = only - {f["id"] for f in manifest["fonts"]}
    if unknown:
        raise SystemExit(f"unknown font ids: {sorted(unknown)}")
    fonts = [f for f in manifest["fonts"] if not only or f["id"] in only]

    failed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [pool.submit(_build, f, manifest["out"]) for f in fonts]
        for future in futures:
            family, code, output = future.result()
            summary = "\n".join(
                line
                for line in output.splitlines()
                if line.startswith(("built", "  ")) or "fail" in line.lower()
            )
            print(f"\n=== {family} (exit {code})\n{summary}")
            if code != 0:
                failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
