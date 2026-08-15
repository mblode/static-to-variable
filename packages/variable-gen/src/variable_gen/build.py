#!/usr/bin/env python3
"""Config-driven variable-font build + per-weight fidelity check.

Exports the designspace (via :mod:`variable_gen.designspace`), runs fontmake, and repeats a
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
import json
import re
import subprocess
import sys
from pathlib import Path

import glyphsLib
import pathops
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

from variable_gen.common import PipelineError, fontmake_command, merge_style_report
from variable_gen.config import ProjectConfig, Style, default_donor_path
from variable_gen.designspace import export_designspace
from variable_gen.outlines import donor_outline, draw_into

UNDERWEIGHT_RATIO = 0.92


def _run(cmd, repo_root: Path):
    return subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)


def _positions(style: Style) -> list[int | float]:
    tag = _axis_tag(style)
    return sorted({m.location[tag] for m in style.masters})


def _master_rows(style: Style) -> list[list[dict[str, float]]]:
    """Masters grouped by every axis except the primary, each row sorted by it."""
    tag = _axis_tag(style)
    rows: dict[tuple, list[dict[str, float]]] = {}
    for master in style.masters:
        extra = tuple(sorted((key, master.location[key]) for key in master.location if key != tag))
        rows.setdefault(extra, []).append(dict(master.location))
    return [sorted(row, key=lambda loc: loc[tag]) for row in rows.values()]


def _axis_tag(style: Style) -> str:
    # Weight is the interpolating axis reconstruct and kerning already assume.
    # Location dicts are sorted alphabetically, so opsz would otherwise win.
    loc = style.masters[0].location
    if "wght" in loc:
        return "wght"
    return next(iter(loc))


def freeze_to_book(config: ProjectConfig, style_key: str, names) -> None:
    """Freeze weight interpolation without erasing other-axis variation.

    Every optical row is pinned to its own default-weight donor. This keeps a
    collapsed glyph safe along ``wght`` while preserving intentional Text/UI/
    Display differences. If those row drawings are incompatible, fontmake's
    next pass reports the glyph by name instead of silently replacing all rows
    with the global default outline.
    """
    style = config.styles[style_key]
    primary_tag = _axis_tag(style)
    primary_default = next(axis.default for axis in config.axes if axis.tag == primary_tag)
    donor_by_id = {donor.id: donor for donor in style.donors}
    rows: dict[tuple[tuple[str, float], ...], list] = {}
    for master in style.masters:
        extra = tuple(
            (axis.tag, master.location[axis.tag]) for axis in config.axes if axis.tag != primary_tag
        )
        rows.setdefault(extra, []).append(master)
    row_defaults = {}
    for extra, masters in rows.items():
        row_default = next(
            (master for master in masters if master.location[primary_tag] == primary_default),
            None,
        )
        if row_default is None:
            coords = ", ".join(f"{tag}={value:g}" for tag, value in extra) or "default row"
            raise PipelineError(
                f"[{style_key}] cannot freeze row {coords}: no master at "
                f"{primary_tag}={primary_default:g}"
            )
        glyph_set = TTFont(str(donor_by_id[row_default.donor_id].path)).getGlyphSet()
        for master in masters:
            row_defaults[master.name] = glyph_set

    with open(style.source) as source_file:
        font = glyphsLib.load(source_file)
    glyph_set_by_id = {
        master.id: row_defaults[master.name]
        for master in font.masters
        if master.name in row_defaults
    }
    by = {g.name: g for g in font.glyphs}
    for nm in names:
        glyph = by.get(nm)
        if glyph is None:
            continue
        for layer in glyph.layers:
            glyph_set = glyph_set_by_id.get(layer.layerId)
            if glyph_set is None:
                continue
            outline = donor_outline(glyph_set, nm)
            if outline is None:
                continue
            draw_into(layer, outline[0])
            layer.width = outline[1]
    font.save(str(style.source))


def layout_report_path(config: ProjectConfig) -> Path:
    return config.repo_root / "packages/variable-gen/reports/layout-report.json"


def _write_layout_report(config: ProjectConfig, style_key: str, layout, hinting) -> None:
    """Record what survived of the donor's layout, for the promotion gate."""
    from variable_gen.layout_report import build_layout_report

    style = config.styles[style_key]
    donor_by_id = {d.id: d for d in style.donors}
    entry = build_layout_report(
        style.output,
        [donor_by_id[m.donor_id].path for m in style.masters],
        default_donor=default_donor_path(style),
        layout=layout,
        hinting=hinting,
    )
    path = layout_report_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = merge_style_report(path, {style_key: entry}, list(config.styles))
    path.write_text(json.dumps(merged, indent=2) + "\n")


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
                # keep the donors' own glyph names (ufo2ft would rename to
                # production names, e.g. Gcommaaccent -> uni0122, and the
                # layout port then loses every unencoded glyph's lookups)
                "--no-production-names",
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
            from variable_gen.hinting import apply_hinting
            from variable_gen.layout import attach_layout
            from variable_gen.release import fix_instances

            vf = TTFont(str(out))
            fix_instances(vf, config, style.italic)
            # .glyphs carries outlines only — attach layout from donors
            # (variable merge when possible, else static default-master port).
            donor_by_id = {d.id: d for d in style.donors}
            master_donors = [
                (donor_by_id[m.donor_id].path, dict(m.location)) for m in style.masters
            ]
            axis = _axis_tag(style)
            axis_name = next(
                (a.name for a in config.axes if a.tag == axis),
                "Weight",
            )
            layout = attach_layout(
                vf,
                master_donors,
                default_donor=default_donor_path(style),
                axis_tag=axis,
                axis_name=axis_name,
            )
            # After the layout tiers: their merge path deletes the hinting
            # tables from the instances it builds, so anything added earlier
            # would not survive.
            hinting = apply_hinting(vf, config.output.hinting)
            vf.save(str(out))
            _write_layout_report(config, style_key, layout, hinting)
            print(
                f"[{style_key}] built (frozen: {frozen}; {layout.summary()}; {hinting.summary()})"
            )
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
    bad = []
    for row in _master_rows(style):
        extras = {key: value for key, value in row[0].items() if key != tag}
        weights = [loc[tag] for loc in row]
        pairs = list(zip(weights, weights[1:], strict=False))
        points = sorted(set(weights) | {(a + b) / 2 for a, b in pairs})
        inst = {
            w: instantiateVariableFont(
                copy.deepcopy(vf), {tag: w, **extras}, inplace=False
            ).getGlyphSet()
            for w in points
        }
        for g in vf.getGlyphOrder():
            if g == ".notdef" or g in bad:
                continue
            for a, b in pairs:
                mid = (a + b) / 2
                aa, ab, am = _area(inst[a], g), _area(inst[b], g), _area(inst[mid], g)
                if not aa or not ab or am is None:
                    continue
                mean = (aa + ab) / 2
                if mean > 800 and abs(am / mean - 1.0) > tol:
                    bad.append(g)
                    break
    return bad


def check_fidelity(
    config: ProjectConfig,
    style_key: str,
    extra_skip: list[str] | tuple[str, ...] = (),
):
    style = config.styles[style_key]
    donor_by_id = {d.id: d for d in style.donors}
    # open_bar intentionally removes the through-bar, so instance area is below
    # the closed-bar donor — skip those glyphs rather than false-fail fidelity.
    # Frozen glyphs pin to the default master, so non-default weights diverge.
    skip_glyphs = set(config.glyphs.freeze)
    skip_glyphs.update(extra_skip)
    for name, strat in config.glyphs.strategies.items():
        if strat.strategy in {"open_bar", "freeze"}:
            skip_glyphs.add(name)
    vf = TTFont(str(style.output))
    master_locs = [dict(master.location) for master in style.masters]
    instances = [
        instantiateVariableFont(copy.deepcopy(vf), loc, inplace=False).getGlyphSet()
        for loc in master_locs
    ]
    instances_by_location = list(zip(master_locs, instances, strict=True))
    for glyph_name in vf.getGlyphOrder():
        constant_in_every_row = True
        for row in _master_rows(style):
            row_areas = [
                area
                for location, glyph_set in instances_by_location
                if location in row
                for area in [_area(glyph_set, glyph_name)]
                if area
            ]
            if len(row_areas) >= 2 and max(row_areas) > min(row_areas) * 1.02:
                constant_in_every_row = False
                break
        if constant_in_every_row:
            skip_glyphs.add(glyph_name)
    fails = []
    for master, gi in zip(style.masters, instances, strict=True):
        location = ",".join(f"{axis.tag}={master.location[axis.tag]:g}" for axis in config.axes)
        donor = TTFont(str(donor_by_id[master.donor_id].path))
        gd = donor.getGlyphSet()
        for g in vf.getGlyphOrder():
            if g == ".notdef" or g not in gd or g in skip_glyphs:
                continue
            ai = _area(gi, g)
            ad = _area(gd, g)
            if ai and ad and ad > 1000 and ai / ad < UNDERWEIGHT_RATIO:
                fails.append((location, g, round(ai / ad, 2)))
    return fails


def _area(gs, n):
    """Return rendered ink area after applying the outline's nonzero fill.

    ``AreaPen`` sums contour areas, which double-counts same-winding overlaps.
    Reconstructed masters deliberately remove those overlaps, so comparing the
    raw sums makes an identical rendered shape look underweight.  Simplifying
    with pathops first measures the union the rasterizer actually fills while
    retaining the existing fidelity threshold.
    """
    if n not in gs:
        return None
    try:
        recording = DecomposingRecordingPen(gs)
        gs[n].draw(recording)
        path = pathops.Path()
        recording.replay(path.getPen())
        path.simplify()
    except Exception:  # noqa: BLE001
        return None
    return abs(path.area)


def main(argv: list[str] | None = None) -> int:
    """Thin wrapper: ``python -m variable_gen.build`` == ``variable-gen build``."""
    from variable_gen.cli import run_command

    return run_command("build", argv)


if __name__ == "__main__":
    raise SystemExit(main())
