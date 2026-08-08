"""Compare a built variable font's layout against the donor it came from.

Everything about this pipeline's layout handling degrades quietly by design —
lookups referencing absent glyphs get pruned, a merge that will not compile
falls back a tier, a donor with no kerning simply has none to carry over. That
is the right behaviour at build time and the wrong behaviour to ship blind, so
each build records what actually survived. :mod:`variable_gen.pipeline` turns
this into a blocking promotion gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont

from variable_gen.hinting import HintingReport
from variable_gen.kerning import KerningTooLarge, flatten_kern, has_kern
from variable_gen.layout import LayoutReport


def _feature_tags(font: TTFont, tag: str) -> list[str]:
    if tag not in font:
        return []
    table = getattr(font[tag], "table", None)
    if table is None or table.FeatureList is None:
        return []
    return sorted({record.FeatureTag for record in table.FeatureList.FeatureRecord})


def _kern_pair_count(path: Path) -> int | None:
    """Flattened kern pairs, or ``None`` when the font is too big to flatten.

    ``None`` rather than a guess: the gate compares donor against output, and a
    number it cannot trust is worse than no number — it reads it as 0 and skips
    the comparison.
    """
    try:
        return len(flatten_kern(TTFont(str(path))))
    except KerningTooLarge:
        return None


def _var_store(font: TTFont) -> bool:
    if "GDEF" not in font:
        return False
    return getattr(getattr(font["GDEF"], "table", None), "VarStore", None) is not None


def build_layout_report(
    output_path: Path,
    donor_paths: list[Path],
    *,
    default_donor: Path,
    layout: LayoutReport,
    hinting: HintingReport,
) -> dict[str, Any]:
    """Everything the promotion gate needs to judge one style's layout."""
    varfont = TTFont(str(output_path), lazy=True)
    donor = TTFont(str(default_donor), lazy=True)

    donor_gsub = _feature_tags(donor, "GSUB")
    donor_gpos = _feature_tags(donor, "GPOS")
    output_gsub = _feature_tags(varfont, "GSUB")
    output_gpos = _feature_tags(varfont, "GPOS")

    donor_pairs = _kern_pair_count(default_donor)
    output_pairs = _kern_pair_count(output_path)

    donors_with_kern = sum(
        1 for path in donor_paths if path.is_file() and has_kern(TTFont(str(path), lazy=True))
    )

    return {
        "features": {
            "donor_gsub": donor_gsub,
            "donor_gpos": donor_gpos,
            "output_gsub": output_gsub,
            "output_gpos": output_gpos,
            "missing_gsub": sorted(set(donor_gsub) - set(output_gsub)),
            "missing_gpos": sorted(set(donor_gpos) - set(output_gpos)),
        },
        "gdef": {
            "donor": "GDEF" in donor,
            "output": "GDEF" in varfont,
            "var_store": _var_store(varfont),
        },
        "glyphs": {
            "donor": len(donor.getGlyphOrder()),
            "output": len(varfont.getGlyphOrder()),
        },
        "hinting": {
            "gasp": hinting.gasp,
            "mode": hinting.mode,
            "prep": hinting.prep,
        },
        "kern": {
            "donor_pairs": donor_pairs,
            "donors_with_kern": donors_with_kern,
            "output_pairs": output_pairs,
            "values": layout.kern.values if layout.kern else 0,
            "varying": layout.kern.varying if layout.kern else 0,
        },
        "layout": {
            "mode": layout.mode,
            "note": layout.note,
            "tables": list(layout.tables),
        },
    }
