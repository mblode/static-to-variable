from __future__ import annotations

import pytest

from variable_gen.common import PipelineError
from variable_gen.quadratic_reference import _fit_piecewise_group, _pad_reference_operation


def test_different_piece_counts_share_topology_without_erasing_authored_join():
    single = ((0, 0), (20, 110), (180, 110), (200, 0))
    left = ((0, 0), (15, 95), (85, 90), (100, 60))
    right = ((100, 60), (120, 30), (180, 100), (200, 0))
    prefix, masters = _fit_piecewise_group([[single], [left, right]], 2, 0.1, "curve")
    signatures = [[(op, len(points)) for op, points in master] for master in masters]
    assert signatures[0] == signatures[1] == [("qCurveTo", 2)] * prefix + [("qCurveTo", 3)]
    assert (100, 60) in [points[-1] for _, points in masters[1]]
    assert all(master[-1][1][-1] == (200, 0) for master in masters)
    reference = ("qCurveTo", ((10, 80), (190, 80), (200, 0)))
    protected = _pad_reference_operation((0, 0), reference, prefix)
    assert protected[-1] == reference
    assert protected[:-1] == [("qCurveTo", ((0, 0), (0, 0)))] * prefix
    assert [(op, len(points)) for op, points in protected] == signatures[0]


def test_piecewise_straight_cubic_conversion_keeps_the_line():
    line = ((0, 0), (10, 0), (20, 0), (30, 0))
    _, masters = _fit_piecewise_group([[line]], 1, 0.01, "line")
    assert all(y == 0 for _, points in masters[0] for _, y in points)
    assert masters[0][-1][1][-1] == (30, 0)


@pytest.mark.parametrize("groups", [[], [[]]])
def test_missing_correspondence_fails(groups):
    with pytest.raises(PipelineError, match="nonempty groups"):
        _fit_piecewise_group(groups, 1, 0.1, "curve")


def test_disconnected_source_cannot_be_fitted_across_a_gap():
    first = ((0, 0), (10, 20), (20, 20), (30, 0))
    second = ((31, 0), (40, 20), (50, 20), (60, 0))
    with pytest.raises(PipelineError, match="disconnected join"):
        _fit_piecewise_group([[first, second]], 1, 0.1, "curve")


@pytest.mark.parametrize("tolerance", [0, -1, float("inf"), float("nan")])
def test_invalid_error_budget_is_rejected(tolerance):
    with pytest.raises(ValueError, match="finite tolerance"):
        _fit_piecewise_group([[((0, 0), (1, 2), (2, 2), (3, 0))]], 1, tolerance, "curve")
