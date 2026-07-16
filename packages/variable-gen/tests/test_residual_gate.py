from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PACKAGE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from variable_gen.pipeline import _residual_stage


REPORT_REL = "packages/variable-gen/reports/repair/blocker-residual-validation"


def _write_verdict(repo_root: Path, payload: dict) -> None:
    out = repo_root / f"{REPORT_REL}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload))


class ResidualGateTests(unittest.TestCase):
    """The promotion gate must mirror the validator's verdict exactly.

    Regression guard for the false-green bug: the old aggregator re-derived
    pass/fail by parsing only three markdown counters
    (sourceStructureFailures/areaDriftFailures/minSegmentFailures) and was blind
    to interpolatable and disallowed-frozen failures, so it could report `pass`
    while the validator exited non-zero.
    """

    def test_interpolatable_only_failure_is_not_green(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            _write_verdict(
                repo_root,
                {
                    "status": "fail",
                    "failure_count": 1,
                    "failures": ["italic:perthousand: interpolatable=1"],
                    "counts_by_family": {
                        "italic": {
                            "area_drift_failures": 0,
                            "min_segment_failures": 0,
                            "interpolatable": 1,
                        }
                    },
                },
            )
            stage = _residual_stage(repo_root)
            self.assertEqual(stage.status, "fail")
            self.assertIn("italic:perthousand: interpolatable=1", stage.failures)

    def test_clean_verdict_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            _write_verdict(
                repo_root,
                {
                    "status": "pass",
                    "failure_count": 0,
                    "failures": [],
                    "counts_by_family": {"roman": {}, "italic": {}},
                },
            )
            stage = _residual_stage(repo_root)
            self.assertEqual(stage.status, "pass")
            self.assertEqual(stage.failures, [])

    def test_missing_artifact_is_missing_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stage = _residual_stage(Path(tmp))
            self.assertNotEqual(stage.status, "pass")


if __name__ == "__main__":
    unittest.main()
