from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from services.machines import fetch_machine_metadata


class MachinesTab(QtWidgets.QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._rows: list[dict[str, object]] = []

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        layout.addWidget(
            QtWidgets.QLabel(
                "Track which machine tiers you own and have online. Online machines cannot exceed owned."
            )
        )

        self.table = QtWidgets.QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["Machine", "Tier", "Owned", "Online"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.setSortingEnabled(False)
        layout.addWidget(self.table)

        self.empty_label = QtWidgets.QLabel(
            "No machine metadata found in the content database.", alignment=QtCore.Qt.AlignmentFlag.AlignCenter
        )
        self.empty_label.setStyleSheet("color: #666;")
        layout.addWidget(self.empty_label)

        btns = QtWidgets.QHBoxLayout()
        self.save_btn = QtWidgets.QPushButton("Save")
        self.save_btn.clicked.connect(self._save_to_db)
        btns.addWidget(self.save_btn)
        btns.addStretch(1)
        layout.addLayout(btns)
        layout.addStretch(1)

    def load_from_db(self) -> None:
        enabled_tiers = set(self.app.get_enabled_tiers())
        rows = fetch_machine_metadata(self.app.conn)
        self.table.setRowCount(0)
        self._rows = []

        if not rows:
            self.table.hide()
            self.save_btn.setEnabled(False)
            self.empty_label.show()
            return

        self.table.show()
        self.save_btn.setEnabled(True)
        self.empty_label.hide()

        for row_idx, meta in enumerate(rows):
            machine_type = (meta["machine_type"] or "").strip()
            tier = (meta["tier"] or "").strip()
            availability = self.app.get_machine_availability(machine_type, tier)
            owned_checked = availability["owned"] > 0
            online_checked = availability["online"] > 0 and owned_checked
            tier_enabled = tier in enabled_tiers

            self.table.insertRow(row_idx)
            machine_item = QtWidgets.QTableWidgetItem(machine_type)
            tier_item = QtWidgets.QTableWidgetItem(tier)
            self.table.setItem(row_idx, 0, machine_item)
            self.table.setItem(row_idx, 1, tier_item)

            owned_cb = QtWidgets.QCheckBox()
            owned_cb.setChecked(owned_checked)
            online_cb = QtWidgets.QCheckBox()
            online_cb.setChecked(online_checked)
            owned_cb.toggled.connect(lambda checked, idx=row_idx: self._on_owned_toggled(idx, checked))
            online_cb.toggled.connect(lambda checked, idx=row_idx: self._on_online_toggled(idx, checked))

            owned_cell = QtWidgets.QWidget()
            owned_layout = QtWidgets.QHBoxLayout(owned_cell)
            owned_layout.setContentsMargins(0, 0, 0, 0)
            owned_layout.addWidget(owned_cb, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
            self.table.setCellWidget(row_idx, 2, owned_cell)

            online_cell = QtWidgets.QWidget()
            online_layout = QtWidgets.QHBoxLayout(online_cell)
            online_layout.setContentsMargins(0, 0, 0, 0)
            online_layout.addWidget(online_cb, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
            self.table.setCellWidget(row_idx, 3, online_cell)

            row_state = {
                "machine_type": machine_type,
                "tier": tier,
                "owned_cb": owned_cb,
                "online_cb": online_cb,
                "tier_enabled": tier_enabled,
            }
            self._rows.append(row_state)
            self._apply_row_enabled_state(row_state)

        self.table.resizeRowsToContents()

    def _apply_row_enabled_state(self, row_state: dict[str, object]) -> None:
        owned_cb = row_state["owned_cb"]
        online_cb = row_state["online_cb"]
        tier_enabled = bool(row_state["tier_enabled"])
        owned_cb.setEnabled(tier_enabled)
        online_cb.setEnabled(tier_enabled and owned_cb.isChecked())

    def _on_owned_toggled(self, row_idx: int, checked: bool) -> None:
        row_state = self._rows[row_idx]
        online_cb = row_state["online_cb"]
        if not checked:
            prev = online_cb.blockSignals(True)
            online_cb.setChecked(False)
            online_cb.blockSignals(prev)
        self._apply_row_enabled_state(row_state)

    def _on_online_toggled(self, row_idx: int, checked: bool) -> None:
        row_state = self._rows[row_idx]
        owned_cb = row_state["owned_cb"]
        if checked and not owned_cb.isChecked():
            prev = owned_cb.blockSignals(True)
            owned_cb.setChecked(True)
            owned_cb.blockSignals(prev)
        self._apply_row_enabled_state(row_state)

    def _save_to_db(self) -> None:
        updates: list[tuple[str, str, int, int]] = []
        for row_state in self._rows:
            owned = 1 if row_state["owned_cb"].isChecked() else 0
            online = 1 if row_state["online_cb"].isChecked() else 0
            if online > owned:
                online = owned
            updates.append((row_state["machine_type"], row_state["tier"], owned, online))
        self.app.set_machine_availability(updates)
        if hasattr(self.app, "status_bar"):
            self.app.status_bar.showMessage("Saved machine availability.")
