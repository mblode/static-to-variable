"""The height-normalisation rule must measure the letter, not its accent.

`normalize` exists to fix a letter that floats off the baseline or falls short
of the default cap. Measuring the whole layer reads a floating accent's height
as the letter's, and the rule then squashes the letter to make ACCENT tops
agree -- which is what shipped Glide's dieresis family 4-5% short at ExtraBlack.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from variable_gen.normalize import base_metrics  # noqa: E402


class _Path:
    def __init__(self, points):
        self._points = points

    def draw(self, pen):
        pen.moveTo(self._points[0])
        for point in self._points[1:]:
            pen.lineTo(point)
        pen.closePath()


class _Layer:
    def __init__(self, paths):
        self.paths = paths


def _box(x0, y0, x1, y1):
    return _Path([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def test_a_floating_accent_does_not_decide_the_letters_height() -> None:
    """The dieresis case: dots clear of the letter must not enter the box.

    Prevents: `adieresis` reading its cap as 730 (the accent top) instead of 584
    (the letter), tripping the shortfall rule by three units and being rescaled.
    """
    letter = _box(0, 0, 500, 584)
    left_dot = _box(120, 640, 220, 730)
    right_dot = _box(300, 640, 400, 730)

    assert base_metrics(_Layer([letter, left_dot, right_dot])) == (0, 584)
    # ...and the letter alone measures the same, which is the whole point.
    assert base_metrics(_Layer([letter])) == (0, 584)


def test_a_connected_accent_still_counts_as_the_letter() -> None:
    """Only DETACHED contours are excluded; a tall single contour is the letter."""
    tall = _box(0, 0, 500, 800)
    assert base_metrics(_Layer([tall])) == (0, 800)


def test_a_counter_does_not_count_as_a_floating_accent() -> None:
    """`o`'s counter sits inside the letter and must not be dropped."""
    outer = _box(0, 0, 500, 560)
    counter = _box(90, 90, 410, 470)
    assert base_metrics(_Layer([outer, counter])) == (0, 560)


def test_all_contours_detached_falls_back_to_the_whole_layer() -> None:
    """Never return nothing: a shape with no grounded contour keeps its box."""
    high_one = _box(0, 900, 100, 950)
    high_two = _box(200, 905, 300, 955)
    assert base_metrics(_Layer([high_one, high_two])) == (900, 955)


def test_an_empty_layer_is_declined_rather_than_guessed() -> None:
    assert base_metrics(_Layer([])) is None
    assert base_metrics(_Layer(None)) is None
