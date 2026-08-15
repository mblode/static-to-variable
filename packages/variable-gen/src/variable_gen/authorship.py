"""Fail-closed provenance for independently authored source master layers.

The normal static-to-variable source is disposable: ``rebuild`` derives every
master from the configured donors.  A project may apply durable, reviewed
drawing records after that rebuild, though.  Those layers carry
``OPTICAL_AUTHORSHIP_KEY`` in Glyphs ``userData`` so ``build`` can distinguish
them from generated geometry without guessing from coordinate differences.

Authorship is weight-row-complete. Once one glyph layer in an optical row is
marked, every configured weight master in that row must be marked. This makes a
missing Thin or ExtraBlack drawing an explicit error instead of silently
projecting the Regular drawing or replacing it with donor geometry. A
weight-pruned optical lab treats each full location as complete.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import glyphsLib

from variable_gen.common import PipelineError
from variable_gen.config import ProjectConfig

OPTICAL_AUTHORSHIP_KEY = "com.mblode.stv.opticalAuthorship"
_PROVENANCE_RE = re.compile(r"manual:[0-9a-f]{64}\Z")

AxisLocation = tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class AuthoredSource:
    """Validated authored layers, indexed by glyph and full axis location."""

    layers: dict[str, dict[AxisLocation, str]]
    rows: dict[str, frozenset[AxisLocation]]

    @property
    def glyphs(self) -> frozenset[str]:
        return frozenset(self.layers)

    def has_glyph(self, glyph_name: str) -> bool:
        return glyph_name in self.layers


def _axis_location(axis_tags: tuple[str, ...], values) -> AxisLocation:
    return tuple((tag, float(value)) for tag, value in zip(axis_tags, values, strict=True))


def _without(location: AxisLocation, tag: str) -> AxisLocation:
    return tuple(item for item in location if item[0] != tag)


def _describe(location: AxisLocation) -> str:
    return ", ".join(f"{tag}={value:g}" for tag, value in location) or "default row"


def inspect_authored_source(config: ProjectConfig, style_key: str) -> AuthoredSource:
    """Load and validate source-layer authorship for one style.

    The marker value is deliberately content-addressed (``manual:<sha256>``).
    The engine does not infer authorship from changed coordinates: only the
    drawing pipeline that owns the reviewed record may set the marker.
    """

    style = config.styles[style_key]
    axis_tags = tuple(axis.tag for axis in config.axes)
    # Optical master rows are completed across weight. In a deliberately
    # weight-pruned drawing lab (for example Regular-only opsz proofs), each
    # full location is already complete; Text must not imply authored UI and
    # Display drawings.
    primary_tag = "wght" if "wght" in axis_tags else None
    configured = {
        tuple((tag, float(master.location[tag])) for tag in axis_tags): master
        for master in style.masters
    }
    configured_by_name = {
        master.name: tuple((tag, float(master.location[tag])) for tag in axis_tags)
        for master in style.masters
    }
    configured_rows: dict[AxisLocation, set[AxisLocation]] = {}
    for location in configured:
        row = _without(location, primary_tag) if primary_tag is not None else location
        configured_rows.setdefault(row, set()).add(location)

    with style.source.open(encoding="utf-8") as source_file:
        font = glyphsLib.load(source_file)
    source_locations = {}
    for master in font.masters:
        master_location = configured_by_name.get(master.name)
        if master_location is None and len(master.axes) == len(axis_tags):
            master_location = _axis_location(axis_tags, master.axes)
        if master_location is not None:
            source_locations[master.id] = master_location

    layers: dict[str, dict[AxisLocation, str]] = {}
    rows: dict[str, set[AxisLocation]] = {}
    errors: list[str] = []
    for glyph in font.glyphs:
        marked: dict[AxisLocation, str] = {}
        for layer in glyph.layers:
            provenance = layer.userData.get(OPTICAL_AUTHORSHIP_KEY)
            if provenance is None:
                continue
            source_location = source_locations.get(layer.layerId)
            if source_location is None or source_location not in configured:
                errors.append(
                    f"{glyph.name}: authored marker is attached to an unconfigured master layer "
                    f"{layer.layerId!r}"
                )
                continue
            if not isinstance(provenance, str) or not _PROVENANCE_RE.fullmatch(provenance):
                errors.append(
                    f"{glyph.name} at {_describe(source_location)}: invalid "
                    f"{OPTICAL_AUTHORSHIP_KEY} "
                    "(expected manual:<64 lowercase hex chars>)"
                )
                continue
            marked[source_location] = provenance

        if not marked:
            continue
        touched_rows = {
            _without(location, primary_tag) if primary_tag is not None else location
            for location in marked
        }
        for row in sorted(touched_rows):
            expected = configured_rows[row]
            missing = expected - set(marked)
            if missing:
                missing_descriptions = []
                for location in sorted(missing):
                    master = configured[location]
                    missing_descriptions.append(f"{_describe(location)} ({master.name})")
                errors.append(
                    f"{glyph.name}: incomplete authored row {_describe(row)}; missing "
                    + ", ".join(missing_descriptions)
                )
            rows.setdefault(glyph.name, set()).add(row)
        layers[glyph.name] = marked

    if errors:
        lines = [f"[{style_key}] invalid optical authorship:"]
        lines.extend(f"  {error}" for error in sorted(errors))
        raise PipelineError("\n".join(lines))
    return AuthoredSource(
        layers=layers,
        rows={name: frozenset(value) for name, value in rows.items()},
    )
