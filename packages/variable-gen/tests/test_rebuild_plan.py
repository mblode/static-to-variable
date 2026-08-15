"""Multi-axis rebuild plan: reconstruct stays 1D per optical-size row."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

PACKAGE_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PACKAGE_SRC))

from variable_gen.config import Donor, Master, Style  # noqa: E402
from variable_gen.rebuild import _master_axis_values, _plan_groups, _style_plan  # noqa: E402


def _style() -> Style:
    donors = (
        Donor("t100", "Text 100", Path("t100.otf"), "t100.otf", {"wght": 100, "opsz": 14}),
        Donor("t400", "Text 400", Path("t400.otf"), "t400.otf", {"wght": 400, "opsz": 14}),
        Donor("t950", "Text 950", Path("t950.otf"), "t950.otf", {"wght": 950, "opsz": 14}),
        Donor("d100", "Display 100", Path("d100.otf"), "d100.otf", {"wght": 100, "opsz": 28}),
        Donor("d400", "Display 400", Path("d400.otf"), "d400.otf", {"wght": 400, "opsz": 28}),
        Donor("d950", "Display 950", Path("d950.otf"), "d950.otf", {"wght": 950, "opsz": 28}),
    )
    masters = (
        Master("Text 100", "t100", {"wght": 100, "opsz": 14}),
        Master("Text 400", "t400", {"wght": 400, "opsz": 14}, default=True),
        Master("Text 950", "t950", {"wght": 950, "opsz": 14}),
        Master("Display 100", "d100", {"wght": 100, "opsz": 28}),
        Master("Display 400", "d400", {"wght": 400, "opsz": 28}),
        Master("Display 950", "d950", {"wght": 950, "opsz": 28}),
    )
    return Style(
        key="roman",
        italic=False,
        donors=donors,
        source=Path("roman.glyphs"),
        config_source="roman.glyphs",
        masters=masters,
        output=Path("out.ttf"),
        config_output="out.ttf",
    )


class RebuildPlanTests(unittest.TestCase):
    def test_single_axis_keys_are_weight(self):
        style = _style()
        style = Style(
            key=style.key,
            italic=False,
            donors=style.donors[:3],
            source=style.source,
            config_source=style.config_source,
            masters=tuple(
                Master(m.name, m.donor_id, {"wght": m.location["wght"]}, m.default)
                for m in style.masters[:3]
            ),
            output=style.output,
            config_output=style.config_output,
        )
        config = SimpleNamespace(
            axes=(SimpleNamespace(tag="wght", name="Weight"),),
        )
        plan = _style_plan(config, style)
        self.assertEqual([item[2] for item in plan], [100, 400, 950])
        self.assertEqual(len(_plan_groups(plan)), 1)

    def test_opsz_rows_shift_by_10000(self):
        style = _style()
        config = SimpleNamespace(
            axes=(
                SimpleNamespace(tag="wght", name="Weight"),
                SimpleNamespace(tag="opsz", name="Optical size"),
            ),
        )
        plan = _style_plan(config, style)
        self.assertEqual(
            [item[2] for item in plan],
            [100, 400, 950, 10100, 10400, 10950],
        )
        groups = _plan_groups(plan)
        self.assertEqual(len(groups), 2)
        self.assertEqual([item[0] for item in groups[0]], ["Text 100", "Text 400", "Text 950"])
        self.assertEqual(
            [item[0] for item in groups[1]],
            ["Display 100", "Display 400", "Display 950"],
        )
        self.assertEqual(
            _master_axis_values(config, style, "Display 400"),
            [400, 28],
        )


if __name__ == "__main__":
    unittest.main()
