"""Tests for porting donor OpenType layout into a built variable font.

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

PACKAGE_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PACKAGE_SRC))

from fontTools.ttLib import TTFont  # noqa: E402

from variable_gen.layout import port_layout  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample-vf.ttf"
DONOR = REPO_ROOT / "examples/minimal/donors/Inter-Regular.ttf"


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

    def test_ported_gsub_only_references_font_glyphs(self):
        vf = TTFont(str(FIXTURE))
        port_layout(vf, DONOR)
        names = set(vf.getGlyphOrder())
        coverage = set()
        for lookup in vf["GSUB"].table.LookupList.Lookup:
            for sub in lookup.SubTable:
                cov = getattr(sub, "Coverage", None)
                if cov is not None:
                    coverage.update(cov.glyphs)
        self.assertTrue(coverage <= names)

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


if __name__ == "__main__":
    unittest.main()
