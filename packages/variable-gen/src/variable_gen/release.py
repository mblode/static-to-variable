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

from fontTools.ttLib import TTFont
from fontTools.ttLib.reorderGlyphs import reorderGlyphs

from variable_gen.config import ProjectConfig

WIN = (3, 1, 0x409)
MAC = (1, 0, 0)


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


def fix_vertical_metrics(
    font, *, win_ascent: float | None = None, win_descent: float | None = None
) -> None:
    """Use the intended line box while keeping every glyph clipping-safe.

    ``sTypo*`` is the cross-platform layout contract. The USE_TYPO_METRICS bit
    asks supporting applications to honour it, and matching ``hhea`` values
    gives older Apple software the same result. Windows clipping metrics are a
    separate ink-coverage envelope, so they must include both the line box and
    the font's real extrema.
    """
    os2 = font["OS/2"]
    hhea = font["hhea"]
    head = font["head"]

    os2.fsSelection |= 0x080  # USE_TYPO_METRICS
    hhea.ascent = os2.sTypoAscender
    hhea.descent = os2.sTypoDescender
    hhea.lineGap = os2.sTypoLineGap
    os2.usWinAscent = math.ceil(
        max(0, os2.sTypoAscender, head.yMax, win_ascent if win_ascent is not None else 0)
    )
    os2.usWinDescent = math.ceil(
        max(0, -os2.sTypoDescender, -head.yMin, win_descent if win_descent is not None else 0)
    )


def fix_instances(font, config: ProjectConfig, italic: bool):
    """Rewrite fvar named-instance subfamily + PostScript names and drop orphan
    name records, deriving names from the weight coordinate so the result is
    independent of what the source emitted (Glyphs emits an empty subfamily for
    the default instance and italic PS names that collide with the roman's)."""
    if "fvar" not in font:
        return
    ps_family = _ps_family(config)
    name = font["name"]
    stat_name_ids: set[int] = set()
    if "STAT" in font:
        stat = font["STAT"].table
        if stat.DesignAxisRecord:
            stat_name_ids.update(axis.AxisNameID for axis in stat.DesignAxisRecord.Axis)
        if stat.AxisValueArray:
            stat_name_ids.update(value.ValueNameID for value in stat.AxisValueArray.AxisValue)
        if stat.ElidedFallbackNameID is not None:
            stat_name_ids.add(stat.ElidedFallbackNameID)
    for inst in font["fvar"].instances:
        parts: list[str] = []
        at_default = True
        for index, axis in enumerate(config.axes):
            value = int(round(inst.coordinates.get(axis.tag, axis.default)))
            label = {int(pos): nm for pos, nm in axis.named_instances.items()}.get(
                value, str(value)
            )
            if index == 0 or value != int(axis.default):
                parts.append(label)
            if value != int(axis.default):
                at_default = False
        base = " ".join(parts) if parts else "Regular"
        ps_base = "".join(parts) if parts else "Regular"
        is_regular = at_default
        if italic:
            sub = "Italic" if is_regular else f"{base} Italic"
            ps = f"{ps_family}-Italic" if is_regular else f"{ps_family}-{ps_base}Italic"
        else:
            sub = base
            ps = ps_family if is_regular else f"{ps_family}-{ps_base}"
        # varLib may intentionally share a name ID between an axis-value label
        # and a named instance. Rewriting that record would turn a STAT label
        # such as "Text" into "Regular Text". Give the instance its own ID and
        # leave axis metadata untouched.
        if inst.subfamilyNameID in stat_name_ids:
            inst.subfamilyNameID = name.addName(sub, platforms=[WIN, MAC])
        else:
            setname(font, sub, inst.subfamilyNameID)
        if inst.postscriptNameID in (None, 0, 0xFFFF):
            inst.postscriptNameID = name.addName(ps, platforms=[WIN, MAC])
        else:
            setname(font, ps, inst.postscriptNameID)

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
    # FontTools' static-name updater visits every platform represented in the
    # name table. Keep all fvar/STAT names available on both of our declared
    # platforms so named-instance generation is well-defined.
    for name_id in used:
        if name_id is None:
            continue
        record = name.getName(name_id, *WIN) or name.getName(name_id, *MAC)
        if record is not None:
            setname(font, record.toUnicode(), name_id)
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
    if config.family.license:
        setname(font, config.family.license, 13)
    if config.family.license_url:
        setname(font, config.family.license_url, 14)
    stamp_version(font, config, ps)
    font["OS/2"].achVendID = config.family.vendor
    os2 = font["OS/2"]
    head = font["head"]
    if config.family.license == "OFL-1.1":
        os2.fsType = 0  # installable embedding; the OFL imposes no embedding restriction
    if italic:
        os2.fsSelection = (os2.fsSelection | 0x001) & ~0x040  # ITALIC, not REGULAR
        head.macStyle |= 0x2
    else:
        os2.fsSelection = (os2.fsSelection | 0x040) & ~0x001  # REGULAR, not ITALIC
        head.macStyle &= ~0x2
    metrics = config.vertical_metrics
    fix_vertical_metrics(
        font,
        win_ascent=metrics.win_ascent if metrics else None,
        win_descent=metrics.win_descent if metrics else None,
    )
    fix_instances(font, config, italic)
    # Ported layout tables can still be ordered for a donor's glyph IDs. Sort
    # Coverage tables and their parallel records for the final VF glyph order;
    # malformed ordering breaks kerning instantiation in strict consumers.
    reorderGlyphs(font, font.getGlyphOrder())
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
