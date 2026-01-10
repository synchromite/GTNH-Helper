from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from ui_dialogs import AddItemDialog, EditItemDialog


class ItemsTab(QtWidgets.QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.items: list = []
        self.items_by_id: dict[int, dict] = {}
        root_layout = QtWidgets.QHBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)

        left = QtWidgets.QVBoxLayout()
        root_layout.addLayout(left, stretch=0)

        right = QtWidgets.QVBoxLayout()
        root_layout.addLayout(right, stretch=1)

        self.item_tree = QtWidgets.QTreeWidget()
        self.item_tree.setHeaderHidden(True)
        self.item_tree.setMinimumWidth(240)
        self.item_tree.currentItemChanged.connect(self.on_item_select)
        if self.app.editor_enabled:
            self.item_tree.itemDoubleClicked.connect(lambda _item: self.open_edit_item_dialog())
        left.addWidget(self.item_tree, stretch=1)

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
        current_item = self.item_tree.currentItem()
        if current_item is not None:
            selected_id = current_item.data(0, QtCore.Qt.UserRole)

        self.items = list(items)
        self.items_by_id = {it["id"]: it for it in self.items}
        self.item_tree.clear()

        kind_nodes: dict[str, QtWidgets.QTreeWidgetItem] = {}
        item_kind_nodes: dict[tuple[str, str], QtWidgets.QTreeWidgetItem] = {}
        material_nodes: dict[tuple[str, str, str], QtWidgets.QTreeWidgetItem] = {}
        id_nodes: dict[int, QtWidgets.QTreeWidgetItem] = {}

        def _value(item: dict | QtCore.QVariant | object, key: str):
            try:
                return item[key]
            except Exception:
                return None

        def _label(value: str | None, fallback: str) -> str:
            if value is None:
                return fallback
            value = value.strip()
            return value if value else fallback

        def _sort_key(it: dict) -> tuple[str, str, str, str]:
            return (
                (_value(it, "kind") or "").strip().lower(),
                (_value(it, "item_kind_name") or "").strip().lower(),
                (_value(it, "material_name") or "").strip().lower(),
                (_value(it, "name") or "").strip().lower(),
            )

        for it in sorted(self.items, key=_sort_key):
            # Level 1: Kind (Item, Fluid, Gas, Machine)
            kind_val = _value(it, "kind")
            kind_label = _label(kind_val, "(No type)").title()

            # Level 2: Item Kind (e.g. Component, etc.)
            item_kind_val = _value(it, "item_kind_name")
            item_kind_label = _label(item_kind_val, "(No kind)")

            # Check if Material exists
            raw_mat_name = _value(it, "material_name")
            has_material = raw_mat_name and raw_mat_name.strip()

            # Build Tree Nodes
            kind_item = kind_nodes.get(kind_label)
            if kind_item is None:
                kind_item = QtWidgets.QTreeWidgetItem([kind_label])
                self.item_tree.addTopLevelItem(kind_item)
                kind_nodes[kind_label] = kind_item

            item_kind_key = (kind_label, item_kind_label)
            item_kind_item = item_kind_nodes.get(item_kind_key)
            if item_kind_item is None:
                item_kind_item = QtWidgets.QTreeWidgetItem([item_kind_label])
                kind_item.addChild(item_kind_item)
                item_kind_nodes[item_kind_key] = item_kind_item

            # Determine Parent: Material Node OR Item Kind Node
            if has_material:
                material_label = raw_mat_name.strip()
                material_key = (kind_label, item_kind_label, material_label)
                material_item = material_nodes.get(material_key)
                if material_item is None:
                    material_item = QtWidgets.QTreeWidgetItem([material_label])
                    item_kind_item.addChild(material_item)
                    material_nodes[material_key] = material_item
                parent_node = material_item
            else:
                # No material, attach directly to Item Kind
                parent_node = item_kind_item

            item_node = QtWidgets.QTreeWidgetItem([it["name"]])
            item_node.setData(0, QtCore.Qt.UserRole, it["id"])
            parent_node.addChild(item_node)
            id_nodes[it["id"]] = item_node

        if selected_id is not None and selected_id in id_nodes:
            self.item_tree.setCurrentItem(id_nodes[selected_id])

    def on_item_select(self, current: QtWidgets.QTreeWidgetItem | None, _previous=None) -> None:
        if current is None:
            self._item_details_set("")
            return
        item_id = current.data(0, QtCore.Qt.UserRole)
        if item_id is None:
            self._item_details_set("")
            return
        it = self.items_by_id.get(item_id)
        if it is None:
            self._item_details_set("")
            return
        txt = (
            f"Name: {it['name']}\n"
            f"Kind: {it['kind']}\n"
            f"Item Type: {it['item_kind_name'] or ''}\n"
            f"Material: {it['material_name'] or ''}\n"
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

    def _selected_item_id(self) -> int | None:
        current = self.item_tree.currentItem()
        if current is None:
            return None
        item_id = current.data(0, QtCore.Qt.UserRole)
        if item_id is None:
            return None
        return int(item_id)

    def open_add_item_dialog(self) -> None:
        if not self.app.editor_enabled:
            QtWidgets.QMessageBox.information(
                self,
                "Editor locked",
                "This copy is running in client mode.\n\n"
                "To enable editing, create a file named '.enable_editor' next to the app.",
            )
            return
        dialog = AddItemDialog(self.app, parent=self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.app.refresh_items()

    def open_edit_item_dialog(self) -> None:
        if not self.app.editor_enabled:
            QtWidgets.QMessageBox.information(self, "Editor locked", "Editing Items is only available in editor mode.")
            return
        item_id = self._selected_item_id()
        if item_id is None:
            QtWidgets.QMessageBox.information(self, "Select an item", "Click an item first.")
            return
        dialog = EditItemDialog(self.app, item_id, parent=self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.app.refresh_items()

    def delete_selected_item(self) -> None:
        if not self.app.editor_enabled:
            QtWidgets.QMessageBox.information(self, "Editor locked", "Deleting Items is only available in editor mode.")
            return
        item_id = self._selected_item_id()
        if item_id is None:
            QtWidgets.QMessageBox.information(self, "Select an item", "Click an item first.")
            return
        it = self.items_by_id[item_id]
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
