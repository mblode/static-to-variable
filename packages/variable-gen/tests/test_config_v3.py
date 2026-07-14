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
CONFIG_PATH = REPO_ROOT / "examples" / "glide" / "stv.config.json"


def _load_raw() -> dict:
    return json.loads(CONFIG_PATH.read_text())


def _write_temp(data: dict) -> Path:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(data, tmp)
    tmp.close()
    return Path(tmp.name)


def test_loads_glide_example() -> None:
    config = load_config(CONFIG_PATH)

    assert config.id == "glide"
    assert config.version == 3
    assert config.family.name == "Glide"
    assert config.family.version == "2.000"
    assert config.family.vendor == "MBLD"
    assert config.family.designer == "Matthew Blode"


def test_axis_range_and_named_instances() -> None:
    config = load_config(CONFIG_PATH)

    assert [axis.tag for axis in config.axes] == ["wght"]
    axis = config.axes[0]
    assert (axis.minimum, axis.default, axis.maximum) == (100.0, 400.0, 950.0)
    assert axis.named_instances[100.0] == "Thin"
    assert axis.named_instances[950.0] == "ExtraBlack"
    assert len(axis.named_instances) == 10


def test_two_styles_with_ordered_masters() -> None:
    config = load_config(CONFIG_PATH)

    assert sorted(config.styles) == ["italic", "roman"]
    for style in config.styles.values():
        assert [m.name for m in style.masters] == ["Thin", "Regular", "ExtraBlack"]
        assert [m.location["wght"] for m in style.masters] == [100.0, 400.0, 950.0]
        assert sum(1 for m in style.masters if m.default) == 1
        default_master = next(m for m in style.masters if m.default)
        assert default_master.name == "Regular"
    assert config.styles["roman"].italic is False
    assert config.styles["italic"].italic is True


def test_vertical_metrics_and_glyph_strategies() -> None:
    config = load_config(CONFIG_PATH)

    assert config.vertical_metrics is not None
    assert config.vertical_metrics.ascender == 986.0
    assert config.vertical_metrics.descender == -277.0
    assert config.vertical_metrics.cap_height == 709.0
    assert config.vertical_metrics.x_height == 481.0

    assert "emacron" in config.glyphs.freeze
    dollar = config.glyphs.strategies["dollar"]
    assert dollar.strategy == "open_bar"
    assert dollar.params["letter"] == "S"
    assert "italic" in config.glyphs.seeds
    assert "roman" in config.glyphs.seeds


def test_rejects_v2_manifest() -> None:
    data = _load_raw()
    data["version"] = 2
    path = _write_temp(data)
    with pytest.raises(ConfigError, match="v2 manifest"):
        load_config(path)


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
