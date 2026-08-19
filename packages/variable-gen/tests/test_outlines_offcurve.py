from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PACKAGE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from glyphsLib.classes import GSFont, GSFontMaster, GSGlyph, GSLayer  # noqa: E402

from variable_gen.outlines import GRID, donor_outline, draw_into, signature  # noqa: E402


class _AllOffCurveGlyph:
    """A glyph whose only contour is fully off-curve, as TrueType stores perfect
    circles (e.g. Roboto's ``registered`` glyph). fontTools draws it as a lone
    ``qCurveTo`` with no leading ``moveTo`` and a trailing ``None`` implied point.
    """

    width = 500

    def draw(self, pen) -> None:
        pen.qCurveTo((0, 0), (100, 0), (100, 100), (0, 100), None)
        pen.closePath()


class _ImplicitClosingLineGlyph:
    width = 500

    def draw(self, pen) -> None:
        pen.moveTo((0, 0))
        pen.lineTo((100, 0))
        pen.curveTo((100, 50), (50, 100), (0, 12))
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


def test_donor_outline_materializes_an_implicit_closing_line() -> None:
    contours, _ = donor_outline({"shape": _ImplicitClosingLineGlyph()}, "shape")

    assert contours[0][-2] == ("lineTo", [(0, 0)])


def _layer() -> GSLayer:
    font = GSFont()
    master = GSFontMaster()
    master.id = "m1"
    font.masters.append(master)
    glyph = GSGlyph("shape")
    font.glyphs.append(glyph)
    layer = GSLayer()
    layer.layerId = "m1"
    glyph.layers.append(layer)
    return layer


_FRACTIONAL = [
    [
        ("moveTo", ((0.4, 0.6),)),
        ("curveTo", ((10.2, 20.7), (30.9, 40.1), (50.5, 60.4))),
        ("lineTo", ((70.49, 80.51),)),
        ("closePath", ()),
    ]
]


def test_draw_into_grid_snaps_every_point_and_keeps_structure() -> None:
    """Snapping moves coordinates onto the grid without changing structure.

    Point counts and node types must survive, because interpolation
    compatibility is a property of the structure rather than of the coordinates.
    Rounding is per-point so this holds by construction; the test pins it so a
    later rewrite cannot quietly break it.
    """
    snapped, plain = _layer(), _layer()
    draw_into(snapped, _FRACTIONAL, grid=GRID)
    draw_into(plain, _FRACTIONAL)

    points = [node for path in snapped.paths for node in path.nodes]
    assert points, "snapped layer drew nothing"
    for node in points:
        assert float(node.position.x) == int(node.position.x), node
        assert float(node.position.y) == int(node.position.y), node

    assert len(snapped.paths) == len(plain.paths)
    assert [len(p.nodes) for p in snapped.paths] == [len(p.nodes) for p in plain.paths]
    assert [[str(n.type) for n in p.nodes] for p in snapped.paths] == [
        [str(n.type) for n in p.nodes] for p in plain.paths
    ]

    for a, b in zip(points, [n for p in plain.paths for n in p.nodes], strict=True):
        assert abs(float(a.position.x) - float(b.position.x)) <= 0.5
        assert abs(float(a.position.y) - float(b.position.y)) <= 0.5


def test_draw_into_without_grid_preserves_exact_coordinates() -> None:
    """Snapping is opt-in: the default must not move anything."""
    layer = _layer()
    draw_into(layer, _FRACTIONAL)
    xs = [float(n.position.x) for p in layer.paths for n in p.nodes]
    assert any(abs(x - 0.4) < 1e-9 for x in xs)
    assert any(abs(x - 70.49) < 1e-9 for x in xs)
