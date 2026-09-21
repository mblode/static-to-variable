from copy import deepcopy
from io import StringIO
import json

import glyphsLib
import pytest

from variable_gen.quadratic_reference_templates import exact_reference_template, recording_sha256
from variable_gen.quadratic_template_refinement import (
    refine_template_groups,
    serialize_template_recipe,
)


def fixture():
    recording = [
        ("moveTo", ((0, 0),)),
        ("qCurveTo", ((0, 8), (4, 8))),
        ("qCurveTo", ((8, 8), (8, 0))),
        ("lineTo", ((0, 0),)),
        ("closePath", ()),
    ]
    return {"templates": [{"recording": recording, "recordingSha256": recording_sha256(recording)}]}


def test_refinement_preserves_geometry_and_merges_source_groups_without_mutating_input():
    recipe = fixture()
    before = deepcopy(recipe)
    result, groups = refine_template_groups(
        recipe, [((1, 3, 4, 1, 1),)], coalesce=True, subdivisions=2
    )
    recording = result["templates"][0]["recording"]
    assert recipe == before
    assert groups == (((1, 7, 1, 1),),)
    assert len(recording[1][1]) == 5
    assert exact_reference_template(recipe["templates"][0]["recording"], recording)
    assert result["templates"][0]["recordingSha256"] == recording_sha256(recording)


def test_coalescing_requires_midpoint_in_every_protected_master():
    recipe = fixture()
    other = deepcopy(recipe["templates"][0])
    other["recording"][2] = ("qCurveTo", ((9, 8), (8, 0)))
    recipe["templates"].append(other)
    result, groups = refine_template_groups(recipe, [((1, 2, 3, 1, 1),)], coalesce=True)
    assert len(result["templates"][0]["recording"]) == 5
    assert groups == (((1, 2, 3, 1, 1),),)


@pytest.mark.parametrize("groups", [[], [((1, 1),)], [((1, 0, 1, 1, 1),)], [((1, True, 1, 1, 1),)]])
def test_invalid_group_coverage_rejected(groups):
    with pytest.raises(ValueError, match="cover every"):
        refine_template_groups(fixture(), groups)


def test_glyphs_roundtrip_retains_exact_fine_coordinates():
    recipe = fixture()
    recipe["carrierScale"] = 64
    recipe["templates"][0]["recording"][1] = ("qCurveTo", ((0.015625, 8), (4, 8)))
    serialized = serialize_template_recipe(recipe)
    assert serialize_template_recipe(serialized) == serialized
    font = glyphsLib.GSFont()
    font.userData["recipe"] = serialized
    restored = glyphsLib.load(StringIO(glyphsLib.dumps(font))).userData["recipe"]
    assert recording_sha256(json.loads(restored["templates"][0]["recording"])) == recording_sha256(
        recipe["templates"][0]["recording"]
    )
