#!/usr/bin/env python3
"""
fix_source_files.py — Fix interpolation incompatibilities in Glide source .glyphs files.
Updates glide-variable-italic.glyphs and glide-variable.glyphs in place.

Fixes applied:
  Pass 1 — Glyphs in GLYPHS_TO_FIX: normalize even when cubic counts already match
            (e.g. italic G where 59/61/61/61 → 69 nodes × 4 masters)
  Pass 2 — ALL glyphs: align contour start points and unify op types across masters.
            This fixes the ~200 glyphs that fontTools varLib.interpolatable flags for
            start-point misalignment and lineTo/curveTo inconsistency.

Usage:
    cd cabinet && ../.venv/bin/python fix_source_files.py [--dry-run]
"""

import sys
import argparse
from pathlib import Path

import glyphsLib
from fontTools.pens.recordingPen import RecordingPen, replayRecording
from fontTools.pens.pointPen import PointToSegmentPen, SegmentToPointPen
from glyphsLib.pens import LayerPointPen

from import_circular import (
    normalize_master_ops,
    cubic_node_counts,
    verify_cubic_compat,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

SOURCE_FILES = {
    "italic": REPO_ROOT / "glide-variable-italic.glyphs",
    "roman":  REPO_ROOT / "glide-variable.glyphs",
}

# Glyphs with known node-count mismatches that require forced normalization.
# These are processed in Pass 1 with force=True so they run even when
# verify_cubic_compat passes (it only checks counts, not start points).
GLYPHS_TO_FIX = {
    "italic": ["G"],
    "roman":  [],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_ops_to_layer(ops: list, layer) -> None:
    """
    Write cubic segment ops to a Glyphs layer, preserving the intended start node.

    SegmentToPointPen treats a path that ends at its own moveTo as an "explicit
    close", so the moveTo point ends up as node[-1] instead of node[0].
    After writing we rotate each path's node list so the moveTo point is first.
    """
    # Step 1: write via standard pipeline
    layer.shapes = []
    layer_pen = LayerPointPen(layer)
    replayRecording(ops, SegmentToPointPen(layer_pen))

    # Step 2: figure out intended start for each path from ops
    intended_starts = []
    for op, args in ops:
        if op == "moveTo":
            intended_starts.append(args[0])

    # Step 3: for each path, rotate so the intended start is node[0]
    for i, path in enumerate(layer.paths):
        if i >= len(intended_starts):
            break
        target = intended_starts[i]
        vals = path.nodes.values()   # mutable underlying list
        n = len(vals)
        if n == 0:
            continue
        # Find index of node closest to target
        def dist_sq(nd):
            return (nd.position.x - target[0])**2 + (nd.position.y - target[1])**2
        best = min(range(n), key=lambda j: dist_sq(vals[j]))
        if best != 0:
            vals[:] = vals[best:] + vals[:best]


def layer_to_ops(layer) -> list:
    """Extract fontTools segment ops from a Glyphs layer via PointToSegmentPen."""
    rec = RecordingPen()
    adapter = PointToSegmentPen(rec)
    for path in layer.paths:
        adapter.beginPath()
        for node in path.nodes:
            seg_type = node.type if node.type != "offcurve" else None
            adapter.addPoint(
                (node.position.x, node.position.y),
                segmentType=seg_type,
                smooth=node.smooth,
            )
        adapter.endPath()
    return rec.value


def master_layers_for_glyph(font, glyph_name):
    """Return {master_id: layer} for all masters of glyph_name."""
    glyph = font.glyphs[glyph_name]
    if glyph is None:
        return {}
    master_ids = {m.id for m in font.masters}
    result = {}
    for layer in glyph.layers:
        if layer.associatedMasterId in master_ids and layer.layerId == layer.associatedMasterId:
            result[layer.associatedMasterId] = layer
    return result


def node_counts_summary(master_ops: dict) -> str:
    counts = {mid: sum(cubic_node_counts(ops)) for mid, ops in master_ops.items()}
    vals = list(counts.values())
    if len(set(vals)) == 1:
        return f"✓ {vals[0]} nodes × {len(vals)} masters"
    return "✗ " + "/".join(str(v) for v in vals) + " nodes (MISMATCH)"


# ---------------------------------------------------------------------------
# Pass 1 — fix a single named glyph (used for node-count mismatches)
# ---------------------------------------------------------------------------

def fix_glyph(font, glyph_name: str, dry_run: bool, force: bool = False) -> bool:
    """
    Normalize glyph_name across all masters.
    force=True: run normalization even when cubic counts already match.
    Returns True if compatible after fix, False on failure.
    """
    layers = master_layers_for_glyph(font, glyph_name)
    if not layers:
        print(f"  {glyph_name}: not found, skipped")
        return True

    # Extract raw ops
    master_raw = {mid: layer_to_ops(layer) for mid, layer in layers.items()}

    print(f"  {glyph_name}: before → {node_counts_summary(master_raw)}")

    # Already compatible AND not forced? Skip.
    if not force and verify_cubic_compat(master_raw):
        print(f"  {glyph_name}: already compatible, no change needed")
        return True

    # Normalize
    master_norm = normalize_master_ops(master_raw)
    if master_norm is None:
        print(f"  {glyph_name}: ✗ normalize_master_ops returned None — cannot fix")
        return False

    print(f"  {glyph_name}: after  → {node_counts_summary(master_norm)}")

    ok = verify_cubic_compat(master_norm)
    if not ok:
        print(f"  {glyph_name}: ✗ still incompatible after normalization")
        return False

    if dry_run:
        print(f"  {glyph_name}: (dry-run) would write normalized paths to {len(layers)} layers")
        return True

    # Write back
    for mid, layer in layers.items():
        write_ops_to_layer(master_norm[mid], layer)

    print(f"  {glyph_name}: ✓ written to {len(layers)} layers")
    return True


# ---------------------------------------------------------------------------
# Pass 2 — normalize ALL glyphs for start-point and op-type consistency
# ---------------------------------------------------------------------------

def fix_all_glyphs(font, dry_run: bool) -> tuple:
    """
    Normalize every glyph in the font:
      - Aligns contour start points across all masters to the reference (first) master.
      - Unifies lineTo/curveTo op types so cubic node counts are equal.

    Only writes back when normalize_master_ops actually changes the ops.

    Returns (changed_count, failed_count, failed_names)
    where failed_names are glyphs where normalize_master_ops returned None
    (fundamental contour-topology mismatch — needs manual Glyphs.app fix).
    """
    changed = 0
    failed = 0
    failed_names = []

    for glyph in font.glyphs:
        layers = master_layers_for_glyph(font, glyph.name)
        if len(layers) < 2:
            continue

        master_raw = {mid: layer_to_ops(layer) for mid, layer in layers.items()}

        # Skip empty glyphs (spaces, .notdef with no outlines, etc.)
        if not any(master_raw.values()):
            continue
        if all(ops == [] for ops in master_raw.values()):
            continue

        master_norm = normalize_master_ops(master_raw)

        if master_norm is None:
            # Contour count differs between masters — cannot auto-normalize.
            # (These are typically already caught by GLYPHS_TO_FIX or are unfixable.)
            failed += 1
            failed_names.append(glyph.name)
            continue

        # Only write back if something actually changed.
        if master_norm == master_raw:
            continue

        changed += 1

        if dry_run:
            # Report the glyph name (verbose output suppressed by default in pass 2)
            pass
        else:
            for mid, layer in layers.items():
                write_ops_to_layer(master_norm[mid], layer)

    return changed, failed, failed_names


# ---------------------------------------------------------------------------
# Full compatibility audit (report only, no changes)
# ---------------------------------------------------------------------------

def audit_font(font, label: str):
    mismatches = []
    for glyph in font.glyphs:
        layers = master_layers_for_glyph(font, glyph.name)
        if len(layers) < 2:
            continue
        master_ops = {mid: layer_to_ops(layer) for mid, layer in layers.items()}
        if not verify_cubic_compat(master_ops):
            counts = {mid: sum(cubic_node_counts(ops)) for mid, ops in master_ops.items()}
            mismatches.append((glyph.name, counts))

    if mismatches:
        print(f"\n  {label} audit — {len(mismatches)} mismatch(es):")
        for name, counts in mismatches:
            vals = "/".join(str(v) for v in counts.values())
            print(f"    {name}: {vals}")
    else:
        print(f"\n  {label} audit — ✓ 0 cubic-count mismatches")

    return len(mismatches)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fix interpolation incompatibilities in Glide .glyphs files")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without saving")
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN — no files will be modified ===\n")

    total_failures = 0

    for key, path in SOURCE_FILES.items():
        print(f"\n{'='*60}")
        print(f"File: {path.name}  ({key})")
        print(f"{'='*60}")

        font = glyphsLib.load(str(path))

        # --- Pass 1: fix known node-count mismatches ---
        glyphs_to_fix = GLYPHS_TO_FIX.get(key, [])
        if glyphs_to_fix:
            print("\nPass 1 — named fixes (node-count normalization):")
            for glyph_name in glyphs_to_fix:
                ok = fix_glyph(font, glyph_name, dry_run=args.dry_run, force=True)
                if not ok:
                    total_failures += 1
        else:
            print("\nPass 1 — no named fixes for this file")

        # --- Pass 2: normalize all glyphs for start-points + op types ---
        print("\nPass 2 — full start-point & op-type normalization (all glyphs):")
        changed, failed, failed_names = fix_all_glyphs(font, dry_run=args.dry_run)
        if args.dry_run:
            print(f"  Would normalize: {changed} glyphs")
        else:
            print(f"  Normalized: {changed} glyphs")
        if failed_names:
            print(f"  ✗ {failed} glyph(s) with contour-topology mismatch (need manual fix):")
            for name in failed_names:
                print(f"    • {name}")
            total_failures += failed

        # --- Audit ---
        audit_font(font, path.name)

        if not args.dry_run:
            font.save(str(path))
            print(f"\n  Saved → {path}")

    print(f"\n{'='*60}")
    if total_failures == 0:
        print("Done. All fixes applied successfully.")
    else:
        print(f"Done with {total_failures} failure(s) — review output above.")
    print(f"{'='*60}")

    return 1 if total_failures else 0


if __name__ == "__main__":
    sys.exit(main())
