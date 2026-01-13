from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from services.db import ALL_TIERS
from ui_dialogs import MachineMetadataEditorDialog


class MachineAvailabilityDialog(QtWidgets.QDialog):
    def __init__(self, app, machine: dict[str, object], parent=None):
        super().__init__(parent)
        self.app = app
        self.machine = machine
        self.setWindowTitle("Machine Availability")
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QtWidgets.QVBoxLayout(self)
        name = machine.get("name") or machine.get("machine_type") or "(Unknown)"
        tier = machine.get("machine_tier") or ""
        layout.addWidget(QtWidgets.QLabel(f"{name} — {tier}"))

        form = QtWidgets.QGridLayout()
        layout.addLayout(form)

        form.addWidget(QtWidgets.QLabel("Owned"), 0, 0)
        self.owned_spin = QtWidgets.QSpinBox()
        self.owned_spin.setRange(0, 9999)
        form.addWidget(self.owned_spin, 0, 1)

        form.addWidget(QtWidgets.QLabel("Online"), 1, 0)
        self.online_spin = QtWidgets.QSpinBox()
        self.online_spin.setRange(0, 9999)
        form.addWidget(self.online_spin, 1, 1)

        availability = self.app.get_machine_availability(machine["machine_type"], machine["machine_tier"])
        owned = int(availability.get("owned", 0))
        online = int(availability.get("online", 0))
        self.owned_spin.setValue(owned)
        self.online_spin.setValue(min(online, owned))
        self.online_spin.setMaximum(owned)
        self.owned_spin.valueChanged.connect(self._on_owned_changed)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_owned_changed(self, value: int) -> None:
        self.online_spin.setMaximum(value)
        if self.online_spin.value() > value:
            self.online_spin.setValue(value)

    def _save(self) -> None:
        owned = self.owned_spin.value()
        online = min(self.online_spin.value(), owned)
        self.app.set_machine_availability(
            [(self.machine["machine_type"], self.machine["machine_tier"], owned, online)]
        )
        self.accept()


class MachinesTab(QtWidgets.QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._machines: list[dict[str, object]] = []
        self._sort_mode = self.app.get_machine_sort_mode() if hasattr(self.app, "get_machine_sort_mode") else "Machine (A→Z)"
        self._preferences_loaded = False

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        layout.addWidget(
            QtWidgets.QLabel(
                "Select a machine to view its specs. Double-click to update availability (owned/online)."
            )
        )

        filters = QtWidgets.QHBoxLayout()
        filters.addWidget(QtWidgets.QLabel("Tier"))
        self.filter_tier_combo = QtWidgets.QComboBox()
        self.filter_tier_combo.currentTextChanged.connect(self._on_tier_filter_changed)
        filters.addWidget(self.filter_tier_combo)
        filters.addSpacing(16)
        self.filter_unlocked_cb = QtWidgets.QCheckBox("Unlocked tiers only")
        self.filter_unlocked_cb.setChecked(
            self.app.get_machine_unlocked_only() if hasattr(self.app, "get_machine_unlocked_only") else True
        )
        self.filter_unlocked_cb.toggled.connect(self._on_unlocked_filter_toggled)
        filters.addWidget(self.filter_unlocked_cb)
        filters.addSpacing(16)
        filters.addWidget(QtWidgets.QLabel("Search"))
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("Filter by machine name")
        if hasattr(self.app, "get_machine_search"):
            self.search_edit.setText(self.app.get_machine_search())
        self.search_edit.textChanged.connect(self._on_search_changed)
        filters.addWidget(self.search_edit)
        filters.addStretch(1)
        layout.addLayout(filters)

        content = QtWidgets.QHBoxLayout()
        layout.addLayout(content, stretch=1)

        self.machine_list = QtWidgets.QListWidget()
        self.machine_list.setMinimumWidth(260)
        self.machine_list.currentRowChanged.connect(self._on_machine_selected)
        self.machine_list.itemDoubleClicked.connect(self._open_availability_dialog)
        content.addWidget(self.machine_list, stretch=0)

        right = QtWidgets.QVBoxLayout()
        content.addLayout(right, stretch=1)

        self.details = QtWidgets.QTextEdit()
        self.details.setReadOnly(True)
        right.addWidget(self.details, stretch=1)

        self.empty_label = QtWidgets.QLabel(
            "No machines found in the content database.", alignment=QtCore.Qt.AlignmentFlag.AlignCenter
        )
        self.empty_label.setStyleSheet("color: #666;")
        right.addWidget(self.empty_label)

        btns = QtWidgets.QHBoxLayout()
        self.edit_metadata_btn = QtWidgets.QPushButton("Edit Specs…")
        self.edit_metadata_btn.clicked.connect(self._open_metadata_editor)
        btns.addWidget(self.edit_metadata_btn)
        btns.addStretch(1)
        right.addLayout(btns)

        if not self.app.editor_enabled:
            self.edit_metadata_btn.setEnabled(False)

    def load_from_db(self) -> None:
        rows = self.app.conn.execute(
            """
            SELECT
                i.id,
                i.key,
                COALESCE(i.display_name, i.key) AS name,
                i.machine_type,
                i.machine_tier,
                COALESCE(mm.input_slots, 1) AS machine_input_slots,
                COALESCE(mm.output_slots, 1) AS machine_output_slots,
                COALESCE(mm.byproduct_slots, 0) AS machine_byproduct_slots,
                COALESCE(mm.storage_slots, 0) AS machine_storage_slots,
                COALESCE(mm.power_slots, 0) AS machine_power_slots,
                COALESCE(mm.circuit_slots, 0) AS machine_circuit_slots,
                COALESCE(mm.input_tanks, 0) AS machine_input_tanks,
                COALESCE(mm.input_tank_capacity_l, 0) AS machine_input_tank_capacity_l,
                COALESCE(mm.output_tanks, 0) AS machine_output_tanks,
                COALESCE(mm.output_tank_capacity_l, 0) AS machine_output_tank_capacity_l
            FROM items i
            LEFT JOIN machine_metadata mm
                ON mm.machine_type = i.machine_type
                AND mm.tier = i.machine_tier
            WHERE i.kind = 'machine'
            ORDER BY name
            """
        ).fetchall()
        self._machines = [dict(row) for row in rows]
        self._rebuild_tier_filter()
        if not self._preferences_loaded:
            self._load_preferences()
        self._render_rows()

    def _rebuild_tier_filter(self) -> None:
        current = self.filter_tier_combo.currentText() if hasattr(self, "filter_tier_combo") else ""
        tiers = {(row.get("machine_tier") or "").strip() for row in self._machines}
        tiers = {tier for tier in tiers if tier}
        ordered = list(ALL_TIERS)
        extras = sorted(tiers - set(ALL_TIERS))
        choices = ["All tiers"] + ordered + extras
        self.filter_tier_combo.blockSignals(True)
        self.filter_tier_combo.clear()
        self.filter_tier_combo.addItems(choices)
        if current in choices:
            self.filter_tier_combo.setCurrentText(current)
        self.filter_tier_combo.blockSignals(False)

    def _load_preferences(self) -> None:
        self._preferences_loaded = True
        if hasattr(self.app, "get_machine_sort_mode"):
            self._sort_mode = self.app.get_machine_sort_mode()
        if hasattr(self.app, "get_machine_tier_filter"):
            tier = self.app.get_machine_tier_filter()
            if tier:
                prev = self.filter_tier_combo.blockSignals(True)
                if tier in [self.filter_tier_combo.itemText(i) for i in range(self.filter_tier_combo.count())]:
                    self.filter_tier_combo.setCurrentText(tier)
                self.filter_tier_combo.blockSignals(prev)
        if hasattr(self.app, "get_machine_unlocked_only"):
            prev = self.filter_unlocked_cb.blockSignals(True)
            self.filter_unlocked_cb.setChecked(self.app.get_machine_unlocked_only())
            self.filter_unlocked_cb.blockSignals(prev)
        if hasattr(self.app, "get_machine_search"):
            prev = self.search_edit.blockSignals(True)
            self.search_edit.setText(self.app.get_machine_search())
            self.search_edit.blockSignals(prev)

    def _sorted_metadata_rows(self) -> list[dict[str, object]]:
        rows = list(self._machines)
        mode = getattr(self, "_sort_mode", "Machine (A→Z)")
        tier_order = {tier: idx for idx, tier in enumerate(ALL_TIERS)}

        def tier_key(value: str) -> tuple[int, str]:
            val = (value or "").strip()
            return (tier_order.get(val, len(ALL_TIERS)), val.lower())

        if mode == "Machine (Z→A)":
            return sorted(rows, key=lambda r: (r.get("name") or "").lower(), reverse=True)
        if mode == "Tier (progression)":
            return sorted(
                rows,
                key=lambda r: (
                    tier_key(r.get("machine_tier") or ""),
                    (r.get("name") or "").lower(),
                ),
            )
        if mode == "Tier (reverse)":
            return sorted(
                rows,
                key=lambda r: (
                    tier_key(r.get("machine_tier") or ""),
                    (r.get("name") or "").lower(),
                ),
                reverse=True,
            )
        return sorted(rows, key=lambda r: (r.get("name") or "").lower())

    def _render_rows(self) -> None:
        rows = self._sorted_metadata_rows()
        self.machine_list.clear()

        if not rows:
            self.machine_list.hide()
            self.details.clear()
            self.empty_label.show()
            return

        self.machine_list.show()
        self.empty_label.hide()

        for row in rows:
            label = row.get("name") or row.get("machine_type") or "(Unnamed machine)"
            tier = (row.get("machine_tier") or "").strip()
            display = f"{label} ({tier})" if tier else str(label)
            item = QtWidgets.QListWidgetItem(display)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, row)
            self.machine_list.addItem(item)

        self._apply_filters()

    def _apply_filters(self) -> None:
        tier_filter = self.filter_tier_combo.currentText() if hasattr(self, "filter_tier_combo") else "All tiers"
        unlocked_only = bool(self.filter_unlocked_cb.isChecked()) if hasattr(self, "filter_unlocked_cb") else False
        enabled_tiers = set(self.app.get_enabled_tiers())
        search_text = (self.search_edit.text() or "").strip().lower() if hasattr(self, "search_edit") else ""
        any_visible = False
        for row_idx in range(self.machine_list.count()):
            item = self.machine_list.item(row_idx)
            row_state = item.data(QtCore.Qt.ItemDataRole.UserRole) or {}
            tier = (row_state.get("machine_tier") or "").strip()
            name = (row_state.get("name") or row_state.get("machine_type") or "").lower()
            matches = True
            if tier_filter and tier_filter != "All tiers":
                matches = tier == tier_filter
            if matches and unlocked_only:
                matches = tier in enabled_tiers
            if matches and search_text:
                matches = search_text in name
            item.setHidden(not matches)
            if matches:
                any_visible = True
        if not any_visible:
            self.details.clear()

    def _on_tier_filter_changed(self, value: str) -> None:
        if hasattr(self.app, "set_machine_tier_filter"):
            self.app.set_machine_tier_filter(value)
        self._apply_filters()

    def _on_unlocked_filter_toggled(self, checked: bool) -> None:
        if hasattr(self.app, "set_machine_unlocked_only"):
            self.app.set_machine_unlocked_only(checked)
        self._apply_filters()

    def _on_search_changed(self, value: str) -> None:
        if hasattr(self.app, "set_machine_search"):
            self.app.set_machine_search(value)
        self._apply_filters()

    def _on_machine_selected(self, row: int) -> None:
        if row < 0:
            self.details.clear()
            return
        item = self.machine_list.item(row)
        if item is None:
            self.details.clear()
            return
        machine = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not machine:
            self.details.clear()
            return
        self._render_machine_details(machine)

    def _render_machine_details(self, machine: dict[str, object]) -> None:
        name = machine.get("name") or machine.get("machine_type") or ""
        machine_type = machine.get("machine_type") or ""
        tier = machine.get("machine_tier") or ""
        availability = self.app.get_machine_availability(machine_type, tier)
        owned = availability.get("owned", 0)
        online = availability.get("online", 0)

        def _as_int(value, default=0):
            try:
                return int(value)
            except Exception:
                return default

        text = (
            f"Name: {name}\n"
            f"Machine Type: {machine_type}\n"
            f"Tier: {tier}\n"
            f"Owned: {owned}\n"
            f"Online: {online}\n"
            "\nMachine Specs\n"
            f"Input Slots: {_as_int(machine.get('machine_input_slots'), default=1) or 1}\n"
            f"Output Slots: {_as_int(machine.get('machine_output_slots'), default=1) or 1}\n"
            f"Byproduct Slots: {_as_int(machine.get('machine_byproduct_slots'))}\n"
            f"Storage Slots: {_as_int(machine.get('machine_storage_slots'))}\n"
            f"Power Slots: {_as_int(machine.get('machine_power_slots'))}\n"
            f"Circuit Slots: {_as_int(machine.get('machine_circuit_slots'))}\n"
            f"Input Tanks: {_as_int(machine.get('machine_input_tanks'))}\n"
            f"Input Tank Capacity (L): {_as_int(machine.get('machine_input_tank_capacity_l'))}\n"
            f"Output Tanks: {_as_int(machine.get('machine_output_tanks'))}\n"
            f"Output Tank Capacity (L): {_as_int(machine.get('machine_output_tank_capacity_l'))}\n"
            "EU/t: —\n"
        )
        self.details.setPlainText(text)

    def _open_availability_dialog(self, item: QtWidgets.QListWidgetItem) -> None:
        machine = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not machine:
            return
        if not machine.get("machine_type") or not machine.get("machine_tier"):
            QtWidgets.QMessageBox.information(
                self,
                "Missing machine info",
                "This machine is missing a type or tier.",
            )
            return
        dialog = MachineAvailabilityDialog(self.app, machine, parent=self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self._render_machine_details(machine)

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
