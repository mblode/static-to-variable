"""Tests for flattening donor kerning and making it vary with the weight axis.

Uses the committed variable-font fixture (tests/fixtures/sample-vf.ttf) and the
OFL Inter donors in examples/minimal, which carry real class-based GPOS kerning
that differs between weights — which is the whole point of the exercise.
"""

import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

PACKAGE_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PACKAGE_SRC))

from fontTools.ttLib import TTFont  # noqa: E402
from fontTools.ttLib.tables._f_v_a_r import Axis  # noqa: E402
from fontTools.varLib.instancer import instantiateVariableFont  # noqa: E402

from variable_gen.kerning import (  # noqa: E402
    X_ADVANCE_DEVICE,
    KerningTooLarge,
    flatten_kern,
    has_kern,
    vary_kern,
)
from variable_gen.layout import _vary_kerning, attach_layout, donor_kern, port_layout  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample-vf.ttf"
DONOR_DIR = REPO_ROOT / "examples/minimal/donors"
DEFAULT_DONOR = DONOR_DIR / "Inter-Regular.ttf"
ALL_DONORS = (
    (DONOR_DIR / "Inter-Thin.ttf", {"wght": 100.0}),
    (DEFAULT_DONOR, {"wght": 400.0}),
    (DONOR_DIR / "Inter-Black.ttf", {"wght": 900.0}),
)


def ported_fixture():
    """The fixture carrying the default donor's layout, as a real build would."""
    vf = TTFont(str(FIXTURE))
    report = port_layout(vf, DEFAULT_DONOR)
    assert report.mode == "static", report.note
    return vf


def donor_set(varfont):
    return [(location["wght"], donor_kern(path, varfont)) for path, location in ALL_DONORS]


def add_opsz_axis(varfont):
    axis = Axis()
    axis.axisTag = "opsz"
    axis.minValue = 12.0
    axis.defaultValue = 16.0
    axis.maxValue = 28.0
    axis.flags = 0
    axis.axisNameID = varfont["fvar"].axes[0].axisNameID
    varfont["fvar"].axes.append(axis)


class FlattenKernTests(unittest.TestCase):
    def test_resolves_class_kerning_into_explicit_pairs(self):
        pairs = flatten_kern(TTFont(str(DEFAULT_DONOR)))
        self.assertGreater(len(pairs), 100)
        for (left, right), value in pairs.items():
            self.assertIsInstance(left, str)
            self.assertIsInstance(right, str)
            self.assertNotEqual(value, 0, "zero pairs carry no kerning and must be dropped")

    def test_donors_disagree_across_weights(self):
        thin = flatten_kern(TTFont(str(ALL_DONORS[0][0])))
        black = flatten_kern(TTFont(str(ALL_DONORS[2][0])))
        shared = set(thin) & set(black)
        self.assertTrue(any(thin[pair] != black[pair] for pair in shared))

    def test_has_kern_agrees_with_flatten(self):
        self.assertTrue(has_kern(TTFont(str(DEFAULT_DONOR))))
        bare = TTFont(str(DEFAULT_DONOR))
        del bare["GPOS"]
        self.assertFalse(has_kern(bare))


class VaryKernTests(unittest.TestCase):
    def test_attaches_device_tables_and_a_variation_store(self):
        vf = ported_fixture()
        report = vary_kern(vf, donor_set(vf), axis_tag="wght")
        self.assertTrue(report.applied)
        self.assertEqual(report.masters, 3)
        self.assertGreater(report.varying, 0)
        self.assertLessEqual(report.varying, report.values)
        self.assertIsNotNone(vf["GDEF"].table.VarStore)
        formats = [
            sub.ValueFormat1
            for lookup in vf["GPOS"].table.LookupList.Lookup
            for sub in lookup.SubTable
            if hasattr(sub, "ValueFormat1")
        ]
        self.assertTrue(any(fmt & X_ADVANCE_DEVICE for fmt in formats))
        vf.save(BytesIO())

    def test_the_default_weight_keeps_exactly_the_values_it_had(self):
        before = flatten_kern(ported_fixture())
        varied = ported_fixture()
        vary_kern(varied, donor_set(varied), axis_tag="wght")
        buf = BytesIO()
        varied.save(buf)
        buf.seek(0)
        at_default = instantiateVariableFont(TTFont(buf), {"wght": 400}, inplace=False)
        self.assertEqual(flatten_kern(at_default), before)

    def test_instances_track_their_donors(self):
        varied = ported_fixture()
        donors = donor_set(varied)
        vary_kern(varied, donors, axis_tag="wght")
        buf = BytesIO()
        varied.save(buf)
        for position, donor_pairs in donors:
            buf.seek(0)
            instance = instantiateVariableFont(TTFont(buf), {"wght": position}, inplace=False)
            got = flatten_kern(instance)
            shared = [pair for pair in donor_pairs if pair in got]
            self.assertTrue(shared, f"no shared pairs at wght {position}")
            exact = sum(1 for pair in shared if got[pair] == donor_pairs[pair])
            self.assertEqual(exact, len(shared), f"wght {position} drifted from its donor")

    def test_identical_donors_produce_no_variation(self):
        vf = ported_fixture()
        same = donor_kern(DEFAULT_DONOR, vf)
        report = vary_kern(vf, [(100.0, same), (400.0, same), (900.0, same)], axis_tag="wght")
        self.assertFalse(report.applied)
        self.assertIsNone(getattr(vf["GDEF"].table, "VarStore", None))

    def test_refuses_a_font_that_already_varies(self):
        vf = ported_fixture()
        donors = donor_set(vf)
        self.assertTrue(vary_kern(vf, donors, axis_tag="wght").applied)
        again = vary_kern(vf, donors, axis_tag="wght")
        self.assertFalse(again.applied)
        self.assertIn("variation store", again.note)

    def test_needs_a_donor_at_the_default_position(self):
        vf = ported_fixture()
        off_axis = [(pos + 50, kern) for pos, kern in donor_set(vf)]
        report = vary_kern(vf, off_axis, axis_tag="wght")
        self.assertFalse(report.applied)
        self.assertIn("default axis position", report.note)

    def test_a_single_donor_is_not_enough(self):
        vf = ported_fixture()
        report = vary_kern(vf, donor_set(vf)[:1], axis_tag="wght")
        self.assertFalse(report.applied)
        self.assertIn("two donors", report.note)

    def test_cells_the_default_donor_does_not_reproduce_stay_constant(self):
        # The default donor's sample has to reproduce the value already in the
        # table — that value came from this donor. Where it does not, the
        # sample describes something else, and varying from it would move every
        # other master by the difference. Moving the default donor's values off
        # the table must therefore leave strictly fewer cells varying.
        baseline = ported_fixture()
        expected = vary_kern(baseline, donor_set(baseline), axis_tag="wght")

        vf = ported_fixture()
        donors = donor_set(vf)
        donors[1] = (400.0, {pair: value + 50 for pair, value in donors[1][1].items()})
        report = vary_kern(vf, donors, axis_tag="wght")

        self.assertGreater(expected.varying, 0)
        self.assertLess(report.varying, expected.varying)

    def test_repeated_weights_in_optical_rows_remain_distinct_masters(self):
        vf = ported_fixture()
        add_opsz_axis(vf)
        weight_donors = donor_set(vf)
        donors = [
            ({"wght": weight, "opsz": optical_size}, kern)
            for optical_size in (12.0, 16.0)
            for weight, kern in weight_donors
        ]

        report = vary_kern(vf, donors, axis_tag="wght")

        self.assertTrue(report.applied)
        self.assertEqual(report.masters, 6)
        vf.save(BytesIO())

    def test_layout_fallback_does_not_drop_duplicate_weights_across_opsz(self):
        vf = ported_fixture()
        add_opsz_axis(vf)
        masters = [
            (path, {"wght": location["wght"], "opsz": optical_size})
            for optical_size in (12.0, 16.0)
            for path, location in ALL_DONORS
        ]

        report = _vary_kerning(vf, masters, "wght")

        self.assertTrue(report.applied)
        self.assertEqual(report.masters, 6)


class FlattenLimitTests(unittest.TestCase):
    def test_a_font_too_large_to_flatten_raises_instead_of_truncating(self):
        with (
            mock.patch("variable_gen.kerning._MAX_FLAT_PAIRS", 10),
            self.assertRaises(KerningTooLarge),
        ):
            flatten_kern(TTFont(str(DEFAULT_DONOR)))

    def test_the_layout_tier_declines_rather_than_varying_from_a_partial_map(self):
        vf = ported_fixture()
        with (
            mock.patch("variable_gen.kerning._MAX_FLAT_PAIRS", 10),
            mock.patch("variable_gen.layout.varlib_build", side_effect=RuntimeError("boom")),
        ):
            report = attach_layout(vf, list(ALL_DONORS), default_donor=DEFAULT_DONOR)
        self.assertEqual(report.mode, "static")
        self.assertIn("expands past", report.note)
        vf.save(BytesIO())


if __name__ == "__main__":
    unittest.main()
