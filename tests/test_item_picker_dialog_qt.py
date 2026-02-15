import os
import sqlite3

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from ui_dialogs import ItemPickerDialog


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
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            key TEXT,
            display_name TEXT,
            kind TEXT,
            item_kind_id INTEGER,
            crafting_grid_size TEXT,
            is_machine INTEGER DEFAULT 0,
            machine_tier INTEGER
        );
        """
    )
    conn.execute("INSERT INTO items (id, key, display_name, kind) VALUES (1, 'chlorine', 'Chlorine', 'gas')")
    return conn


def test_item_picker_gas_has_no_no_kind_group_and_no_empty_categories() -> None:
    _get_app()

    class DummyApp:
        conn = _seed_conn()

    dialog = ItemPickerDialog(DummyApp())
    dialog.rebuild_tree()

    assert dialog.tree.topLevelItemCount() == 1
    gas_root = dialog.tree.topLevelItem(0)
    assert gas_root.text(0) == "Gases"
    assert gas_root.childCount() == 1
    assert gas_root.child(0).text(0) == "Chlorine"

    dialog.deleteLater()
