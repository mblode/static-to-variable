"""A single-style rebuild must not erase other styles from the report —
the repair_build promotion gate reads every style from reconstruction-report.json."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PACKAGE_SRC))

from variable_gen.cli import _merge_style_report  # noqa: E402


class MergeStyleReportTests(unittest.TestCase):
    def test_single_style_update_preserves_other_styles(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reconstruction-report.json"
            path.write_text(json.dumps({"italic": {"donor": 7, "glyphs": {"a": "donor"}}}))
            merged = _merge_style_report(path, {"roman": {"donor": 3}}, ["roman", "italic"])
        self.assertEqual(sorted(merged), ["italic", "roman"])
        self.assertEqual(merged["italic"]["donor"], 7)
        # Configured style order wins over insertion order.
        self.assertEqual(list(merged), ["roman", "italic"])

    def test_missing_or_corrupt_existing_report_is_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "absent.json"
            merged = _merge_style_report(missing, {"roman": {"donor": 1}}, ["roman"])
            self.assertEqual(merged, {"roman": {"donor": 1}})

            corrupt = Path(tmp) / "corrupt.json"
            corrupt.write_text("{ not json")
            merged = _merge_style_report(corrupt, {"roman": {"donor": 2}}, ["roman"])
            self.assertEqual(merged, {"roman": {"donor": 2}})

    def test_updates_overwrite_the_same_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reconstruction-report.json"
            path.write_text(json.dumps({"roman": {"donor": 1}}))
            merged = _merge_style_report(path, {"roman": {"donor": 9}}, ["roman"])
        self.assertEqual(merged["roman"]["donor"], 9)


if __name__ == "__main__":
    unittest.main()
