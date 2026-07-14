"""Render a single glyph to SVG from the Glide variable TTF or a Circular donor OTF."""

from __future__ import annotations

import argparse
import sys
from functools import lru_cache
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from shared import (
    CellSource,
    Family,
    context,
    donor_otf,
    load_font,
    resolve_glyph_name,
    set_config,
    vf_path,
)

SVG_SIZE = 256
PADDING = 0.08


@lru_cache(maxsize=64)
def _instanced_glide(family: Family, wght: int) -> TTFont:
    base = load_font(vf_path(family))
    return instancer.instantiateVariableFont(base, {"wght": wght})


@lru_cache(maxsize=64)
def _donor_font(family: Family, wght: int) -> TTFont:
    return load_font(donor_otf(family, wght))


def _font_units(font: TTFont) -> int:
    return font["head"].unitsPerEm


def _ascender(font: TTFont) -> int:
    os2 = font["OS/2"]
    return os2.sTypoAscender if os2.sTypoAscender else font["hhea"].ascent


def _descender(font: TTFont) -> int:
    os2 = font["OS/2"]
    return os2.sTypoDescender if os2.sTypoDescender else font["hhea"].descent


def render_to_svg(
    family: Family,
    glyph_name_or_seed: str,
    wght: int,
    source: CellSource,
) -> str | None:
    """Render one glyph → SVG string, or None if the glyph is missing in that source."""
    if source == "glide":
        font = _instanced_glide(family, wght)
    else:
        font = _donor_font(family, wght)

    glyph_name = resolve_glyph_name(glyph_name_or_seed, _font_path(family, source, wght))
    if glyph_name is None:
        return None

    glyph_set = font.getGlyphSet()
    if glyph_name not in glyph_set:
        return None

    pen = SVGPathPen(glyph_set)
    glyph_set[glyph_name].draw(pen)
    path_d = pen.getCommands()

    units = _font_units(font)
    ascender = _ascender(font)
    descender = _descender(font)
    height = ascender - descender
    pad = int(units * PADDING)
    view_x = -pad
    view_y = descender - pad
    view_w = units + pad * 2
    view_h = height + pad * 2

    # Flip Y so SVG (y-down) matches font coords (y-up).
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{view_x} {view_y} {view_w} {view_h}" '
        f'width="{SVG_SIZE}" height="{SVG_SIZE}">'
        f'<g transform="scale(1 -1)">'
        f'<path d="{path_d}" fill="currentColor"/>'
        f"</g></svg>"
    )


def _font_path(family: Family, source: CellSource, wght: int) -> Path:
    if source == "glide":
        return vf_path(family)
    return donor_otf(family, wght)


def main() -> int:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", help="Path to an stv.config.json (else STV_CONFIG).")
    pre_args, _ = pre.parse_known_args()
    if pre_args.config:
        set_config(pre_args.config)
    ctx = context()

    parser = argparse.ArgumentParser(description="Render one glyph to SVG.", parents=[pre])
    parser.add_argument("--family", choices=list(ctx.families), required=True)
    parser.add_argument(
        "--glyph",
        required=True,
        help="Glyph name (agrave.ss02), slashed form (/agrave.ss02), or single Unicode char.",
    )
    parser.add_argument(
        "--weight",
        type=int,
        required=True,
        choices=[w.wght for w in ctx.donor_weights()],
    )
    parser.add_argument("--source", choices=["donor", "glide"], required=True)
    parser.add_argument("--out", type=Path, help="Write to file instead of stdout.")
    args = parser.parse_args()

    svg = render_to_svg(args.family, args.glyph, args.weight, args.source)
    if svg is None:
        print(
            f"skip: {args.family} {args.glyph} @ {args.weight} ({args.source}) — glyph missing",
            file=sys.stderr,
        )
        return 2

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(svg, encoding="utf-8")
    else:
        print(svg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
