"""Compiled Display stays native when extra Text spans subdivide the curve."""

from __future__ import annotations

from pathlib import Path

from fontTools.pens.recordingPen import DecomposingRecordingPen
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
