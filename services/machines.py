from __future__ import annotations

import sqlite3
import re

from services.db import ALL_TIERS


def fetch_machine_metadata(conn: sqlite3.Connection, *, tiers: list[str] | None = None) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT machine_type,
               tier,
               machine_name,
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


def _slugify_key(text: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return key or "machine"


def _sync_machine_items(conn: sqlite3.Connection) -> None:
    metadata_rows = conn.execute(
        """
        SELECT machine_type, tier, machine_name
        FROM machine_metadata
        WHERE TRIM(COALESCE(machine_type, '')) <> ''
          AND TRIM(COALESCE(tier, '')) <> ''
        """
    ).fetchall()

    for row in metadata_rows:
        machine_type = (row["machine_type"] or "").strip()
        tier = (row["tier"] or "").strip()
        machine_name = (row["machine_name"] or "").strip() or f"{tier} {machine_type}"
        existing_rows = conn.execute(
            """
            SELECT id
            FROM items
            WHERE kind='machine' AND machine_type=? AND machine_tier=?
            ORDER BY id
            """,
            (machine_type, tier),
        ).fetchall()
        if existing_rows:
            conn.execute(
                """
                UPDATE items
                SET display_name=?, is_machine=1
                WHERE id=?
                """,
                (machine_name, int(existing_rows[0]["id"])),
            )
            continue

        base_key = f"machine_{_slugify_key(machine_type)}_{_slugify_key(tier)}"
        key = base_key
        suffix = 2
        while conn.execute("SELECT 1 FROM items WHERE key=?", (key,)).fetchone():
            key = f"{base_key}_{suffix}"
            suffix += 1

        conn.execute(
            """
            INSERT INTO items(
                key,
                display_name,
                kind,
                is_base,
                is_machine,
                machine_tier,
                machine_type,
                is_multiblock
            )
            VALUES(?, ?, 'machine', 0, 1, ?, ?, 0)
            """,
            (key, machine_name, tier, machine_type),
        )


def replace_machine_metadata(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM machine_metadata")
        conn.executemany(
            """
            INSERT INTO machine_metadata(
                machine_type,
                tier,
                machine_name,
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
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        _sync_machine_items(conn)
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
