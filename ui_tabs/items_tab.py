from PyQt5 import QtWidgets


class ItemsTab(QtWidgets.QWidget):
    def __init__(self, parent, app):
        qt_parent = parent if isinstance(parent, QtWidgets.QWidget) else None
        super().__init__(qt_parent)
        self.app = app
        self.items: list = []

        if hasattr(parent, "addTab"):
            parent.addTab(self, "Items")

        main_layout = QtWidgets.QHBoxLayout(self)

        left = QtWidgets.QWidget(self)
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        right = QtWidgets.QWidget(self)
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.item_list = QtWidgets.QListWidget(left)
        self.item_list.itemSelectionChanged.connect(self.on_item_select)
        if self.app.editor_enabled:
            self.item_list.itemDoubleClicked.connect(lambda _item: self.open_edit_item_dialog())
        left_layout.addWidget(self.item_list, stretch=1)

        btns = QtWidgets.QWidget(left)
        btns_layout = QtWidgets.QHBoxLayout(btns)
        btns_layout.setContentsMargins(0, 8, 0, 0)
        self.btn_add_item = QtWidgets.QPushButton("Add Item", btns)
        self.btn_edit_item = QtWidgets.QPushButton("Edit Item", btns)
        self.btn_del_item = QtWidgets.QPushButton("Delete Item", btns)
        self.btn_add_item.clicked.connect(self.open_add_item_dialog)
        self.btn_edit_item.clicked.connect(self.open_edit_item_dialog)
        self.btn_del_item.clicked.connect(self.delete_selected_item)
        btns_layout.addWidget(self.btn_add_item)
        btns_layout.addWidget(self.btn_edit_item)
        btns_layout.addWidget(self.btn_del_item)
        left_layout.addWidget(btns)

        if not self.app.editor_enabled:
            self.btn_add_item.setEnabled(False)
            self.btn_edit_item.setEnabled(False)
            self.btn_del_item.setEnabled(False)

        self.item_details = QtWidgets.QTextEdit(right)
        self.item_details.setReadOnly(True)
        right_layout.addWidget(self.item_details, stretch=1)

        main_layout.addWidget(left)
        main_layout.addWidget(right, stretch=1)

    def render_items(self, items: list) -> None:
        self.items = list(items)
        self.item_list.clear()
        for it in self.items:
            self.item_list.addItem(it["name"])

    def on_item_select(self):
        row = self.item_list.currentRow()
        if row < 0:
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

    def _item_details_set(self, txt: str):
        self.item_details.setPlainText(txt)

    def open_add_item_dialog(self):
        if not self.app.editor_enabled:
            QtWidgets.QMessageBox.information(
                self,
                "Editor locked",
                "This copy is running in client mode.\n\n"
                "To enable editing, create a file named '.enable_editor' next to the app.",
            )
            return
        QtWidgets.QMessageBox.information(
            self,
            "Add Item",
            "Add Item dialog is not yet implemented for the Qt UI.",
        )
        if hasattr(self.app, "refresh_items"):
            self.app.refresh_items()

    def open_edit_item_dialog(self):
        if not self.app.editor_enabled:
            QtWidgets.QMessageBox.information(
                self,
                "Editor locked",
                "Editing Items is only available in editor mode.",
            )
            return
        row = self.item_list.currentRow()
        if row < 0:
            QtWidgets.QMessageBox.information(
                self,
                "Select an item",
                "Click an item first.",
            )
            return
        QtWidgets.QMessageBox.information(
            self,
            "Edit Item",
            "Edit Item dialog is not yet implemented for the Qt UI.",
        )
        if hasattr(self.app, "refresh_items"):
            self.app.refresh_items()

    def delete_selected_item(self):
        if not self.app.editor_enabled:
            QtWidgets.QMessageBox.information(
                self,
                "Editor locked",
                "Deleting Items is only available in editor mode.",
            )
            return
        row = self.item_list.currentRow()
        if row < 0:
            QtWidgets.QMessageBox.information(
                self,
                "Select an item",
                "Click an item first.",
            )
            return
        it = self.items[row]
        ok = QtWidgets.QMessageBox.question(
            self,
            "Delete item?",
            f"Delete item:\n\n{it['name']}",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if ok != QtWidgets.QMessageBox.Yes:
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
        if hasattr(self.app, "refresh_items"):
            self.app.refresh_items()
        self._item_details_set("")
        if hasattr(self.app, "status") and hasattr(self.app.status, "set"):
            self.app.status.set(f"Deleted item: {it['name']}")
