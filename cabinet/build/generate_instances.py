#!/usr/bin/env python3
"""Generate static font instances from a Glide variable font.

Uses fontTools.varLib.instancer to pin the weight axis at specific values,
producing static TTF fonts.  With ``--validate``, each
generated instance is compared glyph-by-glyph against the original static
master at the same weight and a deviation report is printed.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

from font_metadata import WEIGHT_NAMES
from source_manifest import family_key_for_font_path, load_source_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate static font instances from a Glide variable font."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to the variable TTF font.",
    )
    parser.add_argument(
        "--output-dir",
        default="build/work/output/instances",
        help="Directory for generated static fonts.",
    )
    parser.add_argument(
        "--weights",
        default="400,500,700,900",
        help="Comma-separated weight values to generate.",
    )
    parser.add_argument(
        "--validate",
        metavar="SAMPLE_DIR",
        help="Compare generated instances against original static masters in SAMPLE_DIR.",
    )
    parser.add_argument(
        "--manifest",
        help="Optional JSON source manifest used to map validation masters by weight.",
    )
    parser.add_argument(
        "--family-key",
        choices=("roman", "italic"),
        help="Override the manifest family key used for validation.",
    )
    parser.add_argument(
        "--json-report",
        metavar="PATH",
        help="Write validation report as JSON to this path.",
    )
    return parser.parse_args()


def glyph_ink_area(font: TTFont, glyph_name: str) -> float:
    """Estimate ink area of a glyph using the shoelace formula on contour points."""
    glyph_set = font.getGlyphSet()
    if glyph_name not in glyph_set:
        return 0.0
    pen = RecordingPen()
    glyph_set[glyph_name].draw(pen)

    total_area = 0.0
    contour_points: list[tuple[float, float]] = []
    for op, args in pen.value:
        if op == "moveTo":
            contour_points = [args[0]]
        elif op in ("lineTo", "qCurveTo", "curveTo"):
            contour_points.append(args[-1])
        elif op in ("closePath", "endPath"):
            if len(contour_points) >= 3:
                area = 0.0
                for i in range(len(contour_points)):
                    x0, y0 = contour_points[i]
                    x1, y1 = contour_points[(i + 1) % len(contour_points)]
                    area += x0 * y1 - x1 * y0
                total_area += abs(area) / 2.0
            contour_points = []
    return total_area


def glyph_point_deviation(font_a: TTFont, font_b: TTFont, glyph_name: str) -> float | None:
    """Compute mean point distance between the same glyph in two fonts."""
    gs_a = font_a.getGlyphSet()
    gs_b = font_b.getGlyphSet()
    if glyph_name not in gs_a or glyph_name not in gs_b:
        return None

    pen_a = RecordingPen()
    pen_b = RecordingPen()
    gs_a[glyph_name].draw(pen_a)
    gs_b[glyph_name].draw(pen_b)

    def extract_points(pen: RecordingPen) -> list[tuple[float, float]]:
        points: list[tuple[float, float]] = []
        for op, args in pen.value:
            if op in ("moveTo", "lineTo"):
                points.append(args[0])
            elif op in ("qCurveTo", "curveTo"):
                points.extend(args)
        return points

    pts_a = extract_points(pen_a)
    pts_b = extract_points(pen_b)
    if not pts_a or not pts_b:
        return 0.0
    if len(pts_a) != len(pts_b):
        return None

    total = sum(
        math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)
        for (ax, ay), (bx, by) in zip(pts_a, pts_b)
    )
    return total / len(pts_a)


def stem_width_estimate(font: TTFont, glyph_name: str = "l") -> float | None:
    """Estimate vertical stem width from a simple glyph like 'l'.

    Uses the horizontal extent at the vertical midpoint of the bounding box.
    Falls back to None if the glyph is unavailable.
    """
    glyf_table = font.get("glyf")
    if glyf_table is None or glyph_name not in glyf_table:
        return None
    glyph = glyf_table[glyph_name]
    if not hasattr(glyph, "xMin") or glyph.numberOfContours <= 0:
        return None
    return float(glyph.xMax - glyph.xMin)


def generate_instances(
    variable_font_path: Path,
    output_dir: Path,
    weights: list[int],
) -> dict[int, Path]:
    """Generate static instances at the given weight values."""
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: dict[int, Path] = {}
    stem = variable_font_path.stem

    for weight in weights:
        varfont = TTFont(variable_font_path)
        static_font = instantiateVariableFont(varfont, {"wght": weight})
        weight_name = WEIGHT_NAMES.get(weight, f"wght{weight}")
        ttf_path = output_dir / f"{stem}-{weight_name}.ttf"
        static_font.save(ttf_path)
        print(f"Saved: {ttf_path}")

        generated[weight] = ttf_path
    return generated


def detect_italic(font_path: Path) -> bool:
    """Check whether a variable font is italic based on filename or metadata."""
    return "italic" in font_path.stem.lower()


def validate_instances(
    generated: dict[int, Path],
    sample_dir: Path,
    master_files: dict[int, str],
) -> dict[str, object]:
    """Compare generated instances against original static masters."""
    report: dict[str, object] = {}

    for weight, instance_path in sorted(generated.items()):
        master_filename = master_files.get(weight)
        if master_filename is None:
            continue
        master_path = sample_dir / master_filename
        if not master_path.exists():
            report[str(weight)] = {"error": f"master not found: {master_path}"}
            continue

        instance_font = TTFont(instance_path)
        master_font = TTFont(master_path)

        instance_glyphs = set(instance_font.getGlyphOrder())
        master_glyphs = set(master_font.getGlyphOrder())
        common = sorted(instance_glyphs & master_glyphs)

        deviations: dict[str, float] = {}
        area_diffs: dict[str, float] = {}
        mismatched_points = 0
        total_compared = 0

        for glyph_name in common:
            if glyph_name == ".notdef":
                continue
            dev = glyph_point_deviation(instance_font, master_font, glyph_name)
            if dev is None:
                mismatched_points += 1
            elif dev > 0.5:
                deviations[glyph_name] = round(dev, 2)
            total_compared += 1

            area_i = glyph_ink_area(instance_font, glyph_name)
            area_m = glyph_ink_area(master_font, glyph_name)
            if area_m > 0:
                diff_pct = abs(area_i - area_m) / area_m * 100
                if diff_pct > 1.0:
                    area_diffs[glyph_name] = round(diff_pct, 2)

        stem_instance = stem_width_estimate(instance_font)
        stem_master = stem_width_estimate(master_font)

        weight_report: dict[str, object] = {
            "master": master_filename,
            "common_glyphs": len(common),
            "compared": total_compared,
            "mismatched_point_count": mismatched_points,
            "glyphs_with_deviation": len(deviations),
            "glyphs_with_area_diff_pct": len(area_diffs),
            "stem_width_instance": stem_instance,
            "stem_width_master": stem_master,
        }
        if deviations:
            worst = sorted(deviations.items(), key=lambda kv: kv[1], reverse=True)[:10]
            weight_report["worst_deviations"] = dict(worst)
        if area_diffs:
            worst_area = sorted(area_diffs.items(), key=lambda kv: kv[1], reverse=True)[:10]
            weight_report["worst_area_diffs_pct"] = dict(worst_area)

        report[str(weight)] = weight_report
        status = "MATCH" if not deviations and not area_diffs and mismatched_points == 0 else "DIFF"
        print(
            f"  wght={weight}: {status} "
            f"(deviated={len(deviations)}, area_diff={len(area_diffs)}, "
            f"point_mismatch={mismatched_points}, stem: {stem_instance} vs {stem_master})"
        )

    return report


def main() -> int:
    args = parse_args()
    variable_font_path = Path(args.input).resolve()
    output_dir = Path(args.output_dir).resolve()
    weights = [int(w.strip()) for w in args.weights.split(",")]

    if not variable_font_path.exists():
        raise SystemExit(f"Variable font not found: {variable_font_path}")

    print(f"Generating static instances from: {variable_font_path}")
    generated = generate_instances(variable_font_path, output_dir, weights)

    if args.validate:
        sample_dir = Path(args.validate).resolve()
        if not sample_dir.exists():
            raise SystemExit(f"Sample directory not found: {sample_dir}")

        config = load_source_config(args.manifest)
        family_key = args.family_key or family_key_for_font_path(config, variable_font_path)
        family = config.families.get(family_key)
        if family is None or not family.masters:
            raise SystemExit(f"Source config does not define a usable '{family_key}' family.")

        print(f"\nValidating against masters in: {sample_dir} ({family_key})")
        report = validate_instances(generated, sample_dir, family.master_files_by_weight())

        if args.json_report:
            report_path = Path(args.json_report)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2))
            print(f"\nValidation report: {report_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
