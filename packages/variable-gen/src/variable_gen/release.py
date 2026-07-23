#!/usr/bin/env python3
"""Config-driven release packaging for a static-to-variable family.

Finalizes the variable-font metadata (name table, RIBBI bits, STAT/fvar named
instances, PostScript names, version stamp, vendor id) and emits TTF + WOFF2 into
the configured release directory. Everything is sourced from the v3
``ProjectConfig`` family metadata + ``axes[].namedInstances``.

Run:  uv run python -m variable_gen.cli release --config <path> --style all
"""

from __future__ import annotations

import math
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

from variable_gen.config import ProjectConfig

WIN = (3, 1, 0x409)
MAC = (1, 0, 0)

USE_TYPO_METRICS = 1 << 7

# Reference glyphs whose ink defines the family's true ascender / descender.
_ASCENDER_GLYPHS = "bdfhklt"
_DESCENDER_GLYPHS = "gjpqy"


def _glyph_extent(font: TTFont, chars: str) -> tuple[float | None, float | None]:
    """Return (max top, min bottom) of the given characters' outlines."""
    cmap = font.getBestCmap()
    glyph_set = font.getGlyphSet()
    tops: list[float] = []
    bottoms: list[float] = []
    for char in chars:
        name = cmap.get(ord(char))
        if not name:
            continue
        pen = BoundsPen(glyph_set)
        glyph_set[name].draw(pen)
        if pen.bounds:
            tops.append(pen.bounds[3])
            bottoms.append(pen.bounds[1])
    return (max(tops) if tops else None, min(bottoms) if bottoms else None)


def normalize_vertical_metrics(font: TTFont) -> None:
    """Make the typo/hhea line box hug the glyphs.

    glyphsLib/fontmake default the vertical metrics to an ascent well above the
    cap/ascender line plus a large line gap. Because platforms size the text
    insertion caret and the default line box to those metrics, the caret towers
    above the glyphs and line spacing runs loose. Rebuild the metrics from the
    font's own ink: the ascender line at the top of the ascender glyphs, the
    descender line at the bottom of the descender glyphs (and any lower marks),
    a zero line gap, and USE_TYPO_METRICS so every platform agrees. The win
    metrics stay wide enough to cover accents/marks so nothing clips.
    """
    head = font["head"]
    os2 = font["OS/2"]
    hhea = font["hhea"]

    asc_top, _ = _glyph_extent(font, _ASCENDER_GLYPHS)
    _, desc_bottom = _glyph_extent(font, _DESCENDER_GLYPHS)

    ascent = int(math.ceil((asc_top if asc_top is not None else head.yMax) / 10) * 10)
    lowest = min(desc_bottom if desc_bottom is not None else head.yMin, head.yMin)
    descent = int(math.floor(lowest / 10) * 10)

    os2.sTypoAscender = ascent
    os2.sTypoDescender = descent
    os2.sTypoLineGap = 0
    hhea.ascent = ascent
    hhea.descent = descent
    hhea.lineGap = 0
    # Keep the win box wide enough for accents/marks so tall glyphs never clip.
    os2.usWinAscent = max(head.yMax, ascent)
    os2.usWinDescent = -min(head.yMin, descent)
    os2.fsSelection |= USE_TYPO_METRICS


def _ps_family(config: ProjectConfig) -> str:
    return config.family.name.replace(" ", "")


def setname(font, value, nid):
    name = font["name"]
    for plat in (WIN, MAC):
        name.setName(value, nid, *plat)


def stamp_version(font, config: ProjectConfig, ps_name: str):
    font["head"].fontRevision = float(config.family.version)
    setname(font, f"Version {config.family.version}", 5)
    setname(font, f"{config.family.version};{config.family.vendor};{ps_name}", 3)


def fix_instances(font, config: ProjectConfig, italic: bool):
    """Rewrite fvar named-instance subfamily + PostScript names and drop orphan
    name records, deriving names from the weight coordinate so the result is
    independent of what the source emitted (Glyphs emits an empty subfamily for
    the default instance and italic PS names that collide with the roman's)."""
    if "fvar" not in font:
        return
    axis_tag = config.axes[0].tag
    default = config.axes[0].default
    weight_names = {int(pos): nm for pos, nm in config.axes[0].named_instances.items()}
    ps_family = _ps_family(config)
    name = font["name"]
    for inst in font["fvar"].instances:
        wght = int(round(inst.coordinates.get(axis_tag, default)))
        base = weight_names.get(wght, str(wght))
        is_regular = wght == int(default)
        if italic:
            sub = "Italic" if is_regular else f"{base} Italic"
            ps = f"{ps_family}-Italic" if is_regular else f"{ps_family}-{base}Italic"
        else:
            sub = base
            ps = f"{ps_family}-{base}"
        name.setName(sub, inst.subfamilyNameID, *WIN)
        if inst.postscriptNameID in (None, 0, 0xFFFF):
            inst.postscriptNameID = name.addName(ps, platforms=[WIN])
        else:
            name.setName(ps, inst.postscriptNameID, *WIN)

    used = set()
    for inst in font["fvar"].instances:
        used.add(inst.subfamilyNameID)
        used.add(inst.postscriptNameID)
    for axis in font["fvar"].axes:
        used.add(axis.axisNameID)
    if "STAT" in font:
        stat = font["STAT"].table
        if stat.DesignAxisRecord:
            for ax in stat.DesignAxisRecord.Axis:
                used.add(ax.AxisNameID)
        if stat.AxisValueArray:
            for av in stat.AxisValueArray.AxisValue:
                used.add(getattr(av, "ValueNameID", None))
        used.add(getattr(stat, "ElidedFallbackNameID", None))
    for rec in [r for r in name.names if r.nameID >= 256 and r.nameID not in used]:
        name.removeNames(nameID=rec.nameID)


def finalize_vf(config: ProjectConfig, src: Path, out: Path, italic: bool) -> Path:
    family = config.family.name
    ps_family = _ps_family(config)
    font = TTFont(str(src))
    ps = f"{ps_family}-Italic" if italic else ps_family
    sub = "Italic" if italic else "Regular"
    setname(font, family, 1)  # family
    setname(font, sub, 2)  # subfamily (RIBBI)
    setname(font, f"{family} {sub}" if italic else family, 4)  # full name
    setname(font, ps, 6)  # postscript
    setname(font, family, 16)  # typographic family
    setname(font, sub, 17)  # typographic subfamily
    setname(font, config.family.designer, 8)
    setname(font, config.family.designer, 9)
    setname(font, config.family.designer_url, 11)
    setname(font, config.family.designer_url, 12)
    stamp_version(font, config, ps)
    font["OS/2"].achVendID = config.family.vendor
    os2 = font["OS/2"]
    head = font["head"]
    if italic:
        os2.fsSelection = (os2.fsSelection | 0x001) & ~0x040  # ITALIC, not REGULAR
        head.macStyle |= 0x2
    else:
        os2.fsSelection = (os2.fsSelection | 0x040) & ~0x001  # REGULAR, not ITALIC
        head.macStyle &= ~0x2
    normalize_vertical_metrics(font)
    fix_instances(font, config, italic)
    out.parent.mkdir(parents=True, exist_ok=True)
    font.save(str(out))
    return out


def woff2(ttf: Path) -> Path:
    font = TTFont(str(ttf))
    font.flavor = "woff2"
    w = ttf.with_suffix(".woff2")
    font.save(str(w))
    return w


def _release_dir(config: ProjectConfig) -> Path:
    release = Path(config.output.release_dir)
    if not release.is_absolute():
        release = config.repo_root / release
    return release


def _out_name(src: Path) -> str:
    """Release filename from the built VF: strip the ``-vf`` build suffix."""
    return src.name.replace("-vf", "")


def release_style(config: ProjectConfig, style_key: str) -> Path:
    style = config.styles[style_key]
    out_dir = _release_dir(config)
    out = out_dir / _out_name(style.output)
    finalize_vf(config, style.output, out, style.italic)
    woff2(out)
    return out


def main(argv: list[str] | None = None) -> int:
    """Thin wrapper: ``python -m variable_gen.release`` == ``variable-gen release``."""
    from variable_gen.cli import run_command

    return run_command("release", argv)


if __name__ == "__main__":
    raise SystemExit(main())
