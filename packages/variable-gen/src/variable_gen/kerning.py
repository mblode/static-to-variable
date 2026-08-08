"""Make ported donor kerning vary with the weight axis.

``layout.py`` transplants the donors' compiled ``GDEF``/``GSUB``/``GPOS`` onto the
built VF. Its preferred path merges every master donor with ``varLib.build`` so
kerning varies, but that merges GSUB, GPOS and GDEF as one unit — and
independently compiled statics routinely disagree on things that cannot vary
anyway (``aalt`` alternate sets, mark-glyph-set coverage, per-weight kern
coverage). One such disagreement aborts the whole merge and the font falls back
to kerning frozen at the default weight.

This module takes the other route: keep the default donor's ported GPOS exactly
as it is and add variation to its kern *values* in place, reading only values —
never structure — out of the other donors. Structural disagreement between
donors becomes irrelevant.

The mechanism is the one ``varLib`` uses internally: per-value master deltas go
into an :class:`OnlineVarStoreBuilder`, each varying value gets a
``VariationIndex`` device table, and the store lands in ``GDEF.VarStore``.
"""

from __future__ import annotations

from dataclasses import dataclass

from fontTools.misc.fixedTools import floatToFixedToFloat
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables as ot
from fontTools.varLib.merger import buildVarDevTable
from fontTools.varLib.models import VariationModel, normalizeValue
from fontTools.varLib.varStore import OnlineVarStoreBuilder

# ValueRecord format bits (OpenType GPOS value record).
X_ADVANCE = 0x0004
X_ADVANCE_DEVICE = 0x0040

# How many glyph pairs to check per class-pair cell. Donors classify glyphs
# differently, so a cell that is one value in the default donor can be several
# in another; sampling a few members is how that gets caught (see
# ``_sampled_value``). More samples catch more non-uniform cells.
_SAMPLES = 4

# Guard against a pathological class-0 cell expanding to glyphs squared.
_MAX_FLAT_PAIRS = 2_000_000

KernMap = dict[tuple[str, str], int]


class KerningTooLarge(RuntimeError):
    """A font's kerning expands past what we are willing to hold in memory.

    Raised rather than returning the pairs collected so far: a partial map
    reads as "these pairs have no kerning", which would have us write varied
    values that are simply wrong instead of declining to vary at all.
    """


@dataclass(frozen=True)
class KernReport:
    """What ``vary_kern`` did to the font's kerning."""

    values: int = 0
    varying: int = 0
    masters: int = 0
    note: str = ""

    @property
    def applied(self) -> bool:
        return self.varying > 0

    def summary(self) -> str:
        if not self.applied:
            return f"kern: static ({self.note})" if self.note else "kern: static"
        return f"kern: variable ({self.varying}/{self.values} values, {self.masters} masters)"


def _kern_lookup_indices(table: ot.GPOS) -> set[int]:
    indices: set[int] = set()
    if table is None or table.FeatureList is None:
        return indices
    for record in table.FeatureList.FeatureRecord:
        if record.FeatureTag == "kern" and record.Feature is not None:
            indices.update(record.Feature.LookupListIndex)
    return indices


def _pair_subtables(font: TTFont) -> list[ot.PairPos]:
    """Every ``PairPos`` subtable reachable from the ``kern`` feature.

    Extension lookups are unwrapped, and a subtable reached through more than
    one lookup is returned once so callers never process it twice.
    """
    if "GPOS" not in font:
        return []
    table = getattr(font["GPOS"], "table", None)
    if table is None or table.LookupList is None:
        return []
    found: list[ot.PairPos] = []
    seen: set[int] = set()
    for index in sorted(_kern_lookup_indices(table)):
        if index >= len(table.LookupList.Lookup):
            continue
        lookup = table.LookupList.Lookup[index]
        for subtable in lookup.SubTable:
            resolved = getattr(subtable, "ExtSubTable", subtable)
            if not isinstance(resolved, ot.PairPos) or resolved.Coverage is None:
                continue
            if id(resolved) in seen:
                continue
            seen.add(id(resolved))
            found.append(resolved)
    return found


def has_kern(font: TTFont) -> bool:
    """Whether the font carries kerning at all, without paying to flatten it."""
    if "GPOS" in font and _kern_lookup_indices(getattr(font["GPOS"], "table", None)):
        return True
    return bool(_legacy_kern(font))


def _class_members(classdef: ot.ClassDef | None, universe: list[str]) -> dict[int, list[str]]:
    """Class index -> its glyphs. Glyphs of ``universe`` absent from the class
    definition fall into class 0, which is what the spec says they mean."""
    members: dict[int, list[str]] = {}
    defs = classdef.classDefs if classdef is not None else {}
    for glyph, index in defs.items():
        members.setdefault(index, []).append(glyph)
    implicit = [glyph for glyph in universe if glyph not in defs]
    if implicit:
        members.setdefault(0, []).extend(implicit)
    for glyphs in members.values():
        glyphs.sort()
    return members


def _legacy_kern(font: TTFont) -> KernMap:
    """Pairs from the pre-OpenType ``kern`` table, so a donor that predates GPOS
    does not silently lose its kerning."""
    pairs: KernMap = {}
    if "kern" not in font:
        return pairs
    for subtable in getattr(font["kern"], "kernTables", []):
        for (left, right), value in getattr(subtable, "kernTable", {}).items():
            if value:
                pairs[(left, right)] = value
    return pairs


def flatten_kern(font: TTFont) -> KernMap:
    """Resolve a font's ``kern`` feature into explicit glyph-pair x-advances.

    Class-based (format 2) subtables are expanded against their class members.
    Zero values are dropped: they carry no kerning and expanding them is what
    would make a wide "everything else" class cost glyphs squared.
    """
    pairs: KernMap = {}
    glyph_order = font.getGlyphOrder()
    for subtable in _pair_subtables(font):
        if not subtable.ValueFormat1 & X_ADVANCE:
            continue
        coverage = subtable.Coverage.glyphs
        if subtable.Format == 1:
            for index, first in enumerate(coverage):
                if index >= len(subtable.PairSet):
                    break
                for record in subtable.PairSet[index].PairValueRecord:
                    value = getattr(record.Value1, "XAdvance", 0) if record.Value1 else 0
                    if value:
                        pairs[(first, record.SecondGlyph)] = value
        elif subtable.Format == 2:
            first_members = _class_members(subtable.ClassDef1, coverage)
            second_members = _class_members(subtable.ClassDef2, glyph_order)
            for index1, class1 in enumerate(subtable.Class1Record):
                for index2, class2 in enumerate(class1.Class2Record):
                    value = getattr(class2.Value1, "XAdvance", 0) if class2.Value1 else 0
                    if not value:
                        continue
                    for first in first_members.get(index1, ()):
                        for second in second_members.get(index2, ()):
                            pairs[(first, second)] = value
                    if len(pairs) > _MAX_FLAT_PAIRS:
                        raise KerningTooLarge(f"kerning expands past {_MAX_FLAT_PAIRS} pairs")
    if not pairs:
        return _legacy_kern(font)
    return pairs


def _samples(firsts: list[str], seconds: list[str]) -> list[tuple[str, str]]:
    """Up to ``_SAMPLES`` representative pairs drawn from two class member lists."""
    picked: list[tuple[str, str]] = []
    for first in firsts:
        for second in seconds:
            picked.append((first, second))
            if len(picked) >= _SAMPLES:
                return picked
    return picked


def _sampled_value(kern: KernMap, samples: list[tuple[str, str]]) -> int | None:
    """One donor's value for a class-pair cell, or ``None`` when it has no single
    answer.

    A cell is one value in the *default* donor's classification, but the other
    donors group glyphs differently, so its members can kern differently there.
    Collapsing that to a median would hand some pairs a value that is wrong by a
    lot. Refusing instead leaves the cell constant, which is the value it has
    today — strictly no worse than the current frozen kerning.
    """
    if not samples:
        return 0
    values = {kern.get(pair, 0) for pair in samples}
    if len(values) != 1:
        return None
    return values.pop()


def _ensure_gdef(font: TTFont) -> ot.GDEF:
    if "GDEF" in font and getattr(font["GDEF"], "table", None) is not None:
        return font["GDEF"].table
    table = newTable("GDEF")
    table.table = ot.GDEF()
    table.table.GlyphClassDef = None
    table.table.AttachList = None
    table.table.LigCaretList = None
    table.table.MarkAttachClassDef = None
    table.table.MarkGlyphSetsDef = None
    font["GDEF"] = table
    return table.table


def _axis_triple(font: TTFont, axis_tag: str) -> tuple[float, float, float] | None:
    if "fvar" not in font:
        return None
    for axis in font["fvar"].axes:
        if axis.axisTag == axis_tag:
            return (axis.minValue, axis.defaultValue, axis.maxValue)
    return None


def vary_kern(
    varfont: TTFont,
    donors: list[tuple[float, KernMap]],
    *,
    axis_tag: str = "wght",
) -> KernReport:
    """Add weight variation to ``varfont``'s existing kern values.

    ``donors`` pairs each master's axis position with that donor's flattened
    kerning. The font's current values stay exactly as they are at the default
    position — every master's sampled value is rebased onto the value already in
    the table — so this can only add variation, never shift the default weight's
    kerning.

    Never raises for kerning reasons; a font it cannot vary is left untouched.
    """
    if len(donors) < 2:
        return KernReport(note="fewer than two donors")
    triple = _axis_triple(varfont, axis_tag)
    if triple is None:
        return KernReport(note=f"no {axis_tag} axis")
    gdef = getattr(varfont.get("GDEF"), "table", None)
    if gdef is not None and getattr(gdef, "VarStore", None) is not None:
        return KernReport(note="GDEF already carries a variation store")

    # Quantize to F2Dot14 exactly as the axis coordinate itself is stored.
    # Modelling against the raw float leaves every interior master's peak a
    # hair off the position a renderer actually resolves to, and every delta
    # there comes back scaled by 0.9999-ish — which rounds half the kern values
    # off by one unit at that weight.
    locations = [
        {axis_tag: floatToFixedToFloat(normalizeValue(position, triple), 14)}
        for position, _ in donors
    ]
    default_index = next(
        (index for index, loc in enumerate(locations) if abs(loc[axis_tag]) < 1e-9), None
    )
    if default_index is None:
        return KernReport(note="no donor at the default axis position")

    subtables = _pair_subtables(varfont)
    if not subtables:
        return KernReport(note="font has no kern pair positioning")

    model = VariationModel(locations, axisOrder=[axis_tag])
    store_builder = OnlineVarStoreBuilder([axis_tag])
    store_builder.setModel(model)
    kern_maps = [kern for _, kern in donors]
    glyph_order = varfont.getGlyphOrder()
    examined = 0
    varied = 0

    def apply(value: ot.ValueRecord, samples: list[tuple[str, str]]) -> bool:
        """Give one value record a device table when the donors disagree."""
        nonlocal examined
        existing = getattr(value, "XAdvance", None)
        if existing is None:
            return False
        examined += 1
        sampled = [_sampled_value(kern, samples) for kern in kern_maps]
        if any(donor_value is None for donor_value in sampled):
            return False
        # The default donor's own sample has to reproduce the value already in
        # the table, because that value came from this donor. When it does not,
        # the sample is describing something else — classically a pair covered
        # by two kern lookups, which flattens to the last writer while this
        # subtable still holds the first. Varying from a sample that disagrees
        # would move every other master by the difference, so leave the cell
        # constant instead: that is the value the font ships today.
        if sampled[default_index] != existing:
            return False
        base, device = buildVarDevTable(store_builder, sampled)
        if device is None:
            return False
        value.XAdvance = base
        value.XAdvDevice = device
        return True

    for subtable in subtables:
        if not subtable.ValueFormat1 & X_ADVANCE:
            continue
        coverage = subtable.Coverage.glyphs
        touched = False
        if subtable.Format == 1:
            for index, first in enumerate(coverage):
                if index >= len(subtable.PairSet):
                    break
                for record in subtable.PairSet[index].PairValueRecord:
                    if record.Value1 is None:
                        continue
                    if apply(record.Value1, [(first, record.SecondGlyph)]):
                        touched = True
                        varied += 1
        elif subtable.Format == 2:
            first_members = _class_members(subtable.ClassDef1, coverage)
            second_members = _class_members(subtable.ClassDef2, glyph_order)
            for index1, class1 in enumerate(subtable.Class1Record):
                firsts = first_members.get(index1, [])
                for index2, class2 in enumerate(class1.Class2Record):
                    if class2.Value1 is None:
                        continue
                    samples = _samples(firsts, second_members.get(index2, []))
                    if apply(class2.Value1, samples):
                        touched = True
                        varied += 1
        if touched:
            subtable.ValueFormat1 |= X_ADVANCE_DEVICE
            _fill_device_gaps(subtable)

    store = store_builder.finish()
    if not varied or store is None or not store.VarData:
        return KernReport(values=examined, masters=len(donors), note="donors kern identically")

    gdef = _ensure_gdef(varfont)
    gdef.Version = 0x00010003
    gdef.VarStore = store
    varidx_map = store.optimize()
    gdef.remap_device_varidxes(varidx_map)
    varfont["GPOS"].table.remap_device_varidxes(varidx_map)
    return KernReport(values=examined, varying=varied, masters=len(donors))


def _fill_device_gaps(subtable: ot.PairPos) -> None:
    """Once a subtable's format advertises ``XAdvDevice``, every value record in
    it has to carry the attribute or compiling raises. The ones we left constant
    get an explicit ``None`` (an absent device offset)."""
    if subtable.Format == 1:
        records = [
            record.Value1
            for pairset in subtable.PairSet
            for record in pairset.PairValueRecord
            if record.Value1 is not None
        ]
    else:
        records = [
            class2.Value1
            for class1 in subtable.Class1Record
            for class2 in class1.Class2Record
            if class2.Value1 is not None
        ]
    for record in records:
        if not hasattr(record, "XAdvDevice"):
            record.XAdvDevice = None
