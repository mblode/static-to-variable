from copy import deepcopy
from fractions import Fraction

import pytest
from fontTools.varLib.iup import iup_delta

from variable_gen.common import PipelineError
from variable_gen.iup_projection import exact_iup_deltas, project_native_iup_default


PHANTOMS = [(0, 0), (200, 0), (0, 800), (0, -200)]


def test_exact_inference_distinguishes_rational_identity_from_real_coordinate_drift():
    native = [(0, 0), (1, 1), (3, 3)] + PHANTOMS
    deltas = [(0, 0), None, (10, 10)] + [(0, 0)] * 4
    expected = exact_iup_deltas(native, [2], deltas)
    assert expected[1] == (Fraction(10, 3), Fraction(10, 3))
    scaled = [(x * 16, y * 16) for x, y in native]
    assert exact_iup_deltas(scaled, [2], deltas) == expected
    scaled[1] = (17, 16)
    assert exact_iup_deltas(scaled, [2], deltas) != expected


def project(native, desired, deltas, **kwargs):
    return project_native_iup_default(
        native + PHANTOMS,
        [len(native) - 1],
        [deltas + [(0, 0)] * 4],
        desired + PHANTOMS,
        list(range(len(native) + 4)),
        **kwargs,
    )


def test_exact_ratio_and_fixed_landmark_survive_projection_without_mutating_inputs():
    native = [(0, 0), (5, 5), (10, 10)]
    desired = [(0, 0), (5, 5), (12, 10)]
    deltas = [(0, 0), None, (10, 10)]
    before = deepcopy((native, desired, deltas))
    result = project(native, desired, deltas, fixed_coordinates={(0, 0): 0, (2, 0): 12})
    assert result.coordinates == ((0, 0), (6, 5), (12, 10), *PHANTOMS)
    assert result.maximum_movement == (1, 0)
    assert iup_delta(deltas + [(0, 0)] * 4, result.coordinates, [2]) == iup_delta(
        deltas + [(0, 0)] * 4, native + PHANTOMS, [2]
    )
    assert (native, desired, deltas) == before


@pytest.mark.parametrize("native_x, expected", [(-2, 0), (12, 10)])
def test_clamped_points_stay_on_the_native_side(native_x, expected):
    result = project(
        [(0, 0), (native_x, 5), (10, 10)],
        [(0, 0), (4, 5), (10, 10)],
        [(0, 0), None, (10, 10)],
        fixed_coordinates={(0, 0): 0, (2, 0): 10},
    )
    assert result.coordinates[1][0] == expected


def test_equal_position_unequal_delta_anchors_keep_zero_inference():
    result = project(
        [(0, 0), (5, 5), (0, 10)],
        [(0, 0), (5, 5), (2, 10)],
        [(0, 0), None, (10, 10)],
        fixed_coordinates={(0, 0): 0},
    )
    assert result.coordinates[2][0] == 0
    assert iup_delta([(0, 0), None, (10, 10)] + [(0, 0)] * 4, result.coordinates, [2])[1][0] == 0


@pytest.mark.parametrize("deltas", [[None] * 3, [(2, 2), None, None], [(2, 2), None, (2, 2)]])
def test_zero_one_and_equal_delta_anchors_leave_coordinates_free(deltas):
    desired = [(2, 1), (3, 4), (5, 2)]
    result = project([(0, 0), (5, 5), (10, 10)], desired, deltas)
    assert result.coordinates == tuple(desired + PHANTOMS)
    assert result.maximum_movement == (0, 0)


def test_contours_and_expanded_point_mapping_do_not_share_brackets():
    native = [(0, 0), (5, 5), (10, 10), (50, 0), (60, 0), (70, 0)] + PHANTOMS
    desired = [(50, 0), (1, 1), (60, 0), (70, 0), (0, 0), (5, 5), (12, 10)] + PHANTOMS
    mapping = [4, 5, 6, 0, 2, 3, 7, 8, 9, 10]
    result = project_native_iup_default(
        native,
        [2, 5],
        [[(0, 0), None, (10, 10), None, (99, 0), None] + [(0, 0)] * 4],
        desired,
        mapping,
        fixed_coordinates={(4, 0): 0, (6, 0): 12},
    )
    assert result.coordinates[:4] == tuple(desired[:4])
    assert result.coordinates[5] == (6, 5)


def test_infeasible_fixed_landmarks_fail_instead_of_relaxing_the_ratio():
    with pytest.raises(PipelineError, match="minimax projection failed"):
        project(
            [(0, 0), (5, 5), (10, 10)],
            [(0, 0), (5, 5), (12, 10)],
            [(0, 0), None, (10, 10)],
            fixed_coordinates={(0, 0): 0, (1, 0): 5, (2, 0): 12},
        )


@pytest.mark.parametrize(
    "failure", ["mapping", "ends", "tuple", "landmark", "phantom", "nan", "limit"]
)
def test_invalid_inputs_fail_closed(failure):
    native = [(0, 0), (5, 5), (10, 10)] + PHANTOMS
    desired = deepcopy(native)
    mapping, ends = list(range(7)), [2]
    variations = [[(0, 0), None, (10, 10)] + [(0, 0)] * 4]
    kwargs = {}
    if failure == "mapping":
        mapping[1] = 0
    elif failure == "ends":
        ends = [3]
    elif failure == "tuple":
        variations[0].pop()
    elif failure == "landmark":
        kwargs["fixed_coordinates"] = {(0, 0): 40000}
    elif failure == "phantom":
        kwargs["fixed_coordinates"] = {(3, 0): 1}
    elif failure == "nan":
        desired[0] = (float("nan"), 0)
    else:
        kwargs["max_move"] = float("inf")
    with pytest.raises(PipelineError):
        project_native_iup_default(native, ends, variations, desired, mapping, **kwargs)
