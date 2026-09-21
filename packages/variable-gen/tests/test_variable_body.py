from copy import deepcopy
from io import BytesIO

import pytest
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates

from variable_gen.common import PipelineError
from variable_gen.variable_body import extract_variable_contours, reuse_variable_body
from test_variation_reference import fonts


def fixture():
    font, _ = fonts()
    order = font.getGlyphOrder()[:]
    g = deepcopy(font["glyf"]["curve"])
    font["glyf"]["body"] = deepcopy(g)
    font["hmtx"]["body"] = font["hmtx"]["curve"]
    font["gvar"].variations["body"] = deepcopy(font["gvar"].variations["curve"])
    g.coordinates = GlyphCoordinates(
        [*g.coordinates, *((x + 130, y + 200) for x, y in g.coordinates)]
    )
    g.flags.extend(g.flags[:])
    g.endPtsOfContours = [2, 5]
    g.numberOfContours = 2
    font["glyf"]["curve"] = g
    for v in font["gvar"].variations["curve"]:
        v.coordinates = v.coordinates[:3] + [(0, 0), (5, 2), None] + [(0, 0)] * 4
    font.setGlyphOrder([*order, "body"])
    return font


def recording(font, weight, optical):
    gs = font.getGlyphSet(location={"wght": weight, "opsz": optical})
    pen = DecomposingRecordingPen(gs)
    gs["curve"].draw(pen)
    return pen.value, gs["curve"].width


@pytest.mark.parametrize("serialized", [False, True])
def test_sparse_accent_extraction_roundtrips_without_changing_ink_or_metrics(serialized):
    original = fixture()
    if serialized:
        stream = BytesIO()
        original.save(stream)
        stream.seek(0)
        original = TTFont(stream)
    result, report = reuse_variable_body(original, "curve", "body")
    assert report["accentContours"] == [1]
    assert "curve.stvMark" not in original.getGlyphOrder()
    output = BytesIO()
    result.save(output)
    output.seek(0)
    result = TTFont(output)
    for weight in (100, 237.5, 400, 625.5, 950):
        for optical in (14, 23, 32):
            assert recording(result, weight, optical) == recording(original, weight, optical)


def test_external_single_contour_accent_preserves_owner_body_and_advance():
    original = fixture()
    source = deepcopy(original)
    mark = source["glyf"]["curve"]
    mark.coordinates = GlyphCoordinates(mark.coordinates[3:])
    mark.flags = mark.flags[3:]
    mark.endPtsOfContours = [2]
    mark.numberOfContours = 1
    source["gvar"].variations["curve"] = []
    result, _ = reuse_variable_body(
        original, "curve", "body", accent_font=source, contour_indices=(0,)
    )
    assert len(result["glyf"]["curve"].components) == 2
    assert result["hmtx"]["curve"] == original["hmtx"]["curve"]
    assert list(result["glyf"]["curve.stvMark"].coordinates) == list(mark.coordinates)


def test_complete_contour_extraction_retains_sparse_inference_after_serialization():
    original = fixture()
    result = extract_variable_contours(original, "curve", (1,))
    output = BytesIO()
    result.save(output)
    output.seek(0)
    result = TTFont(output)
    for weight in (100, 400, 625.5, 950):
        expected, width = recording(original, weight, 14)
        actual, actual_width = recording(result, weight, 14)
        # Every test contour has exactly four recording operations.
        assert actual == expected[4:]
        assert actual_width == width
    assert original["glyf"]["curve"].numberOfContours == 2


@pytest.mark.parametrize("defect", ["cycle", "missing", "selection", "axes", "collision"])
def test_invalid_recipe_is_rejected_without_mutating_input(defect):
    original = fixture()
    body = "body"
    kwargs = {}
    if defect == "cycle":
        body = "curve"
    elif defect == "missing":
        body = "absent"
    elif defect == "selection":
        kwargs["contour_indices"] = (4,)
    elif defect == "axes":
        source = deepcopy(original)
        source["fvar"].axes[0].maxValue = 900
        kwargs["accent_font"] = source
    elif defect == "collision":
        order = original.getGlyphOrder()[:]
        original["glyf"]["curve.stvMark"] = deepcopy(original["glyf"]["body"])
        original["hmtx"]["curve.stvMark"] = (200, 0)
        original.setGlyphOrder([*order, "curve.stvMark"])
    before = deepcopy(original["glyf"]["curve"])
    with pytest.raises(PipelineError):
        reuse_variable_body(original, "curve", body, **kwargs)
    assert original["glyf"]["curve"].coordinates == before.coordinates
