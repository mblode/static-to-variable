"""Prepare explicitly authenticated internal components for release serialization."""

from __future__ import annotations

import io
from collections.abc import Collection
from copy import deepcopy

from fontTools.misc.xmlWriter import XMLWriter
from fontTools.ttLib import TTFont

USE_MY_METRICS = 0x0200
OVERLAP_COMPOUND = 0x0400
NO_VARIATION = 0xFFFFFFFF


def normalize_internal_components(
    font: TTFont, *, internal_glyphs: Collection[str], flatten_owners: Collection[str] = ()
) -> dict:
    """Flatten safe identity wrappers and neutralize inaccessible oversized advances.

    The caller supplies its authenticated helper and owner names. This function
    never infers private status from a naming convention. All preconditions are
    checked before mutation. Outlines, glyph order, bearings and gvar phantom
    deltas remain intact; only named wrappers and oversized helper advances are
    eligible. This is not a glyph-quality or clipping approval.
    """
    helpers, owners = set(internal_glyphs), set(flatten_owners)
    names = set(font.getGlyphOrder())
    if not helpers <= names or not owners <= names or helpers & owners:
        raise ValueError("Internal glyph and owner authority does not match the font")
    glyf = font["glyf"]
    encoded = {name for table in font["cmap"].tables for name in table.cmap.values()}
    encoded.update(
        name
        for table in font["cmap"].tables
        for values in getattr(table, "uvsDict", {}).values()
        for _, name in values
        if name is not None
    )
    if helpers & encoded:
        raise ValueError("An internal glyph is reachable through cmap")
    for tag in ("GSUB", "GPOS", "COLR", "MATH", "SVG "):
        if tag in font:
            stream = io.StringIO()
            font[tag].toXML(XMLWriter(stream), font)
            if any(name in stream.getvalue() for name in helpers):
                raise ValueError(f"An internal glyph is referenced by {tag}")
    for name in names:
        glyph = glyf[name]
        if glyph.isComposite() and any(
            c.glyphName in helpers and c.flags & USE_MY_METRICS for c in glyph.components
        ):
            raise ValueError("An internal glyph supplies inherited metrics")

    replacements = []
    for owner in sorted(owners):
        glyph = glyf[owner]
        if not glyph.isComposite():
            raise ValueError("A requested owner is not composite")
        found = False
        for index, outer in enumerate(glyph.components):
            child = glyf[outer.glyphName]
            if not child.isComposite():
                continue
            found = True
            if outer.getComponentInfo()[1] != (1, 0, 0, 1, 0, 0):
                raise ValueError("Only identity outer components may be flattened")
            if outer.flags & USE_MY_METRICS or len(child.components) != 1:
                raise ValueError("Wrapper metrics or component count is not supported")
            inner = child.components[0]
            if inner.glyphName not in helpers or inner.flags & USE_MY_METRICS:
                raise ValueError("Wrapper does not reference an authenticated metric-free helper")
            if glyf[inner.glyphName].isComposite():
                raise ValueError("The authenticated helper must be a simple outline")
            if getattr(child, "program", None) and child.program.getBytecode():
                raise ValueError("A hinted wrapper cannot be flattened")
            variations = font["gvar"].variations.get(outer.glyphName, []) if "gvar" in font else []
            if any(v.coordinates[0] not in (None, (0, 0)) for v in variations):
                raise ValueError("A varying inner component offset cannot be flattened")
            replacement = deepcopy(inner)
            replacement.flags |= outer.flags & OVERLAP_COMPOUND
            replacements.append((owner, index, outer.glyphName, replacement))
        if not found:
            raise ValueError("A requested owner contains no nested component")

    zeroed = sorted(name for name in helpers if font["hmtx"][name][0] > 32767)
    advance_map = None
    if zeroed and "HVAR" in font:
        advance_map = font["HVAR"].table.AdvWidthMap
        if advance_map is None or any(name not in advance_map.mapping for name in zeroed):
            raise ValueError("Oversized helper advances require an explicit complete HVAR map")
    for owner, index, _, replacement in replacements:
        glyf[owner].components[index] = replacement
    for name in zeroed:
        font["hmtx"][name] = (0, font["hmtx"][name][1])
        if advance_map is not None:
            advance_map.mapping[name] = NO_VARIATION
    return {
        "flattened": [
            {"owner": owner, "intermediate": child, "helper": component.glyphName}
            for owner, _, child, component in replacements
        ],
        "zeroedUnencodedAdvances": zeroed,
    }
