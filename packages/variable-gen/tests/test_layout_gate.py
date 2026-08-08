"""Tests for the blocking layout stage in the promotion gate.

Layout transfer degrades quietly at every level by design, so the gate is what
stops a font that lost its features, its kerning or its GDEF from being
promoted. These pin each way it is supposed to go red.
"""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PACKAGE_SRC))

from variable_gen.pipeline import build_pipeline_status  # noqa: E402

HEALTHY = {
    "features": {
        "donor_gpos": ["kern", "mark"],
        "donor_gsub": ["liga", "onum"],
        "missing_gpos": [],
        "missing_gsub": [],
        "output_gpos": ["kern", "mark"],
        "output_gsub": ["liga", "onum"],
    },
    "gdef": {"donor": True, "output": True, "var_store": True},
    "glyphs": {"donor": 500, "output": 500},
    "hinting": {"gasp": True, "mode": "smooth", "prep": True},
    "kern": {
        "donor_pairs": 1000,
        "donors_with_kern": 3,
        "output_pairs": 1000,
        "values": 400,
        "varying": 120,
    },
    "layout": {"mode": "variable-kern", "note": "", "tables": ["GDEF", "GSUB", "GPOS"]},
}


def status_for(entry):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        reports = root / "packages/variable-gen/reports"
        reports.mkdir(parents=True)
        (reports / "reconstruction-report.json").write_text(json.dumps({"roman": {"donor": 1}}))
        (reports / "layout-report.json").write_text(json.dumps({"roman": entry}))
        report = build_pipeline_status(root)
    return next(stage for stage in report["stages"] if stage["id"] == "layout"), report


class LayoutStageTests(unittest.TestCase):
    def test_a_healthy_transfer_passes(self):
        stage, report = status_for(HEALTHY)
        self.assertEqual(stage["status"], "pass")
        self.assertEqual(stage["failures"], [])
        self.assertTrue(stage["blocking"])
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(stage["summary"]["roman_layout_mode"], "variable-kern")

    def test_a_missing_report_does_not_block(self):
        # Only `build` writes the layout report, and the staged pipeline stops
        # at rebuild + audit. A pipeline run that never built must not go red.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "packages/variable-gen/reports"
            reports.mkdir(parents=True)
            (reports / "reconstruction-report.json").write_text(json.dumps({"roman": {"donor": 1}}))
            report = build_pipeline_status(root)
        stage = next(s for s in report["stages"] if s["id"] == "layout")
        self.assertEqual(stage["status"], "missing")
        self.assertFalse(stage["blocking"])
        self.assertEqual(report["verdict"], "pass")

    def test_a_report_that_is_present_still_blocks(self):
        entry = copy.deepcopy(HEALTHY)
        entry["gdef"]["output"] = False
        stage, report = status_for(entry)
        self.assertTrue(stage["blocking"])
        self.assertEqual(report["verdict"], "fail")

    def test_lost_features_fail(self):
        entry = copy.deepcopy(HEALTHY)
        entry["features"]["missing_gsub"] = ["onum"]
        entry["features"]["missing_gpos"] = ["mark"]
        stage, report = status_for(entry)
        self.assertEqual(report["verdict"], "fail")
        self.assertIn("lost donor features: mark, onum", stage["failures"][0])

    def test_dropped_kern_pairs_fail(self):
        entry = copy.deepcopy(HEALTHY)
        entry["kern"]["output_pairs"] = 800
        stage, _ = status_for(entry)
        self.assertIn("kept 800 of the donor's 1000 kern pairs", stage["failures"][0])

    def test_pruning_a_few_pairs_is_tolerated(self):
        entry = copy.deepcopy(HEALTHY)
        entry["kern"]["output_pairs"] = 995
        stage, _ = status_for(entry)
        self.assertEqual(stage["status"], "pass")

    def test_a_lost_gdef_fails(self):
        entry = copy.deepcopy(HEALTHY)
        entry["gdef"]["output"] = False
        stage, _ = status_for(entry)
        self.assertIn("lost the donor's GDEF", stage["failures"][0])

    def test_kerning_frozen_at_the_default_weight_fails(self):
        entry = copy.deepcopy(HEALTHY)
        entry["layout"]["mode"] = "static"
        stage, _ = status_for(entry)
        self.assertIn("frozen at the default weight", stage["failures"][0])

    def test_static_kerning_is_fine_when_only_one_donor_kerns(self):
        entry = copy.deepcopy(HEALTHY)
        entry["layout"]["mode"] = "static"
        entry["kern"]["donors_with_kern"] = 1
        stage, _ = status_for(entry)
        self.assertEqual(stage["status"], "pass")

    def test_no_layout_at_all_fails(self):
        entry = copy.deepcopy(HEALTHY)
        entry["layout"] = {"mode": "none", "note": "donor has no layout tables", "tables": []}
        stage, _ = status_for(entry)
        self.assertIn("has no OpenType layout", stage["failures"][0])

    def test_missing_hinting_tables_fail(self):
        entry = copy.deepcopy(HEALTHY)
        entry["hinting"] = {"gasp": False, "mode": "smooth", "prep": False}
        stage, _ = status_for(entry)
        self.assertIn("missing gasp, prep", stage["failures"][0])

    def test_hinting_is_not_required_when_it_is_turned_off(self):
        entry = copy.deepcopy(HEALTHY)
        entry["hinting"] = {"gasp": False, "mode": "none", "prep": False}
        stage, _ = status_for(entry)
        self.assertEqual(stage["status"], "pass")


if __name__ == "__main__":
    unittest.main()
