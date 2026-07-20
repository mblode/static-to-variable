"""Loader for the static-to-variable project config (``stv.config.json``).

A config captures everything a build needs (family metadata, axes with a
named-instance ladder, per-style donors + ordered masters, glyph strategies,
vertical metrics, and output layout) so the engine can be driven generically
instead of from hardcoded literals.

Paths are resolved against a ``root`` directory that defaults to the config
file's own directory, so a config is portable: copy the config and its donors
anywhere and the relative paths still resolve. ``root`` may be set to point
elsewhere (e.g. ``"../.."`` to keep historical repo-relative paths). The
resolved root is also where repo-internal build artifacts (reports, master
UFOs, the release staging dir) are written. Config files only record relative
paths, so licensed donor sources need not be present for the config to load.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when a v3 static-to-variable project config is invalid."""


@dataclass(frozen=True)
class FamilyMeta:
    name: str
    version: str
    vendor: str
    designer: str
    designer_url: str
    vendor_url: str
    license: str | None = None
    license_url: str | None = None


@dataclass(frozen=True)
class ConfigAxis:
    tag: str
    name: str
    minimum: float
    default: float
    maximum: float
    mapping: tuple[tuple[float, float], ...] = ()
    named_instances: dict[float, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Donor:
    id: str
    name: str
    path: Path
    config_path: str
    location: dict[str, float]
    role: str = "donor"


@dataclass(frozen=True)
class Master:
    name: str
    donor_id: str
    location: dict[str, float]
    default: bool = False


@dataclass(frozen=True)
class Style:
    key: str
    italic: bool
    donors: tuple[Donor, ...]
    source: Path
    config_source: str
    masters: tuple[Master, ...]
    output: Path
    config_output: str
    base_source: Path | None = None
    config_base_source: str | None = None


@dataclass(frozen=True)
class GlyphStrategy:
    strategy: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GlyphConfig:
    freeze: tuple[str, ...] = ()
    strategies: dict[str, GlyphStrategy] = field(default_factory=dict)
    seeds: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class VerticalMetrics:
    ascender: float
    descender: float
    cap_height: float
    x_height: float


@dataclass(frozen=True)
class Discovery:
    dir: str
    pattern: str
    weight_source: str


@dataclass(frozen=True)
class OutputConfig:
    dir: str
    formats: tuple[str, ...]
    release_dir: str


@dataclass(frozen=True)
class ProjectConfig:
    id: str
    version: int
    path: Path
    repo_root: Path
    family: FamilyMeta
    axes: tuple[ConfigAxis, ...]
    styles: dict[str, Style]
    output: OutputConfig
    vertical_metrics: VerticalMetrics | None
    discovery: Discovery | None
    glyphs: GlyphConfig
    normalize: dict[str, bool]
    raw: dict[str, Any]


_VALID_STRATEGIES = {"open_bar", "freeze", "interpolate_neighbors"}


def resolve_style_keys(config: ProjectConfig, style: str) -> list[str]:
    """Expand a ``--style`` argument to config style keys ('all' means every
    style, in config order). Raises ``ConfigError`` for an unknown key."""
    if style != "all" and style not in config.styles:
        raise ConfigError(f"unknown style {style!r}; have {sorted(config.styles)}")
    return list(config.styles) if style == "all" else [style]


def default_donor_path(style: Style) -> Path:
    """Path of the donor backing the style's default master."""
    donor_by_id = {donor.id: donor for donor in style.donors}
    default_master = next(master for master in style.masters if master.default)
    return donor_by_id[default_master.donor_id].path


def load_config(path: str | Path) -> ProjectConfig:
    config_path = Path(path).resolve()
    try:
        raw = json.loads(config_path.read_text())
    except FileNotFoundError as exc:  # noqa: F841
        raise ConfigError(f"{config_path}: config file not found") from None
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{config_path}: invalid JSON: {exc}") from exc

    version = raw.get("version")
    if version != 3:
        raise ConfigError(f"{config_path}: expected version 3, got {version!r}")

    config_id = _required_str(raw, "id", config_path)
    repo_root = _resolve_repo_root(raw, config_path)

    family = _parse_family(_required_dict(raw, "family", config_path), config_path)

    axes = tuple(
        _parse_axis(axis, config_path) for axis in _required_list(raw, "axes", config_path)
    )
    if not axes:
        raise ConfigError(f"{config_path}: at least one axis is required")
    axis_tags = {axis.tag for axis in axes}
    if len(axis_tags) != len(axes):
        raise ConfigError(f"{config_path}: duplicate axis tag(s)")

    raw_styles = _required_dict(raw, "styles", config_path)
    if not raw_styles:
        raise ConfigError(f"{config_path}: at least one style is required")
    styles = {
        key: _parse_style(key, payload, repo_root, axis_tags, config_path)
        for key, payload in sorted(raw_styles.items())
    }

    output = _parse_output(_required_dict(raw, "output", config_path), config_path)

    vertical_metrics = _parse_vertical_metrics(raw.get("verticalMetrics"), config_path)
    discovery = _parse_discovery(raw.get("discovery"), config_path)
    glyphs = _parse_glyphs(raw.get("glyphs"), config_path)
    normalize = _parse_normalize(raw.get("normalize"), config_path)

    return ProjectConfig(
        id=config_id,
        version=version,
        path=config_path,
        repo_root=repo_root,
        family=family,
        axes=axes,
        styles=styles,
        output=output,
        vertical_metrics=vertical_metrics,
        discovery=discovery,
        glyphs=glyphs,
        normalize=normalize,
        raw=raw,
    )


def _resolve_repo_root(raw: dict[str, Any], config_path: Path) -> Path:
    # ``root`` is the canonical field (resolved relative to the config file's
    # directory, defaulting to that directory). ``repoRoot`` is a back-compat
    # alias for configs written before the rename. A missing field means the
    # config's own directory, which is what makes a config portable.
    if "root" in raw and "repoRoot" in raw:
        raise ConfigError(f"{config_path}: set either 'root' or 'repoRoot', not both")
    root_value = raw.get("root", raw.get("repoRoot", "."))
    if not isinstance(root_value, str):
        raise ConfigError(f"{config_path}: root must be a string")
    root = Path(root_value)
    if not root.is_absolute():
        root = config_path.parent / root
    return root.resolve()


def _parse_family(raw: dict[str, Any], config_path: Path) -> FamilyMeta:
    return FamilyMeta(
        name=_required_str(raw, "name", config_path),
        version=_required_str(raw, "version", config_path),
        vendor=_required_str(raw, "vendor", config_path),
        designer=_required_str(raw, "designer", config_path),
        designer_url=_required_str(raw, "designerUrl", config_path),
        vendor_url=_required_str(raw, "vendorUrl", config_path),
        license=_optional_str(raw, "license", config_path),
        license_url=_optional_str(raw, "licenseUrl", config_path),
    )


def _parse_axis(raw: Any, config_path: Path) -> ConfigAxis:
    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path}: axis entries must be objects")

    mapping: list[tuple[float, float]] = []
    for item in raw.get("map", []):
        if not isinstance(item, list | tuple) or len(item) != 2:
            raise ConfigError(f"{config_path}: axis map entries must be [input, output]")
        mapping.append(
            (
                _coerce_number(item[0], "axis.map.input", config_path),
                _coerce_number(item[1], "axis.map.output", config_path),
            )
        )

    minimum = _required_number(raw, "minimum", config_path)
    default = _required_number(raw, "default", config_path)
    maximum = _required_number(raw, "maximum", config_path)
    if not (minimum <= default <= maximum):
        raise ConfigError(
            f"{config_path}: axis default {default} must be within [{minimum}, {maximum}]"
        )

    named_instances = _parse_named_instances(
        raw.get("namedInstances", {}), minimum, maximum, config_path
    )

    return ConfigAxis(
        tag=_required_str(raw, "tag", config_path),
        name=_required_str(raw, "name", config_path),
        minimum=minimum,
        default=default,
        maximum=maximum,
        mapping=tuple(mapping),
        named_instances=named_instances,
    )


def _parse_named_instances(
    raw: Any,
    minimum: float,
    maximum: float,
    config_path: Path,
) -> dict[float, str]:
    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path}: namedInstances must be an object")
    result: dict[float, str] = {}
    for key, value in raw.items():
        try:
            coord = float(key)
        except (TypeError, ValueError):
            raise ConfigError(
                f"{config_path}: namedInstances key {key!r} must be a numeric string"
            ) from None
        if not (minimum <= coord <= maximum):
            raise ConfigError(
                f"{config_path}: namedInstance {key!r} is outside the axis range "
                f"[{minimum}, {maximum}]"
            )
        if not isinstance(value, str) or not value:
            raise ConfigError(
                f"{config_path}: namedInstance {key!r} name must be a non-empty string"
            )
        result[coord] = value
    return result


def _parse_style(
    key: str,
    raw: Any,
    repo_root: Path,
    axis_tags: set[str],
    config_path: Path,
) -> Style:
    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path}: style {key!r} must be an object")

    italic = raw.get("italic", False)
    if not isinstance(italic, bool):
        raise ConfigError(f"{config_path}: style {key!r} italic must be a boolean")

    donors: list[Donor] = []
    donor_ids: set[str] = set()
    for donor in _required_list(raw, "donors", config_path):
        parsed = _parse_donor(donor, repo_root, axis_tags, config_path)
        if parsed.id in donor_ids:
            raise ConfigError(f"{config_path}: style {key!r} has duplicate donor id {parsed.id!r}")
        donor_ids.add(parsed.id)
        donors.append(parsed)
    if not donors:
        raise ConfigError(f"{config_path}: style {key!r} needs at least one donor")

    masters = _parse_masters(
        _required_list(raw, "masters", config_path),
        donor_ids,
        axis_tags,
        key,
        config_path,
    )

    source_value = _required_str(raw, "source", config_path)
    output_value = _required_str(raw, "output", config_path)
    base_source_value = _optional_str(raw, "baseSource", config_path)

    return Style(
        key=key,
        italic=italic,
        donors=tuple(donors),
        source=_resolve_repo_path(repo_root, source_value),
        config_source=source_value,
        masters=masters,
        output=_resolve_repo_path(repo_root, output_value),
        config_output=output_value,
        base_source=(
            _resolve_repo_path(repo_root, base_source_value) if base_source_value else None
        ),
        config_base_source=base_source_value,
    )


def _parse_donor(
    raw: Any,
    repo_root: Path,
    axis_tags: set[str],
    config_path: Path,
) -> Donor:
    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path}: donor entries must be objects")
    location = _parse_location(_required_dict(raw, "location", config_path), axis_tags, config_path)
    path_value = _required_str(raw, "path", config_path)
    return Donor(
        id=_required_str(raw, "id", config_path),
        name=_required_str(raw, "name", config_path),
        path=_resolve_repo_path(repo_root, path_value),
        config_path=path_value,
        location=location,
        role=str(raw.get("role", "donor")),
    )


def _parse_masters(
    raw_masters: list[Any],
    donor_ids: set[str],
    axis_tags: set[str],
    style_key: str,
    config_path: Path,
) -> tuple[Master, ...]:
    if not raw_masters:
        raise ConfigError(f"{config_path}: style {style_key!r} needs at least one master")
    masters: list[Master] = []
    default_count = 0
    for raw in raw_masters:
        if not isinstance(raw, dict):
            raise ConfigError(f"{config_path}: master entries must be objects")
        donor_id = _required_str(raw, "donorId", config_path)
        if donor_id not in donor_ids:
            raise ConfigError(
                f"{config_path}: style {style_key!r} master references unknown donorId {donor_id!r}"
            )
        is_default = raw.get("default", False)
        if not isinstance(is_default, bool):
            raise ConfigError(f"{config_path}: master default must be a boolean")
        if is_default:
            default_count += 1
        masters.append(
            Master(
                name=_required_str(raw, "name", config_path),
                donor_id=donor_id,
                location=_parse_location(
                    _required_dict(raw, "location", config_path),
                    axis_tags,
                    config_path,
                ),
                default=is_default,
            )
        )
    if default_count != 1:
        raise ConfigError(
            f"{config_path}: style {style_key!r} must have exactly one default "
            f"master, found {default_count}"
        )
    return tuple(masters)


def _parse_output(raw: dict[str, Any], config_path: Path) -> OutputConfig:
    formats = raw.get("formats")
    if not isinstance(formats, list) or not formats:
        raise ConfigError(f"{config_path}: output.formats must be a non-empty list")
    for fmt in formats:
        if not isinstance(fmt, str) or not fmt:
            raise ConfigError(f"{config_path}: output.formats entries must be strings")
    return OutputConfig(
        dir=_required_str(raw, "dir", config_path),
        formats=tuple(formats),
        release_dir=_required_str(raw, "releaseDir", config_path),
    )


def _parse_vertical_metrics(raw: Any, config_path: Path) -> VerticalMetrics | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path}: verticalMetrics must be an object")
    return VerticalMetrics(
        ascender=_required_number(raw, "ascender", config_path),
        descender=_required_number(raw, "descender", config_path),
        cap_height=_required_number(raw, "capHeight", config_path),
        x_height=_required_number(raw, "xHeight", config_path),
    )


def _parse_discovery(raw: Any, config_path: Path) -> Discovery | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path}: discovery must be an object")
    return Discovery(
        dir=_required_str(raw, "dir", config_path),
        pattern=_required_str(raw, "pattern", config_path),
        weight_source=_required_str(raw, "weightSource", config_path),
    )


def _parse_glyphs(raw: Any, config_path: Path) -> GlyphConfig:
    if raw is None:
        return GlyphConfig()
    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path}: glyphs must be an object")

    freeze_raw = raw.get("freeze", [])
    if not isinstance(freeze_raw, list):
        raise ConfigError(f"{config_path}: glyphs.freeze must be a list")
    freeze = tuple(_glyph_name(name, "glyphs.freeze", config_path) for name in freeze_raw)

    strategies_raw = raw.get("strategies", {})
    if not isinstance(strategies_raw, dict):
        raise ConfigError(f"{config_path}: glyphs.strategies must be an object")
    strategies: dict[str, GlyphStrategy] = {}
    for name, payload in strategies_raw.items():
        if not isinstance(payload, dict):
            raise ConfigError(f"{config_path}: glyphs.strategies[{name!r}] must be an object")
        strategy = _required_str(payload, "strategy", config_path)
        if strategy not in _VALID_STRATEGIES:
            raise ConfigError(
                f"{config_path}: glyphs.strategies[{name!r}].strategy {strategy!r} "
                f"is not one of {sorted(_VALID_STRATEGIES)}"
            )
        params = payload.get("params", {})
        if not isinstance(params, dict):
            raise ConfigError(
                f"{config_path}: glyphs.strategies[{name!r}].params must be an object"
            )
        strategies[name] = GlyphStrategy(strategy=strategy, params=dict(params))

    seeds_raw = raw.get("seeds", {})
    if not isinstance(seeds_raw, dict):
        raise ConfigError(f"{config_path}: glyphs.seeds must be an object")
    seeds: dict[str, tuple[str, ...]] = {}
    for style_key, names in seeds_raw.items():
        if not isinstance(names, list):
            raise ConfigError(f"{config_path}: glyphs.seeds[{style_key!r}] must be a list")
        seeds[style_key] = tuple(
            _glyph_name(name, f"glyphs.seeds[{style_key!r}]", config_path) for name in names
        )

    return GlyphConfig(freeze=freeze, strategies=strategies, seeds=seeds)


def _parse_normalize(raw: Any, config_path: Path) -> dict[str, bool]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path}: normalize must be an object")
    result: dict[str, bool] = {}
    for key, value in raw.items():
        if not isinstance(value, bool):
            raise ConfigError(f"{config_path}: normalize.{key} must be a boolean")
        result[key] = value
    return result


def _parse_location(
    raw: dict[str, Any],
    axis_tags: set[str],
    config_path: Path,
) -> dict[str, float]:
    unknown_axes = sorted(set(raw) - axis_tags)
    if unknown_axes:
        raise ConfigError(f"{config_path}: unknown axis tag(s): {', '.join(unknown_axes)}")
    missing_axes = sorted(axis_tags - set(raw))
    if missing_axes:
        raise ConfigError(f"{config_path}: missing axis tag(s): {', '.join(missing_axes)}")
    return {
        axis_tag: _coerce_number(raw[axis_tag], f"location.{axis_tag}", config_path)
        for axis_tag in sorted(raw)
    }


def _resolve_repo_path(repo_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (repo_root / path).resolve()


def _glyph_name(value: Any, key: str, config_path: Path) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{config_path}: {key} entries must be non-empty strings")
    return value


def _required_str(raw: dict[str, Any], key: str, config_path: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{config_path}: {key} must be a non-empty string")
    return value


def _optional_str(raw: dict[str, Any], key: str, config_path: Path) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{config_path}: {key} must be a non-empty string when present")
    return value


def _required_number(raw: dict[str, Any], key: str, config_path: Path) -> float:
    return _coerce_number(raw.get(key), key, config_path)


def _coerce_number(value: Any, key: str, config_path: Path) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"{config_path}: {key} must be a number")
    return float(value)


def _required_list(raw: dict[str, Any], key: str, config_path: Path) -> list[Any]:
    value = raw.get(key)
    if not isinstance(value, list):
        raise ConfigError(f"{config_path}: {key} must be a list")
    return value


def _required_dict(raw: dict[str, Any], key: str, config_path: Path) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{config_path}: {key} must be an object")
    return value
