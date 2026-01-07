from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class TabConfig:
    order: list[str]
    enabled: list[str]


def config_path(base_dir: Path, filename: str = "ui_config.json") -> Path:
    return base_dir / filename


def load_tab_config(path: Path, tab_ids: Iterable[str]) -> TabConfig:
    default_order = list(tab_ids)
    default_enabled = list(default_order)
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return TabConfig(order=default_order, enabled=default_enabled)

    order = raw.get("tab_order", default_order)
    enabled = raw.get("enabled_tabs", default_enabled)
    order = [tid for tid in order if tid in default_order]
    for tid in default_order:
        if tid not in order:
            order.append(tid)
    enabled = [tid for tid in enabled if tid in order]
    if not enabled:
        enabled = list(default_enabled)
    enabled_ordered = [tid for tid in order if tid in enabled]
    return TabConfig(order=order, enabled=enabled_ordered)


def save_tab_config(path: Path, order: list[str], enabled: list[str]) -> None:
    data = {"enabled_tabs": enabled, "tab_order": order}
    path.write_text(json.dumps(data, indent=2))


def apply_tab_reorder(
    current_order: list[str],
    enabled_tabs: list[str],
    orders: dict[str, int],
) -> TabConfig:
    if any(tab_id not in current_order for tab_id in orders):
        raise ValueError("Unknown tab id in ordering data.")
    max_order = len(current_order)
    for tab_id, order_val in orders.items():
        if order_val < 1 or order_val > max_order:
            raise ValueError(f"Order for {tab_id} must be within the allowed range.")
    if len(set(orders.values())) != len(current_order):
        raise ValueError("Order values must be unique.")

    new_order = [tab_id for tab_id, _ in sorted(orders.items(), key=lambda item: item[1])]
    enabled_set = set(enabled_tabs)
    new_enabled = [tab_id for tab_id in new_order if tab_id in enabled_set]
    if not new_enabled:
        raise ValueError("At least one tab must remain enabled.")
    return TabConfig(order=new_order, enabled=new_enabled)
