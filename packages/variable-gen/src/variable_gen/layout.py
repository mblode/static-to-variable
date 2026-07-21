"""Port OpenType layout (GDEF/GSUB/GPOS) from a static donor into a built VF.

Both build paths lose the donors' layout tables: the CLI pipeline round-trips
donors through a ``.glyphs`` source that carries outlines and metrics only, and
the showcase builder historically dropped layout before merging. This module
statically ports the default master's GDEF/GSUB/GPOS into the finished variable
font so ligatures and kerning survive (kern values frozen at the default
weight). It degrades instead of failing: glyph names are remapped through the
cmaps when the donor and the VF disagree, lookups referencing glyphs the VF
does not have are pruned via the subsetter's layout closure, and if the result
still cannot compile the font is left exactly as it was.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from fontTools.subset import Options as SubsetOptions
from fontTools.subset import Subsetter
from fontTools.ttLib import TTFont

LAYOUT_TABLES = ("GDEF", "GSUB", "GPOS")


@dataclass
class LayoutReport:
    """What happened to the donor's layout tables."""

    mode: str  # "variable" | "static" | "none"
    tables: tuple[str, ...] = ()
    note: str = ""

    def summary(self) -> str:
        if self.mode == "none":
            return f"layout: none ({self.note})" if self.note else "layout: none"
        extra = f", {self.note}" if self.note else ""
        return f"layout: {self.mode} ({', '.join(self.tables)}{extra})"


def _name_map(donor: TTFont, varfont: TTFont) -> dict[str, str]:
    """donor glyph name -> VF glyph name: identity when the name exists in the
    VF, else matched through the two unicode cmaps."""
    vf_names = set(varfont.getGlyphOrder())
    mapped = {n: n for n in donor.getGlyphOrder() if n in vf_names}
    remaining = [n for n in donor.getGlyphOrder() if n not in mapped]
    if remaining:
        donor_rev = {gname: cp for cp, gname in donor.getBestCmap().items()}
        vf_by_cp = varfont.getBestCmap()
        taken = set(mapped.values())
        for name in remaining:
            cp = donor_rev.get(name)
            vf_name = vf_by_cp.get(cp) if cp is not None else None
            if vf_name and vf_name not in taken:
                mapped[name] = vf_name
                taken.add(vf_name)
    return mapped


def _load_renamed(donor_path: Path, mapping: dict[str, str]) -> TTFont:
    """Load the donor with its glyphs renamed BEFORE any layout table is
    decompiled, so GDEF/GSUB/GPOS come out carrying the VF's names."""
    donor = TTFont(str(donor_path))
    order = donor.getGlyphOrder()
    donor.setGlyphOrder([mapping.get(n, n) for n in order])
    return donor


def _subset_to(donor: TTFont, keep: set[str]) -> None:
    opts = SubsetOptions()
    opts.layout_features = ["*"]
    opts.layout_scripts = ["*"]
    # prune lookups that reference glyphs outside ``keep`` instead of pulling
    # those glyphs in — the VF cannot grow glyphs, so the layout tables must
    # shrink to it (glyf composite closure may still add glyphs to the donor,
    # but layout never references those)
    opts.layout_closure = False
    opts.glyph_names = True
    opts.notdef_outline = True
    opts.recalc_bounds = False
    opts.prune_unicode_ranges = False
    subsetter = Subsetter(options=opts)
    subsetter.populate(glyphs=sorted(keep))
    subsetter.subset(donor)


def _compiles(font: TTFont) -> bool:
    try:
        font.save(BytesIO())
    except Exception:  # noqa: BLE001 (any compile failure means roll back)
        return False
    return True


def port_layout(varfont: TTFont, donor_path: Path) -> LayoutReport:
    """Statically copy GDEF/GSUB/GPOS from the donor at ``donor_path`` into
    ``varfont``. Never raises for layout reasons and never leaves ``varfont``
    broken: on any failure the font is returned to its prior state."""
    plain = TTFont(str(donor_path))
    if not any(t in plain for t in ("GSUB", "GPOS")):
        plain.close()
        return LayoutReport(mode="none", note="donor has no layout tables")
    vf_names = set(varfont.getGlyphOrder())
    mapping = _name_map(plain, varfont)
    plain.close()
    if not mapping:
        return LayoutReport(mode="none", note="no donor glyphs map onto the font")

    donor = _load_renamed(donor_path, mapping)
    keep = set(donor.getGlyphOrder()) & vf_names
    if not keep - {".notdef"}:
        return LayoutReport(mode="none", note="no shared glyphs to keep")
    try:
        _subset_to(donor, keep)
    except Exception:  # noqa: BLE001 (subset edge cases -> give up cleanly)
        return LayoutReport(mode="none", note="layout pruning failed")

    ported: list[str] = []
    saved = {t: varfont[t] for t in LAYOUT_TABLES if t in varfont}
    for tag in LAYOUT_TABLES:
        if tag in donor:
            varfont[tag] = copy.deepcopy(donor[tag])
            ported.append(tag)
    if not ported:
        return LayoutReport(mode="none", note="nothing survived pruning")
    if not _compiles(varfont):
        for tag in LAYOUT_TABLES:
            if tag in varfont:
                del varfont[tag]
        for tag, table in saved.items():
            varfont[tag] = table
        return LayoutReport(mode="none", note="ported tables failed to compile")
    return LayoutReport(mode="static", tables=tuple(ported))
