#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import glyphsLib


REPO_ROOT = Path(__file__).resolve().parents[3]


def _resolve_source_path(source_path: str | Path, manifest_path: Path) -> Path:
    path = Path(source_path)
    if path.is_absolute():
        return path

    repo_candidate = REPO_ROOT / path
    if repo_candidate.exists():
        return repo_candidate

    manifest_candidate = manifest_path.parent / path
    if manifest_candidate.exists():
        return manifest_candidate

    return repo_candidate


def _build_unicode_index(font) -> dict[int, str]:
    unicode_index: dict[int, str] = {}
    for glyph in font.glyphs:
        unicode_values = list(getattr(glyph, "unicodes", []) or [])
        if not unicode_values and getattr(glyph, "unicode", None):
            unicode_values = [glyph.unicode]
        for raw_value in unicode_values:
            if not raw_value:
                continue
            try:
                unicode_index.setdefault(int(str(raw_value), 16), glyph.name)
            except ValueError:
                continue
    return unicode_index


def glyph_names_for_chars(font, chars: str) -> tuple[list[str], list[str]]:
    unicode_index = _build_unicode_index(font)
    glyph_names: list[str] = []
    missing: list[str] = []

    for character in chars:
        glyph_name = unicode_index.get(ord(character))
        if glyph_name is None:
            missing.append(character)
            continue
        if glyph_name not in glyph_names:
            glyph_names.append(glyph_name)

    return glyph_names, missing


def _merge_group_entry(
    expanded_glyphs: dict[str, dict[str, Any]],
    explicit_glyph_names: set[str],
    glyph_name: str,
    group_payload: dict[str, Any],
) -> None:
    existing = dict(expanded_glyphs.get(glyph_name, {}))
    if glyph_name in explicit_glyph_names:
        merged = dict(group_payload)
        merged.update(existing)
    else:
        merged = existing
        merged.update(group_payload)
    expanded_glyphs[glyph_name] = merged


def expand_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text())

    for family_key, family_manifest in manifest.items():
        explicit_glyphs = {
            glyph_name: dict(config)
            for glyph_name, config in family_manifest.get("glyphs", {}).items()
        }
        expanded_glyphs = dict(explicit_glyphs)
        explicit_glyph_names = set(explicit_glyphs)
        resolved_groups: list[dict[str, Any]] = []

        glyph_groups = family_manifest.get("glyph_groups", [])
        font = None

        for index, group in enumerate(glyph_groups):
            group_name = group.get("name") or f"{family_key}-group-{index + 1}"
            group_members: list[str] = []

            if group.get("glyphs"):
                group_members.extend(str(value) for value in group.get("glyphs", []))

            if group.get("chars"):
                if font is None:
                    source_path = _resolve_source_path(family_manifest["source_path"], path)
                    font = glyphsLib.load(str(source_path))
                char_members, missing_characters = glyph_names_for_chars(font, str(group["chars"]))
                if missing_characters:
                    missing_string = "".join(missing_characters)
                    raise ValueError(
                        f"{family_key}:{group_name}: missing glyphs for characters {missing_string!r}"
                    )
                group_members.extend(char_members)

            seen_members: set[str] = set()
            deduped_members: list[str] = []
            for glyph_name in group_members:
                if glyph_name in seen_members:
                    continue
                seen_members.add(glyph_name)
                deduped_members.append(glyph_name)

            inherit_from = group.get("inherit_from")
            inherited_payload = {}
            if inherit_from:
                inherited_payload = dict(expanded_glyphs.get(inherit_from) or explicit_glyphs.get(inherit_from) or {})
                if not inherited_payload:
                    raise ValueError(
                        f"{family_key}:{group_name}: inherit_from={inherit_from!r} not found"
                    )

            default_payload = dict(group.get("default", {}))
            glyph_overrides = {
                glyph_name: dict(config)
                for glyph_name, config in group.get("glyph_overrides", {}).items()
            }

            for glyph_name in deduped_members:
                group_payload = dict(inherited_payload)
                group_payload.update(default_payload)
                group_payload.update(glyph_overrides.get(glyph_name, {}))
                group_payload["group_name"] = group_name
                if inherit_from:
                    group_payload["inherits_from"] = inherit_from
                _merge_group_entry(
                    expanded_glyphs=expanded_glyphs,
                    explicit_glyph_names=explicit_glyph_names,
                    glyph_name=glyph_name,
                    group_payload=group_payload,
                )

            resolved_groups.append(
                {
                    "name": group_name,
                    "glyph_count": len(deduped_members),
                    "glyphs": deduped_members,
                    "inherit_from": inherit_from,
                }
            )

        family_manifest["glyphs"] = expanded_glyphs
        if resolved_groups:
            family_manifest["resolved_glyph_groups"] = resolved_groups

    return manifest
