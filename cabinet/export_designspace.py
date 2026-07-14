#!/usr/bin/env python3
"""Glide designspace-export shim.

The generic implementation now lives in :mod:`variable_gen.designspace`. This
thin wrapper preserves the historical three-argument ``export(glyphs_path,
ds_name, ufo_prefix)`` entry point that ``rederive_from_donors.py``,
``repair_sources.py`` and ``audit_variable_font.py`` import, applying Glide's
weight ladder (Thin..ExtraBlack, Regular default). For the config-driven pipeline
use ``variable_gen.designspace.export_designspace(config, style_key)`` instead.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import glyphsLib
import ufoLib2
from glyphsLib.builder import to_designspace
from variable_gen.designspace import build_designspace

REPO_ROOT = Path(__file__).resolve().parent.parent
MASTER_UFO_DIR = REPO_ROOT / "master_ufo"

# Named weight stops shown in font menus: position -> style name. Glide has 3
# masters (100/400/950); the other stops are interpolated labels on the axis.
WEIGHT_NAMES = {
    100: "Thin",
    200: "ExtraLight",
    300: "Light",
    400: "Regular",
    500: "Medium",
    600: "SemiBold",
    700: "Bold",
    800: "ExtraBold",
    900: "Black",
    950: "ExtraBlack",
}
DEFAULT_WEIGHT = 400


def export(glyphs_path: Path, ds_name: str, ufo_prefix: str) -> Path:
    """Convert a Glide ``.glyphs`` source to UFOs + designspace (legacy entry)."""
    glyphs_path = Path(glyphs_path)
    # Infer family + italic the way the original script did, so callers that pass
    # only the three positional args keep their exact behaviour.
    font = glyphsLib.load(str(glyphs_path))
    ds = to_designspace(font, ufo_module=ufoLib2)
    family = ds.sources[0].familyName if ds.sources else "Glide"
    is_italic = any("Italic" in (s.styleName or "") for s in ds.sources)
    return build_designspace(
        glyphs_path,
        ds_name,
        ufo_prefix,
        family=family,
        is_italic=is_italic,
        axis_tag="wght",
        axis_name="Weight",
        default_weight=DEFAULT_WEIGHT,
        weight_names=WEIGHT_NAMES,
        master_ufo_dir=MASTER_UFO_DIR,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Export .glyphs -> UFO + designspace")
    parser.add_argument("--italic", action="store_true", help="Export italic source")
    args = parser.parse_args()
    if args.italic:
        glyphs_path = REPO_ROOT / "glide-variable-italic.glyphs"
        ds_name, ufo_prefix = "GlideItalic.designspace", "GlideItalic"
    else:
        glyphs_path = REPO_ROOT / "glide-variable.glyphs"
        ds_name, ufo_prefix = "Glide.designspace", "Glide"
    ds_path = export(glyphs_path, ds_name, ufo_prefix)
    print(f"\nDone: {ds_path}")


if __name__ == "__main__":
    main()
