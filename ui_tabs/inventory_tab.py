from __future__ import annotations

from PySide6 import QtWidgets


class InventoryTab(QtWidgets.QWidget):
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

        self.inventory_list = QtWidgets.QListWidget()
        self.inventory_list.setMinimumWidth(240)
        self.inventory_list.currentRowChanged.connect(self.on_inventory_select)
        left.addWidget(self.inventory_list, stretch=1)

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

        tip = QtWidgets.QLabel("Tip: items use counts; fluids use liters (L).")
        tip.setStyleSheet("color: #666;")
        right.addWidget(tip)
        right.addStretch(1)

    def render_items(self, items: list) -> None:
        selected_id = None
        current_row = self.inventory_list.currentRow()
        if 0 <= current_row < len(self.items):
            try:
                selected_id = self.items[current_row]["id"]
            except Exception:
                selected_id = None

        self.items = list(items)
        self.inventory_list.clear()
        for it in self.items:
            self.inventory_list.addItem(it["name"])

        if selected_id is not None:
            for idx, it in enumerate(self.items):
                if it.get("id") == selected_id:
                    self.inventory_list.setCurrentRow(idx)
                    break

    def _inventory_selected_item(self):
        row = self.inventory_list.currentRow()
        if row < 0 or row >= len(self.items):
            return None
        return self.items[row]

    def _inventory_unit_for_item(self, item) -> str:
        kind = (item["kind"] or "").strip().lower()
        return "L" if kind == "fluid" else "count"

    def on_inventory_select(self, row: int) -> None:
        if row < 0 or row >= len(self.items):
            self.inventory_item_name.setText("")
            self.inventory_unit_label.setText("")
            self.inventory_qty_entry.setText("")
            return
        item = self.items[row]
        self.inventory_item_name.setText(item["name"])
        unit = self._inventory_unit_for_item(item)
        self.inventory_unit_label.setText(unit)

        row = self.app.profile_conn.execute(
            "SELECT qty_count, qty_liters FROM inventory WHERE item_id=?",
            (item["id"],),
        ).fetchone()
        if unit == "L":
            qty = row["qty_liters"] if row else None
        else:
            qty = row["qty_count"] if row else None
        self.inventory_qty_entry.setText("" if qty is None else self._format_inventory_qty(qty))

    def _format_inventory_qty(self, qty: float | int) -> str:
        try:
            qty_f = float(qty)
        except (TypeError, ValueError):
            return ""
        if qty_f.is_integer():
            return str(int(qty_f))
        return ""

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
