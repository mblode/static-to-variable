"""Compiled Display stays native when extra Text spans subdivide the curve."""

from __future__ import annotations

from pathlib import Path

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.recordingPen import DecomposingRecordingPen, RecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

import variable_gen.quadratic_reference as quadratic_reference
from variable_gen.quadratic_reference import (
    _recording,
    _same_filled_path,
    preserve_quadratic_reference,
)
from test_quadratic_reference import _compile_variable, _reference_font, _source_set


def test_piecewise_prefix_keeps_compiled_display_native_without_stationary_lobes(
    tmp_path: Path,
) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = _source_set()
    groups = (((1, 1, 1, 1),), ((1, 1, 1, 1),), ((1, 1, 1, 1),))
    for font, contours in zip(fonts, groups, strict=True):
        font["curve"].lib[quadratic_reference.SOURCE_GROUPS_KEY] = contours

    report = preserve_quadratic_reference(
        fonts,
        default_index=1,
        reference_path=reference_path,
        reference_location={},
        protected_locations={1: {}, 2: {}},
        max_error=0.25,
    )

    helper = report.carrier_glyphs[0] if report.carrier_glyphs else "curve"
    outline = fonts[1][helper]
    recording = _recording(outline)
    assert ("qCurveTo", ((0.0, 0.0), (0.0, 0.0))) not in recording.value
    assert ("qCurveTo", ((0, 0), (0, 0))) not in recording.value
    reference = TTFont(reference_path).getGlyphSet()["curve"]
    for index in (1, 2):
        drawn = DecomposingRecordingPen(fonts[index])
        fonts[index]["curve"].draw(drawn)
        assert _same_filled_path(drawn, _recording(reference))
    variable = _compile_variable(fonts, optimize_gvar=False)
    areas = []
    for optical_size in (12, 16, 20, 24, 28):
        instance = instantiateVariableFont(variable, {"opsz": optical_size}, inplace=False)
        glyphs = instance.getGlyphSet()
        drawn = DecomposingRecordingPen(glyphs)
        glyphs["curve"].draw(drawn)
        if optical_size in (16, 28):
            assert _same_filled_path(drawn, _recording(reference))
        areas.append(quadratic_reference._filled_path(drawn).area)
    text_area, mid_area, display_area = areas[0], areas[2], areas[-1]
    low, high = sorted((text_area, display_area))
    assert low <= mid_area <= high or abs(mid_area - high) / max(high, 1) < 0.05


def _closed(start, operations):
    recording = RecordingPen()
    recording.moveTo(start)
    for kind, points in operations:
        getattr(recording, kind)(*points)
    recording.closePath()
    return recording


def _native_operation(native: int) -> tuple[str, tuple[tuple[float, float], ...]]:
    controls = tuple((200 * (index + 0.5) / native, 110.0) for index in range(native))
    return ("qCurveTo", (*controls, (200.0, 0.0)))


@pytest.mark.parametrize("native", (1, 2, 3, 4))
@pytest.mark.parametrize("extra", range(10))
def test_prefix_subdivision_allocates_the_text_point_structure(native: int, extra: int) -> None:
    """Regression: d75faf4 gave Display spans extra controls when native did not divide extra."""
    start = (0.0, 0.0)
    reference = _native_operation(native)
    protected = quadratic_reference._pad_reference_operation(start, reference, extra)
    # Text carries ``extra`` one-control spans, then the native control count.
    assert [len(points) for _, points in protected] == [2] * extra + [native + 1]
    assert _same_filled_path(_closed(start, [reference]), _closed(start, protected))
    stationary = ("qCurveTo", (start, start))
    if 0 < extra < native:
        # No exact subdivision fits; keep the pre-subdivision stationary pads.
        assert protected == [stationary] * extra + [reference]
    else:
        assert stationary not in protected


def test_odd_prefix_on_two_control_display_span_matches_text_signature() -> None:
    curve = ((0, 0), (20, 110), (180, 110), (200, 0))
    prefix, masters = quadratic_reference._fit_piecewise_group([[curve]], 2, 1, "curve")
    assert prefix % 2 == 1
    reference = ("qCurveTo", ((10, 80), (190, 80), (200, 0)))
    protected = quadratic_reference._pad_reference_operation((0, 0), reference, prefix)
    assert [len(points) for _, points in protected] == [len(points) for _, points in masters[0]]
    assert ("qCurveTo", ((0, 0), (0, 0))) not in protected


def _two_control_reference_font(path: Path) -> None:
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef", "curve", "unmarked"])
    empty = TTGlyphPen(None)
    curve = TTGlyphPen(None)
    curve.moveTo((0, 0))
    curve.lineTo((200, 0))
    curve.qCurveTo((180, 110), (20, 110), (0, 0))
    curve.closePath()
    unmarked = TTGlyphPen(None)
    unmarked.moveTo((150, 0))
    unmarked.lineTo((250, 0))
    unmarked.qCurveTo((200, 120), (150, 0))
    unmarked.closePath()
    builder.setupGlyf(
        {".notdef": empty.glyph(), "curve": curve.glyph(), "unmarked": unmarked.glyph()}
    )
    builder.setupHorizontalMetrics({".notdef": (500, 0), "curve": (500, 0), "unmarked": (500, 150)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupCharacterMap({0x61: "curve", 0x62: "unmarked"})
    builder.setupNameTable({"familyName": "Two Control Fixture", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupPost()
    builder.setupMaxp()
    builder.save(path)


def test_odd_prefix_on_two_control_display_span_compiles_compatible_masters(
    tmp_path: Path,
) -> None:
    """Regression: Glide Roman pi/odieresis and Italic r*.ss03 failed fontmake compatibility."""
    reference_path = tmp_path / "reference.ttf"
    _two_control_reference_font(reference_path)
    fonts = _source_set()
    for font in fonts:
        glyph = font["curve"]
        glyph.clearContours()
        pen = glyph.getPen()
        pen.moveTo((0, 0))
        pen.curveTo((20, 110), (180, 110), (200, 0))
        pen.closePath()
        glyph.lib[quadratic_reference.SOURCE_GROUPS_KEY] = ((1, 1, 1, 1),)

    report = preserve_quadratic_reference(
        fonts,
        default_index=1,
        reference_path=reference_path,
        reference_location={},
        protected_locations={1: {}, 2: {}},
        max_error=1,
    )

    assert report.expanded_operations % 2 == 1
    signatures = {
        tuple(len(points) for _, points in _recording(font["curve"]).value) for font in fonts
    }
    assert len(signatures) == 1
    reference = TTFont(reference_path).getGlyphSet()["curve"]
    for index in (1, 2):
        drawn = DecomposingRecordingPen(fonts[index])
        fonts[index]["curve"].draw(drawn)
        assert _same_filled_path(drawn, _recording(reference))
    variable = _compile_variable(fonts, optimize_gvar=False)
    for optical_size in (16, 28):
        instance = instantiateVariableFont(variable, {"opsz": optical_size}, inplace=False)
        glyphs = instance.getGlyphSet()
        drawn = DecomposingRecordingPen(glyphs)
        glyphs["curve"].draw(drawn)
        assert _same_filled_path(drawn, _recording(reference))
