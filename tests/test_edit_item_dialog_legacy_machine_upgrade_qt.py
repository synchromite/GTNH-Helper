import os
import sqlite3

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from services.db import ensure_schema
from ui_dialogs import EditItemDialog


def _get_app() -> QtWidgets.QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class _DummyStatusBar:
    def showMessage(self, _message: str) -> None:
        return


class _DummyApp:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.status_bar = _DummyStatusBar()

    def get_all_tiers(self) -> list[str]:
        return ["ULV", "LV", "MV", "HV"]

    def get_enabled_tiers(self) -> list[str]:
        return ["ULV", "LV", "MV", "HV"]


def test_edit_dialog_upgrades_legacy_machine_kind_and_preserves_metadata() -> None:
    _get_app()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    conn.execute(
        """
        INSERT INTO items(
            key, display_name, kind, is_base, is_machine,
            machine_type, machine_tier, is_multiblock
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        ("legacy_lathe", "Legacy Lathe", "item", 0, 1, "Lathe", "LV", 1),
    )
    item_id = int(conn.execute("SELECT id FROM items WHERE key='legacy_lathe'").fetchone()["id"])
    app = _DummyApp(conn)

    dialog = EditItemDialog(app, item_id)

    assert dialog._current_kind_value() == "machine"
    assert dialog.machine_type_combo.currentText() == "Lathe"
    assert dialog.tier_combo.currentText() == "LV"

    dialog.display_name_edit.setText("Legacy Lathe Mk2")
    dialog.save()

    saved = conn.execute(
        "SELECT kind, is_machine, machine_type, machine_tier, is_multiblock, display_name FROM items WHERE id=?",
        (item_id,),
    ).fetchone()

    assert saved is not None
    assert saved["kind"] == "machine"
    assert saved["is_machine"] == 1
    assert saved["machine_type"] == "Lathe"
    assert saved["machine_tier"] == "LV"
    assert saved["is_multiblock"] == 1
    assert saved["display_name"] == "Legacy Lathe Mk2"

    dialog.deleteLater()
    conn.close()


def test_edit_dialog_upgrades_legacy_machine_when_kind_is_missing() -> None:
    _get_app()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    conn.execute(
        """
        INSERT INTO items(
            key, display_name, kind, is_base, is_machine,
            machine_type, machine_tier, is_multiblock
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        ("legacy_cutter", "Legacy Cutter", None, 0, 1, "Cutter", "MV", 0),
    )
    item_id = int(conn.execute("SELECT id FROM items WHERE key='legacy_cutter'").fetchone()["id"])
    app = _DummyApp(conn)

    dialog = EditItemDialog(app, item_id)

    assert dialog._current_kind_value() == "machine"
    assert dialog.machine_type_combo.currentText() == "Cutter"
    assert dialog.tier_combo.currentText() == "MV"

    dialog.save()

    saved = conn.execute(
        "SELECT kind, is_machine, machine_type, machine_tier FROM items WHERE id=?",
        (item_id,),
    ).fetchone()

    assert saved is not None
    assert saved["kind"] == "machine"
    assert saved["is_machine"] == 1
    assert saved["machine_type"] == "Cutter"
    assert saved["machine_tier"] == "MV"

    dialog.deleteLater()
    conn.close()


def test_edit_dialog_keeps_valid_fluid_kind_even_with_machine_flag() -> None:
    _get_app()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    conn.execute(
        """
        INSERT INTO items(
            key, display_name, kind, is_base, is_machine,
            machine_type, machine_tier
        ) VALUES(?,?,?,?,?,?,?)
        """,
        ("buggy_fluid", "Buggy Fluid", "fluid", 0, 1, "Mixer", "HV"),
    )
    item_id = int(conn.execute("SELECT id FROM items WHERE key='buggy_fluid'").fetchone()["id"])
    app = _DummyApp(conn)

    dialog = EditItemDialog(app, item_id)

    assert dialog._current_kind_value() == "fluid"

    dialog.display_name_edit.setText("Buggy Fluid Updated")
    dialog.save()

    saved = conn.execute(
        "SELECT kind, is_machine, machine_type, machine_tier, display_name FROM items WHERE id=?",
        (item_id,),
    ).fetchone()

    assert saved is not None
    assert saved["kind"] == "fluid"
    assert saved["is_machine"] == 0
    assert saved["machine_type"] is None
    assert saved["machine_tier"] is None
    assert saved["display_name"] == "Buggy Fluid Updated"

    dialog.deleteLater()
    conn.close()
