"""Bounded sub-unit Text corrections that cancel at the protected optical end."""

import math
from copy import deepcopy
from typing import Any

from fontTools.misc.roundTools import otRound
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
from fontTools.ttLib.tables.TupleVariation import TupleVariation

from variable_gen.common import PipelineError


def text_precision_carriers(
    original: TTFont,
    targets: dict[str, dict[float, Any]],
    *,
    weight_axis: str = "wght",
    optical_axis: str = "opsz",
    scale: int = 16,
    maximum_correction: float = 1,
) -> tuple[TTFont, dict[str, Any]]:
    """Return a copy with precise compatible Text frames and unchanged Display.

    Targets are unrounded simple quadratic glyphs at the three weight masters.
    Existing sparse tuples and their native inference frame are scaled intact.
    Each integer correction is paired with its negative at maximum optical size.
    This does not authorize a new drawing or replace fidelity/Display validation.
    """
    if (
        scale not in (16, 32)
        or not math.isfinite(maximum_correction)
        or not 0 < maximum_correction <= 1
    ):
        raise PipelineError("Invalid bounded Text precision policy")
    if any(tag not in original for tag in ("glyf", "gvar", "fvar", "hmtx")) or "vmtx" in original:
        raise PipelineError("Text precision requires horizontal TrueType variations")
    axes = {a.axisTag: a for a in original["fvar"].axes}
    if set(axes) != {weight_axis, optical_axis}:
        raise PipelineError("Text precision requires exactly two declared axes")
    weight, optical = axes[weight_axis], axes[optical_axis]
    if (
        not weight.minValue < weight.defaultValue < weight.maxValue
        or optical.defaultValue != optical.minValue
    ):
        raise PipelineError("Text precision requires interior weight and minimum optical defaults")
    if "avar" in original and any(
        k != v for row in original["avar"].segments.values() for k, v in row.items()
    ):
        raise PipelineError("Text precision does not support remapped axes")
    font = deepcopy(original)
    font.ensureDecompiled()
    reports = {}
    weights = (weight.defaultValue, weight.minValue, weight.maxValue)
    for name, masters in sorted(targets.items()):
        helper = f"{name}.stv-semantic{scale}x"
        if (
            name not in font.getGlyphOrder()
            or helper in font.getGlyphOrder()
            or set(masters) != set(weights)
        ):
            raise PipelineError(f"{name}: missing master/glyph or colliding helper")
        old = deepcopy(font["glyf"][name])
        if old.isComposite() or old.numberOfContours <= 0 or old.program.getBytecode():
            raise PipelineError(f"{name}: precision requires unhinted simple contours")
        old_variations = deepcopy(font["gvar"].variations[name])
        corrections = {}
        maximum = 0.0
        for location in weights:
            target = masters[location]
            if (
                target.isComposite()
                or list(target.flags) != list(old.flags)
                or list(target.endPtsOfContours) != list(old.endPtsOfContours)
            ):
                raise PipelineError(f"{name}: Text precision point correspondence changed")
            current, offset = font.getGlyphSet(
                location={weight_axis: location, optical_axis: optical.minValue}
            )[name]._getGlyphAndOffset()
            if abs(offset) > 1e-9:
                raise PipelineError(f"{name}: nonzero frame offset")
            delta = []
            for point, origin in zip(target.coordinates, current.coordinates, strict=True):
                residual = tuple((a - b) * scale for a, b in zip(point, origin, strict=True))
                if not all(
                    math.isfinite(v) and abs(v) <= maximum_correction * scale for v in residual
                ):
                    raise PipelineError(f"{name}: Text correction exceeds its bound")
                maximum = max(maximum, *(abs(v) / scale for v in residual))
                delta.append(tuple(otRound(v) for v in residual))
            corrections[location] = delta + [(0, 0)] * 4
        carrier = deepcopy(old)
        carrier.coordinates = GlyphCoordinates([(x * scale, y * scale) for x, y in old.coordinates])
        carrier.recalcBounds(font["glyf"])
        if any(not -32768 <= v <= 32767 for p in carrier.coordinates for v in p):
            raise PipelineError(f"{name}: precision carrier exceeds coordinate range")
        metrics = tuple(v * scale for v in font["hmtx"][name])
        if not 0 <= metrics[0] <= 65535 or not -32768 <= metrics[1] <= 32767:
            raise PipelineError(f"{name}: precision carrier exceeds metric range")
        variations = []
        owner_variations = []
        for variation in old_variations:
            # IUP treats each phantom as its own one-point contour. An omitted
            # phantom therefore has zero delta, independently of outline IUP.
            phantoms = [p if p is not None else (0, 0) for p in variation.coordinates[-4:]]
            variations.append(
                TupleVariation(
                    deepcopy(variation.axes),
                    [
                        None if p is None else tuple(v * scale for v in p)
                        for p in variation.coordinates
                    ],
                )
            )
            owner_variations.append(TupleVariation(deepcopy(variation.axes), [(0, 0)] + phantoms))
        default = corrections[weight.defaultValue]
        for location in weights:
            support = (
                {weight_axis: (-1, 0, 1)}
                if location == weight.defaultValue
                else {weight_axis: (-1, -1, 0) if location == weight.minValue else (0, 1, 1)}
            )
            delta = (
                default
                if location == weight.defaultValue
                else [
                    (x - a, y - b)
                    for (x, y), (a, b) in zip(corrections[location], default, strict=True)
                ]
            )
            variations.append(TupleVariation(support, delta))
            variations.append(
                TupleVariation({**support, optical_axis: (0, 1, 1)}, [(-x, -y) for x, y in delta])
            )
        font["glyf"][helper] = carrier
        font["hmtx"][helper] = metrics
        if "HVAR" in font:
            mapping = font["HVAR"].table.AdvWidthMap
            if mapping is None:
                raise PipelineError(f"{name}: precision requires explicit HVAR mapping")
            mapping.mapping[helper] = 0xFFFFFFFF
        font["gvar"].variations[helper] = variations
        pen = TTGlyphPen(font.getGlyphSet())
        pen.addComponent(helper, (1 / scale, 0, 0, 1 / scale, 0, 0))
        font["glyf"][name] = pen.glyph()
        font["gvar"].variations[name] = owner_variations
        reports[name] = {
            "scale": scale,
            "maximumCoordinateCorrection": maximum,
            "pointCount": len(old.coordinates),
        }
    return font, reports
