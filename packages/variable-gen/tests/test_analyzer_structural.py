from __future__ import annotations

import sys
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PACKAGE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from variable_gen.analyze import (
    _winding,
    classify_issue,
    render_compatibility_markdown,
)


class StructuralCheckTests(unittest.TestCase):
    def test_winding_direction(self) -> None:
        ccw = [(0, 0), (10, 0), (10, 10), (0, 10)]
        self.assertEqual(_winding(ccw), 1)
        self.assertEqual(_winding(list(reversed(ccw))), -1)
        self.assertEqual(_winding([(0, 0), (1, 1)]), 0)  # degenerate

    def test_custom_issue_classification(self) -> None:
        self.assertEqual(classify_issue("segment_type_mismatch"), "P0")
        self.assertEqual(classify_issue("winding_mismatch"), "P1")
        self.assertEqual(classify_issue("advance_incompatible"), "P1")
        self.assertEqual(classify_issue("phantom_point_mismatch"), "P1")

    def test_markdown_renders_summary_and_tiers(self) -> None:
        report = {
            "stage": "raw",
            "hard_gates": {"status": "fail", "blocking_reasons": [
                {"field": "interpolatable_error_count", "value": 3, "threshold": 0},
            ]},
            "summary": {
                "family_count": 1, "problem_glyph_count": 2, "issue_count": 3,
                "severity_counts": {"P0": 1, "P1": 1},
                "issue_type_counts": {"segment_type_mismatch": 1, "winding_mismatch": 2},
            },
            "families": {
                "roman": {
                    "name": "Circular", "style": "roman",
                    "summary": {
                        "glyph_count": 100, "problem_glyph_count": 2,
                        "severity_counts": {"P0": 1, "P1": 1},
                        "issue_type_counts": {"segment_type_mismatch": 1, "winding_mismatch": 2},
                    },
                    "glyphs": {
                        "a": {"severity": "P0", "issue_type_counts": {"segment_type_mismatch": 1}},
                        "b": {"severity": "P1", "issue_type_counts": {"winding_mismatch": 2}},
                    },
                },
            },
        }
        md = render_compatibility_markdown(report)
        self.assertIn("# Compatibility report", md)
        self.assertIn("gate: `fail`", md)
        self.assertIn("### P0 (1 glyphs)", md)
        self.assertIn("`a` — segment_type_mismatch=1", md)
        self.assertIn("### P1 (1 glyphs)", md)


if __name__ == "__main__":
    unittest.main()
