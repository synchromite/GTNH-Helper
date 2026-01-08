from __future__ import annotations

import sqlite3


def fetch_recipes(conn: sqlite3.Connection, enabled_tiers: list[str]) -> list[sqlite3.Row]:
    if not enabled_tiers:
        enabled_tiers = ["Stone Age"]
    placeholders = ",".join(["?"] * len(enabled_tiers))
    sql = (
        "SELECT id, name, method, machine, machine_item_id, grid_size, station_item_id, tier, circuit, duration_ticks, "
        "       eu_per_tick, duplicate_of_recipe_id "
        "FROM recipes "
        f"WHERE (tier IS NULL OR TRIM(tier)='' OR tier IN ({placeholders})) "
        "ORDER BY name"
    )
    return conn.execute(sql, tuple(enabled_tiers)).fetchall()


def fetch_recipe_lines(conn: sqlite3.Connection, recipe_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT rl.direction, COALESCE(i.display_name, i.key) AS name, rl.qty_count, rl.qty_liters, rl.chance_percent, rl.output_slot_index
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
        "SELECT machine_output_slots FROM items WHERE id=?",
        (machine_item_id,),
    ).fetchone()
    if not row:
        return None
    try:
        return int(row["machine_output_slots"] or 1)
    except Exception:
        return 1
