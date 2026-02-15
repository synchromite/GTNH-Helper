from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from services.db import ALL_TIERS
from ui_dialogs import MachineMetadataEditorDialog


class MachinesTab(QtWidgets.QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._machines: list[dict[str, object]] = []
        self._selected_machine: dict[str, object] | None = None
        self._sort_mode = self.app.get_machine_sort_mode() if hasattr(self.app, "get_machine_sort_mode") else "Machine (A→Z)"
        self._preferences_loaded = False

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        layout.addWidget(
            QtWidgets.QLabel(
                "Select a machine to view its metadata and specs."
            )
        )

        filters = QtWidgets.QHBoxLayout()
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
        content.addWidget(self.machine_list, stretch=0)

        right = QtWidgets.QVBoxLayout()
        content.addLayout(right, stretch=1)

        detail_controls = QtWidgets.QHBoxLayout()
        detail_controls.addWidget(QtWidgets.QLabel("Tier"))
        self.detail_tier_combo = QtWidgets.QComboBox()
        self.detail_tier_combo.currentTextChanged.connect(self._on_detail_tier_changed)
        detail_controls.addWidget(self.detail_tier_combo)
        detail_controls.addStretch(1)
        right.addLayout(detail_controls)

        self.details = QtWidgets.QTextEdit()
        self.details.setReadOnly(True)
        right.addWidget(self.details, stretch=1)

        self.empty_label = QtWidgets.QLabel(
            "No machines found in the content database.", alignment=QtCore.Qt.AlignmentFlag.AlignCenter
        )
        self.empty_label.setStyleSheet("color: #666;")
        right.addWidget(self.empty_label)

        btns = QtWidgets.QHBoxLayout()
        self.add_machine_type_btn = QtWidgets.QPushButton("Add Machine Type…")
        self.add_machine_type_btn.clicked.connect(self._open_add_machine_type_dialog)
        btns.addWidget(self.add_machine_type_btn)

        self.edit_machine_btn = QtWidgets.QPushButton("Edit Machine…")
        self.edit_machine_btn.clicked.connect(self._open_edit_selected_machine)
        self.edit_machine_btn.setEnabled(False)
        btns.addWidget(self.edit_machine_btn)

        btns.addStretch(1)
        right.addLayout(btns)

        if not self.app.editor_enabled:
            self.add_machine_type_btn.setEnabled(False)
            self.edit_machine_btn.setEnabled(False)

    def load_from_db(self) -> None:
        rows = self.app.conn.execute(
            """
            SELECT
                i.id,
                i.key,
                COALESCE(i.display_name, i.key) AS name,
                i.machine_type,
                i.machine_tier,
                i.is_multiblock,
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
        self._machines = self._group_machine_rows([dict(row) for row in rows])
        if not self._preferences_loaded:
            self._load_preferences()
        self._render_rows()

    def _group_machine_rows(self, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        grouped: dict[str, dict[str, object]] = {}
        for row in rows:
            machine_type = (row.get("machine_type") or "").strip()
            name = (row.get("name") or machine_type or "").strip()
            key = machine_type or name
            if not key:
                continue
            entry = grouped.setdefault(
                key,
                {
                    "machine_type": machine_type or name,
                    "label": machine_type or name or "(Unnamed machine)",
                    "tiers": [],
                    "tier_rows": {},
                },
            )
            tier = (row.get("machine_tier") or "").strip()
            if tier:
                if tier not in entry["tiers"]:
                    entry["tiers"].append(tier)
                entry["tier_rows"][tier] = row
        return list(grouped.values())

    def _sorted_tiers(self, tiers: list[str]) -> list[str]:
        tier_list = self._get_tier_list()
        tier_order = {tier: idx for idx, tier in enumerate(tier_list)}
        extras = sorted([tier for tier in tiers if tier not in tier_order])
        ordered = sorted([tier for tier in tiers if tier in tier_order], key=lambda t: tier_order[t])
        return ordered + extras

    def _load_preferences(self) -> None:
        self._preferences_loaded = True
        if hasattr(self.app, "get_machine_sort_mode"):
            self._sort_mode = self.app.get_machine_sort_mode()
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
        tier_list = self._get_tier_list()
        tier_order = {tier: idx for idx, tier in enumerate(tier_list)}

        def tier_key(value: str) -> tuple[int, str]:
            val = (value or "").strip()
            return (tier_order.get(val, len(tier_list)), val.lower())

        def group_tier_key(machine: dict[str, object], *, reverse: bool = False) -> tuple[int, str]:
            tiers = self._sorted_tiers(list(machine.get("tiers", [])))
            if not tiers:
                return (len(tier_list), "")
            tier = tiers[-1] if reverse else tiers[0]
            return tier_key(tier)

        if mode == "Machine (Z→A)":
            return sorted(rows, key=lambda r: (r.get("label") or "").lower(), reverse=True)
        if mode == "Tier (progression)":
            return sorted(
                rows,
                key=lambda r: (
                    group_tier_key(r),
                    (r.get("label") or "").lower(),
                ),
            )
        if mode == "Tier (reverse)":
            return sorted(
                rows,
                key=lambda r: (
                    group_tier_key(r, reverse=True),
                    (r.get("label") or "").lower(),
                ),
                reverse=True,
            )
        return sorted(rows, key=lambda r: (r.get("label") or "").lower())

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
            label = row.get("label") or row.get("machine_type") or "(Unnamed machine)"
            tiers = self._sorted_tiers(list(row.get("tiers", [])))
            tier_label = ", ".join(tiers)
            display = f"{label} ({tier_label})" if tiers else str(label)
            item = QtWidgets.QListWidgetItem(display)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, row)
            self.machine_list.addItem(item)

        self._apply_filters()

    def _apply_filters(self) -> None:
        unlocked_only = bool(self.filter_unlocked_cb.isChecked()) if hasattr(self, "filter_unlocked_cb") else False
        enabled_tiers = set(self.app.get_enabled_tiers())
        search_text = (self.search_edit.text() or "").strip().lower() if hasattr(self, "search_edit") else ""
        any_visible = False
        selected_row = self.machine_list.currentRow() if hasattr(self, "machine_list") else -1
        selected_hidden = False
        for row_idx in range(self.machine_list.count()):
            item = self.machine_list.item(row_idx)
            row_state = item.data(QtCore.Qt.ItemDataRole.UserRole) or {}
            tiers = [tier.strip() for tier in row_state.get("tiers", []) if tier]
            name = (row_state.get("label") or row_state.get("machine_type") or "").lower()
            matches = True
            if matches and unlocked_only:
                matches = bool(set(tiers) & enabled_tiers)
            if matches and search_text:
                matches = search_text in name
            item.setHidden(not matches)
            if matches:
                any_visible = True
            if row_idx == selected_row:
                selected_hidden = not matches
        if not any_visible:
            self.details.clear()
        if selected_hidden:
            self._selected_machine = None
            self.detail_tier_combo.clear()
            self.detail_tier_combo.setEnabled(False)
            self.details.clear()

    def _on_unlocked_filter_toggled(self, checked: bool) -> None:
        if hasattr(self.app, "set_machine_unlocked_only"):
            self.app.set_machine_unlocked_only(checked)
        self._apply_filters()
        self._refresh_detail_tier_selection()

    def _on_search_changed(self, value: str) -> None:
        if hasattr(self.app, "set_machine_search"):
            self.app.set_machine_search(value)
        self._apply_filters()

    def _on_machine_selected(self, row: int) -> None:
        if row < 0:
            self._selected_machine = None
            if hasattr(self, "edit_machine_btn"):
                self.edit_machine_btn.setEnabled(False)
            self.detail_tier_combo.clear()
            self.detail_tier_combo.setEnabled(False)
            self.details.clear()
            return
        item = self.machine_list.item(row)
        if item is None:
            self._selected_machine = None
            if hasattr(self, "edit_machine_btn"):
                self.edit_machine_btn.setEnabled(False)
            self.detail_tier_combo.clear()
            self.detail_tier_combo.setEnabled(False)
            self.details.clear()
            return
        machine = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not machine:
            self._selected_machine = None
            if hasattr(self, "edit_machine_btn"):
                self.edit_machine_btn.setEnabled(False)
            self.detail_tier_combo.clear()
            self.detail_tier_combo.setEnabled(False)
            self.details.clear()
            return
        self._selected_machine = machine
        if hasattr(self, "edit_machine_btn"):
            self.edit_machine_btn.setEnabled(bool(self.app.editor_enabled and machine.get("machine_type")))
        self._populate_detail_tiers(machine)

    def _open_add_machine_type_dialog(self) -> None:
        if not self.app.editor_enabled:
            QtWidgets.QMessageBox.information(
                self,
                "Editor locked",
                "Editing machine metadata is only available in editor mode.",
            )
            return

        dialog = AddMachineTypeDialog(self._get_tier_list(), parent=self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        machine_type = dialog.machine_type
        tiers = dialog.selected_tiers
        if not machine_type:
            return
        editor = MachineMetadataEditorDialog(
            self.app,
            parent=self,
            initial_machine_type=machine_type,
            initial_tiers=tiers,
        )
        if editor.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.load_from_db()
            self._select_machine_by_type(machine_type)
            if hasattr(self.app, "status_bar"):
                self.app.status_bar.showMessage("Updated machine metadata.")

    def _open_edit_selected_machine(self) -> None:
        if not self.app.editor_enabled:
            QtWidgets.QMessageBox.information(
                self,
                "Editor locked",
                "Editing machine metadata is only available in editor mode.",
            )
            return
        machine = self._selected_machine
        machine_type = (machine or {}).get("machine_type") if machine else ""
        machine_type = (machine_type or "").strip()
        if not machine_type:
            QtWidgets.QMessageBox.information(
                self,
                "No machine selected",
                "Select a machine type first.",
            )
            return
        editor = MachineMetadataEditorDialog(self.app, parent=self, initial_machine_type=machine_type)
        if editor.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.load_from_db()
            self._select_machine_by_type(machine_type)
            if hasattr(self.app, "status_bar"):
                self.app.status_bar.showMessage("Updated machine metadata.")

    def _select_machine_by_type(self, machine_type: str) -> None:
        machine_type = (machine_type or "").strip()
        if not machine_type:
            return
        for row in range(self.machine_list.count()):
            item = self.machine_list.item(row)
            if item is None or item.isHidden():
                continue
            data = item.data(QtCore.Qt.ItemDataRole.UserRole) or {}
            if (data.get("machine_type") or "").strip() == machine_type:
                self.machine_list.setCurrentRow(row)
                return

    def _populate_detail_tiers(self, machine: dict[str, object]) -> None:
        tiers = self._sorted_tiers(list(machine.get("tiers", [])))
        chosen_tier = self._pick_detail_tier(tiers)
        self.detail_tier_combo.blockSignals(True)
        self.detail_tier_combo.clear()
        self.detail_tier_combo.addItems(tiers)
        self.detail_tier_combo.setEnabled(bool(tiers))
        if chosen_tier:
            self.detail_tier_combo.setCurrentText(chosen_tier)
        self.detail_tier_combo.blockSignals(False)
        if chosen_tier:
            self._render_machine_details(machine, chosen_tier)
        else:
            self.details.clear()

    def _pick_detail_tier(self, tiers: list[str]) -> str | None:
        if not tiers:
            return None
        if self.filter_unlocked_cb.isChecked() if hasattr(self, "filter_unlocked_cb") else False:
            enabled_tiers = set(self.app.get_enabled_tiers())
            for tier in tiers:
                if tier in enabled_tiers:
                    return tier
        return tiers[0]

    def _refresh_detail_tier_selection(self) -> None:
        if not self._selected_machine:
            return
        tiers = self._sorted_tiers(list(self._selected_machine.get("tiers", [])))
        chosen_tier = self._pick_detail_tier(tiers)
        if not chosen_tier:
            return
        if self.detail_tier_combo.currentText() != chosen_tier:
            self.detail_tier_combo.blockSignals(True)
            self.detail_tier_combo.setCurrentText(chosen_tier)
            self.detail_tier_combo.blockSignals(False)
        self._render_machine_details(self._selected_machine, chosen_tier)

    def _on_detail_tier_changed(self, tier: str) -> None:
        if not self._selected_machine:
            return
        if not tier:
            self.details.clear()
            return
        self._render_machine_details(self._selected_machine, tier)

    def _render_machine_details(self, machine: dict[str, object], tier: str) -> None:
        machine_type = machine.get("machine_type") or ""
        label = machine.get("label") or machine_type or ""
        row = (machine.get("tier_rows") or {}).get(tier, {})
        item_name = row.get("name") or label
        def _as_int(value, default=0):
            try:
                return int(value)
            except Exception:
                return default

        text = (
            f"Machine: {label}\n"
            f"Item Name: {item_name}\n"
            f"Machine Type: {machine_type}\n"
            f"Tier: {tier}\n"
            f"Multi-block: {'Yes' if row.get('is_multiblock') else 'No'}\n"
            "\nMachine Specs\n"
            f"Input Slots: {_as_int(row.get('machine_input_slots'), default=1) or 1}\n"
            f"Output Slots: {_as_int(row.get('machine_output_slots'), default=1) or 1}\n"
            f"Byproduct Slots: {_as_int(row.get('machine_byproduct_slots'))}\n"
            f"Storage Slots: {_as_int(row.get('machine_storage_slots'))}\n"
            f"Power Slots: {_as_int(row.get('machine_power_slots'))}\n"
            f"Circuit Slots: {_as_int(row.get('machine_circuit_slots'))}\n"
            f"Input Tanks: {_as_int(row.get('machine_input_tanks'))}\n"
            f"Input Tank Capacity (L): {_as_int(row.get('machine_input_tank_capacity_l'))}\n"
            f"Output Tanks: {_as_int(row.get('machine_output_tanks'))}\n"
            f"Output Tank Capacity (L): {_as_int(row.get('machine_output_tank_capacity_l'))}\n"
            "EU/t: —\n"
        )
        self.details.setPlainText(text)

    def _get_tier_list(self) -> list[str]:
        if hasattr(self.app, "get_all_tiers"):
            return list(self.app.get_all_tiers())
        return list(ALL_TIERS)


class AddMachineTypeDialog(QtWidgets.QDialog):
    def __init__(self, tiers: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Machine Type")
        self.setModal(True)
        self.resize(420, 460)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Create a new machine metadata type and select available tiers."))

        form = QtWidgets.QGridLayout()
        form.addWidget(QtWidgets.QLabel("Machine Type"), 0, 0)
        self.machine_type_edit = QtWidgets.QLineEdit()
        self.machine_type_edit.setPlaceholderText("e.g. Cutting Machine")
        form.addWidget(self.machine_type_edit, 0, 1)
        layout.addLayout(form)

        layout.addWidget(QtWidgets.QLabel("Available Tiers"))
        self.tier_list = QtWidgets.QListWidget()
        self.tier_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        for tier in tiers:
            item = QtWidgets.QListWidgetItem(tier)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.CheckState.Unchecked)
            self.tier_list.addItem(item)
        layout.addWidget(self.tier_list, stretch=1)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self.machine_type: str = ""
        self.selected_tiers: list[str] = []

    def _save(self) -> None:
        machine_type = (self.machine_type_edit.text() or "").strip()
        if not machine_type:
            QtWidgets.QMessageBox.warning(self, "Missing machine type", "Enter a machine type.")
            return
        selected_tiers: list[str] = []
        for idx in range(self.tier_list.count()):
            item = self.tier_list.item(idx)
            if item and item.checkState() == QtCore.Qt.CheckState.Checked:
                selected_tiers.append(item.text().strip())
        if not selected_tiers:
            QtWidgets.QMessageBox.warning(self, "No tiers selected", "Select at least one tier.")
            return
        self.machine_type = machine_type
        self.selected_tiers = selected_tiers
        self.accept()
