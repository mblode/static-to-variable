"""Synthetic tests for read-only perpendicular interpolation-kink analysis."""

from __future__ import annotations

import math

import pytest

from variable_gen.interpolation_kinks import (
    interpolation_kink_defects,
    perpendicular_kink_depth,
)


def _outline(
    previous_control: tuple[float, float],
    next_control: tuple[float, float],
    *,
    node: tuple[float, float] = (0.0, 0.0),
    open_path: bool = False,
) -> list:
    """One isolated cubic-to-cubic join surrounded by line joins."""
    return [
        [
            ("moveTo", [(-100.0, -100.0)]),
            ("lineTo", [(-100.0, 0.0)]),
            ("curveTo", [(-80.0, 0.0), previous_control, node]),
            ("curveTo", [next_control, (80.0, 0.0), (100.0, 0.0)]),
            ("lineTo", [(100.0, -100.0)]),
            ("endPath" if open_path else "closePath", []),
        ]
    ]


def _scaled(outline: list, factor: float) -> list:
    return [
        [
            (operation, [(x * factor, y * factor) for x, y in points])
            for operation, points in contour
        ]
        for contour in outline
    ]


def test_perpendicular_depth_is_node_to_control_chord_distance() -> None:
    depth = perpendicular_kink_depth((-5.0, -10.0), (0.0, 0.0), (10.0, 5.0))
    assert depth == pytest.approx(75.0 / math.sqrt(450.0))


def test_clean_smooth_join_has_no_defect() -> None:
    horizontal = _outline((-10.0, 0.0), (20.0, 0.0))
    vertical = _outline((0.0, -10.0), (0.0, 20.0))

    assert (
        interpolation_kink_defects(
            horizontal,
            vertical,
            glyph_name="clean",
            threshold=0.01,
        )
        == ()
    )


def test_known_midpoint_kink_reports_depth_and_multi_axis_location() -> None:
    horizontal = _outline((-100.0, 0.0), (110.0, 0.0))
    vertical_with_reversed_ratio = _outline((0.0, -110.0), (0.0, 100.0))

    defects = interpolation_kink_defects(
        horizontal,
        vertical_with_reversed_ratio,
        glyph_name="synthetic.kink",
        threshold=0.9,
        left_location={"wght": 100.0, "opsz": 12.0},
        right_location={"opsz": 28.0, "wght": 900.0},
    )

    assert len(defects) == 1
    defect = defects[0]
    assert defect.contour_index == 0
    assert defect.node_index == 2
    assert defect.location == (("opsz", 20.0), ("wght", 500.0))
    assert defect.depth == pytest.approx(525.0 / math.sqrt(22050.0))
    assert defect.reason == "depth_exceeded"
    assert defect.as_dict() == {
        "glyph": "synthetic.kink",
        "contour": 0,
        "node": 2,
        "location": {"opsz": 20.0, "wght": 500.0},
        "t": 0.5,
        "depth": defect.depth,
        "endpointDepths": [0.0, 0.0],
        "baselineDepth": 0.0,
        "depthDelta": defect.depth,
        "threshold": 0.9,
        "reason": "depth_exceeded",
    }


def test_non_midpoint_sample_interpolates_complete_location() -> None:
    horizontal = _outline((-10.0, 0.0), (20.0, 0.0))
    vertical = _outline((0.0, -20.0), (0.0, 10.0))

    defects = interpolation_kink_defects(
        horizontal,
        vertical,
        glyph_name="quarter.sample",
        threshold=0.9,
        t=0.25,
        left_location=(("wght", 100.0), ("opsz", 12.0)),
        right_location=(("wght", 900.0), ("opsz", 28.0)),
    )

    assert len(defects) == 1
    assert defects[0].interpolation_t == 0.25
    assert defects[0].location == (("opsz", 16.0), ("wght", 300.0))


def test_depth_and_threshold_scale_in_font_units() -> None:
    horizontal = _outline((-100.0, 0.0), (110.0, 0.0))
    vertical = _outline((0.0, -110.0), (0.0, 100.0))
    original = interpolation_kink_defects(
        horizontal,
        vertical,
        glyph_name="scale",
        threshold=0.9,
    )[0]
    scaled = interpolation_kink_defects(
        _scaled(horizontal, 4.0),
        _scaled(vertical, 4.0),
        glyph_name="scale",
        threshold=3.6,
    )[0]

    assert scaled.depth == pytest.approx(original.depth * 4.0)


def test_caller_supplied_threshold_controls_reporting() -> None:
    horizontal = _outline((-100.0, 0.0), (110.0, 0.0))
    vertical = _outline((0.0, -110.0), (0.0, 100.0))

    assert (
        interpolation_kink_defects(
            horizontal,
            vertical,
            glyph_name="threshold",
            threshold=3.6,
        )
        == ()
    )


def test_intentional_endpoint_corners_are_excluded() -> None:
    corner_a = _outline((-10.0, 0.0), (0.0, 10.0))
    corner_b = _outline((0.0, -10.0), (10.0, 0.0))

    assert (
        interpolation_kink_defects(
            corner_a,
            corner_b,
            glyph_name="corner",
            threshold=0.0,
        )
        == ()
    )


def test_identical_slight_endpoint_bend_is_not_a_new_kink() -> None:
    # About 2.5 units from the control chord, but the same authored bend exists
    # at both endpoints.  Absolute depth alone would mislabel the interpolation.
    bent = _outline((-100.0, 0.0), (100.0, 5.0))

    assert (
        interpolation_kink_defects(
            bent,
            bent,
            glyph_name="inherited.bend",
            threshold=0.9,
        )
        == ()
    )


def test_interior_depth_peak_uses_interpolated_endpoint_baseline() -> None:
    left = _outline(
        (-123.69076071321241, 2.483561128027249),
        (122.98538340772187, -1.1076120178758675),
    )
    right = _outline(
        (3.4297123501111155, -144.08621998136425),
        (3.9695732242258153, 128.94204296242083),
    )

    defects = interpolation_kink_defects(
        left,
        right,
        glyph_name="interior.peak",
        threshold=0.9,
    )

    assert len(defects) == 1
    assert defects[0].endpoint_depths == pytest.approx((0.6827676752863019, 3.714607874157331))
    assert defects[0].baseline_depth == pytest.approx(2.1986877747218165)
    assert defects[0].depth == pytest.approx(3.5601506668224587)
    assert defects[0].depth_delta == pytest.approx(1.3614628921006422)


def test_intentional_endpoint_reversal_is_excluded_as_a_corner() -> None:
    reversal = _outline((10.0, 0.0), (10.0, 0.0))

    assert (
        interpolation_kink_defects(
            reversal,
            reversal,
            glyph_name="authored.reversal",
            threshold=0.0,
        )
        == ()
    )


def test_open_contour_endpoints_are_not_invented_as_joins() -> None:
    one_cubic_open = [
        [
            ("moveTo", [(0.0, 0.0)]),
            ("curveTo", [(10.0, 0.0), (20.0, 0.0), (30.0, 0.0)]),
            ("endPath", []),
        ]
    ]

    assert (
        interpolation_kink_defects(
            one_cubic_open,
            one_cubic_open,
            glyph_name="open",
            threshold=0.0,
        )
        == ()
    )


def test_degenerate_interpolated_join_is_a_blocking_structured_defect() -> None:
    rightward = _outline((-10.0, 0.0), (10.0, 0.0))
    leftward = _outline((10.0, 0.0), (-10.0, 0.0))

    defects = interpolation_kink_defects(
        rightward,
        leftward,
        glyph_name="degenerate",
        threshold=100.0,
    )

    assert len(defects) == 1
    assert defects[0].depth is None
    assert defects[0].reason == "degenerate_interpolated_join"


def test_new_interpolated_reversal_blocks_even_at_zero_depth() -> None:
    rightward = _outline((-10.0, 0.0), (20.0, 0.0))
    leftward = _outline((30.0, 0.0), (-10.0, 0.0))

    defects = interpolation_kink_defects(
        rightward,
        leftward,
        glyph_name="interpolated.reversal",
        threshold=100.0,
    )

    assert len(defects) == 1
    assert defects[0].depth == 0.0
    assert defects[0].endpoint_depths == (0.0, 0.0)
    assert defects[0].baseline_depth == 0.0
    assert defects[0].depth_delta == 0.0
    assert defects[0].reason == "interpolated_corner"


def test_degenerate_endpoint_join_is_a_blocking_structured_defect() -> None:
    collapsed = _outline((0.0, 0.0), (10.0, 0.0))
    smooth = _outline((-10.0, 0.0), (10.0, 0.0))

    defects = interpolation_kink_defects(
        collapsed,
        smooth,
        glyph_name="degenerate.endpoint",
        threshold=100.0,
    )

    assert len(defects) == 1
    assert defects[0].depth is None
    assert defects[0].endpoint_depths == (None, 0.0)
    assert defects[0].baseline_depth is None
    assert defects[0].reason == "degenerate_endpoint_join"


def test_degenerate_endpoint_retains_measurable_corner_depth() -> None:
    collapsed = _outline((0.0, 0.0), (10.0, 0.0))
    corner = _outline((-10.0, 0.0), (0.0, 10.0))

    defects = interpolation_kink_defects(
        collapsed,
        corner,
        glyph_name="degenerate.corner",
        threshold=100.0,
    )

    assert len(defects) == 1
    assert defects[0].endpoint_depths is not None
    assert defects[0].endpoint_depths[0] is None
    assert defects[0].endpoint_depths[1] == pytest.approx(math.sqrt(50.0))
    assert defects[0].reason == "degenerate_endpoint_join"


@pytest.mark.parametrize("bad", [math.inf, -math.inf, math.nan])
def test_nonfinite_coordinates_fail_closed(bad: float) -> None:
    invalid = _outline((bad, 0.0), (10.0, 0.0))
    with pytest.raises(ValueError, match="finite coordinates"):
        interpolation_kink_defects(
            invalid,
            invalid,
            glyph_name="nonfinite",
            threshold=0.9,
        )


def test_real_coordinate_conversion_overflow_fails_with_value_error() -> None:
    invalid = _outline((-10.0, 0.0), (10.0, 0.0))
    invalid[0][2] = ("curveTo", [(-80.0, 0.0), (10**400, 0.0), (0.0, 0.0)])

    with pytest.raises(ValueError, match="finite coordinates"):
        interpolation_kink_defects(
            invalid,
            invalid,
            glyph_name="numeric-overflow",
            threshold=0.9,
        )


@pytest.mark.parametrize("bad", ["1.0", object()])
def test_non_real_coordinates_fail_with_value_error(bad: object) -> None:
    invalid = _outline((-10.0, 0.0), (10.0, 0.0))
    invalid[0][2] = ("curveTo", [(-80.0, 0.0), (bad, 0.0), (0.0, 0.0)])

    with pytest.raises(ValueError, match="finite coordinates"):
        interpolation_kink_defects(
            invalid,
            invalid,
            glyph_name="non-real",
            threshold=0.9,
        )


def test_incompatible_pairs_fail_closed() -> None:
    cubic = _outline((-10.0, 0.0), (10.0, 0.0))
    line = _outline((-10.0, 0.0), (10.0, 0.0))
    line[0][2] = ("lineTo", [(0.0, 0.0)])

    with pytest.raises(ValueError, match="not interpolation-compatible"):
        interpolation_kink_defects(
            cubic,
            line,
            glyph_name="incompatible",
            threshold=0.9,
        )


@pytest.mark.parametrize(
    ("t", "threshold"),
    [
        (math.nan, 0.9),
        (-0.1, 0.9),
        (0.0, 0.9),
        (1.0, 0.9),
        (1.1, 0.9),
        (0.5, math.inf),
        (0.5, -0.1),
    ],
)
def test_invalid_configuration_fails_closed(t: float, threshold: float) -> None:
    outline = _outline((-10.0, 0.0), (10.0, 0.0))
    with pytest.raises(ValueError):
        interpolation_kink_defects(
            outline,
            outline,
            glyph_name="config",
            threshold=threshold,
            t=t,
        )


def test_missing_glyph_context_and_nonfinite_location_fail_closed() -> None:
    outline = _outline((-10.0, 0.0), (10.0, 0.0))
    with pytest.raises(ValueError, match="glyph name"):
        interpolation_kink_defects(outline, outline, glyph_name="", threshold=0.9)
    with pytest.raises(ValueError, match="axis location"):
        interpolation_kink_defects(
            outline,
            outline,
            glyph_name="location",
            threshold=0.9,
            left_location={"wght": 100.0},
            right_location={"wght": math.nan},
        )


def test_non_string_axis_tags_fail_with_value_error() -> None:
    outline = _outline((-10.0, 0.0), (10.0, 0.0))
    with pytest.raises(ValueError, match="tags must be non-empty strings"):
        interpolation_kink_defects(
            outline,
            outline,
            glyph_name="location.tag",
            threshold=0.9,
            left_location=[(1, 100.0)],  # type: ignore[list-item]
            right_location=[(1, 900.0)],  # type: ignore[list-item]
        )


def test_interpolated_axis_location_overflow_fails_closed() -> None:
    outline = _outline((-10.0, 0.0), (10.0, 0.0))
    with pytest.raises(ValueError, match="interpolated axis location"):
        interpolation_kink_defects(
            outline,
            outline,
            glyph_name="location.overflow",
            threshold=0.9,
            left_location={"wght": -1e308},
            right_location={"wght": 1e308},
        )


def test_finite_outline_coordinate_arithmetic_overflow_fails_closed() -> None:
    left = _outline((-1e308, 0.0), (1e308, 0.0))
    right = _outline((1e308, 0.0), (-1e308, 0.0))

    with pytest.raises(ValueError, match="non-finite value"):
        interpolation_kink_defects(
            left,
            right,
            glyph_name="outline.overflow",
            threshold=0.9,
        )


def test_results_are_deterministic() -> None:
    horizontal = _outline((-10.0, 0.0), (20.0, 0.0))
    vertical = _outline((0.0, -20.0), (0.0, 10.0))
    kwargs = {
        "glyph_name": "deterministic",
        "threshold": 0.9,
        "left_location": (("wght", 100.0), ("opsz", 12.0)),
        "right_location": (("wght", 900.0), ("opsz", 28.0)),
    }

    assert interpolation_kink_defects(horizontal, vertical, **kwargs) == interpolation_kink_defects(
        horizontal, vertical, **kwargs
    )
