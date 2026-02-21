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
            kind TEXT,
            is_storage_container INTEGER,
            storage_slot_count INTEGER,
            content_fluid_id INTEGER,
            content_qty_liters INTEGER
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO items(id, key, display_name, kind, is_storage_container, storage_slot_count, content_fluid_id, content_qty_liters)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "oak_chest", "Oak Chest", "item", 1, 27, None, None),
            (2, "diamond_chest", "Diamond Chest", "item", 1, 108, None, None),
            (3, "water", "Water", "fluid", 0, None, None, None),
            (4, "water_tank", "Water Tank", "item", 0, None, 3, 40000),
        ],
    )
    conn.commit()
    return conn


def _row_for_name(dialog: StorageContainerPlacementsDialog, name: str) -> int:
    for idx in range(dialog.table.rowCount()):
        item = dialog.table.item(idx, 0)
        if item is not None and item.text() == name:
            return idx
    raise AssertionError(f"row not found for {name}")


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


def test_dialog_rejects_mixed_container_storage_types(monkeypatch) -> None:
    _get_app()

    class DummyApp:
        def __init__(self) -> None:
            self.profile_conn = connect_profile(":memory:")
            self.conn = _content_conn()

    app_obj = DummyApp()
    main_storage_id = int(default_storage_id(app_obj.profile_conn) or 0)
    storage_id = create_storage_unit(app_obj.profile_conn, name="Mixed Storage")
    upsert_assignment(app_obj.profile_conn, storage_id=main_storage_id, item_id=1, qty_count=10, qty_liters=None)
    upsert_assignment(app_obj.profile_conn, storage_id=main_storage_id, item_id=4, qty_count=10, qty_liters=None)
    app_obj.profile_conn.commit()

    warnings: list[str] = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *_args: warnings.append(str(_args[2])) or QtWidgets.QMessageBox.StandardButton.Ok,
    )

    dialog = StorageContainerPlacementsDialog(app_obj, storage={"id": storage_id, "name": "Mixed Storage", "kind": "generic"})
    dialog.table.cellWidget(_row_for_name(dialog, "Oak Chest"), 2).setValue(1)
    dialog.table.cellWidget(_row_for_name(dialog, "Water Tank"), 2).setValue(1)

    dialog._on_save()

    assert warnings
    assert "one container storage type" in warnings[-1]

    dialog.deleteLater()


def test_dialog_sets_storage_kind_from_first_container_type() -> None:
    _get_app()

    class DummyApp:
        def __init__(self) -> None:
            self.profile_conn = connect_profile(":memory:")
            self.conn = _content_conn()

    app_obj = DummyApp()
    main_storage_id = int(default_storage_id(app_obj.profile_conn) or 0)
    storage_id = create_storage_unit(app_obj.profile_conn, name="Tank Storage", kind="generic")
    upsert_assignment(app_obj.profile_conn, storage_id=main_storage_id, item_id=4, qty_count=5, qty_liters=None)
    app_obj.profile_conn.commit()

    dialog = StorageContainerPlacementsDialog(app_obj, storage={"id": storage_id, "name": "Tank Storage", "kind": "generic"})
    dialog.table.cellWidget(_row_for_name(dialog, "Water Tank"), 2).setValue(2)

    dialog._on_save()

    row = app_obj.profile_conn.execute("SELECT kind FROM storage_units WHERE id=?", (storage_id,)).fetchone()
    assert row is not None
    assert row["kind"] == "fluid"

    dialog.deleteLater()
