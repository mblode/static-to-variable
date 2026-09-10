import pytest

from variable_gen.curve_certificate import certify_curve_distance


def test_same_ink_with_different_parameterization():
    assert certify_curve_distance(
        [[(0, 0), (0, 0), (10, 0), (10, 0)]],
        [[(0, 0), (5, 0), (10, 0)]],
        0.1,
    )


def test_exact_quadratic_elevation_and_subdivision():
    quadratic = [[(0, 0), (6, 12), (12, 0)]]
    cubic = [[(0, 0), (4, 8), (8, 8), (12, 0)]]
    subdivided = [[(0, 0), (3, 6), (6, 6)], [(6, 6), (9, 6), (12, 0)]]
    assert certify_curve_distance(cubic, quadratic, 0.02)
    assert certify_curve_distance(cubic, subdivided, 0.02)


def test_close_curve_passes_but_thickened_or_looped_curve_fails():
    line = [[(0, 0), (5, 0), (10, 0)]]
    assert certify_curve_distance(line, [[(0, 0.01), (5, 0.01), (10, 0.01)]], 0.1)
    assert not certify_curve_distance(line, [[(0, 0.2), (5, 0.2), (10, 0.2)]], 0.1)
    assert not certify_curve_distance(line, [[(0, 0), (0, 10), (10, -10), (10, 0)]], 0.1)


def test_symmetric_check_rejects_extra_path_even_with_shared_samples():
    short = [[(0, 0), (2, 0), (4, 0)]]
    long = [[(0, 0), (5, 0), (10, 0)]]
    assert not certify_curve_distance(short, long, 0.1)
    assert not certify_curve_distance(long, short, 0.1)


def test_invalid_or_disconnected_controls_fail_closed():
    line = [[(0, 0), (5, 0), (10, 0)]]
    with pytest.raises(ValueError):
        certify_curve_distance(line, line, float("nan"))
    with pytest.raises(ValueError):
        certify_curve_distance(line, [[(0, 0), (float("inf"), 0), (10, 0)]], 0.1)
    with pytest.raises(ValueError):
        certify_curve_distance(line, line + line, 0.1)
    assert not certify_curve_distance([], line, 0.1)
