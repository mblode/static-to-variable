"""Attach OpenType layout (GDEF/GSUB/GPOS) to a built variable font.

The CLI pipeline round-trips donors through a ``.glyphs`` source that carries
outlines and metrics only, so fontmake's VF has no usable layout. This module
restores it:

1. **Variable-first** — instantiate the built VF at each master location, port
   that master's donor layout onto the instance, then ``varLib.build`` those
   masters so kerning (and other GPOS) can vary with weight when the merge
   compiles.
2. **Static fallback** — port the default master's GDEF/GSUB/GPOS alone
   (kern values frozen at the default weight).

Both paths degrade instead of failing: glyph names are remapped through the
cmaps when the donor and the VF disagree, lookups referencing glyphs the VF
does not have are pruned, and if the result still cannot compile the font is
left exactly as it was.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal

from fontTools.designspaceLib import (
    AxisDescriptor,
    DesignSpaceDocument,
    InstanceDescriptor,
    SourceDescriptor,
)
from fontTools.subset import Options as SubsetOptions
from fontTools.subset import Subsetter
from fontTools.ttLib import TTFont
from fontTools.varLib import build as varlib_build
from fontTools.varLib.instancer import instantiateVariableFont

LAYOUT_TABLES = ("GDEF", "GSUB", "GPOS")

# Hinting / misc tables that break a clean varLib merge of layout carriers.
_DROP_BEFORE_MERGE = (
    "BASE",
    "JSTF",
    "kern",
    "MATH",
    "fpgm",
    "prep",
    "cvt ",
    "gasp",
)


@dataclass
class LayoutReport:
    """What happened to the donor's layout tables."""

    mode: Literal["variable", "static", "none"]
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


def _prune_glyphs(obj, keep: set[str], _seen: set[int]) -> None:
    """Recursively strip glyph names outside ``keep`` from every Coverage and
    ClassDef reachable from ``obj``.

    The subsetter is *supposed* to leave the donor's GDEF/GSUB/GPOS referencing
    only retained glyphs, but its internal dedup keys subtables by object
    identity, so on some process runs it leaves a class def entry for a dropped
    glyph (classically GDEF's GlyphClassDef of an unencoded ``ogonek.cap``).
    That dangling ref only raises at *compile*, and the compile gate can miss it
    (a false pass), so the crash surfaces at the final save instead. Walking the
    ported tables and dropping stragglers ourselves makes the port deterministic
    regardless of the subsetter's identity-hash order."""
    from fontTools.ttLib.tables.otTables import ClassDef, Coverage  # noqa: PLC0415

    oid = id(obj)
    if oid in _seen:
        return
    _seen.add(oid)
    if isinstance(obj, Coverage):
        obj.glyphs = [g for g in obj.glyphs if g in keep]
        return
    if isinstance(obj, ClassDef):
        obj.classDefs = {g: c for g, c in obj.classDefs.items() if g in keep}
        return
    converters = getattr(obj, "getConverters", None)
    if converters is None:
        return
    for conv in obj.getConverters():
        value = getattr(obj, conv.name, None)
        if value is None:
            continue
        for child in value if isinstance(value, list) else (value,):
            if hasattr(child, "getConverters") or isinstance(child, (Coverage, ClassDef)):
                _prune_glyphs(child, keep, _seen)


def _prune_layout(varfont: TTFont, keep: set[str]) -> None:
    for tag in LAYOUT_TABLES:
        if tag in varfont and getattr(varfont[tag], "table", None) is not None:
            _prune_glyphs(varfont[tag].table, keep, set())


def _compiles(font: TTFont) -> bool:
    try:
        font.save(BytesIO())
    except Exception:  # noqa: BLE001 (any compile failure means roll back)
        return False
    return True


def _restore_layout(varfont: TTFont, saved: dict[str, object]) -> None:
    for tag in LAYOUT_TABLES:
        if tag in varfont:
            del varfont[tag]
    for tag, table in saved.items():
        varfont[tag] = table


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
    # deterministically drop any straggler glyph refs the subsetter left behind
    # (its identity-hash dedup is not stable across runs), so the port never
    # crashes the final save with a dangling class-def entry
    _prune_layout(varfont, vf_names)
    if not _compiles(varfont):
        _restore_layout(varfont, saved)
        return LayoutReport(mode="none", note="ported tables failed to compile")
    return LayoutReport(mode="static", tables=tuple(ported))


def _axis_value(location: dict[str, float], axis_tag: str) -> float:
    if axis_tag in location:
        return float(location[axis_tag])
    if len(location) == 1:
        return float(next(iter(location.values())))
    raise KeyError(axis_tag)


def _designspace(
    masters: list[tuple[TTFont, float]],
    axis_tag: str,
    axis_name: str,
    default_value: float,
) -> DesignSpaceDocument:
    doc = DesignSpaceDocument()
    axis = AxisDescriptor()
    axis.tag = axis_tag
    axis.name = axis_name
    axis.minimum = min(pos for _, pos in masters)
    axis.default = default_value
    axis.maximum = max(pos for _, pos in masters)
    doc.addAxis(axis)

    for font, pos in masters:
        source = SourceDescriptor()
        source.font = font
        source.location = {axis_name: pos}
        source.styleName = f"{axis_tag}{pos:g}"
        if pos == default_value:
            source.copyInfo = True
        doc.addSource(source)

    for _, pos in masters:
        inst = InstanceDescriptor()
        inst.location = {axis_name: pos}
        inst.styleName = f"{axis_tag}{pos:g}"
        doc.addInstance(inst)
    return doc


def attach_layout(
    varfont: TTFont,
    masters: list[tuple[Path, dict[str, float]]],
    *,
    default_donor: Path,
    axis_tag: str = "wght",
    axis_name: str = "Weight",
) -> LayoutReport:
    """Prefer a variable layout merge from all master donors; else static port.

    Never raises for layout reasons and never leaves ``varfont`` broken.
    """
    saved = {t: varfont[t] for t in LAYOUT_TABLES if t in varfont}
    existing: list[tuple[Path, dict[str, float]]] = [
        (Path(path), loc) for path, loc in masters if Path(path).is_file()
    ]
    if len(existing) < 2:
        return port_layout(varfont, default_donor)

    default_donor = Path(default_donor)
    default_value: float | None = None
    for path, loc in existing:
        if path.resolve() == default_donor.resolve():
            try:
                default_value = _axis_value(loc, axis_tag)
            except KeyError:
                default_value = None
            break

    try:
        prepared: list[tuple[TTFont, float]] = []
        order = list(varfont.getGlyphOrder())
        for path, loc in existing:
            pos = _axis_value(loc, axis_tag)
            if default_value is None and path.resolve() == default_donor.resolve():
                default_value = pos
            inst = instantiateVariableFont(copy.deepcopy(varfont), {axis_tag: pos}, inplace=False)
            for tag in LAYOUT_TABLES:
                if tag in inst:
                    del inst[tag]
            for tag in _DROP_BEFORE_MERGE:
                if tag in inst:
                    del inst[tag]
            # Each weight keeps that donor's layout; outlines stay VF-compatible.
            ported = port_layout(inst, path)
            if ported.mode == "none":
                raise RuntimeError(f"no layout from {path.name}: {ported.note}")
            for tag in LAYOUT_TABLES:
                if tag in inst:
                    _ = inst[tag]  # decompile before glyph-order swap
            inst.setGlyphOrder(order)
            prepared.append((inst, pos))

        if default_value is None:
            default_value = sorted(pos for _, pos in prepared)[len(prepared) // 2]

        candidate, _, _ = varlib_build(_designspace(prepared, axis_tag, axis_name, default_value))
        if not _compiles(candidate):
            raise RuntimeError("variable layout merge failed compile gate")

        ported_tags: list[str] = []
        for tag in LAYOUT_TABLES:
            if tag in candidate:
                varfont[tag] = copy.deepcopy(candidate[tag])
                ported_tags.append(tag)
        if not ported_tags:
            raise RuntimeError("variable merge produced no layout tables")
        _prune_layout(varfont, set(varfont.getGlyphOrder()))
        if not _compiles(varfont):
            raise RuntimeError("transplanted variable layout failed to compile")
        return LayoutReport(mode="variable", tables=tuple(ported_tags))
    except Exception:  # noqa: BLE001 — variable path is best-effort
        _restore_layout(varfont, saved)
        return port_layout(varfont, default_donor)
