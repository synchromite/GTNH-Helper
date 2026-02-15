import os
import sqlite3

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from services.db import connect_profile
from ui_tabs.inventory_tab import InventoryTab


def _get_app() -> QtWidgets.QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _item_row(conn: sqlite3.Connection, *, name: str) -> sqlite3.Row:
    return conn.execute(
        "SELECT 1 AS id, ? AS name, 'item' AS kind, 'plate' AS item_kind_name, 'iron' AS material_name, "
        "NULL AS machine_type, NULL AS machine_tier, 0 AS is_machine, NULL AS crafting_grid_size",
        (name,),
    ).fetchone()


def test_inventory_search_expands_all_groups_for_matching_items() -> None:
    app = _get_app()

    class DummyStatusBar:
        def showMessage(self, _msg: str) -> None:
            return None

    class DummyApp:
        def __init__(self) -> None:
            self.profile_conn = connect_profile(":memory:")
            self.status_bar = DummyStatusBar()

        def notify_inventory_change(self) -> None:
            return None

    tab = InventoryTab(DummyApp())
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    row = _item_row(conn, name="Refined Iron Plate")

    tab.render_items([row])
    tab.search_entry.setText("refined")
    app.processEvents()

    tree = tab.inventory_trees["All"]
    kind_item = tree.topLevelItem(0)
    assert kind_item is not None
    item_kind_item = kind_item.child(0)
    assert item_kind_item is not None
    material_item = item_kind_item.child(0)
    assert material_item is not None
    assert material_item.childCount() == 1

    assert tree.isItemExpanded(kind_item)
    assert tree.isItemExpanded(item_kind_item)
    assert tree.isItemExpanded(material_item)

    tab.deleteLater()
    conn.close()


def test_inventory_save_writes_storage_assignment_only() -> None:
    app = _get_app()

    class DummyStatusBar:
        def showMessage(self, _msg: str) -> None:
            return None

    class DummyApp:
        def __init__(self) -> None:
            self.profile_conn = connect_profile(":memory:")
            self.status_bar = DummyStatusBar()

        def notify_inventory_change(self) -> None:
            return None

    tab = InventoryTab(DummyApp())
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    row = _item_row(conn, name="Refined Iron Plate")

    tab.render_items([row])
    tab.storage_selector.setCurrentIndex(1)
    tree = tab.inventory_trees["All"]
    kind_item = tree.topLevelItem(0)
    item_kind_item = kind_item.child(0)
    material_item = item_kind_item.child(0)
    leaf = material_item.child(0)
    tree.setCurrentItem(leaf)

    tab.inventory_qty_entry.setText("12")
    tab.save_inventory_item()
    app.processEvents()

    assignment = tab.app.profile_conn.execute(
        "SELECT qty_count, qty_liters FROM storage_assignments WHERE storage_id=? AND item_id=?",
        (tab.app.profile_conn.execute("SELECT id FROM storage_units WHERE name='Main Storage'").fetchone()["id"], 1),
    ).fetchone()
    legacy = tab.app.profile_conn.execute("SELECT qty_count, qty_liters FROM inventory WHERE item_id=?", (1,)).fetchone()

    assert assignment is not None
    assert assignment["qty_count"] == 12
    assert assignment["qty_liters"] is None
    assert legacy is None

    tab.deleteLater()
    conn.close()


def test_inventory_aggregate_mode_is_read_only() -> None:
    app = _get_app()

    class DummyStatusBar:
        def showMessage(self, _msg: str) -> None:
            return None

    class DummyApp:
        def __init__(self) -> None:
            self.profile_conn = connect_profile(":memory:")
            self.status_bar = DummyStatusBar()

        def notify_inventory_change(self) -> None:
            return None

        def list_storage_units(self):
            return [{"id": 1, "name": "Main Storage"}]

        def get_active_storage_id(self):
            return 1

        def set_active_storage_id(self, _storage_id: int) -> None:
            return None

    tab = InventoryTab(DummyApp())
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    row = _item_row(conn, name="Refined Iron Plate")

    tab.render_items([row])
    tab.storage_selector.setCurrentIndex(0)
    app.processEvents()

    assert tab.inventory_qty_entry.isReadOnly()
    assert not tab.btn_save.isEnabled()
    assert not tab.btn_clear.isEnabled()

    tab.deleteLater()
    conn.close()


def test_inventory_summary_panel_shows_selected_and_aggregate_totals() -> None:
    app = _get_app()

    class DummyStatusBar:
        def showMessage(self, _msg: str) -> None:
            return None

    class DummyApp:
        def __init__(self) -> None:
            self.profile_conn = connect_profile(":memory:")
            self.status_bar = DummyStatusBar()

        def notify_inventory_change(self) -> None:
            return None

    tab = InventoryTab(DummyApp())
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    row = _item_row(conn, name="Refined Iron Plate")

    tab.app.profile_conn.execute(
        "INSERT INTO storage_units(name) VALUES('Overflow')"
    )
    overflow_id = tab.app.profile_conn.execute(
        "SELECT id FROM storage_units WHERE name='Overflow'"
    ).fetchone()["id"]
    tab.app.profile_conn.execute(
        "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters) VALUES(?, ?, ?, ?)",
        (overflow_id, 1, 5, None),
    )
    tab.app.profile_conn.commit()

    tab.render_items([row])
    tab.storage_selector.setCurrentIndex(2)
    app.processEvents()

    text = tab.storage_totals_label.text()
    assert "Selected storage" in text
    assert "Aggregate" in text
    assert "5 count" in text

    tab.deleteLater()
    conn.close()
