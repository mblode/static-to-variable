"""Paths, weight mapping, seed lists, and font-loading helpers for glyph QA.

Everything project-specific (donor sources, weight ladder, per-style variable
font outputs, seed glyph lists, and the set of style keys) is derived from a v3
``stv.config.json`` rather than hardcoded. The active config comes from the
``STV_CONFIG`` environment variable (or a ``--config`` flag the CLI entrypoints
forward via :func:`set_config`), defaulting to the bundled Glide example so the
existing Glide flows keep working unchanged.

Reads from packages/variable-gen reports; writes only inside packages/glyph-forge-engine/.
Keep side-effect-free at import time so the CLIs can import cheaply — the config
is loaded lazily on first use.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cache, lru_cache
from pathlib import Path
from typing import Literal

from fontTools.agl import toUnicode
from fontTools.ttLib import TTFont
from variable_gen.config import ProjectConfig, load_config

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = PACKAGE_ROOT / "public-cache" / "svg"
MANIFEST_PATH = PACKAGE_ROOT / "manifests" / "broken-glyphs.json"

VARIABLE_GEN_REPORTS = REPO_ROOT / "packages" / "variable-gen" / "reports"
TRIAGE_MANIFEST = REPO_ROOT / "packages" / "variable-gen" / "manifests" / "circular-triage.json"

# Default config: the bundled Glide example. Override with STV_CONFIG (env) or a
# --config flag on the CLI entrypoints.
DEFAULT_CONFIG_PATH = REPO_ROOT / "examples" / "glide" / "stv.config.json"

# A style key ("roman" / "italic" / ...) — validated against config.styles.
Family = str
CellSource = Literal["donor", "glide"]


@dataclass(frozen=True)
class DonorWeight:
    """A weight on the QA comparison ladder, from a config donor location."""

    name: str
    wght: int


class ProjectContext:
    """Config-derived view of the values the QA engine needs.

    Wraps a loaded :class:`variable_gen.config.ProjectConfig` and exposes the
    style keys, donor weight ladder, per-family donor OTF paths, per-family
    variable-font outputs, and seed glyph lists.
    """

    def __init__(self, config: ProjectConfig) -> None:
        self.config = config

    @property
    def families(self) -> tuple[str, ...]:
        return tuple(self.config.styles.keys())

    def require_family(self, family: str) -> None:
        if family not in self.config.styles:
            raise ValueError(f"unknown style {family!r}; config defines {sorted(self.families)}")

    def donor_weights(self, family: str | None = None) -> tuple[DonorWeight, ...]:
        """Weight ladder for the QA comparison cells.

        With ``family`` set, returns that style's donors; otherwise the union of
        weights across every style (first style to declare a weight names it).
        Sorted ascending by weight.
        """
        if family is not None:
            self.require_family(family)
            styles = [self.config.styles[family]]
        else:
            styles = list(self.config.styles.values())

        by_wght: dict[int, str] = {}
        for style in styles:
            for donor in style.donors:
                wght = donor.location.get("wght")
                if wght is None:
                    continue
                by_wght.setdefault(int(wght), donor.name)
        return tuple(DonorWeight(name=by_wght[w], wght=w) for w in sorted(by_wght))

    def master_wghts(self, family: str | None = None) -> tuple[int, ...]:
        """The variable-font master locations along the weight axis."""
        if family is not None:
            self.require_family(family)
            styles = [self.config.styles[family]]
        else:
            styles = list(self.config.styles.values())
        wghts: set[int] = set()
        for style in styles:
            for master in style.masters:
                wght = master.location.get("wght")
                if wght is not None:
                    wghts.add(int(wght))
        return tuple(sorted(wghts))

    def donor_otf(self, family: str, wght: int) -> Path | None:
        """Path to the donor source for ``family`` at ``wght``, or None."""
        self.require_family(family)
        for donor in self.config.styles[family].donors:
            if donor.location.get("wght") == wght:
                return donor.path
        return None

    def vf_path(self, family: str) -> Path:
        """Compiled variable-font output for ``family`` (config styles[].output)."""
        self.require_family(family)
        return self.config.styles[family].output

    def seeds(self, family: str) -> tuple[str, ...]:
        """Seed glyph list for ``family``.

        Falls back to every encoded glyph in the compiled variable font when the
        config declares no seeds for the style.
        """
        self.require_family(family)
        configured = self.config.glyphs.seeds.get(family)
        if configured:
            return tuple(configured)
        cmap = _cmap(self.vf_path(family))
        return tuple(dict.fromkeys(cmap.values()))


def _resolve_config_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    if candidate.exists():
        return candidate.resolve()
    return (REPO_ROOT / candidate).resolve()


def _default_config_path() -> Path:
    env = os.environ.get("STV_CONFIG")
    if env:
        return _resolve_config_path(env)
    return DEFAULT_CONFIG_PATH


_ACTIVE_CONTEXT: ProjectContext | None = None


def context() -> ProjectContext:
    """The active :class:`ProjectContext`, loading the default config on demand."""
    global _ACTIVE_CONTEXT
    if _ACTIVE_CONTEXT is None:
        _ACTIVE_CONTEXT = ProjectContext(load_config(_default_config_path()))
    return _ACTIVE_CONTEXT


def set_config(path: str | Path) -> ProjectContext:
    """Point the engine at a specific config (used by --config CLI flags)."""
    global _ACTIVE_CONTEXT
    _ACTIVE_CONTEXT = ProjectContext(load_config(_resolve_config_path(path)))
    return _ACTIVE_CONTEXT


def families() -> tuple[str, ...]:
    return context().families


def donor_weights(family: str | None = None) -> tuple[DonorWeight, ...]:
    return context().donor_weights(family)


def master_wghts(family: str | None = None) -> tuple[int, ...]:
    return context().master_wghts(family)


def donor_otf(family: str, wght: int) -> Path | None:
    return context().donor_otf(family, wght)


def vf_path(family: str) -> Path:
    return context().vf_path(family)


def seeds(family: str) -> tuple[str, ...]:
    return context().seeds(family)


def normalise_name(raw: str) -> str:
    """User writes /agrave.ss02; canonicalise to agrave.ss02."""
    return raw.lstrip("/").strip()


def is_uni_codepoint_name(name: str) -> bool:
    if not name.startswith("uni") or len(name) != 7:
        return False
    try:
        int(name[3:], 16)
    except ValueError:
        return False
    return True


@lru_cache(maxsize=32)
def load_font(path: Path) -> TTFont:
    return TTFont(path)


@cache
def _cmap(path: Path) -> dict[int, str]:
    return load_font(path).getBestCmap()


def resolve_glyph_name(raw: str, font_path: Path) -> str | None:
    """Resolve a seed entry to a glyph name valid for the given font, or None."""
    canon = normalise_name(raw)
    if not canon:
        return None
    font = load_font(font_path)
    order = set(font.getGlyphOrder())
    cmap = _cmap(font_path)
    if is_uni_codepoint_name(canon):
        glyph = cmap.get(int(canon[3:], 16))
        if glyph and glyph in order:
            return glyph
    # Direct name match first (covers /agrave.ss02, f_f_i, etc.).
    if canon in order:
        return canon
    # Single character → cmap lookup.
    if len(canon) == 1:
        glyph = cmap.get(ord(canon))
        if glyph and glyph in order:
            return glyph
    if "." in canon:
        base_name, suffix = canon.split(".", 1)
        try:
            unicode_value = toUnicode(base_name)
        except KeyError:
            unicode_value = ""
        if len(unicode_value) == 1:
            glyph = cmap.get(ord(unicode_value))
            suffixed = f"{glyph}.{suffix}" if glyph else ""
            if suffixed in order:
                return suffixed
    if "." not in canon:
        # Glyphs sources and triage manifests often use friendly Glyphs/AGL names
        # while compiled TTFs may use production names, e.g. ncommaaccent -> uni0146.
        try:
            unicode_value = toUnicode(canon)
        except KeyError:
            unicode_value = ""
        if len(unicode_value) == 1:
            glyph = cmap.get(ord(unicode_value))
            if glyph and glyph in order:
                return glyph
    return None


def feature_tags(glyph_name: str) -> list[str]:
    """Extract suffixes like ss02, ordn, tf, case, uc, numr, dnom, latn_TRK."""
    parts = glyph_name.split(".")
    if len(parts) <= 1:
        return []
    return [p for p in parts[1:] if p]


def glyph_unicode(glyph_name: str, font_path: Path) -> str | None:
    """Reverse-lookup a single Unicode codepoint for a glyph, if any."""
    cmap = _cmap(font_path)
    for cp, name in cmap.items():
        if name == glyph_name:
            return f"U+{cp:04X}"
    return None
