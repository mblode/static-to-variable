"""Characterization tests for the glyph reconstruction engine.

The engine (variable_gen.reconstruct_compatible) is verbatim-ported legacy
geometry code with no licensed donor fonts available to exercise it end to end.
These tests pin its observable contract on small synthetic contours — the
interpolation invariant above all: whatever reconstruct() returns must have the
SAME contour count and per-contour node counts at every axis position.
"""

import sys
import unittest
from pathlib import Path

PACKAGE_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PACKAGE_SRC))

from variable_gen.outlines import _winding, signature  # noqa: E402
from variable_gen.reconstruct_compatible import (  # noqa: E402
    _already_compatible,
    _order_normalize,
    _starts_aligned,
    reconstruct,
    to_ring,
)


def square(size: float, x: float = 0.0, y: float = 0.0, reverse: bool = False):
    """A closed square contour in the (op, [pts]) format donor_outline emits."""
    pts = [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]
    if reverse:
        pts = [pts[0], *reversed(pts[1:])]
    return [
        ("moveTo", [pts[0]]),
        ("lineTo", [pts[1]]),
        ("lineTo", [pts[2]]),
        ("lineTo", [pts[3]]),
        ("closePath", []),
    ]


def rounded_square(size: float, x: float = 0.0, y: float = 0.0):
    """A square whose right edge is a cubic curve — mixes segment types."""
    return [
        ("moveTo", [(x, y)]),
        ("lineTo", [(x + size, y)]),
        (
            "curveTo",
            [
                (x + size * 1.2, y + size * 0.3),
                (x + size * 1.2, y + size * 0.7),
                (x + size, y + size),
            ],
        ),
        ("lineTo", [(x, y + size)]),
        ("closePath", []),
    ]


def scaled_squares(sizes=(100.0, 140.0, 200.0)):
    """One square per weight, scaling monotonically — the compatible base case."""
    return {pos: [square(size)] for pos, size in zip((100, 400, 900), sizes, strict=True)}


def node_counts(contours):
    return [sum(1 for op, _ in con if op not in ("closePath", "endPath")) for con in contours]


def assert_interpolation_invariant(case: unittest.TestCase, rec: dict) -> None:
    """Every position must share one contour count and per-contour node counts."""
    per_pos = {pos: node_counts(contours) for pos, contours in rec.items()}
    distinct = {tuple(counts) for counts in per_pos.values()}
    case.assertEqual(len(distinct), 1, f"structures diverge across weights: {per_pos}")


class AlreadyCompatibleTests(unittest.TestCase):
    def test_identical_structures_are_compatible(self):
        self.assertTrue(_already_compatible(scaled_squares()))

    def test_contour_count_mismatch_is_incompatible(self):
        outlines = scaled_squares()
        outlines[900] = [square(200.0), square(40.0, x=60.0, y=60.0)]
        self.assertFalse(_already_compatible(outlines))

    def test_segment_type_mismatch_is_incompatible(self):
        outlines = scaled_squares()
        outlines[900] = [rounded_square(200.0)]
        self.assertFalse(_already_compatible(outlines))

    def test_reversed_winding_is_incompatible(self):
        outlines = scaled_squares()
        outlines[900] = [square(200.0, reverse=True)]
        self.assertFalse(_already_compatible(outlines))


class ReconstructTests(unittest.TestCase):
    def test_compatible_outlines_pass_through(self):
        outlines = scaled_squares()
        rec, info = reconstruct(outlines, reference_pos=400)
        self.assertIsNotNone(rec)
        self.assertEqual(sorted(rec), [100, 400, 900])
        assert_interpolation_invariant(self, rec)
        # Already-compatible squares keep their exact node structure.
        self.assertEqual(node_counts(rec[400]), node_counts(outlines[400]))

    def test_reversed_winding_is_normalized(self):
        outlines = scaled_squares()
        outlines[900] = [square(200.0, reverse=True)]
        rec, info = reconstruct(outlines, reference_pos=400)
        self.assertIsNotNone(rec, f"winding normalization failed: {info}")
        assert_interpolation_invariant(self, rec)
        windings = set()
        for contours in rec.values():
            ring = to_ring(contours[0])[0]
            windings.add(_winding(ring))
        self.assertEqual(len(windings), 1, "winding still differs across weights")

    def test_node_count_mismatch_resamples_to_shared_structure(self):
        outlines = scaled_squares()
        # The heavy master gains an extra node on the bottom edge.
        heavy = [
            ("moveTo", [(0.0, 0.0)]),
            ("lineTo", [(90.0, 0.0)]),
            ("lineTo", [(200.0, 0.0)]),
            ("lineTo", [(200.0, 200.0)]),
            ("lineTo", [(0.0, 200.0)]),
            ("closePath", []),
        ]
        outlines[900] = [heavy]
        rec, info = reconstruct(outlines, reference_pos=400)
        self.assertIsNotNone(rec, f"resample failed: {info}")
        assert_interpolation_invariant(self, rec)

    def test_returns_none_or_compatible_for_contour_count_mismatch(self):
        outlines = scaled_squares()
        outlines[900] = [square(200.0), square(40.0, x=60.0, y=60.0)]
        rec, info = reconstruct(outlines, reference_pos=400)
        # Counter-closing may or may not reconcile this; the contract is that a
        # non-None result is interpolation-compatible and a None result carries
        # a diagnostic note for the freeze fallback.
        if rec is None:
            self.assertIn("note", info)
        else:
            assert_interpolation_invariant(self, rec)

    def test_info_reports_a_stage(self):
        _, info = reconstruct(scaled_squares(), reference_pos=400)
        self.assertIn("stage", info)


class RingAndOrderTests(unittest.TestCase):
    def test_to_ring_square_corners(self):
        ring, _, corners = to_ring(square(100.0))
        self.assertEqual(len(ring), len(corners))
        # A straight-edged square has exactly its 4 nodes, all corners.
        self.assertEqual(len(ring), 4)
        self.assertTrue(all(corners))

    def test_to_ring_curve_samples_are_not_corners(self):
        ring, _, corners = to_ring(rounded_square(100.0))
        self.assertEqual(len(ring), len(corners))
        # Dense curve samples exist and none of them is flagged as a corner.
        self.assertGreater(len(ring), 4)
        self.assertLess(sum(corners), len(corners))

    def test_starts_aligned_detects_rotated_start(self):
        aligned = scaled_squares()
        self.assertTrue(_starts_aligned(aligned))

        rotated = scaled_squares()
        # Same square, but the heavy master starts at the opposite corner.
        rotated[900] = [
            [
                ("moveTo", [(200.0, 200.0)]),
                ("lineTo", [(0.0, 200.0)]),
                ("lineTo", [(0.0, 0.0)]),
                ("lineTo", [(200.0, 0.0)]),
                ("closePath", []),
            ]
        ]
        self.assertFalse(_starts_aligned(rotated))

    def test_order_normalize_matches_shuffled_contours(self):
        big, small = square(200.0), square(40.0, x=300.0, y=300.0)
        outlines = {
            100: [square(100.0), square(20.0, x=300.0, y=300.0)],
            400: [square(140.0), square(30.0, x=300.0, y=300.0)],
            900: [square(40.0, x=300.0, y=300.0), square(200.0)],  # shuffled
        }
        normalized = _order_normalize(outlines, reference_pos=400)
        self.assertIsNotNone(normalized)
        self.assertEqual(len(normalized[900]), 2)
        self.assertEqual(signature(normalized[900]), signature([big, small]))
        # The big contour is first again at the heavy master.
        first_ring = to_ring(normalized[900][0])[0]
        self.assertGreater(max(x for x, _ in first_ring), 100.0)


class WindingTests(unittest.TestCase):
    def test_ccw_is_positive(self):
        self.assertEqual(_winding([(0, 0), (10, 0), (10, 10), (0, 10)]), 1)

    def test_cw_is_negative(self):
        self.assertEqual(_winding([(0, 0), (0, 10), (10, 10), (10, 0)]), -1)

    def test_degenerate_is_zero(self):
        self.assertEqual(_winding([(0, 0), (10, 0)]), 0)


if __name__ == "__main__":
    unittest.main()
