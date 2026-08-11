"""Release metadata tests."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

PACKAGE_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PACKAGE_SRC))

from fontTools.ttLib import TTFont  # noqa: E402

from variable_gen.config import load_config  # noqa: E402
from variable_gen.release import MAC, WIN, fix_instances, fix_vertical_metrics  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample-vf.ttf"
MINIMAL_CONFIG = REPO_ROOT / "examples" / "minimal" / "stv.config.json"


class ReleaseVerticalMetricsTests(unittest.TestCase):
    def test_typo_line_box_and_real_ink_bounds_have_distinct_jobs(self):
        os2 = SimpleNamespace(
            fsSelection=0x040,
            sTypoAscender=986,
            sTypoDescender=-277,
            sTypoLineGap=0,
            usWinAscent=986,
            usWinDescent=277,
        )
        hhea = SimpleNamespace(ascent=900, descent=-200, lineGap=90)
        head = SimpleNamespace(yMax=1021.2, yMin=-281.1)

        fix_vertical_metrics({"OS/2": os2, "hhea": hhea, "head": head})

        self.assertEqual((hhea.ascent, hhea.descent, hhea.lineGap), (986, -277, 0))
        self.assertEqual((os2.usWinAscent, os2.usWinDescent), (1022, 282))
        self.assertTrue(os2.fsSelection & 0x080)
        self.assertTrue(os2.fsSelection & 0x040)

    def test_typo_metrics_set_the_minimum_clipping_envelope(self):
        os2 = SimpleNamespace(
            fsSelection=0,
            sTypoAscender=986,
            sTypoDescender=-277,
            sTypoLineGap=0,
            usWinAscent=0,
            usWinDescent=0,
        )
        hhea = SimpleNamespace(ascent=0, descent=0, lineGap=0)
        head = SimpleNamespace(yMax=900, yMin=-200)

        fix_vertical_metrics({"OS/2": os2, "hhea": hhea, "head": head})

        self.assertEqual((os2.usWinAscent, os2.usWinDescent), (986, 277))

    def test_explicit_family_envelope_can_cover_non_default_instances(self):
        os2 = SimpleNamespace(
            fsSelection=0,
            sTypoAscender=986,
            sTypoDescender=-277,
            sTypoLineGap=0,
            usWinAscent=0,
            usWinDescent=0,
        )
        hhea = SimpleNamespace(ascent=0, descent=0, lineGap=0)
        head = SimpleNamespace(yMax=1021, yMin=-277)

        fix_vertical_metrics(
            {"OS/2": os2, "hhea": hhea, "head": head},
            win_ascent=1068,
            win_descent=281,
        )

        self.assertEqual((os2.usWinAscent, os2.usWinDescent), (1068, 281))


class ReleaseVariationNameTests(unittest.TestCase):
    def test_fvar_and_stat_names_exist_on_every_declared_platform(self):
        font = TTFont(FIXTURE)
        fix_instances(font, load_config(MINIMAL_CONFIG), italic=False)
        name = font["name"]
        used = {axis.axisNameID for axis in font["fvar"].axes}
        stat = font["STAT"].table
        used.update(axis.AxisNameID for axis in stat.DesignAxisRecord.Axis)
        used.update(value.ValueNameID for value in stat.AxisValueArray.AxisValue)

        for name_id in used:
            self.assertIsNotNone(name.getName(name_id, *WIN), name_id)
            self.assertIsNotNone(name.getName(name_id, *MAC), name_id)


if __name__ == "__main__":
    unittest.main()
