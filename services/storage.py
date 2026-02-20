from __future__ import annotations

import math
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
    container_item_id: int | None = None,
    owned_count: int | None = None,
    placed_count: int | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO storage_units(
            name, kind, slot_count, liter_capacity, priority, allow_planner_use,
            container_item_id, owned_count, placed_count, notes
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            kind,
            slot_count,
            liter_capacity,
            priority,
            1 if allow_planner_use else 0,
            container_item_id,
            owned_count,
            placed_count,
            notes,
        ),
    )
    return int(cur.lastrowid)


def update_storage_unit(conn: sqlite3.Connection, storage_id: int, **fields: Any) -> None:
    allowed = {"name", "kind", "slot_count", "liter_capacity", "priority", "allow_planner_use", "notes", "container_item_id", "owned_count", "placed_count"}
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


def assignment_slot_usage(qty_count: float | int | None, max_stack_size: int | None = 64) -> int:
    qty = float(qty_count or 0)
    if qty <= 0:
        return 0
    stack = max(1, int(max_stack_size or 64))
    return int(math.ceil(qty / stack))


def validate_storage_fit_for_item(
    conn: sqlite3.Connection,
    *,
    storage_id: int,
    item_id: int,
    qty_count: float | int | None,
    qty_liters: float | int | None,
    item_max_stack_size: int | None = 64,
    known_item_stack_sizes: dict[int, int] | None = None,
    known_container_item_ids: set[int] | None = None,
) -> dict[str, int | float | bool | None]:
    storage = conn.execute(
        "SELECT slot_count, liter_capacity FROM storage_units WHERE id=?",
        (storage_id,),
    ).fetchone()
    if storage is None:
        return {
            "fits": False,
            "fits_slots": False,
            "fits_liters": False,
            "slot_count": None,
            "slot_usage": 0,
            "slot_overflow": 0,
            "liter_capacity": None,
            "liter_usage": 0,
            "liter_overflow": 0,
        }

    slot_count = storage["slot_count"]
    liter_capacity = storage["liter_capacity"]

    rows = conn.execute(
        "SELECT item_id, qty_count, qty_liters FROM storage_assignments WHERE storage_id=?",
        (storage_id,),
    ).fetchall()

    slot_usage = 0
    liter_usage = 0.0
    target_replaced = False
    for row in rows:
        rid = int(row["item_id"])
        if rid == item_id:
            row_qty_count = qty_count
            row_qty_liters = qty_liters
            stack_size = item_max_stack_size
            target_replaced = True
        else:
            row_qty_count = row["qty_count"]
            row_qty_liters = row["qty_liters"]
            stack_size = (known_item_stack_sizes or {}).get(rid, 64)
        if rid not in (known_container_item_ids or set()):
            slot_usage += assignment_slot_usage(row_qty_count, stack_size)
        liter_usage += float(row_qty_liters or 0)

    if not target_replaced:
        if item_id not in (known_container_item_ids or set()):
            slot_usage += assignment_slot_usage(qty_count, item_max_stack_size)
        liter_usage += float(qty_liters or 0)

    if slot_count is None:
        fits_slots = True
        slot_overflow = 0
    else:
        fits_slots = slot_usage <= int(slot_count)
        slot_overflow = max(0, int(slot_usage - int(slot_count)))

    if liter_capacity is None:
        fits_liters = True
        liter_overflow = 0.0
    else:
        fits_liters = liter_usage <= float(liter_capacity)
        liter_overflow = max(0.0, float(liter_usage - float(liter_capacity)))

    return {
        "fits": bool(fits_slots and fits_liters),
        "fits_slots": bool(fits_slots),
        "fits_liters": bool(fits_liters),
        "slot_count": None if slot_count is None else int(slot_count),
        "slot_usage": int(slot_usage),
        "slot_overflow": int(slot_overflow),
        "liter_capacity": None if liter_capacity is None else float(liter_capacity),
        "liter_usage": float(liter_usage),
        "liter_overflow": float(liter_overflow),
    }


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


def aggregated_assignment_rows_for_planner(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            a.item_id,
            SUM(a.qty_count) AS qty_count,
            SUM(a.qty_liters) AS qty_liters
        FROM storage_assignments a
        INNER JOIN storage_units s ON s.id = a.storage_id
        WHERE s.allow_planner_use = 1
          AND a.locked = 0
        GROUP BY a.item_id
        """
    ).fetchall()


def storage_inventory_totals(conn: sqlite3.Connection, storage_id: int | None = None) -> dict[str, float | int]:
    """Return assignment/totals summary for one storage or all storages."""
    if storage_id is None:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS entry_count,
                COALESCE(SUM(qty_count), 0) AS total_count,
                COALESCE(SUM(qty_liters), 0) AS total_liters
            FROM storage_assignments
            """
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS entry_count,
                COALESCE(SUM(qty_count), 0) AS total_count,
                COALESCE(SUM(qty_liters), 0) AS total_liters
            FROM storage_assignments
            WHERE storage_id=?
            """,
            (storage_id,),
        ).fetchone()
    return {
        "entry_count": int(row["entry_count"] or 0),
        "total_count": int(round(float(row["total_count"] or 0))),
        "total_liters": int(round(float(row["total_liters"] or 0))),
    }


def list_storage_container_placements(conn: sqlite3.Connection, storage_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            p.storage_id,
            p.item_id,
            p.placed_count
        FROM storage_container_placements p
        WHERE p.storage_id=?
        ORDER BY p.item_id
        """,
        (storage_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def set_storage_container_placement(
    conn: sqlite3.Connection,
    *,
    storage_id: int,
    item_id: int,
    placed_count: int,
) -> None:
    placed = max(0, int(placed_count))
    if placed <= 0:
        conn.execute(
            "DELETE FROM storage_container_placements WHERE storage_id=? AND item_id=?",
            (storage_id, item_id),
        )
        return
    conn.execute(
        """
        INSERT INTO storage_container_placements(storage_id, item_id, placed_count)
        VALUES(?, ?, ?)
        ON CONFLICT(storage_id, item_id)
        DO UPDATE SET placed_count=excluded.placed_count
        """,
        (storage_id, item_id, placed),
    )


def placed_container_count(
    conn: sqlite3.Connection,
    *,
    item_id: int,
    exclude_storage_id: int | None = None,
) -> int:
    if exclude_storage_id is None:
        row = conn.execute(
            "SELECT COALESCE(SUM(placed_count), 0) AS c FROM storage_container_placements WHERE item_id=?",
            (item_id,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(placed_count), 0) AS c
            FROM storage_container_placements
            WHERE item_id=? AND storage_id<>?
            """,
            (item_id, exclude_storage_id),
        ).fetchone()
    return int(row["c"] or 0)


def recompute_storage_slot_capacities(
    conn: sqlite3.Connection,
    player_slots: int = 36,
    *,
    content_conn: sqlite3.Connection | None = None,
) -> None:
    slot_rows = (content_conn or conn).execute(
        "SELECT id, COALESCE(storage_slot_count, 0) AS storage_slot_count FROM items"
    ).fetchall()
    slot_map = {int(r["id"]): int(r["storage_slot_count"] or 0) for r in slot_rows}

    storages = list_storage_units(conn)
    for storage in storages:
        storage_id = int(storage["id"])
        placed_rows = conn.execute(
            """
            SELECT p.item_id, p.placed_count
            FROM storage_container_placements p
            WHERE p.storage_id=?
            """,
            (storage_id,),
        ).fetchall()
        slots_from_containers = sum(
            int(row["placed_count"] or 0) * int(slot_map.get(int(row["item_id"]), 0))
            for row in placed_rows
        )
        base_slots = int(player_slots) if str(storage.get("name") or "") == MAIN_STORAGE_NAME else 0
        conn.execute(
            "UPDATE storage_units SET slot_count=? WHERE id=?",
            (base_slots + slots_from_containers, storage_id),
        )


def storage_slot_usage(
    conn: sqlite3.Connection,
    *,
    storage_id: int,
    known_item_stack_sizes: dict[int, int] | None = None,
    known_container_item_ids: set[int] | None = None,
) -> dict[str, int | None]:
    storage = conn.execute("SELECT slot_count FROM storage_units WHERE id=?", (storage_id,)).fetchone()
    slot_count = int(storage["slot_count"]) if storage and storage["slot_count"] is not None else None

    rows = conn.execute(
        "SELECT item_id, qty_count FROM storage_assignments WHERE storage_id=?",
        (storage_id,),
    ).fetchall()
    used = 0
    for row in rows:
        item_id = int(row["item_id"])
        if item_id in (known_container_item_ids or set()):
            continue
        stack_size = (known_item_stack_sizes or {}).get(item_id, 64)
        used += assignment_slot_usage(row["qty_count"], stack_size)

    free = None if slot_count is None else max(0, int(slot_count - used))
    return {"slot_count": slot_count, "slot_used": int(used), "slot_free": free}
