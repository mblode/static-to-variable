"""Geometry scoring: void (area diff), irregularity (curvature), drift (vertex deviation).

Each metric is normalised to a 0-1 quality score where 1 = perfect match / smooth outline
and 0 = catastrophic regression. The composite score is the geometric mean of the three,
so a single catastrophic component drags the glyph into "red" territory.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cache

import numpy as np
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw
from render_glyph import _donor_font, _instanced_glide
from shared import Family, donor_otf, resolve_glyph_name, vf_path

RASTER = 256


@dataclass(frozen=True)
class CellScores:
    void: float
    irregularity: float
    drift: float
    composite: float

    def to_dict(self) -> dict[str, float]:
        return {
            "void": round(self.void, 4),
            "irregularity": round(self.irregularity, 4),
            "drift": round(self.drift, 4),
            "composite": round(self.composite, 4),
        }


def _flatten_ops(ops: list, steps: int = 12) -> list[tuple[float, float]]:
    """Turn pen ops into a flat list of points (subdividing curves)."""
    pts: list[tuple[float, float]] = []
    current = (0.0, 0.0)
    subpath_start = (0.0, 0.0)
    for op, args in ops:
        if op == "moveTo":
            (current,) = args
            subpath_start = current
            pts.append(current)
        elif op == "lineTo":
            (current,) = args
            pts.append(current)
        elif op == "curveTo":
            # cubic bezier (c1, c2, end)
            c1, c2, end = args
            for i in range(1, steps + 1):
                t = i / steps
                u = 1 - t
                x = u**3 * current[0] + 3 * u**2 * t * c1[0] + 3 * u * t**2 * c2[0] + t**3 * end[0]
                y = u**3 * current[1] + 3 * u**2 * t * c1[1] + 3 * u * t**2 * c2[1] + t**3 * end[1]
                pts.append((x, y))
            current = end
        elif op == "qCurveTo":
            # quadratic bezier chain; last arg is end, preceding are off-curve
            on_pts = [current, *args]
            for index, (a, b, c) in enumerate(zip(on_pts, on_pts[1:], on_pts[2:], strict=False)):
                # midpoint trick: quads are between implied midpoints. Track the
                # segment index explicitly — list.index() returns the FIRST
                # occurrence, which is wrong for contours with duplicate points.
                start = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0) if index > 0 else a
                control = b
                end = (
                    ((b[0] + c[0]) / 2.0, (b[1] + c[1]) / 2.0) if index + 2 < len(on_pts) - 1 else c
                )
                for i in range(1, steps + 1):
                    t = i / steps
                    u = 1 - t
                    x = u * u * start[0] + 2 * u * t * control[0] + t * t * end[0]
                    y = u * u * start[1] + 2 * u * t * control[1] + t * t * end[1]
                    pts.append((x, y))
            current = args[-1]
        elif op == "closePath":
            if pts and pts[-1] != subpath_start:
                pts.append(subpath_start)
            current = subpath_start
        elif op == "endPath":
            current = subpath_start
    return pts


def _subpaths(ops: list) -> list[list[tuple[float, float]]]:
    subs: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    buf: list = []
    for op, args in ops:
        if op == "moveTo" and buf:
            subs.append(_flatten_ops(buf))
            buf = []
        buf.append((op, args))
    if buf:
        subs.append(_flatten_ops(buf))
    return [p for p in subs if len(p) >= 3]


def _raster(ops: list, font: TTFont) -> np.ndarray:
    """Rasterize pen ops to an RASTER×RASTER binary mask using the font's em box."""
    img = Image.new("L", (RASTER, RASTER), 0)
    draw = ImageDraw.Draw(img)
    units = font["head"].unitsPerEm
    # Centre on em box; y is flipped (font up → raster down)
    scale = (RASTER * 0.8) / units
    offset_x = RASTER / 2 - (units / 2) * scale
    offset_y = RASTER / 2 + (units / 2) * scale  # invert later
    for sub in _subpaths(ops):
        pixels = [(int(x * scale + offset_x), int(offset_y - y * scale)) for (x, y) in sub]
        if len(pixels) >= 3:
            draw.polygon(pixels, fill=255)
    return np.array(img, dtype=np.uint8) > 0


def _record_ops(font: TTFont, glyph_name: str) -> list | None:
    glyph_set = font.getGlyphSet()
    if glyph_name not in glyph_set:
        return None
    pen = RecordingPen()
    glyph_set[glyph_name].draw(pen)
    return pen.value


def void_score(donor_mask: np.ndarray, glide_mask: np.ndarray) -> float:
    """Symmetric-difference area / donor area, clipped & inverted so 1 = perfect."""
    donor_area = donor_mask.sum()
    if donor_area == 0:
        return 0.0 if glide_mask.sum() > 0 else 1.0
    diff = np.logical_xor(donor_mask, glide_mask).sum()
    ratio = diff / donor_area
    # 0% diff → 1.0, 50% diff → 0.5, ≥100% → 0
    return float(max(0.0, 1.0 - ratio))


def irregularity_score(glide_ops: list) -> float:
    """Curvature variance: smooth outlines → 1.0, lumpy/kinked → 0.
    Measures the std-dev of turning angles between consecutive polyline segments."""
    subs = _subpaths(glide_ops)
    if not subs:
        return 0.0
    angles: list[float] = []
    for pts in subs:
        if len(pts) < 3:
            continue
        for i in range(len(pts)):
            a = pts[i - 2]
            b = pts[i - 1]
            c = pts[i]
            v1 = (b[0] - a[0], b[1] - a[1])
            v2 = (c[0] - b[0], c[1] - b[1])
            m1 = math.hypot(*v1)
            m2 = math.hypot(*v2)
            if m1 < 1e-3 or m2 < 1e-3:
                continue
            dot = (v1[0] * v2[0] + v1[1] * v2[1]) / (m1 * m2)
            dot = max(-1.0, min(1.0, dot))
            angles.append(math.acos(dot))
    if not angles:
        return 1.0
    # Ideal: all small, consistent angles. Variance → irregularity.
    arr = np.array(angles)
    var = float(arr.var())
    # map variance into [0, 1]: var=0 → 1.0, var ≥ 1.5 (rad²) → 0
    return max(0.0, 1.0 - min(var / 1.5, 1.0))


def drift_score(donor_ops: list, glide_ops: list, font_units: int) -> float:
    """Hausdorff-style distance between outlines, normalised to em box. 1 = coincident."""
    donor_pts = np.array([p for sub in _subpaths(donor_ops) for p in sub])
    glide_pts = np.array([p for sub in _subpaths(glide_ops) for p in sub])
    if donor_pts.size == 0 or glide_pts.size == 0:
        return 0.0
    # mean nearest-neighbour distance, one-way: for each glide point, distance to nearest donor point
    from scipy.spatial import cKDTree

    tree = cKDTree(donor_pts)
    dist, _ = tree.query(glide_pts, k=1)
    mean_d = float(dist.mean())
    # normalise: 0 → 1.0, em-box / 10 → 0
    threshold = font_units / 10.0
    return max(0.0, 1.0 - min(mean_d / threshold, 1.0))


def composite(v: float, i: float, d: float) -> float:
    """Geometric mean (penalises any single bad component)."""
    product = max(v, 1e-4) * max(i, 1e-4) * max(d, 1e-4)
    return float(product ** (1.0 / 3.0))


@cache
def score_cell(family: Family, glyph: str, wght: int) -> CellScores | None:
    donor_path = donor_otf(family, wght)
    if donor_path is None:
        return None
    donor_font = _donor_font(family, wght)
    glide_font = _instanced_glide(family, wght)

    donor_name = resolve_glyph_name(glyph, donor_path)
    glide_name = resolve_glyph_name(glyph, vf_path(family))
    if donor_name is None or glide_name is None:
        return None

    donor_ops = _record_ops(donor_font, donor_name)
    glide_ops = _record_ops(glide_font, glide_name)
    if donor_ops is None or glide_ops is None:
        return None

    donor_mask = _raster(donor_ops, donor_font)
    glide_mask = _raster(glide_ops, glide_font)

    units = glide_font["head"].unitsPerEm
    v = void_score(donor_mask, glide_mask)
    i = irregularity_score(glide_ops)
    d = drift_score(donor_ops, glide_ops, units)
    return CellScores(void=v, irregularity=i, drift=d, composite=composite(v, i, d))
