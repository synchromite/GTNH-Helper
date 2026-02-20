import os
import sqlite3

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from ui_tabs.recipes_tab_qt import RecipesTab


def _get_app() -> QtWidgets.QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _seed_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE item_kinds (
            id INTEGER PRIMARY KEY,
            name TEXT
        );
        CREATE TABLE materials (
            id INTEGER PRIMARY KEY,
            name TEXT
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            key TEXT,
            display_name TEXT,
            kind TEXT,
            item_kind_id INTEGER,
            material_id INTEGER
        );
        CREATE TABLE recipes (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            method TEXT,
            machine TEXT,
            machine_item_id INTEGER,
            grid_size TEXT,
            station_item_id INTEGER,
            tier TEXT,
            circuit INTEGER,
            duration_ticks INTEGER,
            eu_per_tick INTEGER,
            notes TEXT,
            duplicate_of_recipe_id INTEGER
        );
        CREATE TABLE recipe_lines (
            id INTEGER PRIMARY KEY,
            recipe_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            direction TEXT,
            FOREIGN KEY(recipe_id) REFERENCES recipes(id) ON DELETE CASCADE
        );
        """
    )
    conn.executemany(
        "INSERT INTO item_kinds (id, name) VALUES (?, ?)",
        [
            (1, "Ingot"),
            (2, "Dust"),
        ],
    )
    conn.executemany(
        "INSERT INTO materials (id, name) VALUES (?, ?)",
        [
            (1, "Iron"),
            (2, "Copper"),
        ],
    )
    conn.executemany(
        "INSERT INTO items (id, key, display_name, kind, item_kind_id, material_id) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, "ingotIron", "Iron Ingot", "item", 1, 1),
            (2, "dustIron", "Iron Dust", "item", 2, 1),
            (3, "dustCopper", "Copper Dust", "item", 2, 2),
            (4, "chlorine", "Chlorine", "gas", None, None),
        ],
    )
    conn.executemany(
        "INSERT INTO recipes (id, name, duplicate_of_recipe_id) VALUES (?, ?, ?)",
        [
            (100, "Iron Ingot", None),
            (200, "Copper Dust", None),
            (300, "Chlorine", None),
        ],
    )
    conn.executemany(
        "INSERT INTO recipe_lines (recipe_id, item_id, direction) VALUES (?, ?, ?)",
        [
            (100, 1, "out"),
            (100, 2, "in"),
            (200, 3, "out"),
            (300, 4, "out"),
        ],
    )
    return conn


def test_filter_recipes_by_item_name_matches_output_lines_only() -> None:
    _get_app()

    class DummyApp:
        editor_enabled = False
        conn = _seed_conn()

    tab = RecipesTab(DummyApp())
    recipes = [{"id": 100}, {"id": 200}]

    filtered = tab._filter_recipes_by_item_name(recipes, "dust")

    assert [recipe["id"] for recipe in filtered] == [200]
    tab.deleteLater()


def test_filter_recipes_by_item_name_matches_output_metadata_fields() -> None:
    _get_app()

    class DummyApp:
        editor_enabled = False
        conn = _seed_conn()

    tab = RecipesTab(DummyApp())
    recipes = [{"id": 100}, {"id": 200}]

    filtered = tab._filter_recipes_by_item_name(recipes, "ingot")

    assert [recipe["id"] for recipe in filtered] == [100]
    tab.deleteLater()



def test_render_recipes_gases_skip_no_kind_group() -> None:
    _get_app()

    class DummyApp:
        editor_enabled = False
        conn = _seed_conn()

    tab = RecipesTab(DummyApp())
    recipes = [{"id": 300, "name": "Chlorine", "duplicate_of_recipe_id": None}]

    tab.render_recipes(recipes)

    assert tab.recipe_tree.topLevelItemCount() == 1
    gases_node = tab.recipe_tree.topLevelItem(0)
    assert gases_node.text(0) == "Gases"
    assert gases_node.childCount() == 1
    assert gases_node.child(0).text(0) == "Chlorine"

    tab.deleteLater()

def test_filter_recipes_by_item_name_keeps_all_for_blank_search() -> None:
    _get_app()

    class DummyApp:
        editor_enabled = False
        conn = _seed_conn()

    tab = RecipesTab(DummyApp())
    recipes = [{"id": 100}, {"id": 200}]

    filtered = tab._filter_recipes_by_item_name(recipes, "   ")

    assert [recipe["id"] for recipe in filtered] == [100, 200]
    tab.deleteLater()


def test_format_recipe_details_includes_notes(monkeypatch) -> None:
    _get_app()

    class DummyApp:
        editor_enabled = False
        conn = object()

    tab = RecipesTab(DummyApp())

    monkeypatch.setattr("ui_tabs.recipes_tab_qt.fetch_recipe_lines", lambda _conn, _recipe_id: [
        {
            "direction": "in",
            "name": "Iron Dust",
            "qty_count": 1,
            "qty_liters": None,
            "chance_percent": None,
            "consumption_chance": None,
            "output_slot_index": None,
            "input_slot_index": None,
        },
        {
            "direction": "out",
            "name": "Iron Ingot",
            "qty_count": 1,
            "qty_liters": None,
            "chance_percent": None,
            "consumption_chance": None,
            "output_slot_index": None,
            "input_slot_index": None,
        },
    ])
    monkeypatch.setattr("ui_tabs.recipes_tab_qt.fetch_machine_output_slots", lambda _conn, _machine_item_id: None)

    text = tab._format_recipe_details(
        {
            "id": 100,
            "name": "Iron Ingot",
            "method": "machine",
            "machine": "Furnace",
            "machine_item_id": None,
            "grid_size": None,
            "station_item_id": None,
            "tier": None,
            "circuit": None,
            "duration_ticks": None,
            "eu_per_tick": None,
            "notes": "Use rich oxygen mix",
        },
        index=1,
    )

    assert "Notes: Use rich oxygen mix" in text
    tab.deleteLater()


def test_delete_selected_recipe_deletes_canonical_and_variants(monkeypatch) -> None:
    _get_app()

    class DummyStatusBar:
        def __init__(self) -> None:
            self.message = ""

        def showMessage(self, message: str) -> None:
            self.message = message

    class DummyApp:
        editor_enabled = True
        conn = _seed_conn()

        def __init__(self) -> None:
            self.status_bar = DummyStatusBar()
            self.refreshed = False

        def refresh_recipes(self) -> None:
            self.refreshed = True

    app = DummyApp()
    app.conn.executemany(
        "INSERT INTO recipes (id, name, duplicate_of_recipe_id) VALUES (?, ?, ?)",
        [
            (100, "Main Output", None),
            (101, "Secondary Output", 100),
        ],
    )
    app.conn.executemany(
        "INSERT INTO recipe_lines (id, recipe_id, item_id, direction) VALUES (?, ?, ?, ?)",
        [
            (1, 100, 1, "out"),
            (2, 101, 3, "out"),
        ],
    )

    tab = RecipesTab(app)
    monkeypatch.setattr(tab, "_select_recipe_for_current_item", lambda: 100)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *args, **kwargs: QtWidgets.QMessageBox.StandardButton.Yes,
    )

    tab.delete_selected_recipe()

    assert app.conn.execute("SELECT COUNT(*) AS c FROM recipes").fetchone()["c"] == 0
    assert app.conn.execute("SELECT COUNT(*) AS c FROM recipe_lines").fetchone()["c"] == 0
    assert app.refreshed is True
    tab.deleteLater()


def test_delete_selected_recipe_deletes_only_selected_variant(monkeypatch) -> None:
    _get_app()

    class DummyStatusBar:
        def __init__(self) -> None:
            self.message = ""

        def showMessage(self, message: str) -> None:
            self.message = message

    class DummyApp:
        editor_enabled = True
        conn = _seed_conn()

        def __init__(self) -> None:
            self.status_bar = DummyStatusBar()
            self.refreshed = False

        def refresh_recipes(self) -> None:
            self.refreshed = True

    app = DummyApp()
    app.conn.executemany(
        "INSERT INTO recipes (id, name, duplicate_of_recipe_id) VALUES (?, ?, ?)",
        [
            (100, "Main Output", None),
            (101, "Secondary Output", 100),
        ],
    )
    app.conn.executemany(
        "INSERT INTO recipe_lines (id, recipe_id, item_id, direction) VALUES (?, ?, ?, ?)",
        [
            (1, 100, 1, "out"),
            (2, 101, 3, "out"),
        ],
    )

    tab = RecipesTab(app)
    monkeypatch.setattr(tab, "_select_recipe_for_current_item", lambda: 101)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *args, **kwargs: QtWidgets.QMessageBox.StandardButton.Yes,
    )

    tab.delete_selected_recipe()

    rows = app.conn.execute(
        "SELECT id, duplicate_of_recipe_id FROM recipes ORDER BY id"
    ).fetchall()
    assert [(row["id"], row["duplicate_of_recipe_id"]) for row in rows] == [(100, None)]
    assert app.conn.execute("SELECT COUNT(*) AS c FROM recipe_lines WHERE recipe_id=100").fetchone()["c"] == 1
    assert app.conn.execute("SELECT COUNT(*) AS c FROM recipe_lines WHERE recipe_id=101").fetchone()["c"] == 0
    assert app.refreshed is True
    tab.deleteLater()
