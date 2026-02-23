from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SNAPSHOT_SCHEMA_VERSION = 1


@dataclass(slots=True)
class InventorySyncReport:
    """Summary of an applied mod inventory snapshot."""

    imported_rows: int
    unknown_item_keys: list[str]


def load_inventory_snapshot(snapshot_path: str | Path) -> dict[str, Any]:
    """Load and validate a Minecraft-mod inventory snapshot JSON document.

    Expected format:
    {
      "schema_version": 1,
      "entries": [
        {"item_key": "minecraft:iron_ingot", "qty_count": 64},
        {"item_key": "water", "qty_liters": 1000}
      ]
    }
    """

    path = Path(snapshot_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise ValueError("Snapshot root must be a JSON object.")

    version = int(payload.get("schema_version", 0) or 0)
    if version != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError(f"Unsupported snapshot schema_version={version}; expected {SNAPSHOT_SCHEMA_VERSION}.")

    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Snapshot must contain an 'entries' array.")

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"Entry #{idx} must be an object.")
        item_key = (entry.get("item_key") or "").strip()
        if not item_key:
            raise ValueError(f"Entry #{idx} is missing non-empty 'item_key'.")
        if "qty_count" not in entry and "qty_liters" not in entry:
            raise ValueError(f"Entry #{idx} must include qty_count and/or qty_liters.")

    return payload


def build_inventory_snapshot(
    profile_conn: sqlite3.Connection,
    content_conn: sqlite3.Connection,
    *,
    include_zero_qty: bool = False,
) -> dict[str, Any]:
    """Build snapshot payload from current profile inventory."""

    id_to_key = {
        int(row["id"]): str(row["key"])
        for row in content_conn.execute("SELECT id, key FROM items ORDER BY key").fetchall()
    }

    query = """
        SELECT item_id, qty_count, qty_liters
        FROM inventory
        ORDER BY item_id
    """

    entries: list[dict[str, Any]] = []
    for row in profile_conn.execute(query).fetchall():
        item_key = id_to_key.get(int(row["item_id"]))
        if not item_key:
            continue
        qty_count = row["qty_count"]
        qty_liters = row["qty_liters"]
        count_val = float(qty_count) if qty_count is not None else None
        liter_val = float(qty_liters) if qty_liters is not None else None
        if not include_zero_qty:
            has_nonzero = (count_val is not None and count_val > 0) or (liter_val is not None and liter_val > 0)
            if not has_nonzero:
                continue

        entry: dict[str, Any] = {"item_key": item_key}
        if qty_count is not None:
            entry["qty_count"] = int(count_val) if float(count_val).is_integer() else count_val
        if qty_liters is not None:
            entry["qty_liters"] = int(liter_val) if float(liter_val).is_integer() else liter_val
        entries.append(entry)

    entries.sort(key=lambda row: str(row["item_key"]))

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "entries": entries,
    }


def write_inventory_snapshot(
    snapshot_path: str | Path,
    profile_conn: sqlite3.Connection,
    content_conn: sqlite3.Connection,
    *,
    include_zero_qty: bool = False,
) -> Path:
    """Build and write an inventory snapshot to disk."""

    path = Path(snapshot_path)
    payload = build_inventory_snapshot(
        profile_conn,
        content_conn,
        include_zero_qty=include_zero_qty,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return path


def apply_inventory_snapshot(
    profile_conn: sqlite3.Connection,
    content_conn: sqlite3.Connection,
    snapshot: dict[str, Any],
    *,
    clear_existing: bool = True,
) -> InventorySyncReport:
    """Apply snapshot entries into profile inventory table.

    Only rows with item keys that exist in the content DB are imported.
    Unknown keys are returned in the report for caller-side diagnostics.
    """

    key_to_id = {
        str(row["key"]): int(row["id"])
        for row in content_conn.execute("SELECT id, key FROM items").fetchall()
    }

    unknown: list[str] = []
    upsert_rows: list[tuple[int, float | None, float | None]] = []

    for entry in snapshot.get("entries", []):
        item_key = str(entry.get("item_key") or "").strip()
        item_id = key_to_id.get(item_key)
        if item_id is None:
            unknown.append(item_key)
            continue

        qty_count_raw = entry.get("qty_count")
        qty_liters_raw = entry.get("qty_liters")
        qty_count = float(qty_count_raw) if qty_count_raw is not None else None
        qty_liters = float(qty_liters_raw) if qty_liters_raw is not None else None

        if qty_count is not None and qty_count < 0:
            raise ValueError(f"qty_count cannot be negative for item_key='{item_key}'.")
        if qty_liters is not None and qty_liters < 0:
            raise ValueError(f"qty_liters cannot be negative for item_key='{item_key}'.")

        upsert_rows.append((item_id, qty_count, qty_liters))

    with profile_conn:
        if clear_existing:
            profile_conn.execute("DELETE FROM inventory")
        profile_conn.executemany(
            """
            INSERT INTO inventory(item_id, qty_count, qty_liters)
            VALUES(?, ?, ?)
            ON CONFLICT(item_id)
            DO UPDATE SET
              qty_count=excluded.qty_count,
              qty_liters=excluded.qty_liters
            """,
            upsert_rows,
        )

    return InventorySyncReport(imported_rows=len(upsert_rows), unknown_item_keys=sorted(set(unknown)))
