from __future__ import annotations

import pytest

from fontTools.pens.recordingPen import RecordingPen

from variable_gen.common import PipelineError
from variable_gen.quadratic_reference import (
    BALANCED_ENDPOINTS,
    _continuous_piecewise_spline,
    REFERENCE_COUNT,
    _fit_piecewise_group,
    _pad_reference_operation,
    _reference_count_spline,
    _same_filled_path,
)


def test_continuous_chain_fits_connected_piecewise_path_without_stationary_segments():
    first = ((0, 0), (10, 0), (20, 0), (30, 0))
    second = ((30, 0), (40, 0), (50, 0), (60, 0))
    spline = _continuous_piecewise_spline([first, second], 4, 0.01)
    assert spline is not None
    assert len(spline) == 6
    assert spline[0] == (0, 0)
    assert spline[-1] == (60, 0)


def _closed_quadratic(start, operation):
    recording = RecordingPen()
    recording.moveTo(start)
    recording.qCurveTo(*operation[1])
    recording.closePath()
    return recording


def _closed_operations(start, operations):
    recording = RecordingPen()
    recording.moveTo(start)
    for kind, points in operations:
        getattr(recording, kind)(*points)
    recording.closePath()
    return recording


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
    assert ("qCurveTo", ((0, 0), (0, 0))) not in protected
    assert _same_filled_path(
        _closed_quadratic((0, 0), reference), _closed_operations((0, 0), protected)
    )
    assert [(op, len(points)) for op, points in protected] == signatures[0]


def test_piecewise_straight_cubic_conversion_keeps_the_line():
    line = ((0, 0), (10, 0), (20, 0), (30, 0))
    _, masters = _fit_piecewise_group([[line]], 1, 0.01, "line")
    assert all(y == 0 for _, points in masters[0] for _, y in points)
    assert masters[0][-1][1][-1] == (30, 0)


def test_balanced_endpoint_placement_preserves_reference_and_matching_arities():
    curve = ((0, 0), (20, 110), (180, 110), (200, 0))
    prefix, masters = _fit_piecewise_group([[curve], [curve]], 2, 0.1, "curve", BALANCED_ENDPOINTS)
    before = prefix // 2
    after = prefix - before
    signature = [("qCurveTo", 2)] * before + [("qCurveTo", 3)] + [("qCurveTo", 2)] * after
    assert [[(op, len(points)) for op, points in master] for master in masters] == [
        signature,
        signature,
    ]
    reference = ("qCurveTo", ((10, 80), (190, 80), (200, 0)))
    protected = _pad_reference_operation((0, 0), reference, prefix, BALANCED_ENDPOINTS)
    assert [(op, len(points)) for op, points in protected] == signature
    assert protected[before] == reference
    assert protected[:before] == [("qCurveTo", ((0, 0), (0, 0)))] * before
    assert protected[before + 1 :] == [("qCurveTo", ((200, 0), (200, 0)))] * after


def test_balanced_endpoint_placement_rejects_ambiguous_multi_curve_groups():
    left = ((0, 0), (10, 20), (20, 20), (30, 0))
    right = ((30, 0), (40, 20), (50, 20), (60, 0))
    with pytest.raises(PipelineError, match="one authored curve"):
        _fit_piecewise_group([[left, right]], 1, 0.1, "curve", BALANCED_ENDPOINTS)


def test_default_placement_subdivides_display_instead_of_stationary_prefixes():
    curve = ((0, 0), (20, 110), (180, 110), (200, 0))
    implicit = _fit_piecewise_group([[curve]], 2, 0.1, "curve")
    explicit = _fit_piecewise_group([[curve]], 2, 0.1, "curve", "prefix")
    assert implicit == explicit

    reference = ("qCurveTo", ((10, 80), (190, 80), (200, 0)))
    protected = _pad_reference_operation((0, 0), reference, 2)
    assert ("qCurveTo", ((0, 0), (0, 0))) not in protected
    assert len(protected) == 3
    assert _same_filled_path(
        _closed_quadratic((0, 0), reference), _closed_operations((0, 0), protected)
    )
    assert all(
        value * 16 == round(value * 16)
        for _, points in protected
        for point in points
        for value in point
    )


def test_extra_text_segments_are_not_collapsed_display_prefixes():
    """Regression: mid-opsz lobes came from (start, start) Display prefixes."""
    curve = ((0, 0), (0, 220), (100, 220), (100, 0))
    prefix, masters = _fit_piecewise_group([[curve]], 1, 0.25, "curve")
    assert prefix > 0
    reference = ("qCurveTo", ((50, 150), (100, 0)))
    protected = _pad_reference_operation((0, 0), reference, prefix)
    assert all(points != ((0, 0), (0, 0)) for _, points in protected)
    assert _same_filled_path(
        _closed_quadratic((0, 0), reference), _closed_operations((0, 0), protected)
    )
    start = masters[0][0][1][0]
    assert start != (0, 0)
    mid = (
        (start[0] + protected[0][1][0][0]) / 2,
        (start[1] + protected[0][1][0][1]) / 2,
    )
    # Stationary Display prefixes interpolated this first off-curve toward the
    # shared start, forming a lobe. On-curve Display extras keep it away.
    assert (mid[0] ** 2 + mid[1] ** 2) ** 0.5 > 10


def test_reference_count_fits_quadratic_without_stationary_points():
    curve = ((0, 0), (20, 40), (50, 40), (90, 0))
    prefix, masters = _fit_piecewise_group([[curve]], 1, 1e-9, "curve", REFERENCE_COUNT)
    assert prefix == 0
    assert len(masters[0]) == 1
    control, endpoint = masters[0][0][1]
    assert control == pytest.approx((30, 60))
    assert endpoint == (90, 0)
    reference = ("qCurveTo", ((30, 60), (90, 0)))
    assert _pad_reference_operation((0, 0), reference, 0, REFERENCE_COUNT) == [reference]


def test_reference_count_rejects_insufficient_topology_instead_of_padding():
    curve = ((0, 0), (20, 110), (180, -110), (200, 0))
    with pytest.raises(PipelineError, match="exceeds"):
        _fit_piecewise_group([[curve]], 1, 0.25, "curve", REFERENCE_COUNT)
    with pytest.raises(PipelineError, match="stationary"):
        _pad_reference_operation((0, 0), ("qCurveTo", ((30, 60), (90, 0))), 1, REFERENCE_COUNT)


def test_reference_count_has_independent_geometric_bound_and_translation_invariance():
    curve = ((0, 0), (20, 110), (180, 110), (200, 0))
    assert _reference_count_spline(curve, 3, 0.001) is None
    fitted = _reference_count_spline(curve, 3, 2)
    assert fitted is not None
    shifted = _reference_count_spline(tuple((x + 2000, y - 3000) for x, y in curve), 3, 2)
    assert shifted is not None
    for a, b in zip(fitted, shifted, strict=True):
        assert b == pytest.approx((a[0] + 2000, a[1] - 3000))


def test_reference_count_rejects_unreviewed_piecewise_correspondence():
    curve = ((0, 0), (20, 40), (50, 40), (90, 0))
    with pytest.raises(PipelineError, match="one authored curve"):
        _fit_piecewise_group([[curve, curve]], 3, 0.25, "curve", REFERENCE_COUNT)


def test_reference_count_lines_preserves_real_extension_and_intact_reference():
    from variable_gen.quadratic_reference import REFERENCE_COUNT_LINES

    line = ((-30, 0), (-20, 0), (-10, 0), (0, 0))
    curve = ((0, 0), (20, 40), (50, 40), (90, 0))
    prefix, masters = _fit_piecewise_group(
        [[line, curve], [curve]], 1, 1e-9, "curve", REFERENCE_COUNT_LINES
    )
    assert prefix == 1
    assert masters[0][0] == ("qCurveTo", ((-15, 0), (0, 0)))
    assert masters[1][0] == ("qCurveTo", ((0, 0), (0, 0)))
    assert masters[0][-1] == masters[1][-1]
    reference = ("qCurveTo", ((30, 60), (90, 0)))
    assert _pad_reference_operation((0, 0), reference, prefix, REFERENCE_COUNT_LINES) == [
        ("qCurveTo", ((0, 0), (0, 0))),
        reference,
    ]


@pytest.mark.parametrize(
    "first",
    [
        ((-30, 0), (-20, 1), (-10, 0), (0, 0)),
        ((-30, 0), (10, 0), (-10, 0), (0, 0)),
    ],
)
def test_reference_count_lines_rejects_curved_or_reversing_extensions(first):
    from variable_gen.quadratic_reference import REFERENCE_COUNT_LINES

    curve = ((0, 0), (20, 40), (50, 40), (90, 0))
    with pytest.raises(PipelineError, match="monotone straight"):
        _fit_piecewise_group([[first, curve]], 1, 0.5, "curve", REFERENCE_COUNT_LINES)


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
