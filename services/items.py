from __future__ import annotations

import sqlite3


def fetch_items(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT i.id, i.key, COALESCE(i.display_name, i.key) AS name, i.kind, i.is_base, i.is_machine, i.machine_tier, "
        "       i.machine_input_slots, i.machine_output_slots, i.machine_storage_slots, i.machine_power_slots, "
        "       i.machine_circuit_slots, i.machine_input_tanks, i.machine_input_tank_capacity_l, "
        "       i.machine_output_tanks, i.machine_output_tank_capacity_l, "
        "       i.material_id, m.name AS material_name, "
        "       k.name AS item_kind_name "
        "FROM items i "
        "LEFT JOIN materials m ON m.id = i.material_id "
        "LEFT JOIN item_kinds k ON k.id = i.item_kind_id "
        "ORDER BY name"
    ).fetchall()
