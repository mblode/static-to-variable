#!/usr/bin/env python3
"""Bootstrap a minimal ``.glyphs`` source from a style's default-master donor.

The rebuild engine needs a ``.glyphs`` source only for the *glyph set*: glyph
names + unicodes + a single template master (its vertical metrics). Every
master outline is then re-derived from the donors. A project that starts from
raw static fonts has no such source, so this synthesizes one from the
default-master donor OTF/TTF — one master, one layer per glyph carrying the
donor outline + advance width — and writes it to ``style.source``. The normal
rebuild takes over from there.

Run:  uv run python -m variable_gen.cli bootstrap --config <path> --style all
"""

from __future__ import annotations

from pathlib import Path

from fontTools.ttLib import TTFont
from glyphsLib.classes import GSFont, GSFontMaster, GSGlyph, GSLayer

from variable_gen.config import ProjectConfig, Style
from variable_gen.outlines import donor_outline, draw_into


def _default_donor_path(style: Style) -> Path:
    donor_by_id = {d.id: d for d in style.donors}
    default_master = next(m for m in style.masters if m.default)
    return donor_by_id[default_master.donor_id].path


def bootstrap_style(config: ProjectConfig, style_key: str, *, force: bool = False) -> dict:
    """Synthesize ``style.source`` from the default-master donor. Returns stats.

    No-op (``skipped``) when the source already exists unless ``force`` is set.
    """
    style = config.styles[style_key]
    if style.source.exists() and not force:
        return {"skipped": True, "source": str(style.source), "glyphs": 0}

    donor_path = _default_donor_path(style)
    ttf = TTFont(str(donor_path))
    glyphset = ttf.getGlyphSet()
    cmap_rev = {gname: cp for cp, gname in ttf.getBestCmap().items()}

    font = GSFont()
    font.familyName = config.family.name
    font.unitsPerEm = ttf["head"].unitsPerEm
    if style.italic:
        font.customParameters["Italic Angle"] = ttf["post"].italicAngle

    os2 = ttf["OS/2"]
    master = GSFontMaster()
    master.name = "Regular"
    master.id = f"{config.id}-{style_key}-bootstrap"
    master.ascender = os2.sTypoAscender
    master.descender = os2.sTypoDescender
    master.capHeight = os2.sCapHeight
    master.xHeight = os2.sxHeight
    master.italicAngle = ttf["post"].italicAngle
    font.masters = [master]

    added = 0
    skipped: list[str] = []
    for name in ttf.getGlyphOrder():
        if name == ".notdef":
            continue
        outline = donor_outline(glyphset, name)
        if outline is None:
            skipped.append(name)
            continue
        glyph = GSGlyph(name)
        cp = cmap_rev.get(name)
        if cp is not None:
            glyph.unicode = f"{cp:04X}"
        layer = GSLayer()
        layer.layerId = layer.associatedMasterId = master.id
        draw_into(layer, outline[0])
        layer.width = outline[1]
        glyph.layers = [layer]
        font.glyphs.append(glyph)
        added += 1

    style.source.parent.mkdir(parents=True, exist_ok=True)
    font.save(str(style.source))
    return {
        "skipped": False,
        "source": str(style.source),
        "glyphs": added,
        "unmapped": len(skipped),
        "donor": str(donor_path),
    }


def ensure_source(config: ProjectConfig, style_key: str) -> bool:
    """Auto-bootstrap ``style.source`` if it is missing. Returns True if it
    synthesized a source (logging to stdout), False if one already existed."""
    style = config.styles[style_key]
    if style.source.exists():
        return False
    stats = bootstrap_style(config, style_key)
    print(
        f"[{style_key}] no source at {style.source} — bootstrapped "
        f"{stats['glyphs']} glyphs from {Path(stats['donor']).name}"
    )
    return True


def main() -> int:
    import argparse

    from variable_gen.config import load_config

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, help="path to stv.config.json")
    ap.add_argument("--style", default="all", help="style key, or 'all'")
    ap.add_argument("--force", action="store_true", help="overwrite an existing source")
    args = ap.parse_args()

    config = load_config(args.config)
    if args.style != "all" and args.style not in config.styles:
        raise SystemExit(f"unknown style {args.style!r}; have {sorted(config.styles)}")
    keys = list(config.styles) if args.style == "all" else [args.style]

    for key in keys:
        stats = bootstrap_style(config, key, force=args.force)
        if stats["skipped"]:
            print(
                f"[{key}] source exists at {stats['source']} — skipped (use --force to overwrite)"
            )
        else:
            print(
                f"[{key}] bootstrapped {stats['glyphs']} glyphs "
                f"({stats['unmapped']} unmapped) -> {stats['source']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
