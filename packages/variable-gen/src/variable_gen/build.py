#!/usr/bin/env python3
"""Config-driven variable-font build + per-weight fidelity check.

This is the generic form of the historical ``build_glide.py``: it exports the
designspace (via :mod:`variable_gen.designspace`), runs fontmake, and repeats a
freeze loop that pins any cu2qu-incompatible or interpolation-collapsing glyph to
the default master's donor before rebuilding, then verifies that every named
weight matches its mapped donor. Every input (masters, donor paths, output paths)
comes from a v3 ``ProjectConfig`` instead of the hardcoded ``PLANS``/``BUILD``
literals.

The freeze behaviour is preserved exactly (parity depends on it): the loop
detects glyphs that collapse at master-pair midpoints in the BUILT VF, freezes
them to the default-master donor (constant -> can't collapse), and rebuilds.

Run:  uv run python -m variable_gen.cli build --config <path> --style all
"""

from __future__ import annotations

import copy
import re
import subprocess
import sys
from pathlib import Path

import glyphsLib
from fontTools.pens.areaPen import AreaPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

from variable_gen.common import PipelineError, fontmake_command
from variable_gen.config import ProjectConfig, Style, default_donor_path
from variable_gen.designspace import export_designspace
from variable_gen.outlines import donor_outline, draw_into

UNDERWEIGHT_RATIO = 0.92


def _run(cmd, repo_root: Path):
    return subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)


def _positions(style: Style) -> list[int | float]:
    tag = _axis_tag(style)
    return sorted(m.location[tag] for m in style.masters)


def _axis_tag(style: Style) -> str:
    # every master shares the same axis tags; use the first master's
    return next(iter(style.masters[0].location))


def freeze_to_book(config: ProjectConfig, style_key: str, names) -> None:
    """Pin the named glyphs to the default master's donor outline across every
    master (constant -> can't collapse). Mirrors ``build_glide.freeze_to_book``."""
    style = config.styles[style_key]
    book = TTFont(str(default_donor_path(style))).getGlyphSet()
    with open(style.source) as source_file:
        font = glyphsLib.load(source_file)
    ids = [m.id for m in font.masters]
    by = {g.name: g for g in font.glyphs}
    for nm in names:
        g, o = by.get(nm), donor_outline(book, nm)
        if not g or o is None:
            continue
        for layer in g.layers:
            if layer.layerId in ids:
                draw_into(layer, o[0])
                layer.width = o[1]
    font.save(str(style.source))


def build_style(config: ProjectConfig, style_key: str) -> list[str]:
    style = config.styles[style_key]
    # From-scratch project: no .glyphs source means no masters to interpolate.
    # Bootstrap + rebuild first (re-derives every master from the donors) so a
    # bare `build` produces a real multi-master variable font in one shot.
    if not style.source.exists():
        from variable_gen.rebuild import rebuild_style

        print(f"[{style_key}] no source at {style.source} — bootstrapping + rebuilding from donors")
        rebuild_style(config, style_key)
    fontmake = fontmake_command(config.repo_root)
    out = style.output
    out.parent.mkdir(parents=True, exist_ok=True)
    frozen: list[str] = []
    for _ in range(40):
        ds_path = export_designspace(config, style_key)
        p = _run(
            [
                fontmake,
                "-m",
                str(ds_path),
                "-o",
                "variable",
                "--keep-overlaps",
                "--output-path",
                str(out),
            ],
            config.repo_root,
        )
        if p.returncode == 0:
            # The build SUCCEEDED structurally, but the glyphsLib/cu2qu round-trip
            # can still leave complex glyphs that COLLAPSE at interpolated weights.
            # Detect them in the actual VF and freeze to the default donor, rebuild.
            collapsed = [g for g in _collapsing_glyphs(config, style_key) if g not in frozen]
            if collapsed:
                frozen += collapsed
                freeze_to_book(config, style_key, collapsed)
                continue
            # fontmake leaves the default instance's fvar subfamily name empty
            # (its elidable "Regular" label collapses to ""), so repair instance
            # names in the build artifact too, not just at release time.
            from variable_gen.release import fix_instances

            vf = TTFont(str(out))
            fix_instances(vf, config, style.italic)
            vf.save(str(out))
            print(f"[{style_key}] built (frozen: {frozen})")
            return frozen
        err = p.stdout + p.stderr
        names = (
            set(re.findall(r"Glyphs? (?:named )?'([^']+)'", err))
            | set(re.findall(r"incompatible glyphs: '([^']+)'", err))
            | set(re.findall(r"in glyph (\S+?),", err))
            | set(re.findall(r"in glyph (\S+?):", err))
        )
        fresh = [n for n in names if n not in frozen]
        if not fresh:
            sys.stderr.write(err[-2000:])
            raise PipelineError(f"[{style_key}] build failed, no glyph parsed")
        frozen += fresh
        freeze_to_book(config, style_key, fresh)
    raise PipelineError(f"[{style_key}] freeze loop did not converge")


def _collapsing_glyphs(config: ProjectConfig, style_key: str, tol=0.22) -> list[str]:
    """Glyphs whose ink area collapses at a master-pair midpoint in the BUILT VF."""
    style = config.styles[style_key]
    tag = _axis_tag(style)
    vf = TTFont(str(style.output))
    masters = _positions(style)
    pairs = list(zip(masters, masters[1:], strict=False))
    weights = sorted(set(masters) | {(a + b) / 2 for a, b in pairs})
    inst = {
        w: instantiateVariableFont(copy.deepcopy(vf), {tag: w}, inplace=False).getGlyphSet()
        for w in weights
    }
    bad = []
    for g in vf.getGlyphOrder():
        if g == ".notdef":
            continue
        for a, b in pairs:
            m = (a + b) / 2
            aa, ab, am = _area(inst[a], g), _area(inst[b], g), _area(inst[m], g)
            if not aa or not ab or am is None:
                continue
            mean = (aa + ab) / 2
            if mean > 800 and abs(am / mean - 1.0) > tol:
                bad.append(g)
                break
    return bad


def check_fidelity(config: ProjectConfig, style_key: str):
    style = config.styles[style_key]
    tag = _axis_tag(style)
    donor_by_id = {d.id: d for d in style.donors}
    vf = TTFont(str(style.output))
    fails = []
    for master in style.masters:
        pos = master.location[tag]
        donor = TTFont(str(donor_by_id[master.donor_id].path))
        gd = donor.getGlyphSet()
        gi = instantiateVariableFont(copy.deepcopy(vf), {tag: pos}, inplace=False).getGlyphSet()
        for g in vf.getGlyphOrder():
            if g == ".notdef" or g not in gd:
                continue
            ai = _area(gi, g)
            ad = _area(gd, g)
            if ai and ad and ad > 1000 and ai / ad < UNDERWEIGHT_RATIO:
                fails.append((pos, g, round(ai / ad, 2)))
    return fails


def _area(gs, n):
    if n not in gs:
        return None
    pen = AreaPen(gs)
    try:
        gs[n].draw(pen)
    except Exception:  # noqa: BLE001
        return None
    return abs(pen.value)


def main(argv: list[str] | None = None) -> int:
    """Thin wrapper: ``python -m variable_gen.build`` == ``variable-gen build``."""
    from variable_gen.cli import run_command

    return run_command("build", argv)


if __name__ == "__main__":
    raise SystemExit(main())
