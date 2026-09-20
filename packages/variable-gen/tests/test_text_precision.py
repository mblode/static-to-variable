from copy import deepcopy
from io import BytesIO

import pytest
from fontTools.pens.recordingPen import DecomposingRecordingPen, RecordingPen
from fontTools.ttLib import TTFont

from variable_gen.common import PipelineError
from variable_gen.text_precision import text_precision_carriers
from test_variation_reference import fonts


def targets(font):
    result = {}
    for weight in (100, 400, 950):
        glyph, offset = font.getGlyphSet(location={"wght": weight, "opsz": 14})[
            "curve"
        ]._getGlyphAndOffset()
        assert offset == 0
        glyph = deepcopy(glyph)
        glyph.coordinates[2] = (glyph.coordinates[2][0] + 0.375, glyph.coordinates[2][1] + 0.25)
        result[weight] = glyph
    return {"curve": result}


def recording(font, weight, optical):
    glyphs = font.getGlyphSet(location={"wght": weight, "opsz": optical})
    pen = DecomposingRecordingPen(glyphs)
    glyphs["curve"].draw(pen)
    return pen.value, glyphs["curve"].width


@pytest.mark.parametrize("omitted_phantoms", [False, True])
def test_roundtrip_retains_sparse_display_and_corrects_text(omitted_phantoms):
    reference, _ = fonts()
    if omitted_phantoms:
        for variation in reference["gvar"].variations["curve"]:
            variation.coordinates[-4:] = [None] * 4
    authored = targets(reference)
    result, report = text_precision_carriers(reference, authored)
    assert report["curve"]["maximumCoordinateCorrection"] == 0.375
    assert "curve.stv-semantic16x" not in reference.getGlyphOrder()
    assert any(
        p is None for v in result["gvar"].variations["curve.stv-semantic16x"] for p in v.coordinates
    )
    output = BytesIO()
    result.save(output)
    output.seek(0)
    result = TTFont(output)
    for weight in (100, 100.25, 237.5, 400, 625.5, 949.75, 950):
        assert recording(result, weight, 32) == recording(reference, weight, 32)
    for weight in (100, 400, 950):
        expected = RecordingPen()
        authored["curve"][weight].draw(expected, None)
        actual, _ = recording(result, weight, 14)
        desired = expected.value
        for (operation, points), (other, target_points) in zip(actual, desired, strict=True):
            assert operation == other
            for point, target in zip(points, target_points, strict=True):
                assert point == pytest.approx(target, abs=1 / 32)


@pytest.mark.parametrize("defect", ["missing", "topology", "excess", "nan", "collision"])
def test_rejects_unsafe_target_without_mutating_input(defect):
    reference, _ = fonts()
    authored = targets(reference)
    if defect == "missing":
        del authored["curve"][100]
    elif defect == "topology":
        authored["curve"][100].flags[0] = 0
    elif defect in ("excess", "nan"):
        authored["curve"][100].coordinates[0] = (2 if defect == "excess" else float("nan"), 0)
    else:
        reference["glyf"]["curve.stv-semantic16x"] = deepcopy(reference["glyf"]["curve"])
    before = deepcopy(reference["glyf"]["curve"].coordinates)
    with pytest.raises(PipelineError):
        text_precision_carriers(reference, authored)
    assert reference["glyf"]["curve"].coordinates == before
