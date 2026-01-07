import json
from pathlib import Path

import pytest

from services.tab_config import load_tab_config, save_tab_config, apply_tab_reorder


def test_load_tab_config_handles_invalid_file(tmp_path: Path):
    path = tmp_path / "ui_config.json"
    path.write_text("not-json")

    config = load_tab_config(path, ["alpha", "beta"])

    assert config.order == ["alpha", "beta"]
    assert config.enabled == ["alpha", "beta"]


def test_load_tab_config_filters_and_recovers_defaults(tmp_path: Path):
    path = tmp_path / "ui_config.json"
    raw = {"tab_order": ["beta", "ghost"], "enabled_tabs": ["ghost"]}
    path.write_text(json.dumps(raw))

    config = load_tab_config(path, ["alpha", "beta", "gamma"])

    assert config.order == ["beta", "alpha", "gamma"]
    assert config.enabled == ["beta", "alpha", "gamma"]


def test_save_and_apply_tab_reorder(tmp_path: Path):
    path = tmp_path / "ui_config.json"

    config = apply_tab_reorder(
        ["alpha", "beta", "gamma"],
        ["alpha", "gamma"],
        {"alpha": 2, "beta": 1, "gamma": 3},
    )

    save_tab_config(path, config.order, config.enabled)
    saved = json.loads(path.read_text())

    assert saved == {"enabled_tabs": ["alpha", "gamma"], "tab_order": ["beta", "alpha", "gamma"]}


def test_apply_tab_reorder_rejects_empty_enabled():
    with pytest.raises(ValueError, match="At least one tab must remain enabled"):
        apply_tab_reorder(["alpha"], [], {"alpha": 1})
