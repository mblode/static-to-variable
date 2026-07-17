"""Generate a validated v3 ``stv.config.json`` from a set of uploaded static fonts.

Reuses the same font reads as ``variable_gen.discover`` (OS/2 usWeightClass + the
name table) to map each dropped weight onto the wght axis, then assembles a config
that satisfies ``variable_gen.config.load_config`` — the from-scratch build
(bootstrap → rebuild → normalize → build → release) takes it from there.
"""

from __future__ import annotations

import re
from pathlib import Path

from fontTools.ttLib import TTFont, TTLibError

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

# Longest keys first so "extrabold" wins over "bold" (see _infer_weight).
_KEYWORD_WEIGHTS = {
    "hairline": 100,
    "extralight": 200,
    "ultralight": 200,
    "semibold": 600,
    "demibold": 600,
    "extrabold": 800,
    "ultrabold": 800,
    "thin": 100,
    "light": 300,
    "regular": 400,
    "normal": 400,
    "medium": 500,
    "bold": 700,
    "black": 900,
    "heavy": 900,
}

_ACCEPT_SFNT = ("\x00\x01\x00\x00", "OTTO", "true")


class ConfigGenError(ValueError):
    """A user-facing reason the dropped fonts can't be turned into a config."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _name(font: TTFont, *ids: int) -> str | None:
    table = font.get("name")
    if table is None:
        return None
    for name_id in ids:
        value = table.getDebugName(name_id)
        if value:
            return value.strip()
    return None


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _infer_weight(subfamily: str) -> int:
    compact = subfamily.lower().replace(" ", "").replace("-", "")
    for keyword, weight in sorted(_KEYWORD_WEIGHTS.items(), key=lambda kv: -len(kv[0])):
        if keyword in compact:
            return weight
    return 400


def _clean_family(name: str) -> str:
    tokens = name.split()
    droppable = set(_KEYWORD_WEIGHTS) | {"italic", "oblique"}
    while tokens and tokens[-1].lower() in droppable:
        tokens.pop()
    return " ".join(tokens) or name


def inspect_font(path: Path) -> dict:
    """Read weight/family/style from one static font. Raises ConfigGenError."""
    try:
        font = TTFont(str(path), lazy=True)
    except (TTLibError, OSError):
        raise ConfigGenError("unsupported_type", f"{path.name}: not a readable font") from None
    try:
        if font.sfntVersion not in _ACCEPT_SFNT:
            raise ConfigGenError(
                "unsupported_type",
                f"{path.name}: unsupported font (need a single TTF/OTF, not a collection or WOFF)",
            )
        os2 = font.get("OS/2")
        subfamily = _name(font, 17, 2) or "Regular"
        raw_family = _name(font, 16, 1) or path.stem
        raw_weight = getattr(os2, "usWeightClass", None)
        name_weight = _infer_weight(subfamily)
        # Prefer usWeightClass, but defer to the style name when it's missing or a
        # generic 400 that contradicts a named weight — some fonts (e.g. Operator
        # Mono Bold) ship usWeightClass=400 despite a "Bold" subfamily.
        if raw_weight and not (int(raw_weight) == 400 and name_weight != 400):
            weight = int(raw_weight)
        else:
            weight = name_weight
        weight = max(1, min(1000, weight))
        italic = bool(getattr(os2, "fsSelection", 0) & 0x01) or "italic" in subfamily.lower()
        return {
            "weight": weight,
            "subfamily": subfamily,
            "raw_family": raw_family,
            "italic": italic,
        }
    finally:
        font.close()


def _common_family(raw_families: list[str]) -> str:
    """Longest shared leading words across the fonts' family names (e.g.
    'Roboto Thin' / 'Roboto' / 'Roboto Black' -> 'Roboto')."""
    prefix: list[str] = []
    for words in zip(*(f.split() for f in raw_families), strict=False):
        if len(set(words)) == 1:
            prefix.append(words[0])
        else:
            break
    return " ".join(prefix) or raw_families[0]


def _style_name(info: dict, common: str) -> str:
    """The per-font weight name, preferring the family-name suffix (fonts often
    encode the weight there with a 'Regular' subfamily), then subfamily, then the
    standard weight-class name."""
    raw = info["raw_family"]
    if raw.lower().startswith(common.lower()) and len(raw) > len(common):
        suffix = raw[len(common) :].strip(" -")
        if suffix:
            return suffix
    sub = info["subfamily"]
    if sub and sub.lower() not in ("regular", "normal"):
        return sub
    return WEIGHT_NAMES.get(info["weight"], str(info["weight"]))


def generate_config(
    font_paths: list[Path], weight_overrides: dict[str, int] | None = None
) -> tuple[dict, dict[str, Path]]:
    """Turn N static fonts into (config dict, {donor_id: source font path}).

    ``weight_overrides`` maps an uploaded filename (``path.name``) to the weight
    the user chose in the editable table, overriding the detected usWeightClass.
    The caller writes each donor to ``donors/<id>.ttf`` under the job root and the
    config to ``stv.config.json`` there, then validates with ``load_config``.
    """
    if len(font_paths) < 2:
        raise ConfigGenError(
            "too_few_files", "Upload at least 2 static weights to build a variable font."
        )

    overrides = weight_overrides or {}
    infos = []
    for p in font_paths:
        info = {**inspect_font(p), "path": p}
        if p.name in overrides:
            info["weight"] = max(1, min(1000, int(overrides[p.name])))
        infos.append(info)

    seen_weights: dict[int, str] = {}
    for info in infos:
        w = info["weight"]
        if w in seen_weights:
            raise ConfigGenError(
                "duplicate_weight",
                f"Two fonts map to weight {w} ({seen_weights[w]} and "
                f"{info['subfamily']}); each weight must be distinct.",
            )
        seen_weights[w] = info["subfamily"]

    infos.sort(key=lambda i: i["weight"])
    weights = [i["weight"] for i in infos]
    default_w = 400 if 400 in weights else min(weights, key=lambda w: abs(w - 400))
    common = _common_family([i["raw_family"] for i in infos])
    for info in infos:
        info["style"] = _style_name(info, common)
    family_name = _clean_family(common)
    slug = _slug(family_name) or "myfamily"
    italic = all(i["italic"] for i in infos)

    donors: list[dict] = []
    masters: list[dict] = []
    named_instances: dict[str, str] = {}
    id_to_path: dict[str, Path] = {}
    seen_ids: set[str] = set()
    for info in infos:
        base = _slug(info["style"]) or f"w{info['weight']}"
        donor_id = base
        n = 2
        while donor_id in seen_ids:
            donor_id = f"{base}-{n}"
            n += 1
        seen_ids.add(donor_id)
        id_to_path[donor_id] = info["path"]
        donors.append(
            {
                "id": donor_id,
                "name": info["style"],
                "path": f"donors/{donor_id}.ttf",
                "location": {"wght": info["weight"]},
            }
        )
        master = {"name": info["style"], "donorId": donor_id, "location": {"wght": info["weight"]}}
        if info["weight"] == default_w:
            master["default"] = True
        masters.append(master)
        named_instances[str(info["weight"])] = info["style"]

    style_key = "italic" if italic else "roman"
    config = {
        "version": 3,
        "id": slug,
        "family": {
            "name": family_name,
            "version": "1.000",
            "vendor": "STV",
            "designer": "static-to-variable",
            "designerUrl": "https://variable.blode.co",
            "vendorUrl": "https://variable.blode.co",
        },
        "axes": [
            {
                "tag": "wght",
                "name": "Weight",
                "minimum": min(weights),
                "default": default_w,
                "maximum": max(weights),
                "namedInstances": named_instances,
            }
        ],
        "styles": {
            style_key: {
                "italic": italic,
                "source": f"build/{slug}.glyphs",
                "output": f"build/{slug}-vf.ttf",
                "donors": donors,
                "masters": masters,
            }
        },
        "output": {"dir": "build", "releaseDir": "build/release", "formats": ["ttf", "woff2"]},
    }
    return config, id_to_path
