from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from PySide6 import QtWidgets

from ui_dialogs import AddRecipeDialog, EditRecipeDialog
from services.db import ALL_TIERS


class _StatusBarStub:
    def showMessage(self, _message: str) -> None:
        return None


class _AppStub:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.status_bar = _StatusBarStub()

    def get_enabled_tiers(self):
        return ALL_TIERS

    def is_crafting_6x6_unlocked(self) -> bool:
        return True


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("Usage: tk_recipe_dialog_runner.py <add|edit> <db_path> [recipe_id]", file=sys.stderr)
        return 2
    dialog_kind = argv[1]
    db_path = Path(argv[2])
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        return 2
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    app = QtWidgets.QApplication([])
    stub = _AppStub(conn)
    try:
        if dialog_kind == "add":
            dialog = AddRecipeDialog(stub)
        elif dialog_kind == "edit":
            if len(argv) < 4:
                print("Missing recipe_id for edit dialog.", file=sys.stderr)
                return 2
            dialog = EditRecipeDialog(stub, int(argv[3]))
        else:
            print(f"Unknown dialog type: {dialog_kind}", file=sys.stderr)
            return 2
        dialog.exec()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
