"""Endpoint capacity must preserve the original protected point stream."""

import pytest

from variable_gen.quadratic_reference import _reference_count_spline
from variable_gen.quadratic_semantic_partition import partition_endpoint_spans


CURVE = ((0.0, 0.0), (0.0, 200 / 3), (100 / 3, 100.0), (100.0, 100.0))
PROTECTED = ("qCurveTo", ((0.0, 40.0), (45.0, 90.0), (100.0, 100.0)))


def test_native_point_stream_survives_without_subdivision():
    result = partition_endpoint_spans(
        [CURVE], PROTECTED, _reference_count_spline, 1e-7, extra_spans=8
    )
    assert result.protected[0] is PROTECTED
    assert result.protected[1] == ("qCurveTo", ((100.0, 100.0),) * 9)
    assert result.authored[0][1][-1] == pytest.approx((25.0, 75.0))
    assert result.authored[-1][1][-1] == CURVE[-1]
    assert result.authored_curve_count == result.protected_curve_count == 10


def test_existing_authored_seam_survives_and_each_fit_receives_hard_budget():
    calls = []

    def fit(curve, count, tolerance):
        calls.append((curve, count, tolerance))
        return _reference_count_spline(curve, count, tolerance)

    second = tuple((x + 100, y + 100) for x, y in CURVE)
    result = partition_endpoint_spans([CURVE, second], PROTECTED, fit, 0.01, extra_spans=3)
    assert result.authored[0][1][-1] == CURVE[-1]
    assert calls == [(CURVE, 2, 0.01), (second, 3, 0.01)]


@pytest.mark.parametrize("extra", [0, -1, True, 1.5])
def test_invalid_capacity_is_rejected(extra):
    with pytest.raises(ValueError, match="positive integer"):
        partition_endpoint_spans(
            [CURVE], PROTECTED, _reference_count_spline, 0.1, extra_spans=extra
        )


@pytest.mark.parametrize("budget", [0, -1, float("inf"), float("nan")])
def test_invalid_budget_is_rejected(budget):
    with pytest.raises(ValueError, match="finite and positive"):
        partition_endpoint_spans([CURVE], PROTECTED, _reference_count_spline, budget, extra_spans=8)


def test_fit_failure_cannot_be_replaced_by_native_geometry():
    with pytest.raises(ValueError, match="exceed"):
        partition_endpoint_spans([CURVE], PROTECTED, lambda *_: None, 0.1, extra_spans=8)


def test_disconnected_authored_seam_is_rejected_before_fitting():
    with pytest.raises(ValueError, match="disconnected"):
        partition_endpoint_spans(
            [CURVE, CURVE], PROTECTED, _reference_count_spline, 0.1, extra_spans=8
        )
