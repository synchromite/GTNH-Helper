from __future__ import annotations

import sqlite3
from typing import Any


MAIN_STORAGE_NAME = "Main Storage"


def has_storage_tables(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='storage_assignments'"
    ).fetchone()
    return row is not None


def list_storage_units(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM storage_units
        ORDER BY CASE WHEN name = ? THEN 0 ELSE 1 END, LOWER(name), id
        """,
        (MAIN_STORAGE_NAME,),
    ).fetchall()
    return [dict(row) for row in rows]


def default_storage_id(conn: sqlite3.Connection) -> int | None:
    storages = list_storage_units(conn)
    if not storages:
        return None
    for storage in storages:
        if storage.get("name") == MAIN_STORAGE_NAME:
            return int(storage["id"])
    return int(storages[0]["id"])


def create_storage_unit(
    conn: sqlite3.Connection,
    *,
    name: str,
    kind: str = "generic",
    slot_count: int | None = None,
    liter_capacity: float | None = None,
    priority: int = 0,
    allow_planner_use: bool = True,
    notes: str | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO storage_units(name, kind, slot_count, liter_capacity, priority, allow_planner_use, notes)
        VALUES(?, ?, ?, ?, ?, ?, ?)
        """,
        (name, kind, slot_count, liter_capacity, priority, 1 if allow_planner_use else 0, notes),
    )
    return int(cur.lastrowid)


def update_storage_unit(conn: sqlite3.Connection, storage_id: int, **fields: Any) -> None:
    allowed = {"name", "kind", "slot_count", "liter_capacity", "priority", "allow_planner_use", "notes"}
    updates: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "allow_planner_use":
            value = 1 if bool(value) else 0
        updates.append(f"{key}=?")
        values.append(value)
    if not updates:
        return
    values.append(storage_id)
    conn.execute(f"UPDATE storage_units SET {', '.join(updates)} WHERE id=?", values)


def delete_storage_unit(conn: sqlite3.Connection, storage_id: int) -> None:
    conn.execute("DELETE FROM storage_units WHERE id=?", (storage_id,))


def get_assignment(
    conn: sqlite3.Connection,
    *,
    storage_id: int,
    item_id: int,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT storage_id, item_id, qty_count, qty_liters, locked FROM storage_assignments WHERE storage_id=? AND item_id=?",
        (storage_id, item_id),
    ).fetchone()


def upsert_assignment(
    conn: sqlite3.Connection,
    *,
    storage_id: int,
    item_id: int,
    qty_count: int | float | None,
    qty_liters: int | float | None,
    locked: bool = False,
) -> None:
    conn.execute(
        """
        INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters, locked)
        VALUES(?, ?, ?, ?, ?)
        ON CONFLICT(storage_id, item_id)
        DO UPDATE SET qty_count=excluded.qty_count, qty_liters=excluded.qty_liters, locked=excluded.locked
        """,
        (storage_id, item_id, qty_count, qty_liters, 1 if locked else 0),
    )


def delete_assignment(conn: sqlite3.Connection, *, storage_id: int, item_id: int) -> None:
    conn.execute("DELETE FROM storage_assignments WHERE storage_id=? AND item_id=?", (storage_id, item_id))


def aggregate_assignment_for_item(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT SUM(qty_count) AS qty_count, SUM(qty_liters) AS qty_liters
        FROM storage_assignments
        WHERE item_id=?
        """,
        (item_id,),
    ).fetchone()


def aggregated_assignment_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT item_id, SUM(qty_count) AS qty_count, SUM(qty_liters) AS qty_liters
        FROM storage_assignments
        GROUP BY item_id
        """
    ).fetchall()
