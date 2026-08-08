"""Tests for the rasterizer baseline applied to the built variable font."""

import sys
import unittest
from io import BytesIO
from pathlib import Path

PACKAGE_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PACKAGE_SRC))

from fontTools.ttLib import TTFont, newTable  # noqa: E402
from fontTools.ttLib.tables import ttProgram  # noqa: E402

from variable_gen.hinting import apply_hinting  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample-vf.ttf"


def unhinted():
    """The fixture as fontmake would leave it: no rasterizer tables at all.

    (The committed fixture is derived from Inter and inherits its gasp/prep.)
    """
    vf = TTFont(str(FIXTURE))
    for tag in ("gasp", "prep", "fpgm", "cvt "):
        if tag in vf:
            del vf[tag]
    return vf


class ApplyHintingTests(unittest.TestCase):
    def test_smooth_adds_gasp_and_dropout_control(self):
        vf = unhinted()

        report = apply_hinting(vf, "smooth")

        self.assertEqual(report.mode, "smooth")
        self.assertTrue(report.gasp)
        self.assertTrue(report.prep)
        # Grayscale + symmetric smoothing at every size.
        self.assertEqual(vf["gasp"].gaspRange, {0xFFFF: 0x000F})
        assembly = " ".join(vf["prep"].program.getAssembly())
        self.assertIn("SCANCTRL", assembly)
        self.assertIn("SCANTYPE", assembly)
        vf.save(BytesIO())

    def test_the_result_round_trips_through_a_save(self):
        vf = unhinted()
        apply_hinting(vf, "smooth")
        buf = BytesIO()
        vf.save(buf)
        buf.seek(0)
        reloaded = TTFont(buf)
        self.assertEqual(reloaded["gasp"].gaspRange, {0xFFFF: 0x000F})
        self.assertGreaterEqual(reloaded["maxp"].maxZones, 1)
        self.assertGreaterEqual(reloaded["maxp"].maxStackElements, 2)

    def test_none_leaves_the_font_alone(self):
        vf = unhinted()
        report = apply_hinting(vf, "none")
        self.assertEqual(report.summary(), "hinting: none")
        self.assertNotIn("gasp", vf)
        self.assertNotIn("prep", vf)

    def test_it_never_overwrites_real_hinting(self):
        vf = unhinted()
        prep = newTable("prep")
        prep.program = ttProgram.Program()
        prep.program.fromAssembly(["PUSHB[]", "1", "POP[]"])
        vf["prep"] = prep

        report = apply_hinting(vf, "smooth")

        self.assertIn("kept the existing prep", report.note)
        self.assertIn("POP", " ".join(vf["prep"].program.getAssembly()))

    def test_applying_twice_changes_nothing(self):
        vf = unhinted()
        apply_hinting(vf, "smooth")
        first = vf["prep"].program.getAssembly()
        apply_hinting(vf, "smooth")
        self.assertEqual(vf["prep"].program.getAssembly(), first)
        self.assertEqual(vf["gasp"].gaspRange, {0xFFFF: 0x000F})

    def test_an_unknown_mode_is_an_error(self):
        with self.assertRaises(ValueError):
            apply_hinting(unhinted(), "aggressive")


if __name__ == "__main__":
    unittest.main()
