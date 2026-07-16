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


def _first_donor_path(config: ProjectConfig, style: Style):
    donor_by_id = {d.id: d for d in style.donors}
    return donor_by_id[style.masters[0].donor_id].path


def normalize_style(config: ProjectConfig, style_key: str) -> NormalizeStats:
    """Height-normalize one style's source in place. Mirrors
    ``normalize_glyphs.normalize_family`` exactly, config-driven."""
    if not config.normalize.get("heights", True):
        return NormalizeStats(style=style_key, vertical_normalized=0, skipped=True)

    style = config.styles[style_key]
    default_pos = config.axes[0].default

    rep = TTFont(str(_first_donor_path(config, style)))
    cmap_rev = {v: k for k, v in rep.getBestCmap().items()}

    with open(style.source) as source_file:
        font = glyphsLib.load(source_file)
    mids = [m.id for m in font.masters]
    default_id = next((m.id for m in font.masters if m.axes[0] == default_pos), None)

    n_fixed = 0
    for glyph in font.glyphs:
        if not _stable_height(cmap_rev, glyph.name):
            continue
        layers = {layer.layerId: layer for layer in glyph.layers if layer.layerId in mids}
        ref = layers.get(default_id)
        if ref is None or len(layers) < 2:
            continue
        ref_m = layer_metrics(ref)
        if ref_m is None or ref_m[1] is None:
            continue
        ref_ymin, ref_ymax = ref_m[1], ref_m[2]
        ref_h = ref_ymax - ref_ymin
        if ref_h <= 0:
            continue

        boxes: dict[str, tuple[float, float]] = {}
        complete = True
        for mid, layer in layers.items():
            m = layer_metrics(layer)
            if m is None or m[1] is None:
                complete = False
                break
            boxes[mid] = (m[1], m[2])
        if not (complete and boxes):
            continue
        float_up = max(b[0] for b in boxes.values()) - ref_ymin
        falls_short = ref_ymax - min(b[1] for b in boxes.values())
        if float_up <= FLOAT_TOL and falls_short <= SHORT_TOL:
            continue  # consistent with the default master (only overshoots) — leave alone

        # Map every master's vertical extent onto the default master's box
        # (scale + shift Y): Y' = ref_ymin + (Y - ymin) * ref_h/h. X untouched.
        for mid, layer in layers.items():
            if mid == default_id:
                continue
            ymin, ymax = boxes[mid]
            h = ymax - ymin
            if h <= 0:
                continue
            sy = ref_h / h
            for path in layer.paths or []:
                for node in path.nodes:
                    x, y = node.position
                    node.position = (x, ref_ymin + (y - ymin) * sy)
        n_fixed += 1

    font.save(str(style.source))
    return NormalizeStats(style=style_key, vertical_normalized=n_fixed)


def main(argv: list[str] | None = None) -> int:
    """Thin wrapper: ``python -m variable_gen.normalize`` == ``variable-gen normalize``."""
    from variable_gen.cli import run_command

    return run_command("normalize", argv)


if __name__ == "__main__":
    raise SystemExit(main())
