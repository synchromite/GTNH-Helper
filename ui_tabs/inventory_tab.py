from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class InventoryTab(QtWidgets.QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.items: list = []
        self.items_by_id: dict[int, dict] = {}

        root_layout = QtWidgets.QHBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter)

        left_widget = QtWidgets.QWidget()
        left = QtWidgets.QVBoxLayout(left_widget)
        left.setContentsMargins(0, 0, 0, 0)
        splitter.addWidget(left_widget)

        right_widget = QtWidgets.QWidget()
        right = QtWidgets.QVBoxLayout(right_widget)
        right.setContentsMargins(0, 0, 0, 0)
        splitter.addWidget(right_widget)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        self.search_entry = QtWidgets.QLineEdit()
        self.search_entry.setPlaceholderText("Search inventory items...")
        self.search_entry.textChanged.connect(self._on_search_changed)
        left.addWidget(self.search_entry)

        self.inventory_tabs = QtWidgets.QTabWidget()
        left.addWidget(self.inventory_tabs, stretch=1)

        self.inventory_trees: dict[str, QtWidgets.QTreeWidget] = {}
        for label, kind in (
            ("All", None),
            ("Items", "item"),
            ("Fluids", "fluid"),
            ("Gases", "gas"),
            ("Machines", "machine"),
        ):
            tree = QtWidgets.QTreeWidget()
            tree.setHeaderHidden(True)
            tree.setMinimumWidth(240)
            tree.currentItemChanged.connect(self.on_inventory_select)
            tree.setProperty("kind_filter", kind)
            self.inventory_tabs.addTab(tree, label)
            self.inventory_trees[label] = tree

        self.inventory_tabs.currentChanged.connect(self._on_tab_changed)

        header = QtWidgets.QLabel("Track what you currently have in storage.")
        right.addWidget(header)

        self.inventory_item_name = QtWidgets.QLabel("")
        font = self.inventory_item_name.font()
        font.setBold(True)
        font.setPointSize(max(11, font.pointSize()))
        self.inventory_item_name.setFont(font)
        right.addWidget(self.inventory_item_name)

        qty_row = QtWidgets.QHBoxLayout()
        right.addLayout(qty_row)
        qty_row.addWidget(QtWidgets.QLabel("Quantity:"))
        self.inventory_qty_entry = QtWidgets.QLineEdit()
        self.inventory_qty_entry.setFixedWidth(100)
        qty_row.addWidget(self.inventory_qty_entry)
        self.inventory_unit_label = QtWidgets.QLabel("")
        qty_row.addWidget(self.inventory_unit_label)
        qty_row.addStretch(1)

        btns = QtWidgets.QHBoxLayout()
        right.addLayout(btns)
        self.btn_save = QtWidgets.QPushButton("Save")
        self.btn_clear = QtWidgets.QPushButton("Clear")
        self.btn_save.clicked.connect(self.save_inventory_item)
        self.btn_clear.clicked.connect(self.clear_inventory_item)
        btns.addWidget(self.btn_save)
        btns.addWidget(self.btn_clear)
        btns.addStretch(1)

        tip = QtWidgets.QLabel("Tip: items use counts; fluids and gases use liters (L).")
        tip.setStyleSheet("color: #666;")
        right.addWidget(tip)
        right.addStretch(1)

    def render_items(self, items: list) -> None:
        self.items = list(items)
        self.items_by_id = {it["id"]: it for it in self.items}
        selected_id = self._selected_item_id()

        for tree in self.inventory_trees.values():
            self._render_tree(tree, selected_id)

        current_item = self._current_tree().currentItem()
        if current_item is None or selected_id not in self.items_by_id:
            self.inventory_item_name.setText("")
            self.inventory_unit_label.setText("")
            self.inventory_qty_entry.setText("")
        else:
            self.on_inventory_select(current_item, None)

    def _inventory_selected_item(self):
        item_id = self._selected_item_id()
        if item_id is None:
            return None
        return self.items_by_id.get(item_id)

    def _current_tree(self) -> QtWidgets.QTreeWidget:
        widget = self.inventory_tabs.currentWidget()
        if isinstance(widget, QtWidgets.QTreeWidget):
            return widget
        return self.inventory_trees["All"]

    def _selected_item_id(self) -> int | None:
        tree = self._current_tree()
        current = tree.currentItem()
        if current is None:
            return None
        item_id = current.data(0, QtCore.Qt.UserRole)
        if item_id is None:
            return None
        return int(item_id)

    def _inventory_unit_for_item(self, item) -> str:
        kind = (item["kind"] or "").strip().lower()
        return "L" if kind in ("fluid", "gas") else "count"

    def on_inventory_select(
        self,
        current: QtWidgets.QTreeWidgetItem | None,
        _previous: QtWidgets.QTreeWidgetItem | None = None,
    ) -> None:
        if current is None:
            self.inventory_item_name.setText("")
            self.inventory_unit_label.setText("")
            self.inventory_qty_entry.setText("")
            return
        item_id = current.data(0, QtCore.Qt.UserRole)
        if item_id is None:
            self.inventory_item_name.setText("")
            self.inventory_unit_label.setText("")
            self.inventory_qty_entry.setText("")
            return
        item = self.items_by_id.get(int(item_id))
        if item is None:
            self.inventory_item_name.setText("")
            self.inventory_unit_label.setText("")
            self.inventory_qty_entry.setText("")
            return
        self.inventory_item_name.setText(item["name"])
        unit = self._inventory_unit_for_item(item)
        self.inventory_unit_label.setText(unit)

        db_row = self.app.profile_conn.execute(
            "SELECT qty_count, qty_liters FROM inventory WHERE item_id=?",
            (item["id"],),
        ).fetchone()
        if unit == "L":
            qty = db_row["qty_liters"] if db_row else None
        else:
            qty = db_row["qty_count"] if db_row else None
        self.inventory_qty_entry.setText("" if qty is None else self._format_inventory_qty(qty))

    def _format_inventory_qty(self, qty: float | int) -> str:
        try:
            qty_f = float(qty)
        except (TypeError, ValueError):
            return ""
        return str(int(round(qty_f)))

    def save_inventory_item(self) -> None:
        item = self._inventory_selected_item()
        if not item:
            QtWidgets.QMessageBox.information(self, "Select an item", "Click an item first.")
            return

        raw = self.inventory_qty_entry.text().strip()
        if raw == "":
            self.app.profile_conn.execute("DELETE FROM inventory WHERE item_id=?", (item["id"],))
            self.app.profile_conn.commit()
            self.app.status_bar.showMessage(f"Cleared inventory for: {item['name']}")
            self.app.notify_inventory_change()
            return

        try:
            qty_float = float(raw)
        except ValueError:
            QtWidgets.QMessageBox.critical(self, "Invalid quantity", "Enter a whole number.")
            return

        if not qty_float.is_integer():
            QtWidgets.QMessageBox.critical(self, "Invalid quantity", "Enter a whole number.")
            return

        qty = int(qty_float)

        unit = self._inventory_unit_for_item(item)
        qty_count = qty if unit == "count" else None
        qty_liters = qty if unit == "L" else None
        self.app.profile_conn.execute(
            "INSERT INTO inventory(item_id, qty_count, qty_liters) VALUES(?, ?, ?) "
            "ON CONFLICT(item_id) DO UPDATE SET qty_count=excluded.qty_count, qty_liters=excluded.qty_liters",
            (item["id"], qty_count, qty_liters),
        )
        self.app.profile_conn.commit()
        self.inventory_qty_entry.setText(str(qty))
        self.app.status_bar.showMessage(f"Saved inventory for: {item['name']}")
        self.app.notify_inventory_change()

    def clear_inventory_item(self) -> None:
        self.inventory_qty_entry.setText("")
        self.save_inventory_item()

    def _on_search_changed(self, _text: str) -> None:
        selected_id = self._selected_item_id()
        for tree in self.inventory_trees.values():
            self._render_tree(tree, selected_id)

    def _on_tab_changed(self, _index: int) -> None:
        tree = self._current_tree()
        current = tree.currentItem()
        self.on_inventory_select(current, None)

    def _filtered_items(self, kind_filter: str | None) -> list[dict]:
        query = self.search_entry.text().strip().lower()
        items = self.items
        if kind_filter:
            items = [
                it
                for it in items
                if (self._item_value(it, "kind") or "").strip().lower() == kind_filter
            ]
        if not query:
            return items
        return [
            it
            for it in items
            if query in (self._item_value(it, "name") or "").lower()
            or query in (self._item_value(it, "item_kind_name") or "").lower()
            or query in (self._item_value(it, "material_name") or "").lower()
        ]

    def _render_tree(self, tree: QtWidgets.QTreeWidget, selected_id: int | None) -> None:
        tree.blockSignals(True)
        try:
            tree.clear()
            kind_filter = tree.property("kind_filter")
            items = self._filtered_items(kind_filter)
            kind_nodes: dict[str, QtWidgets.QTreeWidgetItem] = {}
            item_kind_nodes: dict[tuple[str, str], QtWidgets.QTreeWidgetItem] = {}
            material_nodes: dict[tuple[str, str, str], QtWidgets.QTreeWidgetItem] = {}
            id_nodes: dict[int, QtWidgets.QTreeWidgetItem] = {}

            def _label(value: str | None, fallback: str) -> str:
                if value is None:
                    return fallback
                value = value.strip()
                return value if value else fallback

            def _sort_key(it: dict) -> tuple[str, str, str, str]:
                return (
                    (self._item_value(it, "kind") or "").strip().lower(),
                    (self._item_value(it, "item_kind_name") or "").strip().lower(),
                    (self._item_value(it, "material_name") or "").strip().lower(),
                    (self._item_value(it, "name") or "").strip().lower(),
                )

            for it in sorted(items, key=_sort_key):
                kind_val = self._item_value(it, "kind")
                kind_label = _label(kind_val, "(No type)").title()

                item_kind_val = self._item_value(it, "item_kind_name")
                item_kind_label = _label(item_kind_val, "(No kind)")
                if (kind_val or "").strip().lower() == "machine":
                    machine_type_val = self._item_value(it, "machine_type")
                    item_kind_label = _label(machine_type_val, "(Machine type)")

                raw_mat_name = self._item_value(it, "material_name")
                has_material = raw_mat_name and raw_mat_name.strip()
                if (kind_val or "").strip().lower() == "machine":
                    has_material = False

                kind_item = kind_nodes.get(kind_label)
                if kind_item is None:
                    kind_item = QtWidgets.QTreeWidgetItem([kind_label])
                    tree.addTopLevelItem(kind_item)
                    kind_nodes[kind_label] = kind_item

                item_kind_key = (kind_label, item_kind_label)
                item_kind_item = item_kind_nodes.get(item_kind_key)
                if item_kind_item is None:
                    item_kind_item = QtWidgets.QTreeWidgetItem([item_kind_label])
                    kind_item.addChild(item_kind_item)
                    item_kind_nodes[item_kind_key] = item_kind_item

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
                    parent_node = item_kind_item

                item_node = QtWidgets.QTreeWidgetItem([it["name"]])
                item_node.setData(0, QtCore.Qt.UserRole, it["id"])
                parent_node.addChild(item_node)
                id_nodes[it["id"]] = item_node

            if selected_id is not None and selected_id in id_nodes:
                tree.setCurrentItem(id_nodes[selected_id])
        finally:
            tree.blockSignals(False)

    @staticmethod
    def _item_value(item, key: str):
        try:
            return item[key]
        except Exception:
            return None
