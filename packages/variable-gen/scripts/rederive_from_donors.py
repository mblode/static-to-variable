#!/usr/bin/env python3
"""Re-derive Glide master outlines directly from the Circular donors.

The importer (populate_circular_glyphs.py) runs path-mapping + rotation + node
normalization to make masters interpolation-compatible. But every Circular donor
is ALREADY point-compatible across Thin/Book/ExtraBlack, so that normalization is
unnecessary — and it compresses the weight range (Thin too heavy, ExtraBlack too
light) for ~half the glyphs, leaving them underweight at the heavy end.

This generalizes the proven per-glyph ffi reconstruction: for every glyph whose
donor outlines share op-sequence + winding across the three master donors, it
copies the donor outline directly into each master (donor-faithful), giving the
full, correct weight range with clean outlines.

  master  <- donor (per FONT_PLANS.donor_paths_by_master_name)
  Thin    <- Circular-Thin            Regular <- Circular-Book
  ExtraBlack <- Circular-ExtraBlack   (italic analogous)

Glyphs that are not in the donors (composites that follow their bases) or whose
donor outlines are not consistent across weights are SKIPPED and reported, so the
build stays interpolation-compatible.

Usage:
  .venv/bin/python packages/variable-gen/scripts/rederive_from_donors.py --font all [--dry-run]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import glyphsLib
from fontTools.designspaceLib import DesignSpaceDocument
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont
from fontTools.varLib.interpolatable import test as interpolatable_test
from ufoLib2 import Font as UFO

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from populate_circular_glyphs import FONT_PLANS  # noqa: E402

REPO_ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(REPO_ROOT / "cabinet"))
from export_designspace import export as export_designspace  # noqa: E402

SOURCES = {
    "roman": REPO_ROOT / "glide-variable.glyphs",
    "italic": REPO_ROOT / "glide-variable-italic.glyphs",
}
EXPORT_ARGS = {
    "roman": ("Glide.designspace", "Glide"),
    "italic": ("GlideItalic.designspace", "GlideItalic"),
}


def donor_outline(glyphset, name):
    """Return (contours, width) or None if the glyph can't be drawn.

    contours: list of contours, each a list of (op, [pt,...]) preserving the
    cubic segment structure straight from the donor CFF outline.
    """
    if name not in glyphset:
        return None
    pen = DecomposingRecordingPen(glyphset)
    try:
        glyphset[name].draw(pen)
    except Exception:  # noqa: BLE001
        return None
    contours, cur = [], None
    for op, args in pen.value:
        if op == "moveTo":
            cur = [("moveTo", [tuple(args[0])])]
        elif op == "lineTo":
            cur.append(("lineTo", [tuple(args[0])]))
        elif op == "curveTo":
            cur.append(("curveTo", [tuple(p) for p in args]))
        elif op == "qCurveTo":
            cur.append(("qCurveTo", [tuple(p) for p in args]))
        elif op in ("closePath", "endPath"):
            cur.append((op, []))
            contours.append(cur)
            cur = None
    return contours, glyphset[name].width


def _winding(points):
    if len(points) < 3:
        return 0
    s = sum(
        points[i][0] * points[(i + 1) % len(points)][1]
        - points[(i + 1) % len(points)][0] * points[i][1]
        for i in range(len(points))
    )
    return 1 if s > 0 else (-1 if s < 0 else 0)


def signature(contours):
    """(op-sequence, winding) per contour — a cheap pre-filter for direct copy.

    A few glyphs pass this yet still interpolate incompatibly (a contour starts
    at a different node across weights, e.g. dollar). Those are caught after the
    fact by the interpolatable pass in revert_incompatible() and reverted to
    their importer masters, rather than guessed at here.
    """
    sig = []
    for con in contours:
        ops = tuple(op for op, _ in con if op in ("moveTo", "lineTo", "curveTo", "qCurveTo"))
        pts = [p[-1] for op, p in con if p]
        sig.append((ops, _winding(pts)))
    return tuple(sig)


def draw_into(layer, contours):
    layer.paths = []
    layer.components = []
    pen = layer.getPen()
    for con in contours:
        for op, pts in con:
            if op == "moveTo":
                pen.moveTo(pts[0])
            elif op == "lineTo":
                pen.lineTo(pts[0])
            elif op == "curveTo":
                pen.curveTo(*pts)
            elif op == "qCurveTo":
                pen.qCurveTo(*pts)
            elif op == "closePath":
                pen.closePath()
            elif op == "endPath":
                pen.endPath()


def rederive_family(family: str, dry_run: bool) -> dict:
    plan = FONT_PLANS[family]
    src_path = SOURCES[family]
    # master name -> donor glyphset
    donor_glyphsets = {}
    for master_name, donor_path in plan.donor_paths_by_master_name.items():
        donor_glyphsets[master_name] = TTFont(str(donor_path)).getGlyphSet()

    # Back up the original (importer) source so revert_incompatible() can put
    # back the few glyphs whose donor outlines don't interpolate cleanly.
    backup_path = Path(str(src_path) + ".rederive-orig")
    if not dry_run:
        shutil.copy(src_path, backup_path)

    font = glyphsLib.load(open(src_path))
    master_name_by_id = {m.id: m.name for m in font.masters}
    target_masters = set(plan.donor_paths_by_master_name)

    rederived, skipped_missing, skipped_incompat = [], [], []
    for glyph in font.glyphs:
        name = glyph.name
        # gather donor outlines for each master
        outlines = {}
        present = True
        for mname, gs in donor_glyphsets.items():
            o = donor_outline(gs, name)
            if o is None:
                present = False
                break
            outlines[mname] = o
        if not present:
            skipped_missing.append(name)
            continue
        # all three must share op-sequence + winding
        sigs = {m: signature(o[0]) for m, o in outlines.items()}
        if len(set(sigs.values())) != 1:
            skipped_incompat.append(name)
            continue
        if not dry_run:
            # Drop any brace/intermediate/backup layers: they created {250}/{675}
            # intermediate masters that pinned non-brace glyphs to Regular and
            # compressed the whole weight range. The donor-faithful masters
            # interpolate correctly on their own.
            glyph.layers = [
                layer for layer in glyph.layers if layer.layerId in master_name_by_id
            ]
            for layer in glyph.layers:
                mname = master_name_by_id.get(layer.layerId)
                if mname in target_masters:
                    contours, width = outlines[mname]
                    draw_into(layer, contours)
                    layer.width = width
        rederived.append(name)

    if not dry_run:
        font.save(str(src_path))
    return {
        "family": family,
        "rederived": len(rederived),
        "skipped_missing": skipped_missing,
        "skipped_incompat": skipped_incompat,
    }


def revert_incompatible(family: str) -> list[str]:
    """Export, find glyphs that still don't interpolate, and put those back.

    A handful of re-derived glyphs (e.g. dollar) start a contour at a different
    node across donor weights and so fail master compatibility. Revert exactly
    those to their original importer masters — which are compatible (if slightly
    compressed) — so the build succeeds. Reproducible: uses the .rederive-orig
    backup, no external snapshot.
    """
    src_path = SOURCES[family]
    backup_path = Path(str(src_path) + ".rederive-orig")
    ds_name, ufo_prefix = EXPORT_ARGS[family]
    ds_path = export_designspace(src_path, ds_name, ufo_prefix)
    ds = DesignSpaceDocument.fromfile(str(ds_path))
    issues = interpolatable_test(
        [UFO.open(s.path) for s in ds.sources], names=[s.name for s in ds.sources]
    )
    # Only revert glyphs with issues that actually break the variable build.
    # kink / underweight are soft warnings fontmake tolerates; reverting on those
    # would needlessly restore compressed importer masters.
    hard = {
        "node_count", "contour_order", "wrong_start_point", "path_count",
        "node_incompatibility", "open_path", "contour_count", "missing",
    }
    incompatible = {
        name for name, glyph_issues in issues.items()
        if any(i.get("type") in hard for i in glyph_issues)
    }
    if not incompatible or not backup_path.exists():
        return sorted(incompatible)

    current = glyphsLib.load(open(src_path))
    original = {g.name: g for g in glyphsLib.load(open(backup_path)).glyphs}
    for glyph in current.glyphs:
        if glyph.name in incompatible and glyph.name in original:
            glyph.layers = original[glyph.name].layers
    current.save(str(src_path))
    return sorted(incompatible)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--font", choices=["roman", "italic", "all"], default="all")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    families = ["roman", "italic"] if args.font == "all" else [args.font]
    for fam in families:
        r = rederive_family(fam, args.dry_run)
        print(f"[{fam}] re-derived {r['rederived']} glyphs from donors"
              f"{' (dry-run)' if args.dry_run else ''}")
        print(f"  skipped (not in donors, follow bases): {len(r['skipped_missing'])}")
        print(f"  skipped (donor incompatible across weights): "
              f"{len(r['skipped_incompat'])} {r['skipped_incompat'][:10]}")
        if not args.dry_run:
            reverted = revert_incompatible(fam)
            print(f"  reverted to importer masters (interpolation-incompatible): "
                  f"{len(reverted)} {reverted[:10]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
