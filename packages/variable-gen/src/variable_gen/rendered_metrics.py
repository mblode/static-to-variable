"""Measure reachable owner ink across every supported variation cell corner."""

from collections.abc import Collection
from copy import deepcopy
from itertools import product

from fontTools.pens.boundsPen import BoundsPen
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.varLib.models import piecewiseLinearMap

from variable_gen.release_components import normalize_internal_components


def check_rendered_metrics(font, *, internal_glyphs: Collection[str] = ()) -> dict:
    """Check actual owner bounds without treating scaled private carriers as ink.

    The caller authenticates the explicit internal roster. Every other glyph,
    including unencoded alternates, is measured. Helpers must be unreachable
    from encoding/layout and cannot supply inherited metrics. This supports
    ordinary glyf/gvar with constant component transforms and monotone avar v1;
    unsupported variation models fail closed. The report is not visual approval.
    """
    if "glyf" not in font or "VARC" in font:
        raise ValueError("Rendered metrics require ordinary glyf outlines")
    excluded = set(internal_glyphs)
    # Reuse the release reachability guards without modifying caller data.
    normalize_internal_components(deepcopy(font), internal_glyphs=excluded)
    for name in excluded:
        if font["glyf"][name].isComposite():
            raise ValueError("Excluded internal glyphs must be simple outlines")
    for name in font.getGlyphOrder():
        glyph = font["glyf"][name]
        if not glyph.isComposite():
            continue
        for component in glyph.components:
            if component.glyphName in excluded:
                xx, xy, yx, yy, _, _ = component.getComponentInfo()[1]
                if xy or yx or not 0 < xx == yy <= 1 / 16:
                    raise ValueError(
                        "Internal components require a positive uniform precision scale"
                    )
    axes = font["fvar"].axes if "fvar" in font else []
    knots = {axis.axisTag: {-1.0, 0.0, 1.0} for axis in axes}
    if "gvar" in font:
        for variations in font["gvar"].variations.values():
            for variation in variations:
                for tag, support in variation.axes.items():
                    knots[tag].update(support)
    if "MVAR" in font:
        for region in font["MVAR"].table.VarStore.VarRegionList.Region:
            for axis, support in zip(axes, region.VarRegionAxis, strict=True):
                knots[axis.axisTag].update(
                    (support.StartCoord, support.PeakCoord, support.EndCoord)
                )
    locations = {}
    for axis in axes:
        inverse = None
        if "avar" in font:
            if font["avar"].majorVersion != 1:
                raise ValueError("Rendered metrics require avar version 1")
            mapping = font["avar"].segments[axis.axisTag]
            pairs = sorted(mapping.items())
            if any(a[1] >= b[1] for a, b in zip(pairs, pairs[1:], strict=False)):
                raise ValueError("Rendered metrics require strictly monotone avar")
            knots[axis.axisTag].update(mapping.values())
            inverse = {value: key for key, value in mapping.items()}
        values = []
        for value in sorted(knots[axis.axisTag]):
            if inverse is not None:
                value = piecewiseLinearMap(value, inverse)
            span = (
                axis.defaultValue - axis.minValue
                if value < 0
                else axis.maxValue - axis.defaultValue
            )
            values.append(axis.defaultValue + value * span)
        locations[axis.axisTag] = sorted(set(values))
    names = [name for name in font.getGlyphOrder() if name not in excluded]
    low, high, count, failures = None, None, 0, []
    for corner in product(*locations.values()):
        location = dict(zip(locations, corner, strict=True))
        glyphs = font.getGlyphSet(location=location)
        metrics_font = (
            instantiateVariableFont(font, location, inplace=False) if "MVAR" in font else font
        )
        metrics = metrics_font["OS/2"]
        for name in names:
            pen = BoundsPen(glyphs)
            glyphs[name].draw(pen)
            count += 1
            if pen.bounds is None:
                continue
            bottom, top = pen.bounds[1], pen.bounds[3]
            record = {"glyph": name, "location": location}
            if low is None or bottom < low["value"]:
                low = {**record, "value": bottom}
            if high is None or top > high["value"]:
                high = {**record, "value": top}
            if top > metrics.usWinAscent or -bottom > metrics.usWinDescent:
                failures.append(
                    {
                        **record,
                        "bounds": pen.bounds,
                        "winAscent": metrics.usWinAscent,
                        "winDescent": metrics.usWinDescent,
                    }
                )
    return {
        "passed": not failures,
        "checks": count,
        "ownerCount": len(names),
        "excludedInternalGlyphs": sorted(excluded),
        "supportCornerLocations": locations,
        "minimumInkY": low,
        "maximumInkY": high,
        "failures": failures,
    }
