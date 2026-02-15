import os
import sqlite3

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from services.db import ensure_schema
from ui_dialogs import MaterialManagerDialog


def _get_app() -> QtWidgets.QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_add_row_focuses_name_cell_for_immediate_edit() -> None:
    app = _get_app()

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    class DummyApp:
        def __init__(self, db_conn):
            self.conn = db_conn

    dialog = MaterialManagerDialog(DummyApp(conn))

    starting_rows = dialog.table.rowCount()
    dialog.add_row_btn.click()
    app.processEvents()

    assert dialog.table.rowCount() == starting_rows + 1
    assert dialog.table.currentRow() == dialog.table.rowCount() - 1
    assert dialog.table.currentColumn() == 0

    dialog.close()
    dialog.deleteLater()
    conn.close()
