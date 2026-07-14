#!/usr/bin/env python3
"""Audit the Circular donor OTFs for cross-weight inconsistencies.

Glide reproduces the donors faithfully, so donor defects (a glyph that gets
LIGHTER as weight increases, a glyph that barely changes weight, or a glyph
whose height jumps around across weights) show up in the variable font. This
flags those so the donor files in cabinet/Circular can be checked/replaced.

Run: .venv/bin/python packages/variable-gen/scripts/audit_donors.py
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

from fontTools.pens.areaPen import AreaPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

REPO_ROOT = Path(__file__).resolve().parents[3]
FAMILIES = {
    "roman": ("cabinet/Circular/Circular", [
        ("Thin", "Circular-Thin"), ("Light", "Circular-Light"),
        ("Regular", "Circular-Regular"), ("Book", "Circular-Book"),
        ("Medium", "Circular-Medium"), ("Bold", "Circular-Bold"),
        ("Black", "Circular-Black"), ("ExtraBlack", "Circular-ExtraBlack"),
    ]),
    "italic": ("cabinet/Circular/Circular Italic", [
        ("Thin", "Circular-ThinItalic"), ("Light", "Circular-LightItalic"),
        ("Regular", "Circular-RegularItalic"), ("Book", "Circular-BookItalic"),
        ("Medium", "Circular-MediumItalic"), ("Bold", "Circular-BoldItalic"),
        ("Black", "Circular-BlackItalic"), ("ExtraBlack", "Circular-ExtraBlackItalic"),
    ]),
}

# weight order is light -> heavy; ink area should rise monotonically and roughly
# double Thin -> ExtraBlack, and a glyph's height should stay fairly stable.
NEAR_FLAT = 1.4          # Black/Thin area ratio below this = barely gains weight
HEIGHT_SWING = 0.18      # height range / median above this = inconsistent height
MONO_SLACK = 0.0         # any drop at a heavier weight = non-monotonic


def measure(glyphset, name):
    if name not in glyphset:
        return None
    ap, bp = AreaPen(glyphset), BoundsPen(glyphset)
    try:
        glyphset[name].draw(ap)
        glyphset[name].draw(bp)
    except Exception:  # noqa: BLE001
        return None
    if bp.bounds is None:
        return abs(ap.value), 0.0
    return abs(ap.value), bp.bounds[3] - bp.bounds[1]


def _stable_height_glyph(cmap_rev, name):
    """Letters/figures should keep a stable height; marks/dots/shapes scale, so
    skip them in the height check (bbox height = stroke thickness for those)."""
    cp = cmap_rev.get(name)
    if cp is None:
        return False
    return (0x30 <= cp <= 0x39) or (0x41 <= cp <= 0x5A) or (0x61 <= cp <= 0x7A) \
        or (0xC0 <= cp <= 0x24F)  # ASCII letters/digits + Latin-1/Extended letters


def audit_family(family):
    donor_dir, weights = FAMILIES[family]
    fonts = [(w, TTFont(str(REPO_ROOT / donor_dir / f"{stem}.otf"))) for w, stem in weights]
    glyphsets = [(w, f.getGlyphSet()) for w, f in fonts]
    common = set.intersection(*[set(f.getGlyphOrder()) for _, f in fonts])
    cmap = fonts[0][1].getBestCmap()
    cmap_rev = {v: k for k, v in cmap.items()}

    non_mono, near_flat, height_bad = [], [], []
    for g in sorted(common):
        if g == ".notdef":
            continue
        rows = [(w, measure(gs, g)) for w, gs in glyphsets]
        if any(m is None for _, m in rows):
            continue
        areas = [m[0] for _, m in rows]
        heights = [m[1] for _, m in rows]
        if max(areas) < 1000:
            continue
        # non-monotonic ink: a heavier weight has less ink than a lighter one
        drops = [(rows[i][0], rows[i + 1][0]) for i in range(len(areas) - 1)
                 if areas[i + 1] < areas[i] - MONO_SLACK]
        if drops:
            non_mono.append((g, [f"{a}>{b}" for a, b in drops]))
        # near-flat weight
        if areas[0] and areas[-1] / areas[0] < NEAR_FLAT:
            near_flat.append((g, round(areas[-1] / areas[0], 2)))
        # inconsistent height — only for letters/figures (height should be stable)
        if heights and statistics.median(heights) > 0 and _stable_height_glyph(cmap_rev, g):
            swing = (max(heights) - min(heights)) / statistics.median(heights)
            if swing > HEIGHT_SWING:
                worst_w = rows[heights.index(min(heights))][0]
                height_bad.append((g, round(swing, 2), worst_w))

    print(f"\n=== {family} ({len(common)} glyphs) ===")
    print(f"NON-MONOTONIC ink (gets lighter at a heavier weight) — {len(non_mono)}:")
    for g, d in non_mono[:40]:
        print(f"   {g}: drops {d}")
    print(f"NEAR-FLAT weight (Black/Thin ink < {NEAR_FLAT}x) — {len(near_flat)}:")
    for g, r in sorted(near_flat, key=lambda x: x[1])[:40]:
        print(f"   {g}: {r}x")
    print(f"INCONSISTENT height (swing > {int(HEIGHT_SWING*100)}% of median) — {len(height_bad)}:")
    for g, s, w in sorted(height_bad, key=lambda x: -x[1])[:40]:
        print(f"   {g}: {int(s*100)}% swing (shortest at {w})")


def main():
    for fam in (sys.argv[1:] or ["roman", "italic"]):
        audit_family(fam)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
