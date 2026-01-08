from __future__ import annotations

import sqlite3
import sys
import tkinter as tk
from pathlib import Path

from ui_dialogs import AddItemDialog, EditItemDialog


class _StatusStub:
    def set(self, _message: str) -> None:
        return None


def _build_root(db_path: Path) -> tk.Tk:
    root = tk.Tk()
    root.geometry("1x1+0+0")
    root.overrideredirect(True)
    try:
        root.attributes("-alpha", 0.0)
    except Exception:
        pass
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    root.conn = conn
    root.status = _StatusStub()
    return root


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("Usage: tk_item_dialog_runner.py <add|edit> <db_path> [item_id]", file=sys.stderr)
        return 2
    dialog_kind = argv[1]
    db_path = Path(argv[2])
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        return 2
    root = _build_root(db_path)
    try:
        if dialog_kind == "add":
            dialog = AddItemDialog(root)
        elif dialog_kind == "edit":
            if len(argv) < 4:
                print("Missing item_id for edit dialog.", file=sys.stderr)
                return 2
            dialog = EditItemDialog(root, int(argv[3]))
        else:
            print(f"Unknown dialog type: {dialog_kind}", file=sys.stderr)
            return 2
        try:
            dialog.deiconify()
            dialog.lift()
            dialog.focus_force()
        except Exception:
            pass
        root.wait_window(dialog)
    finally:
        try:
            root.conn.close()
        except Exception:
            pass
        root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
