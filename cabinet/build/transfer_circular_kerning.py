#!/usr/bin/env python3

from __future__ import annotations

from copy import deepcopy

from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont


DONOR_ITALIC_FILES = {
    100: "Circular-ThinItalic.otf",
    250: "Circular-ThinItalic.otf",
    300: "Circular-LightItalic.otf",
    400: "Circular-BookItalic.otf",
    450: "Circular-BookItalic.otf",
    500: "Circular-MediumItalic.otf",
    700: "Circular-BoldItalic.otf",
    900: "Circular-BlackItalic.otf",
    950: "Circular-ExtraBlackItalic.otf",
}


def subset_donor_for_target(donor_font: TTFont, target_font: TTFont) -> TTFont:
    """Return a donor font subset to glyphs shared with the target font."""
    target_glyphs = set(target_font.getGlyphOrder())
    glyphs = [
        glyph_name
        for glyph_name in donor_font.getGlyphOrder()
        if glyph_name in target_glyphs
    ]

    subset_font = deepcopy(donor_font)
    options = Options()
    options.layout_closure = False
    options.name_IDs = ["*"]
    options.name_legacy = True
    options.name_languages = ["*"]
    subsetter = Subsetter(options=options)
    subsetter.populate(glyphs=glyphs)
    subsetter.subset(subset_font)
    return subset_font
