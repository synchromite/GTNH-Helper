from __future__ import annotations

import sqlite3

from PySide6 import QtCore, QtWidgets

from services.automation import add_step, create_plan, delete_step, list_plans, list_steps, update_step_status
from ui_dialogs import ItemPickerDialog


class AutomationTab(QtWidgets.QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._plan_id: int | None = None

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(
            QtWidgets.QLabel(
                "Track end-to-end automation flows (ore -> crushed -> washed -> dust -> centrifuge) "
                "including optional byproducts."
            )
        )

        top = QtWidgets.QHBoxLayout()
        root.addLayout(top)
        top.addWidget(QtWidgets.QLabel("Plan:"))
        self.plan_combo = QtWidgets.QComboBox()
        self.plan_combo.currentIndexChanged.connect(self._on_plan_changed)
        top.addWidget(self.plan_combo, stretch=1)
        self.new_plan_btn = QtWidgets.QPushButton("New Plan…")
        self.new_plan_btn.clicked.connect(self._create_plan)
        top.addWidget(self.new_plan_btn)

        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "#",
            "Machine",
            "Input",
            "Output",
            "Byproduct",
            "Status",
            "Notes",
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        root.addWidget(self.table, stretch=1)

        buttons = QtWidgets.QHBoxLayout()
        root.addLayout(buttons)
        self.add_step_btn = QtWidgets.QPushButton("Add Step…")
        self.add_step_btn.clicked.connect(self._add_step)
        self.advance_btn = QtWidgets.QPushButton("Advance Status")
        self.advance_btn.clicked.connect(self._advance_status)
        self.remove_btn = QtWidgets.QPushButton("Remove Step")
        self.remove_btn.clicked.connect(self._remove_step)
        buttons.addWidget(self.add_step_btn)
        buttons.addWidget(self.advance_btn)
        buttons.addWidget(self.remove_btn)
        buttons.addStretch(1)

        self.refresh()

    def refresh(self) -> None:
        plans = list_plans(self.app.profile_conn)
        selected = self._plan_id
        self.plan_combo.blockSignals(True)
        self.plan_combo.clear()
        for row in plans:
            self.plan_combo.addItem(row["name"], int(row["id"]))
        self.plan_combo.blockSignals(False)

        if not plans:
            self._plan_id = None
            self.table.setRowCount(0)
            return

        if selected is not None:
            idx = self.plan_combo.findData(selected)
            if idx >= 0:
                self.plan_combo.setCurrentIndex(idx)
        if self.plan_combo.currentIndex() < 0:
            self.plan_combo.setCurrentIndex(0)
        self._on_plan_changed(self.plan_combo.currentIndex())

    def _on_plan_changed(self, _index: int) -> None:
        plan_id = self.plan_combo.currentData()
        self._plan_id = int(plan_id) if plan_id is not None else None
        self._load_steps()

    def _load_steps(self) -> None:
        self.table.setRowCount(0)
        if self._plan_id is None:
            return
        for row in list_steps(self.app.profile_conn, self._plan_id):
            row_idx = self.table.rowCount()
            self.table.insertRow(row_idx)
            self.table.setItem(row_idx, 0, self._item(str(row["step_order"]), row["id"]))
            self.table.setItem(row_idx, 1, QtWidgets.QTableWidgetItem(row["machine_name"]))
            self.table.setItem(row_idx, 2, QtWidgets.QTableWidgetItem(row["input_name"]))
            self.table.setItem(row_idx, 3, QtWidgets.QTableWidgetItem(row["output_name"]))
            self.table.setItem(row_idx, 4, QtWidgets.QTableWidgetItem(row["byproduct_name"]))
            self.table.setItem(row_idx, 5, QtWidgets.QTableWidgetItem(row["status"]))
            self.table.setItem(row_idx, 6, QtWidgets.QTableWidgetItem(row["notes"]))

    def _item(self, text: str, step_id: int) -> QtWidgets.QTableWidgetItem:
        item = QtWidgets.QTableWidgetItem(text)
        item.setData(QtCore.Qt.ItemDataRole.UserRole, step_id)
        return item

    def _create_plan(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "New automation plan", "Plan name:")
        if not ok or not name.strip():
            return
        try:
            plan_id = create_plan(self.app.profile_conn, name)
        except sqlite3.IntegrityError:
            QtWidgets.QMessageBox.warning(self, "Plan exists", "A plan with that name already exists.")
            return
        self._plan_id = plan_id
        self.refresh()

    def _pick_item(self, *, title: str, machines_only: bool = False, optional: bool = False) -> dict | None:
        dialog = ItemPickerDialog(self.app, title=title, machines_only=machines_only, parent=self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return None
        return dialog.result

    def _add_step(self) -> None:
        if self._plan_id is None:
            QtWidgets.QMessageBox.information(self, "No plan", "Create a plan first.")
            return

        machine = self._pick_item(title="Pick Machine", machines_only=True)
        if machine is None:
            return

        input_item = self._pick_item(title="Pick Input Item")
        if input_item is None:
            return

        output_item = self._pick_item(title="Pick Output Item")
        if output_item is None:
            return

        byproduct_item = None
        include_byproduct = QtWidgets.QMessageBox.question(
            self,
            "Byproduct",
            "Add a byproduct item for this step?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if include_byproduct == QtWidgets.QMessageBox.StandardButton.Yes:
            byproduct_item = self._pick_item(title="Pick Byproduct Item", optional=True)
            if byproduct_item is None:
                return

        add_step(
            self.app.profile_conn,
            plan_id=self._plan_id,
            machine_item_id=int(machine["id"]),
            machine_name=machine["name"],
            input_item_id=int(input_item["id"]),
            input_name=input_item["name"],
            output_item_id=int(output_item["id"]),
            output_name=output_item["name"],
            byproduct_item_id=int(byproduct_item["id"]) if byproduct_item is not None else None,
            byproduct_name=byproduct_item["name"] if byproduct_item is not None else "",
        )
        self._load_steps()

    def _selected_step_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        id_item = self.table.item(row, 0)
        if id_item is None:
            return None
        step_id = id_item.data(QtCore.Qt.ItemDataRole.UserRole)
        return int(step_id) if step_id is not None else None

    def _advance_status(self) -> None:
        row = self.table.currentRow()
        step_id = self._selected_step_id()
        if row < 0 or step_id is None:
            return
        status_item = self.table.item(row, 5)
        if status_item is None:
            return
        current = status_item.text().strip().lower()
        next_status = "active" if current == "planned" else "complete"
        if current == "complete":
            next_status = "planned"
        update_step_status(self.app.profile_conn, step_id, next_status)
        self._load_steps()

    def _remove_step(self) -> None:
        step_id = self._selected_step_id()
        if step_id is None:
            return
        delete_step(self.app.profile_conn, step_id)
        self._load_steps()
