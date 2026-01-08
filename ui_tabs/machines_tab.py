from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from services.db import ALL_TIERS
from services.machines import fetch_machine_metadata
from ui_dialogs import MachineMetadataEditorDialog


class MachinesTab(QtWidgets.QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._rows: list[dict[str, object]] = []
        self._metadata_rows: list[dict[str, object]] = []
        self._sort_mode = "Machine (A→Z)"

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        layout.addWidget(
            QtWidgets.QLabel(
                "Track which machine tiers you own and have online. Online machines cannot exceed owned."
            )
        )

        filters = QtWidgets.QHBoxLayout()
        filters.addWidget(QtWidgets.QLabel("Tier"))
        self.filter_tier_combo = QtWidgets.QComboBox()
        self.filter_tier_combo.currentTextChanged.connect(self._apply_filters)
        filters.addWidget(self.filter_tier_combo)
        filters.addSpacing(16)
        self.filter_unlocked_cb = QtWidgets.QCheckBox("Unlocked tiers only")
        self.filter_unlocked_cb.setChecked(True)
        self.filter_unlocked_cb.toggled.connect(self._apply_filters)
        filters.addWidget(self.filter_unlocked_cb)
        filters.addStretch(1)
        layout.addLayout(filters)

        self.table = QtWidgets.QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["Machine", "Tier", "Owned", "Online"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        layout.addWidget(self.table)

        self.empty_label = QtWidgets.QLabel(
            "No machine metadata found in the content database.", alignment=QtCore.Qt.AlignmentFlag.AlignCenter
        )
        self.empty_label.setStyleSheet("color: #666;")
        layout.addWidget(self.empty_label)

        btns = QtWidgets.QHBoxLayout()
        self.save_btn = QtWidgets.QPushButton("Save")
        self.save_btn.clicked.connect(self._save_to_db)
        self.edit_metadata_btn = QtWidgets.QPushButton("Edit Metadata…")
        self.edit_metadata_btn.clicked.connect(self._open_metadata_editor)
        btns.addWidget(self.save_btn)
        btns.addWidget(self.edit_metadata_btn)
        btns.addStretch(1)
        layout.addLayout(btns)
        layout.addStretch(1)

        if not self.app.editor_enabled:
            self.edit_metadata_btn.setEnabled(False)

    def load_from_db(self) -> None:
        rows = fetch_machine_metadata(self.app.conn)
        self._metadata_rows = [dict(row) for row in rows]
        self._rebuild_tier_filter()
        self._render_rows()

    def _rebuild_tier_filter(self) -> None:
        current = self.filter_tier_combo.currentText() if hasattr(self, "filter_tier_combo") else ""
        tiers = {(row.get("tier") or "").strip() for row in self._metadata_rows}
        tiers = {tier for tier in tiers if tier}
        ordered = [tier for tier in ALL_TIERS if tier in tiers]
        extras = sorted(tiers - set(ALL_TIERS))
        choices = ["All tiers"] + ordered + extras
        self.filter_tier_combo.blockSignals(True)
        self.filter_tier_combo.clear()
        self.filter_tier_combo.addItems(choices)
        if current in choices:
            self.filter_tier_combo.setCurrentText(current)
        self.filter_tier_combo.blockSignals(False)

    def _sorted_metadata_rows(self) -> list[dict[str, object]]:
        rows = list(self._metadata_rows)
        mode = getattr(self, "_sort_mode", "Machine (A→Z)")
        tier_order = {tier: idx for idx, tier in enumerate(ALL_TIERS)}

        def tier_key(value: str) -> tuple[int, str]:
            val = (value or "").strip()
            return (tier_order.get(val, len(ALL_TIERS)), val.lower())

        if mode == "Machine (Z→A)":
            return sorted(rows, key=lambda r: (r.get("machine_type") or "").lower(), reverse=True)
        if mode == "Tier (progression)":
            return sorted(
                rows,
                key=lambda r: (
                    tier_key(r.get("tier") or ""),
                    (r.get("machine_type") or "").lower(),
                ),
            )
        if mode == "Tier (reverse)":
            return sorted(
                rows,
                key=lambda r: (
                    tier_key(r.get("tier") or ""),
                    (r.get("machine_type") or "").lower(),
                ),
                reverse=True,
            )
        return sorted(rows, key=lambda r: (r.get("machine_type") or "").lower())

    def _render_rows(self) -> None:
        enabled_tiers = set(self.app.get_enabled_tiers())
        rows = self._sorted_metadata_rows()
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
            machine_type = (meta.get("machine_type") or "").strip()
            tier = (meta.get("tier") or "").strip()
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
        self._apply_filters()

    def _apply_filters(self) -> None:
        tier_filter = self.filter_tier_combo.currentText() if hasattr(self, "filter_tier_combo") else "All tiers"
        unlocked_only = bool(self.filter_unlocked_cb.isChecked()) if hasattr(self, "filter_unlocked_cb") else False
        enabled_tiers = set(self.app.get_enabled_tiers())
        for row_idx, row_state in enumerate(self._rows):
            matches = True
            if tier_filter and tier_filter != "All tiers":
                matches = row_state["tier"] == tier_filter
            if matches and unlocked_only:
                matches = row_state["tier"] in enabled_tiers
            self.table.setRowHidden(row_idx, not matches)

    def _on_header_clicked(self, section: int) -> None:
        if section == 0:
            current = getattr(self, "_sort_mode", "Machine (A→Z)")
            self._sort_mode = "Machine (Z→A)" if current == "Machine (A→Z)" else "Machine (A→Z)"
            self._render_rows()
            return
        if section == 1:
            current = getattr(self, "_sort_mode", "Tier (progression)")
            self._sort_mode = "Tier (reverse)" if current == "Tier (progression)" else "Tier (progression)"
            self._render_rows()

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

    def _open_metadata_editor(self) -> None:
        if not self.app.editor_enabled:
            QtWidgets.QMessageBox.information(
                self,
                "Editor locked",
                "Editing machine metadata is only available in editor mode.",
            )
            return
        dialog = MachineMetadataEditorDialog(self.app, parent=self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.load_from_db()
            if hasattr(self.app, "status_bar"):
                self.app.status_bar.showMessage("Updated machine metadata.")
