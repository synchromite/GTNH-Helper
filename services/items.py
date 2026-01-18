from __future__ import annotations

import sqlite3


def fetch_items(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT 
            i.id, 
            i.key, 
            COALESCE(i.display_name, i.key) AS name, 
            i.kind, 
            i.is_base, 
            i.is_machine, 
            i.machine_tier, 
            i.machine_type,
            i.crafting_grid_size,
            -- For machine stats, prefer the Item override, fallback to Machine Metadata
            COALESCE(mm.input_slots, 1) AS machine_input_slots,
            COALESCE(mm.output_slots, 1) AS machine_output_slots,
            COALESCE(mm.storage_slots, 0) AS machine_storage_slots,
            COALESCE(mm.power_slots, 0) AS machine_power_slots,
            COALESCE(mm.circuit_slots, 0) AS machine_circuit_slots,
            COALESCE(mm.input_tanks, 0) AS machine_input_tanks,
            COALESCE(mm.input_tank_capacity_l, 0) AS machine_input_tank_capacity_l,
            COALESCE(mm.output_tanks, 0) AS machine_output_tanks,
            COALESCE(mm.output_tank_capacity_l, 0) AS machine_output_tank_capacity_l,
            i.material_id, 
            m.name AS material_name, 
            k.name AS item_kind_name 
        FROM items i 
        LEFT JOIN materials m ON m.id = i.material_id 
        LEFT JOIN item_kinds k ON k.id = i.item_kind_id 
        -- Join metadata based on Type + Tier
        LEFT JOIN machine_metadata mm ON (
            mm.machine_type = i.machine_type 
            AND mm.tier = i.machine_tier
        )
        ORDER BY name
        """
    ).fetchall()
