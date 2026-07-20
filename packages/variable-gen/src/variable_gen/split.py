#!/usr/bin/env python3
"""Split a variable font into static weight files — the reverse of the build.

Where the pipeline (bootstrap -> rebuild -> normalize -> build -> release) merges
N static donors into one variable font, this takes one variable font and pins it
at each step along the ``wght`` axis to produce standalone static instances.

It needs none of the merge machinery: ``fontTools.varLib.instancer`` produces a
full static instance in one call (auto-pinning any other axes to their default),
and ``release.woff2`` handles the web flavor. The one thing the instancer does
*not* do is rename per weight — every instance keeps the source family/subfamily,
so without stamping distinct names the outputs collide on install. We stamp them
here, reusing the same name-table helpers as ``release.finalize_vf``.

Run:  variable-gen split --input Family-VF.ttf --output ./static
"""

from __future__ import annotations

import re
from pathlib import Path

from fontTools.ttLib import TTFont, TTLibError
from fontTools.varLib.instancer import instantiateVariableFont

from variable_gen.release import setname, woff2

# usWeightClass -> canonical weight name (OpenType WWS). Off-map steps fall back
# to the numeric weight so an unusual --step still produces distinct names.
WEIGHT_NAMES = {
    100: "Thin",
    200: "ExtraLight",
    300: "Light",
    400: "Regular",
    500: "Medium",
    600: "SemiBold",
    700: "Bold",
    800: "ExtraBold",
    900: "Black",
}

# The RIBBI four (regular/bold/italic/bold-italic) share one family; every other
# weight installs as its own family so the OS doesn't fold them together.
_RIBBI_WEIGHTS = {400, 700}


class SplitError(ValueError):
    """A user-facing reason a font can't be split into static weights."""


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-") or "font"


def _base_family(font: TTFont) -> str:
    name = font["name"]
    return (name.getDebugName(16) or name.getDebugName(1) or "Font").strip()


def _is_italic(font: TTFont) -> bool:
    os2 = font.get("OS/2")
    if os2 is not None and getattr(os2, "fsSelection", 0) & 0x01:
        return True
    subfamily = font["name"].getDebugName(17) or font["name"].getDebugName(2) or ""
    return "italic" in subfamily.lower()


def _wght_axis(font: TTFont):
    for axis in font["fvar"].axes:
        if axis.axisTag == "wght":
            return axis
    return None


def _weight_name(weight: int) -> str:
    return WEIGHT_NAMES.get(weight, str(weight))


def _target_weights(minimum: int, maximum: int, step: int) -> list[int]:
    """Every ``step`` from min to max inclusive, always ending on max."""
    if step < 1:
        raise SplitError("step must be a positive integer")
    weights = list(range(minimum, maximum + 1, step))
    if not weights or weights[-1] != maximum:
        weights.append(maximum)
    return weights


def _stamp_names(inst: TTFont, family: str, weight_name: str, weight: int, italic: bool) -> None:
    """Give the instance a distinct, installable identity (mirrors
    ``release.finalize_vf`` for a single static weight)."""
    ps_family = family.replace(" ", "")
    ps_weight = weight_name.replace(" ", "")
    is_ribbi = weight in _RIBBI_WEIGHTS

    if is_ribbi:
        # Regular/Bold live under the base family; italic sets the style word.
        family_name = family
        if weight == 700:
            subfamily = "Bold Italic" if italic else "Bold"
        else:
            subfamily = "Italic" if italic else "Regular"
    else:
        # Non-RIBBI weights become their own family so they don't overwrite each
        # other or the Regular face when installed.
        family_name = f"{family} {weight_name}"
        subfamily = "Italic" if italic else "Regular"

    typo_sub = f"{weight_name} Italic" if italic else weight_name
    full = f"{family} {weight_name} Italic" if italic else f"{family} {weight_name}"
    ps = f"{ps_family}-{ps_weight}Italic" if italic else f"{ps_family}-{ps_weight}"

    setname(inst, family_name, 1)
    setname(inst, subfamily, 2)
    setname(inst, full, 4)
    setname(inst, ps, 6)
    setname(inst, family, 16)
    setname(inst, typo_sub, 17)

    os2 = inst["OS/2"]
    os2.usWeightClass = weight
    head = inst["head"]
    bold = weight == 700
    # RIBBI fsSelection: REGULAR (bit 6) is set only when neither ITALIC (bit 0)
    # nor BOLD (bit 5) applies; otherwise those bits must be clear.
    os2.fsSelection &= ~(0x001 | 0x020 | 0x040)
    head.macStyle &= ~(0x1 | 0x2)
    if italic:
        os2.fsSelection |= 0x001
        head.macStyle |= 0x2
    if bold:
        os2.fsSelection |= 0x020
        head.macStyle |= 0x1
    if not (italic or bold):
        os2.fsSelection |= 0x040


def split_variable_font(
    input_path: Path,
    output_dir: Path,
    step: int = 100,
) -> list[dict]:
    """Pin ``input_path`` at each ``wght`` step and write a static TTF + WOFF2.

    Returns one entry per generated weight:
    ``{"weight": int, "name": str, "files": [str, ...]}``. Raises ``SplitError``
    if the input is not a weight-variable font.
    """
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    try:
        font = TTFont(str(input_path))
    except (TTLibError, OSError) as exc:
        raise SplitError(f"{input_path.name}: not a readable font ({exc})") from None

    if "fvar" not in font:
        raise SplitError(f"{input_path.name} is not a variable font; nothing to split.")
    axis = _wght_axis(font)
    if axis is None:
        tags = ", ".join(a.axisTag for a in font["fvar"].axes) or "none"
        raise SplitError(f"{input_path.name} has no 'wght' axis to step along (axes: {tags}).")

    family = _base_family(font)
    italic = _is_italic(font)
    slug = _slug(family)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    for weight in _target_weights(int(axis.minValue), int(axis.maxValue), step):
        # inplace=False already deep-copies the font, so `font` stays reusable.
        inst = instantiateVariableFont(
            font, {"wght": weight}, static=True, inplace=False, updateFontNames=False
        )
        weight_name = _weight_name(weight)
        _stamp_names(inst, family, weight_name, weight, italic)

        stem = f"{slug}-{_slug(weight_name)}{'-Italic' if italic else ''}"
        ttf_path = output_dir / f"{stem}.ttf"
        inst.save(str(ttf_path))
        files = [str(ttf_path), str(woff2(ttf_path))]
        inst.close()
        results.append({"weight": weight, "name": weight_name, "files": files})

    font.close()
    return results


def main(argv: list[str] | None = None) -> int:
    """Thin wrapper: ``python -m variable_gen.split`` == ``variable-gen split``."""
    from variable_gen.cli import run_command

    return run_command("split", argv)


if __name__ == "__main__":
    raise SystemExit(main())
