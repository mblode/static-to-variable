"""Internal component cleanup preserves rendered owners and fails before mutation."""

from copy import deepcopy
from io import BytesIO

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables
from fontTools.ttLib.tables.TupleVariation import TupleVariation
from fontTools.varLib.varStore import OnlineVarStoreBuilder

from variable_gen.release_components import NO_VARIATION, normalize_internal_components


def fixture_font():
    names = [".notdef", "carrier", "middle", "A"]
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((6400, 0))
    pen.lineTo((6400, 12800))
    pen.lineTo((0, 12800))
    pen.closePath()
    glyphs = {".notdef": TTGlyphPen(None).glyph(), "carrier": pen.glyph()}
    pen = TTGlyphPen(glyphs)
    pen.addComponent("carrier", (1 / 64, 0, 0, 1 / 64, 0, 0))
    glyphs["middle"] = pen.glyph()
    pen = TTGlyphPen(glyphs)
    pen.addComponent("middle", (1, 0, 0, 1, 0, 0))
    glyphs["A"] = pen.glyph()
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({n: (40000 if n == "carrier" else 500, 0) for n in names})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupCharacterMap({65: "A"})
    builder.setupNameTable({"familyName": "Internal Components", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    builder.setupMaxp()
    builder.setupFvar([("wght", 100, 400, 900, "Weight")], [])
    font = builder.font
    font["gvar"] = newTable("gvar")
    support = {"wght": (0, 1, 1)}
    font["gvar"].variations = {
        ".notdef": [],
        "carrier": [TupleVariation(support, [(0, 0), (64, 0), (64, 128), (0, 128)] + [(0, 0)] * 4)],
        "middle": [TupleVariation(support, [(0, 0)] + [(0, 0), (12, 0), (0, 0), (0, 0)])],
        "A": [TupleVariation(support, [(7, 3)] + [(0, 0)] * 4)],
    }
    store = OnlineVarStoreBuilder(["wght"])
    store.setSupports([support])
    indices = {n: store.storeDeltas([640 if n == "carrier" else 15]) for n in names}
    font["HVAR"] = newTable("HVAR")
    table = font["HVAR"].table = otTables.HVAR()
    table.Version = 0x10000
    table.VarStore = store.finish()
    table.AdvWidthMap = otTables.VarIdxMap()
    table.AdvWidthMap.mapping = indices
    table.LsbMap = table.RsbMap = None
    return font


def rendered(font, name, weight):
    glyphs = font.getGlyphSet(location={"wght": weight})
    pen = DecomposingRecordingPen(glyphs)
    glyphs[name].draw(pen)
    return pen.value, glyphs[name].width


def test_saved_owners_keep_outlines_advances_and_component_variation():
    before = fixture_font()
    after = deepcopy(before)
    variation = deepcopy(after["gvar"].variations["carrier"][0].coordinates)
    result = normalize_internal_components(after, internal_glyphs={"carrier"}, flatten_owners={"A"})
    assert result["flattened"] == [{"owner": "A", "intermediate": "middle", "helper": "carrier"}]
    assert result["zeroedUnencodedAdvances"] == ["carrier"]
    assert after["gvar"].variations["carrier"][0].coordinates == variation
    assert after["HVAR"].table.AdvWidthMap.mapping["carrier"] == NO_VARIATION
    stream = BytesIO()
    after.save(stream)
    stream.seek(0)
    saved = TTFont(stream)
    for weight in (100, 400, 550, 700, 900):
        for name in (".notdef", "middle", "A"):
            assert rendered(before, name, weight) == rendered(saved, name, weight)
        assert rendered(saved, "carrier", weight)[1] == 0


@pytest.mark.parametrize(
    "problem", ["cmap", "feature", "inherited", "moving", "transform", "implicit"]
)
def test_unsafe_input_fails_before_any_mutation(problem):
    font = fixture_font()
    if problem == "cmap":
        font["cmap"].tables[0].cmap[97] = "carrier"
    elif problem == "feature":
        addOpenTypeFeaturesFromString(font, "feature salt { sub A by carrier; } salt;")
    elif problem == "inherited":
        font["glyf"]["middle"].components[0].flags |= 0x200
    elif problem == "moving":
        font["gvar"].variations["middle"][0].coordinates[0] = (1, 0)
    elif problem == "transform":
        font["glyf"]["A"].components[0].x = 1
    elif problem == "implicit":
        font["HVAR"].table.AdvWidthMap = None
    with pytest.raises(ValueError):
        normalize_internal_components(font, internal_glyphs={"carrier"}, flatten_owners={"A"})
    assert font["hmtx"]["carrier"][0] == 40000
    assert font["glyf"]["A"].components[0].glyphName == "middle"


def test_helper_name_is_never_inferred():
    font = fixture_font()
    with pytest.raises(ValueError, match="authenticated"):
        normalize_internal_components(font, internal_glyphs=set(), flatten_owners={"A"})
    assert font["hmtx"]["carrier"][0] == 40000
