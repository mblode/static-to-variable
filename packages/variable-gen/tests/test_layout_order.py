"""Feature sorting preserves required, optional and conditional feature identity."""

from copy import deepcopy
from types import SimpleNamespace as Obj

import pytest

from variable_gen.layout_order import sort_feature_records


def fixture():
    default = Obj(FeatureIndex=[0, 2], ReqFeatureIndex=1)
    language = Obj(FeatureIndex=[1], ReqFeatureIndex=0xFFFF)
    substitution = Obj(SubstitutionRecord=[Obj(FeatureIndex=0), Obj(FeatureIndex=1)])
    table = Obj(
        FeatureList=Obj(
            FeatureRecord=[
                Obj(FeatureTag=tag, identity=index)
                for index, tag in enumerate(("zero", "aalt", "zero"))
            ]
        ),
        ScriptList=Obj(
            ScriptRecord=[
                Obj(Script=Obj(DefaultLangSys=default, LangSysRecord=[Obj(LangSys=language)]))
            ]
        ),
        FeatureVariations=Obj(FeatureVariationRecord=[Obj(FeatureTableSubstitution=substitution)]),
    )
    return {"GSUB": Obj(table=table)}, default, language, substitution


def test_all_feature_references_move_with_their_identity():
    font, default, language, substitution = fixture()
    assert sort_feature_records(font) == {"GSUB": 3}
    records = font["GSUB"].table.FeatureList.FeatureRecord
    assert [record.identity for record in records] == [1, 0, 2]
    assert [records[index].identity for index in default.FeatureIndex] == [0, 2]
    assert records[default.ReqFeatureIndex].identity == 1
    assert records[language.FeatureIndex[0]].identity == 1
    assert language.ReqFeatureIndex == 0xFFFF
    assert [records[row.FeatureIndex].identity for row in substitution.SubstitutionRecord] == [1, 0]
    assert sort_feature_records(font) == {}


@pytest.mark.parametrize("kind", ["optional", "required", "variation"])
def test_invalid_reference_fails_before_any_table_mutation(kind):
    font, default, _, substitution = fixture()
    font["GPOS"] = deepcopy(font["GSUB"])
    if kind == "optional":
        default.FeatureIndex.append(99)
    elif kind == "required":
        default.ReqFeatureIndex = 99
    else:
        substitution.SubstitutionRecord[0].FeatureIndex = 99
    before = deepcopy(font)
    with pytest.raises(ValueError, match="missing feature"):
        sort_feature_records(font)
    assert font == before
