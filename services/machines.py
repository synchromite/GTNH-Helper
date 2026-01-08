from __future__ import annotations

import sqlite3

from services.db import ALL_TIERS


def fetch_machine_metadata(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT machine_type, tier
        FROM machine_metadata
        """
    ).fetchall()
    tier_order = {tier: idx for idx, tier in enumerate(ALL_TIERS)}

    def sort_key(row: sqlite3.Row) -> tuple[str, int]:
        machine_type = (row["machine_type"] or "").strip().lower()
        tier = (row["tier"] or "").strip()
        return (machine_type, tier_order.get(tier, len(ALL_TIERS)))

    return sorted(rows, key=sort_key)
