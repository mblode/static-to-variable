"""Rotating a contour's start node so masters agree where it begins.

The donors disagree: Circular starts the two dots of `divide` at a different
point round the ring in each weight. That is not a shape difference and must not
be treated as one, because the fallback -- resample every master onto a shared
polyline and refit -- is what turns a four-segment circle into an eight-segment
wobble.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from variable_gen.reconstruct_compatible import (  # noqa: E402
    _align_starts,
    _already_compatible,
    _contour_node_points,
    _rotate_contour,
    _starts_aligned,
    reconstruct,
)

K = 0.5522847498307936


def _circle(radius, start=0, cx=0.0, cy=0.0):
    """A four-segment circle written from node ``start``."""
    points = [(cx + radius, cy), (cx, cy + radius), (cx - radius, cy), (cx, cy - radius)]
    tangents = [(0, radius * K), (-radius * K, 0), (0, -radius * K), (radius * K, 0)]
    order = [(index + start) % 4 for index in range(4)]
    ops = [("moveTo", [points[order[0]]])]
    for step in range(4):
        here, nxt = order[step], order[(step + 1) % 4]
        ops.append(
            (
                "curveTo",
                [
                    (points[here][0] + tangents[here][0], points[here][1] + tangents[here][1]),
                    (points[nxt][0] - tangents[nxt][0], points[nxt][1] - tangents[nxt][1]),
                    points[nxt],
                ],
            )
        )
    ops.append(("closePath", []))
    return ops


def _points(contour):
    return {(round(x, 6), round(y, 6)) for _op, pts in contour for x, y in pts}


def test_rotating_a_contour_moves_no_point_and_changes_no_segment_kind() -> None:
    contour = _circle(100)
    turned = _rotate_contour(contour, 2)
    assert turned is not None
    assert _points(turned) == _points(contour)
    assert [op for op, _ in turned] == [op for op, _ in contour]
    assert _contour_node_points(turned)[0] == _contour_node_points(contour)[2]


def test_rotating_all_the_way_round_is_the_original() -> None:
    contour = _circle(100)
    assert _rotate_contour(contour, 4) == contour
    assert _rotate_contour(contour, 0) == contour


def test_masters_that_start_the_same_circle_elsewhere_are_brought_into_line() -> None:
    outlines = {100.0: [_circle(60, start=1)], 400.0: [_circle(90)], 950.0: [_circle(120, start=3)]}
    assert _already_compatible(outlines)
    assert not _starts_aligned(outlines)

    turned = _align_starts(outlines, 400.0)
    assert turned is not None
    assert _already_compatible(turned)
    assert _starts_aligned(turned)
    # The shapes are untouched; only the writing order changed.
    for pos in outlines:
        assert _points(turned[pos][0]) == _points(outlines[pos][0])


def test_a_rotated_circle_survives_reconstruction_as_a_circle() -> None:
    """The whole point: it should come out on the fast path, not be refitted."""
    outlines = {100.0: [_circle(60, start=1)], 400.0: [_circle(90)], 950.0: [_circle(120, start=3)]}
    out, info = reconstruct(outlines, reference_pos=400.0)
    assert out is not None
    assert info["stage"] == "compatible"
    assert sum(1 for op, _ in out[950.0][0] if op == "curveTo") == 4

    # And it is still round: curvature times radius is 1 everywhere on a circle.
    worst = 0.0
    here = None
    for op, args in out[950.0][0]:
        if op == "moveTo":
            here = args[0]
        elif op == "curveTo":
            p1, p2, p3 = args
            for step in range(9):
                t = step / 8
                u = 1 - t
                dx = (
                    3 * u * u * (p1[0] - here[0])
                    + 6 * u * t * (p2[0] - p1[0])
                    + 3 * t * t * (p3[0] - p2[0])
                )
                dy = (
                    3 * u * u * (p1[1] - here[1])
                    + 6 * u * t * (p2[1] - p1[1])
                    + 3 * t * t * (p3[1] - p2[1])
                )
                ddx = 6 * u * (p2[0] - 2 * p1[0] + here[0]) + 6 * t * (p3[0] - 2 * p2[0] + p1[0])
                ddy = 6 * u * (p2[1] - 2 * p1[1] + here[1]) + 6 * t * (p3[1] - 2 * p2[1] + p1[1])
                scale = (dx * dx + dy * dy) ** 1.5
                if scale > 1e-12:
                    worst = max(worst, abs(abs(dx * ddy - dy * ddx) / scale * 120 - 1.0))
            here = p3
    assert worst < 0.03


def test_alignment_declines_when_node_counts_differ() -> None:
    """Rotation cannot reconcile masters that are genuinely drawn differently."""
    five = _circle(90)
    five.insert(2, ("lineTo", [five[1][1][-1]]))
    assert _align_starts({400.0: [_circle(90)], 950.0: [five]}, 400.0) is None


def test_rotation_is_tried_even_when_the_signature_disagrees() -> None:
    """The gate must key on the RESULT, not on the input.

    A rotated start is itself what makes `signature()` disagree, so requiring
    already-compatible input before rotating excludes exactly the glyphs that
    need it. `section` is written MLCCCCCLCCCLCCCCCLCCC at Thin and ExtraBlack
    and MCLCCCLCCCCCLCCCLCCCC at Book -- one sequence, turned by a node.
    """
    straight_first = _circle(90)
    straight_first[1] = ("lineTo", [_contour_node_points(straight_first)[1]])
    rotated = _rotate_contour(straight_first, 1)

    outlines = {400.0: [straight_first], 950.0: [rotated]}
    assert not _already_compatible(outlines)

    out, info = reconstruct(outlines, reference_pos=400.0)
    assert out is not None
    assert info["stage"] == "compatible"


def test_alignment_is_skipped_when_masters_disagree_on_contour_count() -> None:
    """_starts_aligned indexes every master by the reference's contour count."""
    outlines = {400.0: [_circle(90)], 950.0: [_circle(90), _circle(30, cx=300)]}
    # Must not raise; the existing reconstruction path deals with this.
    reconstruct(outlines, reference_pos=400.0)


def test_correspondence_survives_a_letterform_changing_proportion() -> None:
    """The absolute test cannot tell weight change from start drift.

    A square whose left stem thickens with weight keeps starting at the same
    corner, but that corner's position within the contour's own box moves a long
    way -- which `_starts_aligned` reads as drift. `H` does exactly this: it
    starts at 0.917 of the box at Thin and 0.693 at ExtraBlack.
    """
    from variable_gen.reconstruct_compatible import _starts_aligned, _starts_correspond

    def wedge(stem):
        # Starts at the apex, whose position across the fixed-width box moves as
        # the weight grows -- the shape of the H problem, without the H.
        return [
            ("moveTo", [(100.0 + stem, 700.0)]),
            ("lineTo", [(0.0, 0.0)]),
            ("lineTo", [(400.0, 0.0)]),
            ("lineTo", [(100.0 + stem, 700.0)]),
            ("closePath", []),
        ]

    outlines = {100.0: [wedge(30.0)], 400.0: [wedge(120.0)], 950.0: [wedge(280.0)]}
    assert not _starts_aligned(outlines)
    assert _starts_correspond(outlines, 400.0)


def test_correspondence_still_catches_a_genuinely_drifted_start() -> None:
    """The thing `_starts_aligned` exists to stop must still be stopped."""
    from variable_gen.reconstruct_compatible import _starts_correspond

    outlines = {400.0: [_circle(90)], 950.0: [_circle(120, start=2)]}
    assert not _starts_correspond(outlines, 400.0)
    # ...and rotating is what fixes it.
    turned = _align_starts(outlines, 400.0)
    assert turned is not None
    assert _starts_correspond(turned, 400.0)


def test_a_corner_sharp_in_only_one_master_is_still_a_shared_anchor() -> None:
    """`min` across masters drops it; `max` keeps it, which is what projection needs.

    Prevents: a right angle that exists at one weight and not another being
    buried inside a fit run, where the fitter subdivides trying to hold it with
    a cubic. That is what put `aogonek` at 626x the donor's curvature.
    """
    import math

    from variable_gen.reconstruct_compatible import _shared_corner_candidates

    def polygon(sides, spike=None):
        """A regular polygon; every turn is gentle unless one node is pulled out."""
        points = []
        for i in range(sides):
            angle = 2 * math.pi * i / sides
            radius = 300.0 if i != spike else 900.0
            points.append((radius * math.cos(angle), radius * math.sin(angle)))
        # No explicit closing lineTo: repeating the start point would make a
        # zero-length segment, and a zero-length segment reads as a right angle.
        ops = [("moveTo", [points[0]])]
        ops.extend(("lineTo", [point]) for point in points[1:])
        ops.append(("closePath", []))
        return ops

    # 24 sides -> 15 degree turns, under CURVE_CORNER_ANGLE, so nothing is sharp.
    smooth = polygon(24)
    spiked = polygon(24, spike=6)
    outlines = {400.0: [smooth], 950.0: [spiked]}

    shared = {index for _score, _ci, index in _shared_corner_candidates(outlines)}
    union = {index for _score, _ci, index in _shared_corner_candidates(outlines, combine=max)}
    assert shared == set(), "no node turns sharply in BOTH masters"
    assert 6 in union, "the spike is a real corner and must survive as an anchor"
    assert shared < union


def test_the_donors_own_drawing_is_not_challenged_by_a_resample_of_itself() -> None:
    """A `compatible` result is the donor's outline; there is nothing to improve.

    Prevents: `_ink_tournament` replacing an exact result with a uniform
    resample of the same shape. Both score 0.0 at the coarse blur, the fine
    score is relative-only, and a denser polyline wins it by construction --
    `uni2088` shipped as a 26-segment resample of a shape that was already right.
    """
    from variable_gen.reconstruct_compatible import _ink_tournament

    outlines = {100.0: [_circle(60)], 400.0: [_circle(90)], 950.0: [_circle(120)]}
    out, info = reconstruct(outlines, reference_pos=400.0)
    assert info["stage"] == "compatible"

    kept, kept_info = _ink_tournament(out, info, outlines, 400.0)
    assert kept is out
    assert kept_info is info
