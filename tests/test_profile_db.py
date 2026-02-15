import sqlite3

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
            "notes",
        }.issubset(storage_unit_cols)

        assignment_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(storage_assignments)").fetchall()
        }
        assert {"storage_id", "item_id", "qty_count", "qty_liters"}.issubset(assignment_cols)

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
