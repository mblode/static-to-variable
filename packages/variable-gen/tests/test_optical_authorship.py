from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import glyphsLib
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from glyphsLib.classes import GSAxis, GSFont, GSFontMaster, GSGlyph, GSLayer

from variable_gen.authorship import (
    OPTICAL_AUTHORSHIP_KEY,
    AuthoredSource,
    inspect_authored_source,
)
from variable_gen.build import (
    CollapseFinding,
    _freeze_candidates,
    check_authored_fidelity,
    freeze_to_book,
)
from variable_gen.common import PipelineError
from variable_gen.config import ProjectConfig, load_config
from variable_gen.outlines import draw_into

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "two-axis-project.json"
PROVENANCE = "manual:" + "a" * 64


def _static_font(path: Path, *, right: int = 100, width: int = 500) -> None:
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef", "e"])
    empty = TTGlyphPen(None)
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((right, 0))
    pen.lineTo((right, 100))
    pen.lineTo((0, 100))
    pen.closePath()
    builder.setupGlyf({".notdef": empty.glyph(), "e": pen.glyph()})
    builder.setupHorizontalMetrics({".notdef": (500, 0), "e": (width, 0)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupCharacterMap({0x65: "e"})
    builder.setupNameTable(
        {
            "familyName": "Authored Fixture",
            "styleName": "Regular",
            "uniqueFontIdentifier": "AuthoredFixture-Regular",
            "fullName": "Authored Fixture Regular",
            "psName": "AuthoredFixture-Regular",
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
    builder.save(path)


def _project(tmp_path: Path, marked_masters: set[str], marker: str = PROVENANCE) -> ProjectConfig:
    config = load_config(FIXTURE)
    source = tmp_path / "authored.glyphs"
    style = replace(config.styles["roman"], source=source)
    config = replace(config, styles={"roman": style})

    font = GSFont()
    font.familyName = "Authored Fixture"
    font.axes = [GSAxis(name=axis.name, tag=axis.tag) for axis in config.axes]
    ids: dict[str, str] = {}
    for item in style.masters:
        master = GSFontMaster()
        master.name = item.name
        master.id = f"fixture-{item.name.replace(' ', '-').lower()}"
        master.axes = [item.location[axis.tag] for axis in config.axes]
        font.masters.append(master)
        ids[item.name] = master.id

    glyph = GSGlyph("e")
    for item in style.masters:
        layer = GSLayer()
        layer.layerId = layer.associatedMasterId = ids[item.name]
        draw_into(
            layer,
            [
                [
                    ("moveTo", [(0, 0)]),
                    ("lineTo", [(100, 0)]),
                    ("lineTo", [(100, 100)]),
                    ("lineTo", [(0, 100)]),
                    ("closePath", []),
                ]
            ],
        )
        layer.width = 500
        if item.name in marked_masters:
            layer.userData[OPTICAL_AUTHORSHIP_KEY] = marker
        glyph.layers.append(layer)
    font.glyphs.append(glyph)
    font.save(str(source))
    return config


def test_authorship_marker_round_trips_deterministically(tmp_path: Path) -> None:
    text_masters = {"Text Thin", "Text Regular", "Text ExtraBlack"}
    config = _project(tmp_path, text_masters)

    first = inspect_authored_source(config, "roman")
    loaded = glyphsLib.load(str(config.styles["roman"].source))
    second_path = tmp_path / "roundtrip.glyphs"
    loaded.save(str(second_path))
    third_path = tmp_path / "roundtrip-again.glyphs"
    glyphsLib.load(str(second_path)).save(str(third_path))
    roundtrip_config = replace(
        config,
        styles={"roman": replace(config.styles["roman"], source=second_path)},
    )
    second = inspect_authored_source(roundtrip_config, "roman")

    assert first == second
    assert first.glyphs == {"e"}
    assert first.rows["e"] == {(("opsz", 12.0),)}
    assert set(first.layers["e"].values()) == {PROVENANCE}
    assert second_path.read_bytes() == third_path.read_bytes()


def test_incomplete_authored_row_names_missing_endpoint_drawings(tmp_path: Path) -> None:
    config = _project(tmp_path, {"Text Regular"})

    with pytest.raises(PipelineError) as caught:
        inspect_authored_source(config, "roman")

    message = str(caught.value)
    assert "e: incomplete authored row opsz=12" in message
    assert "wght=100, opsz=12 (Text Thin)" in message
    assert "wght=950, opsz=12 (Text ExtraBlack)" in message


def test_weight_pruned_optical_lab_does_not_require_other_optical_sizes(
    tmp_path: Path,
) -> None:
    config = _project(tmp_path, {"Text Regular"})
    style = config.styles["roman"]
    regulars = tuple(
        replace(master, location={"opsz": master.location["opsz"]})
        for master in style.masters
        if master.location["wght"] == 400
    )
    config = replace(
        config,
        axes=(config.axes[1],),
        styles={"roman": replace(style, masters=regulars)},
    )

    authored = inspect_authored_source(config, "roman")

    assert authored.glyphs == {"e"}
    assert set(authored.layers["e"]) == {(("opsz", 12.0),)}


def test_authorship_marker_must_be_content_addressed(tmp_path: Path) -> None:
    config = _project(tmp_path, {"Text Thin", "Text Regular", "Text ExtraBlack"}, "manual")

    with pytest.raises(PipelineError, match=r"e at wght=100, opsz=12: invalid"):
        inspect_authored_source(config, "roman")


def test_safe_complete_authored_row_is_not_a_freeze_candidate(tmp_path: Path) -> None:
    config = _project(tmp_path, {"Text Thin", "Text Regular", "Text ExtraBlack"})
    authored = inspect_authored_source(config, "roman")

    assert _freeze_candidates("roman", authored, [], []) == []


def test_compiled_authored_masters_match_source_geometry(tmp_path: Path) -> None:
    config = _project(tmp_path, {"Text Thin", "Text Regular", "Text ExtraBlack"})
    output = tmp_path / "output.ttf"
    _static_font(output)
    config = replace(
        config,
        styles={"roman": replace(config.styles["roman"], output=output)},
    )

    assert check_authored_fidelity(config, "roman") == []


def test_compiled_authored_master_fidelity_reports_area_and_advance(tmp_path: Path) -> None:
    config = _project(tmp_path, {"Text Thin", "Text Regular", "Text ExtraBlack"})
    output = tmp_path / "output.ttf"
    _static_font(output, right=80, width=520)
    config = replace(
        config,
        styles={"roman": replace(config.styles["roman"], output=output)},
    )

    failures = check_authored_fidelity(config, "roman")

    assert len(failures) == 6
    assert any("Text" not in failure and "area ratio 0.800" in failure for failure in failures)
    assert any("advance 520 != source 500" in failure for failure in failures)


def test_authored_collapse_fails_named_instead_of_freezing(tmp_path: Path) -> None:
    config = _project(tmp_path, {"Text Thin", "Text Regular", "Text ExtraBlack"})
    authored = inspect_authored_source(config, "roman")
    finding = CollapseFinding(
        glyph="e",
        location=(("opsz", 12.0), ("wght", 250.0)),
        left=100,
        right=400,
        midpoint_area=700,
        endpoint_mean_area=1000,
    )

    with pytest.raises(PipelineError) as caught:
        _freeze_candidates("roman", authored, [finding], [])

    message = str(caught.value)
    assert "authored glyph interpolation is unsafe" in message
    assert "e at opsz=12, wght=250 between 100 and 400" in message


def test_generated_collapse_keeps_existing_freeze_behavior() -> None:
    finding = CollapseFinding(
        glyph="generated",
        location=(("opsz", 12.0), ("wght", 250.0)),
        left=100,
        right=400,
        midpoint_area=700,
        endpoint_mean_area=1000,
    )

    assert _freeze_candidates("roman", AuthoredSource({}, {}), [finding], []) == ["generated"]
    assert _freeze_candidates("roman", AuthoredSource({}, {}), [finding], ["generated"]) == []


def test_direct_freeze_refuses_to_mutate_authored_glyph(tmp_path: Path) -> None:
    config = _project(tmp_path, {"Text Thin", "Text Regular", "Text ExtraBlack"})
    source = config.styles["roman"].source
    before = source.read_bytes()

    with pytest.raises(PipelineError, match="authored glyphs cannot be donor-frozen: e"):
        freeze_to_book(config, "roman", ["e"])

    assert source.read_bytes() == before
