from __future__ import annotations

from variable_gen.build import _area


class _Glyph:
    def __init__(self, rectangles):
        self.rectangles = rectangles

    def draw(self, pen):
        for left, bottom, right, top in self.rectangles:
            pen.moveTo((left, bottom))
            pen.lineTo((right, bottom))
            pen.lineTo((right, top))
            pen.lineTo((left, top))
            pen.closePath()


class _CompositeGlyph:
    def draw(self, pen):
        pen.addComponent("base", (1, 0, 0, 1, 50, 0))


def test_fidelity_area_uses_rendered_union_for_overlapping_contours():
    glyph_set = {"overlap": _Glyph([(0, 0, 100, 100), (50, 0, 150, 100)])}

    assert _area(glyph_set, "overlap") == 15_000


def test_fidelity_area_decomposes_components():
    glyph_set = {
        "base": _Glyph([(0, 0, 100, 100)]),
        "composite": _CompositeGlyph(),
    }

    assert _area(glyph_set, "composite") == 10_000


def test_fidelity_area_returns_none_for_missing_glyph():
    assert _area({}, "missing") is None
