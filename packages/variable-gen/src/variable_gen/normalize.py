#!/usr/bin/env python3
"""Config-driven normalization of donor-inherited glyph defects.

This is the generic form of the historical ``normalize_glyphs.py`` (the ``PLANS``
dependency is gone; everything comes from a v3 ``ProjectConfig``). It runs AFTER
the master rebuild and BEFORE the build, fixing defects while keeping masters
interpolation-compatible (per-master operations that preserve point structure):

  * Height: for letters/figures that sit on the baseline, map every master's
    vertical box onto the default master's box, so the height is consistent
    across weights. Enabled by ``normalize.heights`` (default true).

The ``normalize.monotonicInk`` toggle is reserved for a future ink-monotonicity
pass; the current engine performs only the height normalization above, matching
the historical ``normalize_glyphs.py`` behaviour.

Run:  uv run python -m variable_gen.cli normalize --config <path> --style all
"""

from __future__ import annotations

import glyphsLib
from fontTools.pens.areaPen import AreaPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

from variable_gen.config import ProjectConfig, Style, load_config

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


def normalize_style(config: ProjectConfig, style_key: str) -> dict:
    """Height-normalize one style's source in place. Mirrors
    ``normalize_glyphs.normalize_family`` exactly, config-driven."""
    if not config.normalize.get("heights", True):
        return {"style": style_key, "vertical_normalized": 0, "skipped": True}

    style = config.styles[style_key]
    default_pos = config.axes[0].default

    rep = TTFont(str(_first_donor_path(config, style)))
    cmap_rev = {v: k for k, v in rep.getBestCmap().items()}

    font = glyphsLib.load(open(style.source))
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

        boxes = {}
        for mid, layer in layers.items():
            m = layer_metrics(layer)
            if m is None or m[1] is None:
                boxes = None
                break
            boxes[mid] = (m[1], m[2])
        if not boxes:
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
    return {"style": style_key, "vertical_normalized": n_fixed}


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, help="path to stv.config.json")
    ap.add_argument("--style", default="all", help="style key, or 'all'")
    args = ap.parse_args()

    config = load_config(args.config)
    keys = list(config.styles) if args.style == "all" else [args.style]
    if args.style != "all" and args.style not in config.styles:
        raise SystemExit(f"unknown style {args.style!r}; have {sorted(config.styles)}")
    for key in keys:
        r = normalize_style(config, key)
        if r.get("skipped"):
            print(f"[{key}] height normalization disabled (normalize.heights=false)")
        else:
            print(
                f"[{key}] vertical-normalized {r['vertical_normalized']} glyphs "
                f"(aligned to the default master's box)"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
