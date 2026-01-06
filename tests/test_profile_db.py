import sqlite3

import db


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

        inventory_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(inventory)").fetchall()
        }
        assert {"item_id", "qty_count", "qty_liters"}.issubset(inventory_cols)
    finally:
        conn.close()
