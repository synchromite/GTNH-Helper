from __future__ import annotations

import sqlite3

from services.db import ALL_TIERS


def fetch_machine_metadata(conn: sqlite3.Connection, *, tiers: list[str] | None = None) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT machine_type,
               tier,
               input_slots,
               output_slots,
               byproduct_slots,
               storage_slots,
               power_slots,
               circuit_slots,
               input_tanks,
               input_tank_capacity_l,
               output_tanks,
               output_tank_capacity_l
        FROM machine_metadata
        """
    ).fetchall()
    tier_list = tiers or list(ALL_TIERS)
    tier_order = {tier: idx for idx, tier in enumerate(tier_list)}

    def sort_key(row: sqlite3.Row) -> tuple[str, int]:
        machine_type = (row["machine_type"] or "").strip().lower()
        tier = (row["tier"] or "").strip()
        return (machine_type, tier_order.get(tier, len(tier_list)))

    return sorted(rows, key=sort_key)


def replace_machine_metadata(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM machine_metadata")
        conn.executemany(
            """
            INSERT INTO machine_metadata(
                machine_type,
                tier,
                input_slots,
                output_slots,
                byproduct_slots,
                storage_slots,
                power_slots,
                circuit_slots,
                input_tanks,
                input_tank_capacity_l,
                output_tanks,
                output_tank_capacity_l
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
