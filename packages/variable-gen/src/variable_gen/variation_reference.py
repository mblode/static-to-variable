"""Retain a reference's sparse interpolation with explicit integer residuals."""

from copy import deepcopy

from fontTools.misc.roundTools import otRound
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables.TupleVariation import TupleVariation
from fontTools.varLib.iup import iup_delta

from variable_gen.common import PipelineError


def restore_reference_inference(
    reference: TTFont, candidate: TTFont, glyphs: frozenset[str]
) -> dict[str, int]:
    """Restore fractional IUP behavior for explicitly selected, matching glyphs.

    This changes candidate coordinates by less than one unit. It is not a
    general geometry-preservation guarantee: a changed default can change IUP's
    coordinate frame. Callers must verify protected geometry and authored
    fidelity afterward. All validation precedes mutation.
    """

    def axes(font):
        return [(a.axisTag, a.minValue, a.defaultValue, a.maxValue) for a in font["fvar"].axes]

    if axes(reference) != axes(candidate):
        raise PipelineError("Reference inference requires identical axis normalization")
    avar = [
        font["avar"].compile(font) if "avar" in font else None for font in (reference, candidate)
    ]
    if avar[0] != avar[1]:
        raise PipelineError("Reference inference requires identical avar mapping")
    if reference["head"].unitsPerEm != candidate["head"].unitsPerEm:
        raise PipelineError("Reference inference requires identical units per em")
    staged = {}
    counts = {}
    for name in sorted(glyphs):
        old, new = reference["glyf"][name], candidate["glyf"][name]
        if old.isComposite() or new.isComposite():
            raise PipelineError(f"{name}: reference inference requires simple contours")
        if (list(old.endPtsOfContours), list(old.flags)) != (
            list(new.endPtsOfContours),
            list(new.flags),
        ):
            raise PipelineError(f"{name}: reference inference requires identical point topology")
        coords, controls = candidate["glyf"]._getCoordinatesAndControls(
            name, candidate["hmtx"].metrics, getattr(candidate.get("vmtx"), "metrics", None)
        )
        revised = []
        count = 0
        for variation in candidate["gvar"].variations[name]:
            matches = [v for v in reference["gvar"].variations[name] if v.axes == variation.axes]
            if len(matches) > 1:
                raise PipelineError(f"{name}: ambiguous reference variation support")
            if not matches or not any(delta is None for delta in matches[0].coordinates):
                revised.append(variation)
                continue
            native = matches[0]
            if len(native.coordinates) != len(variation.coordinates) or any(
                delta is None for delta in variation.coordinates
            ):
                raise PipelineError(
                    f"{name}: reference inference requires explicit matching deltas"
                )
            inferred = iup_delta(native.coordinates, coords, controls.endPts)
            residual = [
                tuple(value - otRound(base) for value, base in zip(delta, original, strict=True))
                for delta, original in zip(variation.coordinates, inferred, strict=True)
            ]
            revised.extend([deepcopy(native), TupleVariation(variation.axes, residual)])
            count += 1
        staged[name] = revised
        counts[name] = count
    for name, variations in staged.items():
        candidate["gvar"].variations[name] = variations
    return counts
