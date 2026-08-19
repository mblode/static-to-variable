"""Release metadata tests."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

PACKAGE_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PACKAGE_SRC))

from fontTools.ttLib import TTFont  # noqa: E402
from fontTools.ttLib.tables._f_v_a_r import NamedInstance  # noqa: E402

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
    def test_default_instance_postscript_name_matches_name_id_6(self):
        font = TTFont(FIXTURE)
        defaults = {axis.axisTag: axis.defaultValue for axis in font["fvar"].axes}
        instance = NamedInstance()
        instance.coordinates = defaults
        instance.subfamilyNameID = font["name"].addName("Regular", platforms=[WIN, MAC])
        instance.postscriptNameID = font["name"].addName("Temporary-Regular", platforms=[WIN, MAC])
        font["fvar"].instances.append(instance)
        for platform in (WIN, MAC):
            font["name"].setName("STVMinimal", 6, *platform)
        fix_instances(font, load_config(MINIMAL_CONFIG), italic=False)
        default_instance = next(
            instance for instance in font["fvar"].instances if instance.coordinates == defaults
        )

        self.assertEqual(
            font["name"].getDebugName(default_instance.postscriptNameID),
            "STVMinimal",
        )

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

    def test_elidable_axis_values_omitted_from_instance_names(self):
        """Test that elidable axis values are omitted when at their default,
        independent of other axes (per OpenType STAT spec)."""
        from fontTools.ttLib.tables import otTables

        font = TTFont(FIXTURE)
        # Modify STAT table to mark axis values as elidable.
        # The fixture has a single axis; add elidable flags to test elision.
        stat = font["STAT"].table

        # Mark existing axis values as elidable (they represent defaults)
        if stat.AxisValueArray:
            for av in stat.AxisValueArray.AxisValue:
                # Check if this is a default value by checking ValueNameID or axis name
                av.Flags = 0x0002  # ELIDABLE flag

        # Now we'll test with a synthetic two-axis setup by modifying fvar
        # Set up two axes: wght (400-700, default 400) and opsz (12-28, default 16)
        fvar = font["fvar"]

        # Replace axes with synthetic ones
        axis_wght = fvar.axes[0]
        axis_wght.axisTag = "wght"
        axis_wght.minValue = 400
        axis_wght.defaultValue = 400
        axis_wght.maxValue = 700
        axis_wght.axisNameID = 256

        # Create a new axis for opsz
        axis_opsz = type(axis_wght)()
        axis_opsz.axisTag = "opsz"
        axis_opsz.minValue = 12
        axis_opsz.defaultValue = 16
        axis_opsz.maxValue = 28
        axis_opsz.axisNameID = 257
        axis_opsz.flags = 0

        fvar.axes.append(axis_opsz)

        # Update STAT with the two axes
        stat.DesignAxisRecord.Axis = []
        for i, axis in enumerate(fvar.axes):
            ax = otTables.AxisRecord()
            ax.AxisTag = axis.axisTag
            ax.Sort = i
            ax.AxisNameID = axis.axisNameID
            stat.DesignAxisRecord.Axis.append(ax)

        # Create synthetic AxisValue records for the second axis
        stat.AxisValueArray.AxisValue = []

        # wght 400 (default, elidable)
        av_wght_400 = otTables.AxisValue()
        av_wght_400.Format = 3
        av_wght_400.Flags = 0x0002  # ELIDABLE
        av_wght_400.ValueNameID = font["name"].addName("Regular", platforms=[WIN, MAC])
        av_wght_400.AxisIndex = 0
        av_wght_400.Value = 400
        stat.AxisValueArray.AxisValue.append(av_wght_400)

        # opsz 16 (default, elidable)
        av_opsz_16 = otTables.AxisValue()
        av_opsz_16.Format = 3
        av_opsz_16.Flags = 0x0002  # ELIDABLE
        av_opsz_16.ValueNameID = font["name"].addName("UI", platforms=[WIN, MAC])
        av_opsz_16.AxisIndex = 1
        av_opsz_16.Value = 16
        stat.AxisValueArray.AxisValue.append(av_opsz_16)

        # opsz 12 (not default, not elidable)
        av_opsz_12 = otTables.AxisValue()
        av_opsz_12.Format = 3
        av_opsz_12.Flags = 0
        av_opsz_12.ValueNameID = font["name"].addName("Text", platforms=[WIN, MAC])
        av_opsz_12.AxisIndex = 1
        av_opsz_12.Value = 12
        stat.AxisValueArray.AxisValue.append(av_opsz_12)

        # opsz 28 (not default, not elidable)
        av_opsz_28 = otTables.AxisValue()
        av_opsz_28.Format = 3
        av_opsz_28.Flags = 0
        av_opsz_28.ValueNameID = font["name"].addName("Display", platforms=[WIN, MAC])
        av_opsz_28.AxisIndex = 1
        av_opsz_28.Value = 28
        stat.AxisValueArray.AxisValue.append(av_opsz_28)

        # wght 700 (not default, not elidable)
        av_wght_700 = otTables.AxisValue()
        av_wght_700.Format = 3
        av_wght_700.Flags = 0
        av_wght_700.ValueNameID = font["name"].addName("Bold", platforms=[WIN, MAC])
        av_wght_700.AxisIndex = 0
        av_wght_700.Value = 700
        stat.AxisValueArray.AxisValue.append(av_wght_700)

        # Clear existing instances and add test instances
        font["fvar"].instances = []

        # Test case 1: both at default (both elidable) -> fallback "Italic"
        inst1 = NamedInstance()
        inst1.coordinates = {"wght": 400, "opsz": 16}
        inst1.subfamilyNameID = font["name"].addName("Italic", platforms=[WIN, MAC])
        inst1.postscriptNameID = font["name"].addName("STVMinimal-Italic", platforms=[WIN, MAC])
        font["fvar"].instances.append(inst1)

        # Test case 2: wght at default (elidable), opsz not at default -> "Text Italic"
        inst2 = NamedInstance()
        inst2.coordinates = {"wght": 400, "opsz": 12}
        inst2.subfamilyNameID = font["name"].addName("Text Italic", platforms=[WIN, MAC])
        inst2.postscriptNameID = font["name"].addName("STVMinimal-TextItalic", platforms=[WIN, MAC])
        font["fvar"].instances.append(inst2)

        # Test case 3: wght at default (elidable), opsz far from default -> "Display Italic"
        inst3 = NamedInstance()
        inst3.coordinates = {"wght": 400, "opsz": 28}
        inst3.subfamilyNameID = font["name"].addName("Display Italic", platforms=[WIN, MAC])
        inst3.postscriptNameID = font["name"].addName(
            "STVMinimal-DisplayItalic", platforms=[WIN, MAC]
        )
        font["fvar"].instances.append(inst3)

        # Test case 4: wght not at default, opsz at default (elidable) -> "Bold Italic"
        inst4 = NamedInstance()
        inst4.coordinates = {"wght": 700, "opsz": 16}
        inst4.subfamilyNameID = font["name"].addName("Bold Italic", platforms=[WIN, MAC])
        inst4.postscriptNameID = font["name"].addName("STVMinimal-BoldItalic", platforms=[WIN, MAC])
        font["fvar"].instances.append(inst4)

        # Test case 5: neither at default -> "Bold Text Italic"
        inst5 = NamedInstance()
        inst5.coordinates = {"wght": 700, "opsz": 12}
        inst5.subfamilyNameID = font["name"].addName("Bold Text Italic", platforms=[WIN, MAC])
        inst5.postscriptNameID = font["name"].addName(
            "STVMinimal-BoldTextItalic", platforms=[WIN, MAC]
        )
        font["fvar"].instances.append(inst5)

        # Create synthetic config with two axes (using a mock since ProjectConfig is frozen)
        mock_config = SimpleNamespace(
            family=SimpleNamespace(name="STVMinimal"),
            axes=(
                SimpleNamespace(
                    tag="wght",
                    name="Weight",
                    minimum=400,
                    default=400,
                    maximum=700,
                    named_instances={400: "Regular", 700: "Bold"},
                ),
                SimpleNamespace(
                    tag="opsz",
                    name="Optical Size",
                    minimum=12,
                    default=16,
                    maximum=28,
                    named_instances={12: "Text", 16: "UI", 28: "Display"},
                ),
            ),
        )

        # Run the fix
        fix_instances(font, mock_config, italic=True)

        # Verify the results
        instances = font["fvar"].instances
        self.assertEqual(
            font["name"].getDebugName(instances[0].subfamilyNameID),
            "Italic",
            "Both elidable at default should use fallback",
        )
        self.assertEqual(
            font["name"].getDebugName(instances[0].postscriptNameID),
            "STVMinimal-Italic",
            "PostScript name should match subfamily for fallback",
        )

        self.assertEqual(
            font["name"].getDebugName(instances[1].subfamilyNameID),
            "Text Italic",
            "wght elidable at default, opsz not -> omit wght, include opsz",
        )
        self.assertEqual(
            font["name"].getDebugName(instances[1].postscriptNameID),
            "STVMinimal-TextItalic",
            "PostScript name should match subfamily",
        )

        self.assertEqual(
            font["name"].getDebugName(instances[2].subfamilyNameID),
            "Display Italic",
            "wght elidable at default, opsz not -> omit wght, include opsz",
        )
        self.assertEqual(
            font["name"].getDebugName(instances[2].postscriptNameID),
            "STVMinimal-DisplayItalic",
            "PostScript name should match subfamily",
        )

        self.assertEqual(
            font["name"].getDebugName(instances[3].subfamilyNameID),
            "Bold Italic",
            "wght not at default, opsz elidable at default -> include wght, omit opsz",
        )
        self.assertEqual(
            font["name"].getDebugName(instances[3].postscriptNameID),
            "STVMinimal-BoldItalic",
            "PostScript name should match subfamily",
        )

        self.assertEqual(
            font["name"].getDebugName(instances[4].subfamilyNameID),
            "Bold Text Italic",
            "Neither at default -> include both",
        )
        self.assertEqual(
            font["name"].getDebugName(instances[4].postscriptNameID),
            "STVMinimal-BoldTextItalic",
            "PostScript name should match subfamily",
        )


if __name__ == "__main__":
    unittest.main()
