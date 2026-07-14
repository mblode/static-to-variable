#!/usr/bin/env python3
"""Build + rebrand the static Glide-Mono companion face.

Glide-Mono is a Glide-only extra (a separate static family), so it lives here in
the example rather than in the generic ``variable_gen`` engine. It builds
``../glide/glide-mono.glyphs`` with fontmake, stamps the shared family metadata
from ``stv.config.json``, and emits TTF + WOFF2 into the configured release dir.

Run:  uv run python examples/glide/extra/build_mono.py [--config <path>]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from variable_gen.build import _fontmake
from variable_gen.config import load_config
from variable_gen.release import _release_dir, setname, woff2

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "stv.config.json"


def build_mono(config, out: Path) -> Path:
    # The mono source sits beside the repo (a sibling ``glide`` checkout).
    src = config.repo_root.parent / "glide" / "glide-mono.glyphs"
    tmp = out.parent / "_mono_raw.ttf"
    out.parent.mkdir(parents=True, exist_ok=True)
    fontmake = _fontmake(config.repo_root)
    p = subprocess.run(
        [fontmake, "-g", str(src), "-o", "ttf", "--output-path", str(tmp)],
        cwd=config.repo_root,
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        sys.stderr.write(p.stdout + p.stderr)
        raise SystemExit("mono build failed")

    font = TTFont(str(tmp))
    setname(font, "Glide Mono", 1)
    setname(font, "Regular", 2)
    setname(font, "Glide Mono Regular", 4)
    setname(font, "GlideMono-Regular", 6)
    setname(font, "Glide Mono", 16)
    setname(font, "Regular", 17)
    setname(font, config.family.designer, 8)
    setname(font, config.family.designer, 9)
    setname(font, config.family.designer_url, 11)
    setname(font, config.family.designer_url, 12)
    font["head"].fontRevision = float(config.family.version)
    setname(font, f"Version {config.family.version}", 5)
    setname(font, f"{config.family.version};{config.family.vendor};GlideMono-Regular", 3)
    font["OS/2"].achVendID = config.family.vendor
    os2 = font["OS/2"]
    os2.fsSelection = (os2.fsSelection | 0x040) & ~0x001
    font["head"].macStyle &= ~0x2
    font.save(str(out))
    tmp.unlink(missing_ok=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=str(DEFAULT_CONFIG), help="path to stv.config.json")
    args = ap.parse_args()
    config = load_config(args.config)
    out = build_mono(config, _release_dir(config) / "glide-mono.ttf")
    woff2(out)
    print(f"[mono] -> {out.name} + .woff2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
