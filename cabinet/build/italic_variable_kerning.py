#!/usr/bin/env python3

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from fontTools.otlLib.builder import buildLookup, buildPairPosGlyphsSubtable, buildValue
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

from transfer_circular_kerning import DONOR_ITALIC_FILES, subset_donor_for_target


FOCUS_GLYPHS = {"a"}


def iter_pairpos_subtables(font: TTFont):
    if "GPOS" not in font or not getattr(font["GPOS"].table, "LookupList", None):
        return

    for lookup in font["GPOS"].table.LookupList.Lookup:
        lookup_type = lookup.LookupType
        if lookup_type == 2:
            for subtable in lookup.SubTable:
                yield subtable
        elif lookup_type == 9:
            for subtable in lookup.SubTable:
                if getattr(subtable, "ExtensionLookupType", None) != 2:
                    continue
                yield subtable.ExtSubTable


def extract_pair_adjustments(font: TTFont, allowed_glyphs: set[str] | None = None) -> dict[tuple[str, str], int]:
    allowed = set(font.getGlyphOrder()) if allowed_glyphs is None else set(allowed_glyphs)
    glyph_order = [glyph_name for glyph_name in font.getGlyphOrder() if glyph_name in allowed]
    pairs: dict[tuple[str, str], int] = {}

    for subtable in iter_pairpos_subtables(font) or ():
        format_type = getattr(subtable, "Format", None)
        if format_type == 1:
            coverage = getattr(subtable.Coverage, "glyphs", []) or []
            for left, pair_set in zip(coverage, subtable.PairSet):
                if left not in allowed:
                    continue
                for record in pair_set.PairValueRecord:
                    right = record.SecondGlyph
                    if right not in allowed:
                        continue
                    value_1 = getattr(record, "Value1", None)
                    x_advance = (getattr(value_1, "XAdvance", 0) or 0) if value_1 is not None else 0
                    x_placement = (getattr(value_1, "XPlacement", 0) or 0) if value_1 is not None else 0
                    value = x_advance + x_placement
                    if value != 0:
                        pairs[(left, right)] = value
        elif format_type == 2:
            coverage = getattr(subtable.Coverage, "glyphs", []) or []
            class_def_1 = getattr(getattr(subtable, "ClassDef1", None), "classDefs", {}) or {}
            class_def_2 = getattr(getattr(subtable, "ClassDef2", None), "classDefs", {}) or {}
            lefts = [glyph_name for glyph_name in glyph_order if glyph_name in coverage]
            for left in lefts:
                class_1 = class_def_1.get(left, 0)
                if class_1 >= len(subtable.Class1Record):
                    continue
                row = subtable.Class1Record[class_1]
                for right in glyph_order:
                    class_2 = class_def_2.get(right, 0)
                    if class_2 >= len(row.Class2Record):
                        continue
                    record = row.Class2Record[class_2]
                    value_1 = getattr(record, "Value1", None)
                    x_advance = (getattr(value_1, "XAdvance", 0) or 0) if value_1 is not None else 0
                    x_placement = (getattr(value_1, "XPlacement", 0) or 0) if value_1 is not None else 0
                    value = x_advance + x_placement
                    if value != 0:
                        pairs[(left, right)] = value

    return pairs


def pair_value(font: TTFont, left: str, right: str) -> int | None:
    return extract_pair_adjustments(font, allowed_glyphs={left, right}).get((left, right))


def advance_width(font: TTFont, glyph_name: str) -> int:
    return font["hmtx"].metrics[glyph_name][0]


def x_bounds(font: TTFont, glyph_name: str) -> tuple[int, int]:
    pen = BoundsPen(font.getGlyphSet())
    font.getGlyphSet()[glyph_name].draw(pen)
    bounds = pen.bounds
    if bounds is None:
        return 0, 0
    x_min, _, x_max, _ = bounds
    return int(x_min), int(x_max)


def outline_gap(font: TTFont, left: str, right: str, kern: int = 0) -> int:
    right_x_min, _ = x_bounds(font, right)
    _, left_x_max = x_bounds(font, left)
    return advance_width(font, left) + kern + right_x_min - left_x_max


def build_focus_pair_adjustments(
    target_font: TTFont,
    donor_subset: TTFont,
    donor_pair_map: dict[tuple[str, str], int],
    focus_glyphs: set[str],
) -> dict[tuple[str, str], int]:
    common_glyphs = set(target_font.getGlyphOrder()) & set(donor_subset.getGlyphOrder())
    adjustments: dict[tuple[str, str], int] = {}
    for focus in sorted(focus_glyphs & common_glyphs):
        for glyph_name in sorted(common_glyphs):
            left, right = focus, glyph_name
            donor_kern = donor_pair_map.get((left, right), 0)
            desired_gap = outline_gap(donor_subset, left, right, donor_kern)
            base_gap = outline_gap(target_font, left, right, 0)
            adjusted_kern = desired_gap - base_gap
            if adjusted_kern == donor_kern:
                continue
            adjustments[(left, right)] = adjusted_kern
    return adjustments


def build_canonical_pair_lookup(font: TTFont, pair_values: dict[tuple[str, str], int]) -> object:
    glyph_map = {glyph_name: gid for gid, glyph_name in enumerate(font.getGlyphOrder())}
    canonical_pairs = {
        pair: (buildValue({"XAdvance": int(value)}), None)
        for pair, value in sorted(pair_values.items())
        if pair[0] in glyph_map and pair[1] in glyph_map
    }
    subtable = buildPairPosGlyphsSubtable(canonical_pairs, glyph_map)
    return buildLookup([subtable], table="GPOS")


def apply_lookup_to_donor_subset(target_font: TTFont, donor_subset: TTFont, lookup: object) -> None:
    donor_gpos = deepcopy(donor_subset["GPOS"])
    for index, existing_lookup in enumerate(donor_gpos.table.LookupList.Lookup):
        if existing_lookup.LookupType in (2, 9):
            donor_gpos.table.LookupList.Lookup[index] = lookup
            break
    else:
        donor_gpos.table.LookupList.Lookup.append(lookup)
        donor_gpos.table.LookupList.LookupCount = len(donor_gpos.table.LookupList.Lookup)
    target_font["GPOS"] = donor_gpos


def build_variable_italic_gpos_sources(
    source_paths: list[Path],
    donor_dir: Path,
    build_dir: Path,
    master_weights: list[int],
    force: bool,
) -> tuple[list[Path], dict[int, int]]:
    build_dir.mkdir(parents=True, exist_ok=True)
    source_fonts = [TTFont(path, recalcBBoxes=False, recalcTimestamp=False) for path in source_paths]
    common_glyphs = set(source_fonts[0].getGlyphOrder())
    for font in source_fonts[1:]:
        common_glyphs &= set(font.getGlyphOrder())

    pair_maps: dict[int, dict[tuple[str, str], int]] = {}
    pair_counts: dict[int, int] = {}
    union_pairs: set[tuple[str, str]] = set()

    for weight, source_font in zip(master_weights, source_fonts):
        donor_filename = DONOR_ITALIC_FILES[weight]
        donor_font = TTFont(donor_dir / donor_filename, recalcBBoxes=False, recalcTimestamp=False)
        donor_subset = subset_donor_for_target(donor_font, source_font)
        pair_map = extract_pair_adjustments(donor_subset, allowed_glyphs=common_glyphs)
        pair_map.update(
            build_focus_pair_adjustments(
                target_font=source_font,
                donor_subset=donor_subset,
                donor_pair_map=pair_map,
                focus_glyphs=FOCUS_GLYPHS,
            )
        )
        pair_maps[weight] = pair_map
        pair_counts[weight] = len(pair_map)
        union_pairs |= set(pair_map)

    build_paths: list[Path] = []
    for source_path, weight in zip(source_paths, master_weights):
        build_path = build_dir / f"italic-variable-kern-{source_path.name}"
        build_paths.append(build_path)
        if build_path.exists() and not force:
            continue

        target_font = TTFont(source_path, recalcBBoxes=False, recalcTimestamp=False)
        donor_font = TTFont(donor_dir / DONOR_ITALIC_FILES[weight], recalcBBoxes=False, recalcTimestamp=False)
        donor_subset = subset_donor_for_target(donor_font, target_font)
        canonical_map = {
            pair: pair_maps[weight].get(pair, 0)
            for pair in union_pairs
            if pair[0] in common_glyphs and pair[1] in common_glyphs
        }
        lookup = build_canonical_pair_lookup(target_font, canonical_map)
        apply_lookup_to_donor_subset(target_font, donor_subset, lookup)
        if "kern" in target_font:
            del target_font["kern"]
        target_font.save(build_path)

    return build_paths, pair_counts
