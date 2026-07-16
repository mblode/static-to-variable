"""The residual validator must consume artifacts the current pipeline produces.

The legacy repair runner used to write the validator's inputs; after the
consolidation they come from the audit reports plus the rebuild's per-glyph
outcome map. These tests build synthetic versions of exactly those artifacts,
so a rename or shape drift on either side fails loudly here instead of on a
clean checkout.
"""

import json
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import validate_residual_glyphs as validator  # noqa: E402


def write_audit_reports(report_dir: Path, family: str, *, interpolatable=None) -> None:
    family_dir = report_dir / family
    family_dir.mkdir(parents=True, exist_ok=True)
    (family_dir / f"{family}-designspace-interpolatable-all.json").write_text(
        json.dumps(interpolatable or {})
    )
    (family_dir / f"{family}-instance-risk-all.json").write_text(
        json.dumps({"weights": {"250": {"risky_glyphs": {"at": {"min_segment_length": 1.2}}}}})
    )
    (family_dir / f"{family}-master-validation-all.json").write_text(
        json.dumps({"weights": {"100": {"worst_area_diffs_pct": {"dollar": 30.0}}}})
    )


MANIFEST = {
    "roman": {
        "glyphs": {
            "dollar": {
                "strategy": "manual_review",
                "repair_bucket": "reconstruction_required",
                "priority": "blocker",
                "allow_frozen": True,
                "allow_frozen_reason": "design decision: constant currency bar",
            },
            "at": {"strategy": "donor_copy", "priority": "blocker"},
            "ghost": {"strategy": "donor_copy", "priority": "blocker"},
        }
    }
}

OUTCOMES = {"dollar": "ai_pending", "at": "reconstructed"}

SOLVER = {"roman/dollar": {"requiresReconstruction": True}}


class BuildFamilyReviewTests(unittest.TestCase):
    def run_review(self, tmp: Path, *, interpolatable=None):
        write_audit_reports(tmp, "roman", interpolatable=interpolatable)
        return validator.build_family_review(
            family_key="roman",
            manifest=MANIFEST,
            report_dir=tmp,
            glyph_outcomes=OUTCOMES,
            max_area_drift=25.0,
            min_segment_threshold=0.0,
            min_priority=None,
            repair_buckets=None,
            solver_results=SOLVER,
        )

    def test_reads_current_audit_artifact_names(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            lines, counts, failures = self.run_review(Path(tmp))
        self.assertEqual(counts["tracked"], 2)
        self.assertEqual(counts["reconstruction_required"], 1)
        self.assertEqual(counts["frozen"], 1)

    def test_glyph_absent_from_reconstruction_report_fails(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            _, _, failures = self.run_review(Path(tmp))
        self.assertIn("roman:ghost: missing from reconstruction report", failures)

    def test_interpolatable_issue_fails_non_reconstruction_glyph(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            _, _, failures = self.run_review(
                Path(tmp), interpolatable={"at": [{"type": "node_count"}]}
            )
        self.assertIn("roman:at: interpolatable=1", failures)

    def test_allowlisted_frozen_glyph_passes_area_drift(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            _, _, failures = self.run_review(Path(tmp))
        # dollar is frozen (ai_pending) but allowlisted with a reason, and its
        # 30% area drift is exempt because reconstruction is required + solver
        # agrees — no dollar failures expected.
        self.assertFalse([f for f in failures if f.startswith("roman:dollar")])

    def test_missing_audit_reports_name_the_command_to_run(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as ctx:
                validator.build_family_review(
                    family_key="roman",
                    manifest=MANIFEST,
                    report_dir=Path(tmp),
                    glyph_outcomes=OUTCOMES,
                    max_area_drift=25.0,
                    min_segment_threshold=0.0,
                    min_priority=None,
                    repair_buckets=None,
                    solver_results={},
                )
        message = str(ctx.exception)
        self.assertIn("missing required report", message)
        self.assertIn("run audit", message)


class GlyphOutcomeLoadingTests(unittest.TestCase):
    def test_missing_report_names_the_rebuild_command(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as ctx:
                validator.load_glyph_outcomes(Path(tmp) / "nope.json", "roman")
        self.assertIn("rebuild", str(ctx.exception))

    def test_report_without_outcomes_is_rejected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reconstruction-report.json"
            path.write_text(json.dumps({"roman": {"donor": 5}}))
            with self.assertRaises(SystemExit) as ctx:
                validator.load_glyph_outcomes(path, "roman")
        self.assertIn("rebuild", str(ctx.exception))

    def test_outcomes_extracted_per_family(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reconstruction-report.json"
            path.write_text(json.dumps({"roman": {"glyphs": {"at": "donor", "dollar": "frozen"}}}))
            outcomes = validator.load_glyph_outcomes(path, "roman")
        self.assertEqual(outcomes, {"at": "donor", "dollar": "frozen"})


if __name__ == "__main__":
    unittest.main()
