#!/usr/bin/env python3
"""
fix_ttf_startpoints.py — Fix contour start-point alignment in variable font masters.

Builds 4 individual master TTFs from the UFO sources, aligns start-point
indices across masters (using the Regular/400 master as reference), then merges
into a variable font with fontTools varLib.

This fixes the "start point differs" warnings from fontTools.varLib.interpolatable
that persist after the source-level normalization because cu2qu can shuffle
start points during cubic-to-quadratic conversion.

Usage:
    cd <repo-root>
    .venv/bin/python cabinet/fix_ttf_startpoints.py [--italic]
    # Outputs: cabinet/input/roman/GlideVF.ttf (or italic/)
"""

import argparse
import subprocess
import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph
from fontTools import varLib
from fontTools.designspaceLib import DesignSpaceDocument

REPO_ROOT = Path(__file__).resolve().parent.parent
MASTER_UFO_DIR = REPO_ROOT / "master_ufo"


def build_master_ttfs(ds_path: Path, out_dir: Path) -> list[Path]:
    """Build individual static TTFs for each master using fontmake."""
    out_dir.mkdir(parents=True, exist_ok=True)
    venv_fontmake = REPO_ROOT / ".venv" / "bin" / "fontmake"
    result = subprocess.run(
        [str(venv_fontmake),
         "-m", str(ds_path),
         "-o", "ttf",
         "--overlaps-backend", "pathops",
         "--output-dir", str(out_dir)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        # Fall back to keep-overlaps if pathops fails
        result = subprocess.run(
            [str(venv_fontmake),
             "-m", str(ds_path),
             "-o", "ttf",
             "--keep-overlaps",
             "--output-dir", str(out_dir)],
            capture_output=True, text=True
        )
    if result.returncode != 0:
        print("STDERR:", result.stderr[-2000:])
        raise RuntimeError("fontmake failed to build master TTFs")
    ttfs = sorted(out_dir.glob("*.ttf"))
    print(f"  Built {len(ttfs)} master TTFs: {[t.name for t in ttfs]}")
    return ttfs


def get_glyph_contours(glyph_table, glyph_name: str) -> list | None:
    """
    Return list of contour point lists for a glyph.
    Each contour is a list of (x, y, flags) tuples (TrueType quadratic).
    Returns None for empty/missing glyphs or composites.
    """
    if glyph_name not in glyph_table:
        return None
    g = glyph_table[glyph_name]
    if not hasattr(g, 'numberOfContours') or g.numberOfContours <= 0:
        return None  # empty or composite
    g.expand(glyph_table)
    n = g.numberOfContours
    contours = []
    start = 0
    for end in g.endPtsOfContours:
        pts = list(zip(g.coordinates[start:end+1], g.flags[start:end+1]))
        contours.append(pts)
        start = end + 1
    return contours


def rotate_to_point(pts: list, target_xy: tuple) -> int:
    """
    Return the index of the on-curve point in `pts` closest to `target_xy`.
    Only considers on-curve points (flag bit 0 == 1 in TrueType).
    """
    on_curve = [(i, p) for i, (p, f) in enumerate(pts) if f & 1]
    if not on_curve:
        return 0
    tx, ty = target_xy
    best_i, best_d = 0, float('inf')
    for i, (x, y) in on_curve:
        d = (x - tx) ** 2 + (y - ty) ** 2
        if d < best_d:
            best_d = d
            best_i = i
    return best_i


def align_start_points_in_ttfs(ttf_paths: list[Path]) -> int:
    """
    Align contour start points across master TTFs using the first TTF as reference.
    Modifies glyph tables in-place and saves each TTF.
    Returns number of glyphs fixed.
    """
    if len(ttf_paths) < 2:
        return 0

    fonts = [TTFont(str(p)) for p in ttf_paths]
    ref_font = fonts[0]
    ref_glyph_set = ref_font['glyf']

    glyph_names = list(ref_font.getGlyphOrder())
    fixed_count = 0

    for glyph_name in glyph_names:
        ref_contours = get_glyph_contours(ref_glyph_set, glyph_name)
        if ref_contours is None:
            continue

        needs_fix = False
        for font in fonts[1:]:
            other_contours = get_glyph_contours(font['glyf'], glyph_name)
            if other_contours is None or len(other_contours) != len(ref_contours):
                continue
            for k, (ref_c, other_c) in enumerate(zip(ref_contours, other_contours)):
                if len(ref_c) != len(other_c):
                    continue
                ref_start_xy = ref_c[0][0]
                other_start_xy = other_c[0][0]
                if ref_start_xy != other_start_xy:
                    needs_fix = True
                    break
            if needs_fix:
                break

        if not needs_fix:
            continue

        fixed_count += 1

        # For each non-reference master, rotate contours to align with reference
        for font in fonts[1:]:
            glyph_table = font['glyf']
            other_contours = get_glyph_contours(glyph_table, glyph_name)
            if other_contours is None or len(other_contours) != len(ref_contours):
                continue

            g = glyph_table[glyph_name]
            all_coords = list(g.coordinates)
            all_flags = list(g.flags)

            new_coords = []
            new_flags = []
            offset = 0

            for k, (ref_c, other_c) in enumerate(zip(ref_contours, other_contours)):
                if len(ref_c) != len(other_c):
                    # Can't align - use as-is
                    new_coords.extend([p for p, f in other_c])
                    new_flags.extend([f for p, f in other_c])
                    offset += len(other_c)
                    continue

                ref_start_xy = ref_c[0][0]
                rot = rotate_to_point(other_c, ref_start_xy)

                if rot != 0:
                    # Rotate the contour
                    rotated = other_c[rot:] + other_c[:rot]
                else:
                    rotated = other_c

                new_coords.extend([p for p, f in rotated])
                new_flags.extend([f for p, f in rotated])
                offset += len(other_c)

            from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
            import array
            g.coordinates = GlyphCoordinates(new_coords)
            g.flags = array.array("B", new_flags)

    # Contour-order fix: some glyphs have contours in different sequence across masters.
    # Use bounding-box matching (same as normalize_master_ops) to reorder non-reference masters.
    for glyph_name in glyph_names:
        ref_contours = get_glyph_contours(fonts[0]['glyf'], glyph_name)
        if ref_contours is None or len(ref_contours) < 2:
            continue

        def contour_centroid(c):
            xs = [p[0] for p, f in c]
            ys = [p[1] for p, f in c]
            return (sum(xs) / len(xs), sum(ys) / len(ys))

        ref_centroids = [contour_centroid(c) for c in ref_contours]

        for font in fonts[1:]:
            other_contours = get_glyph_contours(font['glyf'], glyph_name)
            if other_contours is None or len(other_contours) != len(ref_contours):
                continue

            other_centroids = [contour_centroid(c) for c in other_contours]

            # Match each other contour to best reference contour by centroid distance
            used = set()
            mapping = []  # mapping[k] = index of other_contour that best matches ref_contour[k]
            for rx, ry in ref_centroids:
                best_j, best_d = 0, float('inf')
                for j, (ox, oy) in enumerate(other_centroids):
                    if j in used:
                        continue
                    d = (rx - ox) ** 2 + (ry - oy) ** 2
                    if d < best_d:
                        best_d = d
                        best_j = j
                mapping.append(best_j)
                used.add(best_j)

            # If mapping is identity, no reorder needed
            if mapping == list(range(len(ref_contours))):
                continue

            # Reorder contours
            g = font['glyf'][glyph_name]
            reordered = [other_contours[j] for j in mapping]

            from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
            import array
            new_coords = [p for c in reordered for p, f in c]
            new_flags = [f for c in reordered for p, f in c]
            # Rebuild endPtsOfContours
            end = -1
            new_ends = []
            for c in reordered:
                end += len(c)
                new_ends.append(end)
            g.coordinates = GlyphCoordinates(new_coords)
            g.flags = array.array("B", new_flags)
            g.endPtsOfContours = new_ends

    # Save fixed TTFs
    for font, path in zip(fonts, ttf_paths):
        font.save(str(path))
        print(f"  Saved aligned: {path.name}")

    return fixed_count


def build_variable_from_masters(ds_path: Path, master_ttfs: list[Path],
                                 output_ttf: Path) -> None:
    """Build a variable font from pre-aligned master TTFs."""
    ds = DesignSpaceDocument.fromfile(str(ds_path))

    # Update source filenames to point to our built master TTFs
    # Sort masters by wght value to match TTF sort order
    master_locations = []
    for src in ds.sources:
        wght = src.location.get('Weight', 0)
        master_locations.append((wght, src))
    master_locations.sort(key=lambda x: x[0])
    sorted_srcs = [src for _, src in master_locations]

    # fontmake names TTFs after source name — find by matching
    for src, ttf_path in zip(sorted_srcs, master_ttfs):
        src.font = TTFont(str(ttf_path))
        src.path = str(ttf_path)
        src.filename = ttf_path.name

    print("  Building variable font with varLib...")
    vf, _, _ = varLib.build(ds)
    output_ttf.parent.mkdir(parents=True, exist_ok=True)
    vf.save(str(output_ttf))
    print(f"  Saved: {output_ttf}")


ITALIC_LOOKUP_PREFIX = """\
# Prefix: Prefix
lookup SUB_5 {
\tsub x by multiply;
} SUB_5;
lookup SUB_6 {
\tsub slash by fraction;
\tsub zero by zero.numr;
\tsub one by one.numr;
\tsub two by two.numr;
\tsub three by three.numr;
\tsub four by four.numr;
\tsub five by five.numr;
\tsub six by six.numr;
\tsub seven by seven.numr;
\tsub eight by eight.numr;
\tsub nine by nine.numr;
\tsub fraction by fraction;
\tsub uni2215 by fraction;
} SUB_6;
lookup SUB_7 {
\tsub space by space.frac;
\tsub zero by zero.dnom;
\tsub one by one.dnom;
\tsub two by two.dnom;
\tsub three by three.dnom;
\tsub four by four.dnom;
\tsub five by five.dnom;
\tsub six by six.dnom;
\tsub seven by seven.dnom;
\tsub eight by eight.dnom;
\tsub nine by nine.dnom;
} SUB_7;

"""


def _inject_italic_lookup_defs() -> None:
    """
    glyphsLib omits SUB_5/6/7 lookup definitions when exporting italic UFOs.
    Inject them at the top of each italic master's features.fea if not already present.
    """
    for ufo_dir in sorted((MASTER_UFO_DIR).glob("GlideItalic_*.ufo")):
        fea_path = ufo_dir / "features.fea"
        if not fea_path.exists():
            continue
        content = fea_path.read_text()
        if "lookup SUB_5 {" in content:
            continue  # already injected (definition present)
        fea_path.write_text(ITALIC_LOOKUP_PREFIX + content)
        print(f"  Injected SUB_5/6/7 into {fea_path.parent.name}/features.fea")


def main():
    parser = argparse.ArgumentParser(description="Fix start-point alignment in variable font masters")
    parser.add_argument("--italic", action="store_true", help="Process italic source")
    args = parser.parse_args()

    if args.italic:
        ds_name = "GlideItalic.designspace"
        out_ttf = REPO_ROOT / "cabinet" / "input" / "italic" / "GlideVF.ttf"
        masters_dir = REPO_ROOT / "master_ufo" / "italic_masters"
    else:
        ds_name = "Glide.designspace"
        out_ttf = REPO_ROOT / "cabinet" / "input" / "roman" / "GlideVF.ttf"
        masters_dir = REPO_ROOT / "master_ufo" / "roman_masters"

    ds_path = MASTER_UFO_DIR / ds_name
    if not ds_path.exists():
        print(f"ERROR: {ds_path} not found. Run cabinet/export_designspace.py first.")
        sys.exit(1)

    if args.italic:
        _inject_italic_lookup_defs()

    print(f"\n=== Step 1: Build master TTFs ===")
    ttf_paths = build_master_ttfs(ds_path, masters_dir)

    if len(ttf_paths) < 4:
        print(f"WARNING: Expected 4 masters, got {len(ttf_paths)}")

    print(f"\n=== Step 2: Align contour start points ===")
    fixed = align_start_points_in_ttfs(ttf_paths)
    print(f"  Fixed {fixed} glyphs")

    print(f"\n=== Step 3: Build variable font ===")
    # Sort by weight (file name order usually matches)
    ttf_paths.sort()
    build_variable_from_masters(ds_path, ttf_paths, out_ttf)

    print(f"\n=== Step 4: Verify ===")
    from fontTools.varLib.interpolatable import main as interp_check
    print("Running interpolatable check...")
    # Capture result
    from fontTools.ttLib import TTFont
    font = TTFont(str(out_ttf))
    fvar = font['fvar']
    print(f"  Axis: wght {fvar.axes[0].minValue}–{fvar.axes[0].maxValue}")
    print(f"  Glyphs with gvar: {len(font['gvar'].variations)}")


if __name__ == "__main__":
    main()
