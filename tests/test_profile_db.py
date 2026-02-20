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
        assert "storage_container_placements" in tables
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


def test_connect_profile_creates_machine_availability_version_triggers(tmp_path):
    profile_path = tmp_path / "profile.db"
    conn = db.connect_profile(profile_path)
    try:
        triggers = {
            row["name"]: row["sql"]
            for row in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger'")
        }

        expected = {
            "trg_machine_availability_version_insert": "AFTER INSERT",
            "trg_machine_availability_version_update": "AFTER UPDATE",
            "trg_machine_availability_version_delete": "AFTER DELETE",
        }
        for trigger_name, clause in expected.items():
            assert trigger_name in triggers
            trigger_sql = (triggers[trigger_name] or "").upper()
            assert clause in trigger_sql
            assert "UPDATE APP_SETTINGS" in trigger_sql
            assert "MACHINE_AVAILABILITY_VERSION" in trigger_sql
            assert "CAST(COALESCE(VALUE, '0') AS INTEGER) + 1" in trigger_sql
    finally:
        conn.close()


def test_machine_availability_version_increments_on_insert_update_delete(tmp_path):
    profile_path = tmp_path / "profile.db"
    conn = db.connect_profile(profile_path)
    try:
        def current_version() -> int:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key='machine_availability_version'"
            ).fetchone()
            assert row is not None
            return int(row["value"] or 0)

        v0 = current_version()

        conn.execute(
            "INSERT INTO machine_availability(machine_type, tier, owned, online) VALUES(?, ?, ?, ?)",
            ("macerator", "LV", 1, 1),
        )
        conn.commit()
        v1 = current_version()
        assert v1 == v0 + 1

        conn.execute(
            "UPDATE machine_availability SET online=? WHERE machine_type=? AND tier=?",
            (0, "macerator", "LV"),
        )
        conn.commit()
        v2 = current_version()
        assert v2 == v1 + 1

        conn.execute(
            "DELETE FROM machine_availability WHERE machine_type=? AND tier=?",
            ("macerator", "LV"),
        )
        conn.commit()
        v3 = current_version()
        assert v3 == v2 + 1
    finally:
        conn.close()
