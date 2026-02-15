import sqlite3
import pytest

from services import db
from services import materials


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
    assert "machine_metadata" in tables
    assert "materials" in tables

    item_columns = _table_columns(conn, "items")
    for column in (
        "item_kind_id",
        "material_id",
        "is_machine",
        "machine_tier",
        "machine_type",
        "content_fluid_id",
        "content_qty_liters",
        "needs_review",
    ):
        assert column in item_columns

    recipe_columns = _table_columns(conn, "recipes")
    for column in ("method", "grid_size", "station_item_id", "machine_item_id"):
        assert column in recipe_columns

    metadata_columns = _table_columns(conn, "machine_metadata")
    for column in (
        "machine_type",
        "tier",
        "machine_name",
        "input_slots",
        "output_slots",
        "byproduct_slots",
        "storage_slots",
        "power_slots",
        "circuit_slots",
        "input_tanks",
        "input_tank_capacity_l",
        "output_tanks",
        "output_tank_capacity_l",
    ):
        assert column in metadata_columns

    machine_kind = conn.execute(
        "SELECT id FROM item_kinds WHERE LOWER(name)=LOWER('Machine')"
    ).fetchone()
    assert machine_kind is not None
    
    lines_columns = _table_columns(conn, "recipe_lines")
    for column in ("chance_percent", "consumption_chance", "output_slot_index"):
        assert column in lines_columns

def test_materials_crud():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.ensure_schema(conn)

    material_id = materials.add_material(conn, "Iron", "magnetic")
    row = conn.execute("SELECT name, attributes FROM materials WHERE id=?", (material_id,)).fetchone()
    assert row["name"] == "Iron"
    assert row["attributes"] == "magnetic"

    materials.update_material(conn, material_id, "Iron", "ferrous")
    updated = conn.execute("SELECT attributes FROM materials WHERE id=?", (material_id,)).fetchone()
    assert updated["attributes"] == "ferrous"

    materials.delete_material(conn, material_id)
    missing = conn.execute("SELECT 1 FROM materials WHERE id=?", (material_id,)).fetchone()
    assert missing is None


def test_connect_read_only_applies_schema_migrations(tmp_path):
    db_path = tmp_path / "legacy.db"

    legacy = sqlite3.connect(db_path)
    legacy.execute(
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL,
            is_base INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    legacy.execute("INSERT INTO items(key, kind, is_base) VALUES('foo', 'item', 0)")
    legacy.commit()
    legacy.close()

    conn = db.connect(db_path, read_only=True)
    try:
        # Regression check: old DBs must be migrated even in client mode.
        cols = _table_columns(conn, "items")
        assert "needs_review" in cols

        query_only = conn.execute("PRAGMA query_only").fetchone()[0]
        assert query_only == 1

        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO items(key, kind, is_base) VALUES('bar', 'item', 0)")
    finally:
        conn.close()
