from __future__ import annotations

import logging
import time
import tkinter as tk
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from ui_dialogs import AddItemDialog, EditItemDialog

_LOGGER = logging.getLogger(__name__)
if not _LOGGER.handlers:
    _log_path = Path(__file__).resolve().parent / "items_tab_qt.log"
    _handler = logging.FileHandler(_log_path, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _LOGGER.addHandler(_handler)
    _LOGGER.setLevel(logging.INFO)


class _QtStatusProxy:
    def __init__(self, app):
        self._app = app

    def set(self, message: str) -> None:
        self._app.status_bar.showMessage(message)


class ItemsTab(QtWidgets.QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.items: list = []

        root_layout = QtWidgets.QHBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)

        left = QtWidgets.QVBoxLayout()
        root_layout.addLayout(left, stretch=0)

        right = QtWidgets.QVBoxLayout()
        root_layout.addLayout(right, stretch=1)

        self.item_list = QtWidgets.QListWidget()
        self.item_list.setMinimumWidth(240)
        self.item_list.currentRowChanged.connect(self.on_item_select)
        if self.app.editor_enabled:
            self.item_list.itemDoubleClicked.connect(lambda _item: self.open_edit_item_dialog())
        left.addWidget(self.item_list, stretch=1)

        btns = QtWidgets.QHBoxLayout()
        left.addLayout(btns)
        self.btn_add_item = QtWidgets.QPushButton("Add Item")
        self.btn_edit_item = QtWidgets.QPushButton("Edit Item")
        self.btn_del_item = QtWidgets.QPushButton("Delete Item")
        self.btn_add_item.clicked.connect(self.open_add_item_dialog)
        self.btn_edit_item.clicked.connect(self.open_edit_item_dialog)
        self.btn_del_item.clicked.connect(self.delete_selected_item)
        btns.addWidget(self.btn_add_item)
        btns.addWidget(self.btn_edit_item)
        btns.addWidget(self.btn_del_item)
        btns.addStretch(1)

        if not self.app.editor_enabled:
            self.btn_add_item.setEnabled(False)
            self.btn_edit_item.setEnabled(False)
            self.btn_del_item.setEnabled(False)

        self.item_details = QtWidgets.QTextEdit()
        self.item_details.setReadOnly(True)
        right.addWidget(self.item_details)

    def render_items(self, items: list) -> None:
        selected_id = None
        current_row = self.item_list.currentRow()
        if 0 <= current_row < len(self.items):
            selected_id = self.items[current_row].get("id")

        self.items = list(items)
        self.item_list.clear()
        for it in self.items:
            self.item_list.addItem(it["name"])

        if selected_id is not None:
            for idx, it in enumerate(self.items):
                if it.get("id") == selected_id:
                    self.item_list.setCurrentRow(idx)
                    break

    def on_item_select(self, row: int) -> None:
        if row < 0 or row >= len(self.items):
            self._item_details_set("")
            return
        it = self.items[row]
        txt = (
            f"Name: {it['name']}\n"
            f"Kind: {it['kind']}\n"
            f"Item Kind: {it['item_kind_name'] or ''}\n"
            f"Base: {'Yes' if it['is_base'] else 'No'}\n"
        )
        is_machine_kind = ((it["item_kind_name"] or "").strip().lower() == "machine") or bool(it["is_machine"])
        if is_machine_kind:
            txt += f"Machine Tier: {it['machine_tier'] or ''}\n"

            def _as_int(value, default=0):
                try:
                    return int(value)
                except Exception:
                    return default

            mis_i = _as_int(it["machine_input_slots"], default=1) or 1
            txt += f"Input Slots: {mis_i}\n"
            mos_i = _as_int(it["machine_output_slots"], default=1) or 1
            txt += f"Output Slots: {mos_i}\n"
            txt += f"Storage Slots: {_as_int(it['machine_storage_slots'])}\n"
            txt += f"Power Slots: {_as_int(it['machine_power_slots'])}\n"
            txt += f"Circuit Slots: {_as_int(it['machine_circuit_slots'])}\n"
            in_tanks = _as_int(it["machine_input_tanks"])
            in_cap = _as_int(it["machine_input_tank_capacity_l"])
            if in_tanks > 0 or in_cap > 0:
                cap_txt = f" ({in_cap} L)" if in_cap > 0 else ""
                txt += f"Input Tanks: {in_tanks}{cap_txt}\n"
            out_tanks = _as_int(it["machine_output_tanks"])
            out_cap = _as_int(it["machine_output_tank_capacity_l"])
            if out_tanks > 0 or out_cap > 0:
                cap_txt = f" ({out_cap} L)" if out_cap > 0 else ""
                txt += f"Output Tanks: {out_tanks}{cap_txt}\n"
        self._item_details_set(txt)

    def _item_details_set(self, txt: str) -> None:
        self.item_details.setPlainText(txt)

    def _run_tk_dialog(self, dialog_cls, *args) -> None:
        root = tk.Tk()
        root.withdraw()
        root.conn = self.app.conn
        root.status = _QtStatusProxy(self.app)
        if hasattr(self.app, "get_enabled_tiers"):
            root.get_enabled_tiers = self.app.get_enabled_tiers
        dialog = dialog_cls(root, *args)
        _LOGGER.info("Opened Tk dialog %s", dialog_cls.__name__)
        try:
            loops = 0
            while True:
                try:
                    if not dialog.winfo_exists():
                        break
                except tk.TclError:
                    _LOGGER.info("Tk dialog %s destroyed (TclError).", dialog_cls.__name__)
                    break
                try:
                    root.update()
                except tk.TclError as exc:
                    _LOGGER.exception("Tk update failed for %s: %s", dialog_cls.__name__, exc)
                    break
                try:
                    QtCore.QCoreApplication.processEvents()
                except Exception as exc:
                    _LOGGER.exception("Qt processEvents failed for %s: %s", dialog_cls.__name__, exc)
                    break
                loops += 1
                if loops % 200 == 0:
                    _LOGGER.info("Tk dialog %s still open after %s loops.", dialog_cls.__name__, loops)
                time.sleep(0.01)
        finally:
            try:
                dialog.destroy()
            except tk.TclError:
                pass
            _LOGGER.info("Closed Tk dialog %s", dialog_cls.__name__)
        root.destroy()

    def open_add_item_dialog(self) -> None:
        if not self.app.editor_enabled:
            QtWidgets.QMessageBox.information(
                self,
                "Editor locked",
                "This copy is running in client mode.\n\n"
                "To enable editing, create a file named '.enable_editor' next to the app.",
            )
            return
        self._run_tk_dialog(AddItemDialog)
        self.app.refresh_items()

    def open_edit_item_dialog(self) -> None:
        if not self.app.editor_enabled:
            QtWidgets.QMessageBox.information(self, "Editor locked", "Editing Items is only available in editor mode.")
            return
        row = self.item_list.currentRow()
        if row < 0:
            QtWidgets.QMessageBox.information(self, "Select an item", "Click an item first.")
            return
        item_id = self.items[row]["id"]
        self._run_tk_dialog(EditItemDialog, item_id)
        self.app.refresh_items()

    def delete_selected_item(self) -> None:
        if not self.app.editor_enabled:
            QtWidgets.QMessageBox.information(self, "Editor locked", "Deleting Items is only available in editor mode.")
            return
        row = self.item_list.currentRow()
        if row < 0:
            QtWidgets.QMessageBox.information(self, "Select an item", "Click an item first.")
            return
        it = self.items[row]
        ok = QtWidgets.QMessageBox.question(
            self,
            "Delete item?",
            f"Delete item:\n\n{it['name']}",
        )
        if ok != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            self.app.conn.execute("DELETE FROM items WHERE id=?", (it["id"],))
            self.app.conn.commit()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self,
                "Cannot delete",
                "This item is referenced by a recipe.\nRemove it from recipes first.\n\n"
                f"Details: {exc}",
            )
            return
        self.app.refresh_items()
        self._item_details_set("")
        self.app.status_bar.showMessage(f"Deleted item: {it['name']}")
