"""Tests for the variable -> static split (the reverse of the build pipeline).

Runs against a tiny committed variable-font fixture (tests/fixtures/sample-vf.ttf,
~6K, derived from the OFL Inter donors in examples/minimal — see fixtures/README).
"""

import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PACKAGE_SRC))

from fontTools.ttLib import TTFont  # noqa: E402

from variable_gen.split import SplitError, split_variable_font  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample-vf.ttf"
STATIC_DONOR = REPO_ROOT / "examples/minimal/donors/Inter-Regular.ttf"


class SplitVariableFontTests(unittest.TestCase):
    def _run(self, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        results = split_variable_font(FIXTURE, out, **kwargs)
        return out, results

    def test_default_step_covers_the_axis(self):
        # Fixture axis is wght 100..900; default step 100 -> 9 weights.
        out, results = self._run()
        self.assertEqual([r["weight"] for r in results], list(range(100, 901, 100)))
        self.assertEqual(len(list(out.glob("*.ttf"))), 9)

    def test_each_output_is_static_with_correct_weight(self):
        _, results = self._run()
        for entry in results:
            ttf = next(f for f in entry["files"] if f.endswith(".ttf"))
            font = TTFont(ttf)
            self.assertNotIn("fvar", font, f"{ttf} still has an fvar axis")
            self.assertEqual(font["OS/2"].usWeightClass, entry["weight"])

    def test_names_are_distinct_per_weight(self):
        # The whole point: without renaming, every instance would install as the
        # same family/subfamily and overwrite the others.
        _, results = self._run()
        identities = set()
        for entry in results:
            ttf = next(f for f in entry["files"] if f.endswith(".ttf"))
            name = TTFont(ttf)["name"]
            identities.add((name.getDebugName(1), name.getDebugName(17)))
        self.assertEqual(len(identities), len(results))

    def test_woff2_written_alongside_ttf(self):
        _, results = self._run()
        for entry in results:
            suffixes = {Path(f).suffix for f in entry["files"]}
            self.assertEqual(suffixes, {".ttf", ".woff2"})

    def test_step_snaps_to_the_axis_maximum(self):
        # range(100, 901, 200) is 100,300,500,700,900 — max already included.
        _, results = self._run(step=200)
        self.assertEqual([r["weight"] for r in results], [100, 300, 500, 700, 900])

    def test_non_variable_font_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SplitError):
                split_variable_font(STATIC_DONOR, Path(tmp))


if __name__ == "__main__":
    unittest.main()
