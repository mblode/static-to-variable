from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PACKAGE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from glyphsLib.classes import GSFont, GSFontMaster, GSGlyph, GSLayer  # noqa: E402

from variable_gen.outlines import donor_outline, draw_into, signature  # noqa: E402


class _AllOffCurveGlyph:
    """A glyph whose only contour is fully off-curve, as TrueType stores perfect
    circles (e.g. Roboto's ``registered`` glyph). fontTools draws it as a lone
    ``qCurveTo`` with no leading ``moveTo`` and a trailing ``None`` implied point.
    """

    width = 500

    def draw(self, pen) -> None:
        pen.qCurveTo((0, 0), (100, 0), (100, 100), (0, 100), None)
        pen.closePath()


def test_donor_outline_handles_all_offcurve_truetype_contour() -> None:
    # Regression: this used to crash in donor_outline with
    # "'NoneType' object has no attribute 'append'" because the contour opened
    # on a qCurveTo instead of a moveTo, breaking bootstrap on real fonts.
    glyphset = {"registered": _AllOffCurveGlyph()}

    result = donor_outline(glyphset, "registered")

    assert result is not None
    contours, width = result
    assert width == 500
    assert len(contours) == 1
    ops = [op for op, _ in contours[0]]
    assert ops[0] == "qCurveTo"
    assert ops[-1] == "closePath"


def test_offcurve_contour_survives_signature_and_draw_into() -> None:
    # signature() must not choke on the implied (None) endpoint, and draw_into
    # must render the captured contour back into a glyphsLib layer.
    glyphset = {"registered": _AllOffCurveGlyph()}
    contours, _ = donor_outline(glyphset, "registered")

    signature(contours)  # must not raise on the None implied point

    font = GSFont()
    master = GSFontMaster()
    master.id = "m1"
    font.masters.append(master)
    glyph = GSGlyph("registered")
    font.glyphs.append(glyph)
    layer = GSLayer()
    layer.layerId = "m1"
    glyph.layers.append(layer)

    draw_into(layer, contours)

    assert len(layer.paths) == 1
