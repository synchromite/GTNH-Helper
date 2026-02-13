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
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            key TEXT,
            display_name TEXT
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
        "INSERT INTO items (id, key, display_name) VALUES (?, ?, ?)",
        [
            (1, "ingotIron", "Iron Ingot"),
            (2, "dustIron", "Iron Dust"),
            (3, "dustCopper", "Copper Dust"),
        ],
    )
    conn.executemany(
        "INSERT INTO recipe_lines (recipe_id, item_id, direction) VALUES (?, ?, ?)",
        [
            (100, 1, "out"),
            (100, 2, "in"),
            (200, 3, "out"),
        ],
    )
    return conn


def test_filter_recipes_by_item_name_matches_any_recipe_line() -> None:
    _get_app()

    class DummyApp:
        editor_enabled = False
        conn = _seed_conn()

    tab = RecipesTab(DummyApp())
    recipes = [{"id": 100}, {"id": 200}]

    filtered = tab._filter_recipes_by_item_name(recipes, "dust")

    assert [recipe["id"] for recipe in filtered] == [100, 200]
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
