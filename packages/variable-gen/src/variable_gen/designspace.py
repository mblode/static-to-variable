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
from pathlib import Path

import glyphsLib
import ufoLib2
from fontTools.designspaceLib import (
    AxisLabelDescriptor,
    InstanceDescriptor,
)
from glyphsLib.builder import to_designspace

from variable_gen.config import ProjectConfig


def fix_designspace_axis(
    ds,
    *,
    axis_tag: str,
    axis_name: str,
    default_weight: float,
    weight_names: dict[int, str],
    family: str,
    is_italic: bool,
    write_instances: bool = True,
) -> None:
    """Correct the variable axis, pin the default, and emit clean named instances
    + STAT axis labels. glyphsLib emits a broken axis (min=max=default, bogus avar
    map); this rebuilds it from the actual source master locations."""
    for axis in ds.axes:
        if axis.tag != axis_tag:
            continue
        locs = []
        for src in ds.sources:
            val = src.location.get(axis.name) or src.location.get(axis.tag)
            if val is not None:
                locs.append(val)
        if not locs:
            continue
        axis.minimum = min(locs)
        axis.maximum = max(locs)
        axis.default = (
            default_weight if axis.minimum <= default_weight <= axis.maximum else min(locs)
        )
        axis.map = []  # drop incorrect avar mapping

        # STAT axis-value labels for every named stop in range.
        axis.axisLabels = [
            AxisLabelDescriptor(
                name=name,
                userValue=pos,
                # Regular<->Bold RIBBI link (default weight -> 700 when present)
                linkedUserValue=(
                    700 if pos == default_weight and axis.minimum <= 700 <= axis.maximum else None
                ),
                elidable=(pos == default_weight),
            )
            for pos, name in sorted(weight_names.items())
            if axis.minimum <= pos <= axis.maximum
        ]
        print(f"  Fixed {axis.tag}: min={axis.minimum} default={axis.default} max={axis.maximum}")

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
    ds.instances = []
    for pos, base_name in sorted(weight_names.items()):
        if not (wmin <= pos <= wmax):
            continue
        style = f"{base_name} Italic" if is_italic else base_name
        inst = InstanceDescriptor()
        inst.familyName = family
        inst.styleName = style
        inst.name = f"{family} {style}"
        inst.location = {axis_name: pos}
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
    weight_names: dict[int, str],
    master_ufo_dir: Path,
    write_instances: bool = True,
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
    weight_names = {int(pos): name for pos, name in primary.named_instances.items()}
    extra_axes = [
        {
            "tag": axis.tag,
            "name": axis.name,
            "default": axis.default,
            "named": {int(pos): name for pos, name in axis.named_instances.items()},
        }
        for axis in config.axes[1:]
    ]
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
        write_instances=not extra_axes,
    )
    if extra_axes:
        _expand_opsz_instances(
            path,
            family=config.family.name,
            is_italic=style.italic,
            weight_name=primary.name,
            weight_names=weight_names,
            extra=extra_axes[0],
        )
    return path


def _expand_opsz_instances(
    ds_path: Path,
    *,
    family,
    is_italic,
    weight_name,
    weight_names,
    extra,
) -> None:
    """Named instances at every wght × opsz stop."""
    from fontTools.designspaceLib import DesignSpaceDocument

    ds = DesignSpaceDocument.fromfile(str(ds_path))
    fix_designspace_axis(
        ds,
        axis_tag=extra["tag"],
        axis_name=extra["name"],
        default_weight=extra["default"],
        weight_names=extra["named"],
        family=family,
        is_italic=is_italic,
        write_instances=False,
    )
    ds.instances = []
    for w_pos, w_name in sorted(weight_names.items()):
        for o_pos, o_name in sorted(extra["named"].items()):
            style = f"{w_name} {o_name}"
            if is_italic:
                style = f"{style} Italic"
            inst = InstanceDescriptor()
            inst.familyName = family
            inst.styleName = style
            inst.name = f"{family} {style}"
            inst.location = {weight_name: w_pos, extra["name"]: o_pos}
            inst.lib = {"public.fontInfo": {}}
            ds.addInstance(inst)
    ds.write(str(ds_path))
    print(f"  Wrote {len(ds.instances)} named instances (wght × {extra['tag']})")


def main(argv: list[str] | None = None) -> int:
    """Thin wrapper: ``python -m variable_gen.designspace`` == ``variable-gen designspace``."""
    from variable_gen.cli import run_command

    return run_command("designspace", argv)


if __name__ == "__main__":
    raise SystemExit(main())
