"""Chunked semantic carriers keep IUP compression only when it is lossless."""

from __future__ import annotations

import copy

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables.TupleVariation import TupleVariation

from variable_gen.build import (
    _exact_authored_carriers,
    _optimize_unmarked_variations,
    _preserved_authored_variations,
)

LOSSY = "curve.stv-semantic64x.c0"
EXACT = "curve.stv-semantic64x.c1"
PLAIN_LOSSY = "plain"
BOTTOM = range(0, 1300, 100)
POINTS = [(x, 0) for x in BOTTOM] + [(1200, 100), (0, 100)]
# x-deltas along the bottom edge. Rounding x / 120 stays within the ordinary 0.5
# tolerance of the straight line from 0 to 10, but not on it; 3x / 100 is on it.
LOSSY_DELTAS = [(round(x / 120), 0) for x in BOTTOM] + [(10, 0), (0, 0)]
EXACT_DELTAS = [(3 * x // 100, 0) for x in BOTTOM] + [(36, 0), (0, 0)]


def _font() -> TTFont:
    names = [".notdef", "curve", LOSSY, EXACT, PLAIN_LOSSY]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(names)
    glyphs = {".notdef": TTGlyphPen(None).glyph()}
    for name in names[1:]:
        pen = TTGlyphPen(None)
        pen.moveTo(POINTS[0])
        for point in POINTS[1:]:
            pen.lineTo(point)
        pen.closePath()
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name: (400, 0) for name in names})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Carrier", "styleName": "Regular"})
    builder.setupFvar([("wght", 100, 400, 900, "Weight")], [])
    font = builder.font
    font["gvar"] = newTable("gvar")
    phantoms = [(0, 0)] * 4
    font["gvar"].variations = {
        ".notdef": [],
        "curve": [TupleVariation({"wght": (0, 1, 1)}, EXACT_DELTAS + phantoms)],
        LOSSY: [TupleVariation({"wght": (0, 1, 1)}, LOSSY_DELTAS + phantoms)],
        EXACT: [TupleVariation({"wght": (0, 1, 1)}, EXACT_DELTAS + phantoms)],
        PLAIN_LOSSY: [TupleVariation({"wght": (0, 1, 1)}, LOSSY_DELTAS + phantoms)],
    }
    return font


def _tuples(font: TTFont, name: str) -> list:
    return [(v.axes, list(v.coordinates)) for v in font["gvar"].variations[name]]


def test_chunked_carrier_names_are_recognized_for_authored_owners_only() -> None:
    font = _font()
    font.setGlyphOrder(
        [
            *font.getGlyphOrder(),
            "curve.stv-semantic16x",
            "curve.stv-semantic64x",
            "curve.stv-semantic64x.alt",
            "other.stv-semantic64x.c0",
        ]
    )
    authored = frozenset({"curve"})
    preserved = _preserved_authored_variations(font, authored)

    assert preserved == frozenset({"curve", "curve.stv-semantic16x"})
    assert _exact_authored_carriers(font, authored, preserved) == frozenset(
        {LOSSY, EXACT, "curve.stv-semantic64x"}
    )


def test_lossy_iup_on_a_chunked_carrier_keeps_the_tuple_explicit() -> None:
    font = _font()
    before = _tuples(font, LOSSY)
    preserved = frozenset({"curve"})

    _optimize_unmarked_variations(
        font, preserved, _exact_authored_carriers(font, preserved, preserved)
    )

    # The ordinary glyph with identical deltas is compressed with a 1/3-unit error,
    # which the chunked carrier must not inherit.
    assert None in font["gvar"].variations[PLAIN_LOSSY][0].coordinates
    assert _tuples(font, LOSSY) == before


def test_exact_chunked_carrier_compression_is_byte_identical_to_ordinary() -> None:
    guarded = _font()
    ordinary = copy.deepcopy(guarded)
    preserved = frozenset({"curve"})

    _optimize_unmarked_variations(
        guarded, preserved, _exact_authored_carriers(guarded, preserved, preserved)
    )
    _optimize_unmarked_variations(ordinary, preserved)

    assert None in guarded["gvar"].variations[EXACT][0].coordinates
    assert _tuples(guarded, EXACT) == _tuples(ordinary, EXACT)
    assert _tuples(guarded, PLAIN_LOSSY) == _tuples(ordinary, PLAIN_LOSSY)
    assert guarded["gvar"].compile(guarded) != ordinary["gvar"].compile(ordinary)
    guarded["gvar"].variations[LOSSY] = ordinary["gvar"].variations[LOSSY]
    assert guarded["gvar"].compile(guarded) == ordinary["gvar"].compile(ordinary)
