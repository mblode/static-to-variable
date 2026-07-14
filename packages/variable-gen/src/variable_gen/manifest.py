from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ManifestError(ValueError):
    """Raised when a static-to-variable manifest is invalid."""


@dataclass(frozen=True)
class Axis:
    tag: str
    name: str
    minimum: float
    default: float
    maximum: float
    donor_values: tuple[float, ...] = ()
    output_values: tuple[float, ...] = ()
    mapping: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class DonorSource:
    id: str
    name: str
    path: Path
    manifest_path: str
    location: dict[str, float]
    role: str = "donor"
    expected_sha256: str | None = None


@dataclass(frozen=True)
class GeneratedSource:
    id: str
    path: Path
    manifest_path: str
    role: str
    master_locations: tuple[dict[str, float], ...]


@dataclass(frozen=True)
class Family:
    key: str
    name: str
    style: str
    donors: tuple[DonorSource, ...]
    generated_sources: tuple[GeneratedSource, ...] = ()


@dataclass(frozen=True)
class StaticToVariableManifest:
    id: str
    version: int
    path: Path
    repo_root: Path
    axes: tuple[Axis, ...]
    families: dict[str, Family]
    raw: dict[str, Any]


def load_manifest(path: str | Path) -> StaticToVariableManifest:
    manifest_path = Path(path).resolve()
    raw = json.loads(manifest_path.read_text())

    version = raw.get("version")
    if version != 2:
        raise ManifestError(f"{manifest_path}: expected version 2, got {version!r}")

    manifest_id = _required_str(raw, "id", manifest_path)
    repo_root = _resolve_repo_root(raw, manifest_path)

    axes = tuple(
        _parse_axis(axis, manifest_path) for axis in _required_list(raw, "axes", manifest_path)
    )
    axis_tags = {axis.tag for axis in axes}
    if not axis_tags:
        raise ManifestError(f"{manifest_path}: at least one axis is required")

    raw_families = _required_dict(raw, "families", manifest_path)
    families = {
        family_key: _parse_family(family_key, payload, repo_root, axis_tags, manifest_path)
        for family_key, payload in sorted(raw_families.items())
    }
    if not families:
        raise ManifestError(f"{manifest_path}: at least one family is required")

    return StaticToVariableManifest(
        id=manifest_id,
        version=version,
        path=manifest_path,
        repo_root=repo_root,
        axes=axes,
        families=families,
        raw=raw,
    )


def _resolve_repo_root(raw: dict[str, Any], manifest_path: Path) -> Path:
    repo_root_value = raw.get("repo_root", "../../..")
    if not isinstance(repo_root_value, str):
        raise ManifestError(f"{manifest_path}: repo_root must be a string")
    repo_root = Path(repo_root_value)
    if not repo_root.is_absolute():
        repo_root = manifest_path.parent / repo_root
    return repo_root.resolve()


def _parse_axis(raw: Any, manifest_path: Path) -> Axis:
    if not isinstance(raw, dict):
        raise ManifestError(f"{manifest_path}: axis entries must be objects")

    mapping: list[tuple[float, float]] = []
    for item in raw.get("map", []):
        if not isinstance(item, list | tuple) or len(item) != 2:
            raise ManifestError(f"{manifest_path}: axis map entries must be [input, output]")
        mapping.append(
            (
                _coerce_number(item[0], "axis.map.input", manifest_path),
                _coerce_number(item[1], "axis.map.output", manifest_path),
            )
        )

    return Axis(
        tag=_required_str(raw, "tag", manifest_path),
        name=_required_str(raw, "name", manifest_path),
        minimum=_required_number(raw, "minimum", manifest_path),
        default=_required_number(raw, "default", manifest_path),
        maximum=_required_number(raw, "maximum", manifest_path),
        donor_values=_number_tuple(raw, "donor_values", manifest_path),
        output_values=_number_tuple(raw, "output_values", manifest_path),
        mapping=tuple(mapping),
    )


def _parse_family(
    family_key: str,
    raw: Any,
    repo_root: Path,
    axis_tags: set[str],
    manifest_path: Path,
) -> Family:
    if not isinstance(raw, dict):
        raise ManifestError(f"{manifest_path}: family {family_key!r} must be an object")

    donors: list[DonorSource] = []
    seen_ids: set[str] = set()
    for donor in _required_list(raw, "donors", manifest_path):
        parsed = _parse_donor(donor, repo_root, axis_tags, manifest_path)
        if parsed.id in seen_ids:
            raise ManifestError(f"{manifest_path}: duplicate donor id {parsed.id!r}")
        seen_ids.add(parsed.id)
        donors.append(parsed)

    generated_sources = tuple(
        _parse_generated_source(source, repo_root, axis_tags, manifest_path)
        for source in raw.get("generated_sources", [])
    )

    return Family(
        key=family_key,
        name=_required_str(raw, "name", manifest_path),
        style=_required_str(raw, "style", manifest_path),
        donors=tuple(donors),
        generated_sources=generated_sources,
    )


def _parse_donor(
    raw: Any,
    repo_root: Path,
    axis_tags: set[str],
    manifest_path: Path,
) -> DonorSource:
    if not isinstance(raw, dict):
        raise ManifestError(f"{manifest_path}: donor entries must be objects")

    location = _parse_location(
        _required_dict(raw, "location", manifest_path),
        axis_tags,
        manifest_path,
    )
    manifest_path_value = _required_str(raw, "path", manifest_path)
    return DonorSource(
        id=_required_str(raw, "id", manifest_path),
        name=_required_str(raw, "name", manifest_path),
        path=_resolve_repo_path(repo_root, manifest_path_value),
        manifest_path=manifest_path_value,
        location=location,
        role=str(raw.get("role", "donor")),
        expected_sha256=_optional_str(raw, "sha256", manifest_path),
    )


def _parse_generated_source(
    raw: Any,
    repo_root: Path,
    axis_tags: set[str],
    manifest_path: Path,
) -> GeneratedSource:
    if not isinstance(raw, dict):
        raise ManifestError(f"{manifest_path}: generated source entries must be objects")

    raw_locations = raw.get("master_locations", [])
    if not isinstance(raw_locations, list):
        raise ManifestError(f"{manifest_path}: master_locations must be a list")
    master_locations = tuple(
        _parse_location(location, axis_tags, manifest_path) for location in raw_locations
    )
    manifest_path_value = _required_str(raw, "path", manifest_path)
    return GeneratedSource(
        id=_required_str(raw, "id", manifest_path),
        path=_resolve_repo_path(repo_root, manifest_path_value),
        manifest_path=manifest_path_value,
        role=str(raw.get("role", "generated_repair_target")),
        master_locations=master_locations,
    )


def _parse_location(
    raw: dict[str, Any],
    axis_tags: set[str],
    manifest_path: Path,
) -> dict[str, float]:
    unknown_axes = sorted(set(raw) - axis_tags)
    if unknown_axes:
        raise ManifestError(f"{manifest_path}: unknown axis tag(s): {', '.join(unknown_axes)}")
    missing_axes = sorted(axis_tags - set(raw))
    if missing_axes:
        raise ManifestError(f"{manifest_path}: missing axis tag(s): {', '.join(missing_axes)}")
    return {
        axis_tag: _coerce_number(
            raw[axis_tag],
            f"location.{axis_tag}",
            manifest_path,
        )
        for axis_tag in sorted(raw)
    }


def _resolve_repo_path(repo_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (repo_root / path).resolve()


def _required_str(raw: dict[str, Any], key: str, manifest_path: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{manifest_path}: {key} must be a non-empty string")
    return value


def _optional_str(raw: dict[str, Any], key: str, manifest_path: Path) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{manifest_path}: {key} must be a non-empty string when present")
    return value


def _required_number(raw: dict[str, Any], key: str, manifest_path: Path) -> float:
    value = raw.get(key)
    return _coerce_number(value, key, manifest_path)


def _coerce_number(value: Any, key: str, manifest_path: Path) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ManifestError(f"{manifest_path}: {key} must be a number")
    return float(value)


def _number_tuple(
    raw: dict[str, Any],
    key: str,
    manifest_path: Path,
) -> tuple[float, ...]:
    values = raw.get(key, [])
    if not isinstance(values, list):
        raise ManifestError(f"{manifest_path}: {key} must be a list")
    return tuple(_coerce_number(value, f"{key}[]", manifest_path) for value in values)


def _required_list(raw: dict[str, Any], key: str, manifest_path: Path) -> list[Any]:
    value = raw.get(key)
    if not isinstance(value, list):
        raise ManifestError(f"{manifest_path}: {key} must be a list")
    return value


def _required_dict(raw: dict[str, Any], key: str, manifest_path: Path) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ManifestError(f"{manifest_path}: {key} must be an object")
    return value
