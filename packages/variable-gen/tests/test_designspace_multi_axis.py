from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.otlLib.builder import buildStatTable
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.designspaceLib import (
    AxisDescriptor,
    DesignSpaceDocument,
    SourceDescriptor,
)
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.ttLib import TTFont
from fontTools.varLib import build as varlib_build
from fontTools.varLib.instancer import instantiateVariableFont

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PACKAGE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from variable_gen.config import load_config  # noqa: E402
from variable_gen.designspace import (  # noqa: E402
    _configure_multi_axis_designspace,
    fix_designspace_axis,
)
from variable_gen.release import fix_instances  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "two-axis-project.json"


def _write_designspace(path: Path, style_key: str = "roman") -> None:
    config = load_config(FIXTURE)
    document = DesignSpaceDocument()
    for config_axis in config.axes:
        axis = AxisDescriptor()
        axis.name = config_axis.name
        axis.tag = config_axis.tag
        # Deliberately wrong: the correction step must replace all four fields.
        axis.minimum = axis.default = axis.maximum = config_axis.default
        axis.map = [(config_axis.default, config_axis.default)]
        document.addAxis(axis)
    for master in config.styles[style_key].masters:
        source = SourceDescriptor()
        source.name = master.name
        source.location = {axis.name: master.location[axis.tag] for axis in config.axes}
        document.addSource(source)
    document.write(path)


def test_axes_labels_and_named_instance_product_are_config_driven(tmp_path: Path) -> None:
    config = load_config(FIXTURE)
    path = tmp_path / "fixture.designspace"
    _write_designspace(path)

    document = DesignSpaceDocument.fromfile(path)
    primary = config.axes[0]
    fix_designspace_axis(
        document,
        axis_tag=primary.tag,
        axis_name=primary.name,
        default_weight=primary.default,
        weight_names=dict(primary.named_instances),
        family=config.family.name,
        is_italic=False,
        write_instances=False,
        minimum=primary.minimum,
        maximum=primary.maximum,
        mapping=primary.mapping,
    )
    document.write(path)

    _configure_multi_axis_designspace(
        path,
        family=config.family.name,
        is_italic=False,
        axes=config.axes,
    )

    document = DesignSpaceDocument.fromfile(path)
    weight, optical_size = document.axes
    assert (weight.minimum, weight.default, weight.maximum) == (100, 400, 950)
    assert weight.map == [(100, 100), (400, 400), (700, 650), (950, 950)]
    assert (optical_size.minimum, optical_size.default, optical_size.maximum) == (12, 16, 28)
    assert [label.name for label in optical_size.axisLabels] == ["Text", "UI", "Display"]
    assert len(document.instances) == 9
    styles = {instance.styleName for instance in document.instances}
    assert {"Regular", "Regular Text", "Regular Display"} <= styles


def test_multi_axis_designspace_rewrite_is_deterministic(tmp_path: Path) -> None:
    config = load_config(FIXTURE)
    outputs = []
    for index in range(2):
        path = tmp_path / f"fixture-{index}.designspace"
        _write_designspace(path, "italic")
        document = DesignSpaceDocument.fromfile(path)
        primary = config.axes[0]
        fix_designspace_axis(
            document,
            axis_tag=primary.tag,
            axis_name=primary.name,
            default_weight=primary.default,
            weight_names=dict(primary.named_instances),
            family=config.family.name,
            is_italic=True,
            write_instances=False,
            minimum=primary.minimum,
            maximum=primary.maximum,
            mapping=primary.mapping,
        )
        document.write(path)
        _configure_multi_axis_designspace(
            path,
            family=config.family.name,
            is_italic=True,
            axes=config.axes,
        )
        outputs.append(path.read_bytes())

    assert outputs[0] == outputs[1]
    document = DesignSpaceDocument.fromstring(outputs[0])
    styles = {instance.styleName for instance in document.instances}
    assert "Italic" in styles
    assert "Regular Text Italic" in styles


def _static_font(path: Path, *, width: int, right: int, top: int, kern: int, italic: bool) -> None:
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef", "A", "V", "acutecomb", "Aacute"])
    empty_pen = TTGlyphPen(None)
    glyphs = {".notdef": empty_pen.glyph()}
    pen = TTGlyphPen(None)
    pen.moveTo((50, 0))
    pen.lineTo((right, 0))
    pen.lineTo((right, top))
    pen.lineTo((50, top))
    pen.closePath()
    glyphs["A"] = pen.glyph()
    pen = TTGlyphPen(None)
    pen.moveTo((80, 0))
    pen.lineTo((right + 30, 0))
    pen.lineTo((right + 30, top))
    pen.lineTo((80, top))
    pen.closePath()
    glyphs["V"] = pen.glyph()
    pen = TTGlyphPen(None)
    pen.moveTo((180, top + 25))
    pen.lineTo((260, top + 90))
    pen.lineTo((300, top + 90))
    pen.lineTo((220, top + 25))
    pen.closePath()
    glyphs["acutecomb"] = pen.glyph()
    pen = TTGlyphPen(glyphs)
    pen.addComponent("A", (1, 0, 0, 1, 0, 0))
    pen.addComponent("acutecomb", (1, 0, 0, 1, 0, 0))
    glyphs["Aacute"] = pen.glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(
        {
            ".notdef": (500, 0),
            "A": (width, 50),
            "V": (width + 10, 80),
            "acutecomb": (0, 180),
            "Aacute": (width, 50),
        }
    )
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupCharacterMap({0x41: "A", 0x56: "V", 0xC1: "Aacute", 0x301: "acutecomb"})
    builder.setupNameTable(
        {
            "familyName": "Two Axis Fixture",
            "styleName": "Italic" if italic else "Regular",
            "uniqueFontIdentifier": f"TwoAxisFixture-{path.stem}",
            "fullName": f"Two Axis Fixture {path.stem}",
            "psName": f"TwoAxisFixture-{path.stem}",
            "version": "Version 1.000",
        }
    )
    builder.setupOS2(
        sTypoAscender=800,
        sTypoDescender=-200,
        usWinAscent=800,
        usWinDescent=200,
    )
    builder.setupPost()
    builder.setupMaxp()
    addOpenTypeFeaturesFromString(builder.font, f"feature kern {{ pos A V {kern}; }} kern;")
    builder.save(path)


def _build_tiny_two_axis_font(tmp_path: Path, style_key: str = "roman") -> TTFont:
    config = load_config(FIXTURE)
    style = config.styles[style_key]
    document = DesignSpaceDocument()
    for config_axis in config.axes:
        axis = AxisDescriptor()
        axis.name = config_axis.name
        axis.tag = config_axis.tag
        axis.minimum = config_axis.minimum
        axis.default = config_axis.default
        axis.maximum = config_axis.maximum
        document.addAxis(axis)

    for master in style.masters:
        weight = master.location["wght"]
        optical_size = master.location["opsz"]
        font_path = tmp_path / f"{master.donor_id}.ttf"
        _static_font(
            font_path,
            width=round(520 + (weight - 400) * 0.12 + (16 - optical_size) * 2),
            right=round(350 + (weight - 400) * 0.08 + (16 - optical_size)),
            top=round(650 + (16 - optical_size)),
            kern=round(-40 - (weight - 400) * 0.04 + (optical_size - 16)),
            italic=style.italic,
        )
        source = SourceDescriptor()
        source.name = master.name
        source.filename = font_path.name
        source.location = {axis.name: master.location[axis.tag] for axis in config.axes}
        if master.default:
            source.copyInfo = True
        document.addSource(source)

    primary = config.axes[0]
    fix_designspace_axis(
        document,
        axis_tag=primary.tag,
        axis_name=primary.name,
        default_weight=primary.default,
        weight_names=dict(primary.named_instances),
        family=config.family.name,
        is_italic=style.italic,
        write_instances=False,
        minimum=primary.minimum,
        maximum=primary.maximum,
        mapping=primary.mapping,
    )
    designspace_path = tmp_path / "tiny.designspace"
    document.write(designspace_path)
    _configure_multi_axis_designspace(
        designspace_path,
        family=config.family.name,
        is_italic=style.italic,
        axes=config.axes,
    )
    variable_font, _model, _masters = varlib_build(designspace_path)
    return variable_font


def _kern_value(font: TTFont) -> int:
    feature_records = font["GPOS"].table.FeatureList.FeatureRecord
    lookup_list = font["GPOS"].table.LookupList.Lookup
    for feature_record in feature_records:
        if feature_record.FeatureTag != "kern":
            continue
        for lookup_index in feature_record.Feature.LookupListIndex:
            for subtable in lookup_list[lookup_index].SubTable:
                if getattr(subtable, "Format", None) != 1:
                    continue
                coverage_index = subtable.Coverage.glyphs.index("A")
                for pair in subtable.PairSet[coverage_index].PairValueRecord:
                    if pair.SecondGlyph == "V":
                        return pair.Value1.XAdvance
    raise AssertionError("fixture kern A/V pair not found")


@pytest.mark.parametrize("style_key", ["roman", "italic"])
def test_two_axis_fixture_builds_all_required_variation_tables(
    tmp_path: Path, style_key: str
) -> None:
    variable_font = _build_tiny_two_axis_font(tmp_path, style_key)

    assert {"fvar", "avar", "gvar", "HVAR", "STAT"} <= set(variable_font.keys())
    assert [axis.axisTag for axis in variable_font["fvar"].axes] == ["wght", "opsz"]
    assert len(variable_font["fvar"].instances) == 9
    assert variable_font["glyf"]["Aacute"].isComposite()
    default = instantiateVariableFont(variable_font, {"wght": 400, "opsz": 16}, inplace=False)
    instance = instantiateVariableFont(variable_font, {"wght": 950, "opsz": 28}, inplace=False)
    assert instance["hmtx"].metrics["A"][0] == 562
    assert _kern_value(default) != _kern_value(instance)
    assert "fvar" not in instance


@pytest.mark.parametrize("style_key", ["roman", "italic"])
def test_two_axis_binary_build_is_deterministic(tmp_path: Path, style_key: str) -> None:
    variable_font = _build_tiny_two_axis_font(tmp_path, style_key)
    first = BytesIO()
    second = BytesIO()
    variable_font.save(first, reorderTables=False)
    variable_font.save(second, reorderTables=False)

    assert first.getvalue() == second.getvalue()


def test_release_keeps_stat_optical_labels_distinct_from_instance_names(
    tmp_path: Path,
) -> None:
    config = load_config(FIXTURE)
    variable_font = _build_tiny_two_axis_font(tmp_path)
    buildStatTable(
        variable_font,
        [
            {"tag": "wght", "name": "Weight"},
            {
                "tag": "opsz",
                "name": "Optical size",
                "values": [
                    {"value": 12, "name": "Text"},
                    {"value": 16, "name": "UI", "flags": 0x2},
                    {"value": 28, "name": "Display"},
                ],
            },
        ],
    )
    stat = variable_font["STAT"].table
    optical_labels = [
        variable_font["name"].getDebugName(value.ValueNameID)
        for value in stat.AxisValueArray.AxisValue
        if value.AxisIndex == 1
    ]
    text_name_id = next(
        value.ValueNameID
        for value in stat.AxisValueArray.AxisValue
        if value.AxisIndex == 1 and value.Value == 12
    )
    text_instance = next(
        instance
        for instance in variable_font["fvar"].instances
        if instance.coordinates == {"wght": 400, "opsz": 12}
    )
    text_instance.subfamilyNameID = text_name_id

    fix_instances(variable_font, config, italic=False)

    assert optical_labels == ["Text", "UI", "Display"]
    assert [
        variable_font["name"].getDebugName(value.ValueNameID)
        for value in stat.AxisValueArray.AxisValue
        if value.AxisIndex == 1
    ] == optical_labels
    assert variable_font["name"].getDebugName(text_instance.subfamilyNameID) == "Regular Text"
    assert text_instance.subfamilyNameID != text_name_id
