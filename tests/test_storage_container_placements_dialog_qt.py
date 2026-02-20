import os
import sqlite3

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from services.db import connect_profile
from services.storage import create_storage_unit, default_storage_id, get_assignment, upsert_assignment
from ui_dialogs import StorageContainerPlacementsDialog


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
            storage_slot_count INTEGER
        )
        """
    )
    conn.execute(
        """
        INSERT INTO items(id, key, display_name, is_storage_container, storage_slot_count)
        VALUES(1, 'oak_chest', 'Oak Chest', 1, 27)
        """
    )
    conn.commit()
    return conn


def test_dialog_save_does_not_convert_secondary_placements_into_inventory() -> None:
    _get_app()

    class DummyApp:
        def __init__(self) -> None:
            self.profile_conn = connect_profile(":memory:")
            self.conn = _content_conn()

    app_obj = DummyApp()
    main_storage_id = int(default_storage_id(app_obj.profile_conn) or 0)
    ore_storage_id = create_storage_unit(app_obj.profile_conn, name="Ore Storage")
    upsert_assignment(app_obj.profile_conn, storage_id=main_storage_id, item_id=1, qty_count=10, qty_liters=None)
    app_obj.profile_conn.commit()

    dialog = StorageContainerPlacementsDialog(app_obj, storage={"id": ore_storage_id, "name": "Ore Storage"})
    spin = dialog.table.cellWidget(0, 2)
    assert isinstance(spin, QtWidgets.QSpinBox)
    spin.setValue(5)

    dialog._on_save()

    assert get_assignment(app_obj.profile_conn, storage_id=main_storage_id, item_id=1)["qty_count"] == 10
    assert get_assignment(app_obj.profile_conn, storage_id=ore_storage_id, item_id=1) is None

    dialog.deleteLater()


def test_dialog_save_does_not_overwrite_main_storage_owned_count() -> None:
    _get_app()

    class DummyApp:
        def __init__(self) -> None:
            self.profile_conn = connect_profile(":memory:")
            self.conn = _content_conn()

    app_obj = DummyApp()
    main_storage_id = int(default_storage_id(app_obj.profile_conn) or 0)
    upsert_assignment(app_obj.profile_conn, storage_id=main_storage_id, item_id=1, qty_count=10, qty_liters=None)
    app_obj.profile_conn.commit()

    dialog = StorageContainerPlacementsDialog(app_obj, storage={"id": main_storage_id, "name": "Main Storage"})
    spin = dialog.table.cellWidget(0, 2)
    assert isinstance(spin, QtWidgets.QSpinBox)
    spin.setValue(5)

    dialog._on_save()

    main_assignment = get_assignment(app_obj.profile_conn, storage_id=main_storage_id, item_id=1)
    assert main_assignment is not None
    assert main_assignment["qty_count"] == 10

    dialog.deleteLater()
