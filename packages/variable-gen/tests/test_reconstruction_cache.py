"""Deterministic, fail-closed reconstruction-cache behavior."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from variable_gen import rebuild as rebuild_module
from variable_gen.config import GlyphStrategy
from variable_gen.rebuild import reconstruct_all
from variable_gen.reconstruction_cache import (
    ReconstructionCacheContext,
    ReconstructionCacheStats,
    load_reconstruction,
    reconstruction_cache_key,
    store_reconstruction,
)


def _square(size: float) -> list:
    return [
        [
            ("moveTo", [(0, 0)]),
            ("lineTo", [(size, 0)]),
            ("lineTo", [(size, size)]),
            ("lineTo", [(0, size)]),
            ("closePath", []),
        ]
    ]


def _jobs() -> dict[str, dict[float, list]]:
    return {"square": {100.0: _square(80), 400.0: _square(100)}}


def _context(opsz: float = 16.0) -> ReconstructionCacheContext:
    return ReconstructionCacheContext(
        primary_tag="wght",
        axis_locations=(
            (("wght", 100.0), ("opsz", opsz)),
            (("wght", 400.0), ("opsz", opsz)),
        ),
        reference_location=(("wght", 400.0), ("opsz", opsz)),
    )


def _strategies(relief: int = 3) -> dict[str, GlyphStrategy]:
    return {
        "square": GlyphStrategy(
            strategy="open_bar",
            params={"letter": "O", "relief": relief},
        )
    }


def test_cold_miss_then_warm_hit_is_byte_stable(tmp_path: Path) -> None:
    cold_stats = ReconstructionCacheStats()
    warm_stats = ReconstructionCacheStats()

    with patch("variable_gen.rebuild.reconstruct", wraps=rebuild_module.reconstruct) as compute:
        cold = reconstruct_all(
            _jobs(),
            400.0,
            1,
            cache_dir=tmp_path,
            cache_context=_context(),
            strategies=_strategies(),
            cache_stats=cold_stats,
        )
        cache_file = next(tmp_path.rglob("*.json"))
        cold_bytes = cache_file.read_bytes()

        warm = reconstruct_all(
            _jobs(),
            400.0,
            1,
            cache_dir=tmp_path,
            cache_context=_context(),
            strategies=_strategies(),
            cache_stats=warm_stats,
        )

    assert compute.call_count == 1
    assert cold == warm
    assert cache_file.read_bytes() == cold_bytes
    assert cold_stats == ReconstructionCacheStats(hits=0, misses=1, writes=1)
    assert warm_stats == ReconstructionCacheStats(hits=1, misses=0, writes=0)


def test_key_covers_outlines_axes_reference_strategy_and_implementation() -> None:
    common = {
        "glyph_name": "square",
        "outlines_by_pos": _jobs()["square"],
        "reference_pos": 400.0,
        "context": _context(),
        "strategy": {"strategy": "open_bar", "params": {"relief": 3}},
        "implementation_digest": "implementation-a",
    }
    baseline = reconstruction_cache_key(**common)
    assert baseline is not None

    changed_outlines = {**common, "outlines_by_pos": {100.0: _square(81), 400.0: _square(100)}}
    changed_axes = {**common, "context": _context(opsz=12.0)}
    changed_reference = {**common, "reference_pos": 100.0}
    changed_strategy = {
        **common,
        "strategy": {"strategy": "open_bar", "params": {"relief": 5}},
    }
    changed_implementation = {**common, "implementation_digest": "implementation-b"}

    assert {
        reconstruction_cache_key(**changed_outlines),
        reconstruction_cache_key(**changed_axes),
        reconstruction_cache_key(**changed_reference),
        reconstruction_cache_key(**changed_strategy),
        reconstruction_cache_key(**changed_implementation),
    }.isdisjoint({baseline})


def test_corrupt_entry_recomputes_and_incomplete_context_bypasses(tmp_path: Path) -> None:
    initial = ReconstructionCacheStats()
    reconstruct_all(
        _jobs(),
        400.0,
        1,
        cache_dir=tmp_path,
        cache_context=_context(),
        strategies=_strategies(),
        cache_stats=initial,
    )
    cache_file = next(tmp_path.rglob("*.json"))
    tampered = json.loads(cache_file.read_text())
    tampered["result"]["info"]["stage"] = "tampered"
    cache_file.write_text(json.dumps(tampered))

    repaired = ReconstructionCacheStats()
    reconstruct_all(
        _jobs(),
        400.0,
        1,
        cache_dir=tmp_path,
        cache_context=_context(),
        strategies=_strategies(),
        cache_stats=repaired,
    )
    assert repaired == ReconstructionCacheStats(hits=0, misses=1, writes=1)
    assert json.loads(cache_file.read_text())["schema"] == 1

    bypassed = ReconstructionCacheStats()
    reconstruct_all(
        _jobs(),
        400.0,
        1,
        cache_dir=tmp_path / "incomplete",
        cache_context=None,
        strategies=_strategies(),
        cache_stats=bypassed,
    )
    assert bypassed == ReconstructionCacheStats(bypassed=1)
    assert not (tmp_path / "incomplete").exists()


def test_all_offcurve_quadratic_round_trips_without_losing_implied_point(
    tmp_path: Path,
) -> None:
    key = "a" * 64
    result = (
        {
            400.0: [
                [
                    ("qCurveTo", [(0, 0), (100, 0), (100, 100), None]),
                    ("closePath", []),
                ]
            ]
        },
        {"stage": "compatible"},
    )
    store_reconstruction(tmp_path, key, result)
    assert load_reconstruction(tmp_path, key) == result
