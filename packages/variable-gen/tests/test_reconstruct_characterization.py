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
    _corner_correspondence_ok,
    _cubic_in_tan,
    _cubic_out_tan,
    _expected_corner_count,
    _interpolation_rank,
    _order_normalize,
    _reconstruct_floating_contour,
    _signed_area,
    _stabilize_cubic_joins,
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

    def test_shuffled_mixed_structure_contours_are_ordered_before_resampling(self):
        """A contour-order flip must not map unlike pieces across the axis."""
        outlines = {
            100: [square(100.0), rounded_square(30.0, x=250.0, y=250.0)],
            400: [square(140.0), rounded_square(40.0, x=250.0, y=250.0)],
            900: [rounded_square(60.0, x=250.0, y=250.0), square(200.0)],
        }

        rec, info = reconstruct(outlines, reference_pos=400)

        self.assertIsNotNone(rec, info)
        assert rec is not None
        assert_interpolation_invariant(self, rec)
        for contours in rec.values():
            first = to_ring(contours[0])[0]
            second = to_ring(contours[1])[0]
            self.assertLess(max(x for x, _ in first), min(x for x, _ in second))

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

    def test_reconstructed_curves_do_not_ship_as_dense_polylines(self):
        outlines = {
            100: [rounded_square(100.0)],
            400: [rounded_square(140.0)],
            900: [rounded_square(200.0)],
        }
        # Force reconstruction with one redundant on-curve point in the heavy
        # master's straight edge; the rounded edge must remain cubic afterward.
        outlines[900][0].insert(1, ("lineTo", [(100.0, 0.0)]))
        rec, info = reconstruct(outlines, reference_pos=400)
        self.assertIsNotNone(rec, f"curve restoration failed: {info}")
        structures = {tuple((op, len(pts)) for op, pts in rec[pos][0]) for pos in sorted(rec)}
        self.assertEqual(len(structures), 1)
        self.assertIn("curveTo", {op for op, _ in rec[400][0]})
        self.assertLessEqual(sum(op == "lineTo" for op, _ in rec[400][0]), 3)
        self.assertLessEqual(
            sum(op == "curveTo" for op, _ in rec[400][0]),
            2,
            "a smooth donor curve must not fragment into tiny cubic spans",
        )

    def test_rejects_fallback_with_drifting_corner_indices(self):
        originals = scaled_squares()

        def sampled_square(offset: int):
            points = [
                (0.0, 0.0),
                (50.0, 0.0),
                (100.0, 0.0),
                (100.0, 50.0),
                (100.0, 100.0),
                (50.0, 100.0),
                (0.0, 100.0),
                (0.0, 50.0),
            ]
            points = points[offset:] + points[:offset]
            return [
                ("moveTo", [points[0]]),
                *(("lineTo", [point]) for point in points[1:]),
                ("closePath", []),
            ]

        candidate = {
            100: [sampled_square(0)],
            400: [sampled_square(0)],
            900: [sampled_square(1)],
        }
        self.assertFalse(_corner_correspondence_ok(candidate, originals))

    def test_smooth_cubic_join_uses_one_arm_ratio_across_masters(self):
        def contour(incoming, outgoing):
            return [
                ("moveTo", [(0.0, 0.0)]),
                ("curveTo", [(20.0, 0.0), (100.0 - incoming, 100.0), (100.0, 100.0)]),
                ("curveTo", [(100.0 + outgoing, 100.0), (180.0, 20.0), (200.0, 0.0)]),
                ("closePath", []),
            ]

        contours = {100: contour(20.0, 40.0), 400: contour(30.0, 30.0), 900: contour(40.0, 20.0)}
        _stabilize_cubic_joins(contours, {position: set() for position in contours})
        ratios = []
        for outline in contours.values():
            join = outline[1][1][-1]
            incoming = join[0] - outline[1][1][-2][0]
            outgoing = outline[2][1][0][0] - join[0]
            ratios.append(incoming / outgoing)
        self.assertAlmostEqual(min(ratios), max(ratios))

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

    def test_topology_choice_prefers_cleaner_interpolation(self):
        clean = scaled_squares()
        folded = scaled_squares()
        # Corresponding nodes cross between the first two masters, creating ink
        # outside both endpoints despite clean endpoint outlines.
        folded[400] = [
            [
                ("moveTo", [(0.0, 0.0)]),
                ("lineTo", [(140.0, 140.0)]),
                ("lineTo", [(140.0, 0.0)]),
                ("lineTo", [(0.0, 140.0)]),
                ("closePath", []),
            ]
        ]
        self.assertLess(_interpolation_rank(clean), _interpolation_rank(folded))

    def test_reconstructs_detached_accent_separately_from_body(self):
        outlines = {
            100: [square(100.0), square(25.0, x=55.0, y=240.0)],
            400: [rounded_square(140.0), square(25.0, x=55.0, y=240.0)],
            900: [square(200.0), square(25.0, x=55.0, y=240.0)],
        }
        rec = _reconstruct_floating_contour(outlines, reference_pos=400)
        self.assertIsNotNone(rec)
        assert_interpolation_invariant(self, rec)
        self.assertEqual({len(contours) for contours in rec.values()}, {2})

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

    def test_order_normalize_uses_area_for_concentric_same_winding_contours(self):
        def centered(size):
            return square(size, x=-size / 2, y=-size / 2)

        outlines = {
            100: [centered(180.0), centered(60.0)],
            400: [centered(200.0), centered(70.0)],
            900: [centered(90.0), centered(240.0)],  # shuffled, same centroid/sign
        }

        normalized = _order_normalize(outlines, reference_pos=400)

        self.assertIsNotNone(normalized)
        assert normalized is not None
        heavy_areas = [abs(_signed_area(to_ring(contour)[0])) for contour in normalized[900]]
        self.assertGreater(heavy_areas[0], heavy_areas[1])


class DegenerateHandleTests(unittest.TestCase):
    def test_collapsed_outgoing_handle_skips_stub(self):
        """CFF rounding can leave a 0–1 unit stub handle (Thin ``d`` @ 532)."""
        a, b = (222.0, 533.0), (74.0, 413.0)
        # Stub c1 is 1 unit away; prefer the longer c2 over the stub tangent.
        self.assertEqual(
            _cubic_out_tan(a, (222.0, 532.0), (128.0, 523.0), b),
            _cubic_out_tan(a, (128.0, 523.0), (128.0, 523.0), b),
        )

    def test_collapsed_incoming_handle_skips_zero_length(self):
        start, end = (291.0, 535.0), (222.0, 533.0)
        # c2 collapsed onto the end node → fall back to c1 → end.
        self.assertEqual(
            _cubic_in_tan(start, (245.0, 537.0), end, end),
            _cubic_in_tan(start, (245.0, 537.0), (245.0, 537.0), end),
        )


class ExpectedCornerCountTests(unittest.TestCase):
    def test_unanimous_counts(self):
        outlines = scaled_squares()
        self.assertEqual(_expected_corner_count(outlines), 4)

    def test_single_corner_flicker_uses_majority(self):
        outlines = scaled_squares()
        # Extra notch on the light master only (one-corner flicker).
        light = [
            ("moveTo", [(0.0, 0.0)]),
            ("lineTo", [(100.0, 0.0)]),
            ("lineTo", [(100.0, 100.0)]),
            ("lineTo", [(50.0, 70.0)]),
            ("lineTo", [(0.0, 100.0)]),
            ("closePath", []),
        ]
        outlines[100] = [light]
        self.assertEqual(_expected_corner_count(outlines), 4)

    def test_wide_disagreement_returns_none(self):
        outlines = scaled_squares()
        # Star-like zigzag: many real corners, not a one-count flicker.
        heavy = [
            ("moveTo", [(100.0, 0.0)]),
            ("lineTo", [(120.0, 60.0)]),
            ("lineTo", [(200.0, 60.0)]),
            ("lineTo", [(140.0, 100.0)]),
            ("lineTo", [(160.0, 180.0)]),
            ("lineTo", [(100.0, 130.0)]),
            ("lineTo", [(40.0, 180.0)]),
            ("lineTo", [(60.0, 100.0)]),
            ("lineTo", [(0.0, 60.0)]),
            ("lineTo", [(80.0, 60.0)]),
            ("closePath", []),
        ]
        outlines[900] = [heavy]
        self.assertIsNone(_expected_corner_count(outlines))


class ContourCountChangeTests(unittest.TestCase):
    def test_merging_extra_contour_still_weight_varies(self):
        """A stub contour that exists only at one weight must not freeze the glyph.

        Failure this prevents: topology-change glyphs (r.ss03 / tcommaaccent)
        returning None and being pinned to Book@400.
        """
        stub = [square(20.0, x=250.0, y=250.0)]
        outlines = {
            100: [square(100.0), *stub],
            400: [square(140.0)],
            900: [square(200.0)],
        }
        rec, info = reconstruct(outlines, reference_pos=400)
        self.assertIsNotNone(rec, f"expected weight-varying fallback, got {info}")
        assert_interpolation_invariant(self, rec)
        widths = []
        for pos in sorted(rec):
            xs = [p[0] for op, pts in rec[pos][0] if op in ("moveTo", "lineTo") for p in pts]
            widths.append(max(xs) - min(xs))
        self.assertNotEqual(widths[0], widths[-1], f"widths stuck: {widths}")


class WindingTests(unittest.TestCase):
    def test_ccw_is_positive(self):
        self.assertEqual(_winding([(0, 0), (10, 0), (10, 10), (0, 10)]), 1)

    def test_cw_is_negative(self):
        self.assertEqual(_winding([(0, 0), (0, 10), (10, 10), (10, 0)]), -1)

    def test_degenerate_is_zero(self):
        self.assertEqual(_winding([(0, 0), (10, 0)]), 0)


if __name__ == "__main__":
    unittest.main()
