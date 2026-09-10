from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PACKAGE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from variable_gen.config import ConfigError, load_config  # noqa: E402

REPO_ROOT = PACKAGE_ROOT.parents[1]
CONFIG_PATH = REPO_ROOT / "examples" / "inter" / "stv.config.json"


def _load_raw() -> dict:
    return json.loads(CONFIG_PATH.read_text())


def _write_temp(data: dict) -> Path:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(data, tmp)
    tmp.close()
    return Path(tmp.name)


def test_loads_inter_example() -> None:
    config = load_config(CONFIG_PATH)

    assert config.id == "inter"
    assert config.version == 3
    assert config.family.name == "Inter STV"
    assert config.family.version == "1.000"
    assert config.family.vendor == "STV"
    assert config.family.designer == "The Inter Project Authors"


@pytest.mark.parametrize("enabled", [True, False])
def test_style_can_control_gvar_optimization(enabled, tmp_path) -> None:
    raw = _load_raw()
    raw["styles"]["roman"]["optimizeGvar"] = enabled
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    config = load_config(path)
    assert config.styles["roman"].optimize_gvar is enabled
    assert config.styles["italic"].optimize_gvar is True


@pytest.mark.parametrize("value", [0, 1, "false", None])
def test_gvar_optimization_requires_a_boolean(value, tmp_path) -> None:
    raw = _load_raw()
    raw["styles"]["roman"]["optimizeGvar"] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ConfigError, match="optimizeGvar must be a boolean"):
        load_config(path)


def test_authored_delta_preservation_is_opt_in_and_boolean(tmp_path) -> None:
    raw = _load_raw()
    raw["styles"]["roman"]["preserveAuthoredDeltas"] = True
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    config = load_config(path)
    assert config.styles["roman"].preserve_authored_deltas is True
    assert config.styles["italic"].preserve_authored_deltas is False
    raw["styles"]["roman"]["preserveAuthoredDeltas"] = "true"
    path.write_text(json.dumps(raw))
    with pytest.raises(ConfigError, match="preserveAuthoredDeltas must be a boolean"):
        load_config(path)


def test_axis_range_and_named_instances() -> None:
    config = load_config(CONFIG_PATH)

    assert [axis.tag for axis in config.axes] == ["wght"]
    axis = config.axes[0]
    assert (axis.minimum, axis.default, axis.maximum) == (100.0, 400.0, 900.0)
    assert axis.named_instances[100.0] == "Thin"
    assert axis.named_instances[900.0] == "Black"
    assert len(axis.named_instances) == 9


def test_two_styles_with_ordered_masters() -> None:
    config = load_config(CONFIG_PATH)

    assert sorted(config.styles) == ["italic", "roman"]
    for style in config.styles.values():
        assert [m.name for m in style.masters] == ["Thin", "Regular", "Black"]
        assert [m.location["wght"] for m in style.masters] == [100.0, 400.0, 900.0]
        assert sum(1 for m in style.masters if m.default) == 1
        default_master = next(m for m in style.masters if m.default)
        assert default_master.name == "Regular"
    assert config.styles["roman"].italic is False
    assert config.styles["italic"].italic is True


def test_vertical_metrics_and_glyph_strategies() -> None:
    config = load_config(CONFIG_PATH)

    assert config.vertical_metrics is not None
    assert config.vertical_metrics.ascender == 1984.0
    assert config.vertical_metrics.descender == -494.0
    assert config.vertical_metrics.cap_height == 1456.0
    assert config.vertical_metrics.x_height == 1118.0

    assert "periodcentered" in config.glyphs.freeze
    dollar = config.glyphs.strategies["dollar"]
    assert dollar.strategy == "interpolate_neighbors"


def test_rejects_wrong_version() -> None:
    data = _load_raw()
    data["version"] = 4
    path = _write_temp(data)
    with pytest.raises(ConfigError, match="expected version 3"):
        load_config(path)


def test_rejects_missing_family() -> None:
    data = _load_raw()
    del data["family"]
    path = _write_temp(data)
    with pytest.raises(ConfigError, match="family"):
        load_config(path)


def test_rejects_bad_donor_reference() -> None:
    data = _load_raw()
    data["styles"]["roman"]["masters"][0]["donorId"] = "does-not-exist"
    path = _write_temp(data)
    with pytest.raises(ConfigError, match="unknown donorId"):
        load_config(path)


def test_rejects_out_of_range_named_instance() -> None:
    data = _load_raw()
    data["axes"][0]["namedInstances"]["1200"] = "Ultra"
    path = _write_temp(data)
    with pytest.raises(ConfigError, match="outside the axis range"):
        load_config(path)


def test_rejects_multiple_default_masters() -> None:
    data = _load_raw()
    data["styles"]["roman"]["masters"][0]["default"] = True
    path = _write_temp(data)
    with pytest.raises(ConfigError, match="exactly one default"):
        load_config(path)


def test_loads_quadratic_reference_contract() -> None:
    data = _load_raw()
    data["styles"]["roman"]["quadraticReference"] = {
        "path": "references/default.ttf",
        "location": {"opsz": 16, "wght": 400},
        "maxError": 0.75,
        "glyphMaxError": {"curve": 0.25},
    }
    path = _write_temp(data)

    reference = load_config(path).styles["roman"].quadratic_reference

    assert reference is not None
    assert reference.config_path == "references/default.ttf"
    assert reference.path == (path.parent / "references/default.ttf").resolve()
    assert reference.location == {"opsz": 16.0, "wght": 400.0}
    assert reference.max_error == 0.75
    assert reference.glyph_max_error == {"curve": 0.25}


@pytest.mark.parametrize(
    "value", [{"curve": 0}, {"curve": True}, {"curve": float("nan")}, {"": 0.25}, []]
)
def test_rejects_invalid_glyph_precision(value):
    data = _load_raw()
    data["styles"]["roman"]["quadraticReference"] = {
        "path": "reference.ttf",
        "glyphMaxError": value,
    }
    with pytest.raises(ConfigError):
        load_config(_write_temp(data))


def test_loads_quadratic_topology_contract() -> None:
    data = _load_raw()
    data["styles"]["roman"]["quadraticReference"] = {
        "path": "references/default.ttf",
    }
    data["styles"]["roman"]["quadraticTopology"] = {
        "masters": [master["name"] for master in data["styles"]["roman"]["masters"]],
        "glyphs": {"O": [[["moveTo", 1], ["curveTo", 3], ["closePath", 0]]]},
    }
    topology = load_config(_write_temp(data)).styles["roman"].quadratic_topology

    assert topology is not None
    assert topology.glyphs == {"O": ((("moveTo", 1), ("curveTo", 3), ("closePath", 0)),)}
    assert topology.master_names == tuple(
        master["name"] for master in data["styles"]["roman"]["masters"]
    )


def test_loads_protected_reference_masters() -> None:
    data = _load_raw()
    name = data["styles"]["roman"]["masters"][0]["name"]
    data["styles"]["roman"]["quadraticReference"] = {
        "path": "reference.ttf",
        "protectedMasters": {name: {"wght": 100, "opsz": 32}},
    }
    reference = load_config(_write_temp(data)).styles["roman"].quadratic_reference
    assert reference is not None
    assert reference.protected_masters == {name: {"wght": 100.0, "opsz": 32.0}}
    assert reference.location == {}


@pytest.mark.parametrize("protected", [{}, {"missing": {}}, {"missing": 42}, []])
def test_rejects_invalid_protected_reference_masters(protected: object) -> None:
    data = _load_raw()
    data["styles"]["roman"]["quadraticReference"] = {
        "path": "reference.ttf",
        "protectedMasters": protected,
    }
    with pytest.raises(ConfigError):
        load_config(_write_temp(data))


def test_rejects_reference_location_with_protected_masters() -> None:
    data = _load_raw()
    name = data["styles"]["roman"]["masters"][0]["name"]
    data["styles"]["roman"]["quadraticReference"] = {
        "path": "reference.ttf",
        "location": {},
        "protectedMasters": {name: {}},
    }
    with pytest.raises(ConfigError, match="either location or protectedMasters"):
        load_config(_write_temp(data))


def test_rejects_quadratic_topology_without_reference() -> None:
    data = _load_raw()
    data["styles"]["roman"]["quadraticTopology"] = {
        "masters": [master["name"] for master in data["styles"]["roman"]["masters"]],
        "glyphs": {"O": [[["moveTo", 1], ["curveTo", 3], ["closePath", 0]]]},
    }

    with pytest.raises(ConfigError, match="quadraticTopology requires quadraticReference"):
        load_config(_write_temp(data))


@pytest.mark.parametrize("max_error", [0, -1, True, "one"])
def test_rejects_invalid_quadratic_reference_error(max_error: object) -> None:
    data = _load_raw()
    data["styles"]["roman"]["quadraticReference"] = {
        "path": "references/default.ttf",
        "maxError": max_error,
    }
    path = _write_temp(data)

    with pytest.raises(ConfigError, match="quadraticReference.maxError"):
        load_config(path)
