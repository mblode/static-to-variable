"""Clipping checks see real owner ink, including interior variation peaks."""

import pytest
from fontTools.ttLib import newTable
from fontTools.ttLib.tables.TupleVariation import TupleVariation

from test_release_components import fixture_font
from variable_gen.rendered_metrics import check_rendered_metrics


def prepared():
    font = fixture_font()
    font["OS/2"].usWinAscent = 210
    font["OS/2"].usWinDescent = 100
    return font


def test_internal_carrier_is_not_owner_ink_and_input_is_unchanged():
    font = prepared()
    result = check_rendered_metrics(font, internal_glyphs={"carrier"})
    assert result["passed"]
    assert result["ownerCount"] == 3
    assert result["maximumInkY"]["value"] == 205
    assert font["hmtx"]["carrier"][0] == 40000
    assert not check_rendered_metrics(font)["passed"]


def test_interior_peak_and_unencoded_owner_cannot_hide_clipping():
    font = prepared()
    font["gvar"].variations["middle"].append(
        TupleVariation({"wght": (0, 0.5, 1)}, [(0, 20)] + [(0, 0)] * 4)
    )
    result = check_rendered_metrics(font, internal_glyphs={"carrier"})
    assert not result["passed"]
    assert 650 in result["supportCornerLocations"]["wght"]
    assert any(row["glyph"] == "middle" for row in result["failures"])


def test_static_owner_is_measured():
    font = prepared()
    del font["gvar"], font["fvar"], font["HVAR"]
    result = check_rendered_metrics(font, internal_glyphs={"carrier"})
    assert result["passed"] and result["checks"] == 3


def test_encoded_carrier_is_rejected():
    font = prepared()
    font["cmap"].tables[0].cmap[66] = "carrier"
    with pytest.raises(ValueError, match="cmap"):
        check_rendered_metrics(font, internal_glyphs={"carrier"})


def test_invalid_internal_transform_is_rejected():
    font = prepared()
    font["glyf"]["middle"].components[0].transform = [[1, 0], [0, 1]]
    with pytest.raises(ValueError, match="precision scale"):
        check_rendered_metrics(font, internal_glyphs={"carrier"})


def test_nonmonotone_axis_map_is_rejected():
    font = prepared()
    font["avar"] = newTable("avar")
    font["avar"].majorVersion = 1
    font["avar"].segments = {"wght": {-1: -1, 0: 0, 0.5: 0, 1: 1}}
    with pytest.raises(ValueError, match="strictly monotone"):
        check_rendered_metrics(font, internal_glyphs={"carrier"})
