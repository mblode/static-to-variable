#!/usr/bin/env python3
"""Config-driven normalization of donor-inherited glyph defects.

This is the generic form of the historical ``normalize_glyphs.py`` (the ``PLANS``
dependency is gone; everything comes from a v3 ``ProjectConfig``). It runs AFTER
the master rebuild and BEFORE the build, fixing defects while keeping masters
interpolation-compatible (per-master operations that preserve point structure):

  * Height: for letters/figures that sit on the baseline, map every master's
    vertical box onto the default master's box, so the height is consistent
    across weights. Enabled by ``normalize.heights`` (default true).

Run:  uv run python -m variable_gen.cli normalize --config <path> --style all
"""

from __future__ import annotations

from dataclasses import dataclass

import glyphsLib
from fontTools.pens.areaPen import AreaPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

from variable_gen.config import ProjectConfig, Style


@dataclass(frozen=True)
class NormalizeStats:
    style: str
    vertical_normalized: int
    skipped: bool = False


# A letter/figure is a donor defect (not innate overshoot) when its vertical box
# is inconsistent with the default master: it floats above the baseline, or falls
# short of the default cap. Innate overshoot only pushes ymin negative / ymax up,
# so round glyphs (6, 9, o, 0...) are never flagged and keep their bloom.
FLOAT_TOL = 30  # max allowed upward float of the baseline vs the default master
SHORT_TOL = 40  # max allowed shortfall of the cap vs the default master


def _stable_height(cmap_rev, name):
    cp = cmap_rev.get(name)
    if cp is None:
        return False
    return (
        (0x30 <= cp <= 0x39)
        or (0x41 <= cp <= 0x5A)
        or (0x61 <= cp <= 0x7A)
        or (0xC0 <= cp <= 0x24F)
    )


def layer_metrics(layer):
    ap, bp = AreaPen(None), BoundsPen(None)
    try:
        layer.draw(ap)
        layer.draw(bp)
    except Exception:  # noqa: BLE001
        return None
    if bp.bounds is None:
        return abs(ap.value), None, None
    return abs(ap.value), bp.bounds[1], bp.bounds[3]  # area, ymin, ymax


#: A contour sitting entirely above this fraction of the layer's height is a
#: floating accent, not part of the letter, and must not decide the letter's box.
DETACHED_ABOVE = 0.5


def base_metrics(layer):
    """(ymin, ymax) of the letter itself, ignoring contours that float above it.

    `layer_metrics` measures the whole layer. That is wrong for the rule this
    module implements, whose own description is about letters that "sit on the
    baseline": a dieresis floats clear of the letter, so including its dots reads
    the ACCENT's height as the letter's cap.

    The consequence was measurable and had been shipping unnoticed. Circular's
    dots gain mass with weight while the accent top stays near the ascender, so
    across Thin/Book/ExtraBlack `adieresis` spans 687/730/768 -- a 43-unit
    shortfall against a 40-unit tolerance. It tripped by three units, and the
    rescale then squashed the whole glyph, base and dots together, to make the
    accent tops agree. The base letter of `adieresis` `edieresis` `odieresis`
    `udieresis` came out 4.2-4.9% shorter than the same letter standing alone at
    ExtraBlack, and the dots came out elliptical, 167x167 to 169x159.

    The signature is unmistakable once looked for: those six glyphs have an
    IDENTICAL ymax at every weight, while every other accented glyph varies --
    including `atilde` and `ntilde`, whose spread is larger. Nothing else in the
    pipeline pins a height like that.

    Returns None when the layer cannot be measured, and falls back to the whole
    layer when nothing qualifies as base ink.
    """
    paths = list(layer.paths or [])
    if not paths:
        return None
    boxes = []
    for path in paths:
        pen = BoundsPen(None)
        try:
            path.draw(pen)
        except Exception:  # noqa: BLE001
            return None
        if pen.bounds is None:
            continue
        boxes.append((pen.bounds[1], pen.bounds[3]))
    if not boxes:
        return None
    low = min(box[0] for box in boxes)
    high = max(box[1] for box in boxes)
    height = high - low
    if height <= 0:
        return low, high
    grounded = [box for box in boxes if box[0] <= low + height * DETACHED_ABOVE]
    if not grounded:
        return low, high
    return min(box[0] for box in grounded), max(box[1] for box in grounded)


def _first_donor_path(config: ProjectConfig, style: Style):
    donor_by_id = {d.id: d for d in style.donors}
    return donor_by_id[style.masters[0].donor_id].path


def normalize_style(config: ProjectConfig, style_key: str) -> NormalizeStats:
    """Height-normalize one style's source in place. Mirrors
    ``normalize_glyphs.normalize_family`` exactly, config-driven."""
    if not config.normalize.get("heights", True):
        return NormalizeStats(style=style_key, vertical_normalized=0, skipped=True)

    style = config.styles[style_key]
    primary_default = config.axes[0].default

    rep = TTFont(str(_first_donor_path(config, style)))
    cmap_rev = {v: k for k, v in rep.getBestCmap().items()}

    with open(style.source) as source_file:
        font = glyphsLib.load(source_file)
    mids = [m.id for m in font.masters]
    rows: dict[tuple[float, ...], list] = {}
    for master in font.masters:
        rows.setdefault(tuple(float(value) for value in master.axes[1:]), []).append(master)

    n_fixed = 0
    for glyph in font.glyphs:
        if not _stable_height(cmap_rev, glyph.name):
            continue
        layers = {layer.layerId: layer for layer in glyph.layers if layer.layerId in mids}
        glyph_fixed = False
        for row_masters in rows.values():
            # Normalize weight defects against the default weight *inside this
            # optical row*. A single global reference would silently flatten
            # the Text pole's intended vertical changes onto the UI pole.
            default_master = next(
                (master for master in row_masters if master.axes[0] == primary_default),
                None,
            )
            if default_master is None:
                continue
            row_layers = {
                master.id: layers[master.id] for master in row_masters if master.id in layers
            }
            ref = row_layers.get(default_master.id)
            if ref is None or len(row_layers) < 2:
                continue
            ref_m = base_metrics(ref)
            if ref_m is None:
                continue
            ref_ymin, ref_ymax = ref_m
            ref_h = ref_ymax - ref_ymin
            if ref_h <= 0:
                continue

            boxes: dict[str, tuple[float, float]] = {}
            complete = True
            for mid, layer in row_layers.items():
                metrics = base_metrics(layer)
                if metrics is None:
                    complete = False
                    break
                boxes[mid] = metrics
            if not (complete and boxes):
                continue
            float_up = max(box[0] for box in boxes.values()) - ref_ymin
            falls_short = ref_ymax - min(box[1] for box in boxes.values())
            if float_up <= FLOAT_TOL and falls_short <= SHORT_TOL:
                continue

            # Map weights in this row onto this row's default box. X and every
            # other optical row remain untouched.
            for mid, layer in row_layers.items():
                if mid == default_master.id:
                    continue
                ymin, ymax = boxes[mid]
                height = ymax - ymin
                if height <= 0:
                    continue
                scale_y = ref_h / height
                for path in layer.paths or []:
                    for node in path.nodes:
                        x, y = node.position
                        node.position = (x, ref_ymin + (y - ymin) * scale_y)
            glyph_fixed = True
        if glyph_fixed:
            n_fixed += 1

    font.save(str(style.source))
    return NormalizeStats(style=style_key, vertical_normalized=n_fixed)


def main(argv: list[str] | None = None) -> int:
    """Thin wrapper: ``python -m variable_gen.normalize`` == ``variable-gen normalize``."""
    from variable_gen.cli import run_command

    return run_command("normalize", argv)


if __name__ == "__main__":
    raise SystemExit(main())
