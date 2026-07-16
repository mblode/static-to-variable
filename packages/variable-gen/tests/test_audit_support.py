"""Unit tests for the audit gate's extracted geometry/report helpers.

The pure-geometry helpers get synthetic data; the font-level metrics run
against the committed Inter subset donors in examples/minimal (32K test
fixtures, no licensed fonts involved).
"""

import sys
import unittest
from pathlib import Path

PACKAGE_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PACKAGE_SRC))

from fontTools.ttLib import TTFont  # noqa: E402

from variable_gen.audit_support import (  # noqa: E402
    bounding_boxes_overlap,
    contour_segment_lengths,
    glyph_ink_area,
    glyph_intersection_metrics,
    glyph_point_deviation,
    json_safe,
    sample_cubic,
    sample_quadratic,
    segments_intersect,
    sign,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DONOR = REPO_ROOT / "examples/minimal/donors/Inter-Regular.ttf"


class PureGeometryTests(unittest.TestCase):
    def test_sign(self):
        self.assertEqual(sign(3.2), 1)
        self.assertEqual(sign(-0.1), -1)
        self.assertEqual(sign(0.0), 0)

    def test_sample_quadratic_ends_at_end_point(self):
        pts = sample_quadratic((0, 0), (5, 10), (10, 0), steps=4)
        self.assertEqual(len(pts), 4)
        self.assertEqual(pts[-1], (10, 0))

    def test_sample_cubic_ends_at_end_point(self):
        pts = sample_cubic((0, 0), (0, 10), (10, 10), (10, 0), steps=5)
        self.assertEqual(len(pts), 5)
        self.assertEqual(pts[-1], (10, 0))

    def test_bounding_boxes_overlap(self):
        self.assertTrue(bounding_boxes_overlap((0, 0), (10, 10), (5, 5), (15, 15)))
        self.assertFalse(bounding_boxes_overlap((0, 0), (10, 10), (20, 20), (30, 30)))

    def test_segments_intersect_crossing(self):
        self.assertTrue(segments_intersect((0, 0), (10, 10), (0, 10), (10, 0)))

    def test_segments_intersect_ignores_shared_endpoints(self):
        self.assertFalse(segments_intersect((0, 0), (10, 10), (10, 10), (20, 0)))

    def test_segments_intersect_parallel(self):
        self.assertFalse(segments_intersect((0, 0), (10, 0), (0, 5), (10, 5)))

    def test_contour_segment_lengths(self):
        lengths = contour_segment_lengths([[(0, 0), (3, 4), (3, 4)]])
        self.assertEqual(lengths, [5.0, 0.0])


class JsonSafeTests(unittest.TestCase):
    def test_passthrough_scalars_and_containers(self):
        value = {"a": [1, 2.5, "x", None, True], "b": {"c": (1, 2)}}
        self.assertEqual(json_safe(value), {"a": [1, 2.5, "x", None, True], "b": {"c": [1, 2]}})

    def test_numpy_like_item_unwrapping(self):
        class FakeScalar:
            def item(self):
                return 7

        self.assertEqual(json_safe({"n": FakeScalar()}), {"n": 7})

    def test_unknown_objects_stringify(self):
        class Odd:
            def __repr__(self):
                return "<odd>"

        self.assertEqual(json_safe(Odd()), "<odd>")

    def test_non_string_keys_coerced(self):
        self.assertEqual(json_safe({1: "a"}), {"1": "a"})


@unittest.skipUnless(DONOR.exists(), "minimal example donors not present")
class FontMetricTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.font = TTFont(str(DONOR))

    def test_ink_area_positive_for_real_glyph(self):
        self.assertGreater(glyph_ink_area(self.font, "A"), 0.0)

    def test_ink_area_zero_for_missing_glyph(self):
        self.assertEqual(glyph_ink_area(self.font, "no.such.glyph"), 0.0)

    def test_point_deviation_zero_against_itself(self):
        self.assertEqual(glyph_point_deviation(self.font, self.font, "A"), 0.0)

    def test_point_deviation_none_for_missing_glyph(self):
        self.assertIsNone(glyph_point_deviation(self.font, self.font, "no.such.glyph"))

    def test_intersection_metrics_clean_glyph(self):
        metrics = glyph_intersection_metrics(self.font, "o")
        self.assertEqual(metrics["intersections"], 0)
        self.assertFalse(metrics["zero_ink"])
        self.assertEqual(metrics["contours"], 2)

    def test_intersection_metrics_flags_overlapping_strokes(self):
        # Inter's A keeps its stem/crossbar overlaps in the static TTF; the
        # metric counts those crossings — that is exactly what it measures.
        metrics = glyph_intersection_metrics(self.font, "A")
        self.assertGreater(metrics["intersections"], 0)


if __name__ == "__main__":
    unittest.main()
