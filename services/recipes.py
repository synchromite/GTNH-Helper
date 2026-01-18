from __future__ import annotations

import sqlite3

from services.db import ALL_TIERS

def load_online_machine_availability(profile_conn: sqlite3.Connection | None) -> dict[str, set[str]]:
    if profile_conn is None:
        return {}
    rows = profile_conn.execute(
        "SELECT machine_type, tier, online FROM machine_availability",
    ).fetchall()
    available: dict[str, set[str]] = {}
    for row in rows:
        online = int(row["online"] or 0)
        if online <= 0:
            continue
        machine_type = (row["machine_type"] or "").strip().lower()
        if not machine_type:
            continue
        tier = (row["tier"] or "").strip()
        available.setdefault(machine_type, set()).add(tier)
    return available

def _recipe_machine_available(row: sqlite3.Row, available_machines: dict[str, set[str]]) -> bool:
    method = (row["method"] or "machine").strip().lower()
    if method != "machine":
        return True
    machine_name = (row["machine_item_name"] or "").strip()
    machine_type = (machine_name or row["machine"] or "").strip().lower()
    if not machine_type:
        return True
    tiers = available_machines.get(machine_type)
    if not tiers:
        return False
    tier = (row["tier"] or "").strip() or (row["machine_item_tier"] or "").strip()
    if not tier:
        return True

    # Check for exact match or higher tier
    if tier in tiers:
        return True

    try:
        req_idx = ALL_TIERS.index(tier)
        for owned in tiers:
            try:
                if ALL_TIERS.index(owned) >= req_idx:
                    return True
            except ValueError:
                continue
    except ValueError:
        pass

    return False

def fetch_recipes(
    conn: sqlite3.Connection,
    enabled_tiers: list[str],
    available_machines: dict[str, set[str]] | None = None,
) -> list[sqlite3.Row]:
    if not enabled_tiers:
        enabled_tiers = ["Stone Age"]
    placeholders = ",".join(["?"] * len(enabled_tiers))
    sql = (
        "SELECT r.id, r.name, r.method, r.machine, r.machine_item_id, r.grid_size, r.station_item_id, "
        "       r.tier, r.circuit, r.duration_ticks, r.eu_per_tick, r.duplicate_of_recipe_id, "
        "       mi.machine_tier AS machine_item_tier, "
        "       COALESCE(mi.display_name, mi.key) AS machine_item_name "
        "FROM recipes r "
        "LEFT JOIN items mi ON mi.id = r.machine_item_id "
        f"WHERE (r.tier IS NULL OR TRIM(r.tier)='' OR r.tier IN ({placeholders})) "
        "ORDER BY r.name"
    )
    rows = conn.execute(sql, tuple(enabled_tiers)).fetchall()
    if not available_machines:
        return rows
    return [row for row in rows if _recipe_machine_available(row, available_machines)]

def fetch_recipe_lines(conn: sqlite3.Connection, recipe_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT rl.direction, COALESCE(i.display_name, i.key) AS name, rl.qty_count, rl.qty_liters,
               rl.chance_percent, rl.consumption_chance, rl.output_slot_index, rl.input_slot_index
        FROM recipe_lines rl
        JOIN items i ON i.id = rl.item_id
        WHERE rl.recipe_id=?
        ORDER BY rl.id
        """,
        (recipe_id,),
    ).fetchall()

def fetch_item_name(conn: sqlite3.Connection, item_id: int) -> str:
    row = conn.execute(
        "SELECT COALESCE(display_name, key) AS name FROM items WHERE id=?",
        (item_id,),
    ).fetchone()
    return row["name"] if row else ""

def fetch_machine_output_slots(conn: sqlite3.Connection, machine_item_id: int) -> int | None:
    row = conn.execute(
        """
        SELECT COALESCE(mm.output_slots, 1) AS machine_output_slots
        FROM items i
        LEFT JOIN machine_metadata mm ON (
            mm.machine_type = i.machine_type
            AND mm.tier = i.machine_tier
        )
        WHERE i.id=?
        """,
        (machine_item_id,),
    ).fetchone()
    if not row:
        return None
    try:
        return int(row["machine_output_slots"] or 1)
    except Exception:
        return 1
