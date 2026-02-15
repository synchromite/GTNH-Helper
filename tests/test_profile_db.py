import sqlite3
import pytest

from services import db


def test_connect_profile_creates_tables(tmp_path):
    profile_path = tmp_path / "profile.db"
    conn = db.connect_profile(profile_path)
    try:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "app_settings" in tables
        assert "inventory" in tables
        assert "machine_availability" in tables
        assert "storage_units" in tables
        assert "storage_assignments" in tables
        assert "machine_metadata" not in tables

        inventory_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(inventory)").fetchall()
        }
        assert {"item_id", "qty_count", "qty_liters"}.issubset(inventory_cols)

        storage_rows = conn.execute("SELECT id, name FROM storage_units").fetchall()
        assert len(storage_rows) == 1
        assert storage_rows[0]["name"] == "Main Storage"

        storage_unit_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(storage_units)").fetchall()
        }
        assert {
            "id",
            "name",
            "kind",
            "slot_count",
            "liter_capacity",
            "priority",
            "allow_planner_use",
            "container_item_id",
            "owned_count",
            "placed_count",
            "notes",
        }.issubset(storage_unit_cols)

        assignment_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(storage_assignments)").fetchall()
        }
        assert {"storage_id", "item_id", "qty_count", "qty_liters", "locked"}.issubset(assignment_cols)

        conn.execute(
            """
            INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters, locked)
            VALUES (?, ?, ?, ?, ?)
            """,
            (storage_rows[0]["id"], 1, 1, None, 0),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters, locked)
                VALUES (?, ?, ?, ?, ?)
                """,
                (storage_rows[0]["id"], 1, 2, None, 1),
            )

        assignment_fks = {
            (row["from"], row["table"], row["on_delete"])
            for row in conn.execute("PRAGMA foreign_key_list(storage_assignments)").fetchall()
        }
        assert ("storage_id", "storage_units", "CASCADE") in assignment_fks

        availability_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(machine_availability)").fetchall()
        }
        assert {"machine_type", "tier", "owned", "online"}.issubset(availability_cols)
    finally:
        conn.close()


def test_connect_profile_does_not_backfill_storage_assignments_from_inventory(tmp_path):
    profile_path = tmp_path / "profile.db"

    conn = sqlite3.connect(profile_path)
    conn.execute(
        """
        CREATE TABLE inventory (
            item_id INTEGER PRIMARY KEY,
            qty_count REAL,
            qty_liters REAL
        )
        """
    )
    conn.execute("INSERT INTO inventory(item_id, qty_count, qty_liters) VALUES (?, ?, ?)", (1, 42, None))
    conn.commit()
    conn.close()

    profile_conn = db.connect_profile(profile_path)
    try:
        assignment_count = profile_conn.execute(
            "SELECT COUNT(1) AS c FROM storage_assignments"
        ).fetchone()["c"]
        assert assignment_count == 0

        main_storage = profile_conn.execute(
            "SELECT name FROM storage_units WHERE name='Main Storage'"
        ).fetchone()
        assert main_storage is not None
    finally:
        profile_conn.close()
