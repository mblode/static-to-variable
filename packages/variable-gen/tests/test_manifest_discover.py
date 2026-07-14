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

from variable_gen.analyze import classify_issue, glyph_severity
from variable_gen.discover import build_inventory_report, write_inventory_report
from variable_gen.manifest import ManifestError, load_manifest
from variable_gen.pipeline import build_pipeline_status


MANIFEST_PATH = PACKAGE_ROOT / "manifests" / "circular-sources.v2.json"


class ManifestDiscoveryTests(unittest.TestCase):
    def test_loads_circular_manifest(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)

        self.assertEqual(manifest.id, "circular-static-donors")
        self.assertEqual([axis.tag for axis in manifest.axes], ["wght"])
        self.assertEqual(manifest.axes[0].minimum, 100.0)
        self.assertEqual(
            manifest.axes[0].donor_values,
            (250.0, 300.0, 400.0, 450.0, 500.0, 700.0, 900.0, 950.0),
        )
        self.assertEqual(manifest.axes[0].output_values, (100.0, 400.0, 950.0))
        self.assertEqual(sorted(manifest.families), ["italic", "roman"])
        self.assertEqual(len(manifest.families["roman"].donors), 8)
        self.assertEqual(len(manifest.families["italic"].donors), 8)
        self.assertEqual(
            manifest.families["roman"].generated_sources[0].role,
            "generated_repair_target",
        )

    def test_inventory_report_is_deterministic_and_read_only(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)
        report = build_inventory_report(manifest)

        self.assertEqual(report["schema"], "static_to_variable.inventory.v1")
        self.assertEqual(report["summary"]["family_count"], 2)
        self.assertEqual(report["summary"]["donor_count"], 16)
        self.assertEqual(report["summary"]["missing_donor_count"], 0)
        self.assertIn("roman", report["families"])
        self.assertIn("italic", report["families"])
        self.assertEqual(
            report["families"]["roman"]["donors"][0]["location"]["wght"],
            250.0,
        )
        self.assertIn("sha256", report["families"]["roman"]["donors"][0])

        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "inventory.json"
            written_path = write_inventory_report(report, output)
            first = written_path.read_text()
            write_inventory_report(report, output)
            self.assertEqual(first, written_path.read_text())

    def test_rejects_string_or_boolean_axis_locations(self) -> None:
        manifest_data = json.loads(MANIFEST_PATH.read_text())
        manifest_data["families"]["roman"]["donors"][0]["location"]["wght"] = "250"

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "manifest.json"
            path.write_text(json.dumps(manifest_data))
            with self.assertRaises(ManifestError):
                load_manifest(path)

        manifest_data = json.loads(MANIFEST_PATH.read_text())
        manifest_data["axes"][0]["minimum"] = True

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "manifest.json"
            path.write_text(json.dumps(manifest_data))
            with self.assertRaises(ManifestError):
                load_manifest(path)

    def test_issue_classification(self) -> None:
        self.assertEqual(classify_issue("node_count"), "P0")
        self.assertEqual(classify_issue("wrong_start_point"), "P1")
        self.assertEqual(classify_issue("unknown_future_issue"), "P2")
        self.assertEqual(
            glyph_severity(
                [
                    {"type": "wrong_start_point"},
                    {"type": "node_incompatibility"},
                ]
            ),
            "P0",
        )

    def test_pipeline_status_shape(self) -> None:
        report = build_pipeline_status(PACKAGE_ROOT.parents[1])

        self.assertEqual(
            report["schema"],
            "static_to_variable.pipeline_status.v1",
        )
        self.assertIn(report["verdict"], {"pass", "fail"})
        self.assertGreaterEqual(report["summary"]["stage_count"], 6)
        self.assertTrue(any(stage["id"] == "raw_compatibility" for stage in report["stages"]))


if __name__ == "__main__":
    unittest.main()
