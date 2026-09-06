from copy import deepcopy
from io import BytesIO

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.misc.roundTools import otRound
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables.TupleVariation import TupleVariation
from fontTools.varLib.iup import iup_delta

from variable_gen.common import PipelineError
from variable_gen.variation_reference import restore_reference_inference


def fonts():
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef", "curve"])
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((100, 0))
    pen.qCurveTo((50, 149), (0, 0))
    pen.closePath()
    builder.setupGlyf({".notdef": TTGlyphPen(None).glyph(), "curve": pen.glyph()})
    builder.setupHorizontalMetrics({".notdef": (200, 0), "curve": (200, 0)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupCharacterMap({99: "curve"})
    builder.setupNameTable({"familyName": "Inference", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    builder.setupMaxp()
    builder.setupFvar([("wght", 100, 400, 950, "Weight"), ("opsz", 14, 14, 32, "Optical size")], [])
    reference = builder.font
    reference["gvar"] = newTable("gvar")
    reference["gvar"].variations = {
        ".notdef": [],
        "curve": [TupleVariation({"wght": (0, 1, 1)}, [(0, 0), (1, 0), None] + [(0, 0)] * 4)],
    }
    candidate = deepcopy(reference)
    coords, controls = reference["glyf"]._getCoordinatesAndControls(
        "curve", reference["hmtx"].metrics
    )
    expanded = iup_delta(
        reference["gvar"].variations["curve"][0].coordinates, coords, controls.endPts
    )
    candidate["gvar"].variations["curve"][0].coordinates = [
        tuple(otRound(value) for value in point) for point in expanded
    ]
    candidate["glyf"]["curve"].coordinates.translate((0, 46))
    candidate["gvar"].variations["curve"].append(
        TupleVariation({"opsz": (0, 1, 1)}, [(0, -46)] * 3 + [(0, 0)] * 4)
    )
    return reference, candidate


def recording(font, weight, optical):
    pen = RecordingPen()
    font.getGlyphSet(location={"wght": weight, "opsz": optical})["curve"].draw(pen)
    return pen.value


def test_fractional_reference_survives_serialization_and_keeps_text_default():
    reference, candidate = fonts()
    assert recording(reference, 950, 32) != recording(candidate, 950, 32)
    untouched = deepcopy(candidate["glyf"]["curve"].coordinates)
    assert restore_reference_inference(reference, candidate, frozenset({"curve"})) == {"curve": 1}
    binary = BytesIO()
    candidate.save(binary)
    binary.seek(0)
    candidate = TTFont(binary)
    for weight in (100, 400, 537.25, 625, 949.99, 950):
        assert recording(reference, weight, 32) == recording(candidate, weight, 32)
    assert candidate["glyf"]["curve"].coordinates == untouched
    assert candidate["fvar"].axes[1].defaultValue == 14
    assert recording(reference, 400, 14) != recording(candidate, 400, 14)


@pytest.mark.parametrize("failure", ["axis", "topology", "compressed"])
def test_incompatible_inference_fails_before_mutation(failure):
    reference, candidate = fonts()
    if failure == "axis":
        candidate["fvar"].axes[0].maxValue = 900
    elif failure == "topology":
        candidate["glyf"]["curve"].flags[1] = 0
    else:
        candidate["gvar"].variations["curve"][0].coordinates[0] = None
    before = deepcopy(candidate["gvar"].variations)
    with pytest.raises(PipelineError):
        restore_reference_inference(reference, candidate, frozenset({"curve"}))
    assert candidate["gvar"].variations == before
