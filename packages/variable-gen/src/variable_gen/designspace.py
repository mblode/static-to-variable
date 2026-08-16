#!/usr/bin/env python3
"""Config-driven designspace export for a static-to-variable project.

Converts a ``.glyphs`` source into UFOs + a ``.designspace`` document,
correcting the axis that glyphsLib mis-computes (it emits ``min=max=default``
with a bogus avar map because it confuses instance axesValues with mapping
points). The axis range, default, STAT axis labels, and fvar named instances
are all sourced from the v3 ``ProjectConfig`` (``axes[].namedInstances`` + the
family metadata).

The core ``build_designspace`` takes plain values so callers that are not
config-driven can still invoke it directly.

Run:  uv run python -m variable_gen.cli designspace --config <path> --style all
"""

from __future__ import annotations

import shutil
from itertools import product
from pathlib import Path

import glyphsLib
import ufoLib2
from fontTools.designspaceLib import (
    AxisLabelDescriptor,
    InstanceDescriptor,
)
from glyphsLib.builder import to_designspace

from variable_gen.config import ConfigAxis, ProjectConfig


def fix_designspace_axis(
    ds,
    *,
    axis_tag: str,
    axis_name: str,
    default_weight: float,
    weight_names: dict[float, str],
    family: str,
    is_italic: bool,
    write_instances: bool = True,
    minimum: float | None = None,
    maximum: float | None = None,
    mapping: tuple[tuple[float, float], ...] = (),
) -> None:
    """Correct the variable axis, pin the default, and emit clean named instances
    + STAT axis labels. glyphsLib emits a broken axis (min=max=default, bogus avar
    map); this rebuilds it from the actual source master locations."""
    found_axis = False
    for axis in ds.axes:
        if axis.tag != axis_tag:
            continue
        found_axis = True
        locs = []
        for src in ds.sources:
            val = src.location.get(axis.name)
            if val is None:
                val = src.location.get(axis.tag)
            if val is not None:
                locs.append(val)
        if not locs:
            continue
        axis.minimum = min(locs) if minimum is None else minimum
        axis.maximum = max(locs) if maximum is None else maximum
        axis.default = (
            default_weight if axis.minimum <= default_weight <= axis.maximum else min(locs)
        )
        # Drop glyphsLib's bogus map, but retain an explicitly configured avar
        # mapping. DesignspaceLib stores user -> design coordinates here.
        axis.map = list(mapping)
        if mapping:
            for source in ds.sources:
                key = axis.name if axis.name in source.location else axis.tag
                if key in source.location:
                    source.location[key] = axis.map_forward(source.location[key])

        # STAT axis-value labels for every named stop in range.
        axis.axisLabels = [
            AxisLabelDescriptor(
                name=name,
                userValue=pos,
                # Regular<->Bold RIBBI link (default weight -> 700 when present)
                linkedUserValue=(
                    700
                    if axis_tag == "wght"
                    and pos == default_weight
                    and axis.minimum <= 700 <= axis.maximum
                    else None
                ),
                elidable=(pos == default_weight),
            )
            for pos, name in sorted(weight_names.items())
            if axis.minimum <= pos <= axis.maximum
        ]
        print(f"  Fixed {axis.tag}: min={axis.minimum} default={axis.default} max={axis.maximum}")

    if not found_axis:
        raise ValueError(f"designspace has no configured {axis_tag!r} axis")

    if write_instances:
        _write_weight_instances(
            ds,
            axis_name=axis_name,
            axis_tag=axis_tag,
            weight_names=weight_names,
            family=family,
            is_italic=is_italic,
        )


def _write_weight_instances(ds, *, axis_name, axis_tag, weight_names, family, is_italic) -> None:
    def _loc(src):
        return src.location.get(axis_name, src.location.get(axis_tag))

    wmin = min(_loc(s) for s in ds.sources)
    wmax = max(_loc(s) for s in ds.sources)
    axis = next(item for item in ds.axes if item.tag == axis_tag)
    ds.instances = []
    for pos, base_name in sorted(weight_names.items()):
        design_pos = axis.map_forward(pos)
        if not (wmin <= design_pos <= wmax):
            continue
        style = f"{base_name} Italic" if is_italic else base_name
        inst = InstanceDescriptor()
        inst.familyName = family
        inst.styleName = style
        inst.name = f"{family} {style}"
        inst.location = {axis_name: design_pos}
        inst.lib = {"public.fontInfo": {}}
        ds.addInstance(inst)
    print(f"  Wrote {len(ds.instances)} named instances ({'italic' if is_italic else 'roman'})")


# glyphsLib writes this into every UFO it emits; ufo2ft then runs the listed
# filters during the fontmake build.
UFO2FT_FILTERS_KEY = "com.github.googlei18n.ufo2ft.filters"


def drop_open_corner_filter(ufo) -> bool:
    """Remove glyphsLib's ``eraseOpenCorners`` pre-filter from one UFO's lib.

    An "open corner" is a Glyphs *drawing* convention: the designer overlaps two
    strokes at a joint and leaves a small crossing loop, which the filter erases
    at compile time. Our masters are not drawn that way. They are reconstructed
    from already-compiled static TTFs, whose outlines never contain that
    convention, so the filter has nothing legitimate to erase here.

    What it does instead is misread the acute junctions of diagonal strokes as
    open corners. Worse, ufo2ft applies it to each master independently, so the
    same glyph gets a different point count per weight and the masters stop
    interpolating. Measured on Inter Thin/Regular/Black, it broke every diagonal
    glyph in the font (A M N W X Y Z w x y, plus their accented forms) while
    leaving curve-only glyphs (B o e n) untouched. fontmake then rejected them as
    incompatible and ``build_style`` froze them to the default master, which is
    why they rendered at one fixed weight across the whole axis.

    Returns whether the filter was present.
    """
    filters = ufo.lib.get(UFO2FT_FILTERS_KEY)
    if not filters:
        return False
    kept = [f for f in filters if f.get("name") != "eraseOpenCorners"]
    if len(kept) == len(filters):
        return False
    if kept:
        ufo.lib[UFO2FT_FILTERS_KEY] = kept
    else:
        del ufo.lib[UFO2FT_FILTERS_KEY]
    return True


def build_designspace(
    glyphs_path: Path,
    ds_name: str,
    ufo_prefix: str,
    *,
    family: str,
    is_italic: bool,
    axis_tag: str,
    axis_name: str,
    default_weight: float,
    weight_names: dict[float, str],
    master_ufo_dir: Path,
    write_instances: bool = True,
    axis_minimum: float | None = None,
    axis_maximum: float | None = None,
    axis_mapping: tuple[tuple[float, float], ...] = (),
    quadratic_reference_path: Path | None = None,
    quadratic_reference_location: dict[str, float] | None = None,
    quadratic_reference_max_error: float = 1.0,
    quadratic_topology: dict[str, tuple[tuple[tuple[str, int], ...], ...]] | None = None,
    quadratic_topology_master_names: tuple[str, ...] = (),
    default_master_name: str | None = None,
) -> Path:
    """Convert one ``.glyphs`` source to UFOs + a corrected designspace, written
    under ``master_ufo_dir``. Returns the designspace path."""
    glyphs_path = Path(glyphs_path)
    print(f"Loading {glyphs_path.name}...")
    font = glyphsLib.load(str(glyphs_path))

    print("Converting to designspace + UFOs...")
    ds = to_designspace(font, ufo_module=ufoLib2)

    fix_designspace_axis(
        ds,
        axis_tag=axis_tag,
        axis_name=axis_name,
        default_weight=default_weight,
        weight_names=weight_names,
        family=family,
        is_italic=is_italic,
        write_instances=write_instances,
        minimum=axis_minimum,
        maximum=axis_maximum,
        mapping=axis_mapping,
    )

    if quadratic_reference_path is not None:
        from variable_gen.quadratic_reference import preserve_quadratic_reference

        default_indices = [
            index
            for index, source in enumerate(ds.sources)
            if source.styleName == default_master_name
        ]
        if len(default_indices) != 1:
            raise ValueError(
                "quadratic reference requires exactly one source named "
                f"{default_master_name!r}; found {len(default_indices)}"
            )
        report = preserve_quadratic_reference(
            [source.font for source in ds.sources],
            default_index=default_indices[0],
            reference_path=quadratic_reference_path,
            reference_location=quadratic_reference_location or {},
            max_error=quadratic_reference_max_error,
            topology_contract=quadratic_topology,
            topology_contract_master_names=quadratic_topology_master_names,
            # Configured master names are Glyphs style names (for example
            # ``Text Regular``); designspace source names include the family
            # prefix (for example ``Glide Text Regular``).
            source_master_names=tuple(source.styleName for source in ds.sources),
        )
        print(
            "  Preserved quadratic reference: "
            f"{report.glyphs} authored glyph(s), "
            f"{report.exact_default_glyphs} already exact, "
            f"{report.expanded_operations} compatibility prefix(es)"
        )

    master_ufo_dir.mkdir(parents=True, exist_ok=True)
    dropped = 0
    for src in ds.sources:
        safe_name = src.name.replace(" ", "_").replace("/", "_")
        ufo_filename = f"{ufo_prefix}_{safe_name}.ufo"
        ufo_path = master_ufo_dir / ufo_filename
        if ufo_path.exists():
            shutil.rmtree(ufo_path)
        dropped += drop_open_corner_filter(src.font)
        print(f"  Saving {ufo_filename}...")
        src.font.save(str(ufo_path))
        src.filename = ufo_filename
        src.path = str(ufo_path)

    if dropped:
        print(f"  Dropped glyphsLib's eraseOpenCorners filter from {dropped} master(s)")

    ds_path = master_ufo_dir / ds_name
    ds.write(str(ds_path))
    print(f"  Designspace written: {ds_path}")
    return ds_path


def _ds_naming(config: ProjectConfig, style_key: str) -> tuple[str, str]:
    """(designspace filename, UFO prefix) for a style — the family name with an
    ``Italic`` suffix for italic styles."""
    prefix = config.family.name.replace(" ", "")
    if config.styles[style_key].italic:
        prefix = f"{prefix}Italic"
    return f"{prefix}.designspace", prefix


def export_designspace(config: ProjectConfig, style_key: str) -> Path:
    """Export one style's designspace + UFOs, driven entirely by the config."""
    style = config.styles[style_key]
    ds_name, ufo_prefix = _ds_naming(config, style_key)
    primary = config.axes[0]
    weight_names = dict(primary.named_instances)
    default_master = next(master for master in style.masters if master.default)
    quadratic_reference = style.quadratic_reference
    quadratic_topology = style.quadratic_topology
    path = build_designspace(
        style.source,
        ds_name,
        ufo_prefix,
        family=config.family.name,
        is_italic=style.italic,
        axis_tag=primary.tag,
        axis_name=primary.name,
        default_weight=primary.default,
        weight_names=weight_names,
        master_ufo_dir=config.repo_root / "master_ufo",
        write_instances=len(config.axes) == 1,
        axis_minimum=primary.minimum,
        axis_maximum=primary.maximum,
        axis_mapping=primary.mapping,
        quadratic_reference_path=(
            quadratic_reference.path if quadratic_reference is not None else None
        ),
        quadratic_reference_location=(
            quadratic_reference.location if quadratic_reference is not None else None
        ),
        quadratic_reference_max_error=(
            quadratic_reference.max_error if quadratic_reference is not None else 1.0
        ),
        quadratic_topology=(quadratic_topology.glyphs if quadratic_topology is not None else None),
        quadratic_topology_master_names=(
            quadratic_topology.master_names if quadratic_topology is not None else ()
        ),
        default_master_name=default_master.name,
    )
    if len(config.axes) > 1:
        _configure_multi_axis_designspace(
            path,
            family=config.family.name,
            is_italic=style.italic,
            axes=config.axes,
        )
    return path


def _instance_positions(axis: ConfigAxis) -> list[tuple[float, str]]:
    positions = sorted(axis.named_instances.items())
    if not positions:
        return [(axis.default, f"{axis.default:g}")]
    return positions


def _instance_style(
    axes: tuple[ConfigAxis, ...], values: tuple[tuple[float, str], ...], is_italic: bool
) -> str:
    parts = [values[0][1]]
    parts.extend(
        label
        for axis, (position, label) in zip(axes[1:], values[1:], strict=True)
        if position != axis.default
    )
    base = " ".join(parts) or "Regular"
    if is_italic:
        at_default = all(value[0] == axis.default for axis, value in zip(axes, values, strict=True))
        return "Italic" if at_default else f"{base} Italic"
    return base


def _configure_multi_axis_designspace(
    ds_path: Path,
    *,
    family: str,
    is_italic: bool,
    axes: tuple[ConfigAxis, ...],
) -> None:
    """Correct every axis and emit named instances at the full axis product."""
    from fontTools.designspaceLib import DesignSpaceDocument

    ds = DesignSpaceDocument.fromfile(str(ds_path))
    for axis in axes[1:]:
        fix_designspace_axis(
            ds,
            axis_tag=axis.tag,
            axis_name=axis.name,
            default_weight=axis.default,
            weight_names=dict(axis.named_instances),
            family=family,
            is_italic=is_italic,
            write_instances=False,
            minimum=axis.minimum,
            maximum=axis.maximum,
            mapping=axis.mapping,
        )
    ds.instances = []
    ladders = [_instance_positions(axis) for axis in axes]
    for values in product(*ladders):
        style = _instance_style(axes, values, is_italic)
        inst = InstanceDescriptor()
        inst.familyName = family
        inst.styleName = style
        inst.name = f"{family} {style}"
        descriptors = {axis.tag: axis for axis in ds.axes}
        inst.location = {
            axis.name: descriptors[axis.tag].map_forward(position)
            for axis, (position, _label) in zip(axes, values, strict=True)
        }
        inst.lib = {"public.fontInfo": {}}
        ds.addInstance(inst)
    ds.write(str(ds_path))
    tags = " × ".join(axis.tag for axis in axes)
    print(f"  Wrote {len(ds.instances)} named instances ({tags})")


def main(argv: list[str] | None = None) -> int:
    """Thin wrapper: ``python -m variable_gen.designspace`` == ``variable-gen designspace``."""
    from variable_gen.cli import run_command

    return run_command("designspace", argv)


if __name__ == "__main__":
    raise SystemExit(main())
