"""Font-level audit helpers shared by the variable-audit gate.

Geometry metrics (ink area, point deviation, self-intersections), designspace
interpolatable runs, UFO contour-order normalization, and fontmake variable
builds. Runs against any config-driven project.
"""

from __future__ import annotations

import json
import math
import shlex
import subprocess
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

import ufoLib2
from fontTools.designspaceLib import DesignSpaceDocument
from fontTools.pens.basePen import decomposeQuadraticSegment
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont
from fontTools.varLib import interpolatable
from fontTools.varLib.instancer import instantiateVariableFont

from variable_gen.common import fontmake_command

Point = tuple[float, float]


def json_safe(value: Any) -> Any:
    """Recursively coerce fontTools report objects into JSON-serializable data."""
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except Exception:  # noqa: BLE001 — numpy scalars vary; fall through to str()
            pass
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


# --- glyph geometry metrics -------------------------------------------------


def glyph_ink_area(font: TTFont, glyph_name: str) -> float:
    """Estimate ink area of a glyph using the shoelace formula on contour points."""
    glyph_set = font.getGlyphSet()
    if glyph_name not in glyph_set:
        return 0.0
    pen = RecordingPen()
    glyph_set[glyph_name].draw(pen)

    total_area = 0.0
    contour_points: list[Point] = []
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
    """Compute mean point distance between the same glyph in two fonts.

    Returns ``None`` when the glyph is missing from either font or the point
    structures do not match (different point counts).
    """
    gs_a = font_a.getGlyphSet()
    gs_b = font_b.getGlyphSet()
    if glyph_name not in gs_a or glyph_name not in gs_b:
        return None

    pen_a = RecordingPen()
    pen_b = RecordingPen()
    gs_a[glyph_name].draw(pen_a)
    gs_b[glyph_name].draw(pen_b)

    def extract_points(pen: RecordingPen) -> list[Point]:
        points: list[Point] = []
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
        for (ax, ay), (bx, by) in zip(pts_a, pts_b, strict=True)
    )
    return total / len(pts_a)


# --- polyline sampling + self-intersection metrics ---------------------------


def sample_quadratic(p0: Point, p1: Point, p2: Point, steps: int) -> list[Point]:
    points = []
    for step in range(1, steps + 1):
        t = step / steps
        mt = 1.0 - t
        x = (mt * mt * p0[0]) + (2.0 * mt * t * p1[0]) + (t * t * p2[0])
        y = (mt * mt * p0[1]) + (2.0 * mt * t * p1[1]) + (t * t * p2[1])
        points.append((x, y))
    return points


def sample_cubic(p0: Point, p1: Point, p2: Point, p3: Point, steps: int) -> list[Point]:
    points = []
    for step in range(1, steps + 1):
        t = step / steps
        mt = 1.0 - t
        x = (mt**3) * p0[0] + 3 * (mt**2) * t * p1[0] + 3 * mt * (t**2) * p2[0] + (t**3) * p3[0]
        y = (mt**3) * p0[1] + 3 * (mt**2) * t * p1[1] + 3 * mt * (t**2) * p2[1] + (t**3) * p3[1]
        points.append((x, y))
    return points


def glyph_polylines(font: TTFont, glyph_name: str, steps: int = 10) -> list[list[Point]]:
    """Flatten a glyph's outline into per-contour polylines with curves sampled."""
    glyph_set = font.getGlyphSet()
    if glyph_name not in glyph_set:
        return []

    pen = RecordingPen()
    glyph_set[glyph_name].draw(pen)
    contours: list[list[Point]] = []
    contour: list[Point] = []
    start: Point | None = None
    current: Point | None = None

    for op, args in pen.value:
        if op == "moveTo":
            if contour:
                contours.append(contour)
            start = args[0]
            current = start
            contour = [start]
        elif op == "lineTo":
            current = args[0]
            contour.append(current)
        elif op == "qCurveTo" and current is not None:
            for control, end in decomposeQuadraticSegment(args):
                contour.extend(sample_quadratic(current, control, end, steps))
                current = end
        elif op == "curveTo" and current is not None:
            c1, c2, end = args
            contour.extend(sample_cubic(current, c1, c2, end, steps))
            current = end
        elif op in ("closePath", "endPath"):
            if contour and start is not None and contour[-1] != start:
                contour.append(start)
            if contour:
                contours.append(contour)
            contour = []
            start = None
            current = None

    if contour:
        contours.append(contour)
    return contours


def segments_for_contours(
    contours: list[list[Point]],
) -> list[tuple[int, int, Point, Point]]:
    segments = []
    for contour_index, contour in enumerate(contours):
        for segment_index in range(len(contour) - 1):
            segments.append(
                (contour_index, segment_index, contour[segment_index], contour[segment_index + 1])
            )
    return segments


def sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def ccw(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def bounding_boxes_overlap(a0: Point, a1: Point, b0: Point, b1: Point) -> bool:
    return not (
        max(a0[0], a1[0]) < min(b0[0], b1[0])
        or max(b0[0], b1[0]) < min(a0[0], a1[0])
        or max(a0[1], a1[1]) < min(b0[1], b1[1])
        or max(b0[1], b1[1]) < min(a0[1], a1[1])
    )


def segments_intersect(a0: Point, a1: Point, b0: Point, b1: Point) -> bool:
    if a0 == b0 or a0 == b1 or a1 == b0 or a1 == b1:
        return False
    if not bounding_boxes_overlap(a0, a1, b0, b1):
        return False
    d1 = ccw(a0, a1, b0)
    d2 = ccw(a0, a1, b1)
    d3 = ccw(b0, b1, a0)
    d4 = ccw(b0, b1, a1)
    return (d1 == 0 or d2 == 0 or sign(d1) != sign(d2)) and (
        d3 == 0 or d4 == 0 or sign(d3) != sign(d4)
    )


def contour_segment_lengths(contours: list[list[Point]]) -> list[float]:
    lengths = []
    for contour in contours:
        for p0, p1 in zip(contour, contour[1:], strict=False):
            lengths.append(math.hypot(p1[0] - p0[0], p1[1] - p0[1]))
    return lengths


def glyph_intersection_metrics(font: TTFont, glyph_name: str) -> dict[str, object]:
    contours = glyph_polylines(font, glyph_name)
    segments = segments_for_contours(contours)
    intersections = 0

    for index, (contour_a, segment_a, a0, a1) in enumerate(segments):
        for contour_b, segment_b, b0, b1 in segments[index + 1 :]:
            if contour_a == contour_b and abs(segment_a - segment_b) <= 1:
                continue
            if contour_a == contour_b and {segment_a, segment_b} == {
                0,
                len(contours[contour_a]) - 2,
            }:
                continue
            if segments_intersect(a0, a1, b0, b1):
                intersections += 1

    lengths = contour_segment_lengths(contours)
    return {
        "contours": len(contours),
        "intersections": intersections,
        "min_segment_length": round(min(lengths), 2) if lengths else None,
        "zero_ink": glyph_ink_area(font, glyph_name) <= 0.0,
    }


# --- designspace-wide checks --------------------------------------------------


def designspace_source_paths(designspace_path: Path) -> list[Path]:
    designspace = DesignSpaceDocument.fromfile(str(designspace_path))
    source_paths: list[Path] = []
    for source in designspace.sources:
        if source.path:
            source_paths.append(Path(source.path).resolve())
        elif source.filename:
            source_paths.append((designspace_path.parent / source.filename).resolve())
    return source_paths


def run_interpolatable_designspace(designspace_path: Path, report_path: Path) -> dict[str, object]:
    """Run fontTools ``varLib.interpolatable`` across a designspace's sources and
    write the raw problem payload to ``report_path``. Returns a compact summary."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in (".stdout.txt", ".stderr.txt"):
        stale = report_path.with_suffix(suffix)
        if stale.exists():
            stale.unlink()
    source_paths = [str(path) for path in designspace_source_paths(designspace_path)]

    problems = interpolatable.main([*source_paths, "--quiet"])
    payload = json_safe(problems)
    report_path.write_text(json.dumps(payload, indent=2))
    issue_counts: Counter[str] = Counter()
    for issues in payload.values():
        for issue in issues:
            issue_counts[str(issue.get("type", "unknown"))] += 1
    return {"problem_glyphs": len(payload), "issue_types": dict(issue_counts)}


# --- UFO contour-order + unicode normalization --------------------------------


def _ufo_contour_signature(contour: Any) -> tuple[str, ...]:
    return tuple(str(point.segmentType or "offcurve") for point in contour)


def _ufo_canonical_contour_signature(contour: Any) -> tuple[str, ...]:
    signature = list(_ufo_contour_signature(contour))
    if not signature:
        return ()
    count = len(signature)
    forward = {tuple(signature[index:] + signature[:index]) for index in range(count)}
    reverse_sig = signature[::-1]
    reverse = {tuple(reverse_sig[index:] + reverse_sig[:index]) for index in range(count)}
    return min(forward | reverse)


def _ufo_contour_centroid(contour: Any) -> Point:
    xs: list[float] = []
    ys: list[float] = []
    for point in contour:
        if point.segmentType is None:
            continue
        xs.append(point.x)
        ys.append(point.y)
    if not xs:
        return (0.0, 0.0)
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _ufo_contour_bbox(contour: Any) -> tuple[float, float, float, float]:
    xs = [point.x for point in contour]
    ys = [point.y for point in contour]
    return (min(xs), min(ys), max(xs), max(ys))


def _ufo_dist_sq(a: Point, b: Point) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def best_ufo_contour_mapping(reference_contours: list[Any], other_contours: list[Any]) -> list[int]:
    """Match ``other_contours`` to ``reference_contours`` (same length) minimizing
    signature mismatches, centroid distance, and size drift. Exact assignment via
    bitmask DP — contour counts per glyph are small."""
    count = len(reference_contours)
    if count <= 1:
        return list(range(count))

    reference_signatures = [
        _ufo_canonical_contour_signature(contour) for contour in reference_contours
    ]
    other_signatures = [_ufo_canonical_contour_signature(contour) for contour in other_contours]

    reference_centroids = [_ufo_contour_centroid(contour) for contour in reference_contours]
    other_centroids = [_ufo_contour_centroid(contour) for contour in other_contours]
    reference_bboxes = [_ufo_contour_bbox(contour) for contour in reference_contours]
    other_bboxes = [_ufo_contour_bbox(contour) for contour in other_contours]

    costs = [[0.0] * count for _ in range(count)]
    for reference_index in range(count):
        reference_bbox = reference_bboxes[reference_index]
        reference_width = reference_bbox[2] - reference_bbox[0]
        reference_height = reference_bbox[3] - reference_bbox[1]
        reference_scale = max(reference_width * reference_height, 1.0)

        for other_index in range(count):
            penalty = 0.0
            if reference_signatures[reference_index] != other_signatures[other_index]:
                penalty = 1_000_000.0
            other_bbox = other_bboxes[other_index]
            centroid_cost = (
                _ufo_dist_sq(
                    reference_centroids[reference_index],
                    other_centroids[other_index],
                )
                / reference_scale
            )
            size_cost = abs(reference_width - (other_bbox[2] - other_bbox[0]))
            size_cost += abs(reference_height - (other_bbox[3] - other_bbox[1]))
            costs[reference_index][other_index] = penalty + centroid_cost + size_cost

    @lru_cache(None)
    def solve(reference_index: int, used_mask: int) -> tuple[float, tuple[int, ...]]:
        if reference_index == count:
            return (0.0, ())

        best_score = float("inf")
        best_mapping: tuple[int, ...] = ()
        for other_index in range(count):
            if used_mask & (1 << other_index):
                continue
            sub_score, sub_mapping = solve(reference_index + 1, used_mask | (1 << other_index))
            score = costs[reference_index][other_index] + sub_score
            if score < best_score:
                best_score = score
                best_mapping = (other_index,) + sub_mapping
        return (best_score, best_mapping)

    return list(solve(0, 0)[1])


def _reorder_ufo_glyph_contours(glyph: Any, mapping: list[int]) -> bool:
    expected = list(range(len(mapping)))
    if mapping == expected:
        return False
    contours = list(glyph)
    glyph.clearContours()
    for contour_index in mapping:
        glyph.appendContour(contours[contour_index])
    return True


def _generic_unicode_glyph_name(glyph_name: str, codepoint: int) -> bool:
    upper_name = glyph_name.upper()
    return upper_name in {
        f"UNI{codepoint:04X}",
        f"U{codepoint:04X}",
        f"U{codepoint:06X}",
    }


def _preferred_unicode_owner(codepoint: int, glyph_names: list[str]) -> str:
    return min(
        glyph_names,
        key=lambda glyph_name: (
            _generic_unicode_glyph_name(glyph_name, codepoint),
            "." in glyph_name,
            len(glyph_name),
            glyph_name,
        ),
    )


def clear_duplicate_ufo_unicodes(designspace_path: Path) -> int:
    """Ensure each codepoint maps to exactly one glyph per UFO source. Returns
    the number of cleared duplicate mappings."""
    cleared = 0
    for source_path in designspace_source_paths(designspace_path):
        font = ufoLib2.Font.open(source_path)
        owners_by_codepoint: dict[int, list[str]] = {}
        for glyph_name in font.keys():
            glyph = font[glyph_name]
            for codepoint in getattr(glyph, "unicodes", []) or []:
                owners_by_codepoint.setdefault(int(codepoint), []).append(glyph_name)

        duplicate_owners = {
            codepoint: glyph_names
            for codepoint, glyph_names in owners_by_codepoint.items()
            if len(glyph_names) > 1
        }
        if not duplicate_owners:
            continue

        for codepoint, glyph_names in duplicate_owners.items():
            keep = _preferred_unicode_owner(codepoint, glyph_names)
            for glyph_name in glyph_names:
                if glyph_name == keep:
                    continue
                glyph = font[glyph_name]
                glyph.unicodes = [value for value in glyph.unicodes if int(value) != codepoint]
                cleared += 1

        font.save(source_path, overwrite=True)
    return cleared


def normalize_designspace_ufo_contour_order(designspace_path: Path) -> int:
    """Reorder contours in every non-reference UFO source to match the first
    source's contour order per glyph. Returns the number of reordered glyphs."""
    source_paths = designspace_source_paths(designspace_path)

    if len(source_paths) < 2:
        return 0

    reference_font = ufoLib2.Font.open(source_paths[0])
    other_fonts = [(path, ufoLib2.Font.open(path)) for path in source_paths[1:]]
    changed_paths: set[Path] = set()
    reordered_glyphs = 0

    reference_glyph_names = set(reference_font.keys())
    common_glyph_names = set(reference_glyph_names)
    for _, font in other_fonts:
        common_glyph_names &= set(font.keys())

    for glyph_name in sorted(common_glyph_names):
        reference_glyph = reference_font[glyph_name]
        reference_contours = list(reference_glyph)
        if len(reference_contours) <= 1:
            continue

        for path, font in other_fonts:
            glyph = font[glyph_name]
            contours = list(glyph)
            if len(contours) != len(reference_contours) or len(contours) <= 1:
                continue
            mapping = best_ufo_contour_mapping(reference_contours, contours)
            if _reorder_ufo_glyph_contours(glyph, mapping):
                changed_paths.add(path)
                reordered_glyphs += 1

    for path, font in other_fonts:
        if path in changed_paths:
            font.save(path, overwrite=True)

    return reordered_glyphs


# --- variable font builds ------------------------------------------------------


def _command_output_log_paths(output_path: Path) -> tuple[Path, Path]:
    return output_path.with_suffix(".stdout.txt"), output_path.with_suffix(".stderr.txt")


def _tail_text(text: str | None, *, max_lines: int = 40, max_chars: int = 8000) -> str:
    if not text:
        return "(empty)"
    tail = "\n".join(text.splitlines()[-max_lines:])
    if len(tail) <= max_chars:
        return tail
    clipped = tail[-max_chars:]
    first_newline = clipped.find("\n")
    if first_newline == -1:
        return clipped
    return clipped[first_newline + 1 :]


def _write_failed_command_output(
    output_path: Path, error: subprocess.CalledProcessError
) -> tuple[Path, Path] | None:
    stdout_path, stderr_path = _command_output_log_paths(output_path)
    try:
        stdout_path.write_text(error.stdout or "")
        stderr_path.write_text(error.stderr or "")
    except OSError as write_error:
        print(
            f"Could not write fontmake stdout/stderr logs next to {output_path}: {write_error}",
            file=sys.stderr,
        )
        return None
    return stdout_path, stderr_path


def build_variable_font(designspace_path: Path, output_path: Path, repo_root: Path) -> Path:
    """Normalize the designspace sources, then build a variable TTF with fontmake.

    On failure the fontmake stdout/stderr are written next to ``output_path`` and
    the ``CalledProcessError`` is re-raised with the command context attached.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    normalize_designspace_ufo_contour_order(designspace_path)
    cleared_unicodes = clear_duplicate_ufo_unicodes(designspace_path)
    if cleared_unicodes:
        print(f"Cleared duplicate UFO unicode mappings: {cleared_unicodes}")
    command = [
        fontmake_command(repo_root),
        "-m",
        str(designspace_path),
        "-o",
        "variable",
        "--keep-overlaps",
        "--output-path",
        str(output_path),
        "--no-check-compatibility",
    ]
    try:
        subprocess.run(command, cwd=repo_root, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        log_paths = _write_failed_command_output(output_path, error)
        command_text = shlex.join(command)
        print(f"fontmake failed while building {output_path}", file=sys.stderr)
        print(f"Command: {command_text}", file=sys.stderr)
        if log_paths:
            stdout_path, stderr_path = log_paths
            print(f"stdout log: {stdout_path}", file=sys.stderr)
            print(f"stderr log: {stderr_path}", file=sys.stderr)
        print("stderr tail:", file=sys.stderr)
        print(_tail_text(error.stderr), file=sys.stderr)
        print("stdout tail:", file=sys.stderr)
        print(_tail_text(error.stdout), file=sys.stderr)

        note = f"fontmake failed for {designspace_path} -> {output_path}; command: {command_text}"
        if log_paths:
            stdout_path, stderr_path = log_paths
            note = f"{note}; stdout: {stdout_path}; stderr: {stderr_path}"
        error.add_note(note)
        raise
    return output_path


def generate_static_samples(
    variable_font_path: Path, weights: list[int], output_dir: Path
) -> dict[int, Path]:
    """Instance the variable font at each weight, writing static TTF samples."""
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: dict[int, Path] = {}
    for weight in weights:
        varfont = TTFont(variable_font_path)
        static_font = instantiateVariableFont(varfont, {"wght": weight})
        output_path = output_dir / f"{variable_font_path.stem}-wght{weight}.ttf"
        static_font.save(output_path)
        generated[weight] = output_path
    return generated
