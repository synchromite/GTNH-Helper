import os
import sqlite3

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from services.db import ALL_TIERS, ensure_schema
from ui_dialogs import AddItemDialog, AddRecipeDialog, EditRecipeDialog


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
        self.recipe_focus_id = None

    def get_all_tiers(self) -> list[str]:
        return list(ALL_TIERS)

    def get_enabled_tiers(self) -> list[str]:
        return list(ALL_TIERS)

    def refresh_items(self) -> None:
        return

    def refresh_recipes(self) -> None:
        return


def _insert_machine_metadata(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO machine_metadata(
            machine_type, tier, input_slots, output_slots,
            input_tanks, output_tanks
        ) VALUES(?,?,?,?,?,?)
        """,
        ("Lathe", "LV", 1, 1, 0, 0),
    )
    conn.commit()


def _add_item(app: _DummyApp, name: str, *, kind: str = "item") -> int:
    qt_app = _get_app()
    dialog = AddItemDialog(app)
    dialog.show()
    qt_app.processEvents()
    dialog.display_name_edit.setText(name)
    dialog.kind_combo.setCurrentText(kind)
    dialog._on_high_level_kind_changed()
    if kind == "machine":
        dialog.machine_type_combo.setCurrentText("Lathe")
        tier_index = dialog.tier_combo.findText("LV")
        if tier_index == -1:
            dialog.tier_combo.addItem("LV")
            tier_index = dialog.tier_combo.findText("LV")
        assert tier_index != -1
        dialog.tier_combo.setCurrentIndex(tier_index)
    qt_app.processEvents()
    dialog.save()
    row = app.conn.execute(
        "SELECT id FROM items WHERE COALESCE(display_name, key)=?",
        (name,),
    ).fetchone()
    assert row is not None, f"Expected item '{name}' to be saved."
    dialog.deleteLater()
    return int(row["id"])


def test_qa_recipe_flow_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    def _unexpected_dialog(*_args, **_kwargs):
        raise AssertionError("Unexpected modal dialog in QA smoke test.")

    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", _unexpected_dialog)
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", _unexpected_dialog)
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *_args, **_kwargs: QtWidgets.QMessageBox.StandardButton.Yes)
    _get_app()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    _insert_machine_metadata(conn)
    app = _DummyApp(conn)

    machine_id = _add_item(app, "Basic Lathe", kind="machine")
    ingot_id = _add_item(app, "Iron Ingot")
    rod_id = _add_item(app, "Iron Rod")

    dialog = AddRecipeDialog(app)
    dialog.name_edit.setText("Iron Rod")
    dialog.name_item_id = rod_id
    dialog.method_combo.setCurrentText("Machine")
    dialog.machine_edit.setText("Basic Lathe")
    dialog.machine_item_id = machine_id
    dialog.inputs = [
        {
            "item_id": ingot_id,
            "name": "Iron Ingot",
            "kind": "item",
            "qty_count": 1,
            "qty_liters": None,
        }
    ]
    dialog.outputs = [
        {
            "item_id": rod_id,
            "name": "Iron Rod",
            "kind": "item",
            "qty_count": 1,
            "qty_liters": None,
        }
    ]
    dialog.save()
    dialog.deleteLater()

    recipe = conn.execute("SELECT id FROM recipes WHERE name=?", ("Iron Rod",)).fetchone()
    assert recipe is not None

    lines = conn.execute(
        "SELECT direction, item_id FROM recipe_lines WHERE recipe_id=? ORDER BY direction",
        (recipe["id"],),
    ).fetchall()
    assert [(row["direction"], row["item_id"]) for row in lines] == [
        ("in", ingot_id),
        ("out", rod_id),
    ]
    conn.close()


def test_edit_recipe_variant_save_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[tuple[str, str]] = []

    def _capture_warning(_parent, title: str, text: str):
        warnings.append((title, text))
        return QtWidgets.QMessageBox.StandardButton.Ok

    def _unexpected_dialog(*_args, **_kwargs):
        raise AssertionError("Unexpected modal dialog in variant save guard test.")

    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", _capture_warning)
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", _unexpected_dialog)
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *_args, **_kwargs: QtWidgets.QMessageBox.StandardButton.Yes)

    _get_app()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    app = _DummyApp(conn)

    item_row = conn.execute(
        "INSERT INTO items(key, display_name, kind) VALUES(?, ?, ?)",
        ("item.test", "Test Item", "item"),
    )
    item_id = int(item_row.lastrowid)
    canonical_recipe_id = int(
        conn.execute(
            "INSERT INTO recipes(name, method) VALUES(?, ?)",
            ("Test Item", "machine"),
        ).lastrowid
    )
    variant_recipe_id = int(
        conn.execute(
            "INSERT INTO recipes(name, method, duplicate_of_recipe_id) VALUES(?, ?, ?)",
            ("Test Item", "machine", canonical_recipe_id),
        ).lastrowid
    )
    conn.execute(
        "INSERT INTO recipe_lines(recipe_id, item_id, direction, qty_count) VALUES(?, ?, 'out', 1)",
        (canonical_recipe_id, item_id),
    )
    conn.execute(
        "INSERT INTO recipe_lines(recipe_id, item_id, direction, qty_count) VALUES(?, ?, 'out', 1)",
        (variant_recipe_id, item_id),
    )
    conn.commit()

    dialog = EditRecipeDialog(app, variant_recipe_id)
    save_btn = dialog.button_box.button(QtWidgets.QDialogButtonBox.StandardButton.Save)
    assert save_btn is not None
    assert not save_btn.isEnabled()
    dialog.name_edit.setText("Mutated Name")
    dialog.save()
    dialog.deleteLater()

    assert warnings == [
        (
            "Variant is read-only",
            "Recipe variants are read-only in this dialog. Select the canonical recipe variant to make edits.",
        )
    ]
    variant_name = conn.execute("SELECT name FROM recipes WHERE id=?", (variant_recipe_id,)).fetchone()["name"]
    assert variant_name == "Test Item"
    conn.close()
