import sqlite3
from pathlib import Path

from services.db import ensure_schema, merge_db


def _connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


def _insert_item(conn: sqlite3.Connection, *, key: str, name: str | None, is_base: int = 0):
    conn.execute(
        "INSERT INTO items(key, display_name, kind, is_base) VALUES(?,?,?,?)",
        (key, name, "item", is_base),
    )
    return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def test_merge_db_imports_items_and_recipes(tmp_path: Path):
    dest_conn = _connect(":memory:")
    dest_conn.execute("INSERT INTO item_kinds(name, sort_order, is_builtin) VALUES('Custom', 1, 0)")
    existing_id = _insert_item(dest_conn, key="iron", name=None, is_base=0)

    src_path = tmp_path / "src.db"
    src_conn = _connect(src_path)
    src_conn.execute("INSERT INTO item_kinds(name, sort_order, is_builtin) VALUES('Widget', 5, 0)")

    iron_id = _insert_item(src_conn, key="iron", name="Iron Ingot", is_base=1)
    widget_id = _insert_item(src_conn, key="widget", name="Widget", is_base=0)

    src_conn.execute("INSERT INTO recipes(name, method) VALUES('Make Widget', 'crafting')")
    recipe_id = src_conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    src_conn.execute(
        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_count) VALUES(?,?,?,?)",
        (recipe_id, "in", iron_id, 2),
    )
    src_conn.execute(
        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_count) VALUES(?,?,?,?)",
        (recipe_id, "out", widget_id, 1),
    )
    src_conn.commit()

    stats = merge_db(dest_conn, src_path)

    assert stats["kinds_added"] == 1
    assert stats["items_added"] == 1
    assert stats["items_updated"] == 1
    assert stats["recipes_added"] == 1
    assert stats["lines_added"] == 2

    merged_iron = dest_conn.execute("SELECT display_name, is_base FROM items WHERE id=?", (existing_id,)).fetchone()
    assert merged_iron["display_name"] == "Iron Ingot"
    assert merged_iron["is_base"] == 1

    widget = dest_conn.execute("SELECT id FROM items WHERE key='widget'").fetchone()
    assert widget is not None

    recipe = dest_conn.execute("SELECT id FROM recipes WHERE name='Make Widget'").fetchone()
    assert recipe is not None

    lines = dest_conn.execute("SELECT item_id FROM recipe_lines WHERE recipe_id=?", (recipe["id"],)).fetchall()
    item_ids = {row["item_id"] for row in lines}
    assert widget["id"] in item_ids
