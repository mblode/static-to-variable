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

import os
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import glyphsLib
from fontTools.ttLib import TTFont
from glyphsLib.classes import GSAxis, GSFontMaster, GSLayer

from variable_gen import reconstruct_compatible as rc
from variable_gen.common import PipelineError
from variable_gen.config import ProjectConfig, Style
from variable_gen.outlines import Contour, donor_outline, draw_into
from variable_gen.reconstruct_compatible import (
    _interp_ok,
    _struct_ok,
    open_bar,
    reconstruct,
    union_overlaps,
)


@dataclass
class RebuildStats:
    """Per-style outcome counts for one ``rebuild_style`` run.

    ``glyphs`` maps every glyph to its outcome (``donor`` / ``reconstructed`` /
    ``sampled`` / ``frozen`` / ``frozen_incompatible``) so downstream gates — the
    residual validator above all — can tell which glyphs carry one constant
    outline across masters without re-deriving it from the source.
    """

    donor: int = 0
    reconstructed: int = 0
    sampled: int = 0
    frozen: int = 0
    frozen_incompatible: list[str] = field(default_factory=list)
    glyphs: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, order=True)
class AxisLocation:
    """Hashable, ordered axis coordinates used throughout multi-axis rebuilds.

    The old rebuild plan smuggled an optical-size row into a numeric weight by
    adding ``10_000``.  Besides imposing an undocumented coordinate limit, that
    made a real two-axis location indistinguishable from an invented 1D point.
    Keeping the axis tags attached to their values makes row grouping explicit
    and prevents locations from colliding when another axis is added.
    """

    values: tuple[tuple[str, float], ...]

    @classmethod
    def from_mapping(cls, location: dict[str, float], axis_tags: list[str]) -> AxisLocation:
        return cls(tuple((tag, float(location[tag])) for tag in axis_tags))

    @classmethod
    def from_values(cls, axis_tags: list[str], values: list[float]) -> AxisLocation:
        return cls(tuple((tag, float(value)) for tag, value in zip(axis_tags, values, strict=True)))

    def __getitem__(self, tag: str) -> float:
        for axis_tag, value in self.values:
            if axis_tag == tag:
                return value
        raise KeyError(tag)

    def without(self, tag: str) -> AxisLocation:
        return AxisLocation(tuple(item for item in self.values if item[0] != tag))

    def as_dict(self) -> dict[str, float]:
        return dict(self.values)

    def describe(self) -> str:
        return ", ".join(f"{tag}={value:g}" for tag, value in self.values) or "default row"


@dataclass(frozen=True)
class PlanMaster:
    name: str
    donor_path: Path
    location: AxisLocation


@dataclass(frozen=True)
class ReconstructionRow:
    location: AxisLocation
    masters: tuple[PlanMaster, ...]


# Vertical metrics + italic angle carried from the source template onto each
# rebuilt master (the family metrics overwrite the first four downstream).
METRIC_ATTRS = ("ascender", "descender", "capHeight", "xHeight", "italicAngle")


def make_master(template, name, pos, mid):
    """Build a GSFontMaster at axis position ``pos`` from a template master.

    ``pos`` is a number (one axis) or a list of numbers (one per config axis).
    """
    m = GSFontMaster()
    m.name, m.id, m.axes = name, mid, pos if isinstance(pos, list) else [pos]
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


def _style_plan(config: ProjectConfig, style: Style) -> list[PlanMaster]:
    """Ordered masters with their complete, tagged design-space locations."""
    tags = [axis.tag for axis in config.axes]
    donor_by_id = {donor.id: donor for donor in style.donors}
    return [
        PlanMaster(
            name=master.name,
            donor_path=donor_by_id[master.donor_id].path,
            location=AxisLocation.from_mapping(master.location, tags),
        )
        for master in style.masters
    ]


def _plan_groups(plan: list[PlanMaster], primary_tag: str = "wght") -> list[ReconstructionRow]:
    """Group masters into explicit 1D rows along ``primary_tag``."""
    if plan and primary_tag not in dict(plan[0].location.values):
        primary_tag = plan[0].location.values[0][0]
    groups: dict[AxisLocation, list[PlanMaster]] = {}
    for master in plan:
        groups.setdefault(master.location.without(primary_tag), []).append(master)
    return [
        ReconstructionRow(
            location=location,
            masters=tuple(sorted(masters, key=lambda item: item.location[primary_tag])),
        )
        for location, masters in sorted(groups.items())
    ]


def _outline_signature(contours) -> tuple:
    """The interpolation-relevant operations and point counts of an outline."""
    return tuple(tuple((op, len(points)) for op, points in contour) for contour in contours)


def _raise_row_topology_error(failures: dict[str, list[str]]) -> None:
    if not failures:
        return
    lines = ["multi-axis reconstruction produced incompatible optical rows:"]
    for glyph_name in sorted(failures):
        lines.append(f"  {glyph_name}: {'; '.join(failures[glyph_name])}")
    raise PipelineError("\n".join(lines))


def _check_row_signatures(
    name: str,
    outlines: dict[AxisLocation, list],
    rows: list[ReconstructionRow],
    primary_tag: str,
    reference_location: AxisLocation,
) -> None:
    if len(rows) < 2:
        return
    details = _row_signature_details(outlines, rows, primary_tag, reference_location)
    if details is not None:
        _raise_row_topology_error({name: [details]})


def _row_signature_details(
    outlines: dict[AxisLocation, list],
    rows: list[ReconstructionRow],
    primary_tag: str,
    reference_location: AxisLocation,
) -> str | None:
    row_signatures: dict[AxisLocation, tuple] = {}
    for row in rows:
        row_master = min(
            row.masters,
            key=lambda item: abs(item.location[primary_tag] - reference_location[primary_tag]),
        )
        outline = outlines.get(row_master.location)
        if outline is not None:
            row_signatures[row.location] = _outline_signature(outline)
    if len(set(row_signatures.values())) <= 1:
        return None
    return ", ".join(
        f"{location.describe()} signature={signature!r}"
        for location, signature in row_signatures.items()
    )


def reconstruct_plan(
    donor_outlines: dict[str, dict],
    plan: list[PlanMaster],
    primary_tag: str,
    reference_location: AxisLocation,
    workers: int,
) -> dict[str, tuple]:
    """Reconstruct each optical-size row independently, then merge.

    ``reconstruct`` is 1D. A 3×2 wght×opsz grid must not be fed in as six
    keys on one axis — that is both wrong and extremely slow.
    """
    merged_outlines: dict[str, dict[AxisLocation, list]] = {}
    merged_info: dict[str, list[dict]] = {}
    failures: dict[str, list[str]] = {}
    groups = _plan_groups(plan, primary_tag)
    for row in groups:
        jobs = {
            name: {master.location[primary_tag]: outs[master.name][0] for master in row.masters}
            for name, outs in donor_outlines.items()
        }
        part = reconstruct_all(jobs, reference_location[primary_tag], workers)
        for name, (rec, info) in part.items():
            merged_info.setdefault(name, []).append(info)
            if rec is None:
                failures.setdefault(name, []).append(
                    f"{row.location.describe()} could not be reconstructed "
                    f"({info.get('stage', 'unknown')})"
                )
                continue
            target = merged_outlines.setdefault(name, {})
            for master in row.masters:
                target[master.location] = rec[master.location[primary_tag]]

    if len(groups) > 1:
        for name, locations in merged_outlines.items():
            details = _row_signature_details(locations, groups, primary_tag, reference_location)
            if details is not None:
                failures.setdefault(name, []).append(details)
    _raise_row_topology_error(failures)

    result: dict[str, tuple] = {}
    for name, outlines in merged_outlines.items():
        infos = merged_info[name]
        stage = (
            "reconstructed"
            if any(info.get("stage") == "reconstructed" for info in infos)
            else "donor"
        )
        result[name] = (outlines, {"stage": stage, "rows": infos})
    return result


def _open_bar_rows(
    *,
    name: str,
    letter: str,
    anchor: str,
    donor_outlines: dict[str, dict],
    donors: dict[str, object],
    plan: list[PlanMaster],
    primary_tag: str,
    reference_location: AxisLocation,
) -> dict[AxisLocation, list] | None:
    """Apply the 1D open-bar synthesizer independently in every axis row."""
    rows = _plan_groups(plan, primary_tag)
    merged: dict[AxisLocation, list] = {}
    for row in rows:
        letter_outlines: dict[float, list] = {}
        glyph_outlines: dict[float, list] = {}
        for master in row.masters:
            donor_letter = donor_outline(donors[master.name], letter)
            if donor_letter is None:
                return None
            position = master.location[primary_tag]
            letter_outlines[position] = donor_letter[0]
            glyph_outlines[position] = donor_outlines[name][master.name][0]
        rebuilt = open_bar(
            glyph_outlines,
            letter_outlines,
            anchor,
            reference_pos=reference_location[primary_tag],
        )
        if rebuilt is None or not _struct_ok(rebuilt) or not _interp_ok(rebuilt):
            return None
        for master in row.masters:
            merged[master.location] = rebuilt[master.location[primary_tag]]
    _check_row_signatures(name, merged, rows, primary_tag, reference_location)
    return merged


def _master_axis_values(config: ProjectConfig, style: Style, name: str) -> list[int | float]:
    master = next(item for item in style.masters if item.name == name)
    return [_int_if_whole(master.location[axis.tag]) for axis in config.axes]


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


def reconstruct_workers(job_count: int) -> int:
    """How many processes to reconstruct with.

    ``STV_JOBS`` overrides (1 disables the pool, which keeps tracebacks readable
    when debugging a single glyph). Otherwise one per core, capped at the number
    of glyphs so a tiny font doesn't pay to spawn 8 interpreters.
    """
    override = os.environ.get("STV_JOBS")
    if override:
        try:
            requested = int(override)
        except ValueError:
            requested = 0
        if requested > 0:
            return min(requested, max(1, job_count))
    return max(1, min(os.cpu_count() or 1, job_count))


def reconstruct_all(jobs: dict[str, dict], reference_pos, workers: int) -> dict[str, tuple]:
    """``reconstruct`` every glyph's donor outlines, across processes.

    Reconstruction dominates the whole pipeline (measured in production: 35.6s of
    a 44.5s build) and it ran on a single core, which is what put real families
    out of reach of the build timeout. It is a pure function of plain coordinate
    lists with no shared state, so it parallelises exactly.

    Results are keyed by glyph name, so the caller applies them in the source's
    own order and the output is identical to the serial path.
    """
    if workers <= 1:
        return {name: reconstruct(o, reference_pos=reference_pos) for name, o in jobs.items()}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            name: pool.submit(reconstruct, outlines, reference_pos)
            for name, outlines in jobs.items()
        }
        return {name: future.result() for name, future in futures.items()}


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
    primary_tag = config.axes[0].tag
    donors = {master.name: TTFont(str(master.donor_path)).getGlyphSet() for master in plan}

    default_master = next(m for m in style.masters if m.default)
    default_name = default_master.name
    reference_location = next(master.location for master in plan if master.name == default_name)

    # per-glyph strategy table (config form of OPEN_BAR_GLYPHS + friends).
    # glyphs.freeze pins names to the default-master donor (implicit freeze).
    from variable_gen.config import GlyphStrategy

    strategies = dict(config.glyphs.strategies)
    for freeze_name in config.glyphs.freeze:
        strategies.setdefault(freeze_name, GlyphStrategy(strategy="freeze", params={}))

    # Source uses friendly names (rcommaaccent), donors use uniXXXX — resolve the
    # donor glyph name by codepoint when the source name isn't present in donors.
    rep = TTFont(str(plan[0].donor_path))
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
    axis_tags = [axis.tag for axis in config.axes]
    if style.base_source is not None:
        # prior source, for sampling
        with open(style.base_source) as base_file:
            base = glyphsLib.load(base_file)
        base_glyphs = {g.name: g for g in base.glyphs}
        base_mids = {
            master.id: AxisLocation.from_values(axis_tags[: len(master.axes)], list(master.axes))
            for master in base.masters
            if 0 < len(master.axes) <= len(axis_tags)
        }

    template = font.masters[0]
    ids = {master.name: f"{config.id}-{style_key}-{master.name}" for master in plan}
    if hasattr(font, "axes") and config.axes:
        font.axes = [GSAxis(name=axis.name, tag=axis.tag) for axis in config.axes]
    font.masters = [
        make_master(
            template,
            master.name,
            _master_axis_values(config, style, master.name),
            ids[master.name],
        )
        for master in plan
    ]
    default_donor_path = next(master.donor_path for master in plan if master.name == default_name)
    metrics = _vertical_metrics(config, default_donor_path)
    for m in font.masters:  # adopt the family's vertical metrics
        for attr, val in metrics.items():
            setattr(m, attr, val)
    font.instances = []

    # Resolve every glyph's donor outlines up front (cheap table lookups), then
    # reconstruct them all in one parallel pass before the serial write-back loop
    # below. Covers every glyph present in all donors, including the few the
    # strategy table handles specially, because those paths fall through to the
    # normal reconstruction when their own handling doesn't apply.
    donor_outlines: dict[str, dict] = {}
    for glyph in font.glyphs:
        dn = donor_name_for(glyph)
        if dn is None:
            continue
        resolved = {master.name: donor_outline(donors[master.name], dn) for master in plan}
        if all(o is not None for o in resolved.values()):
            donor_outlines[glyph.name] = resolved

    workers = reconstruct_workers(len(donor_outlines))
    groups = _plan_groups(plan, primary_tag)
    print(
        f"[{style_key}] reconstructing {len(donor_outlines)} glyphs on {workers} core(s)"
        f" ({len(groups)} interpolating row(s))"
    )
    reconstructed = reconstruct_plan(
        donor_outlines,
        plan,
        primary_tag,
        reference_location,
        workers,
    )

    stats = RebuildStats()
    for glyph in font.glyphs:
        strat = strategies.get(glyph.name)

        # Freeze only along the primary axis. Each optical row keeps its own
        # default-weight drawing and advance, so an explicit freeze never erases
        # legitimate optical-size variation.
        if strat is not None and strat.strategy == "freeze":
            frozen_rows: dict[AxisLocation, tuple[list, float]] = {}
            valid = True
            for row in groups:
                row_default = min(
                    row.masters,
                    key=lambda item: abs(
                        item.location[primary_tag] - reference_location[primary_tag]
                    ),
                )
                row_outline = donor_outline(donors[row_default.name], donor_name_for(glyph))
                if row_outline is None:
                    valid = False
                    break
                contours, width = row_outline
                cleaned = union_overlaps(contours)
                if cleaned is not None:
                    contours = cleaned
                for master in row.masters:
                    frozen_rows[master.location] = (contours, width)
            if valid:
                _check_row_signatures(
                    glyph.name,
                    {location: outline for location, (outline, _width) in frozen_rows.items()},
                    groups,
                    primary_tag,
                    reference_location,
                )
                glyph.layers = []
                for master in plan:
                    layer = GSLayer()
                    layer.layerId = layer.associatedMasterId = ids[master.name]
                    glyph.layers.append(layer)
                    contours, width = frozen_rows[master.location]
                    draw_into(layer, contours)
                    layer.width = width
                stats.frozen += 1
                stats.glyphs[glyph.name] = "frozen"
                continue

        outlines = donor_outlines.get(glyph.name, {})
        in_donors = len(outlines) == len(plan)

        if in_donors:
            out8 = {master.name: outlines[master.name] for master in plan}
            # Open-bar design change: $ / ¢ keep only the TOP and BOTTOM bar stubs
            # (no through-middle). Body = the bare letter (S/c) donor; bar = two
            # nubs. Built directly (bypasses the donor area gate — intentionally
            # not the donor shape). Falls through to the normal path if it fails.
            if strat is not None and strat.strategy == "open_bar":
                letter = strat.params["letter"]
                anchor = strat.params["anchor"]
                rc.NUB_OVERLAP = strat.params.get("nubOverlap", rc.NUB_OVERLAP)
                rc.MIN_PROTRUDE = strat.params.get("minProtrude", rc.MIN_PROTRUDE)
                bf = _open_bar_rows(
                    name=glyph.name,
                    letter=letter,
                    anchor=anchor,
                    donor_outlines=donor_outlines,
                    donors=donors,
                    plan=plan,
                    primary_tag=primary_tag,
                    reference_location=reference_location,
                )
                if bf is not None:
                    glyph.layers = []
                    for master in plan:
                        layer = GSLayer()
                        layer.layerId = layer.associatedMasterId = ids[master.name]
                        glyph.layers.append(layer)
                        draw_into(layer, bf[master.location])
                        layer.width = outlines[master.name][1]
                    stats.reconstructed += 1
                    stats.donor += 1
                    stats.glyphs[glyph.name] = "reconstructed"
                    continue
            # Independent statics aren't interpolation-compatible. ALWAYS run
            # reconstruct(): it returns the donor outlines unchanged when they
            # truly interpolate, and reconstructs to a shared structure otherwise.
            # If it can't reconcile the glyph (genuine topology change), leave the
            # donor outlines and flag for freeze.
            rec, info = reconstructed[glyph.name]
            if rec is not None:
                out8 = {
                    master.name: (rec[master.location], outlines[master.name][1]) for master in plan
                }
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
                out8 = {master.name: reg for master in plan}
                stats.frozen_incompatible.append(glyph.name)
                stats.glyphs[glyph.name] = "frozen_incompatible"
            glyph.layers = []
            for master in plan:
                layer = GSLayer()
                layer.layerId = layer.associatedMasterId = ids[master.name]
                glyph.layers.append(layer)
                draw_into(layer, out8[master.name][0])
                layer.width = out8[master.name][1]
            stats.donor += 1
            continue

        # not in donors — sample the glyph's prior interpolation from base_source
        bg = base_glyphs.get(glyph.name)
        old_rows: dict[AxisLocation, dict[float, tuple]] = {}
        if bg:
            for layer in bg.layers:
                if layer.layerId in base_mids:
                    location = base_mids[layer.layerId]
                    old_rows.setdefault(location.without(primary_tag), {})[
                        location[primary_tag]
                    ] = layer_outline(layer)
        if any(len(row) >= 2 for row in old_rows.values()):
            glyph.layers = []
            ok = True
            sampled_outlines: dict[AxisLocation, list] = {}
            for master in plan:
                base_row = old_rows.get(master.location.without(primary_tag))
                if base_row is None and len(old_rows) == 1:
                    base_row = next(iter(old_rows.values()))
                if base_row is None or len(base_row) < 2:
                    ok = False
                    break
                old_positions = sorted(base_row)
                p = master.location[primary_tag]
                lows = [q for q in old_positions if q <= p] or [old_positions[0]]
                highs = [q for q in old_positions if q >= p] or [old_positions[-1]]
                a, b = max(lows), min(highs)
                try:
                    if a == b:
                        contours, width = base_row[a]
                    else:
                        t = (p - a) / (b - a)
                        contours = lerp_outline(base_row[a][0], base_row[b][0], t)
                        width = base_row[a][1] + (base_row[b][1] - base_row[a][1]) * t
                    sampled_outlines[master.location] = contours
                    layer = GSLayer()
                    layer.layerId = layer.associatedMasterId = ids[master.name]
                    glyph.layers.append(layer)
                    draw_into(layer, contours)
                    layer.width = width
                except Exception as exc:  # noqa: BLE001 — fall back to freeze below
                    print(
                        f"[{style_key}] sampling {glyph.name} from base source failed"
                        f" at {master.name}: {exc} — freezing",
                        file=sys.stderr,
                    )
                    ok = False
                    break
            if ok and len(glyph.layers) == len(plan):
                _check_row_signatures(
                    glyph.name,
                    sampled_outlines,
                    groups,
                    primary_tag,
                    reference_location,
                )
                stats.sampled += 1
                stats.glyphs[glyph.name] = "sampled"
                continue

        # last resort: freeze to whatever single outline we can (keeps build valid)
        fallback_row = next(iter(old_rows.values()), {})
        fallback_positions = sorted(fallback_row)
        ref = (
            fallback_row[fallback_positions[len(fallback_positions) // 2]]
            if fallback_positions
            else ([], 0)
        )
        glyph.layers = []
        for master in plan:
            layer = GSLayer()
            layer.layerId = layer.associatedMasterId = ids[master.name]
            glyph.layers.append(layer)
            draw_into(layer, ref[0])
            layer.width = ref[1]
        stats.frozen += 1
        stats.glyphs[glyph.name] = "frozen"

    tmp = style.source.with_suffix(".glyphs.tmp")
    font.save(str(tmp))
    tmp.replace(style.source)
    return stats


def main(argv: list[str] | None = None) -> int:
    """Thin wrapper: ``python -m variable_gen.rebuild`` == ``variable-gen rebuild``."""
    from variable_gen.cli import run_command

    return run_command("rebuild", argv)


if __name__ == "__main__":
    raise SystemExit(main())
