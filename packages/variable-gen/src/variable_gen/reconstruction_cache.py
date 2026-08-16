"""Content-addressed cache for pure per-glyph reconstruction results."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from math import isfinite
from pathlib import Path
from typing import Any, TypeGuard

CACHE_SCHEMA = 1
CACHE_ENV = "STV_RECONSTRUCTION_CACHE"
ReconstructionResult = tuple[dict[float, list] | None, dict[str, Any]]


@dataclass(frozen=True)
class ReconstructionCacheContext:
    """Complete design-space context for one one-dimensional reconstruction row."""

    primary_tag: str
    axis_locations: tuple[tuple[tuple[str, float], ...], ...]
    reference_location: tuple[tuple[str, float], ...]


@dataclass
class ReconstructionCacheStats:
    hits: int = 0
    misses: int = 0
    writes: int = 0
    bypassed: int = 0
    errors: int = 0


def cache_dir_from_environment() -> Path | None:
    """Shared local cache directory, or ``None`` when explicitly disabled."""

    override = os.environ.get(CACHE_ENV)
    if override is not None:
        if override.strip().lower() in {"", "0", "false", "off", "none"}:
            return None
        return Path(override).expanduser().resolve()

    if sys.platform == "darwin":
        base = Path.home() / "Library/Caches"
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "static-to-variable/reconstruction-v1"


@lru_cache(maxsize=1)
def reconstruction_implementation_digest() -> str | None:
    """Hash every implementation input whose change must invalidate results.

    Failure to read any source or dependency version disables caching. Reusing a
    stale result is worse than recomputing it.
    """

    from variable_gen import audit_support, outlines, reconstruct_compatible

    digest = hashlib.sha256(f"schema={CACHE_SCHEMA}\n".encode())
    digest.update(f"python={sys.implementation.name}-{sys.version_info[:2]}\n".encode())
    for package in ("fonttools", "skia-pathops"):
        try:
            package_version = version(package)
        except PackageNotFoundError:
            return None
        digest.update(f"{package}={package_version}\n".encode())

    for module in (reconstruct_compatible, audit_support, outlines):
        source = getattr(module, "__file__", None)
        if not source:
            return None
        path = Path(source)
        try:
            digest.update(path.read_bytes())
        except OSError:
            return None
        digest.update(b"\0")
    return digest.hexdigest()


def reconstruction_cache_key(
    *,
    glyph_name: str,
    outlines_by_pos: dict[float, list],
    reference_pos: float,
    context: ReconstructionCacheContext | None,
    strategy: dict[str, Any] | None,
    implementation_digest: str | None = None,
) -> str | None:
    """Return a deterministic key, failing closed when context is incomplete."""

    implementation_digest = implementation_digest or reconstruction_implementation_digest()
    if implementation_digest is None or context is None or strategy is None:
        return None
    payload = {
        "schema": CACHE_SCHEMA,
        "implementation": implementation_digest,
        "glyph": glyph_name,
        "outlines": [
            {"position": position, "contours": contours}
            for position, contours in sorted(outlines_by_pos.items())
        ],
        "reference_position": reference_pos,
        "primary_tag": context.primary_tag,
        "axis_locations": context.axis_locations,
        "reference_location": context.reference_location,
        "strategy": strategy,
    }
    try:
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def load_reconstruction(cache_dir: Path, key: str) -> ReconstructionResult | None:
    path = _cache_path(cache_dir, key)
    try:
        payload = json.loads(path.read_text())
        if payload.get("schema") != CACHE_SCHEMA or payload.get("key") != key:
            return None
        encoded_result = payload.get("result")
        if payload.get("result_sha256") != _json_digest(encoded_result):
            return None
        return _decode_result(encoded_result)
    except (AttributeError, json.JSONDecodeError, OSError, TypeError, ValueError):
        return None


def store_reconstruction(cache_dir: Path, key: str, result: ReconstructionResult) -> None:
    path = _cache_path(cache_dir, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded_result = _encode_result(result)
    payload = {
        "schema": CACHE_SCHEMA,
        "key": key,
        "result": encoded_result,
        "result_sha256": _json_digest(encoded_result),
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    temporary: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=f".{key}.", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(fd, "w") as handle:
            handle.write(encoded)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / key[:2] / f"{key}.json"


def _json_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _encode_result(result: ReconstructionResult) -> dict[str, Any]:
    outlines, info = result
    return {
        "outlines": (
            None
            if outlines is None
            else [
                {"position": position, "contours": contours}
                for position, contours in sorted(outlines.items())
            ]
        ),
        "info": info,
    }


def _decode_result(payload: Any) -> ReconstructionResult:
    if not isinstance(payload, dict) or not isinstance(payload.get("info"), dict):
        raise ValueError("malformed reconstruction cache result")
    encoded_outlines = payload.get("outlines")
    if encoded_outlines is None:
        return None, payload["info"]
    if not isinstance(encoded_outlines, list):
        raise ValueError("malformed cached outlines")
    outlines: dict[float, list] = {}
    for entry in encoded_outlines:
        if not isinstance(entry, dict):
            raise ValueError("malformed cached outline entry")
        position = entry.get("position")
        if not _finite_number(position):
            raise ValueError("malformed cached axis position")
        outlines[position] = _decode_contours(entry.get("contours"))
    return outlines, payload["info"]


def _decode_contours(payload: Any) -> list:
    if not isinstance(payload, list):
        raise ValueError("malformed cached contours")
    contours = []
    for encoded_contour in payload:
        if not isinstance(encoded_contour, list):
            raise ValueError("malformed cached contour")
        contour = []
        for encoded_segment in encoded_contour:
            if not isinstance(encoded_segment, list) or len(encoded_segment) != 2:
                raise ValueError("malformed cached segment")
            operation, encoded_points = encoded_segment
            if operation not in {
                "moveTo",
                "lineTo",
                "curveTo",
                "qCurveTo",
                "closePath",
                "endPath",
            } or not isinstance(encoded_points, list):
                raise ValueError("malformed cached segment operation")
            points: list[tuple[Any, Any] | None] = []
            for point in encoded_points:
                if point is None and operation == "qCurveTo":
                    points.append(None)
                    continue
                if (
                    not isinstance(point, list)
                    or len(point) != 2
                    or not all(_finite_number(value) for value in point)
                ):
                    raise ValueError("malformed cached point")
                points.append((point[0], point[1]))
            contour.append((operation, points))
        contours.append(contour)
    return contours


def _finite_number(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool) and isfinite(value)
