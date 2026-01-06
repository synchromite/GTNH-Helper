import sqlite3

import db


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def test_ensure_schema_creates_tables_and_defaults():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    db.ensure_schema(conn)

    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "items" in tables
    assert "item_kinds" in tables
    assert "recipes" in tables
    assert "recipe_lines" in tables
    assert "app_settings" in tables

    item_columns = _table_columns(conn, "items")
    for column in (
        "item_kind_id",
        "is_machine",
        "machine_tier",
        "machine_input_slots",
        "machine_output_slots",
        "machine_storage_slots",
        "machine_power_slots",
        "machine_circuit_slots",
        "machine_input_tanks",
        "machine_input_tank_capacity_l",
        "machine_output_tanks",
        "machine_output_tank_capacity_l",
    ):
        assert column in item_columns

    recipe_columns = _table_columns(conn, "recipes")
    for column in ("method", "grid_size", "station_item_id", "machine_item_id"):
        assert column in recipe_columns

    machine_kind = conn.execute(
        "SELECT id FROM item_kinds WHERE LOWER(name)=LOWER('Machine')"
    ).fetchone()
    assert machine_kind is not None
