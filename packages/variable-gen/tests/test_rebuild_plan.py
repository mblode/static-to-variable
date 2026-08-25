"""Multi-axis rebuild plan: reconstruct stays 1D per optical-size row."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PACKAGE_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PACKAGE_SRC))

from variable_gen.common import PipelineError  # noqa: E402
from variable_gen.config import Donor, Master, Style  # noqa: E402
from variable_gen.rebuild import (  # noqa: E402
    AxisLocation,
    PlanMaster,
    _check_row_signatures,
    _master_axis_values,
    _plan_groups,
    _style_plan,
    reconstruct_plan,
)
from variable_gen.reconstruct_compatible import (  # noqa: E402
    _has_interpolated_self_intersection,
    _interp_ok,
    _interp_smooth,
    exact_node_union,
)
from variable_gen.reconstruction_cache import ReconstructionCacheStats  # noqa: E402


KAPPA = 0.5522847498307936


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


def _plan():
    config = SimpleNamespace(
        axes=(
            SimpleNamespace(tag="wght", name="Weight"),
            SimpleNamespace(tag="opsz", name="Optical size"),
        ),
    )
    return _style_plan(config, _style())


def _rounded_box(*, split_curve: bool = False):
    size = 100.0
    handle = size * KAPPA * 0.5
    contour = [
        ("moveTo", [(0.0, 0.0)]),
        ("lineTo", [(size, 0.0)]),
    ]
    if split_curve:
        contour.extend(
            [
                (
                    "curveTo",
                    [
                        (size + handle / 2, 0.0),
                        (size + handle, handle / 2),
                        (size + handle, handle),
                    ],
                ),
                (
                    "curveTo",
                    [
                        (size + handle, handle * 1.5),
                        (size + handle / 2, size),
                        (size, size),
                    ],
                ),
            ]
        )
    else:
        contour.append(
            (
                "curveTo",
                [(size + handle, 0.0), (size + handle, size), (size, size)],
            )
        )
    contour.extend(
        [
            ("lineTo", [(0.0, size)]),
            ("lineTo", [(0.0, 0.0)]),
            ("closePath", []),
        ]
    )
    return [contour]


def _donor_grid(plan, glyphs):
    return {
        name: {master.name: (outline_by_master(master), 500.0) for master in plan}
        for name, outline_by_master in glyphs.items()
    }


def _kink_outline(*, vertical: bool):
    """Two smooth masters whose interpolated handles disagree at the origin."""
    first_handle = (0.0, 100.0) if vertical else (10.0, 0.0)
    last_handle = (0.0, -10.0) if vertical else (-100.0, 0.0)
    return [
        [
            ("moveTo", [(0.0, 0.0)]),
            ("curveTo", [first_handle, (200.0, 100.0), (200.0, 200.0)]),
            ("curveTo", [(100.0, 200.0), last_handle, (0.0, 0.0)]),
            ("closePath", []),
        ]
    ]


def _depth_kink_outline(*, vertical: bool):
    """Smooth cubic join whose interpolated midpoint exceeds the depth threshold.

    Unlike ``_kink_outline``, both masters stay under the angle-based
    ``_interp_smooth`` limit. The reconstruction gate must still reject it.
    """
    previous = (0.0, -110.0) if vertical else (-100.0, 0.0)
    nxt = (0.0, 100.0) if vertical else (110.0, 0.0)
    return [
        [
            ("moveTo", [(-100.0, -100.0)]),
            ("lineTo", [(-100.0, 0.0)]),
            ("curveTo", [(-80.0, 0.0), previous, (0.0, 0.0)]),
            ("curveTo", [nxt, (80.0, 0.0), (100.0, 0.0)]),
            ("lineTo", [(100.0, -100.0)]),
            ("closePath", []),
        ]
    ]


def _rectangle(x: float, y: float = 0.0):
    return [
        ("moveTo", [(x, y)]),
        ("lineTo", [(x + 20.0, y)]),
        ("lineTo", [(x + 20.0, y + 20.0)]),
        ("lineTo", [(x, y + 20.0)]),
        ("lineTo", [(x, y)]),
        ("closePath", []),
    ]


def _crossing_rectangles(*, moving_right: bool):
    moving = _rectangle(100.0 if moving_right else 0.0, 10.0)
    return [_rectangle(50.0), moving]


def _successful_row_fallback(jobs, _reference_pos, _workers, **_kwargs):
    return {
        name: (
            {position: _rounded_box() for position in outlines},
            {"stage": "donor", "note": "row-fallback"},
        )
        for name, outlines in jobs.items()
    }


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
        self.assertEqual(
            [item.location.as_dict() for item in plan],
            [
                {"wght": 100.0},
                {"wght": 400.0},
                {"wght": 950.0},
            ],
        )
        self.assertEqual(len(_plan_groups(plan)), 1)

    def test_opsz_rows_keep_structured_locations(self):
        style = _style()
        config = SimpleNamespace(
            axes=(
                SimpleNamespace(tag="wght", name="Weight"),
                SimpleNamespace(tag="opsz", name="Optical size"),
            ),
        )
        plan = _style_plan(config, style)
        self.assertEqual(
            [item.location.as_dict() for item in plan],
            [
                {"wght": 100.0, "opsz": 14.0},
                {"wght": 400.0, "opsz": 14.0},
                {"wght": 950.0, "opsz": 14.0},
                {"wght": 100.0, "opsz": 28.0},
                {"wght": 400.0, "opsz": 28.0},
                {"wght": 950.0, "opsz": 28.0},
            ],
        )
        groups = _plan_groups(plan)
        self.assertEqual(len(groups), 2)
        self.assertEqual(
            [item.name for item in groups[0].masters],
            ["Text 100", "Text 400", "Text 950"],
        )
        self.assertEqual(
            [item.name for item in groups[1].masters],
            ["Display 100", "Display 400", "Display 950"],
        )
        self.assertEqual(
            _master_axis_values(config, style, "Display 400"),
            [400, 28],
        )

    def test_incompatible_rows_fail_with_the_glyph_and_locations(self):
        style = _style()
        config = SimpleNamespace(
            axes=(
                SimpleNamespace(tag="wght", name="Weight"),
                SimpleNamespace(tag="opsz", name="Optical size"),
            ),
        )
        plan = _style_plan(config, style)
        rows = _plan_groups(plan)
        outlines = {}
        for master in rows[0].masters:
            outlines[master.location] = [[("moveTo", [(0, 0)]), ("closePath", [])]]
        for master in rows[1].masters:
            outlines[master.location] = [
                [
                    ("moveTo", [(0, 0)]),
                    ("lineTo", [(1, 1)]),
                    ("closePath", []),
                ]
            ]

        with self.assertRaisesRegex(PipelineError, r"zero: .*opsz=14.*opsz=28"):
            _check_row_signatures(
                "zero",
                outlines,
                rows,
                "wght",
                plan[1].location,
            )

    def test_full_grid_exact_union_wins_before_rows_are_reconstructed(self):
        plan = _plan()
        reference: AxisLocation = plan[1].location
        donors = _donor_grid(
            plan,
            {
                "round": lambda master: _rounded_box(
                    split_curve=master.name in {"Text 400", "Display 950"}
                )
            },
        )
        cache_stats = ReconstructionCacheStats()

        with mock.patch("variable_gen.rebuild.reconstruct_all") as reconstruct_rows:
            result = reconstruct_plan(
                donors,
                plan,
                "wght",
                reference,
                workers=1,
                cache_stats=cache_stats,
            )

        reconstruct_rows.assert_not_called()
        outlines, info = result["round"]
        self.assertEqual(list(outlines), [master.location for master in plan])
        self.assertEqual(info["stage"], "reconstructed")
        self.assertEqual(
            info["rows"],
            [
                {"stage": "reconstructed", "note": "exact-node-union"},
                {"stage": "reconstructed", "note": "exact-node-union"},
            ],
        )
        self.assertTrue(
            all(
                sum(operation == "curveTo" for operation, _points in outline[0]) == 2
                for outline in outlines.values()
            )
        )
        self.assertEqual(cache_stats, ReconstructionCacheStats(bypassed=1))

    def test_non_unionable_grid_keeps_row_fallback_behavior_and_metadata(self):
        plan = _plan()
        reference: AxisLocation = plan[1].location

        def implicit_close(_master):
            contour = _rounded_box()[0]
            return [[*contour[:-2], contour[-1]]]

        donors = _donor_grid(
            plan,
            {
                "fallback": lambda master: (
                    implicit_close(master)
                    if master.name in {"Text 100", "Display 100"}
                    else _rounded_box()
                )
            },
        )
        full_grid = {master.location: donors["fallback"][master.name][0] for master in plan}
        self.assertIsNone(exact_node_union(full_grid, reference))

        calls = []

        def reconstruct_rows(jobs, _reference_pos, _workers, **_kwargs):
            row = len(calls)
            calls.append(jobs)
            return {
                name: (
                    {position: _rounded_box() for position in outlines},
                    {"stage": "donor", "note": f"row-{row}"},
                )
                for name, outlines in jobs.items()
            }

        with mock.patch("variable_gen.rebuild.reconstruct_all", side_effect=reconstruct_rows):
            result = reconstruct_plan(donors, plan, "wght", reference, workers=1)

        self.assertEqual(len(calls), 2)
        outlines, info = result["fallback"]
        self.assertEqual(list(outlines), [master.location for master in plan])
        self.assertEqual(
            info,
            {
                "stage": "donor",
                "rows": [
                    {"stage": "donor", "note": "row-0"},
                    {"stage": "donor", "note": "row-1"},
                ],
            },
        )
        self.assertTrue(all(outline == _rounded_box() for outline in outlines.values()))

    def test_exact_candidate_with_midpoint_kink_falls_back_to_rows(self):
        plan = _plan()
        reference: AxisLocation = plan[1].location
        donors = _donor_grid(
            plan,
            {
                "kink": lambda master: _rounded_box(
                    split_curve=master.name in {"Text 400", "Display 950"}
                )
            },
        )
        horizontal = _kink_outline(vertical=False)
        vertical = _kink_outline(vertical=True)
        self.assertFalse(_interp_smooth({100.0: horizontal, 400.0: vertical}))
        candidate = {
            master.location: (horizontal if master.location["opsz"] == 14.0 else vertical)
            for master in plan
        }

        # exact_node_union's own tests establish subdivision fidelity. Supplying
        # its compatible result directly keeps this scheduler test focused on a
        # nonlinear handle interpolation that is impractical to induce through
        # donor node matching here.
        with (
            mock.patch("variable_gen.rebuild.exact_node_union", return_value=candidate),
            mock.patch("variable_gen.rebuild._interp_ok", return_value=True),
            mock.patch(
                "variable_gen.rebuild._has_interpolated_self_intersection",
                return_value=False,
            ),
            mock.patch("variable_gen.rebuild._quality_offenders", return_value=None),
            mock.patch(
                "variable_gen.rebuild.reconstruct_all",
                side_effect=_successful_row_fallback,
            ) as reconstruct_rows,
        ):
            result = reconstruct_plan(donors, plan, "wght", reference, workers=1)

        self.assertEqual(reconstruct_rows.call_count, 2)
        self.assertEqual(result["kink"][1]["stage"], "donor")

    def test_exact_candidate_with_depth_kink_falls_back_to_rows(self):
        plan = _plan()
        reference: AxisLocation = plan[1].location
        donors = _donor_grid(
            plan,
            {
                "depth": lambda master: _rounded_box(
                    split_curve=master.name in {"Text 400", "Display 950"}
                )
            },
        )
        horizontal = _depth_kink_outline(vertical=False)
        vertical = _depth_kink_outline(vertical=True)
        pair = {100.0: horizontal, 400.0: vertical}
        self.assertTrue(_interp_ok(pair))
        self.assertTrue(_interp_smooth(pair))
        self.assertFalse(_has_interpolated_self_intersection(pair))
        candidate = {
            master.location: (horizontal if master.location["wght"] == 100.0 else vertical)
            for master in plan
        }

        with (
            mock.patch("variable_gen.rebuild.exact_node_union", return_value=candidate),
            mock.patch("variable_gen.rebuild._quality_offenders", return_value=None),
            mock.patch(
                "variable_gen.rebuild.reconstruct_all",
                side_effect=_successful_row_fallback,
            ) as reconstruct_rows,
        ):
            result = reconstruct_plan(donors, plan, "wght", reference, workers=1)

        self.assertEqual(reconstruct_rows.call_count, 2)
        self.assertEqual(result["depth"][1]["stage"], "donor")

    def test_real_exact_union_midpoint_kink_falls_back_to_rows(self):
        light_location = AxisLocation((("wght", 0.0),))
        heavy_location = AxisLocation((("wght", 1.0),))
        plan = [
            PlanMaster("Light", Path("unused-light.ttf"), light_location),
            PlanMaster("Heavy", Path("unused-heavy.ttf"), heavy_location),
        ]

        # Both endpoint masters are smooth at (100, 0). The heavy master's
        # first cubic is the exact t=.5 subdivision of
        # (0,0) -> (30,50) -> (200,0) -> (100,0).
        light = [
            [
                ("moveTo", [(0.0, 0.0)]),
                ("curveTo", [(30.0, 50.0), (90.0, 0.0), (100.0, 0.0)]),
                ("curveTo", [(200.0, 0.0), (30.0, -50.0), (0.0, 0.0)]),
                ("closePath", []),
            ]
        ]
        heavy = [
            [
                ("moveTo", [(0.0, 0.0)]),
                ("curveTo", [(15.0, 25.0), (65.0, 25.0), (98.75, 18.75)]),
                ("curveTo", [(132.5, 12.5), (150.0, 0.0), (100.0, 0.0)]),
                ("curveTo", [(90.0, 0.0), (30.0, -50.0), (0.0, 0.0)]),
                ("closePath", []),
            ]
        ]
        grid = {light_location: light, heavy_location: heavy}
        candidate = exact_node_union(grid, light_location)
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertTrue(_interp_ok(candidate))
        self.assertFalse(_interp_smooth(candidate))
        self.assertFalse(_has_interpolated_self_intersection(candidate))

        donors = {
            "kink": {
                "Light": (light, 500.0),
                "Heavy": (heavy, 500.0),
            }
        }
        with mock.patch(
            "variable_gen.rebuild.reconstruct_all",
            side_effect=_successful_row_fallback,
        ) as reconstruct_rows:
            result = reconstruct_plan(
                donors,
                plan,
                "wght",
                light_location,
                workers=1,
            )

        reconstruct_rows.assert_called_once()
        self.assertEqual(
            result["kink"][1],
            {
                "stage": "donor",
                "rows": [{"stage": "donor", "note": "row-fallback"}],
            },
        )

    def test_exact_candidate_with_interpolated_self_intersection_falls_back_to_rows(self):
        plan = _plan()
        reference: AxisLocation = plan[1].location
        donors = _donor_grid(
            plan,
            {
                "cross": lambda master: _rounded_box(
                    split_curve=master.name in {"Text 400", "Display 950"}
                )
            },
        )
        ordered = _crossing_rectangles(moving_right=False)
        swapped = _crossing_rectangles(moving_right=True)
        self.assertTrue(_has_interpolated_self_intersection({100.0: ordered, 400.0: swapped}))
        candidate = {
            master.location: (ordered if master.location["wght"] == 100.0 else swapped)
            for master in plan
        }

        with (
            mock.patch("variable_gen.rebuild.exact_node_union", return_value=candidate),
            mock.patch("variable_gen.rebuild._interp_ok", return_value=True),
            mock.patch("variable_gen.rebuild._interp_smooth", return_value=True),
            mock.patch("variable_gen.rebuild._quality_offenders", return_value=None),
            mock.patch(
                "variable_gen.rebuild.reconstruct_all",
                side_effect=_successful_row_fallback,
            ) as reconstruct_rows,
        ):
            result = reconstruct_plan(donors, plan, "wght", reference, workers=1)

        self.assertEqual(reconstruct_rows.call_count, 2)
        self.assertEqual(result["cross"][1]["stage"], "donor")

    def test_exact_union_preserves_input_order_and_serial_parallel_determinism(self):
        plan = _plan()
        reference: AxisLocation = plan[1].location
        donors = _donor_grid(
            plan,
            {
                "z-exact": lambda master: _rounded_box(
                    split_curve=master.name in {"Text 400", "Display 950"}
                ),
                "a-donor": lambda _master: _rounded_box(),
            },
        )

        serial = reconstruct_plan(donors, plan, "wght", reference, workers=1)
        parallel = reconstruct_plan(donors, plan, "wght", reference, workers=2)

        self.assertEqual(list(serial), ["z-exact", "a-donor"])
        self.assertEqual(serial, parallel)
        self.assertEqual(
            list(serial["z-exact"][0]),
            [master.location for master in plan],
        )


if __name__ == "__main__":
    unittest.main()
