from __future__ import annotations

from pathlib import Path

import pytest
import ufo2ft
import ufoLib2
from fontTools.cu2qu.ufo import fonts_to_quadratic
from fontTools.designspaceLib import AxisDescriptor, DesignSpaceDocument, SourceDescriptor
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

from variable_gen.authorship import OPTICAL_AUTHORSHIP_KEY
from variable_gen.common import PipelineError
from variable_gen.quadratic_reference import (
    _fixed_quadratic_spline,
    _recording,
    _same_filled_path,
    preserve_quadratic_reference,
)

PROVENANCE = "manual:" + "a" * 64


def _reference_font(path: Path, *, units_per_em: int = 1000) -> None:
    builder = FontBuilder(units_per_em, isTTF=True)
    builder.setupGlyphOrder([".notdef", "curve", "unmarked"])
    empty = TTGlyphPen(None)
    curve = TTGlyphPen(None)
    curve.moveTo((0, 0))
    curve.lineTo((100, 0))
    curve.qCurveTo((50, 150), (0, 0))
    curve.closePath()
    unmarked = TTGlyphPen(None)
    unmarked.moveTo((150, 0))
    unmarked.lineTo((250, 0))
    unmarked.qCurveTo((200, 120), (150, 0))
    unmarked.closePath()
    builder.setupGlyf(
        {
            ".notdef": empty.glyph(),
            "curve": curve.glyph(),
            "unmarked": unmarked.glyph(),
        }
    )
    builder.setupHorizontalMetrics({".notdef": (500, 0), "curve": (500, 0), "unmarked": (500, 150)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupCharacterMap({0x61: "curve", 0x62: "unmarked"})
    builder.setupNameTable(
        {
            "familyName": "Quadratic Reference Fixture",
            "styleName": "Regular",
            "uniqueFontIdentifier": "QuadraticReferenceFixture-Regular",
            "fullName": "Quadratic Reference Fixture Regular",
            "psName": "QuadraticReferenceFixture-Regular",
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


def _source_font(
    *, height: float, width: float, marked: bool, units_per_em: int = 1000
) -> ufoLib2.Font:
    font = ufoLib2.Font()
    font.info.familyName = "Quadratic Reference Fixture"
    font.info.styleName = f"Height {height:g}"
    font.info.unitsPerEm = units_per_em
    font.info.ascender = 800
    font.info.descender = -200
    font.newGlyph(".notdef").width = 500

    curve = font.newGlyph("curve")
    pen = curve.getPen()
    pen.moveTo((0, 0))
    pen.curveTo((0, height), (100, height), (100, 0))
    pen.closePath()
    curve.width = width
    if marked:
        curve.lib[OPTICAL_AUTHORSHIP_KEY] = PROVENANCE

    unmarked = font.newGlyph("unmarked")
    pen = unmarked.getPen()
    pen.moveTo((150, 0))
    pen.curveTo((150, 180), (250, 180), (250, 0))
    pen.closePath()
    unmarked.width = 500
    return font


def _source_set() -> list[ufoLib2.Font]:
    return [
        _source_font(height=220, width=520, marked=True),
        _source_font(height=200, width=500, marked=False),
        _source_font(height=200, width=500, marked=False),
    ]


def _signature(glyph) -> tuple[tuple[str, int], ...]:
    recording = _recording(glyph)
    return tuple((operation, len(points)) for operation, points in recording.value)


def _compile_variable(fonts: list[ufoLib2.Font]) -> TTFont:
    document = DesignSpaceDocument()
    axis = AxisDescriptor()
    axis.name = "Optical size"
    axis.tag = "opsz"
    axis.minimum = 12
    axis.default = 16
    axis.maximum = 28
    document.addAxis(axis)
    for index, (font, optical_size) in enumerate(zip(fonts, (12, 16, 28), strict=True)):
        source = SourceDescriptor()
        source.name = f"master-{index}"
        source.familyName = font.info.familyName
        source.styleName = font.info.styleName
        source.location = {axis.name: optical_size}
        source.font = font
        document.addSource(source)
    return ufo2ft.compileVariableTTF(document, useProductionNames=False)


def _cubic_point(curve: tuple[complex, complex, complex, complex], t: float) -> complex:
    p0, p1, p2, p3 = curve
    u = 1 - t
    return u**3 * p0 + 3 * u**2 * t * p1 + 3 * u * t**2 * p2 + t**3 * p3


def _quadratic_point(start: complex, control: complex, end: complex, t: float) -> complex:
    u = 1 - t
    return u**2 * start + 2 * u * t * control + t**2 * end


def test_reference_geometry_survives_compatible_closed_variable_build(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = _source_set()

    report = preserve_quadratic_reference(
        fonts,
        default_index=1,
        reference_path=reference_path,
        reference_location={},
        max_error=1,
    )

    assert report.glyphs == 1
    assert report.converted_glyphs == 1
    assert report.exact_default_glyphs == 0
    assert report.expanded_operations == 3
    assert report.maximum_segments == 4
    signatures = {_signature(font["curve"]) for font in fonts}
    assert signatures == {
        (
            ("moveTo", 1),
            ("lineTo", 1),
            ("qCurveTo", 2),
            ("qCurveTo", 2),
            ("qCurveTo", 2),
            ("qCurveTo", 2),
            ("closePath", 0),
        )
    }

    reference = TTFont(reference_path).getGlyphSet()["curve"]
    assert _same_filled_path(_recording(fonts[1]["curve"]), _recording(reference))
    assert _same_filled_path(_recording(fonts[2]["curve"]), _recording(reference))
    assert fonts[1]["curve"].width == fonts[2]["curve"].width == 500
    assert fonts[0]["curve"].width == 520

    variable = _compile_variable(fonts)
    ui = instantiateVariableFont(variable, {"opsz": 16}, inplace=False)
    display = instantiateVariableFont(variable, {"opsz": 28}, inplace=False)
    text = instantiateVariableFont(variable, {"opsz": 12}, inplace=False)
    assert _same_filled_path(_recording(ui.getGlyphSet()["curve"]), _recording(reference))
    assert _same_filled_path(_recording(display.getGlyphSet()["curve"]), _recording(reference))
    assert ui["hmtx"].metrics["curve"][0] == 500
    assert display["hmtx"].metrics["curve"][0] == 500
    assert text["hmtx"].metrics["curve"][0] == 520


def test_authored_cubic_fit_stays_within_one_unit() -> None:
    points = ((0, 0), (0, 220), (100, 220), (100, 0))
    spline = _fixed_quadratic_spline(points, 4, 1)

    assert spline is not None
    cubic = tuple(complex(*point) for point in points)
    controls = [complex(*point) for point in spline[1:-1]]
    endpoints = [complex(*spline[0])]
    endpoints.extend(
        (left + right) / 2 for left, right in zip(controls, controls[1:], strict=False)
    )
    endpoints.append(complex(*spline[-1]))
    maximum_error = max(
        abs(
            _quadratic_point(endpoints[index], control, endpoints[index + 1], step / 1000)
            - _cubic_point(cubic, (index + step / 1000) / len(controls))
        )
        for index, control in enumerate(controls)
        for step in range(1001)
    )

    assert 0 < maximum_error <= 1


def test_topology_contract_binds_every_authored_master_before_cu2qu(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = [
        _source_font(height=220, width=520, marked=True),
        _source_font(height=200, width=500, marked=True),
        _source_font(height=180, width=480, marked=True),
    ]
    contract = {
        "curve": ((("moveTo", 1), ("curveTo", 3), ("closePath", 0)),),
    }

    report = preserve_quadratic_reference(
        fonts,
        default_index=1,
        reference_path=reference_path,
        reference_location={},
        max_error=1,
        topology_contract=contract,
        topology_contract_master_names=("text", "ui", "display"),
        source_master_names=("text", "ui", "display"),
    )

    assert report.glyphs == 1


def test_topology_contract_fails_closed_for_unmarked_or_drifted_master(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = [
        _source_font(height=220, width=520, marked=True),
        _source_font(height=200, width=500, marked=False),
        _source_font(height=180, width=480, marked=True),
    ]
    contract = {
        "curve": ((("moveTo", 1), ("curveTo", 3), ("closePath", 0)),),
    }

    with pytest.raises(PipelineError, match="requires authored provenance in master 1"):
        preserve_quadratic_reference(
            fonts,
            default_index=1,
            reference_path=reference_path,
            reference_location={},
            topology_contract=contract,
            topology_contract_master_names=("text", "ui", "display"),
            source_master_names=("text", "ui", "display"),
        )

    fonts[1] = _source_font(height=200, width=500, marked=True)
    pen = fonts[1]["curve"].getPen()
    fonts[1]["curve"].clearContours()
    pen.moveTo((0, 0))
    pen.lineTo((100, 0))
    pen.closePath()
    with pytest.raises(PipelineError, match="topology contract mismatch in master 1"):
        preserve_quadratic_reference(
            fonts,
            default_index=1,
            reference_path=reference_path,
            reference_location={},
            topology_contract=contract,
            topology_contract_master_names=("text", "ui", "display"),
            source_master_names=("text", "ui", "display"),
        )


def test_topology_contract_rejects_a_partial_or_reordered_master_set(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = [_source_font(height=220, width=520, marked=True)]
    with pytest.raises(PipelineError, match="master inputs differ"):
        preserve_quadratic_reference(
            fonts,
            default_index=0,
            reference_path=reference_path,
            reference_location={},
            topology_contract={
                "curve": ((("moveTo", 1), ("curveTo", 3), ("closePath", 0)),),
            },
            topology_contract_master_names=("text", "ui", "display"),
            source_master_names=("text",),
        )


def test_reference_reconciliation_is_provenance_scoped_and_deterministic(
    tmp_path: Path,
) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    first = _source_set()
    second = _source_set()
    normal = _source_set()
    fonts_to_quadratic(
        normal,
        max_err=1,
        reverse_direction=True,
        remember_curve_type=False,
    )

    first_report = preserve_quadratic_reference(
        first,
        default_index=1,
        reference_path=reference_path,
        reference_location={},
        max_error=1,
    )
    second_report = preserve_quadratic_reference(
        second,
        default_index=1,
        reference_path=reference_path,
        reference_location={},
        max_error=1,
    )

    assert first_report == second_report
    for first_font, second_font, normal_font in zip(first, second, normal, strict=True):
        assert _recording(first_font["curve"]).value == _recording(second_font["curve"]).value
        assert _recording(first_font["unmarked"]).value == _recording(normal_font["unmarked"]).value


def test_reference_validation_fails_before_mutating_sources(tmp_path: Path) -> None:
    reference_path = tmp_path / "wrong-upem.ttf"
    _reference_font(reference_path, units_per_em=2048)
    fonts = _source_set()
    before = [_recording(font["curve"]).value for font in fonts]

    with pytest.raises(PipelineError, match="unitsPerEm must match every source"):
        preserve_quadratic_reference(
            fonts,
            default_index=1,
            reference_path=reference_path,
            reference_location={},
            max_error=1,
        )

    assert [_recording(font["curve"]).value for font in fonts] == before


def test_open_authored_contour_fails_before_quadratic_conversion(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = _source_set()
    glyph = fonts[0]["curve"]
    glyph.clearContours()
    pen = glyph.getPen()
    pen.moveTo((0, 0))
    pen.curveTo((0, 220), (100, 220), (100, 0))
    pen.endPath()
    before = [_recording(font["curve"]).value for font in fonts]

    with pytest.raises(PipelineError, match="requires closed contours"):
        preserve_quadratic_reference(
            fonts,
            default_index=1,
            reference_path=reference_path,
            reference_location={},
            max_error=1,
        )

    assert [_recording(font["curve"]).value for font in fonts] == before
