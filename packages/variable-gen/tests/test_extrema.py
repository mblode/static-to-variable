from __future__ import annotations

import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PACKAGE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from variable_gen.extrema import (  # noqa: E402
    cluster_parameters,
    cubic_extrema,
    insert_extrema,
    needed_splits,
    parameters_for_master,
    split_segment,
)

ufoLib2 = pytest.importorskip("ufoLib2")


def _quarter_arc() -> tuple:
    """A quarter circle from (100, 0) to (0, 100): no extremum inside it."""
    k = 100 * 0.5522847498
    return ("c", (100.0, 0.0), (100.0, k), (k, 100.0), (0.0, 100.0))


def _half_arc() -> tuple:
    """Bottom to top the long way round, so the rightmost point is interior."""
    k = 100 * 0.5522847498 * 1.3333
    return ("c", (0.0, -100.0), (k, -100.0), (k, 100.0), (0.0, 100.0))


def _point_at(segment, t):
    _, p0, p1, p2, p3 = segment
    m = 1 - t
    return (
        m**3 * p0[0] + 3 * m * m * t * p1[0] + 3 * m * t * t * p2[0] + t**3 * p3[0],
        m**3 * p0[1] + 3 * m * m * t * p1[1] + 3 * m * t * t * p2[1] + t**3 * p3[1],
    )


def test_a_quarter_arc_turns_only_at_its_ends() -> None:
    assert cubic_extrema(_quarter_arc()) == []
    assert needed_splits(_quarter_arc()) == []


def test_a_half_arc_turns_once_in_the_middle() -> None:
    splits = needed_splits(_half_arc())

    assert len(splits) == 1
    assert splits[0] == pytest.approx(0.5, abs=1e-9)


def test_splitting_reproduces_the_curve_exactly() -> None:
    """The whole justification for doing this upstream: the split is not a fit."""
    segment = _half_arc()
    pieces = split_segment(segment, [0.25, 0.6])

    assert len(pieces) == 3
    bounds = [0.0, 0.25, 0.6, 1.0]
    for index, piece in enumerate(pieces):
        low, high = bounds[index], bounds[index + 1]
        for step in range(21):
            local = step / 20
            got = _point_at(piece, local)
            want = _point_at(segment, low + local * (high - low))
            assert got[0] == pytest.approx(want[0], abs=1e-9)
            assert got[1] == pytest.approx(want[1], abs=1e-9)


def test_a_split_lands_on_the_turn() -> None:
    segment = _half_arc()
    first, second = split_segment(segment, needed_splits(segment))

    # The shared node is the rightmost point, so both sides leave it vertically:
    # the neighbouring handle stands directly above or below it.
    assert first[4] == pytest.approx(second[1], abs=1e-9)
    assert first[4][0] == pytest.approx(_point_at(segment, 0.5)[0], abs=1e-9)
    assert first[3][0] == pytest.approx(first[4][0], abs=1e-6)
    assert second[2][0] == pytest.approx(second[1][0], abs=1e-6)


def test_masters_that_disagree_on_a_root_still_get_one_shared_split() -> None:
    """The gvar rule: same split count everywhere, each at its own turn."""
    clusters = cluster_parameters([0.49, 0.51, 0.52])

    assert clusters == [[0.49, 0.51, 0.52]]
    assert parameters_for_master(clusters, [0.49]) == [0.49]
    assert parameters_for_master(clusters, [0.52]) == [0.52]
    # A master flat enough to have no root of its own takes the cluster centre.
    assert parameters_for_master(clusters, []) == [pytest.approx(0.506666, abs=1e-5)]


def test_distinct_turns_stay_distinct() -> None:
    assert cluster_parameters([0.2, 0.8]) == [[0.2], [0.8]]


def _font_with(segment: tuple) -> ufoLib2.Font:
    font = ufoLib2.Font()
    glyph = font.newGlyph("test")
    pen = glyph.getPen()
    pen.moveTo(segment[1])
    pen.curveTo(segment[2], segment[3], segment[4])
    pen.lineTo(segment[1])
    pen.closePath()
    return font


def test_every_master_comes_back_with_the_same_point_count() -> None:
    """One master has an interior turn and the other does not; gvar needs both split."""
    monotone = ("c", (0.0, -100.0), (30.0, -40.0), (70.0, 40.0), (100.0, 100.0))
    turning = _font_with(_half_arc())
    flat = _font_with(monotone)
    assert needed_splits(_half_arc())
    assert not needed_splits(monotone)

    stats = insert_extrema([turning, flat])

    assert stats.splits == 1
    counts = {len(font["test"].contours[0]) for font in (turning, flat)}
    assert len(counts) == 1


def test_a_glyph_with_nothing_to_split_is_left_alone() -> None:
    font = _font_with(_quarter_arc())
    before = [(point.x, point.y, point.type) for point in font["test"].contours[0]]

    stats = insert_extrema([font])

    assert stats.splits == 0
    assert [(point.x, point.y, point.type) for point in font["test"].contours[0]] == before


def test_masters_that_already_disagree_on_structure_are_skipped() -> None:
    one = _font_with(_half_arc())
    other = ufoLib2.Font()
    pen = other.newGlyph("test").getPen()
    pen.moveTo((0.0, 0.0))
    pen.lineTo((10.0, 0.0))
    pen.lineTo((10.0, 10.0))
    pen.closePath()

    stats = insert_extrema([one, other])

    assert stats.skipped_incompatible == 1
    assert stats.splits == 0
