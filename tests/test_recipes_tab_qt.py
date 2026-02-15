import os
import sqlite3

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

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
        CREATE TABLE recipe_lines (
            id INTEGER PRIMARY KEY,
            recipe_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            direction TEXT
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
