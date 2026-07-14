#!/usr/bin/env python3
"""Config-driven designspace export for a static-to-variable project.

This is the generic form of ``cabinet/export_designspace.py``: it converts a
``.glyphs`` source into UFOs + a ``.designspace`` document, correcting the axis
that glyphsLib mis-computes (it emits ``min=max=default`` with a bogus avar map
because it confuses instance axesValues with mapping points). The axis range,
default, STAT axis labels, and fvar named instances are all sourced from the v3
``ProjectConfig`` (``axes[].namedInstances`` + the family metadata) instead of a
hardcoded ``WEIGHT_NAMES`` table.

The core ``build_designspace`` takes plain values so the Glide-specific shim in
``cabinet/export_designspace.py`` (and any other legacy caller) can keep calling
it with the original three-argument ``export`` signature.

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

from variable_gen.config import ProjectConfig, load_config


def fix_designspace_axis(
    ds,
    *,
    axis_tag: str,
    axis_name: str,
    default_weight: float,
    weight_names: dict[int, str],
    family: str,
    is_italic: bool,
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

    # Named instances at every named stop in range, with a plain weight location.
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
    )

    master_ufo_dir.mkdir(parents=True, exist_ok=True)
    for src in ds.sources:
        safe_name = src.name.replace(" ", "_").replace("/", "_")
        ufo_filename = f"{ufo_prefix}_{safe_name}.ufo"
        ufo_path = master_ufo_dir / ufo_filename
        if ufo_path.exists():
            shutil.rmtree(ufo_path)
        print(f"  Saving {ufo_filename}...")
        src.font.save(str(ufo_path))
        src.filename = ufo_filename
        src.path = str(ufo_path)

    ds_path = master_ufo_dir / ds_name
    ds.write(str(ds_path))
    print(f"  Designspace written: {ds_path}")
    return ds_path


def _ds_naming(config: ProjectConfig, style_key: str) -> tuple[str, str]:
    """(designspace filename, UFO prefix) for a style — the family name with an
    ``Italic`` suffix for italic styles (matching the historical Glide names)."""
    prefix = config.family.name.replace(" ", "")
    if config.styles[style_key].italic:
        prefix = f"{prefix}Italic"
    return f"{prefix}.designspace", prefix


def export_designspace(config: ProjectConfig, style_key: str) -> Path:
    """Export one style's designspace + UFOs, driven entirely by the config."""
    style = config.styles[style_key]
    axis = config.axes[0]
    weight_names = {int(pos): name for pos, name in axis.named_instances.items()}
    ds_name, ufo_prefix = _ds_naming(config, style_key)
    return build_designspace(
        style.source,
        ds_name,
        ufo_prefix,
        family=config.family.name,
        is_italic=style.italic,
        axis_tag=axis.tag,
        axis_name=axis.name,
        default_weight=axis.default,
        weight_names=weight_names,
        master_ufo_dir=config.repo_root / "master_ufo",
    )


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
        ds_path = export_designspace(config, key)
        print(f"[{key}] -> {ds_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
