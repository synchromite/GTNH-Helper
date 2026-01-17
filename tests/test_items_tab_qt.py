import os
import sqlite3

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6 import QtCore

from ui_tabs.items_tab_qt import ItemsTab


def _get_app() -> QtWidgets.QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _make_item_row() -> sqlite3.Row:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT 1 AS id, 'Test Item' AS name, 'item' AS kind, 'Machine' AS item_kind_name, "
        "NULL AS material_name, 1 AS is_base, 1 AS is_machine, 2 AS machine_tier, 2 AS machine_input_slots, "
        "1 AS machine_output_slots, 0 AS machine_storage_slots, 0 AS machine_power_slots, "
        "0 AS machine_circuit_slots, 0 AS machine_input_tanks, 0 AS machine_input_tank_capacity_l, "
        "0 AS machine_output_tanks, 0 AS machine_output_tank_capacity_l"
    ).fetchone()
    conn.close()
    return row


def test_render_items_handles_sqlite_rows_and_preserves_selection() -> None:
    app = _get_app()

    class DummyApp:
        editor_enabled = False

    tab = ItemsTab(DummyApp())
    row = _make_item_row()
    tab.render_items([row])
    iterator = QtWidgets.QTreeWidgetItemIterator(tab.item_tree)
    selected = None
    while iterator.value():
        item = iterator.value()
        if item.childCount() == 0:
            selected = item
            break
        iterator += 1
    assert selected is not None
    tab.item_tree.setCurrentItem(selected)
    app.processEvents()
    tab.render_items([row])
    app.processEvents()

    current = tab.item_tree.currentItem()
    assert current is not None
    assert current.data(0, QtCore.Qt.UserRole) == row["id"]
    assert "Test Item" in tab.item_details.toPlainText()

    tab.deleteLater()
