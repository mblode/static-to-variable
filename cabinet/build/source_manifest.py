#!/usr/bin/env python3

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MasterSpec:
    filename: str
    style_name: str
    weight: int


@dataclass(frozen=True)
class FamilyConfig:
    family_key: str
    default_style: str
    masters: tuple[MasterSpec, ...]

    def master_files_by_weight(self) -> dict[int, str]:
        return {master.weight: master.filename for master in self.masters}


@dataclass(frozen=True)
class SourceConfig:
    family_name: str
    axis_maps: dict[str, tuple[tuple[float, float], ...]]
    families: dict[str, FamilyConfig]


def _default_payload() -> dict[str, object]:
    return {
        "family_name": "Glide",
        "axis_maps": {"wght": [[400, 400], [500, 500], [700, 700], [900, 900]]},
        "families": {
            "roman": {
                "default_style": "Regular",
                "masters": [
                    {"filename": "glide-root-regular.ttf", "style_name": "Regular", "weight": 400},
                    {"filename": "glide-root-medium.ttf", "style_name": "Medium", "weight": 500},
                    {"filename": "glide-root-bold.ttf", "style_name": "Bold", "weight": 700},
                    {"filename": "glide-root-black.ttf", "style_name": "Black", "weight": 900},
                ],
            },
            "italic": {
                "default_style": "Italic",
                "masters": [
                    {
                        "filename": "glide-root-regularItalic.ttf",
                        "style_name": "Regular Italic",
                        "weight": 400,
                    },
                    {
                        "filename": "glide-root-mediumItalic.ttf",
                        "style_name": "Medium Italic",
                        "weight": 500,
                    },
                    {
                        "filename": "glide-root-boldItalic.ttf",
                        "style_name": "Bold Italic",
                        "weight": 700,
                    },
                    {
                        "filename": "glide-root-blackItalic.ttf",
                        "style_name": "Black Italic",
                        "weight": 900,
                    },
                ],
            },
        },
    }


def _coerce_master(raw: dict[str, object]) -> MasterSpec:
    return MasterSpec(
        filename=str(raw["filename"]),
        style_name=str(raw["style_name"]),
        weight=int(raw["weight"]),
    )


def _coerce_family(family_key: str, raw: dict[str, object]) -> FamilyConfig:
    masters = tuple(_coerce_master(master) for master in raw.get("masters", []))
    return FamilyConfig(
        family_key=family_key,
        default_style=str(raw.get("default_style", "Regular")),
        masters=masters,
    )


def load_source_config(manifest_path: str | Path | None) -> SourceConfig:
    if manifest_path is None:
        payload = _default_payload()
    else:
        payload = json.loads(Path(manifest_path).read_text())

    axis_maps = {
        axis_tag: tuple((float(inp), float(out)) for inp, out in mappings)
        for axis_tag, mappings in payload.get("axis_maps", {}).items()
    }
    families = {
        family_key: _coerce_family(family_key, raw_family)
        for family_key, raw_family in payload.get("families", {}).items()
    }
    return SourceConfig(
        family_name=str(payload.get("family_name", "Glide")),
        axis_maps=axis_maps,
        families=families,
    )


def select_masters(family: FamilyConfig, two_master: bool) -> list[MasterSpec]:
    masters = sorted(family.masters, key=lambda master: master.weight)
    if not two_master or len(masters) <= 2:
        return masters
    return [masters[0], masters[-1]]


def family_key_for_font_path(config: SourceConfig, font_path: str | Path) -> str:
    stem = Path(font_path).stem.lower()
    if "italic" in stem and "italic" in config.families:
        return "italic"
    if "roman" in stem and "roman" in config.families:
        return "roman"
    if "roman" in config.families:
        return "roman"
    if "italic" in config.families:
        return "italic"
    raise KeyError("No usable family keys found in source config")
