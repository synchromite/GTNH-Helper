import sqlite3
from pathlib import Path

from services.db import ensure_schema, find_item_merge_conflicts, merge_db


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

    conflicts = find_item_merge_conflicts(dest_conn, src_path)
    mapping = {c["src_id"]: c["dest_id"] for c in conflicts}
    stats = merge_db(dest_conn, src_path, item_conflicts=mapping)

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


def test_merge_db_normalizes_kind_names(tmp_path: Path):
    dest_conn = _connect(":memory:")
    circuit_kind = dest_conn.execute(
        "SELECT id FROM item_kinds WHERE LOWER(name)=LOWER('Circuit')"
    ).fetchone()["id"]

    src_path = tmp_path / "src.db"
    src_conn = _connect(src_path)
    src_conn.execute("INSERT INTO item_kinds(name, sort_order, is_builtin) VALUES('Circuits', 70, 0)")
    src_kind_id = src_conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    src_conn.execute(
        "INSERT INTO items(key, display_name, kind, item_kind_id) VALUES(?,?,?,?)",
        ("test_circuit", "Test Circuit", "item", src_kind_id),
    )
    src_conn.commit()

    conflicts = find_item_merge_conflicts(dest_conn, src_path)
    mapping = {c["src_id"]: c["dest_id"] for c in conflicts}
    stats = merge_db(dest_conn, src_path, item_conflicts=mapping)

    assert stats["kinds_added"] == 0
    merged_item = dest_conn.execute(
        "SELECT item_kind_id FROM items WHERE key='test_circuit'"
    ).fetchone()
    assert merged_item["item_kind_id"] == circuit_kind
    assert dest_conn.execute(
        "SELECT id FROM item_kinds WHERE LOWER(name)=LOWER('Circuits')"
    ).fetchone() is None


def test_merge_db_keeps_distinct_kind_names(tmp_path: Path):
    dest_conn = _connect(":memory:")

    src_path = tmp_path / "src.db"
    src_conn = _connect(src_path)
    src_conn.execute(
        "INSERT INTO item_kinds(name, sort_order, is_builtin) VALUES('Circuit (Advanced)', 75, 0)"
    )
    src_conn.commit()

    conflicts = find_item_merge_conflicts(dest_conn, src_path)
    mapping = {c["src_id"]: c["dest_id"] for c in conflicts}
    stats = merge_db(dest_conn, src_path, item_conflicts=mapping)

    assert stats["kinds_added"] == 1
    assert dest_conn.execute(
        "SELECT id FROM item_kinds WHERE name='Circuit (Advanced)'"
    ).fetchone() is not None



def test_merge_db_needs_review_only_requires_material_for_material_kinds(tmp_path: Path):
    dest_conn = _connect(":memory:")

    src_path = tmp_path / "src.db"
    src_conn = _connect(src_path)
    component_kind = src_conn.execute(
        "SELECT id FROM item_kinds WHERE LOWER(name)=LOWER('Component')"
    ).fetchone()["id"]
    dust_kind = src_conn.execute(
        "SELECT id FROM item_kinds WHERE LOWER(name)=LOWER('Dust')"
    ).fetchone()["id"]
    src_conn.execute(
        "INSERT INTO items(key, display_name, kind, item_kind_id, material_id) VALUES(?,?,?,?,?)",
        ("component_no_material", "Generic Component", "item", component_kind, None),
    )
    src_conn.execute(
        "INSERT INTO items(key, display_name, kind, item_kind_id, material_id) VALUES(?,?,?,?,?)",
        ("dust_no_material", "Unknown Dust", "item", dust_kind, None),
    )
    src_conn.commit()

    stats = merge_db(dest_conn, src_path)

    assert stats["items_added"] == 2
    rows = {
        row["key"]: int(row["needs_review"])
        for row in dest_conn.execute(
            "SELECT key, needs_review FROM items WHERE key IN ('component_no_material', 'dust_no_material')"
        ).fetchall()
    }
    assert rows["component_no_material"] == 0
    assert rows["dust_no_material"] == 1
def test_merge_db_merges_close_recipe_names_on_match(tmp_path: Path):
    dest_conn = _connect(":memory:")
    widget_id = _insert_item(dest_conn, key="widget", name="Widget")
    dest_conn.execute("INSERT INTO recipes(name, method, duration_ticks) VALUES(?,?,?)", ("Make Widget", "crafting", 100))
    dest_recipe_id = dest_conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    dest_conn.execute(
        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_count) VALUES(?,?,?,?)",
        (dest_recipe_id, "out", widget_id, 1),
    )
    dest_conn.commit()

    src_path = tmp_path / "src.db"
    src_conn = _connect(src_path)
    src_widget_id = _insert_item(src_conn, key="widget_alt", name="Widget")
    src_conn.execute(
        "INSERT INTO recipes(name, method, duration_ticks) VALUES(?,?,?)",
        ("Make Widget!", "crafting", 100),
    )
    src_recipe_id = src_conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    src_conn.execute(
        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_count) VALUES(?,?,?,?)",
        (src_recipe_id, "out", src_widget_id, 1),
    )
    src_conn.commit()

    conflicts = find_item_merge_conflicts(dest_conn, src_path)
    mapping = {c["src_id"]: c["dest_id"] for c in conflicts}
    stats = merge_db(dest_conn, src_path, item_conflicts=mapping)

    assert stats["recipes_added"] == 0
    recipes = dest_conn.execute("SELECT id FROM recipes").fetchall()
    assert len(recipes) == 1


def test_merge_db_marks_recipe_duplicates_on_mismatch(tmp_path: Path):
    dest_conn = _connect(":memory:")
    widget_id = _insert_item(dest_conn, key="widget", name="Widget")
    dest_conn.execute("INSERT INTO recipes(name, method, duration_ticks) VALUES(?,?,?)", ("Make Widget", "crafting", 100))
    dest_recipe_id = dest_conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    dest_conn.execute(
        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_count) VALUES(?,?,?,?)",
        (dest_recipe_id, "out", widget_id, 1),
    )
    dest_conn.commit()

    src_path = tmp_path / "src.db"
    src_conn = _connect(src_path)
    src_widget_id = _insert_item(src_conn, key="widget_alt", name="Widget")
    src_conn.execute(
        "INSERT INTO recipes(name, method, duration_ticks) VALUES(?,?,?)",
        ("Make Widget!", "crafting", 120),
    )
    src_recipe_id = src_conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    src_conn.execute(
        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_count) VALUES(?,?,?,?)",
        (src_recipe_id, "out", src_widget_id, 1),
    )
    src_conn.commit()

    stats = merge_db(dest_conn, src_path)

    assert stats["recipes_added"] == 1
    dup_row = dest_conn.execute(
        "SELECT duplicate_of_recipe_id FROM recipes WHERE id!=?",
        (dest_recipe_id,),
    ).fetchone()
    assert dup_row["duplicate_of_recipe_id"] == dest_recipe_id
