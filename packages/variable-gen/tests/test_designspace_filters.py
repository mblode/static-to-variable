from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PACKAGE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import ufoLib2  # noqa: E402

from variable_gen.designspace import (  # noqa: E402
    UFO2FT_FILTERS_KEY,
    drop_open_corner_filter,
)

ERASE_OPEN_CORNERS = {
    "name": "eraseOpenCorners",
    "namespace": "glyphsLib.filters",
    "pre": True,
}


def _ufo(filters) -> ufoLib2.Font:
    font = ufoLib2.Font()
    if filters is not None:
        font.lib[UFO2FT_FILTERS_KEY] = filters
    return font


def test_drops_the_filter_glyphslib_injects() -> None:
    # Regression: glyphsLib writes eraseOpenCorners into every UFO it emits, and
    # ufo2ft runs it per master. On outlines reconstructed from static TTFs it
    # misreads acute diagonal junctions as open corners and erases a different
    # number of points in each weight, so A/M/N/W/X/Y/Z/w/x/y stopped
    # interpolating and got frozen to a single weight in the built font.
    font = _ufo([ERASE_OPEN_CORNERS])

    assert drop_open_corner_filter(font) is True
    assert UFO2FT_FILTERS_KEY not in font.lib


def test_keeps_other_filters() -> None:
    other = {"name": "propagateAnchors", "namespace": "glyphsLib.filters", "pre": True}
    font = _ufo([ERASE_OPEN_CORNERS, other])

    assert drop_open_corner_filter(font) is True
    assert font.lib[UFO2FT_FILTERS_KEY] == [other]


def test_no_op_when_the_filter_is_absent() -> None:
    other = {"name": "propagateAnchors", "namespace": "glyphsLib.filters", "pre": True}
    font = _ufo([other])

    assert drop_open_corner_filter(font) is False
    assert font.lib[UFO2FT_FILTERS_KEY] == [other]


def test_no_op_when_there_is_no_filter_key() -> None:
    font = _ufo(None)

    assert drop_open_corner_filter(font) is False
    assert UFO2FT_FILTERS_KEY not in font.lib
