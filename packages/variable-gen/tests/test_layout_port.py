"""Tests for porting / attaching donor OpenType layout into a built variable font.

Uses the committed variable-font fixture (tests/fixtures/sample-vf.ttf, 15
glyphs) and the OFL Inter donors in examples/minimal (full statics with real
GDEF/GSUB/GPOS), so the port has to prune donor lookups down to the small
shared glyph set and still produce a compilable font.
"""

import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

PACKAGE_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PACKAGE_SRC))

from fontTools.ttLib import TTFont  # noqa: E402

from variable_gen.layout import attach_layout, port_layout  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample-vf.ttf"
DONOR_DIR = REPO_ROOT / "examples/minimal/donors"
DONOR = DONOR_DIR / "Inter-Regular.ttf"
DONORS = (
    (DONOR_DIR / "Inter-Thin.ttf", {"wght": 100.0}),
    (DONOR_DIR / "Inter-Regular.ttf", {"wght": 400.0}),
    (DONOR_DIR / "Inter-Black.ttf", {"wght": 900.0}),
)


class PortLayoutTests(unittest.TestCase):
    def test_ports_and_prunes_donor_layout(self):
        # Donor has 180 glyphs of layout; the VF has 15. The port must prune
        # every lookup down to the shared set and still compile.
        vf = TTFont(str(FIXTURE))
        report = port_layout(vf, DONOR)
        self.assertEqual(report.mode, "static")
        self.assertIn("GPOS", report.tables)
        self.assertIn("GSUB", report.tables)
        vf.save(BytesIO())

    def test_compile_failure_rolls_back_and_keeps_original_layout(self):
        # If the ported tables copy in but won't compile, the VF must be left
        # with its own layout untouched, not stripped.
        vf = TTFont(str(FIXTURE))
        original_gpos = vf["GPOS"]
        with mock.patch("variable_gen.layout._compiles", return_value=False):
            report = port_layout(vf, DONOR)
        self.assertEqual(report.mode, "none")
        self.assertEqual(report.note, "ported tables failed to compile")
        self.assertIs(vf["GPOS"], original_gpos)

    def test_donor_without_layout_reports_none_and_leaves_font_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            bare = TTFont(str(DONOR))
            for tag in ("GDEF", "GSUB", "GPOS"):
                if tag in bare:
                    del bare[tag]
            bare_path = Path(tmp) / "bare.ttf"
            bare.save(str(bare_path))

            vf = TTFont(str(FIXTURE))
            original_gpos = vf["GPOS"]  # the fixture ships its own layout
            report = port_layout(vf, bare_path)
        self.assertEqual(report.mode, "none")
        self.assertIs(vf["GPOS"], original_gpos)


class AttachLayoutTests(unittest.TestCase):
    def test_single_master_falls_back_to_static_port(self):
        vf = TTFont(str(FIXTURE))
        report = attach_layout(
            vf,
            [(DONOR, {"wght": 400.0})],
            default_donor=DONOR,
        )
        self.assertEqual(report.mode, "static")
        self.assertIn("GPOS", report.tables)
        vf.save(BytesIO())

    def test_multi_master_attaches_compilable_layout(self):
        for path, _ in DONORS:
            self.assertTrue(path.is_file(), f"missing donor {path}")
        vf = TTFont(str(FIXTURE))
        report = attach_layout(
            vf,
            list(DONORS),
            default_donor=DONOR,
            axis_tag="wght",
            axis_name="Weight",
        )
        # Inter minimal donors share layout structure — expect variable kerning.
        self.assertEqual(report.mode, "variable")
        self.assertIn("GPOS", report.tables)
        self.assertIn("GSUB", report.tables)
        vf.save(BytesIO())
        self.assertEqual(report.summary(), "layout: variable (GDEF, GSUB, GPOS)")

    def test_varlib_failure_falls_back_to_static(self):
        vf = TTFont(str(FIXTURE))
        with mock.patch(
            "variable_gen.layout.varlib_build",
            side_effect=RuntimeError("boom"),
        ):
            report = attach_layout(
                vf,
                list(DONORS),
                default_donor=DONOR,
            )
        self.assertEqual(report.mode, "static")
        self.assertIn("GPOS", report.tables)
        vf.save(BytesIO())


if __name__ == "__main__":
    unittest.main()
