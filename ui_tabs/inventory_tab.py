from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from services.storage import (
    aggregate_assignment_for_item,
    default_storage_id,
    delete_assignment,
    get_assignment,
    placed_container_count,
    storage_inventory_totals,
    upsert_assignment,
    validate_storage_fit_for_item,
    recompute_storage_slot_capacities,
    set_storage_container_placement,
    list_storage_container_placements,
)
from ui_dialogs import StorageUnitsDialog


class InventoryTab(QtWidgets.QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.items: list = []
        self.items_by_id: dict[int, dict] = {}
        self._machine_availability_target: dict[str, str] | None = None
        self.machine_availability_checks: list[QtWidgets.QCheckBox] = []
        self.storage_units: list[dict[str, int | str]] = []


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

        storage_row = QtWidgets.QHBoxLayout()
        right.addLayout(storage_row)
        storage_row.addWidget(QtWidgets.QLabel("Storage:"))
        self.storage_selector = QtWidgets.QComboBox()
        self.storage_selector.currentIndexChanged.connect(self._on_storage_changed)
        storage_row.addWidget(self.storage_selector)
        self.manage_storage_button = QtWidgets.QPushButton("Manage…")
        self.manage_storage_button.clicked.connect(self._open_storage_manager)
        storage_row.addWidget(self.manage_storage_button)
        storage_row.addStretch(1)

        self.enable_inventory_management = QtWidgets.QCheckBox("Enable inventory capacity management")
        self.enable_inventory_management.toggled.connect(self._on_inventory_management_toggled)
        right.addWidget(self.enable_inventory_management)

        self.filter_to_selected_storage = QtWidgets.QCheckBox("Filter item list to selected storage")
        self.filter_to_selected_storage.toggled.connect(self._on_filter_to_storage_toggled)
        right.addWidget(self.filter_to_selected_storage)

        self.storage_mode_label = QtWidgets.QLabel("")
        self.storage_mode_label.setStyleSheet("color: #666;")
        right.addWidget(self.storage_mode_label)

        self.storage_totals_label = QtWidgets.QLabel("")
        self.storage_totals_label.setStyleSheet("color: #666;")
        right.addWidget(self.storage_totals_label)

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

        self.machine_availability_group = QtWidgets.QGroupBox("Machine Availability")
        availability_layout = QtWidgets.QVBoxLayout(self.machine_availability_group)
        self.machine_availability_status = QtWidgets.QLabel("")
        self.machine_availability_status.setStyleSheet("color: #666;")
        availability_layout.addWidget(self.machine_availability_status)
        self.machine_availability_container = QtWidgets.QWidget()
        self.machine_availability_list = QtWidgets.QVBoxLayout(self.machine_availability_container)
        self.machine_availability_list.setContentsMargins(0, 0, 0, 0)
        availability_scroll = QtWidgets.QScrollArea()
        availability_scroll.setWidgetResizable(True)
        availability_scroll.setWidget(self.machine_availability_container)
        availability_layout.addWidget(availability_scroll)
        self.machine_availability_group.setVisible(False)
        right.addWidget(self.machine_availability_group)

        self.container_placement_group = QtWidgets.QGroupBox("Container Placement")
        container_layout = QtWidgets.QGridLayout(self.container_placement_group)
        self.container_placement_note = QtWidgets.QLabel("")
        self.container_placement_note.setWordWrap(True)
        self.container_placement_note.setStyleSheet("color: #666;")
        container_layout.addWidget(self.container_placement_note, 0, 0, 1, 3)
        container_layout.addWidget(QtWidgets.QLabel("Target Storage:"), 1, 0)
        self.container_target_storage = QtWidgets.QComboBox()
        container_layout.addWidget(self.container_target_storage, 1, 1, 1, 2)
        container_layout.addWidget(QtWidgets.QLabel("Placed:"), 2, 0)
        self.container_placed_spin = QtWidgets.QSpinBox()
        self.container_placed_spin.setRange(0, 1_000_000)
        container_layout.addWidget(self.container_placed_spin, 2, 1)
        self.container_apply_button = QtWidgets.QPushButton("Apply placement")
        self.container_apply_button.clicked.connect(self._apply_container_placement)
        container_layout.addWidget(self.container_apply_button, 2, 2)
        self.container_placement_group.setVisible(False)
        right.addWidget(self.container_placement_group)

        tip = QtWidgets.QLabel("Tip: items use counts; fluids and gases use liters (L).")
        tip.setStyleSheet("color: #666;")
        right.addWidget(tip)
        right.addStretch(1)

    def render_items(self, items: list) -> None:
        self._refresh_storage_selector()
        self._sync_inventory_management_toggle()
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

    def _refresh_storage_selector(self) -> None:
        if hasattr(self.app, "list_storage_units"):
            self.storage_units = list(self.app.list_storage_units())
        else:
            self.storage_units = [{"id": 1, "name": "Main Storage"}]

        self.storage_selector.blockSignals(True)
        self.storage_selector.clear()
        self.storage_selector.addItem("All Storages (Aggregate)", None)
        for storage in self.storage_units:
            self.storage_selector.addItem(str(storage["name"]), int(storage["id"]))

        active_storage_id = self.app.get_active_storage_id() if hasattr(self.app, "get_active_storage_id") else None
        index = 0
        if active_storage_id is not None:
            for idx in range(self.storage_selector.count()):
                if self.storage_selector.itemData(idx) == active_storage_id:
                    index = idx
                    break
        self.storage_selector.setCurrentIndex(index)
        self.storage_selector.blockSignals(False)

        self.container_target_storage.blockSignals(True)
        self.container_target_storage.clear()
        for storage in self.storage_units:
            self.container_target_storage.addItem(str(storage["name"]), int(storage["id"]))
        if self.container_target_storage.count() > 0 and index > 0:
            self.container_target_storage.setCurrentIndex(min(index - 1, self.container_target_storage.count() - 1))
        self.container_target_storage.blockSignals(False)

        self._set_inventory_edit_mode()
        self._refresh_summary_panel()

    def _inventory_management_enabled(self) -> bool:
        row = self.app.profile_conn.execute(
            "SELECT value FROM app_settings WHERE key='inventory_management_enabled'"
        ).fetchone()
        return str((row["value"] if row else "0") or "0").strip() == "1"

    def _sync_inventory_management_toggle(self) -> None:
        enabled = self._inventory_management_enabled()
        self.enable_inventory_management.blockSignals(True)
        self.enable_inventory_management.setChecked(enabled)
        self.enable_inventory_management.blockSignals(False)
        if enabled:
            recompute_storage_slot_capacities(self.app.profile_conn, player_slots=36, content_conn=self.app.conn)
            self.app.profile_conn.commit()

    def _on_inventory_management_toggled(self, checked: bool) -> None:
        self.app.profile_conn.execute(
            "INSERT INTO app_settings(key, value) VALUES('inventory_management_enabled', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("1" if checked else "0",),
        )
        if checked:
            recompute_storage_slot_capacities(self.app.profile_conn, player_slots=36, content_conn=self.app.conn)
        self.app.profile_conn.commit()
        self._refresh_storage_selector()
        current = self._current_tree().currentItem()
        self.on_inventory_select(current, None)

    def _on_filter_to_storage_toggled(self, _checked: bool) -> None:
        selected_id = self._selected_item_id()
        for tree in self.inventory_trees.values():
            self._render_tree(tree, selected_id)
        current = self._current_tree().currentItem()
        self.on_inventory_select(current, None)

    def _current_storage_id(self) -> int | None:
        value = self.storage_selector.currentData()
        if value is None:
            return None
        return int(value)

    def _is_aggregate_mode(self) -> bool:
        return self._current_storage_id() is None

    def _set_inventory_edit_mode(self) -> None:
        aggregate = self._is_aggregate_mode()
        self.inventory_qty_entry.setReadOnly(aggregate)
        self.btn_save.setEnabled(not aggregate)
        self.btn_clear.setEnabled(not aggregate)
        for checkbox in self.machine_availability_checks:
            checkbox.setEnabled(not aggregate)
        if aggregate:
            self.storage_mode_label.setText("Aggregate mode is read-only.")
        else:
            self.storage_mode_label.setText("")

    def _on_storage_changed(self, _index: int) -> None:
        storage_id = self._current_storage_id()
        if storage_id is not None and hasattr(self.app, "set_active_storage_id"):
            self.app.set_active_storage_id(storage_id)
        self._set_inventory_edit_mode()
        self._refresh_summary_panel()
        if self.filter_to_selected_storage.isChecked():
            selected_id = self._selected_item_id()
            for tree in self.inventory_trees.values():
                self._render_tree(tree, selected_id)
        current = self._current_tree().currentItem()
        self.on_inventory_select(current, None)

    def _open_storage_manager(self) -> None:
        dialog = StorageUnitsDialog(self.app, parent=self)
        dialog.exec()
        self._refresh_storage_selector()
        self._refresh_summary_panel()
        current = self._current_tree().currentItem()
        self.on_inventory_select(current, None)

    def _refresh_summary_panel(self) -> None:
        storage_id = self._current_storage_id()
        aggregate_totals = storage_inventory_totals(self.app.profile_conn, None)
        if storage_id is None:
            self.storage_totals_label.setText(
                "Aggregate totals: "
                f"{aggregate_totals['entry_count']} entries, "
                f"{aggregate_totals['total_count']} count, "
                f"{aggregate_totals['total_liters']} L"
            )
            return
        selected = storage_inventory_totals(self.app.profile_conn, storage_id)
        self.storage_totals_label.setText(
            "Selected storage: "
            f"{selected['entry_count']} entries, "
            f"{selected['total_count']} count, "
            f"{selected['total_liters']} L "
            "| Aggregate: "
            f"{aggregate_totals['entry_count']} entries, "
            f"{aggregate_totals['total_count']} count, "
            f"{aggregate_totals['total_liters']} L"
        )

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
            self._set_machine_availability_target(None)
            self.container_placement_group.setVisible(False)
            return
        item_id = current.data(0, QtCore.Qt.UserRole)
        if item_id is None:
            self.inventory_item_name.setText("")
            self.inventory_unit_label.setText("")
            self.inventory_qty_entry.setText("")
            self._set_machine_availability_target(None)
            self.container_placement_group.setVisible(False)
            return
        item = self.items_by_id.get(int(item_id))
        if item is None:
            self.inventory_item_name.setText("")
            self.inventory_unit_label.setText("")
            self.inventory_qty_entry.setText("")
            self._set_machine_availability_target(None)
            self.container_placement_group.setVisible(False)
            return
        self.inventory_item_name.setText(item["name"])
        unit = self._inventory_unit_for_item(item)
        self.inventory_unit_label.setText(unit)

        storage_id = self._current_storage_id()
        if storage_id is None:
            db_row = aggregate_assignment_for_item(self.app.profile_conn, item["id"])
        else:
            db_row = get_assignment(self.app.profile_conn, storage_id=storage_id, item_id=item["id"])
        if unit == "L":
            qty = db_row["qty_liters"] if db_row else None
        else:
            qty = db_row["qty_count"] if db_row else None
        self.inventory_qty_entry.setText("" if qty is None else self._format_inventory_qty(qty))
        self._sync_machine_availability(item, qty)
        self._refresh_container_placement_panel(item, qty)

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

        if self._is_aggregate_mode():
            QtWidgets.QMessageBox.information(self, "Aggregate mode", "Switch to a specific storage to edit quantities.")
            return

        storage_id = self._current_storage_id()
        raw = self.inventory_qty_entry.text().strip()
        if raw == "":
            delete_assignment(self.app.profile_conn, storage_id=storage_id, item_id=item["id"])
            self.app.profile_conn.commit()
            self.app.status_bar.showMessage(f"Cleared inventory for: {item['name']}")
            self.app.notify_inventory_change()
            self._refresh_summary_panel()
            if self._is_machine_item(item):
                self._save_machine_availability(item, owned=0, online=0)
            self._sync_container_storage_after_inventory_save(item, qty=0)
            self._refresh_container_placement_panel(item, 0)
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
        if qty < 0:
            QtWidgets.QMessageBox.critical(self, "Invalid quantity", "Quantity cannot be negative.")
            return

        unit = self._inventory_unit_for_item(item)
        qty_count = qty if unit == "count" else None
        qty_liters = qty if unit == "L" else None

        if self._inventory_management_enabled():
            stack_sizes = {
                int(candidate["id"]): max(1, int(self._item_value(candidate, "max_stack_size") or 64))
                for candidate in self.items
            }
            container_ids = {
                int(candidate["id"])
                for candidate in self.items
                if int(self._item_value(candidate, "is_storage_container") or 0)
            }
            fit = validate_storage_fit_for_item(
                self.app.profile_conn,
                storage_id=storage_id,
                item_id=item["id"],
                qty_count=qty_count,
                qty_liters=qty_liters,
                item_max_stack_size=max(1, int(self._item_value(item, "max_stack_size") or 64)),
                known_item_stack_sizes=stack_sizes,
                known_container_item_ids=container_ids,
            )
            if not fit["fits"]:
                reasons: list[str] = []
                if not fit["fits_slots"]:
                    reasons.append(
                        f"slots {fit['slot_usage']}/{fit['slot_count']} (overflow +{fit['slot_overflow']})"
                    )
                if not fit["fits_liters"]:
                    reasons.append(
                        f"liters {int(round(float(fit['liter_usage'])))}"
                        f"/{int(round(float(fit['liter_capacity'])))}"
                        f" (overflow +{int(round(float(fit['liter_overflow'])))} L)"
                    )
                self._show_storage_capacity_warning(reasons)
                return

        upsert_assignment(
            self.app.profile_conn,
            storage_id=storage_id,
            item_id=item["id"],
            qty_count=qty_count,
            qty_liters=qty_liters,
        )
        self.app.profile_conn.commit()
        self.inventory_qty_entry.setText(str(qty))
        self.app.status_bar.showMessage(f"Saved inventory for: {item['name']}")
        self.app.notify_inventory_change()
        self._refresh_summary_panel()
        if self._is_machine_item(item):
            online = min(self._current_online_count(), qty)
            self._save_machine_availability(item, owned=qty, online=online)
            self._render_machine_availability(item, qty, online)
        self._sync_container_storage_after_inventory_save(item, qty=qty)
        self._refresh_container_placement_panel(item, qty)

    def _show_storage_capacity_warning(self, reasons: list[str]) -> None:
        message = "Cannot save inventory for this storage:\n- " + "\n- ".join(reasons)
        dialog = QtWidgets.QMessageBox(self)
        dialog.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Storage capacity exceeded")
        dialog.setText(message)
        dialog.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        dialog.setTextFormat(QtCore.Qt.TextFormat.PlainText)

        # Allow the dialog to size to content so multi-line warnings are readable.
        dialog.setSizeGripEnabled(True)
        longest_line = max((len(line) for line in message.splitlines()), default=40)
        approx_width = max(420, min(980, int(longest_line * 7.2) + 80))
        dialog.setMinimumWidth(approx_width)

        label = dialog.findChild(QtWidgets.QLabel, "qt_msgbox_label")
        if label is not None:
            label.setWordWrap(True)
            label.setMinimumWidth(approx_width - 50)

        layout = dialog.layout()
        if layout is not None:
            layout.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetMinimumSize)
        dialog.adjustSize()
        dialog.exec()


    def clear_inventory_item(self) -> None:
        self.inventory_qty_entry.setText("")
        self.save_inventory_item()


    def _storage_row_by_id(self, storage_id: int | None) -> dict | None:
        if storage_id is None:
            return None
        for row in self.storage_units:
            if int(row.get("id") or 0) == int(storage_id):
                return row
        return None

    def _is_storage_container_item(self, item: dict | None) -> bool:
        if not item:
            return False
        return bool(int(self._item_value(item, "is_storage_container") or 0))

    def _container_slot_count_for_item(self, item: dict) -> int:
        return max(0, int(self._item_value(item, "storage_slot_count") or 0))

    def _refresh_container_placement_panel(self, item: dict | None, qty) -> None:
        storage_id = self._current_storage_id()
        if storage_id is None or not self._is_storage_container_item(item):
            self.container_placement_group.setVisible(False)
            return

        main_storage_id = default_storage_id(self.app.profile_conn)
        main_row = None
        if main_storage_id is not None:
            main_row = get_assignment(self.app.profile_conn, storage_id=int(main_storage_id), item_id=int(item["id"]))
        owned_total = max(0, int(float((main_row["qty_count"] if main_row else 0) or 0)))

        # Keep target selector synced to currently selected storage by default.
        target_storage_id = self.container_target_storage.currentData()
        if target_storage_id is None:
            target_storage_id = storage_id
        target_storage_id = int(target_storage_id)

        placement_rows = {
            int(r["item_id"]): int(r.get("placed_count") or 0)
            for r in list_storage_container_placements(self.app.profile_conn, target_storage_id)
        }
        placed_current = placement_rows.get(int(item["id"]), 0)
        placed_current = min(placed_current, owned_total)

        self.container_placed_spin.blockSignals(True)
        self.container_placed_spin.setMaximum(owned_total)
        self.container_placed_spin.setValue(placed_current)
        self.container_placed_spin.blockSignals(False)

        slot_count = self._container_slot_count_for_item(item)
        target_name = self.container_target_storage.currentText() or "Selected Storage"
        self.container_placement_note.setText(
            f"Owned total (Main Storage): {owned_total}. "
            f"Target storage: {target_name}. "
            f"Slots per container: {slot_count}. "
            f"Usable slots from placed: {placed_current * slot_count}."
        )
        self.container_apply_button.setEnabled(not self._is_aggregate_mode())
        self.container_placement_group.setVisible(True)

    def _sync_container_storage_after_inventory_save(self, item: dict, *, qty: int) -> None:
        if not self._is_storage_container_item(item):
            return
        storage_id = self._current_storage_id()
        if storage_id is None:
            return

        # Main Storage owns container inventory; ensure baseline slots when capacity management is enabled.
        if self._inventory_management_enabled():
            recompute_storage_slot_capacities(self.app.profile_conn, player_slots=36, content_conn=self.app.conn)
        self.app.profile_conn.commit()
        self.storage_units = list(self.app.list_storage_units()) if hasattr(self.app, "list_storage_units") else self.storage_units
        self._refresh_summary_panel()

    def _apply_container_placement(self) -> None:
        item = self._inventory_selected_item()
        if not self._is_storage_container_item(item):
            self.container_placement_group.setVisible(False)
            return

        main_storage_id = default_storage_id(self.app.profile_conn)
        if main_storage_id is None:
            return

        target_storage_id = self.container_target_storage.currentData()
        if target_storage_id is None:
            target_storage_id = self._current_storage_id()
        if target_storage_id is None:
            return
        target_storage_id = int(target_storage_id)

        main_row = get_assignment(self.app.profile_conn, storage_id=int(main_storage_id), item_id=int(item["id"]))
        owned_total = max(0, int(float((main_row["qty_count"] if main_row else 0) or 0)))
        requested = self.container_placed_spin.value()
        already_elsewhere = placed_container_count(
            self.app.profile_conn,
            item_id=int(item["id"]),
            exclude_storage_id=target_storage_id,
        )
        max_allowed_here = max(0, owned_total - already_elsewhere)
        if requested > max_allowed_here:
            QtWidgets.QMessageBox.warning(
                self,
                "Placement exceeds owned",
                (
                    f"You own {owned_total} total '{item['name']}' in Main Storage, "
                    f"with {already_elsewhere} already placed in other storages.\n\n"
                    f"Max placeable in this storage: {max_allowed_here}."
                ),
            )
            return
        placed = requested

        set_storage_container_placement(
            self.app.profile_conn,
            storage_id=target_storage_id,
            item_id=int(item["id"]),
            placed_count=placed,
        )

        # Placed containers are storage space, not inventory entries in that storage.
        if target_storage_id != int(main_storage_id):
            delete_assignment(self.app.profile_conn, storage_id=target_storage_id, item_id=int(item["id"]))

        if self._inventory_management_enabled():
            recompute_storage_slot_capacities(self.app.profile_conn, player_slots=36, content_conn=self.app.conn)

        self.app.profile_conn.commit()
        if hasattr(self.app, "list_storage_units"):
            self.storage_units = list(self.app.list_storage_units())
        self._refresh_summary_panel()
        self._refresh_container_placement_panel(item, owned_total)
        self.app.status_bar.showMessage(
            f"Updated container placement for {item['name']}: {placed}/{owned_total} placed"
        )

    def _on_search_changed(self, _text: str) -> None:
        selected_id = self._selected_item_id()
        for tree in self.inventory_trees.values():
            self._render_tree(tree, selected_id)
        current = self._current_tree().currentItem()
        self.on_inventory_select(current, None)

    def _on_tab_changed(self, _index: int) -> None:
        tree = self._current_tree()
        current = tree.currentItem()
        self.on_inventory_select(current, None)

    def _is_machine_item(self, item: dict) -> bool:
        kind_val = (self._item_value(item, "kind") or "").strip().lower()
        item_kind_val = (self._item_value(item, "item_kind_name") or "").strip().lower()
        is_machine_flag = bool(self._item_value(item, "is_machine"))
        return kind_val == "machine" or item_kind_val == "machine" or is_machine_flag

    def _set_machine_availability_target(self, target: dict[str, str] | None) -> None:
        self._machine_availability_target = target
        if target is None:
            self.machine_availability_group.setVisible(False)
            self._clear_machine_availability_checks()

    def _clear_machine_availability_checks(self) -> None:
        self.machine_availability_checks = []
        while self.machine_availability_list.count():
            item = self.machine_availability_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _sync_machine_availability(self, item: dict, qty) -> None:
        if not self._is_machine_item(item):
            self._set_machine_availability_target(None)
            return
        machine_type = (self._item_value(item, "machine_type") or "").strip()
        machine_tier = (self._item_value(item, "machine_tier") or "").strip()
        if not machine_type or not machine_tier:
            self._set_machine_availability_target(None)
            return
        owned = int(qty or 0)
        availability = (
            self.app.get_machine_availability(machine_type, machine_tier)
            if hasattr(self.app, "get_machine_availability")
            else {"owned": 0, "online": 0}
        )
        online = min(int(availability.get("online", 0)), owned)
        self._set_machine_availability_target({"machine_type": machine_type, "machine_tier": machine_tier})
        self._render_machine_availability(item, owned, online)

    def _render_machine_availability(self, item: dict, owned: int, online: int) -> None:
        self._clear_machine_availability_checks()
        if not self._is_machine_item(item):
            self._set_machine_availability_target(None)
            return
        self.machine_availability_group.setVisible(True)
        if owned <= 0:
            self.machine_availability_status.setText("Set a quantity to track which machines are online.")
            return
        aggregate = self._is_aggregate_mode()
        suffix = " (read-only in aggregate mode)" if aggregate else ""
        self.machine_availability_status.setText(f"Online: {online} of {owned}{suffix}")
        for idx in range(owned):
            checkbox = QtWidgets.QCheckBox(f"Machine {idx + 1}")
            checkbox.setChecked(idx < online)
            checkbox.toggled.connect(self._on_machine_online_changed)
            checkbox.setEnabled(not aggregate)
            self.machine_availability_list.addWidget(checkbox)
            self.machine_availability_checks.append(checkbox)
        self.machine_availability_list.addStretch(1)

    def _current_online_count(self) -> int:
        return sum(1 for checkbox in self.machine_availability_checks if checkbox.isChecked())

    def _save_machine_availability(self, item: dict, *, owned: int, online: int) -> None:
        machine_type = (self._item_value(item, "machine_type") or "").strip()
        machine_tier = (self._item_value(item, "machine_tier") or "").strip()
        if not machine_type or not machine_tier:
            return
        if online > owned:
            online = owned
        if hasattr(self.app, "set_machine_availability"):
            self.app.set_machine_availability([(machine_type, machine_tier, owned, online)])

    def _on_machine_online_changed(self, _checked: bool) -> None:
        if self._is_aggregate_mode():
            return
        if not self._machine_availability_target:
            return
        owned = len(self.machine_availability_checks)
        online = min(self._current_online_count(), owned)
        self.machine_availability_status.setText(f"Online: {online} of {owned}")
        if hasattr(self.app, "set_machine_availability"):
            self.app.set_machine_availability(
                [
                    (
                        self._machine_availability_target["machine_type"],
                        self._machine_availability_target["machine_tier"],
                        owned,
                        online,
                    )
                ]
            )

    def _filtered_items(self, kind_filter: str | None) -> list[dict]:
        query = self.search_entry.text().strip().lower()
        items = self.items
        if kind_filter:
            items = [
                it
                for it in items
                if (self._item_value(it, "kind") or "").strip().lower() == kind_filter
            ]
        if self.filter_to_selected_storage.isChecked() and not self._is_aggregate_mode():
            storage_id = self._current_storage_id()
            assigned_ids = {
                int(row["item_id"])
                for row in self.app.profile_conn.execute(
                    "SELECT item_id FROM storage_assignments WHERE storage_id=?",
                    (storage_id,),
                ).fetchall()
            }
            items = [it for it in items if int(it["id"]) in assigned_ids]

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
            query = self.search_entry.text().strip()
            kind_filter = tree.property("kind_filter")
            items = self._filtered_items(kind_filter)
            kind_nodes: dict[str, QtWidgets.QTreeWidgetItem] = {}
            item_kind_nodes: dict[tuple[str, str], QtWidgets.QTreeWidgetItem] = {}
            material_nodes: dict[tuple[str, str, str], QtWidgets.QTreeWidgetItem] = {}
            id_nodes: dict[int, QtWidgets.QTreeWidgetItem] = {}

            def _label(value: str | None, fallback: str) -> str:
                if value is None:
                    return fallback
                value = value.strip().replace("_", " ")
                return value if value else fallback

            def _sort_key(it: dict) -> tuple[str, str, str, str]:
                kind_raw = (self._item_value(it, "kind") or "").strip().lower()
                grid_size_raw = (self._item_value(it, "crafting_grid_size") or "").strip().lower()
                if kind_raw == "crafting_grid":
                    return (
                        kind_raw,
                        grid_size_raw,
                        "",
                        (self._item_value(it, "name") or "").strip().lower(),
                    )
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
                if (kind_val or "").strip().lower() == "crafting_grid":
                    grid_size_val = self._item_value(it, "crafting_grid_size")
                    item_kind_label = _label(grid_size_val, "(No grid size)")
                use_item_kind_grouping = self._use_item_kind_grouping(kind_val)

                raw_mat_name = self._item_value(it, "material_name")
                has_material = raw_mat_name and raw_mat_name.strip()
                if (kind_val or "").strip().lower() == "machine":
                    has_material = False
                if (kind_val or "").strip().lower() == "crafting_grid":
                    has_material = False

                kind_item = kind_nodes.get(kind_label)
                if kind_item is None:
                    kind_item = QtWidgets.QTreeWidgetItem([kind_label])
                    tree.addTopLevelItem(kind_item)
                    kind_nodes[kind_label] = kind_item

                if use_item_kind_grouping:
                    item_kind_key = (kind_label, item_kind_label)
                    item_kind_item = item_kind_nodes.get(item_kind_key)
                    if item_kind_item is None:
                        item_kind_item = QtWidgets.QTreeWidgetItem([item_kind_label])
                        kind_item.addChild(item_kind_item)
                        item_kind_nodes[item_kind_key] = item_kind_item
                else:
                    item_kind_item = kind_item

                if has_material:
                    material_label = raw_mat_name.strip()
                    material_key = (kind_label, item_kind_label if use_item_kind_grouping else None, material_label)
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

            if query:
                tree.expandAll()
            else:
                tree.collapseAll()
        finally:
            tree.blockSignals(False)

    @staticmethod
    def _use_item_kind_grouping(kind_val: str | None) -> bool:
        return (kind_val or "").strip().lower() != "gas"

    @staticmethod
    def _item_value(item, key: str):
        try:
            return item[key]
        except Exception:
            return None
