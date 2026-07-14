from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, TypeVar

FamilyT = TypeVar("FamilyT")


def select_families(
    families: dict[str, FamilyT],
    family_filter: str,
) -> dict[str, FamilyT]:
    if family_filter == "all":
        return dict(sorted(families.items()))
    if family_filter not in families:
        available = ", ".join(sorted(families))
        raise ValueError(f"unknown family {family_filter!r}; available: {available}")
    return {family_filter: families[family_filter]}


def write_json_report(report: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def display_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_artifact_path(repo_root: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return repo_root / path
