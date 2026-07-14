#!/usr/bin/env python3
"""
Normalize only the glyphs that still trigger export-time structure warnings.

This script targets the two warning types that are still safe to automate:
  - wrong_start_point
  - node_incompatibility

It exports the current .glyphs source to UFO/designspace, runs
fontTools.varLib.interpolatable, collects the affected glyphs, then applies the
existing per-glyph topology normalizer only to that set.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import glyphsLib
from fontTools.designspaceLib import DesignSpaceDocument
from fontTools.varLib import interpolatable

from export_designspace import export
from fix_source_files import fix_glyph, master_layers_for_glyph

REPO_ROOT = Path(__file__).resolve().parent.parent

SOURCE_FILES = {
    "roman": REPO_ROOT / "glide-variable.glyphs",
    "italic": REPO_ROOT / "glide-variable-italic.glyphs",
}

TARGET_WARNING_TYPES = {"wrong_start_point", "node_incompatibility"}


def designspace_for(label: str) -> tuple[Path, str, str]:
    if label == "italic":
        return SOURCE_FILES[label], "GlideItalic.designspace", "GlideItalic"
    return SOURCE_FILES[label], "Glide.designspace", "Glide"


def collect_target_glyphs(ds_path: Path) -> tuple[list[str], Counter]:
    designspace = DesignSpaceDocument.fromfile(str(ds_path))
    source_paths: list[str] = []
    for source in designspace.sources:
        if source.path:
            source_paths.append(str(Path(source.path).resolve()))
        elif source.filename:
            source_paths.append(str((ds_path.parent / source.filename).resolve()))

    problems = interpolatable.main([*source_paths, "--quiet"])
    counts: Counter = Counter()
    targets = set()

    for glyph_name, issues in problems.items():
        for issue in issues:
            issue_type = issue["type"].name if hasattr(issue["type"], "name") else str(issue["type"])
            if issue_type in TARGET_WARNING_TYPES:
                counts[issue_type] += 1
                targets.add(glyph_name)

    return sorted(targets), counts


def glyph_has_components(font, glyph_name: str) -> bool:
    layers = master_layers_for_glyph(font, glyph_name)
    return any(layer.components for layer in layers.values())


def process_font(label: str, dry_run: bool) -> int:
    source_path, ds_name, ufo_prefix = designspace_for(label)
    print(f"\n{'=' * 72}")
    print(f"Processing {source_path.name}")
    print(f"{'=' * 72}")

    ds_path = export(source_path, ds_name, ufo_prefix)
    targets, counts = collect_target_glyphs(ds_path)

    print("Initial export-warning scan")
    print("---------------------------")
    print(f"wrong_start_point:         {counts['wrong_start_point']}")
    print(f"node_incompatibility:      {counts['node_incompatibility']}")
    print(f"target glyphs:             {len(targets)}")

    if not targets:
        print("No target glyphs found.")
        return 0

    font = glyphsLib.load(str(source_path))
    fixed = 0
    skipped: list[str] = []
    failed: list[str] = []

    for glyph_name in targets:
        if glyph_has_components(font, glyph_name):
            skipped.append(glyph_name)
            continue
        if fix_glyph(font, glyph_name, dry_run=dry_run, force=True):
            fixed += 1
        else:
            failed.append(glyph_name)

    print("\nNormalization pass")
    print("------------------")
    print(f"normalized glyphs:         {fixed}")
    print(f"skipped glyphs:            {len(skipped)}")
    print(f"failed glyphs:             {len(failed)}")
    if skipped:
        print(f"  skipped: {', '.join(skipped[:20])}")
    if failed:
        print(f"  failed: {', '.join(failed[:20])}")

    if dry_run:
        print("Dry run complete. File not saved.")
        return 0

    font.save(str(source_path))
    print(f"Saved -> {source_path}")

    ds_path = export(source_path, ds_name, ufo_prefix)
    remaining_targets, remaining_counts = collect_target_glyphs(ds_path)

    print("\nPost-fix export-warning scan")
    print("----------------------------")
    print(f"wrong_start_point:         {remaining_counts['wrong_start_point']}")
    print(f"node_incompatibility:      {remaining_counts['node_incompatibility']}")
    print(f"remaining target glyphs:   {len(remaining_targets)}")
    if remaining_targets:
        print(f"  sample: {', '.join(remaining_targets[:20])}")

    return 1 if remaining_targets else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize only the glyphs that still trigger export-time structure warnings"
    )
    parser.add_argument("--roman", action="store_true", help="Process roman only")
    parser.add_argument("--italic", action="store_true", help="Process italic only")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without saving")
    args = parser.parse_args()

    labels = ["roman", "italic"]
    if args.roman and not args.italic:
        labels = ["roman"]
    elif args.italic and not args.roman:
        labels = ["italic"]

    exit_code = 0
    for label in labels:
        exit_code |= process_font(label, dry_run=args.dry_run)

    print("\nDone.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
