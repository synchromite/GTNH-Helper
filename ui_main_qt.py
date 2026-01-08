#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from PyQt5 import QtWidgets

from services.db import DEFAULT_DB_PATH
from services.db_lifecycle import DbLifecycle
from services.items import fetch_items
from ui_tabs.items_tab import ItemsTab


class _QtStatus:
    def __init__(self, status_bar: QtWidgets.QStatusBar):
        self._status_bar = status_bar

    def set(self, text: str) -> None:
        self._status_bar.showMessage(text)


class AppQt(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GTNH Helper")
        self.resize(1100, 700)

        self.editor_enabled = self._detect_editor_enabled()

        self.db = DbLifecycle(editor_enabled=self.editor_enabled, db_path=DEFAULT_DB_PATH)
        self._sync_db_handles()

        self.status = _QtStatus(self.statusBar())

        self.items: list = []

        self.tabs = QtWidgets.QTabWidget(self)
        self.setCentralWidget(self.tabs)

        self.items_tab = ItemsTab(self.tabs, self)

        self.refresh_items()

    def _detect_editor_enabled(self) -> bool:
        try:
            here = Path(__file__).resolve().parent
            return (here / ".enable_editor").exists()
        except Exception:
            return False

    def _sync_db_handles(self) -> None:
        self.db_path = self.db.db_path
        self.profile_db_path = self.db.profile_db_path
        self.conn = self.db.conn
        self.profile_conn = self.db.profile_conn

    def refresh_items(self) -> None:
        self.items = fetch_items(self.conn)
        if self.items_tab is not None:
            self.items_tab.render_items(self.items)


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    window = AppQt()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
