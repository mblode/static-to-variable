"""Making masters agree on segment counts by splitting, which must be exact.

Circular spends different numbers of segments on the same stretch in different
weights -- `three` is `L CCCC L CCCC LLLLLL` at Thin and `L CCCC L CCC LLLLLL`
at Book. The run structure agrees; only the counts differ. Splitting the sparser
master's segment brings them into line and must not move the outline by so much
as a rounding error, or the whole point is lost.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from variable_gen.reconstruct_compatible import (  # noqa: E402
    _already_compatible,
    _drop_redundant_line_nodes,
    _grow_run,
    _split_segment_once,
    _unify_run_counts,
)

K = 0.5522847498307936


def _cubic_at(p0, p1, p2, p3, t):
    u = 1 - t
    return (
        u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
        u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
    )


def test_splitting_a_cubic_reproduces_it_exactly() -> None:
    """The halves must trace the original curve, not merely end where it ends."""
    start, c1, c2, end = (0.0, 0.0), (30.0, 120.0), (170.0, 140.0), (200.0, 20.0)
    pair, mid = _split_segment_once("curveTo", [c1, c2, end], start)
    assert pair is not None
    left, right = pair

    for step in range(101):
        t = step / 100
        want = _cubic_at(start, c1, c2, end, t)
        if t <= 0.5:
            got = _cubic_at(start, *left[1], t * 2)
        else:
            got = _cubic_at(mid, *right[1], (t - 0.5) * 2)
        assert got[0] == pytest.approx(want[0], abs=1e-9)
        assert got[1] == pytest.approx(want[1], abs=1e-9)


def test_splitting_a_line_lands_on_its_midpoint() -> None:
    pair, mid = _split_segment_once("lineTo", [(100.0, 40.0)], (0.0, 0.0))
    assert mid == (50.0, 20.0)
    assert [op for op, _ in pair] == ["lineTo", "lineTo"]


def test_growing_a_run_adds_exactly_the_nodes_asked_for() -> None:
    run = [("lineTo", [(90.0, 0.0)]), ("lineTo", [(100.0, 0.0)])]
    grown = _grow_run(run, (0.0, 0.0), 4)
    assert len(grown) == 4
    # Always the longest remaining segment, so the 90 is halved and then its
    # halves are: 90 -> 45|45 -> 22.5|22.5|45. The 10 is never touched, which is
    # the point -- nodes land where the run is long, not spread evenly.
    assert [point[1][-1][0] for point in grown] == [22.5, 45.0, 90.0, 100.0]


def test_a_node_sitting_on_its_own_chord_is_dropped() -> None:
    run = [("lineTo", [(50.0, 0.0)]), ("lineTo", [(100.0, 0.0)])]
    assert _drop_redundant_line_nodes(run, (0.0, 0.0)) == [("lineTo", [(100.0, 0.0)])]


def test_a_spike_doubling_back_is_not_mistaken_for_a_redundant_node() -> None:
    """Collinear is not enough -- the node has to lie BETWEEN its neighbours."""
    run = [("lineTo", [(150.0, 0.0)]), ("lineTo", [(100.0, 0.0)])]
    assert len(_drop_redundant_line_nodes(run, (0.0, 0.0))) == 2


def _square(size, extra_curve=False):
    """A rounded square, optionally drawn with one corner in two curves."""
    s = size
    k = s * K * 0.5
    ops = [("moveTo", [(0.0, 0.0)])]
    ops.append(("lineTo", [(s, 0.0)]))
    if extra_curve:
        ops.append(("curveTo", [(s + k / 2, 0.0), (s + k, k / 2), (s + k, k)]))
        ops.append(("curveTo", [(s + k, k * 1.5), (s + k / 2, s), (s, s)]))
    else:
        ops.append(("curveTo", [(s + k, 0.0), (s + k, s), (s, s)]))
    ops.append(("lineTo", [(0.0, s)]))
    ops.append(("lineTo", [(0.0, 0.0)]))
    ops.append(("closePath", []))
    return ops


def test_masters_spending_different_segments_on_a_run_are_reconciled() -> None:
    outlines = {
        100.0: [_square(100.0)],
        400.0: [_square(140.0, extra_curve=True)],
        950.0: [_square(200.0)],
    }
    assert not _already_compatible(outlines)

    unified = _unify_run_counts(outlines, 400.0)
    assert unified is not None
    assert _already_compatible(unified)
    for pos in outlines:
        assert sum(1 for op, _ in unified[pos][0] if op == "curveTo") == 2


def test_unification_declines_a_contour_that_closes_implicitly() -> None:
    """`closePath` may stand for an edge the segment list does not carry, and
    turning the runs would drop it."""
    open_ended = [
        ("moveTo", [(0.0, 0.0)]),
        ("lineTo", [(100.0, 0.0)]),
        ("curveTo", [(140.0, 0.0), (140.0, 100.0), (100.0, 100.0)]),
        ("closePath", []),
    ]
    assert _unify_run_counts({400.0: [open_ended], 950.0: [open_ended]}, 400.0) is None


def test_promoting_a_line_to_a_cubic_traces_the_same_straight_segment() -> None:
    """A line IS a cubic with its controls on the chord; the raise must be exact.

    Prevents: `_promote_lines_to_curves` bowing a straight stem while making the
    masters agree, which would be a shape change dressed up as notation.
    """
    from variable_gen.reconstruct_compatible import _promote_lines_to_curves

    def box(curved_top):
        top = (
            ("curveTo", [(33.0, 100.0), (67.0, 100.0), (100.0, 100.0)])
            if curved_top
            else ("lineTo", [(100.0, 100.0)])
        )
        return [
            ("moveTo", [(0.0, 0.0)]),
            ("lineTo", [(0.0, 100.0)]),
            top,
            ("lineTo", [(100.0, 0.0)]),
            ("lineTo", [(0.0, 0.0)]),
            ("closePath", []),
        ]

    outlines = {400.0: [box(False)], 950.0: [box(True)]}
    promoted = _promote_lines_to_curves(outlines, 400.0)

    raised = promoted[400.0][0][2]
    assert raised[0] == "curveTo"
    # Controls a third and two thirds along the chord from (0,100) to (100,100),
    # so the cubic traces exactly that straight segment.
    assert raised[1][0] == pytest.approx((100 / 3, 100.0))
    assert raised[1][1] == pytest.approx((200 / 3, 100.0))
    assert raised[1][2] == (100.0, 100.0)
    # Every other segment is left alone -- no blanket promotion.
    assert [op for op, _ in promoted[400.0][0]] == [
        "moveTo",
        "lineTo",
        "curveTo",
        "lineTo",
        "lineTo",
        "closePath",
    ]


def test_promotion_declines_when_the_counts_do_not_already_agree() -> None:
    """Without positional correspondence there is no 'same place' to compare."""
    from variable_gen.reconstruct_compatible import _promote_lines_to_curves

    short = [
        ("moveTo", [(0.0, 0.0)]),
        ("lineTo", [(100.0, 0.0)]),
        ("lineTo", [(0.0, 0.0)]),
        ("closePath", []),
    ]
    long = [
        ("moveTo", [(0.0, 0.0)]),
        ("curveTo", [(30.0, 0.0), (70.0, 0.0), (100.0, 0.0)]),
        ("lineTo", [(50.0, 50.0)]),
        ("lineTo", [(0.0, 0.0)]),
        ("closePath", []),
    ]
    outlines = {400.0: [short], 950.0: [long]}
    assert _promote_lines_to_curves(outlines, 400.0) is outlines
