from dataclasses import replace

import numpy as np
import pytest
from fontTools.pens.areaPen import AreaPen

from variable_gen.quadratic_landmarks import (
    LandmarkMaster,
    curves_sha256,
    prepare_landmark_basis,
)


def line(a, b):
    a, b = np.array(a, dtype=float), np.array(b, dtype=float)
    return tuple(map(tuple, [a, a + (b - a) / 3, a + 2 * (b - a) / 3, b]))


def master(protected=False):
    curves = tuple(
        line(a, b)
        for a, b in [
            ((0, 0), (100, 0)),
            ((100, 0), (100, 80)),
            ((100, 80), (0, 80)),
            ((0, 80), (0, 0)),
        ]
    )
    return LandmarkMaster(
        curves,
        tuple(zip(("start", "right", "top", "left", "end"), range(5), strict=True)),
        curves_sha256(curves),
        protected,
        frozenset({"right", "top"}),
    )


def area(recording):
    pen = AreaPen(None)
    for op, points in recording:
        getattr(pen, op)(*points)
    return pen.value


def test_basis_preserves_native_spans_source_area_and_shared_corner_slots():
    result = prepare_landmark_basis([master(), master(True)])
    assert result.slots == (2, 2, 2, 2)
    assert result.groups[0] == result.groups[1]
    assert area(result.sources[0]) == pytest.approx(8000)
    assert area(result.protected[1]) == pytest.approx(8000)
    points = [p[-1] for op, p in result.protected[1] if op == "qCurveTo"]
    assert points == [(100, 0), (100, 0), (100, 80), (100, 80), (0, 80), (0, 80), (0, 0), (0, 0)]


def test_changed_source_hash_is_rejected_before_conversion():
    a = master()
    with pytest.raises(ValueError, match="hash mismatch"):
        prepare_landmark_basis([replace(a, recording_sha256="0" * 64), master(True)])


def test_opposite_winding_does_not_silently_morph_through_empty_ink():
    a = master(True)
    curves = tuple(tuple(reversed(c)) for c in reversed(a.curves))
    with pytest.raises(ValueError, match="winding mismatch"):
        prepare_landmark_basis(
            [master(), replace(a, curves=curves, recording_sha256=curves_sha256(curves))]
        )


@pytest.mark.parametrize(
    "landmarks",
    [
        (("start", 0), ("top", 1), ("right", 2), ("left", 3), ("end", 4)),
        (("start", 0), ("right", 1), ("left", 3), ("end", 4)),
        (("start", 0), ("right", 2), ("top", 1), ("left", 3), ("end", 4)),
    ],
)
def test_missing_reordered_or_nonmonotonic_landmarks_are_rejected(landmarks):
    with pytest.raises(ValueError, match="landmark"):
        prepare_landmark_basis([master(), replace(master(True), landmarks=landmarks)])


def test_declared_corner_cannot_point_into_a_straight_edge():
    a = master()
    curves = (line((0, 0), (50, 0)), line((50, 0), (100, 0)), *a.curves[1:])
    changed = replace(
        a,
        curves=curves,
        recording_sha256=curves_sha256(curves),
        landmarks=(("start", 0), ("right", 1), ("top", 3), ("left", 4), ("end", 5)),
    )
    with pytest.raises(ValueError, match="sharp corner"):
        prepare_landmark_basis([changed, master(True)])


def test_protected_cubic_cannot_be_approximated_as_quadratic():
    a = master(True)
    curves = (tuple([(0, 0), (20, -20), (80, -10), (100, 0)]), *a.curves[1:])
    changed = replace(
        a, curves=curves, recording_sha256=curves_sha256(curves), corner_roles=frozenset()
    )
    with pytest.raises(ValueError, match="exact quadratic"):
        prepare_landmark_basis([master(), changed])


def test_authored_master_cannot_drop_required_corner_roles():
    with pytest.raises(ValueError, match="same required corner roles"):
        prepare_landmark_basis(
            [master(), replace(master(), corner_roles=frozenset()), master(True)]
        )


def test_quarter_partition_preserves_curves_without_stationary_slots():
    from variable_gen.quadratic_reference_templates import exact_reference_template

    source, protected = master(), master(True)
    quadratic = ((0, 0), (100 / 3, -100 / 3), (200 / 3, -100 / 3), (100, 0))
    curves = (quadratic, *protected.curves[1:])
    protected = replace(
        protected, curves=curves, recording_sha256=curves_sha256(curves), corner_roles=frozenset()
    )
    result = prepare_landmark_basis([source, protected], native_partition="quarters")
    assert result.slots == (4, 4, 4, 4)
    original = [
        ("moveTo", ((0, 0),)),
        ("qCurveTo", ((50, -50), (100, 0))),
        ("lineTo", ((100, 80),)),
        ("lineTo", ((0, 80),)),
        ("lineTo", ((0, 0),)),
        ("closePath", ()),
    ]
    assert exact_reference_template(original, result.protected[1])
    ends = [points[-1] for op, points in result.protected[1] if op == "qCurveTo"]
    assert all(a != b for a, b in zip(ends, ends[1:], strict=False))


def test_quarter_partition_rejects_unequal_native_region_counts():
    a = master(True)
    curves = (line((0, 0), (50, 0)), line((50, 0), (100, 0)), *a.curves[1:])
    changed = replace(
        a,
        curves=curves,
        recording_sha256=curves_sha256(curves),
        landmarks=(("start", 0), ("right", 2), ("top", 3), ("left", 4), ("end", 5)),
    )
    with pytest.raises(ValueError, match="matching protected"):
        prepare_landmark_basis([master(), a, changed], native_partition="quarters")
    with pytest.raises(ValueError, match="unknown native"):
        prepare_landmark_basis([master(), a], native_partition="approximate")


def test_dyadic_capacity_balances_native_counts_with_exact_quarters_first():
    from variable_gen.quadratic_reference_templates import exact_reference_template

    a = master(True)
    curves = tuple(line((x, 0), (x + 20, 0)) for x in range(0, 100, 20)) + a.curves[1:]
    b = replace(
        a,
        curves=curves,
        recording_sha256=curves_sha256(curves),
        landmarks=(("start", 0), ("right", 5), ("top", 6), ("left", 7), ("end", 8)),
    )
    result = prepare_landmark_basis([master(), a, b], native_partition="dyadic")
    assert result.slots == (5, 1, 1, 1)
    points = [p[-1] for op, p in result.protected[1] if op == "qCurveTo"]
    assert points[:5] == [(25, 0), (50, 0), (75, 0), (100, 0), (100, 0)]
    assert exact_reference_template(result.protected[1], result.protected[2])
    assert area(result.sources[0]) == pytest.approx(8000)
