#!/usr/bin/env python3
"""Config-driven master rebuild for a static-to-variable project.

This is the generic form of the historical ``rebuild_8master.py``: it reproduces
that script's ``rebuild_family`` byte for byte, but sources every input from a v3
``ProjectConfig`` instead of the hardcoded ``PLANS`` literal. For each style it

  * rebuilds the ordered masters from their donor fonts at their axis positions,
  * adopts the config's vertical metrics (falling back to the default master's
    donor when the config omits them),
  * applies per-glyph strategies (``open_bar`` / ``freeze``) in place of the old
    hardcoded ``OPEN_BAR_GLYPHS`` table, and
  * samples any non-donor glyph's prior interpolation from ``style.baseSource``
    (a project with no prior source simply omits it; those glyphs then freeze).

The heavy geometry (donor reconstruction, open-bar synthesis) still lives in the
pipeline scripts; this module imports those pure helpers rather than duplicating
them. It writes the same ``reports/reconstruction-report.json`` the script does.

Run:  uv run python -m variable_gen.cli rebuild --config <path> --style all|<name>
Then: uv run python -m variable_gen.cli build --config <path> --style all
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import glyphsLib
from fontTools.ttLib import TTFont
from glyphsLib.classes import GSFontMaster, GSLayer

from variable_gen import reconstruct_compatible as rc
from variable_gen.config import ProjectConfig, Style
from variable_gen.outlines import Contour, donor_outline, draw_into
from variable_gen.reconstruct_compatible import (
    _interp_ok,
    _struct_ok,
    open_bar,
    reconstruct,
)


@dataclass
class RebuildStats:
    """Per-style outcome counts for one ``rebuild_style`` run.

    ``glyphs`` maps every glyph to its outcome (``donor`` / ``reconstructed`` /
    ``sampled`` / ``frozen`` / ``ai_pending``) so downstream gates — the
    residual validator above all — can tell which glyphs carry one constant
    outline across masters without re-deriving it from the source.
    """

    donor: int = 0
    reconstructed: int = 0
    sampled: int = 0
    frozen: int = 0
    ai_pending: list[str] = field(default_factory=list)
    glyphs: dict[str, str] = field(default_factory=dict)


# Vertical metrics + italic angle carried from the source template onto each
# rebuilt master (the family metrics overwrite the first four downstream).
METRIC_ATTRS = ("ascender", "descender", "capHeight", "xHeight", "italicAngle")


def make_master(template, name, pos, mid):
    """Build a GSFontMaster at axis position ``pos`` from a template master."""
    m = GSFontMaster()
    m.name, m.id, m.axes = name, mid, [pos]
    for a in METRIC_ATTRS:
        if hasattr(template, a):
            setattr(m, a, getattr(template, a))
    return m


def lerp_outline(a, b, t):
    """Interpolate two compatible (op, [pts]) contour lists."""
    out = []
    for ca, cb in zip(a, b, strict=False):
        nc = []
        for (op, pa), (_, pb) in zip(ca, cb, strict=False):
            nc.append(
                (
                    op,
                    [
                        (pa[i][0] + (pb[i][0] - pa[i][0]) * t, pa[i][1] + (pb[i][1] - pa[i][1]) * t)
                        for i in range(len(pa))
                    ],
                )
            )
        out.append(nc)
    return out


def layer_outline(layer):
    """Read a GSLayer's contours as (op, [pts]) for sampling/interpolation."""
    from fontTools.pens.recordingPen import RecordingPen

    pen = RecordingPen()
    layer.draw(pen)
    contours: list[Contour] = []
    cur: Contour = []
    for op, args in pen.value:
        if op == "moveTo":
            cur = [("moveTo", [tuple(args[0])])]
        elif op == "lineTo":
            cur.append(("lineTo", [tuple(args[0])]))
        elif op in ("curveTo", "qCurveTo"):
            cur.append((op, [tuple(p) for p in args]))
        elif op in ("closePath", "endPath"):
            cur.append((op, []))
            contours.append(cur)
            cur = []
    return contours, layer.width


def _int_if_whole(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value


def _style_plan(config: ProjectConfig, style: Style) -> list[tuple[str, Path, int | float]]:
    """Ordered (master name, donor .otf path, axis position) — the config form of
    ``PLANS[family]["masters"]``. Position uses the first (primary) axis."""
    tag = config.axes[0].tag
    donor_by_id = {donor.id: donor for donor in style.donors}
    return [
        (master.name, donor_by_id[master.donor_id].path, _int_if_whole(master.location[tag]))
        for master in style.masters
    ]


def _vertical_metrics(config: ProjectConfig, default_donor_path: Path) -> dict[str, int | float]:
    """Config vertical metrics, or — when absent — the default master's donor
    OS/2 + head metrics, so a generic project inherits its base weight's shape."""
    vm = config.vertical_metrics
    if vm is not None:
        return {
            "ascender": _int_if_whole(vm.ascender),
            "descender": _int_if_whole(vm.descender),
            "capHeight": _int_if_whole(vm.cap_height),
            "xHeight": _int_if_whole(vm.x_height),
        }
    donor = TTFont(str(default_donor_path))
    os2 = donor["OS/2"]
    return {
        "ascender": os2.sTypoAscender,
        "descender": os2.sTypoDescender,
        "capHeight": os2.sCapHeight,
        "xHeight": os2.sxHeight,
    }


def rebuild_style(config: ProjectConfig, style_key: str) -> RebuildStats:
    """Rebuild one style's ``.glyphs`` source in place, returning reconstruction
    stats. Mirrors ``rebuild_8master.rebuild_family`` exactly, config-driven."""
    style = config.styles[style_key]
    # A from-scratch project ships no .glyphs source; synthesize a minimal one
    # (glyph set + one template master) from the default-master donor so the
    # rebuild below can re-derive every master from the donors as usual.
    from variable_gen.bootstrap import ensure_source

    ensure_source(config, style_key)
    plan = _style_plan(config, style)
    donors = {name: TTFont(str(path)).getGlyphSet() for name, path, _ in plan}
    pos_by_name = {name: pos for name, _, pos in plan}

    default_master = next(m for m in style.masters if m.default)
    default_name = default_master.name
    reference_pos = pos_by_name[default_name]

    # per-glyph strategy table (config form of OPEN_BAR_GLYPHS + friends)
    strategies = config.glyphs.strategies

    # Source uses friendly names (rcommaaccent), donors use uniXXXX — resolve the
    # donor glyph name by codepoint when the source name isn't present in donors.
    rep = TTFont(str(plan[0][1]))
    donor_order = set(rep.getGlyphOrder())
    donor_cmap = rep.getBestCmap()

    def donor_name_for(glyph):
        if glyph.name in donor_order:
            return glyph.name
        uni = glyph.unicode
        if uni:
            cp = int(uni, 16) if isinstance(uni, str) else uni
            return donor_cmap.get(cp)
        return None

    with open(style.source) as source_file:
        font = glyphsLib.load(source_file)
    base_glyphs: dict = {}
    base_mids: dict = {}
    if style.base_source is not None:
        # prior source, for sampling
        with open(style.base_source) as base_file:
            base = glyphsLib.load(base_file)
        base_glyphs = {g.name: g for g in base.glyphs}
        base_mids = {m.id: m.axes[0] for m in base.masters}

    template = font.masters[0]
    ids = {name: f"{config.id}-{style_key}-{name}" for name, _, _ in plan}
    font.masters = [make_master(template, name, pos, ids[name]) for name, _, pos in plan]
    default_donor_path = next(path for name, path, _ in plan if name == default_name)
    metrics = _vertical_metrics(config, default_donor_path)
    for m in font.masters:  # adopt the family's vertical metrics
        for attr, val in metrics.items():
            setattr(m, attr, val)
    font.instances = []

    stats = RebuildStats()
    for glyph in font.glyphs:
        strat = strategies.get(glyph.name)

        # freeze strategy: pin the glyph to the default master's donor outline
        # across every master (constant -> never collapses, never varies).
        if strat is not None and strat.strategy == "freeze":
            reg = donor_outline(donors[default_name], donor_name_for(glyph))
            if reg is not None:
                glyph.layers = []
                for name, _, _ in plan:
                    layer = GSLayer()
                    layer.layerId = layer.associatedMasterId = ids[name]
                    glyph.layers.append(layer)
                    draw_into(layer, reg[0])
                    layer.width = reg[1]
                stats.frozen += 1
                stats.glyphs[glyph.name] = "frozen"
                continue

        dn = donor_name_for(glyph)
        maybe_outlines = {
            name: (donor_outline(donors[name], dn) if dn else None) for name, _, _ in plan
        }
        outlines = {name: o for name, o in maybe_outlines.items() if o is not None}
        in_donors = len(outlines) == len(plan)

        if in_donors:
            out8 = {name: outlines[name] for name, _, _ in plan}
            # Open-bar design change: $ / ¢ keep only the TOP and BOTTOM bar stubs
            # (no through-middle). Body = the bare letter (S/c) donor; bar = two
            # nubs. Built directly (bypasses the donor area gate — intentionally
            # not the donor shape). Falls through to the normal path if it fails.
            if strat is not None and strat.strategy == "open_bar":
                letter = strat.params["letter"]
                anchor = strat.params["anchor"]
                rc.NUB_OVERLAP = strat.params.get("nubOverlap", rc.NUB_OVERLAP)
                rc.MIN_PROTRUDE = strat.params.get("minProtrude", rc.MIN_PROTRUDE)
                letter_o = {
                    pos_by_name[name]: donor_outline(donors[name], letter)[0]
                    for name, _, _ in plan
                    if donor_outline(donors[name], letter) is not None
                }
                glyph_o = {pos_by_name[name]: outlines[name][0] for name, _, _ in plan}
                if len(letter_o) == len(plan):
                    bf = open_bar(glyph_o, letter_o, anchor, reference_pos=reference_pos)
                    if bf is not None and _struct_ok(bf) and _interp_ok(bf):
                        glyph.layers = []
                        for name, _, _ in plan:
                            layer = GSLayer()
                            layer.layerId = layer.associatedMasterId = ids[name]
                            glyph.layers.append(layer)
                            draw_into(layer, bf[pos_by_name[name]])
                            layer.width = outlines[name][1]
                        stats.reconstructed += 1
                        stats.donor += 1
                        stats.glyphs[glyph.name] = "reconstructed"
                        continue
            # Independent statics aren't interpolation-compatible. ALWAYS run
            # reconstruct(): it returns the donor outlines unchanged when they
            # truly interpolate, and reconstructs to a shared structure otherwise.
            # If it can't reconcile the glyph (genuine topology change), leave the
            # donor outlines and flag for freeze.
            pos_outlines = {pos_by_name[name]: outlines[name][0] for name, _, _ in plan}
            rec, info = reconstruct(pos_outlines, reference_pos=reference_pos)
            if rec is not None:
                out8 = {name: (rec[pos_by_name[name]], outlines[name][1]) for name, _, _ in plan}
                if info["stage"] == "reconstructed":
                    stats.reconstructed += 1
                    stats.glyphs[glyph.name] = "reconstructed"
                else:
                    stats.glyphs[glyph.name] = "donor"
            else:
                # reconstruct can't make it interpolate cleanly. Freeze to the
                # default-master donor (constant across masters) so it renders
                # correctly and never collapses; it just won't vary in weight.
                reg = outlines[default_name]
                out8 = {name: reg for name, _, _ in plan}
                stats.ai_pending.append(glyph.name)
                stats.glyphs[glyph.name] = "ai_pending"
            glyph.layers = []
            for name, _, _ in plan:
                layer = GSLayer()
                layer.layerId = layer.associatedMasterId = ids[name]
                glyph.layers.append(layer)
                draw_into(layer, out8[name][0])
                layer.width = out8[name][1]
            stats.donor += 1
            continue

        # not in donors — sample the glyph's prior interpolation from base_source
        bg = base_glyphs.get(glyph.name)
        old = {}
        if bg:
            for layer in bg.layers:
                if layer.layerId in base_mids:
                    old[base_mids[layer.layerId]] = layer_outline(layer)
        if len(old) >= 2:
            old_positions = sorted(old)
            glyph.layers = []
            ok = True
            for name, _, _ in plan:
                p = pos_by_name[name]
                lows = [q for q in old_positions if q <= p] or [old_positions[0]]
                highs = [q for q in old_positions if q >= p] or [old_positions[-1]]
                a, b = max(lows), min(highs)
                try:
                    if a == b:
                        contours, width = old[a]
                    else:
                        t = (p - a) / (b - a)
                        contours = lerp_outline(old[a][0], old[b][0], t)
                        width = old[a][1] + (old[b][1] - old[a][1]) * t
                    layer = GSLayer()
                    layer.layerId = layer.associatedMasterId = ids[name]
                    glyph.layers.append(layer)
                    draw_into(layer, contours)
                    layer.width = width
                except Exception as exc:  # noqa: BLE001 — fall back to freeze below
                    print(
                        f"[{style_key}] sampling {glyph.name} from base source failed"
                        f" at {name}: {exc} — freezing",
                        file=sys.stderr,
                    )
                    ok = False
                    break
            if ok and len(glyph.layers) == len(plan):
                stats.sampled += 1
                stats.glyphs[glyph.name] = "sampled"
                continue

        # last resort: freeze to whatever single outline we can (keeps build valid)
        ref = old[sorted(old)[len(old) // 2]] if old else (([], 0))
        glyph.layers = []
        for name, _, _ in plan:
            layer = GSLayer()
            layer.layerId = layer.associatedMasterId = ids[name]
            glyph.layers.append(layer)
            draw_into(layer, ref[0])
            layer.width = ref[1]
        stats.frozen += 1
        stats.glyphs[glyph.name] = "frozen"

    font.save(str(style.source))
    return stats


def main(argv: list[str] | None = None) -> int:
    """Thin wrapper: ``python -m variable_gen.rebuild`` == ``variable-gen rebuild``."""
    from variable_gen.cli import run_command

    return run_command("rebuild", argv)


if __name__ == "__main__":
    raise SystemExit(main())
