import os
import sqlite3

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from ui_dialogs import StorageUnitDialog


def _get_app() -> QtWidgets.QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _content_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE items(
            id INTEGER PRIMARY KEY,
            key TEXT,
            display_name TEXT,
            is_storage_container INTEGER,
            storage_slot_count INTEGER,
            content_fluid_id INTEGER,
            content_qty_liters INTEGER
        )
        """
    )
    conn.execute(
        """
        INSERT INTO items(id, key, display_name, is_storage_container, storage_slot_count, content_fluid_id, content_qty_liters)
        VALUES(1, 'water_tank', 'Water Tank', 0, NULL, 999, 40000)
        """
    )
    conn.commit()
    return conn


def test_storage_unit_dialog_lists_fluid_containers_as_container_items() -> None:
    _get_app()

    class DummyApp:
        def __init__(self) -> None:
            self.conn = _content_conn()

    dialog = StorageUnitDialog(DummyApp())
    names = [dialog.container_item_combo.itemText(i) for i in range(dialog.container_item_combo.count())]

    assert "Water Tank" in names

    dialog.deleteLater()
