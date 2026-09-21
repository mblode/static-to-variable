"""Reuse a qualified variable body while retaining explicit accent contours."""

from copy import deepcopy
from typing import Any

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables import otTables
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphComponent, GlyphCoordinates

from variable_gen.common import PipelineError


def extract_variable_contours(
    original: TTFont, glyph: str, contour_indices: tuple[int, ...]
) -> TTFont:
    """Select complete simple contours, retaining their native sparse tuples."""
    if any(tag not in original for tag in ("glyf", "gvar", "hmtx")):
        raise PipelineError("Contour extraction requires variable TrueType outlines")
    font = deepcopy(original)
    font.ensureDecompiled()
    if glyph not in font.getGlyphOrder():
        raise PipelineError("Missing contour extraction glyph")
    mark = font["glyf"][glyph]
    if mark.isComposite() or mark.numberOfContours <= 0 or mark.program.getBytecode():
        raise PipelineError("Contour extraction requires unhinted simple contours")
    if "HVAR" in font and any(
        getattr(font["HVAR"].table, key, None) is not None for key in ("LsbMap", "RsbMap")
    ):
        raise PipelineError("Contour extraction does not support explicit sidebearing maps")
    mark.recalcBounds(font["glyf"])
    old_x_min = mark.xMin
    if (
        not contour_indices
        or tuple(sorted(set(contour_indices))) != contour_indices
        or any(type(i) is not int or not 0 <= i < mark.numberOfContours for i in contour_indices)
    ):
        raise PipelineError("Invalid contour extraction selection")
    indexes: list[int] = []
    ends: list[int] = []
    for index in contour_indices:
        start = mark.endPtsOfContours[index - 1] + 1 if index else 0
        indexes.extend(range(start, mark.endPtsOfContours[index] + 1))
        ends.append(len(indexes) - 1)
    mark.coordinates = GlyphCoordinates([mark.coordinates[i] for i in indexes])
    selected_flags = [mark.flags[i] for i in indexes]
    mark.flags = mark.flags[:0]
    mark.flags.extend(selected_flags)
    mark.endPtsOfContours = ends
    mark.numberOfContours = len(ends)
    mark.recalcBounds(font["glyf"])
    advance, bearing = font["hmtx"][glyph]
    font["hmtx"][glyph] = (advance, bearing + mark.xMin - old_x_min)
    for variation in font["gvar"].variations.get(glyph, []):
        variation.coordinates = [variation.coordinates[i] for i in indexes] + variation.coordinates[
            -4:
        ]
    return font


def reuse_variable_body(
    original: TTFont,
    glyph: str,
    body: str | None,
    *,
    contour_indices: tuple[int, ...] = (1,),
    accent_font: TTFont | None = None,
) -> tuple[TTFont, dict[str, Any]]:
    """Compose a body and selected accent contours without refitting either.

    Callers authorize body equivalence and any external accent drawing. This
    primitive retains the owner's metrics and sparse inference within each
    complete contour. With body=None, selected external contours supply the
    complete replacement outline. Saved-outline and protected-end fidelity
    remain gates.
    """
    source = original if accent_font is None else accent_font
    helper = f"{glyph}.stvMark"
    for font in (original, source):
        if any(tag not in font for tag in ("glyf", "gvar", "fvar", "hmtx")) or "vmtx" in font:
            raise PipelineError("Body reuse requires horizontal variable TrueType fonts")

    def axes(font):
        return [(a.axisTag, a.minValue, a.defaultValue, a.maxValue) for a in font["fvar"].axes]

    if axes(original) != axes(source) or original["head"].unitsPerEm != source["head"].unitsPerEm:
        raise PipelineError("Accent axes or units differ from the owner")
    if any(
        "avar" in f and any(k != v for row in f["avar"].segments.values() for k, v in row.items())
        for f in (original, source)
    ):
        raise PipelineError("Body reuse does not support remapped axes")
    if glyph not in original.getGlyphOrder() or (
        body is not None and (glyph == body or body not in original.getGlyphOrder())
    ):
        raise PipelineError("Body reuse requires distinct existing owner and body")
    if body is None and accent_font is None:
        raise PipelineError("Complete outline replacement requires an external source")
    if glyph not in source.getGlyphOrder() or helper in original.getGlyphOrder():
        raise PipelineError("Missing accent glyph or colliding mark helper")
    pending, seen = ([] if body is None else [body]), set()
    while pending:
        name = pending.pop()
        if name == glyph:
            raise PipelineError("Body reuse would create a component cycle")
        if name in seen:
            continue
        seen.add(name)
        item = original["glyf"][name]
        if item.isComposite():
            pending.extend(c.glyphName for c in item.components)
    font = deepcopy(original)
    font.ensureDecompiled()
    source = deepcopy(source)
    source.ensureDecompiled()
    order = font.getGlyphOrder()[:]
    owner_deltas = deepcopy(font["gvar"].variations.get(glyph, []))
    owner_coords, owner_controls = font["glyf"]._getCoordinatesAndControls(
        glyph, font["hmtx"].metrics
    )
    for variation in owner_deltas:
        variation.calcInferredDeltas(owner_coords, owner_controls.endPts)
        variation.coordinates = [(0, 0)] * (1 if body is None else 2) + variation.coordinates[-4:]
    name = glyph
    mark = source["glyf"][name]
    component = GlyphComponent()
    component.x = component.y = 0
    component.flags = 4
    if mark.isComposite():
        variations = source["gvar"].variations.get(name, [])
        if len(mark.components) != 1 or any(
            v.coordinates[0] not in (None, (0, 0)) for v in variations
        ):
            raise PipelineError("Accent carrier must be one stationary component")
        component = deepcopy(mark.components[0])
        _, (xx, xy, yx, yy, dx, dy) = component.getComponentInfo()
        if xy or yx or dx or dy or xx != yy or xx not in (1, 1 / 16, 1 / 32, 1 / 64):
            raise PipelineError("Unsupported accent carrier transform")
        name = component.glyphName
        mark = source["glyf"][name]
    if mark.isComposite() or mark.numberOfContours <= 0 or mark.program.getBytecode():
        raise PipelineError("Accent extraction requires unhinted simple contours")
    if (
        not contour_indices
        or tuple(sorted(set(contour_indices))) != contour_indices
        or any(type(i) is not int or not 0 <= i < mark.numberOfContours for i in contour_indices)
    ):
        raise PipelineError("Invalid accent contour selection")
    indexes: list[int] = []
    ends: list[int] = []
    for index in contour_indices:
        start = mark.endPtsOfContours[index - 1] + 1 if index else 0
        indexes.extend(range(start, mark.endPtsOfContours[index] + 1))
        ends.append(len(indexes) - 1)
    accent = deepcopy(mark)
    accent.coordinates = GlyphCoordinates([mark.coordinates[i] for i in indexes])
    accent.flags = mark.flags[:0]
    accent.flags.extend(mark.flags[i] for i in indexes)
    accent.endPtsOfContours = ends
    accent.numberOfContours = len(ends)
    variations = deepcopy(source["gvar"].variations.get(name, []))
    for variation in variations:
        variation.coordinates = [variation.coordinates[i] for i in indexes] + [(0, 0)] * 4
    font["glyf"][helper] = accent
    font["gvar"].variations[helper] = variations
    font["hmtx"][helper] = font["hmtx"][glyph]
    if "HVAR" in font:
        table = font["HVAR"].table
        if table.AdvWidthMap is None:
            table.AdvWidthMap = otTables.VarIdxMap()
            table.AdvWidthMap.mapping = {n: i for i, n in enumerate(order)}
        for key in ("AdvWidthMap", "LsbMap", "RsbMap"):
            mapping = getattr(table, key, None)
            if mapping is not None:
                mapping.mapping[helper] = mapping.mapping[glyph]
    component.glyphName = helper
    composite = Glyph()
    composite.numberOfContours = -1
    composite.components = [component]
    if body is not None:
        base = GlyphComponent()
        base.glyphName, base.x, base.y, base.flags = body, 0, 0, 4
        composite.components.insert(0, base)
    font["glyf"][glyph] = composite
    font["gvar"].variations[glyph] = owner_deltas
    font.setGlyphOrder([*order, helper])
    return font, {"body": body, "markHelper": helper, "accentContours": list(contour_indices)}
