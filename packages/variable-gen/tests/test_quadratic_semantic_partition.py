from __future__ import annotations

import pytest

from variable_gen.quadratic_reference import _reference_count_spline
from variable_gen.quadratic_semantic_partition import (
    partition_semantic_curve,
    subdivide_quadratic_chain,
)


def test_exact_reference_subdivision_preserves_endpoints_and_quadratic_shape():
    operation = ("qCurveTo", ((0, 100), (100, 100), (100, 0)))
    expanded = subdivide_quadratic_chain((0, 0), operation, 2)
    assert expanded == (
        (0.0, 50.0),
        (25.0, 100.0),
        (75.0, 100.0),
        (100.0, 50.0),
        (100, 0),
    )


def test_semantic_slot_keeps_real_line_and_exact_protected_curve():
    curve = ((10, 0), (10, 200 / 3), (130 / 3, 100), (110, 100))
    protected = ("qCurveTo", ((0, 50), (50, 100), (110, 100)))
    result = partition_semantic_curve(
        curve,
        (0, 0),
        protected,
        _reference_count_spline,
        1e-8,
        subdivisions=2,
        semantic_slot=True,
        straight_extension=((0, 0), (10, 0)),
    )
    assert result.authored[0] == ("qCurveTo", ((5, 0), (10, 0)))
    assert result.authored[-1][1][-1] == (110, 100)
    assert result.protected[0][1][-1] == pytest.approx(
        tuple(
            (a + b) / 2
            for a, b in zip(result.protected[0][1][0], result.protected[1][1][0], strict=True)
        )
    )
    assert result.protected[-1][1][-1] == (110, 100)


def test_semantic_slot_partitions_curve_when_master_has_no_extension():
    curve = ((0, 0), (0, 200 / 3), (100 / 3, 100), (100, 100))
    protected = ("qCurveTo", ((0, 50), (50, 100), (100, 100)))
    result = partition_semantic_curve(
        curve,
        (0, 0),
        protected,
        _reference_count_spline,
        1e-8,
        subdivisions=2,
        semantic_slot=True,
    )
    assert len(result.authored) == len(result.protected) == 2
    assert result.authored[0][1][-1] == pytest.approx(
        tuple(
            (a + b) / 2
            for a, b in zip(result.authored[0][1][0], result.authored[1][1][0], strict=True)
        )
    )
    assert result.authored[-1][1][-1] == (100, 100)


@pytest.mark.parametrize("subdivisions", [0, -1, 1.5])
def test_invalid_subdivision_count_fails_closed(subdivisions):
    with pytest.raises(ValueError, match="positive integer"):
        subdivide_quadratic_chain((0, 0), ("qCurveTo", ((20, 20), (40, 0))), subdivisions)


def test_semantic_partition_rejects_bad_extension_or_insufficient_fit():
    curve = ((10, 0), (20, 20), (30, 20), (40, 0))
    protected = ("qCurveTo", ((20, 20), (40, 0)))
    with pytest.raises(ValueError, match="must end"):
        partition_semantic_curve(
            curve,
            (0, 0),
            protected,
            _reference_count_spline,
            1,
            semantic_slot=True,
            straight_extension=((0, 0), (9, 0)),
        )
    with pytest.raises(ValueError, match="exceeds"):
        partition_semantic_curve(
            curve,
            (0, 0),
            protected,
            lambda *_: None,
            0.1,
        )
