"""Attach OpenType layout (GDEF/GSUB/GPOS) to a built variable font.

The CLI pipeline round-trips donors through a ``.glyphs`` source that carries
outlines and metrics only, so fontmake's VF has no usable layout. This module
restores it, in descending order of fidelity:

1. **Variable merge** — instantiate the built VF at each master location, port
   that master's donor layout onto the instance, then ``varLib.build`` those
   masters so kerning *and* mark attachment vary with weight.
2. **Variable kerning** — port the default master's layout, then vary its kern
   values from the other donors (see :mod:`variable_gen.kerning`). Tier 1 merges
   GSUB, GPOS and GDEF as one unit, so independently compiled statics that
   disagree about ``aalt`` alternates or mark-glyph-set coverage lose their
   variable kerning to a table that could never have varied anyway; this tier
   reads values only, so that disagreement stops mattering.
3. **Static port** — the default master's layout alone, kern frozen at the
   default weight. Where the donors carry no kerning to vary, this is already
   the whole truth.

Every path degrades instead of failing: glyph names are remapped through the
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

from variable_gen.kerning import KerningTooLarge, KernReport, flatten_kern, vary_kern

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

LayoutMode = Literal["variable", "variable-kern", "static", "none"]


@dataclass
class LayoutReport:
    """What happened to the donor's layout tables."""

    mode: LayoutMode
    tables: tuple[str, ...] = ()
    note: str = ""
    kern: KernReport | None = None

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
    masters: list[tuple[TTFont, dict[str, float]]],
    axes: list[tuple[str, str, float, float, float]],
    default_location: dict[str, float],
) -> DesignSpaceDocument:
    doc = DesignSpaceDocument()
    names = {}
    for tag, name, minimum, default, maximum in axes:
        axis = AxisDescriptor()
        axis.tag = tag
        axis.name = name
        axis.minimum = minimum
        axis.default = default
        axis.maximum = maximum
        doc.addAxis(axis)
        names[tag] = name

    for font, location in masters:
        source = SourceDescriptor()
        source.font = font
        source.location = {names[tag]: value for tag, value in location.items()}
        source.styleName = " ".join(f"{tag}{value:g}" for tag, value in location.items())
        if location == default_location:
            source.copyInfo = True
        doc.addSource(source)

    for _, location in masters:
        inst = InstanceDescriptor()
        inst.location = {names[tag]: value for tag, value in location.items()}
        inst.styleName = " ".join(f"{tag}{value:g}" for tag, value in location.items())
        doc.addInstance(inst)
    return doc


def donor_kern(donor_path: Path, varfont: TTFont) -> dict[tuple[str, str], int]:
    """One donor's flattened kerning, keyed by the *VF's* glyph names.

    The donor is renamed before its layout is decompiled, exactly as
    :func:`port_layout` does, so the pairs line up with the coverage tables
    already sitting in the font.
    """
    plain = TTFont(str(donor_path))
    mapping = _name_map(plain, varfont)
    plain.close()
    donor = _load_renamed(donor_path, mapping)
    try:
        return flatten_kern(donor)
    finally:
        donor.close()


def _vary_kerning(
    varfont: TTFont, existing: list[tuple[Path, dict[str, float]]], axis_tag: str
) -> KernReport:
    donors: list[tuple[dict[str, float], dict[tuple[str, str], int]]] = []
    seen: set[tuple[tuple[str, float], ...]] = set()
    for path, location in existing:
        try:
            _axis_value(location, axis_tag)
        except KeyError:
            return KernReport(note=f"{path.name} has no {axis_tag} location")
        canonical = tuple(sorted((tag, float(value)) for tag, value in location.items()))
        if canonical in seen:
            return KernReport(note=f"duplicate donor location {dict(canonical)}")
        seen.add(canonical)
        try:
            donors.append((dict(location), donor_kern(path, varfont)))
        except KerningTooLarge as exc:
            return KernReport(note=f"{path.name}: {exc}")
    if not any(kern for _, kern in donors):
        return KernReport(note="donors carry no kerning")
    return vary_kern(varfont, donors, axis_tag=axis_tag)


def _port_base(varfont: TTFont, donor_path: Path) -> tuple[str, ...]:
    """Copy the donor's ``BASE`` table over, reverting if it will not compile.

    Taken from the default donor rather than merged along with the rest:
    per-script baseline coordinates are not a thing that varies by weight, and
    feeding them through varLib only adds a way for tier 1 to fail.
    """
    donor = TTFont(str(donor_path))
    try:
        if "BASE" not in donor:
            return ()
        previous = varfont["BASE"] if "BASE" in varfont else None
        varfont["BASE"] = copy.deepcopy(donor["BASE"])
        if _compiles(varfont):
            return ("BASE",)
        del varfont["BASE"]
        if previous is not None:
            varfont["BASE"] = previous
        return ()
    finally:
        donor.close()


def attach_layout(
    varfont: TTFont,
    masters: list[tuple[Path, dict[str, float]]],
    *,
    default_donor: Path,
    axis_tag: str = "wght",
    axis_name: str = "Weight",
) -> LayoutReport:
    """Restore donor layout at the best fidelity that compiles.

    Never raises for layout reasons and never leaves ``varfont`` broken.
    """
    default_donor = Path(default_donor)
    existing: list[tuple[Path, dict[str, float]]] = [
        (Path(path), loc) for path, loc in masters if Path(path).is_file()
    ]
    report = _attach(varfont, existing, default_donor, axis_tag, axis_name)
    if report.mode != "none":
        report.tables = tuple(report.tables) + _port_base(varfont, default_donor)
    return report


def _attach(
    varfont: TTFont,
    existing: list[tuple[Path, dict[str, float]]],
    default_donor: Path,
    axis_tag: str,
    axis_name: str,
) -> LayoutReport:
    saved = {t: varfont[t] for t in LAYOUT_TABLES if t in varfont}
    if len(existing) < 2:
        return port_layout(varfont, default_donor)

    merged = _variable_merge(varfont, existing, default_donor, axis_tag, axis_name)
    if merged is not None:
        return merged
    _restore_layout(varfont, saved)

    static = port_layout(varfont, default_donor)
    if static.mode == "none":
        return static

    kern = _vary_kerning(varfont, existing, axis_tag)
    if not kern.applied:
        return LayoutReport(mode="static", tables=static.tables, note=kern.note, kern=kern)
    if _compiles(varfont):
        return LayoutReport(
            mode="variable-kern",
            tables=static.tables,
            note=f"{kern.varying} of {kern.values} kern values vary",
            kern=kern,
        )
    # The varied kerning does not compile — go back to a clean static port
    # rather than shipping a font we cannot save.
    _restore_layout(varfont, saved)
    fallback = port_layout(varfont, default_donor)
    return LayoutReport(
        mode=fallback.mode,
        tables=fallback.tables,
        note="varied kerning failed to compile",
    )


def _variable_merge(
    varfont: TTFont,
    existing: list[tuple[Path, dict[str, float]]],
    default_donor: Path,
    axis_tag: str,
    axis_name: str,
) -> LayoutReport | None:
    """Tier 1: merge every donor's whole layout with varLib. ``None`` if it
    cannot be done, leaving ``varfont`` for the caller to restore."""
    default_location: dict[str, float] | None = None
    for path, loc in existing:
        if path.resolve() == default_donor.resolve():
            default_location = dict(loc)
            break

    try:
        prepared: list[tuple[TTFont, dict[str, float]]] = []
        order = list(varfont.getGlyphOrder())
        for path, loc in existing:
            _axis_value(loc, axis_tag)
            location = dict(loc)
            if default_location is None and path.resolve() == default_donor.resolve():
                default_location = location
            inst = instantiateVariableFont(copy.deepcopy(varfont), location, inplace=False)
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
            prepared.append((inst, location))

        fvar_axes = list(varfont["fvar"].axes)
        axes = [
            (
                axis.axisTag,
                axis_name if axis.axisTag == axis_tag else axis.axisTag,
                axis.minValue,
                axis.defaultValue,
                axis.maxValue,
            )
            for axis in fvar_axes
        ]
        if default_location is None:
            default_location = {axis.axisTag: axis.defaultValue for axis in fvar_axes}

        candidate, _, _ = varlib_build(_designspace(prepared, axes, default_location))
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
    except Exception:  # noqa: BLE001 — tier 1 is best-effort; the caller drops a tier
        return None
