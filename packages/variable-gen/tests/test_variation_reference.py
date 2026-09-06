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
from variable_gen.variation_reference import restore_reference_with_prefixes


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


def prefixed_fonts():
    reference, candidate = fonts()
    pen = TTGlyphPen(None)
    pen.moveTo((0, 46))
    pen.lineTo((100, 46))
    pen.qCurveTo((115, 52), (110, 54))
    pen.qCurveTo((67, 195), (0, 46))
    pen.closePath()
    candidate["glyf"]["curve"] = pen.glyph()
    mapping = (0, 1, 1, 1, 2, 3, 4, 5, 6)
    for variation in candidate["gvar"].variations["curve"]:
        variation.coordinates = [variation.coordinates[index] for index in mapping]
    optical = candidate["gvar"].variations["curve"][1]
    optical.coordinates[2:5] = [(-15, -52), (-10, -54), (-17, -46)]
    return reference, candidate


def without_stationary_prefixes(value):
    result, current = [], None
    for op, points in value:
        if not (op == "qCurveTo" and points and all(point == current for point in points)):
            result.append((op, points))
        if points:
            current = points[-1]
    return result


def test_native_frame_and_constant_tuple_keep_text_and_fractional_display_after_save():
    reference, candidate = prefixed_fonts()
    before = recording(candidate, 400, 14)
    assert restore_reference_with_prefixes(
        reference, candidate, frozenset({"curve"}), {"wght": 400, "opsz": 32}
    ) == {"curve": 1}
    binary = BytesIO()
    candidate.save(binary)
    binary.seek(0)
    candidate = TTFont(binary)
    assert recording(candidate, 400, 14) == before
    assert candidate["fvar"].axes[1].defaultValue == 14
    for weight in (*range(100, 951), 537.25, 949.99):
        actual = without_stationary_prefixes(recording(candidate, weight, 32))
        expected = recording(reference, weight, 32)
        for (op, points), (other_op, other_points) in zip(actual, expected, strict=True):
            assert op == other_op
            for point, other_point in zip(points, other_points, strict=True):
                assert point == pytest.approx(other_point, abs=1e-12, rel=0)


def test_prefix_mapping_rejects_a_moved_protected_point_before_mutation():
    reference, candidate = prefixed_fonts()
    candidate["glyf"]["curve"].coordinates[2] = (116, 52)
    before_glyph = deepcopy(candidate["glyf"]["curve"].coordinates)
    before_variations = deepcopy(candidate["gvar"].variations)
    with pytest.raises(PipelineError, match="exact native prefix"):
        restore_reference_with_prefixes(
            reference, candidate, frozenset({"curve"}), {"wght": 400, "opsz": 32}
        )
    assert before_glyph == candidate["glyf"]["curve"].coordinates
    assert before_variations == candidate["gvar"].variations
