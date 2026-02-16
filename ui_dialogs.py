#!/usr/bin/env python3
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from services.db import ALL_TIERS
from services.machines import fetch_machine_metadata, replace_machine_metadata
from services.materials import add_material, delete_material, fetch_materials, update_material
from services.storage import (
    create_storage_unit,
    delete_storage_unit,
    list_storage_container_placements,
    list_storage_units,
    recompute_storage_slot_capacities,
    set_storage_container_placement,
    update_storage_unit,
)


def _row_get(row, key: str, default=None):
    """Safe key access for sqlite3.Row/dicts."""
    try:
        if row is None:
            return default
        if hasattr(row, "keys") and key in row.keys():
            return row[key]
        if hasattr(row, "get"):
            return row.get(key, default)
        return row[key]
    except Exception:
        return default


TPS = 20  # Minecraft target ticks per second

# User-facing label for "no tier" (stored as NULL in DB)
NONE_TIER_LABEL = "— none —"

# Separate label for Item Kind "none" (stored as NULL)
NONE_KIND_LABEL = "— none —"

NONE_MATERIAL_LABEL = "(None)"
NONE_FLUID_LABEL = "(None)"

ADD_NEW_KIND_LABEL = "+ Add new…"


class StorageUnitDialog(QtWidgets.QDialog):
    def __init__(self, app, *, storage: dict | None = None, parent=None):
        super().__init__(parent)
        self.app = app
        self.storage = storage
        self.result_data: dict | None = None
        self.setWindowTitle("Edit Storage" if storage else "Create Storage")
        self.resize(460, 360)

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        self.name_edit = QtWidgets.QLineEdit((storage or {}).get("name", ""))
        form.addRow("Name", self.name_edit)

        self.kind_edit = QtWidgets.QLineEdit((storage or {}).get("kind", "generic"))
        form.addRow("Kind", self.kind_edit)

        self.slot_spin = QtWidgets.QSpinBox()
        self.slot_spin.setRange(0, 1_000_000)
        self.slot_spin.setSpecialValueText("(unset)")
        self.slot_spin.setValue(int((storage or {}).get("slot_count") or 0))
        form.addRow("Slot Count", self.slot_spin)

        self.container_item_combo = QtWidgets.QComboBox()
        self.container_item_combo.addItem("(None)", None)
        self._container_item_slots: dict[int, int] = {}
        for row in self.app.conn.execute(
            "SELECT id, COALESCE(display_name, key) AS name, storage_slot_count FROM items WHERE COALESCE(is_storage_container, 0)=1 ORDER BY name"
        ).fetchall():
            item_id = int(row["id"])
            self.container_item_combo.addItem(str(row["name"]), item_id)
            self._container_item_slots[item_id] = int(row["storage_slot_count"] or 0)
        form.addRow("Container Item", self.container_item_combo)

        self.owned_spin = QtWidgets.QSpinBox()
        self.owned_spin.setRange(0, 1_000_000)
        self.owned_spin.setSpecialValueText("(unset)")
        self.owned_spin.setValue(int((storage or {}).get("owned_count") or 0))
        form.addRow("Owned", self.owned_spin)

        self.placed_spin = QtWidgets.QSpinBox()
        self.placed_spin.setRange(0, 1_000_000)
        self.placed_spin.setSpecialValueText("(unset)")
        self.placed_spin.setValue(int((storage or {}).get("placed_count") or 0))
        form.addRow("Placed", self.placed_spin)

        self.liter_spin = QtWidgets.QDoubleSpinBox()
        self.liter_spin.setRange(0, 1_000_000_000)
        self.liter_spin.setDecimals(1)
        self.liter_spin.setSingleStep(1000)
        self.liter_spin.setSpecialValueText("(unset)")
        self.liter_spin.setValue(float((storage or {}).get("liter_capacity") or 0))
        form.addRow("Liter Capacity", self.liter_spin)

        self.priority_spin = QtWidgets.QSpinBox()
        self.priority_spin.setRange(-10_000, 10_000)
        self.priority_spin.setValue(int((storage or {}).get("priority") or 0))
        form.addRow("Priority", self.priority_spin)

        self.allow_planner_checkbox = QtWidgets.QCheckBox("Allow planner to consume from this storage")
        self.allow_planner_checkbox.setChecked(bool((storage or {}).get("allow_planner_use", 1)))
        form.addRow("", self.allow_planner_checkbox)

        self.notes_edit = QtWidgets.QPlainTextEdit((storage or {}).get("notes", "") or "")
        self.notes_edit.setPlaceholderText("Optional notes")
        form.addRow("Notes", self.notes_edit)

        if storage and storage.get("container_item_id"):
            target = int(storage["container_item_id"])
            for idx in range(self.container_item_combo.count()):
                if self.container_item_combo.itemData(idx) == target:
                    self.container_item_combo.setCurrentIndex(idx)
                    break

        self.container_item_combo.currentIndexChanged.connect(self._sync_slot_count_from_container)
        self.placed_spin.valueChanged.connect(self._sync_slot_count_from_container)
        self._sync_slot_count_from_container()

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel | QtWidgets.QDialogButtonBox.StandardButton.Save)
        btns.accepted.connect(self._on_save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _sync_slot_count_from_container(self) -> None:
        item_id = self.container_item_combo.currentData()
        if item_id is None:
            self.slot_spin.setReadOnly(False)
            self.slot_spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.UpDownArrows)
            return
        slots_per_unit = self._container_item_slots.get(int(item_id), 0)
        placed = self.placed_spin.value()
        self.slot_spin.setReadOnly(True)
        self.slot_spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.slot_spin.setValue(max(0, slots_per_unit * max(0, placed)))

    def _on_save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QtWidgets.QMessageBox.critical(self, "Invalid name", "Storage name is required.")
            return
        existing_names = {
            str(row["name"]).strip().casefold()
            for row in list_storage_units(self.app.profile_conn)
            if self.storage is None or int(row["id"]) != int(self.storage["id"])
        }
        if name.casefold() in existing_names:
            QtWidgets.QMessageBox.critical(self, "Duplicate name", "Storage name must be unique.")
            return

        slot_count = self.slot_spin.value() or None
        liter_capacity = self.liter_spin.value() or None
        container_item_id = self.container_item_combo.currentData()
        owned_count = self.owned_spin.value() or None
        placed_count = self.placed_spin.value() or None
        if owned_count is not None and placed_count is not None and placed_count > owned_count:
            QtWidgets.QMessageBox.critical(self, "Invalid counts", "Placed count cannot exceed owned count.")
            return
        if slot_count is not None and slot_count < 0:
            QtWidgets.QMessageBox.critical(self, "Invalid slot count", "Slot count cannot be negative.")
            return
        if liter_capacity is not None and liter_capacity < 0:
            QtWidgets.QMessageBox.critical(self, "Invalid liter capacity", "Liter capacity cannot be negative.")
            return

        self.result_data = {
            "name": name,
            "kind": (self.kind_edit.text().strip() or "generic"),
            "slot_count": slot_count,
            "liter_capacity": liter_capacity,
            "priority": self.priority_spin.value(),
            "allow_planner_use": self.allow_planner_checkbox.isChecked(),
            "container_item_id": container_item_id,
            "owned_count": owned_count,
            "placed_count": placed_count,
            "notes": (self.notes_edit.toPlainText().strip() or None),
        }
        self.accept()


class StorageUnitsDialog(QtWidgets.QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("Manage Storages")
        self.resize(560, 360)

        layout = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Name", "Kind", "Slots", "Owned", "Placed", "Liters"])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, stretch=1)

        row = QtWidgets.QHBoxLayout()
        self.btn_new = QtWidgets.QPushButton("New…")
        self.btn_edit = QtWidgets.QPushButton("Edit…")
        self.btn_containers = QtWidgets.QPushButton("Containers…")
        self.btn_delete = QtWidgets.QPushButton("Delete")
        self.btn_close = QtWidgets.QPushButton("Close")
        self.btn_new.clicked.connect(self._on_new)
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_containers.clicked.connect(self._on_containers)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_close.clicked.connect(self.accept)
        row.addWidget(self.btn_new)
        row.addWidget(self.btn_edit)
        row.addWidget(self.btn_containers)
        row.addWidget(self.btn_delete)
        row.addStretch(1)
        row.addWidget(self.btn_close)
        layout.addLayout(row)

        self.reload()

    def reload(self) -> None:
        rows = list_storage_units(self.app.profile_conn)
        self.table.setRowCount(len(rows))
        for idx, row in enumerate(rows):
            self.table.setItem(idx, 0, QtWidgets.QTableWidgetItem(str(row["name"])))
            self.table.setItem(idx, 1, QtWidgets.QTableWidgetItem(str(row.get("kind") or "generic")))
            self.table.setItem(idx, 2, QtWidgets.QTableWidgetItem("" if row.get("slot_count") is None else str(int(row["slot_count"])) ))
            self.table.setItem(idx, 3, QtWidgets.QTableWidgetItem("" if row.get("owned_count") is None else str(int(row["owned_count"]))))
            self.table.setItem(idx, 4, QtWidgets.QTableWidgetItem("" if row.get("placed_count") is None else str(int(row["placed_count"]))))
            self.table.setItem(idx, 5, QtWidgets.QTableWidgetItem("" if row.get("liter_capacity") is None else str(int(round(float(row["liter_capacity"])))) ))
            self.table.item(idx, 0).setData(QtCore.Qt.ItemDataRole.UserRole, int(row["id"]))
        if rows:
            self.table.selectRow(0)

    def _selected_storage_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        storage_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if storage_id is None:
            return None
        return int(storage_id)

    def _selected_storage_row(self) -> dict | None:
        storage_id = self._selected_storage_id()
        if storage_id is None:
            return None
        for row in list_storage_units(self.app.profile_conn):
            if int(row["id"]) == storage_id:
                return row
        return None

    def _on_new(self) -> None:
        dialog = StorageUnitDialog(self.app, parent=self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted or not dialog.result_data:
            return
        create_storage_unit(self.app.profile_conn, **dialog.result_data)
        self.app.profile_conn.commit()
        self.reload()

    def _on_edit(self) -> None:
        storage = self._selected_storage_row()
        if storage is None:
            return
        dialog = StorageUnitDialog(self.app, storage=storage, parent=self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted or not dialog.result_data:
            return
        update_storage_unit(self.app.profile_conn, int(storage["id"]), **dialog.result_data)
        self.app.profile_conn.commit()
        self.reload()

    def _on_containers(self) -> None:
        storage = self._selected_storage_row()
        if storage is None:
            return
        dialog = StorageContainerPlacementsDialog(self.app, storage=storage, parent=self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.reload()

    def _on_delete(self) -> None:
        storage = self._selected_storage_row()
        if storage is None:
            return
        if str(storage.get("name") or "") == "Main Storage":
            QtWidgets.QMessageBox.information(self, "Delete blocked", "Main Storage cannot be deleted.")
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            "Delete storage",
            f"Delete storage '{storage['name']}'? Assigned inventory for this storage will be removed.",
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        delete_storage_unit(self.app.profile_conn, int(storage["id"]))
        self.app.profile_conn.commit()
        self.reload()


class StorageContainerPlacementsDialog(QtWidgets.QDialog):
    def __init__(self, app, *, storage: dict, parent=None):
        super().__init__(parent)
        self.app = app
        self.storage = storage
        self.setWindowTitle(f"Container Placements — {storage['name']}")
        self.resize(520, 420)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Set how many container items are placed in this storage."))

        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Container Item", "Slots/Container", "Placed"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, stretch=1)

        self._rows: list[dict] = []
        self._load_rows()

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _load_rows(self) -> None:
        placement_rows = {
            int(row["item_id"]): int(row.get("placed_count") or 0)
            for row in list_storage_container_placements(self.app.profile_conn, int(self.storage["id"]))
        }
        container_rows = self.app.conn.execute(
            """
            SELECT id, COALESCE(display_name, key) AS name, COALESCE(storage_slot_count, 0) AS storage_slot_count
            FROM items
            WHERE COALESCE(is_storage_container, 0)=1
            ORDER BY LOWER(COALESCE(display_name, key)), id
            """
        ).fetchall()
        self._rows = [dict(r) for r in container_rows]

        self.table.setRowCount(len(self._rows))
        for idx, row in enumerate(self._rows):
            item_id = int(row["id"])
            self.table.setItem(idx, 0, QtWidgets.QTableWidgetItem(str(row["name"])))
            self.table.item(idx, 0).setData(QtCore.Qt.ItemDataRole.UserRole, item_id)
            self.table.setItem(idx, 1, QtWidgets.QTableWidgetItem(str(int(row.get("storage_slot_count") or 0))))
            spin = QtWidgets.QSpinBox()
            spin.setRange(0, 1_000_000)
            spin.setValue(placement_rows.get(item_id, 0))
            self.table.setCellWidget(idx, 2, spin)

    def _on_save(self) -> None:
        storage_id = int(self.storage["id"])
        for idx, row in enumerate(self._rows):
            item_id = int(row["id"])
            spin = self.table.cellWidget(idx, 2)
            placed = int(spin.value()) if isinstance(spin, QtWidgets.QSpinBox) else 0
            set_storage_container_placement(
                self.app.profile_conn,
                storage_id=storage_id,
                item_id=item_id,
                placed_count=placed,
            )
            if placed > 0:
                self.app.profile_conn.execute(
                    """
                    INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters, locked)
                    VALUES(?, ?, ?, NULL, 0)
                    ON CONFLICT(storage_id, item_id)
                    DO UPDATE SET qty_count=excluded.qty_count, qty_liters=NULL
                    """,
                    (storage_id, item_id, placed),
                )
            else:
                self.app.profile_conn.execute(
                    "DELETE FROM storage_assignments WHERE storage_id=? AND item_id=?",
                    (storage_id, item_id),
                )

        recompute_storage_slot_capacities(self.app.profile_conn)
        self.app.profile_conn.commit()
        self.accept()


class ItemPickerDialog(QtWidgets.QDialog):
    """Searchable tree picker for Items.

    Returns: self.result = {"id": int, "name": str, "kind": "item"|"fluid"}
    """

    def __init__(
        self,
        app,
        title: str = "Pick Item",
        machines_only: bool = False,
        kinds: list[str] | None = None,
        *,
        crafting_grids_only: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.app = app
        self.machines_only = machines_only
        self.crafting_grids_only = crafting_grids_only
        self.kinds = kinds
        self._base_kinds = set(kinds) if kinds else {"item", "fluid", "gas", "machine", "crafting_grid"}
        self.result: dict | None = None
        self._items = []
        self._display_map: dict[QtWidgets.QTreeWidgetItem, dict] = {}
        self._dup_name_counts: dict[tuple[str, str], int] = {}
        self._tab_kinds: list[set[str]] = []

        self.setWindowTitle(title)
        self.resize(520, 520)
        layout = QtWidgets.QVBoxLayout(self)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Search"))
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.returnPressed.connect(self.on_ok)
        self._search_timer = QtCore.QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self.rebuild_tree)
        self.search_edit.textChanged.connect(self._schedule_rebuild)
        top.addWidget(self.search_edit)
        layout.addLayout(top)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemDoubleClicked.connect(lambda *_: self.on_ok())

        self._build_tabs(layout)
        layout.addWidget(self.tree, stretch=1)

        btns = QtWidgets.QHBoxLayout()
        self.new_button = QtWidgets.QPushButton("New Item…")
        self.new_button.clicked.connect(self.new_item)
        btns.addWidget(self.new_button)
        btns.addStretch(1)
        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QtWidgets.QPushButton("OK")
        ok_btn.clicked.connect(self.on_ok)
        btns.addWidget(cancel_btn)
        btns.addWidget(ok_btn)
        layout.addLayout(btns)

        self.reload_items()
        self.rebuild_tree()
        self.search_edit.setFocus()

    def _build_tabs(self, layout: QtWidgets.QVBoxLayout) -> None:
        if self.machines_only or self.crafting_grids_only:
            return
        self.tabs = QtWidgets.QTabBar()
        self.tabs.setExpanding(True)
        self.tabs.setUsesScrollButtons(False)
        self._tab_kinds = []

        def _add_tab(label: str, kinds: set[str]) -> None:
            self._tab_kinds.append(kinds)
            self.tabs.addTab(label)

        if "item" in self._base_kinds:
            _add_tab("Items", {"item"})
        if self._base_kinds & {"fluid", "gas"}:
            _add_tab("Fluids", {"fluid", "gas"})
        if "machine" in self._base_kinds:
            _add_tab("Machines", {"machine"})
        if "crafting_grid" in self._base_kinds:
            _add_tab("Crafting Grids", {"crafting_grid"})
        _add_tab("All", set(self._base_kinds))

        self.tabs.currentChanged.connect(self.rebuild_tree)
        layout.addWidget(self.tabs)
        self._select_default_tab()

    def _select_default_tab(self) -> None:
        if not getattr(self, "tabs", None):
            return
        for idx, kinds in enumerate(self._tab_kinds):
            if kinds == self._base_kinds:
                self.tabs.setCurrentIndex(idx)
                return
        self.tabs.setCurrentIndex(0)

    def _active_kinds(self) -> set[str]:
        if self.machines_only:
            return {"machine"}
        if self.crafting_grids_only:
            return {"crafting_grid"}
        if getattr(self, "tabs", None) and self._tab_kinds:
            idx = self.tabs.currentIndex()
            if 0 <= idx < len(self._tab_kinds):
                return set(self._tab_kinds[idx])
        return set(self._base_kinds)

    def _schedule_rebuild(self) -> None:
        self._search_timer.start()

    def reload_items(self) -> None:
        if self.machines_only:
            # Select all machines (kind='machine' OR kind='item' flagged as machine)
            # We do NOT filter by enabled tiers here, so recipe editors can see all available machines.
            sql = (
                "SELECT i.id, i.key, COALESCE(i.display_name, i.key) AS name, i.kind, "
                "       i.machine_tier, i.is_machine, k.name AS item_kind_name "
                "FROM items i "
                "LEFT JOIN item_kinds k ON k.id = i.item_kind_id "
                "WHERE (i.kind='machine') "
                "   OR (i.kind='item' AND (LOWER(COALESCE(k.name,''))=LOWER('Machine') OR i.is_machine=1)) "
                "ORDER BY name"
            )
            self._items = self.app.conn.execute(sql).fetchall()
        elif self.crafting_grids_only:
            self._items = self.app.conn.execute(
                "SELECT i.id, i.key, COALESCE(i.display_name, i.key) AS name, i.kind, "
                "       i.item_kind_id, k.name AS item_kind_name, i.crafting_grid_size "
                "FROM items i "
                "LEFT JOIN item_kinds k ON k.id = i.item_kind_id "
                "WHERE i.kind='crafting_grid' "
                "ORDER BY name"
            ).fetchall()
        else:
            if self.kinds:
                placeholders = ",".join(["?"] * len(self.kinds))
                self._items = self.app.conn.execute(
                    "SELECT i.id, i.key, COALESCE(i.display_name, i.key) AS name, i.kind, "
                    "       i.item_kind_id, k.name AS item_kind_name "
                    "FROM items i "
                    "LEFT JOIN item_kinds k ON k.id = i.item_kind_id "
                    f"WHERE i.kind IN ({placeholders}) "
                    "ORDER BY name",
                    tuple(self.kinds),
                ).fetchall()
            else:
                self._items = self.app.conn.execute(
                    "SELECT i.id, i.key, COALESCE(i.display_name, i.key) AS name, i.kind, "
                    "       i.item_kind_id, k.name AS item_kind_name "
                    "FROM items i "
                    "LEFT JOIN item_kinds k ON k.id = i.item_kind_id "
                    "ORDER BY name"
                ).fetchall()

    def _label_for(self, row) -> str:
        name = row["name"]
        kind = row["kind"]
        if self._dup_name_counts.get((kind, name), 0) > 1:
            return f"{name}  (#{row['id']})"
        return name

    def rebuild_tree(self) -> None:
        self.tree.clear()
        self._display_map.clear()
        query = (self.search_edit.text() or "").strip().lower()
        self._dup_name_counts = {}
        for row in self._items:
            key = (row["kind"], row["name"])
            self._dup_name_counts[key] = self._dup_name_counts.get(key, 0) + 1

        active_kinds = None if self.machines_only else self._active_kinds()

        def _matches(row) -> bool:
            if active_kinds is not None and row["kind"] not in active_kinds:
                return False
            if not query:
                return True
            return query in (row["name"] or "").lower()

        if self.machines_only:
            p_machines = QtWidgets.QTreeWidgetItem(self.tree, ["Machines"])
            p_machines.setExpanded(True)
            for row in self._items:
                if not _matches(row):
                    continue
                child = QtWidgets.QTreeWidgetItem(p_machines, [self._label_for(row)])
                self._display_map[child] = row
            self._select_first_child(p_machines)
            if p_machines.childCount() == 0:
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(p_machines))
            return
        if self.crafting_grids_only:
            p_grids = QtWidgets.QTreeWidgetItem(self.tree, ["Crafting Grids"])
            p_grids.setExpanded(True)
            for row in self._items:
                if not _matches(row):
                    continue
                child = QtWidgets.QTreeWidgetItem(p_grids, [self._label_for(row)])
                self._display_map[child] = row
            self._select_first_child(p_grids)
            if p_grids.childCount() == 0:
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(p_grids))
            return

        active_kinds = self._active_kinds()
        kind_labels = {
            "item": "Items",
            "fluid": "Fluids",
            "gas": "Gases",
            "machine": "Machines",
            "crafting_grid": "Crafting Grids",
        }

        grouped: dict[str, dict[str | None, list]] = {
            "item": {},
            "fluid": {},
            "gas": {},
            "machine": {},
            "crafting_grid": {},
        }

        def _category_label(row) -> str | None:
            kind = row["kind"]
            if kind == "gas":
                return None
            if kind == "crafting_grid":
                label = (_row_get(row, "crafting_grid_size") or "").strip()
                return label.replace("_", " ") if label else "(crafting grid)"
            label = (_row_get(row, "item_kind_name") or "").strip()
            label = label.replace("_", " ")
            if label:
                return label
            return "(no type)" if kind == "item" else f"({kind})"

        for row in self._items:
            if not _matches(row):
                continue
            kind = row["kind"]
            if kind not in active_kinds:
                continue
            category = _category_label(row)
            grouped.setdefault(kind, {})
            grouped[kind].setdefault(category, []).append(row)

        for kind in ("item", "fluid", "gas", "machine", "crafting_grid"):
            if kind not in active_kinds:
                continue
            categories = grouped.get(kind, {})
            if not categories:
                continue
            parent_item = QtWidgets.QTreeWidgetItem(self.tree, [kind_labels[kind]])
            parent_item.setExpanded(True)
            for category in sorted(categories.keys(), key=lambda val: "" if val is None else val.casefold()):
                rows = categories[category]
                if category is None:
                    category_item = parent_item
                else:
                    category_item = QtWidgets.QTreeWidgetItem(parent_item, [category])
                    category_item.setExpanded(bool(query))
                for row in sorted(rows, key=lambda r: self._label_for(r).casefold()):
                    child = QtWidgets.QTreeWidgetItem(category_item, [self._label_for(row)])
                    self._display_map[child] = row

        for idx in range(self.tree.topLevelItemCount()):
            p = self.tree.topLevelItem(idx)
            if p is not None and self._select_first_child(p):
                return

    def _children(self, item: QtWidgets.QTreeWidgetItem) -> list[QtWidgets.QTreeWidgetItem]:
        return [item.child(i) for i in range(item.childCount())]

    def _select_first_child(self, parent: QtWidgets.QTreeWidgetItem) -> bool:
        for child in self._children(parent):
            if child in self._display_map:
                self.tree.setCurrentItem(child)
                return True
            if self._select_first_child(child):
                return True
        return False

    def get_selected_row(self):
        sel = self.tree.currentItem()
        if not sel:
            return None
        return self._display_map.get(sel)

    def new_item(self) -> None:
        dlg = AddItemDialog(self.app, parent=self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.reload_items()
            self.rebuild_tree()

    def on_ok(self) -> None:
        row = self.get_selected_row()
        if not row:
            QtWidgets.QMessageBox.warning(self, "Missing selection", "Select an item.")
            return
        self.result = {"id": row["id"], "name": row["name"], "kind": row["kind"]}
        self.accept()


class ItemMergeConflictDialog(QtWidgets.QDialog):
    """Resolve ambiguous item matches during DB merge."""
    def __init__(self, conflicts: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Resolve Item Conflicts")
        self.resize(720, 420)
        self._conflicts = conflicts
        self.result: dict[int, int] | None = None
        # ... (implementation omitted for brevity, unchanged)


class _ItemDialogBase(QtWidgets.QDialog):
    KIND_OPTIONS = [
        ("item", "Item"),
        ("fluid", "Fluid"),
        ("gas", "Gas"),
        ("machine", "Machine"),
        ("crafting_grid", "Crafting Grid"),
    ]

    def __init__(
        self,
        app,
        title: str,
        *,
        row=None,
        parent=None,
        allowed_kinds: list[str] | None = None,
        default_kind: str | None = None,
        show_availability: bool = False,
    ):
        super().__init__(parent)
        self.app = app
        self._row = row
        self.item_id = row["id"] if row else None
        self.item_kind_id = row["item_kind_id"] if row else None
        self.machine_kind_id = None
        self.material_id = row["material_id"] if row else None
        self.content_fluid_id = None
        self.crafting_grid_size = None
        
        # Safe access to new columns if they exist in _row, else None
        self.content_fluid_id_val = _row_get(row, "content_fluid_id")
        self.content_qty_val = _row_get(row, "content_qty_liters")
        self.is_storage_container_val = int(_row_get(row, "is_storage_container", 0) or 0)
        self.storage_slot_count_val = _row_get(row, "storage_slot_count")

        self._all_item_kinds: list[dict] = []
        self._kind_name_to_id: dict[str, int] = {}
        self._kind_id_to_applies: dict[int, str] = {}
        self._material_name_to_id: dict[str, int] = {}
        self._fluid_name_to_id: dict[str, int] = {}
        self._allowed_kinds = allowed_kinds
        self._default_kind = default_kind
        self._show_availability = show_availability
        self.availability_group = None
        self.owned_spin = None
        self.online_spin = None
        
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QGridLayout()
        layout.addLayout(form)

        form.addWidget(QtWidgets.QLabel("Display Name"), 0, 0)
        self.display_name_edit = QtWidgets.QLineEdit()
        form.addWidget(self.display_name_edit, 0, 1)

        form.addWidget(QtWidgets.QLabel("Kind"), 1, 0)
        self.kind_combo = QtWidgets.QComboBox()
        kind_values = allowed_kinds or [value for value, _label in self.KIND_OPTIONS]
        for value, label in self.KIND_OPTIONS:
            if value not in kind_values:
                continue
            self.kind_combo.addItem(label, value)
        form.addWidget(self.kind_combo, 1, 1)

        self.item_kind_label = QtWidgets.QLabel("Item Type")
        form.addWidget(self.item_kind_label, 2, 0)
        self.item_kind_combo = QtWidgets.QComboBox()
        form.addWidget(self.item_kind_combo, 2, 1)

        # Row 3: Crafting Grid Size (for Crafting Grid item kind)
        self.crafting_grid_label = QtWidgets.QLabel("Crafting Grid")
        self.crafting_grid_combo = QtWidgets.QComboBox()
        form.addWidget(self.crafting_grid_label, 3, 0)
        form.addWidget(self.crafting_grid_combo, 3, 1)
        self.crafting_grid_label.hide()
        self.crafting_grid_combo.hide()

        # Has Material Checkbox (Row 4)
        self.has_material_check = QtWidgets.QCheckBox("Has Material?")
        form.addWidget(self.has_material_check, 4, 1)

        # Row 5: Material OR Machine Type
        self.material_label = QtWidgets.QLabel("Material")
        self.material_combo = QtWidgets.QComboBox()
        form.addWidget(self.material_label, 5, 0)
        form.addWidget(self.material_combo, 5, 1)

        self.machine_type_label = QtWidgets.QLabel("Machine Type")
        self.machine_type_combo = QtWidgets.QComboBox()
        self.machine_type_combo.setEditable(True)
        form.addWidget(self.machine_type_label, 5, 0)
        form.addWidget(self.machine_type_combo, 5, 1)
        self.machine_type_label.hide()
        self.machine_type_combo.hide()

        self.tier_label = QtWidgets.QLabel("Tier")
        self.tier_combo = QtWidgets.QComboBox()
        tiers = self.app.get_all_tiers() if hasattr(self.app, "get_all_tiers") else list(ALL_TIERS)
        self.tier_combo.addItems([NONE_TIER_LABEL] + list(tiers))
        form.addWidget(self.tier_label, 6, 0)
        form.addWidget(self.tier_combo, 6, 1)
        self.tier_label.hide()
        self.tier_combo.hide()

        self.is_multiblock_check = QtWidgets.QCheckBox("Multi-block machine")
        form.addWidget(self.is_multiblock_check, 7, 1)
        self.is_multiblock_check.hide()
        
        # Row 8: Fluid Container options
        self.container_group = QtWidgets.QGroupBox("Fluid Container")
        container_layout = QtWidgets.QGridLayout(self.container_group)
        self.is_container_check = QtWidgets.QCheckBox("Is Fluid Container? (e.g. Cell/Bucket)")
        container_layout.addWidget(self.is_container_check, 0, 0, 1, 2)

        self.content_fluid_label = QtWidgets.QLabel("Contains Fluid")
        self.content_fluid_combo = QtWidgets.QComboBox()
        container_layout.addWidget(self.content_fluid_label, 1, 0)
        container_layout.addWidget(self.content_fluid_combo, 1, 1)

        self.content_qty_label = QtWidgets.QLabel("Amount (L)")
        self.content_qty_edit = QtWidgets.QLineEdit("1000")
        self.content_qty_edit.setValidator(QtGui.QIntValidator(1, 1000000))
        container_layout.addWidget(self.content_qty_label, 2, 0)
        container_layout.addWidget(self.content_qty_edit, 2, 1)
        form.addWidget(self.container_group, 8, 0, 1, 2)

        self.storage_container_group = QtWidgets.QGroupBox("Inventory Container")
        storage_container_layout = QtWidgets.QGridLayout(self.storage_container_group)
        self.is_storage_container_check = QtWidgets.QCheckBox("Is Inventory Container? (e.g. Chest, Iron Chest)")
        storage_container_layout.addWidget(self.is_storage_container_check, 0, 0, 1, 2)
        self.storage_slot_count_label = QtWidgets.QLabel("Storage Slots")
        self.storage_slot_count_spin = QtWidgets.QSpinBox()
        self.storage_slot_count_spin.setRange(1, 1_000_000)
        self.storage_slot_count_spin.setValue(int(self.storage_slot_count_val or 27))
        storage_container_layout.addWidget(self.storage_slot_count_label, 1, 0)
        storage_container_layout.addWidget(self.storage_slot_count_spin, 1, 1)
        form.addWidget(self.storage_container_group, 9, 0, 1, 2)

        self.is_base_check = QtWidgets.QCheckBox("Base resource (planner stops here later)")
        form.addWidget(self.is_base_check, 10, 1)

        self.has_cell_check = QtWidgets.QCheckBox("Has Cell? (auto-create '<Name> Cell')")
        form.addWidget(self.has_cell_check, 11, 1)
        self.has_cell_check.hide()

        self.auto_cell_size_group = QtWidgets.QGroupBox("Auto Cell Size")
        auto_cell_size_layout = QtWidgets.QHBoxLayout(self.auto_cell_size_group)
        self.auto_cell_144_radio = QtWidgets.QRadioButton("144 L")
        self.auto_cell_1000_radio = QtWidgets.QRadioButton("1000 L")
        self.auto_cell_1000_radio.setChecked(True)
        auto_cell_size_layout.addWidget(self.auto_cell_144_radio)
        auto_cell_size_layout.addWidget(self.auto_cell_1000_radio)
        auto_cell_size_layout.addStretch(1)
        form.addWidget(self.auto_cell_size_group, 11, 1)
        self.auto_cell_size_group.hide()

        if self._show_availability:
            self.availability_group = QtWidgets.QGroupBox("Availability")
            availability_layout = QtWidgets.QGridLayout(self.availability_group)
            availability_layout.addWidget(QtWidgets.QLabel("Owned"), 0, 0)
            self.owned_spin = QtWidgets.QSpinBox()
            self.owned_spin.setRange(0, 999)
            availability_layout.addWidget(self.owned_spin, 0, 1)
            availability_layout.addWidget(QtWidgets.QLabel("Online"), 1, 0)
            self.online_spin = QtWidgets.QSpinBox()
            self.online_spin.setRange(0, 999)
            self.online_spin.setMaximum(0)
            availability_layout.addWidget(self.online_spin, 1, 1)
            self.owned_spin.valueChanged.connect(self._on_owned_changed)
            form.addWidget(self.availability_group, 12, 0, 1, 2)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._reload_item_kinds()
        self._reload_materials()
        self._reload_machine_types()
        self._reload_fluids()
        self._reload_crafting_grids()

        self.kind_combo.currentTextChanged.connect(self._on_high_level_kind_changed)
        self.item_kind_combo.currentTextChanged.connect(self._on_item_kind_selected)
        self.material_combo.currentTextChanged.connect(self._on_material_selected)
        self.machine_type_combo.currentTextChanged.connect(self._on_machine_type_selected)
        self.has_material_check.toggled.connect(self._on_has_material_toggled)
        self.is_container_check.toggled.connect(self._on_is_container_toggled)
        self.is_storage_container_check.toggled.connect(self._on_is_storage_container_toggled)
        self.has_cell_check.toggled.connect(self._on_has_cell_toggled)
        self.content_fluid_combo.currentTextChanged.connect(self._on_content_fluid_selected)
        self.crafting_grid_combo.currentTextChanged.connect(self._on_crafting_grid_selected)

        self._load_row_defaults()
        self._on_high_level_kind_changed()
        self._on_item_kind_selected()

    def _load_row_defaults(self) -> None:
        if not self._row:
            self.display_name_edit.setText("")
            if self._default_kind:
                self._set_kind_value(self._default_kind)
            else:
                self.kind_combo.setCurrentIndex(0)
            self.item_kind_combo.setCurrentText(NONE_KIND_LABEL)
            self.material_combo.setCurrentText(NONE_MATERIAL_LABEL)
            if self.crafting_grid_combo.count() > 0:
                self.crafting_grid_combo.setCurrentIndex(0)
            self.is_base_check.setChecked(False)
            self.has_material_check.setChecked(False)
            self.is_container_check.setChecked(False)
            self.is_multiblock_check.setChecked(False)
            self.is_storage_container_check.setChecked(False)
            self.storage_slot_count_spin.setValue(27)
            self.content_fluid_combo.setCurrentText(NONE_FLUID_LABEL)
            self.content_qty_edit.setText("1000")
            if self._show_availability:
                if self.owned_spin is not None:
                    self.owned_spin.setValue(0)
                if self.online_spin is not None:
                    self.online_spin.setValue(0)
                self._on_owned_changed()
            return

        self.display_name_edit.setText(self._row["display_name"] or self._row["key"])
        self._set_kind_value(self._row["kind"])
        item_kind_name = (self._row["item_kind_name"] or "") or NONE_KIND_LABEL
        self.item_kind_combo.setCurrentText(item_kind_name)
        if _row_get(self._row, "crafting_grid_size"):
            self.crafting_grid_combo.setCurrentText(str(_row_get(self._row, "crafting_grid_size")))

        if (item_kind_name.strip().lower() == "machine") or bool(self._row["is_machine"]):
            # Prefer machine_type, fallback to display_name for legacy/migration
            m_type = _row_get(self._row, "machine_type")
            if not m_type:
                 m_type = self._row["display_name"]
            self.machine_type_combo.setCurrentText(m_type or "")
            self.tier_combo.setCurrentText(self._row["machine_tier"] or NONE_TIER_LABEL)
            self.is_multiblock_check.setChecked(bool(_row_get(self._row, "is_multiblock")))
        else:
            self.is_multiblock_check.setChecked(False)

        material_name = (self._row["material_name"] or "") or NONE_MATERIAL_LABEL
        if material_name != NONE_MATERIAL_LABEL:
            self.has_material_check.setChecked(True)
        else:
            self.has_material_check.setChecked(False)
        self.material_combo.setCurrentText(material_name)
        
        # Fluid container defaults
        if self.content_fluid_id_val:
            self.is_container_check.setChecked(True)
            # Find name for this id
            # This is slightly inefficient but safe
            row = self.app.conn.execute("SELECT COALESCE(display_name, key) as name FROM items WHERE id=?", (self.content_fluid_id_val,)).fetchone()
            if row:
                self.content_fluid_combo.setCurrentText(row["name"])
            if self.content_qty_val:
                self.content_qty_edit.setText(str(self.content_qty_val))
        else:
            self.is_container_check.setChecked(False)
            self.content_fluid_combo.setCurrentText(NONE_FLUID_LABEL)
            self.content_qty_edit.setText("1000")

        self.is_storage_container_check.setChecked(bool(self.is_storage_container_val))
        if self.storage_slot_count_val:
            self.storage_slot_count_spin.setValue(int(self.storage_slot_count_val))
        self._on_is_storage_container_toggled()

        self.is_base_check.setChecked(bool(self._row["is_base"]))
        if self._show_availability:
            if self.owned_spin is not None:
                self.owned_spin.setValue(0)
            if self.online_spin is not None:
                self.online_spin.setValue(0)
            self._on_owned_changed()

    def _reload_item_kinds(self) -> None:
        # 1. Fetch all kinds
        rows = self.app.conn.execute(
            "SELECT id, name, applies_to FROM item_kinds ORDER BY sort_order ASC, name COLLATE NOCASE ASC"
        ).fetchall()
        self._all_item_kinds = rows
        self._kind_name_to_id = {r["name"]: r["id"] for r in rows}
        self._kind_id_to_applies = {r["id"]: (r["applies_to"] or "item").strip().lower() for r in rows}
        self.machine_kind_id = next((r["id"] for r in rows if (r["name"] or "").strip().lower() == "machine"), None)

        self._update_item_kind_combo()

    def _update_item_kind_combo(self) -> None:
        current_kind_super = self._current_kind_value()
        if not current_kind_super:
            current_kind_super = "item"

        # Determine which names to show
        filtered_names = [NONE_KIND_LABEL]
        if current_kind_super in ("item", "fluid"):
            for r in self._all_item_kinds:
                kid = r["id"]
                applies_to = self._kind_id_to_applies.get(kid, "item")
                if applies_to == current_kind_super:
                    filtered_names.append(r["name"])
            filtered_names.append(ADD_NEW_KIND_LABEL)

        # Update Combo
        cur = self.item_kind_combo.currentText()
        self.item_kind_combo.blockSignals(True)
        self.item_kind_combo.clear()
        self.item_kind_combo.addItems(filtered_names)
        
        if cur not in filtered_names:
            cur = NONE_KIND_LABEL
        
        self.item_kind_combo.setCurrentText(cur)
        self.item_kind_combo.blockSignals(False)

        v = (self.item_kind_combo.currentText() or "").strip()
        self.item_kind_id = self._kind_name_to_id.get(v) if v and v != NONE_KIND_LABEL else None

    def _reload_materials(self) -> None:
        rows = fetch_materials(self.app.conn)
        self._material_name_to_id = {r["name"]: r["id"] for r in rows}
        values = [NONE_MATERIAL_LABEL] + [r["name"] for r in rows]
        cur = self.material_combo.currentText()
        self.material_combo.blockSignals(True)
        self.material_combo.clear()
        self.material_combo.addItems(values)
        if cur not in values:
            cur = NONE_MATERIAL_LABEL
        self.material_combo.setCurrentText(cur)
        self.material_combo.blockSignals(False)

        v = (self.material_combo.currentText() or "").strip()
        self.material_id = self._material_name_to_id.get(v) if v and v != NONE_MATERIAL_LABEL else None
    
    def _reload_fluids(self) -> None:
        # Fetch all items that are kind='fluid' or 'gas'
        rows = self.app.conn.execute(
            "SELECT id, COALESCE(display_name, key) as name FROM items WHERE kind IN ('fluid', 'gas') ORDER BY name COLLATE NOCASE ASC"
        ).fetchall()
        self._fluid_name_to_id = {r["name"]: r["id"] for r in rows}
        values = [NONE_FLUID_LABEL] + [r["name"] for r in rows]
        
        cur = self.content_fluid_combo.currentText()
        self.content_fluid_combo.blockSignals(True)
        self.content_fluid_combo.clear()
        self.content_fluid_combo.addItems(values)
        if cur not in values:
            cur = NONE_FLUID_LABEL
        self.content_fluid_combo.setCurrentText(cur)
        self.content_fluid_combo.blockSignals(False)
        
        v = (self.content_fluid_combo.currentText() or "").strip()
        self.content_fluid_id = self._fluid_name_to_id.get(v) if v and v != NONE_FLUID_LABEL else None

    def _reload_crafting_grids(self) -> None:
        grids = self.app.get_crafting_grids() if hasattr(self.app, "get_crafting_grids") else ["2x2", "3x3"]
        values = [g for g in grids if g]
        if not values:
            values = ["2x2", "3x3"]
        cur = self.crafting_grid_combo.currentText()
        self.crafting_grid_combo.blockSignals(True)
        self.crafting_grid_combo.clear()
        self.crafting_grid_combo.addItems(values)
        if cur not in values:
            cur = values[0]
        self.crafting_grid_combo.setCurrentText(cur)
        self.crafting_grid_combo.blockSignals(False)
        self._on_crafting_grid_selected()

    def _reload_machine_types(self) -> None:
        rows = fetch_machine_metadata(self.app.conn)
        types = sorted({(row["machine_type"] or "").strip() for row in rows if row["machine_type"]})
        self.machine_type_combo.blockSignals(True)
        self.machine_type_combo.clear()
        self.machine_type_combo.addItems([""] + types)
        self.machine_type_combo.blockSignals(False)

    def _ensure_item_kind(self, name: str, applies_to: str) -> str | None:
        name = (name or "").strip()
        if not name:
            return None
        applies_to = (applies_to or "item").strip().lower()
        if applies_to not in ("item", "fluid"):
            applies_to = "item"
        row = self.app.conn.execute(
            "SELECT name FROM item_kinds WHERE LOWER(name)=LOWER(?)",
            (name,),
        ).fetchone()
        if row:
            return row["name"]
        self.app.conn.execute(
            "INSERT INTO item_kinds(name, sort_order, is_builtin, applies_to) VALUES(?, 500, 0, ?)",
            (name, applies_to),
        )
        self.app.conn.commit()
        return name

    def _on_item_kind_selected(self) -> None:
        v = (self.item_kind_combo.currentText() or "").strip()
        kind_high = self._current_kind_value()

        # "Machine" is now a top-level Kind
        is_machine_kind = kind_high == "machine"
        is_fluid_kind = kind_high == "fluid"
        is_gas_kind = kind_high == "gas"
        is_fluid_like = is_fluid_kind or is_gas_kind
        is_crafting_grid_kind = kind_high == "crafting_grid"
        show_item_kind = kind_high in ("item", "fluid")

        self.item_kind_label.setVisible(show_item_kind)
        self.item_kind_combo.setVisible(show_item_kind)

        self.crafting_grid_label.setVisible(is_crafting_grid_kind)
        self.crafting_grid_combo.setVisible(is_crafting_grid_kind)
        if is_crafting_grid_kind:
            self._on_crafting_grid_selected()
        else:
            self.crafting_grid_size = None

        # Machine-specific fields depend on KIND, not Item Type
        self.machine_type_label.setVisible(is_machine_kind)
        self.machine_type_combo.setVisible(is_machine_kind)
        self.tier_label.setVisible(is_machine_kind)
        self.tier_combo.setVisible(is_machine_kind)
        self.is_multiblock_check.setVisible(is_machine_kind)
        self.is_base_check.setVisible(not is_machine_kind and not is_crafting_grid_kind)
        if is_machine_kind or is_crafting_grid_kind:
            self.is_base_check.setChecked(False)
            if not is_machine_kind:
                self.is_multiblock_check.setChecked(False)

        if self._show_availability and self.availability_group is not None:
            self.availability_group.setVisible(is_machine_kind)
            if not is_machine_kind:
                if self.owned_spin is not None:
                    self.owned_spin.setValue(0)
                if self.online_spin is not None:
                    self.online_spin.setValue(0)
            else:
                self._on_owned_changed()

        # Material is hidden if Machine Kind OR Fluid/Gas.
        if is_machine_kind or is_fluid_like or is_crafting_grid_kind:
            self.has_material_check.setVisible(False)
            self.material_label.setVisible(False)
            self.material_combo.setVisible(False)
            self.material_id = None

            self.container_group.setVisible(False)
            self.is_container_check.setChecked(False)
            self._on_is_container_toggled()
            self.storage_container_group.setVisible(False)
            self.is_storage_container_check.setChecked(False)
            self._on_is_storage_container_toggled()
        else:
            self.has_material_check.setVisible(True)
            self._on_has_material_toggled()

            self.container_group.setVisible(True)
            self._on_is_container_toggled()
            self.storage_container_group.setVisible(kind_high == "item")
            self._on_is_storage_container_toggled()

        canonical = None
        if v == ADD_NEW_KIND_LABEL and show_item_kind:
            new_name, ok = QtWidgets.QInputDialog.getText(self, "Add Item Kind", "New kind name:")
            if not ok or not new_name.strip():
                self.item_kind_combo.setCurrentText(NONE_KIND_LABEL)
                self.item_kind_id = None
                return
            canonical = self._ensure_item_kind(new_name, kind_high)

        if v == ADD_NEW_KIND_LABEL and show_item_kind:
            self._reload_item_kinds()

        if canonical:
            # If strictly filtering, the new kind isn't associated yet, so we must force-add it
            # Insert before "Add New..." (which is always last)
            if self.item_kind_combo.findText(canonical) == -1:
                self.item_kind_combo.insertItem(self.item_kind_combo.count() - 1, canonical)
            self.item_kind_combo.setCurrentText(canonical)

        v2 = (self.item_kind_combo.currentText() or "").strip()
        if is_machine_kind:
            self.item_kind_id = self.machine_kind_id
        elif is_crafting_grid_kind:
            self.item_kind_id = None
        elif show_item_kind:
            self.item_kind_id = self._kind_name_to_id.get(v2) if v2 and v2 != NONE_KIND_LABEL else None
        else:
            self.item_kind_id = None

    def _on_has_material_toggled(self) -> None:
        checked = self.has_material_check.isChecked()
        if self.has_material_check.isVisible():
            self.material_label.setVisible(checked)
            self.material_combo.setVisible(checked)
            if checked:
                self._on_material_selected()
            else:
                self.material_id = None
        else:
            self.material_label.setVisible(False)
            self.material_combo.setVisible(False)
            self.material_id = None
            
    def _on_is_container_toggled(self) -> None:
        checked = self.is_container_check.isChecked()
        if self.is_container_check.isVisible():
            self.content_fluid_label.setVisible(checked)
            self.content_fluid_combo.setVisible(checked)
            self.content_qty_label.setVisible(checked)
            self.content_qty_edit.setVisible(checked)
            if checked:
                self._on_content_fluid_selected()
            else:
                self.content_fluid_id = None
        else:
            self.content_fluid_label.setVisible(False)
            self.content_fluid_combo.setVisible(False)
            self.content_qty_label.setVisible(False)
            self.content_qty_edit.setVisible(False)
            self.content_fluid_id = None

    def _on_is_storage_container_toggled(self) -> None:
        checked = self.is_storage_container_check.isVisible() and self.is_storage_container_check.isChecked()
        self.storage_slot_count_label.setVisible(checked)
        self.storage_slot_count_spin.setVisible(checked)

    def _on_material_selected(self) -> None:
        if self.material_combo.isVisible():
            v = (self.material_combo.currentText() or "").strip()
            self.material_id = self._material_name_to_id.get(v) if v and v != NONE_MATERIAL_LABEL else None
        else:
            self.material_id = None
            
    def _on_content_fluid_selected(self) -> None:
        if self.content_fluid_combo.isVisible():
            v = (self.content_fluid_combo.currentText() or "").strip()
            self.content_fluid_id = self._fluid_name_to_id.get(v) if v and v != NONE_FLUID_LABEL else None
        else:
            self.content_fluid_id = None

    def _on_crafting_grid_selected(self) -> None:
        if self.crafting_grid_combo.isVisible():
            v = (self.crafting_grid_combo.currentText() or "").strip()
            self.crafting_grid_size = v if v else None
        else:
            self.crafting_grid_size = None

    def _on_machine_type_selected(self) -> None:
        return

    def _on_owned_changed(self) -> None:
        if not self._show_availability or self.owned_spin is None or self.online_spin is None:
            return
        owned = self.owned_spin.value()
        self.online_spin.setMaximum(owned)
        if self.online_spin.value() > owned:
            self.online_spin.setValue(owned)

    def _on_high_level_kind_changed(self) -> None:
        self._update_item_kind_combo()
        self._on_item_kind_selected()
        kind_high = self._current_kind_value()
        is_fluid_like = kind_high in ("fluid", "gas")
        show_has_cell = is_fluid_like and self.item_id is None
        self.has_cell_check.setVisible(show_has_cell)
        if not show_has_cell:
            self.has_cell_check.setChecked(False)
        self._on_has_cell_toggled()

        if kind_high in ("machine", "gas", "crafting_grid"):
            self.item_kind_combo.setEnabled(False)
        else:
            self.item_kind_combo.setEnabled(True)

    def _current_kind_value(self) -> str:
        data = self.kind_combo.currentData()
        if isinstance(data, str) and data:
            return data.strip().lower()
        return (self.kind_combo.currentText() or "").strip().lower().replace(" ", "_")

    def _set_kind_value(self, value: str | None) -> None:
        if not value:
            return
        target = value.strip().lower()
        for idx in range(self.kind_combo.count()):
            if (self.kind_combo.itemData(idx) or "").strip().lower() == target:
                self.kind_combo.setCurrentIndex(idx)
                return

    def _on_has_cell_toggled(self) -> None:
        visible = self.has_cell_check.isVisible() and self.has_cell_check.isChecked()
        self.auto_cell_size_group.setVisible(visible)

    def _clear_layout(self, layout: QtWidgets.QGridLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _parse_int_opt(self, text: str) -> int | None:
        text = (text or "").strip()
        if text == "":
            return None
        if not text.isdigit():
            raise ValueError("Must be a whole number.")
        return int(text)

    def _set_status(self, message: str) -> None:
        if hasattr(self.app, "status_bar"):
            self.app.status_bar.showMessage(message)
        elif hasattr(self.app, "status"):
            try:
                self.app.status.set(message)
            except Exception:
                pass

    def _slugify(self, s: str) -> str:
        s = (s or "").strip().lower()
        out = []
        last_us = False
        for ch in s:
            if ch.isalnum():
                out.append(ch)
                last_us = False
            else:
                if not last_us:
                    out.append("_")
                    last_us = True
        key = "".join(out).strip("_")
        return key or "item"

    def _get_machine_values(self) -> dict:
        if not self.machine_type_combo.isVisible():
            return {}

        m_type = self.machine_type_combo.currentText().strip()
        tier = self.tier_combo.currentText().strip()

        if not m_type or not tier or tier == NONE_TIER_LABEL:
            return {}
        return {"machine_tier": tier}

    def save(self) -> None:
        raise NotImplementedError

class AddItemDialog(_ItemDialogBase):
    def __init__(
        self,
        app,
        parent=None,
        *,
        title: str = "Add Item",
        allowed_kinds: list[str] | None = None,
        default_kind: str | None = None,
    ):
        super().__init__(
            app,
            title,
            parent=parent,
            allowed_kinds=allowed_kinds,
            default_kind=default_kind,
            show_availability=False,
        )

    def save(self) -> None:
        display_name = (self.display_name_edit.text() or "").strip()
        if not display_name:
            QtWidgets.QMessageBox.warning(self, "Missing name", "Display Name is required.")
            return

        key = self._slugify(display_name)

        kind = self._current_kind_value()
        if kind not in ("item", "fluid", "gas", "machine", "crafting_grid"):
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid kind",
                "Kind must be item, fluid, gas, machine, or crafting grid.",
            )
            return

        is_base = 1 if self.is_base_check.isChecked() else 0
        is_multiblock = 1 if self.is_multiblock_check.isChecked() else 0

        # "Machine" is now a top-level Kind
        is_machine = 1 if kind == "machine" else 0
        item_kind_id = None if kind in ("gas", "crafting_grid") else self.item_kind_id

        crafting_grid_size = None
        if kind == "crafting_grid":
            crafting_grid_size = self.crafting_grid_size
            if not crafting_grid_size:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Missing grid size",
                    "Crafting Grid items require a grid size selection.",
                )
                return

        if self.has_material_check.isVisible() and self.has_material_check.isChecked():
            material_id = self.material_id
        else:
            material_id = None
            
        # Parse Fluid Container Fields
        content_fluid_id = None
        content_qty = None
        if self.is_container_check.isVisible() and self.is_container_check.isChecked():
            content_fluid_id = self.content_fluid_id
            if content_fluid_id is not None:
                try:
                    content_qty = int(self.content_qty_edit.text())
                except ValueError:
                    content_qty = 0
        
        is_storage_container = 1 if (kind == "item" and self.is_storage_container_check.isChecked()) else 0
        storage_slot_count = self.storage_slot_count_spin.value() if is_storage_container else None

        md = {}
        machine_type_val = None
        if is_machine:
            md = self._get_machine_values()
            machine_type_val = (self.machine_type_combo.currentText() or "").strip() or None
            if not machine_type_val:
                QtWidgets.QMessageBox.warning(self, "Missing machine type", "Machine Type is required.")
                return
            if not md.get("machine_tier"):
                QtWidgets.QMessageBox.warning(self, "Missing tier", "Tier is required for machines.")
                return

        key = self._next_unique_key(key)

        try:
            cur = self.app.conn.execute(
                "INSERT INTO items(key, display_name, kind, is_base, is_machine, item_kind_id, material_id, "
                "machine_type, machine_tier, is_multiblock, content_fluid_id, content_qty_liters, crafting_grid_size, is_storage_container, storage_slot_count) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    key,
                    display_name,
                    kind,
                    is_base,
                    is_machine,
                    item_kind_id,
                    material_id,
                    machine_type_val,
                    md.get("machine_tier"),
                    is_multiblock,
                    content_fluid_id,
                    content_qty,
                    crafting_grid_size,
                    is_storage_container,
                    storage_slot_count,
                ),
            )
            item_id = cur.lastrowid

            if kind in ("fluid", "gas") and self.has_cell_check.isChecked():
                self._ensure_auto_cell_for_fluid(
                    fluid_item_id=item_id,
                    fluid_name=display_name,
                    is_base=is_base,
                    liters=self._selected_auto_cell_liters(),
                )

            self.app.conn.commit()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self,
                "Save failed",
                f"Could not add item.\n\nDetails: {exc}",
            )
            return

        if hasattr(self.app, "last_added_item_id"):
            self.app.last_added_item_id = item_id

        if is_machine and self._show_availability and self.owned_spin is not None and self.online_spin is not None:
            owned = int(self.owned_spin.value())
            online = int(self.online_spin.value())
            if online > owned:
                online = owned
            try:
                self.app.set_machine_availability(
                    [
                        (
                            machine_type_val or "",
                            md.get("machine_tier") or "",
                            owned,
                            online,
                        )
                    ]
                )
            except Exception as exc:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Availability save failed",
                    f"Item added, but availability could not be saved.\n\nDetails: {exc}",
                )

        self._set_status(f"Added item: {display_name}")
        if hasattr(self.app, "_machines_load_from_db"):
            self.app._machines_load_from_db()
        self.accept()

    def _next_unique_key(self, key: str) -> str:
        cur = self.app.conn.execute("SELECT 1 FROM items WHERE key=?", (key,)).fetchone()
        if not cur:
            return key
        base = key
        n = 2
        while self.app.conn.execute("SELECT 1 FROM items WHERE key=?", (f"{base}_{n}",)).fetchone():
            n += 1
        return f"{base}_{n}"

    def _selected_auto_cell_liters(self) -> int:
        if self.auto_cell_144_radio.isChecked():
            return 144
        return 1000

    def _ensure_auto_cell_for_fluid(
        self,
        *,
        fluid_item_id: int,
        fluid_name: str,
        is_base: int,
        liters: int,
    ) -> None:
        cell_display_name = f"{fluid_name} Cell"
        cell_key = self._slugify(cell_display_name)
        cell_item_kind_id = self._get_or_create_cell_item_kind_id()
        existing = self.app.conn.execute(
            "SELECT id FROM items WHERE kind='item' AND (LOWER(key)=LOWER(?) OR content_fluid_id=?) LIMIT 1",
            (cell_key, fluid_item_id),
        ).fetchone()
        if existing:
            return

        self.app.conn.execute(
            "INSERT INTO items(key, display_name, kind, is_base, is_machine, item_kind_id, material_id, "
            "machine_type, machine_tier, is_multiblock, content_fluid_id, content_qty_liters, crafting_grid_size, is_storage_container, storage_slot_count) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                self._next_unique_key(cell_key),
                cell_display_name,
                "item",
                is_base,
                0,
                cell_item_kind_id,
                None,
                None,
                None,
                0,
                fluid_item_id,
                liters,
                None,
                0,
                None,
            ),
        )

    def _get_or_create_cell_item_kind_id(self) -> int | None:
        row = self.app.conn.execute(
            "SELECT id FROM item_kinds WHERE LOWER(name)='cell' AND LOWER(COALESCE(applies_to, 'item'))='item' LIMIT 1"
        ).fetchone()
        if row:
            return int(row["id"])

        canonical_name = self._ensure_item_kind("Cell", "item")
        if not canonical_name:
            return None
        row = self.app.conn.execute(
            "SELECT id FROM item_kinds WHERE LOWER(name)=LOWER(?) LIMIT 1",
            (canonical_name,),
        ).fetchone()
        if not row:
            return None
        return int(row["id"])


class EditItemDialog(_ItemDialogBase):
    def __init__(self, app, item_id: int, parent=None):
        row = app.conn.execute(
            "SELECT i.id, i.key, COALESCE(i.display_name, i.key) AS name, i.display_name, i.kind, "
            "       i.is_base, i.is_machine, i.machine_type, i.machine_tier, i.is_multiblock, "
            "       i.content_fluid_id, i.content_qty_liters, i.crafting_grid_size, i.is_storage_container, i.storage_slot_count, "
            "       i.item_kind_id, i.material_id, k.name AS item_kind_name, m.name AS material_name "
            "FROM items i "
            "LEFT JOIN item_kinds k ON k.id = i.item_kind_id "
            "LEFT JOIN materials m ON m.id = i.material_id "
            "WHERE i.id=?",
            (item_id,),
        ).fetchone()
        self._original_key = row["key"] if row else None
        super().__init__(app, "Edit Item", row=row, parent=parent)
        if not row:
            QtWidgets.QMessageBox.warning(self, "Not found", "Item not found.")
            self.reject()

    def save(self) -> None:
        display_name = (self.display_name_edit.text() or "").strip()
        if not display_name:
            QtWidgets.QMessageBox.warning(self, "Missing name", "Display Name is required.")
            return

        kind = self._current_kind_value()
        if kind not in ("item", "fluid", "gas", "machine", "crafting_grid"):
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid kind",
                "Kind must be item, fluid, gas, machine, or crafting grid.",
            )
            return

        is_base = 1 if self.is_base_check.isChecked() else 0
        is_multiblock = 1 if self.is_multiblock_check.isChecked() else 0

        # "Machine" is now a top-level Kind
        is_machine = 1 if kind == "machine" else 0
        item_kind_id = None if kind in ("gas", "crafting_grid") else self.item_kind_id

        crafting_grid_size = None
        if kind == "crafting_grid":
            crafting_grid_size = self.crafting_grid_size
            if not crafting_grid_size:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Missing grid size",
                    "Crafting Grid items require a grid size selection.",
                )
                return

        if self.has_material_check.isVisible() and self.has_material_check.isChecked():
            material_id = self.material_id
        else:
            material_id = None
            
        content_fluid_id = None
        content_qty = None
        if self.is_container_check.isVisible() and self.is_container_check.isChecked():
            content_fluid_id = self.content_fluid_id
            if content_fluid_id is not None:
                try:
                    content_qty = int(self.content_qty_edit.text())
                except ValueError:
                    content_qty = 0

        is_storage_container = 1 if (kind == "item" and self.is_storage_container_check.isChecked()) else 0
        storage_slot_count = self.storage_slot_count_spin.value() if is_storage_container else None

        md = {}
        machine_type_val = None
        if is_machine:
            md = self._get_machine_values()
            machine_type_val = (self.machine_type_combo.currentText() or "").strip() or None
            if not machine_type_val:
                QtWidgets.QMessageBox.warning(self, "Missing machine type", "Machine Type is required.")
                return
            if not md.get("machine_tier"):
                QtWidgets.QMessageBox.warning(self, "Missing tier", "Tier is required for machines.")
                return

        try:
            self.app.conn.execute(
                "UPDATE items SET display_name=?, kind=?, is_base=?, is_machine=?, item_kind_id=?, material_id=?, "
                "machine_type=?, machine_tier=?, is_multiblock=?, content_fluid_id=?, content_qty_liters=?, crafting_grid_size=?, is_storage_container=?, storage_slot_count=? "
                "WHERE id=?",
                (
                    display_name,
                    kind,
                    is_base,
                    is_machine,
                    item_kind_id,
                    material_id,
                    machine_type_val,
                    md.get("machine_tier"),
                    is_multiblock,
                    content_fluid_id,
                    content_qty,
                    crafting_grid_size,
                    is_storage_container,
                    storage_slot_count,
                    self.item_id,
                ),
            )

            self.app.conn.commit()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self,
                "Save failed",
                f"Could not update item.\n\nDetails: {exc}",
            )
            return

        self._set_status(f"Updated item: {display_name}")
        if hasattr(self.app, "_machines_load_from_db"):
            self.app._machines_load_from_db()
        self.accept()

class ItemLineDialog(QtWidgets.QDialog):
    def __init__(
        self,
        app,
        title: str,
        *,
        show_chance: bool = False,
        show_consumption: bool = False,
        input_slot_choices: list[int] | None = None,
        fixed_input_slot: int | None = None,
        require_input_slot: bool = False,
        output_slot_choices: list[int] | None = None,
        fixed_output_slot: int | None = None,
        require_chance: bool = False,
        initial_line: dict | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle(title)
        self.show_chance = show_chance
        self.show_consumption = show_consumption
        self.input_slot_choices = input_slot_choices
        self.fixed_input_slot = fixed_input_slot
        self.require_input_slot = require_input_slot
        self.output_slot_choices = output_slot_choices
        self.fixed_output_slot = fixed_output_slot
        self.require_chance = require_chance
        self.result = None
        self._selected = None

        layout = QtWidgets.QGridLayout(self)

        layout.addWidget(QtWidgets.QLabel("Item"), 0, 0)
        self.item_label = QtWidgets.QLabel("(none selected)")
        layout.addWidget(self.item_label, 0, 1)
        btns_item = QtWidgets.QHBoxLayout()
        pick_btn = QtWidgets.QPushButton("Pick…")
        pick_btn.clicked.connect(self.pick_item)
        new_btn = QtWidgets.QPushButton("New Item…")
        new_btn.clicked.connect(self.new_item)
        btns_item.addWidget(pick_btn)
        btns_item.addWidget(new_btn)
        layout.addLayout(btns_item, 0, 2)

        layout.addWidget(QtWidgets.QLabel("Kind"), 1, 0)
        self.kind_label = QtWidgets.QLabel("(select an item)")
        layout.addWidget(self.kind_label, 1, 1)

        self.qty_label = QtWidgets.QLabel("Quantity")
        layout.addWidget(self.qty_label, 2, 0)
        self.qty_edit = QtWidgets.QLineEdit()
        self.qty_edit.setValidator(QtGui.QIntValidator(1, 10**9))
        layout.addWidget(self.qty_edit, 2, 1)

        row = 3
        if self.show_consumption:
            layout.addWidget(QtWidgets.QLabel("Consumption Chance (%)"), row, 0)
            self.consumption_edit = QtWidgets.QLineEdit()
            self.consumption_edit.setValidator(QtGui.QDoubleValidator(0.0, 100.0, 3))
            layout.addWidget(self.consumption_edit, row, 1)
            consumption_btns = QtWidgets.QHBoxLayout()
            consumption_zero = QtWidgets.QPushButton("0%")
            consumption_zero.clicked.connect(lambda: self.consumption_edit.setText("0"))
            consumption_full = QtWidgets.QPushButton("100%")
            consumption_full.clicked.connect(lambda: self.consumption_edit.setText("100"))
            consumption_btns.addWidget(consumption_zero)
            consumption_btns.addWidget(consumption_full)
            consumption_btn_frame = QtWidgets.QWidget()
            consumption_btn_layout = QtWidgets.QHBoxLayout(consumption_btn_frame)
            consumption_btn_layout.setContentsMargins(0, 0, 0, 0)
            consumption_btn_layout.addLayout(consumption_btns)
            layout.addWidget(consumption_btn_frame, row, 2)
            row += 1
        if self.fixed_input_slot is not None or self.input_slot_choices:
            layout.addWidget(QtWidgets.QLabel("Grid Slot"), row, 0)
            if self.fixed_input_slot is not None:
                self.input_slot_label = QtWidgets.QLabel(str(self.fixed_input_slot))
                layout.addWidget(self.input_slot_label, row, 1)
            else:
                values = [str(v) for v in (self.input_slot_choices or [])]
                self.input_slot_combo = QtWidgets.QComboBox()
                self.input_slot_combo.addItems(values)
                if values:
                    self.input_slot_combo.setCurrentIndex(0)
                layout.addWidget(self.input_slot_combo, row, 1)
            row += 1
        if self.fixed_output_slot is not None or self.output_slot_choices:
            layout.addWidget(QtWidgets.QLabel("Output Slot"), row, 0)
            if self.fixed_output_slot is not None:
                self.output_slot_label = QtWidgets.QLabel(str(self.fixed_output_slot))
                layout.addWidget(self.output_slot_label, row, 1)
            else:
                values = [str(v) for v in (self.output_slot_choices or [])]
                self.output_slot_combo = QtWidgets.QComboBox()
                self.output_slot_combo.addItems(values)
                if values:
                    self.output_slot_combo.setCurrentIndex(0)
                layout.addWidget(self.output_slot_combo, row, 1)
            row += 1
        if self.show_chance:
            layout.addWidget(QtWidgets.QLabel("Chance (%)"), row, 0)
            self.chance_edit = QtWidgets.QLineEdit()
            self.chance_edit.setValidator(QtGui.QDoubleValidator(0.0, 100.0, 3))
            layout.addWidget(self.chance_edit, row, 1)
            chance_note = "Chance is required for extra output slots." if self.require_chance else "Leave blank for 100% (guaranteed)"
            layout.addWidget(QtWidgets.QLabel(chance_note), row, 2)
            row += 1

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, row, 0, 1, 3)

        row_count = self.app.conn.execute("SELECT COUNT(*) AS c FROM items").fetchone()
        if row_count and row_count["c"] == 1:
            only = self.app.conn.execute(
                "SELECT id, COALESCE(display_name, key) AS name, kind FROM items LIMIT 1"
            ).fetchone()
            if only:
                self._set_selected({"id": only["id"], "name": only["name"], "kind": only["kind"]})

        if initial_line:
            row_sel = self.app.conn.execute(
                "SELECT id, COALESCE(display_name, key) AS name, kind FROM items WHERE id=?",
                (initial_line.get("item_id"),),
            ).fetchone()
            if row_sel:
                self._set_selected({"id": row_sel["id"], "name": row_sel["name"], "kind": row_sel["kind"]})
            if initial_line.get("qty_liters") is not None:
                self.qty_edit.setText(str(self._coerce_whole_number(initial_line["qty_liters"])))
            elif initial_line.get("qty_count") is not None:
                self.qty_edit.setText(str(self._coerce_whole_number(initial_line["qty_count"])))
            if self.show_chance:
                chance = initial_line.get("chance_percent")
                if chance is None or abs(float(chance) - 100.0) < 1e-9:
                    self.chance_edit.setText("")
                else:
                    self.chance_edit.setText(str(chance))
            if self.show_consumption:
                consumption = initial_line.get("consumption_chance")
                if consumption is None:
                    self.consumption_edit.setText("")
                else:
                    display_percent = self._fraction_to_percent(consumption)
                    if isinstance(display_percent, (int, float)):
                        if abs(display_percent - int(display_percent)) < 1e-9:
                            self.consumption_edit.setText(str(int(display_percent)))
                        else:
                            self.consumption_edit.setText(str(display_percent))
                    else:
                        self.consumption_edit.setText(str(display_percent))
            if (
                self.fixed_output_slot is None
                and self.output_slot_choices is not None
                and initial_line.get("output_slot_index") is not None
            ):
                self.output_slot_combo.setCurrentText(str(initial_line["output_slot_index"]))
            if (
                self.fixed_input_slot is None
                and self.input_slot_choices is not None
                and initial_line.get("input_slot_index") is not None
            ):
                self.input_slot_combo.setCurrentText(str(initial_line["input_slot_index"]))
        self.update_kind_ui()

    @staticmethod
    def _coerce_whole_number(value):
        if value is None:
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return value

    @staticmethod
    def _fraction_to_percent(value):
        if value is None:
            return None
        try:
            v = float(value)
        except (TypeError, ValueError):
            return value
        if 0 <= v <= 1:
            return v * 100
        return v

    def _set_selected(self, sel: dict | None) -> None:
        self._selected = sel
        if not sel:
            self.item_label.setText("(none selected)")
        else:
            self.item_label.setText(sel["name"])
        self.update_kind_ui()

    def update_kind_ui(self) -> None:
        if not self._selected:
            self.kind_label.setText("(select an item)")
            self.qty_label.setText("Quantity")
            return
        kind = self._selected["kind"]
        self.kind_label.setText(kind)
        self.qty_label.setText("Liters (L)" if kind in ("fluid", "gas") else "Count")

    def pick_item(self) -> None:
        dlg = ItemPickerDialog(self.app, title="Pick Item", parent=self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted and dlg.result:
            self._set_selected({"id": dlg.result["id"], "name": dlg.result["name"], "kind": dlg.result["kind"]})

    def new_item(self) -> None:
        dlg = AddItemDialog(self.app, parent=self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            newest = self.app.conn.execute(
                "SELECT id, COALESCE(display_name, key) AS name, kind "
                "FROM items ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if newest:
                self._set_selected({"id": newest["id"], "name": newest["name"], "kind": newest["kind"]})

    def save(self) -> None:
        it = self._selected
        if not it:
            QtWidgets.QMessageBox.warning(self, "Missing item", "Select an item.")
            return
        qty_s = (self.qty_edit.text() or "").strip()
        try:
            if not qty_s.isdigit():
                raise ValueError
            qty = int(qty_s)
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Invalid quantity", "Quantity must be a whole number.")
            return
        if qty <= 0:
            QtWidgets.QMessageBox.warning(self, "Invalid quantity", "Quantity must be > 0.")
            return

        if it["kind"] in ("fluid", "gas"):
            self.result = {"item_id": it["id"], "name": it["name"], "kind": it["kind"], "qty_liters": qty, "qty_count": None}
        else:
            self.result = {"item_id": it["id"], "name": it["name"], "kind": it["kind"], "qty_liters": None, "qty_count": qty}

        if self.show_consumption:
            cons_s = (self.consumption_edit.text() or "").strip()
            if cons_s == "":
                self.result["consumption_chance"] = 1.0
            else:
                try:
                    consumption = float(cons_s)
                except ValueError:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Invalid consumption chance",
                        "Consumption chance must be a number between 0 and 100.",
                    )
                    return
                if consumption < 0 or consumption > 100:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Invalid consumption chance",
                        "Consumption chance must be between 0 and 100.",
                    )
                    return
                self.result["consumption_chance"] = consumption / 100.0

        if self.show_chance:
            ch_s = (self.chance_edit.text() or "").strip()
            if ch_s == "":
                if self.require_chance:
                    slot_val = None
                    if self.fixed_output_slot is not None:
                        slot_val = self.fixed_output_slot
                    elif getattr(self, "output_slot_combo", None):
                        try:
                            slot_val = int(self.output_slot_combo.currentText())
                        except Exception:
                            slot_val = None
                    if slot_val is not None and slot_val <= 0:
                        chance = 100.0
                        self.result["chance_percent"] = chance
                    else:
                        QtWidgets.QMessageBox.warning(self, "Invalid chance", "Chance is required for extra output slots.")
                        return
                else:
                    self.result["chance_percent"] = 100.0
            else:
                try:
                    chance = float(ch_s)
                except ValueError:
                    QtWidgets.QMessageBox.warning(self, "Invalid chance", "Chance must be a number between 0 and 100.")
                    return
                if chance <= 0 or chance > 100:
                    QtWidgets.QMessageBox.warning(self, "Invalid chance", "Chance must be > 0 and <= 100.")
                    return
                self.result["chance_percent"] = chance

        if self.fixed_input_slot is not None or self.input_slot_choices:
            try:
                if self.fixed_input_slot is not None:
                    slot_val = self.fixed_input_slot
                else:
                    slot_val = int(self.input_slot_combo.currentText())
                self.result["input_slot_index"] = slot_val
            except Exception:
                QtWidgets.QMessageBox.warning(self, "Invalid grid slot", "Select a valid grid slot.")
                return
            if self.require_input_slot and self.result.get("input_slot_index") is None:
                QtWidgets.QMessageBox.warning(self, "Missing grid slot", "Select a grid slot.")
                return

        if self.fixed_output_slot is not None or self.output_slot_choices:
            try:
                if self.fixed_output_slot is not None:
                    slot_val = self.fixed_output_slot
                else:
                    slot_val = int(self.output_slot_combo.currentText())
                self.result["output_slot_index"] = slot_val
            except Exception:
                QtWidgets.QMessageBox.warning(self, "Invalid output slot", "Select a valid output slot.")
                return

        self.accept()


class _RecipeDialogBase(QtWidgets.QDialog):
    def __init__(self, app, title: str, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle(title)
        self.resize(850, 520)
        self.inputs: list[dict] = []
        self.outputs: list[dict] = []
        self.name_item_id: int | None = None
        self.duplicate_of_recipe_id: int | None = None
        self._station_grid_lock = False

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QGridLayout()
        layout.addLayout(form)

        form.addWidget(QtWidgets.QLabel("Name"), 0, 0)
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setReadOnly(True)
        self.name_edit.setPlaceholderText("Use 'Pick' button...")

        name_btns = QtWidgets.QHBoxLayout()
        name_pick = QtWidgets.QPushButton("Pick…")
        name_pick.clicked.connect(self.pick_name)
        name_clear = QtWidgets.QPushButton("Clear")
        name_clear.clicked.connect(self.clear_name)
        name_btns.addWidget(name_pick)
        name_btns.addWidget(name_clear)

        name_frame = QtWidgets.QWidget()
        name_layout = QtWidgets.QHBoxLayout(name_frame)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.addWidget(self.name_edit)
        name_layout.addLayout(name_btns)
        form.addWidget(name_frame, 0, 1)

        form.addWidget(QtWidgets.QLabel("Method"), 0, 2)
        self.method_combo = QtWidgets.QComboBox()
        self.method_combo.addItems(["Machine", "Crafting"])
        form.addWidget(self.method_combo, 0, 3)

        self.variant_label = QtWidgets.QLabel("Variant")
        self.variant_combo = QtWidgets.QComboBox()
        self.variant_label.setVisible(False)
        self.variant_combo.setVisible(False)
        form.addWidget(self.variant_label, 1, 0)
        form.addWidget(self.variant_combo, 1, 1, 1, 3)

        self.machine_label = QtWidgets.QLabel("Machine")
        self.grid_label = QtWidgets.QLabel("Grid")
        self.method_label_stack = QtWidgets.QStackedWidget()
        self.method_label_stack.addWidget(self.machine_label)
        self.method_label_stack.addWidget(self.grid_label)
        form.addWidget(self.method_label_stack, 2, 0)

        self.machine_edit = QtWidgets.QLineEdit()
        self.machine_edit.setReadOnly(True)
        self.machine_edit.setPlaceholderText("Use 'Pick' button...")
        self.machine_item_id = None
        machine_btns = QtWidgets.QHBoxLayout()
        machine_pick = QtWidgets.QPushButton("Pick…")
        machine_pick.clicked.connect(self.pick_machine)
        machine_clear = QtWidgets.QPushButton("Clear")
        machine_clear.clicked.connect(self.clear_machine)
        machine_btns.addWidget(machine_pick)
        machine_btns.addWidget(machine_clear)
        machine_frame = QtWidgets.QWidget()
        machine_layout = QtWidgets.QHBoxLayout(machine_frame)
        machine_layout.setContentsMargins(0, 0, 0, 0)
        machine_layout.addWidget(self.machine_edit)
        machine_layout.addLayout(machine_btns)

        self.grid_combo = QtWidgets.QComboBox()
        self.grid_combo.addItems(self._get_available_grid_sizes())
        grid_frame = QtWidgets.QWidget()
        grid_layout = QtWidgets.QVBoxLayout(grid_frame)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_select_row = QtWidgets.QHBoxLayout()
        grid_select_row.addWidget(self.grid_combo)
        grid_select_row.addStretch(1)
        grid_layout.addLayout(grid_select_row)
        self.grid_preview = QtWidgets.QWidget()
        self.grid_preview_layout = QtWidgets.QGridLayout(self.grid_preview)
        self.grid_preview_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_preview_layout.setSpacing(4)
        grid_layout.addWidget(self.grid_preview)
        self.grid_note_label = QtWidgets.QLabel("Grid slots are numbered left → right, top → bottom.")
        self.grid_note_label.setStyleSheet("color: #888;")
        grid_layout.addWidget(self.grid_note_label)

        self.method_field_stack = QtWidgets.QStackedWidget()
        self.method_field_stack.addWidget(machine_frame)
        self.method_field_stack.addWidget(grid_frame)
        form.addWidget(self.method_field_stack, 2, 1)

        self.tier_label = QtWidgets.QLabel("Tier")
        form.addWidget(self.tier_label, 2, 2)
        self.tier_combo = QtWidgets.QComboBox()
        enabled_tiers = self.app.get_enabled_tiers() if hasattr(self.app, "get_enabled_tiers") else ALL_TIERS
        self.tier_combo.addItems([NONE_TIER_LABEL] + list(enabled_tiers))
        form.addWidget(self.tier_combo, 2, 3)

        self.circuit_label = QtWidgets.QLabel("Circuit")
        form.addWidget(self.circuit_label, 3, 0)
        self.circuit_edit = QtWidgets.QLineEdit()
        self.circuit_edit.setValidator(QtGui.QIntValidator(0, 10**9))
        form.addWidget(self.circuit_edit, 3, 1)

        self.station_label = QtWidgets.QLabel("Station")
        self.station_edit = QtWidgets.QLineEdit()
        self.station_edit.setReadOnly(True)
        self.station_item_id = None
        station_btns = QtWidgets.QHBoxLayout()
        station_pick = QtWidgets.QPushButton("Pick…")
        station_pick.clicked.connect(self.pick_station)
        station_clear = QtWidgets.QPushButton("Clear")
        station_clear.clicked.connect(self.clear_station)
        station_btns.addWidget(station_pick)
        station_btns.addWidget(station_clear)
        self.station_frame = QtWidgets.QWidget()
        station_layout = QtWidgets.QHBoxLayout(self.station_frame)
        station_layout.setContentsMargins(0, 0, 0, 0)
        station_layout.addWidget(self.station_edit)
        station_layout.addLayout(station_btns)
        form.addWidget(self.station_label, 3, 2)
        form.addWidget(self.station_frame, 3, 3)

        self.duration_label = QtWidgets.QLabel("Duration (seconds)")
        form.addWidget(self.duration_label, 4, 0)
        self.duration_edit = QtWidgets.QLineEdit()
        self.duration_edit.setValidator(QtGui.QDoubleValidator(0.0, 10**9, 3))
        form.addWidget(self.duration_edit, 4, 1)

        self.eut_label = QtWidgets.QLabel("EU/t")
        form.addWidget(self.eut_label, 4, 2)
        self.eut_edit = QtWidgets.QLineEdit()
        self.eut_edit.setValidator(QtGui.QIntValidator(0, 10**9))
        form.addWidget(self.eut_edit, 4, 3)

        self.additional_notes_check = QtWidgets.QCheckBox("Additional Notes")
        self.additional_notes_check.setChecked(False)
        form.addWidget(self.additional_notes_check, 5, 0, 1, 2)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        layout.addWidget(splitter, stretch=1)

        self.notes_widget = QtWidgets.QWidget()
        notes_layout = QtWidgets.QVBoxLayout(self.notes_widget)
        notes_layout.setContentsMargins(0, 0, 0, 0)
        notes_layout.addWidget(QtWidgets.QLabel("Notes"))
        self.notes_edit = QtWidgets.QTextEdit()
        notes_layout.addWidget(self.notes_edit)
        splitter.addWidget(self.notes_widget)
        self.notes_widget.setVisible(False)

        lists_widget = QtWidgets.QWidget()
        lists_layout = QtWidgets.QHBoxLayout(lists_widget)
        lists_layout.setContentsMargins(0, 0, 0, 0)

        in_col = QtWidgets.QVBoxLayout()
        lists_layout.addLayout(in_col)
        in_col.addWidget(QtWidgets.QLabel("Inputs"))
        self.in_list = QtWidgets.QListWidget()
        in_col.addWidget(self.in_list, stretch=1)
        in_btns = QtWidgets.QHBoxLayout()
        self.btn_add_input = QtWidgets.QPushButton("Add Input")
        self.btn_add_input.clicked.connect(self.add_input)
        in_btns.addWidget(self.btn_add_input)
        in_col.addLayout(in_btns)
        self.in_btns_layout = in_btns

        out_col = QtWidgets.QVBoxLayout()
        lists_layout.addLayout(out_col)
        out_col.addWidget(QtWidgets.QLabel("Outputs"))
        self.out_list = QtWidgets.QListWidget()
        out_col.addWidget(self.out_list, stretch=1)
        out_btns = QtWidgets.QHBoxLayout()
        self.btn_add_output = QtWidgets.QPushButton("Add Output")
        self.btn_add_output.clicked.connect(self.add_output)
        out_btns.addWidget(self.btn_add_output)
        out_col.addLayout(out_btns)
        self.out_btns_layout = out_btns

        splitter.addWidget(lists_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        bottom = QtWidgets.QHBoxLayout()
        bottom.addWidget(QtWidgets.QLabel("Tip: Close window or Cancel to discard. No partial saves."))
        bottom.addStretch(1)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        bottom.addWidget(buttons)
        layout.addLayout(bottom)

        self.method_combo.currentTextChanged.connect(self._toggle_method_fields)
        self.grid_combo.currentTextChanged.connect(self._refresh_crafting_grid)
        self.additional_notes_check.toggled.connect(self._toggle_notes_editor)
        self._toggle_method_fields()

    def _set_variant_visible(self, visible: bool) -> None:
        self.variant_label.setVisible(visible)
        self.variant_combo.setVisible(visible)

    def _toggle_notes_editor(self, checked: bool) -> None:
        self.notes_widget.setVisible(checked)
        if not checked:
            self.notes_edit.clear()

    def _toggle_method_fields(self) -> None:
        method = (self.method_combo.currentText() or "Machine").strip().lower()
        is_crafting = method == "crafting"

        self.method_label_stack.setCurrentIndex(1 if is_crafting else 0)
        self.method_field_stack.setCurrentIndex(1 if is_crafting else 0)

        self.station_label.setVisible(is_crafting)
        self.station_frame.setVisible(is_crafting)
        if is_crafting:
            self._apply_station_grid_size()
            self._refresh_crafting_grid()
        else:
            self.grid_combo.setEnabled(True)

    def _get_available_grid_sizes(self) -> list[str]:
        if hasattr(self.app, "get_crafting_grids"):
            grid_values = list(self.app.get_crafting_grids())
        else:
            grid_values = ["2x2", "3x3"]
        grid_values = [g for g in grid_values if g]
        if "2x2" not in grid_values:
            grid_values.insert(0, "2x2")
        if hasattr(self.app, "is_crafting_6x6_unlocked"):
            if self.app.is_crafting_6x6_unlocked():
                if "6x6" not in grid_values:
                    grid_values.append("6x6")
            else:
                grid_values = [g for g in grid_values if g.strip().lower() != "6x6"]
        return grid_values

    @staticmethod
    def _parse_grid_size(value: str) -> tuple[int, int] | None:
        raw = (value or "").strip().lower().replace("×", "x")
        if "x" not in raw:
            return None
        parts = [p.strip() for p in raw.split("x", 1)]
        if len(parts) != 2:
            return None
        if not parts[0].isdigit() or not parts[1].isdigit():
            return None
        rows = int(parts[0])
        cols = int(parts[1])
        if rows <= 0 or cols <= 0:
            return None
        return rows, cols

    def _refresh_crafting_grid(self) -> None:
        if self._station_grid_lock:
            return
        while self.grid_preview_layout.count():
            item = self.grid_preview_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        dims = self._parse_grid_size(self.grid_combo.currentText())
        if not dims:
            return
        rows, cols = dims
        slot = 1
        for r in range(rows):
            for c in range(cols):
                label = QtWidgets.QLabel(str(slot))
                label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                label.setMinimumSize(26, 26)
                label.setStyleSheet("border: 1px solid #3a3c40; border-radius: 3px;")
                self.grid_preview_layout.addWidget(label, r, c)
                slot += 1

    def _fetch_crafting_grid_size(self, item_id: int) -> str | None:
        row = self.app.conn.execute(
            "SELECT crafting_grid_size FROM items WHERE id=?",
            (item_id,),
        ).fetchone()
        if not row:
            return None
        return (row["crafting_grid_size"] or "").strip() or None

    def _apply_station_grid_size(self) -> None:
        if self.station_item_id is None:
            self.grid_combo.setEnabled(True)
            return
        grid_size = self._fetch_crafting_grid_size(self.station_item_id)
        if not grid_size:
            self.grid_combo.setEnabled(True)
            return
        if self.grid_combo.findText(grid_size) == -1:
            self.grid_combo.addItem(grid_size)
        self._station_grid_lock = True
        try:
            self.grid_combo.setCurrentText(grid_size)
        finally:
            self._station_grid_lock = False
        self.grid_combo.setEnabled(False)
        self._refresh_crafting_grid()

    def pick_machine(self) -> None:
        d = ItemPickerDialog(self.app, title="Pick Machine", machines_only=True, parent=self)
        if d.exec() == QtWidgets.QDialog.DialogCode.Accepted and d.result:
            self.machine_item_id = d.result["id"]
            self.machine_edit.setText(d.result["name"])
            row = self.app.conn.execute(
                "SELECT machine_tier FROM items WHERE id=?",
                (self.machine_item_id,),
            ).fetchone()
            if row:
                machine_tier = (row["machine_tier"] or "").strip()
                if machine_tier:
                    if self.tier_combo.findText(machine_tier) == -1:
                        self.tier_combo.addItem(machine_tier)
                    self.tier_combo.setCurrentText(machine_tier)

    def clear_machine(self) -> None:
        self.machine_item_id = None
        self.machine_edit.setText("")

    def pick_station(self) -> None:
        d = ItemPickerDialog(self.app, title="Pick Station", crafting_grids_only=True, parent=self)
        if d.exec() == QtWidgets.QDialog.DialogCode.Accepted and d.result:
            self.station_item_id = d.result["id"]
            self.station_edit.setText(d.result["name"])
            self._apply_station_grid_size()

    def pick_name(self) -> None:
        d = ItemPickerDialog(self.app, title="Pick Recipe Item", parent=self)
        if d.exec() == QtWidgets.QDialog.DialogCode.Accepted and d.result:
            self.name_item_id = d.result["id"]
            self.name_edit.setText(d.result["name"])

    def clear_name(self) -> None:
        self.name_item_id = None
        self.name_edit.setText("")

    def clear_station(self) -> None:
        self.station_item_id = None
        self.station_edit.setText("")
        self.grid_combo.setEnabled(True)

    def _resolve_name_item_id(self, *, warn: bool = True) -> int | None:
        # If we have a specific item ID from the picker (or loaded from DB), use it.
        if self.name_item_id is not None:
            return self.name_item_id

        # Fallback logic (legacy or if ID was somehow cleared but text remains)
        name = (self.name_edit.text() or "").strip()
        if not name:
            if warn:
                QtWidgets.QMessageBox.warning(self, "Missing name", "Recipe name is required.")
            return None
        rows = self.app.conn.execute(
            "SELECT id FROM items WHERE COALESCE(display_name, key)=?",
            (name,),
        ).fetchall()
        if not rows:
            if warn:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Unknown item",
                    "Pick a recipe name from the items list so it matches an item.",
                )
            return None
        if len(rows) > 1:
            if warn:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Ambiguous name",
                    "Multiple items share that name. Please pick the item from the list.",
                )
            return None
        return int(rows[0]["id"])

    def _validate_name_output(self, item_id: int) -> bool:
        if not any(line.get("item_id") == item_id for line in self.outputs):
            QtWidgets.QMessageBox.warning(
                self,
                "Missing output",
                "The recipe outputs must include the selected item name.",
            )
            return False
        return True

    def _fmt_line(self, line: dict, *, is_output: bool = False) -> str:
        chance = line.get("chance_percent")
        chance_txt = ""
        if chance is not None:
            try:
                c = float(chance)
            except Exception:
                c = None
            if c is not None and c < 99.999:
                if abs(c - int(c)) < 1e-9:
                    chance_txt = f" ({int(c)}%)"
                else:
                    chance_txt = f" ({c}%)"
        slot_txt = ""
        if is_output:
            slot_idx = line.get("output_slot_index")
            if slot_idx is not None:
                slot_txt = f" (Slot {slot_idx})"
        else:
            slot_idx = line.get("input_slot_index")
            if slot_idx is not None:
                slot_txt = f" (Slot {slot_idx})"
        if line["kind"] in ("fluid", "gas"):
            qty = self._coerce_whole_number(line["qty_liters"])
            return f"{line['name']} × {qty} L{slot_txt}{chance_txt}"
        qty = self._coerce_whole_number(line["qty_count"])
        return f"{line['name']} × {qty}{slot_txt}{chance_txt}"

    @staticmethod
    def _coerce_whole_number(value):
        if value is None:
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return value

    def _get_machine_output_slots(self) -> int | None:
        if self.machine_item_id is None:
            return None
        row = self.app.conn.execute(
            "SELECT machine_type, machine_tier FROM items WHERE id=?",
            (self.machine_item_id,),
        ).fetchone()
        if not row:
            return None
        tier_raw = (self.tier_combo.currentText() or "").strip()
        tier = None if tier_raw in ("", NONE_TIER_LABEL) else tier_raw
        if tier is None:
            tier = (row["machine_tier"] or "").strip() or None
        if tier:
            machine_type = (row["machine_type"] or "").strip()
            if machine_type:
                meta = self.app.conn.execute(
                    """
                    SELECT output_slots
                    FROM machine_metadata
                    WHERE LOWER(machine_type)=LOWER(?) AND tier=?
                    """,
                    (machine_type, tier),
                ).fetchone()
                if meta:
                    try:
                        slots = int(meta["output_slots"] or 1)
                    except Exception:
                        slots = 1
                    return slots if slots > 0 else 1
        return 1

    def _get_machine_tank_limits(self) -> tuple[int | None, int | None]:
        if self.machine_item_id is None:
            return None, None
        row = self.app.conn.execute(
            "SELECT machine_type, machine_tier FROM items WHERE id=?",
            (self.machine_item_id,),
        ).fetchone()
        if not row:
            return None, None
        tier_raw = (self.tier_combo.currentText() or "").strip()
        tier = None if tier_raw in ("", NONE_TIER_LABEL) else tier_raw
        if tier is None:
            tier = (row["machine_tier"] or "").strip() or None
        if tier:
            machine_type = (row["machine_type"] or "").strip()
            if machine_type:
                meta = self.app.conn.execute(
                    """
                    SELECT input_tanks, output_tanks
                    FROM machine_metadata
                    WHERE LOWER(machine_type)=LOWER(?) AND tier=?
                    """,
                    (machine_type, tier),
                ).fetchone()
                if meta:
                    in_tanks = int(meta["input_tanks"] or 0)
                    out_tanks = int(meta["output_tanks"] or 0)
                    return (in_tanks if in_tanks > 0 else None, out_tanks if out_tanks > 0 else None)
        return None, None

    def _parse_int_opt(self, s: str):
        s = (s or "").strip()
        if s == "":
            return None
        if not s.isdigit():
            raise ValueError("Must be an integer.")
        return int(s)

    def _parse_float_opt(self, s: str) -> float | None:
        s = (s or "").strip()
        if s == "":
            return None
        try:
            v = float(s)
        except ValueError as exc:
            raise ValueError("Must be a number.") from exc
        if v < 0:
            raise ValueError("Must be zero or greater.")
        return v

    @staticmethod
    def _canonical_name(name: str) -> str:
        return " ".join((name or "").split()).strip().casefold()

    def _fetch_item_name(self, item_id: int) -> str:
        row = self.app.conn.execute(
            "SELECT COALESCE(display_name, key) AS name FROM items WHERE id=?",
            (item_id,),
        ).fetchone()
        return row["name"] if row else ""

    def _insert_recipe(
        self,
        name: str,
        method_db: str,
        machine: str | None,
        machine_item_id: int | None,
        grid_size: str | None,
        station_item_id: int | None,
        circuit: int | None,
        tier: str | None,
        duration_ticks: int | None,
        eut: int | None,
        notes: str | None,
        duplicate_of_recipe_id: int | None = None,
    ) -> int:
        cur = self.app.conn.execute(
            """INSERT INTO recipes(
                   name, method, machine, machine_item_id, grid_size, station_item_id,
                   circuit, tier, duration_ticks, eu_per_tick, notes, duplicate_of_recipe_id
               )
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                name,
                method_db,
                machine,
                machine_item_id,
                grid_size,
                station_item_id,
                circuit,
                tier,
                duration_ticks,
                eut,
                notes,
                duplicate_of_recipe_id,
            ),
        )
        return int(cur.lastrowid)

    def _insert_recipe_lines(self, recipe_id: int) -> None:
        for line in self.inputs:
            if line["kind"] in ("fluid", "gas"):
                self.app.conn.execute(
                    "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_liters, chance_percent, consumption_chance, output_slot_index, input_slot_index) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (
                        recipe_id,
                        "in",
                        line["item_id"],
                        line["qty_liters"],
                        None,
                        line.get("consumption_chance", 1.0),
                        None,
                        line.get("input_slot_index"),
                    ),
                )
            else:
                self.app.conn.execute(
                    "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_count, chance_percent, consumption_chance, output_slot_index, input_slot_index) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (
                        recipe_id,
                        "in",
                        line["item_id"],
                        line["qty_count"],
                        None,
                        line.get("consumption_chance", 1.0),
                        None,
                        line.get("input_slot_index"),
                    ),
                )

        for line in self.outputs:
            if line["kind"] in ("fluid", "gas"):
                self.app.conn.execute(
                    "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_liters, chance_percent, output_slot_index, input_slot_index) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (
                        recipe_id,
                        "out",
                        line["item_id"],
                        line["qty_liters"],
                        line.get("chance_percent", 100.0),
                        line.get("output_slot_index"),
                        None,
                    ),
                )
            else:
                self.app.conn.execute(
                    "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_count, chance_percent, output_slot_index, input_slot_index) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (
                        recipe_id,
                        "out",
                        line["item_id"],
                        line["qty_count"],
                        line.get("chance_percent", 100.0),
                        line.get("output_slot_index"),
                        None,
                    ),
                )

    def _sync_output_duplicates(
        self,
        base_recipe_id: int,
        base_name_item_id: int,
        method_db: str,
        machine: str | None,
        machine_item_id: int | None,
        grid_size: str | None,
        station_item_id: int | None,
        circuit: int | None,
        tier: str | None,
        duration_ticks: int | None,
        eut: int | None,
        notes: str | None,
    ) -> None:
        desired: dict[str, dict[str, str | int]] = {}
        for line in self.outputs:
            item_id = line.get("item_id")
            if item_id is None or item_id == base_name_item_id:
                continue
            name = self._fetch_item_name(item_id) or (line.get("name") or "")
            if not name:
                continue
            canon = self._canonical_name(name)
            has_canonical = self.app.conn.execute(
                "SELECT 1 FROM recipes WHERE duplicate_of_recipe_id IS NULL AND LOWER(name)=LOWER(?) LIMIT 1",
                (name,),
            ).fetchone()
            if has_canonical:
                continue
            desired[canon] = {"name": name, "item_id": int(item_id)}

        existing_rows = self.app.conn.execute(
            "SELECT id, name FROM recipes WHERE duplicate_of_recipe_id=?",
            (base_recipe_id,),
        ).fetchall()
        existing = {
            self._canonical_name(row["name"]): row
            for row in existing_rows
            if row["name"]
        }

        for canon, row in existing.items():
            if canon not in desired:
                self.app.conn.execute("DELETE FROM recipe_lines WHERE recipe_id=?", (row["id"],))
                self.app.conn.execute("DELETE FROM recipes WHERE id=?", (row["id"],))

        for canon, meta in desired.items():
            name = str(meta["name"])
            row = existing.get(canon)
            if row:
                self.app.conn.execute(
                    """UPDATE recipes SET
                       name=?, method=?, machine=?, machine_item_id=?, grid_size=?, station_item_id=?,
                       circuit=?, tier=?, duration_ticks=?, eu_per_tick=?, notes=?, duplicate_of_recipe_id=?
                       WHERE id=?""",
                    (
                        name,
                        method_db,
                        machine,
                        machine_item_id,
                        grid_size,
                        station_item_id,
                        circuit,
                        tier,
                        duration_ticks,
                        eut,
                        notes,
                        base_recipe_id,
                        row["id"],
                    ),
                )
                self.app.conn.execute("DELETE FROM recipe_lines WHERE recipe_id=?", (row["id"],))
                self._insert_recipe_lines(int(row["id"]))
                continue

            new_id = self._insert_recipe(
                name,
                method_db,
                machine,
                machine_item_id,
                grid_size,
                station_item_id,
                circuit,
                tier,
                duration_ticks,
                eut,
                notes,
                duplicate_of_recipe_id=base_recipe_id,
            )
            self._insert_recipe_lines(new_id)

    def save(self) -> None:
        raise NotImplementedError

    # --- Shared List Management Methods (Moved from EditRecipeDialog) ---

    def add_input(self) -> None:
        dialog_kwargs = self._get_input_dialog_kwargs()
        if dialog_kwargs is None:
            return
        d = ItemLineDialog(self.app, "Add Input", parent=self, **dialog_kwargs)
        if d.exec() == QtWidgets.QDialog.DialogCode.Accepted and d.result:
            if d.result.get("kind") in ("fluid", "gas") and not self._check_tank_limit(direction="in"):
                return
            self.inputs.append(d.result)
            self.in_list.addItem(self._fmt_line(d.result))

    def add_output(self) -> None:
        dialog_kwargs = self._get_output_dialog_kwargs()
        d = ItemLineDialog(self.app, "Add Output", parent=self, **dialog_kwargs)
        if d.exec() == QtWidgets.QDialog.DialogCode.Accepted and d.result:
            if d.result.get("kind") in ("fluid", "gas") and not self._check_tank_limit(direction="out"):
                return
            self.outputs.append(d.result)
            self.out_list.addItem(self._fmt_line(d.result, is_output=True))

    def edit_selected(self, list_widget: QtWidgets.QListWidget, backing_list: list, *, is_output: bool = False) -> None:
        idx = list_widget.currentRow()
        if idx < 0:
            return
        line = backing_list[idx]
        dialog_kwargs = {}
        if is_output:
            dialog_kwargs = self._get_output_dialog_kwargs(current_slot=line.get("output_slot_index"))
        else:
            dialog_kwargs = self._get_input_dialog_kwargs(current_slot=line.get("input_slot_index"))
        if dialog_kwargs is None:
            return
        d = ItemLineDialog(
            self.app,
            "Edit Output" if is_output else "Edit Input",
            initial_line=line,
            parent=self,
            **dialog_kwargs,
        )
        if d.exec() == QtWidgets.QDialog.DialogCode.Accepted and d.result:
            if d.result.get("kind") in ("fluid", "gas"):
                if is_output and not self._check_tank_limit(direction="out", exclude_idx=idx):
                    return
                if not is_output and not self._check_tank_limit(direction="in", exclude_idx=idx):
                    return
            new_line = d.result
            new_line["id"] = line.get("id")
            backing_list[idx] = new_line
            list_widget.item(idx).setText(self._fmt_line(new_line, is_output=is_output))

    def remove_selected(self, list_widget: QtWidgets.QListWidget, backing_list: list) -> None:
        idx = list_widget.currentRow()
        if idx < 0:
            return
        backing_list.pop(idx)
        list_widget.takeItem(idx)

    @staticmethod
    def _count_fluid_lines(lines: list[dict], *, exclude_idx: int | None = None) -> int:
        count = 0
        for idx, line in enumerate(lines):
            if exclude_idx is not None and idx == exclude_idx:
                continue
            if line.get("kind") in ("fluid", "gas"):
                count += 1
        return count

    def _check_tank_limit(self, *, direction: str, exclude_idx: int | None = None) -> bool:
        in_tanks, out_tanks = self._get_machine_tank_limits()
        limit = in_tanks if direction == "in" else out_tanks
        if limit is None:
            return True
        lines = self.inputs if direction == "in" else self.outputs
        if self._count_fluid_lines(lines, exclude_idx=exclude_idx) >= limit:
            QtWidgets.QMessageBox.warning(
                self,
                "No tank available",
                f"This machine only has {limit} fluid {direction} tank(s).",
            )
            return False
        return True

    def _get_used_output_slots(self, *, exclude_slot: int | None = None) -> set[int]:
        used = set()
        for line in self.outputs:
            slot_idx = line.get("output_slot_index")
            if slot_idx is not None:
                slot_val = int(slot_idx)
                if exclude_slot is not None and slot_val == exclude_slot:
                    continue
                used.add(slot_val)
        return used

    def _get_used_input_slots(self, *, exclude_slot: int | None = None) -> set[int]:
        used = set()
        for line in self.inputs:
            slot_idx = line.get("input_slot_index")
            if slot_idx is not None:
                slot_val = int(slot_idx)
                if exclude_slot is not None and slot_val == exclude_slot:
                    continue
                used.add(slot_val)
        return used

    def _get_crafting_grid_slots(self) -> list[int]:
        dims = self._parse_grid_size(self.grid_combo.currentText())
        if not dims:
            return []
        rows, cols = dims
        return list(range(1, rows * cols + 1))

    def _get_input_dialog_kwargs(self, *, current_slot: int | None = None) -> dict | None:
        method = (self.method_combo.currentText() or "Machine").strip().lower()
        dialog_kwargs = {"show_consumption": True}
        if method != "crafting":
            return dialog_kwargs
        slots = self._get_crafting_grid_slots()
        if not slots:
            QtWidgets.QMessageBox.warning(self, "Invalid grid", "Select a valid crafting grid size first.")
            return None
        used_slots = self._get_used_input_slots(exclude_slot=current_slot)
        available = [slot for slot in slots if slot not in used_slots]
        if current_slot is not None and current_slot not in available:
            available.append(current_slot)
        available.sort()
        dialog_kwargs.update(
            {
                "input_slot_choices": available,
                "require_input_slot": True,
            }
        )
        return dialog_kwargs

    def _validate_crafting_inputs(self, grid_size: str) -> bool:
        dims = self._parse_grid_size(grid_size)
        if not dims:
            QtWidgets.QMessageBox.warning(self, "Invalid grid", "Select a valid crafting grid size.")
            return False
        rows, cols = dims
        max_slot = rows * cols
        seen = set()
        for line in self.inputs:
            slot = line.get("input_slot_index")
            if slot is None:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Missing grid slot",
                    "Each crafting input must be assigned to a grid slot.",
                )
                return False
            if slot < 1 or slot > max_slot:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Invalid grid slot",
                    f"Slot {slot} is outside the {grid_size} grid.",
                )
                return False
            if slot in seen:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Duplicate grid slot",
                    f"Slot {slot} is already used by another input.",
                )
                return False
            seen.add(slot)
        return True

    def _get_output_dialog_kwargs(self, *, current_slot: int | None = None) -> dict:
        method = (self.method_combo.currentText() or "Machine").strip().lower()
        if method == "machine" and self.machine_item_id is not None:
            mos = self._get_machine_output_slots() or 1
            if mos <= 1:
                if current_slot is not None and current_slot != 0:
                    return {"show_chance": True, "output_slot_choices": [current_slot], "require_chance": True}
                return {"show_chance": True, "fixed_output_slot": 0}
            used_slots = self._get_used_output_slots(exclude_slot=current_slot)
            slots = [i for i in range(0, mos) if i not in used_slots]
            if current_slot is not None and current_slot not in slots:
                slots.append(current_slot)
            slots.sort()
            return {"show_chance": True, "output_slot_choices": slots, "require_chance": True}
        return {"show_chance": True}


class AddRecipeDialog(_RecipeDialogBase):
    def __init__(self, app, parent=None):
        super().__init__(app, "Add Recipe", parent=parent)

        # Add Edit/Remove buttons which are not in base layout
        self.btn_edit_input = QtWidgets.QPushButton("Edit")
        self.btn_edit_input.clicked.connect(lambda: self.edit_selected(self.in_list, self.inputs))
        self.btn_remove_input = QtWidgets.QPushButton("Remove")
        self.btn_remove_input.clicked.connect(lambda: self.remove_selected(self.in_list, self.inputs))
        self.in_btns_layout.addWidget(self.btn_edit_input)
        self.in_btns_layout.addWidget(self.btn_remove_input)

        self.btn_edit_output = QtWidgets.QPushButton("Edit")
        self.btn_edit_output.clicked.connect(lambda: self.edit_selected(self.out_list, self.outputs, is_output=True))
        self.btn_remove_output = QtWidgets.QPushButton("Remove")
        self.btn_remove_output.clicked.connect(lambda: self.remove_selected(self.out_list, self.outputs))
        self.out_btns_layout.addWidget(self.btn_edit_output)
        self.out_btns_layout.addWidget(self.btn_remove_output)

    def save(self) -> None:
        name = self.name_edit.text().strip()
        name_item_id = self._resolve_name_item_id()
        if name_item_id is None:
            return
        self.name_item_id = name_item_id
        if not self._validate_name_output(name_item_id):
            return

        method = (self.method_combo.currentText() or "Machine").strip().lower()
        if method == "crafting":
            method_db = "crafting"
            machine = None
            self.machine_item_id = None
            machine_item_id = None
            station_item_id = self.station_item_id
            if station_item_id is None:
                grid_size = (self.grid_combo.currentText() or "2x2").strip()
                if grid_size != "2x2":
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Missing crafting grid",
                        "Only the built-in 2x2 grid can be used without a Crafting Grid item.",
                    )
                    return
            else:
                grid_size = self._fetch_crafting_grid_size(station_item_id)
                if not grid_size:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Missing grid size",
                        "Selected crafting grid item does not have a grid size.",
                    )
                    return
                if self.grid_combo.currentText().strip() != grid_size:
                    self.grid_combo.setCurrentText(grid_size)
            if not self._validate_crafting_inputs(grid_size):
                return
        else:
            method_db = "machine"
            machine = self.machine_edit.text().strip() or None
            machine_item_id = None if machine is None else self.machine_item_id
            grid_size = None
            station_item_id = None
            for line in self.inputs:
                line["input_slot_index"] = None
        tier_raw = (self.tier_combo.currentText() or "").strip()
        tier = None if (tier_raw == "" or tier_raw == NONE_TIER_LABEL) else tier_raw
        notes = self.notes_edit.toPlainText().strip() or None
        if not self.additional_notes_check.isChecked():
            notes = None

        try:
            circuit = self._parse_int_opt(self.circuit_edit.text())
            duration_s = self._parse_float_opt(self.duration_edit.text())
            eut = self._parse_int_opt(self.eut_edit.text())
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid number", str(exc))
            return

        duration_ticks = None if duration_s is None else int(round(duration_s * TPS))

        if not self.inputs and not self.outputs:
            ok = QtWidgets.QMessageBox.question(self, "No lines?", "No inputs/outputs added. Save anyway?")
            if ok != QtWidgets.QMessageBox.StandardButton.Yes:
                return

        try:
            self.app.conn.execute("BEGIN")
            recipe_id = self._insert_recipe(
                name,
                method_db,
                machine,
                machine_item_id,
                grid_size,
                station_item_id,
                circuit,
                tier,
                duration_ticks,
                eut,
                notes,
            )
            self.app.recipe_focus_id = int(recipe_id)

            self._insert_recipe_lines(recipe_id)
            self._sync_output_duplicates(
                int(recipe_id),
                name_item_id,
                method_db,
                machine,
                machine_item_id,
                grid_size,
                station_item_id,
                circuit,
                tier,
                duration_ticks,
                eut,
                notes,
            )

            self.app.conn.commit()
        except Exception as exc:
            self.app.conn.rollback()
            QtWidgets.QMessageBox.critical(self, "Save failed", str(exc))
            return

        if hasattr(self.app, "refresh_items"):
            self.app.refresh_items()
        if hasattr(self.app, "refresh_recipes"):
            self.app.refresh_recipes()
        self.accept()


class EditRecipeDialog(_RecipeDialogBase):
    def __init__(self, app, recipe_id: int, parent=None):
        self.recipe_id = recipe_id
        self._variant_change_block = False
        super().__init__(app, "Edit Recipe", parent=parent)
        self._set_variant_visible(False)
        self.variant_combo.currentIndexChanged.connect(self._on_variant_change)
        self.tier_label.setVisible(False)
        self.tier_combo.setVisible(False)
        self.circuit_label.setVisible(False)
        self.circuit_edit.setVisible(False)
        self.duration_label.setVisible(False)
        self.duration_edit.setVisible(False)
        self.eut_label.setVisible(False)
        self.eut_edit.setVisible(False)
        self._load_recipe(recipe_id)

        self.btn_edit_input = QtWidgets.QPushButton("Edit")
        self.btn_edit_input.clicked.connect(lambda: self.edit_selected(self.in_list, self.inputs))
        self.btn_remove_input = QtWidgets.QPushButton("Remove")
        self.btn_remove_input.clicked.connect(lambda: self.remove_selected(self.in_list, self.inputs))
        self.in_btns_layout.addWidget(self.btn_edit_input)
        self.in_btns_layout.addWidget(self.btn_remove_input)

        self.btn_edit_output = QtWidgets.QPushButton("Edit")
        self.btn_edit_output.clicked.connect(lambda: self.edit_selected(self.out_list, self.outputs, is_output=True))
        self.btn_remove_output = QtWidgets.QPushButton("Remove")
        self.btn_remove_output.clicked.connect(lambda: self.remove_selected(self.out_list, self.outputs))
        self.out_btns_layout.addWidget(self.btn_edit_output)
        self.out_btns_layout.addWidget(self.btn_remove_output)

    def _load_recipe(self, recipe_id: int) -> None:
        r = self.app.conn.execute("SELECT * FROM recipes WHERE id=?", (recipe_id,)).fetchone()
        if not r:
            QtWidgets.QMessageBox.warning(self, "Not found", "Recipe not found.")
            self.reject()
            return

        self.recipe_id = recipe_id
        self.duplicate_of_recipe_id = r["duplicate_of_recipe_id"]
        self.name_edit.setText(r["name"])
        self.name_item_id = self._resolve_name_item_id(warn=False)
        initial_method = (r["method"] or "machine").strip().lower()
        self.method_combo.setCurrentText("Crafting" if initial_method == "crafting" else "Machine")
        self.machine_edit.setText(r["machine"] or "")
        self.machine_item_id = r["machine_item_id"]

        grid_values = [self.grid_combo.itemText(i) for i in range(self.grid_combo.count())]
        if r["grid_size"] and r["grid_size"] not in grid_values:
            self.grid_combo.addItem(r["grid_size"])
        if r["grid_size"]:
            self.grid_combo.setCurrentText(r["grid_size"])

        enabled_tiers = self.app.get_enabled_tiers() if hasattr(self.app, "get_enabled_tiers") else ALL_TIERS
        current_tier = (r["tier"] or "").strip()
        tiers = list(enabled_tiers)
        values = [NONE_TIER_LABEL]
        if current_tier and current_tier not in tiers:
            values.append(current_tier)
        values.extend(tiers)
        self.tier_combo.clear()
        self.tier_combo.addItems(values)
        self.tier_combo.setCurrentText(current_tier or NONE_TIER_LABEL)

        self.circuit_edit.setText("" if r["circuit"] is None else str(r["circuit"]))
        seconds = "" if r["duration_ticks"] is None else f"{(r['duration_ticks'] / TPS):g}"
        self.duration_edit.setText(seconds)
        self.eut_edit.setText("" if r["eu_per_tick"] is None else str(r["eu_per_tick"]))
        notes = (r["notes"] or "").strip()
        self.additional_notes_check.setChecked(bool(notes))
        self.notes_edit.setPlainText(notes)

        self.station_item_id = r["station_item_id"]
        self.station_edit.setText("")
        if self.station_item_id is not None:
            row = self.app.conn.execute(
                "SELECT COALESCE(display_name, key) AS name FROM items WHERE id=?",
                (self.station_item_id,),
            ).fetchone()
            if row:
                self.station_edit.setText(row["name"])
        self._apply_station_grid_size()

        self.inputs = []
        self.outputs = []
        self.in_list.clear()
        self.out_list.clear()
        self._load_lines(recipe_id)

        self._toggle_method_fields()
        self._refresh_variant_choices(r)

    def _refresh_variant_choices(self, recipe_row) -> None:
        canonical_id = recipe_row["duplicate_of_recipe_id"] or recipe_row["id"]
        rows = self.app.conn.execute(
            """
            SELECT r.id, r.name, r.method, r.machine, r.machine_item_id, r.grid_size, r.tier,
                   r.station_item_id, r.duplicate_of_recipe_id,
                   COALESCE(mi.display_name, mi.key) AS machine_item_name,
                   COALESCE(si.display_name, si.key) AS station_item_name
            FROM recipes r
            LEFT JOIN items mi ON mi.id = r.machine_item_id
            LEFT JOIN items si ON si.id = r.station_item_id
            WHERE r.id=? OR r.duplicate_of_recipe_id=?
            ORDER BY r.name, r.method, r.machine, r.tier, r.id
            """,
            (canonical_id, canonical_id),
        ).fetchall()
        base_name = (recipe_row["name"] or "").strip()

        self._variant_change_block = True
        try:
            self.variant_combo.clear()
            current_index = 0
            for idx, row in enumerate(rows):
                self.variant_combo.addItem(self._format_variant_label(row, base_name=base_name))
                self.variant_combo.setItemData(idx, row["id"])
                if row["id"] == self.recipe_id:
                    current_index = idx
            if rows:
                self.variant_combo.setCurrentIndex(current_index)
        finally:
            self._variant_change_block = False

    @staticmethod
    def _format_variant_label(row, *, base_name: str = "") -> str:
        name = (row["name"] or "").strip()
        tier = (row["tier"] or "").strip()
        tier_label = tier if tier else NONE_TIER_LABEL
        method = (row["method"] or "machine").strip().lower()
        name_prefix = ""
        if name and base_name and name != base_name:
            name_prefix = f"{name} • "
        if method == "crafting":
            grid = (row["grid_size"] or "").strip()
            grid_label = f" {grid}" if grid else ""
            return f"{name_prefix}Crafting{grid_label} • Tier: {tier_label}"
        machine_label = (row["machine"] or row["machine_item_name"] or "").strip() or "Machine"
        return f"{name_prefix}{machine_label} • Tier: {tier_label}"

    def _on_variant_change(self) -> None:
        if self._variant_change_block:
            return
        recipe_id = self.variant_combo.currentData()
        if recipe_id is None or recipe_id == self.recipe_id:
            return
        self._load_recipe(int(recipe_id))

    def _load_lines(self, recipe_id: int) -> None:
        ins = self.app.conn.execute(
            """
            SELECT rl.id, rl.item_id, COALESCE(i.display_name, i.key) AS name, i.kind,
                   rl.qty_count, rl.qty_liters, rl.chance_percent, rl.consumption_chance,
                   rl.output_slot_index, rl.input_slot_index
            FROM recipe_lines rl
            JOIN items i ON i.id = rl.item_id
            WHERE rl.recipe_id=? AND rl.direction='in'
            ORDER BY rl.id
            """,
            (recipe_id,),
        ).fetchall()

        outs = self.app.conn.execute(
            """
            SELECT rl.id, rl.item_id, COALESCE(i.display_name, i.key) AS name, i.kind,
                   rl.qty_count, rl.qty_liters, rl.chance_percent, rl.output_slot_index, rl.input_slot_index
            FROM recipe_lines rl
            JOIN items i ON i.id = rl.item_id
            WHERE rl.recipe_id=? AND rl.direction='out'
            ORDER BY rl.id
            """,
            (recipe_id,),
        ).fetchall()

        for row in ins:
            qty_count = self._coerce_whole_number(row["qty_count"])
            qty_liters = self._coerce_whole_number(row["qty_liters"])
            line = {
                "id": row["id"],
                "item_id": row["item_id"],
                "name": row["name"],
                "kind": row["kind"],
                "qty_count": qty_count,
                "qty_liters": qty_liters,
                "chance_percent": row["chance_percent"],
                "consumption_chance": row["consumption_chance"],
                "output_slot_index": row["output_slot_index"],
                "input_slot_index": row["input_slot_index"],
            }
            self.inputs.append(line)
            self.in_list.addItem(self._fmt_line(line))

        for row in outs:
            qty_count = self._coerce_whole_number(row["qty_count"])
            qty_liters = self._coerce_whole_number(row["qty_liters"])
            line = {
                "id": row["id"],
                "item_id": row["item_id"],
                "name": row["name"],
                "kind": row["kind"],
                "qty_count": qty_count,
                "qty_liters": qty_liters,
                "chance_percent": row["chance_percent"],
                "output_slot_index": row["output_slot_index"],
                "input_slot_index": row["input_slot_index"],
            }
            self.outputs.append(line)
            self.out_list.addItem(self._fmt_line(line, is_output=True))

    def save(self) -> None:
        name = self.name_edit.text().strip()
        name_item_id = self._resolve_name_item_id()
        if name_item_id is None:
            return
        self.name_item_id = name_item_id
        if not self._validate_name_output(name_item_id):
            return

        method = (self.method_combo.currentText() or "Machine").strip().lower()
        if method == "crafting":
            method_db = "crafting"
            machine = None
            self.machine_item_id = None
            machine_item_id = None
            station_item_id = self.station_item_id
            if station_item_id is None:
                grid_size = (self.grid_combo.currentText() or "2x2").strip()
                if grid_size != "2x2":
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Missing crafting grid",
                        "Only the built-in 2x2 grid can be used without a Crafting Grid item.",
                    )
                    return
            else:
                grid_size = self._fetch_crafting_grid_size(station_item_id)
                if not grid_size:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Missing grid size",
                        "Selected crafting grid item does not have a grid size.",
                    )
                    return
                if self.grid_combo.currentText().strip() != grid_size:
                    self.grid_combo.setCurrentText(grid_size)
            if not self._validate_crafting_inputs(grid_size):
                return
        else:
            method_db = "machine"
            machine = self.machine_edit.text().strip() or None
            machine_item_id = None if machine is None else self.machine_item_id
            grid_size = None
            station_item_id = None
            for line in self.inputs:
                line["input_slot_index"] = None
        tier_raw = (self.tier_combo.currentText() or "").strip()
        tier = None if (tier_raw == "" or tier_raw == NONE_TIER_LABEL) else tier_raw
        notes = self.notes_edit.toPlainText().strip() or None
        if not self.additional_notes_check.isChecked():
            notes = None

        try:
            circuit = self._parse_int_opt(self.circuit_edit.text())
            duration_s = self._parse_float_opt(self.duration_edit.text())
            eut = self._parse_int_opt(self.eut_edit.text())
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid number", str(exc))
            return

        duration_ticks = None if duration_s is None else int(round(duration_s * TPS))

        if not self.inputs and not self.outputs:
            ok = QtWidgets.QMessageBox.question(self, "No lines?", "No inputs/outputs added. Save anyway?")
            if ok != QtWidgets.QMessageBox.StandardButton.Yes:
                return

        try:
            self.app.conn.execute("BEGIN")
            
            # Update recipe
            self.app.conn.execute(
                """UPDATE recipes SET 
                   name=?, method=?, machine=?, machine_item_id=?, grid_size=?, station_item_id=?, 
                   circuit=?, tier=?, duration_ticks=?, eu_per_tick=?, notes=?
                   WHERE id=?""",
                (name, method_db, machine, machine_item_id, grid_size, station_item_id, 
                 circuit, tier, duration_ticks, eut, notes, self.recipe_id),
            )
            
            # Delete old lines
            self.app.conn.execute("DELETE FROM recipe_lines WHERE recipe_id=?", (self.recipe_id,))

            # Re-insert lines
            self._insert_recipe_lines(self.recipe_id)
            if self.duplicate_of_recipe_id is None:
                self._sync_output_duplicates(
                    self.recipe_id,
                    name_item_id,
                    method_db,
                    machine,
                    machine_item_id,
                    grid_size,
                    station_item_id,
                    circuit,
                    tier,
                    duration_ticks,
                    eut,
                    notes,
                )

            self.app.conn.commit()
        except Exception as exc:
            self.app.conn.rollback()
            QtWidgets.QMessageBox.critical(self, "Save failed", str(exc))
            return

        if hasattr(self.app, "refresh_items"):
            self.app.refresh_items()
        if hasattr(self.app, "refresh_recipes"):
            self.app.refresh_recipes()
        self.accept()


class MachineMetadataEditorDialog(QtWidgets.QDialog):
    _slot_defaults = {
        "input_slots": 1,
        "output_slots": 1,
        "storage_slots": 0,
        "power_slots": 0,
        "circuit_slots": 0,
        "input_tanks": 0,
        "input_tank_capacity_l": 0,
        "output_tanks": 0,
        "output_tank_capacity_l": 0,
    }

    def __init__(
        self,
        app,
        parent=None,
        *,
        initial_machine_type: str | None = None,
        initial_tiers: list[str] | None = None,
    ):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("Edit Machine Metadata")
        self.setModal(True)
        self.resize(960, 520)

        self._metadata: dict[tuple[str, str], dict[str, object]] = {}
        self._current_key: tuple[str, str] | None = None
        self._loading = False
        self._initial_machine_type = (initial_machine_type or "").strip()
        self._initial_tiers = [
            (tier or "").strip() for tier in (initial_tiers or []) if (tier or "").strip()
        ]

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(
            QtWidgets.QLabel(
                "Define machine tiers and per-tier slot/tank capabilities."
            )
        )

        header = QtWidgets.QHBoxLayout()
        header.addWidget(QtWidgets.QLabel("Machine Type"))
        self.machine_type_combo = QtWidgets.QComboBox()
        self.machine_type_combo.setEditable(True)
        self.machine_type_combo.currentTextChanged.connect(self._on_machine_type_changed)
        header.addWidget(self.machine_type_combo, stretch=1)
        self.remove_machine_btn = QtWidgets.QPushButton("Remove Type")
        self.remove_machine_btn.clicked.connect(self._remove_machine_type)
        header.addWidget(self.remove_machine_btn)
        layout.addLayout(header)

        body = QtWidgets.QHBoxLayout()
        layout.addLayout(body, stretch=1)

        left = QtWidgets.QVBoxLayout()
        body.addLayout(left, stretch=0)

        left.addWidget(QtWidgets.QLabel("Tiers"))
        self.tier_list = QtWidgets.QListWidget()
        self.tier_list.currentRowChanged.connect(self._on_tier_selected)
        left.addWidget(self.tier_list, stretch=1)

        tier_controls = QtWidgets.QHBoxLayout()
        self.tier_combo = QtWidgets.QComboBox()
        self.tier_combo.setEditable(True)
        self.tier_combo.addItems(self._get_tier_list())
        tier_controls.addWidget(self.tier_combo, stretch=1)
        self.add_tier_btn = QtWidgets.QPushButton("Add Tier")
        self.add_tier_btn.clicked.connect(self._add_tier)
        tier_controls.addWidget(self.add_tier_btn)
        self.remove_tier_btn = QtWidgets.QPushButton("Remove Tier")
        self.remove_tier_btn.clicked.connect(self._remove_selected_tier)
        tier_controls.addWidget(self.remove_tier_btn)
        left.addLayout(tier_controls)

        self.manage_tiers_btn = QtWidgets.QPushButton("Manage Tiers…")
        self.manage_tiers_btn.clicked.connect(self._open_tier_manager)
        left.addWidget(self.manage_tiers_btn)

        right = QtWidgets.QVBoxLayout()
        body.addLayout(right, stretch=1)

        right.addWidget(QtWidgets.QLabel("Metadata"))
        self.form = QtWidgets.QGridLayout()
        right.addLayout(self.form)

        name_row = self.form.rowCount()
        self.machine_name_label = QtWidgets.QLabel("Machine Name")
        self.machine_name_edit = QtWidgets.QLineEdit()
        self.machine_name_edit.setPlaceholderText("e.g. Basic Cutting Machine")
        self.machine_name_edit.textChanged.connect(lambda _=None: self._on_value_changed("machine_name"))
        self.form.addWidget(self.machine_name_label, name_row, 0)
        self.form.addWidget(self.machine_name_edit, name_row, 1)

        self.slot_widgets: dict[str, tuple[QtWidgets.QCheckBox, QtWidgets.QSpinBox]] = {}
        self._required_slot_keys: set[str] = set()
        self.capacity_widgets: dict[str, QtWidgets.QSpinBox] = {}
        self.capacity_labels: dict[str, QtWidgets.QLabel] = {}

        self._add_slot_row("input_slots", "Input Slots", 1, 64, required=True)
        self._add_slot_row("output_slots", "Output Slots", 1, 64, required=True)
        self._add_slot_row("storage_slots", "Storage Slots", 0, 64)
        self._add_slot_row("power_slots", "Power Slots", 0, 16)
        self._add_slot_row("circuit_slots", "Circuit Slots", 0, 16)
        self._add_slot_row("input_tanks", "Input Tanks", 0, 32, with_capacity="input_tank_capacity_l")
        self._add_slot_row("output_tanks", "Output Tanks", 0, 32, with_capacity="output_tank_capacity_l")

        right.addStretch(1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_metadata()
        self._apply_initial_selection()

    def _apply_initial_selection(self) -> None:
        machine_type = self._initial_machine_type
        if not machine_type:
            return
        requested_tiers = self._sorted_tiers(list(dict.fromkeys(self._initial_tiers)))
        for tier in requested_tiers:
            key = (machine_type, tier)
            if key not in self._metadata:
                self._metadata[key] = {"machine_name": f"{tier} {machine_type}", **dict(self._slot_defaults)}
        self._refresh_machine_types()
        if requested_tiers:
            self._select_tier(machine_type, requested_tiers[0])
        else:
            self.machine_type_combo.setCurrentText(machine_type)

    def _get_tier_list(self) -> list[str]:
        if hasattr(self.app, "get_all_tiers"):
            return list(self.app.get_all_tiers())
        return list(ALL_TIERS)

    def _load_metadata(self) -> None:
        self._metadata = {}
        rows = fetch_machine_metadata(self.app.conn, tiers=self._get_tier_list())
        for row in rows:
            machine_type = (row["machine_type"] or "").strip()
            tier = (row["tier"] or "").strip()
            if not machine_type or not tier:
                continue
            self._metadata[(machine_type, tier)] = {
                "machine_name": (row["machine_name"] or "").strip(),
                "input_slots": int(row["input_slots"] or 1),
                "output_slots": int(row["output_slots"] or 1),
                "storage_slots": int(row["storage_slots"] or 0),
                "power_slots": int(row["power_slots"] or 0),
                "circuit_slots": int(row["circuit_slots"] or 0),
                "input_tanks": int(row["input_tanks"] or 0),
                "input_tank_capacity_l": int(row["input_tank_capacity_l"] or 0),
                "output_tanks": int(row["output_tanks"] or 0),
                "output_tank_capacity_l": int(row["output_tank_capacity_l"] or 0),
            }
        self._refresh_machine_types()

    def _refresh_machine_types(self) -> None:
        machine_types = sorted({machine for machine, _ in self._metadata.keys()}, key=str.casefold)
        current = self.machine_type_combo.currentText().strip()
        self.machine_type_combo.blockSignals(True)
        self.machine_type_combo.clear()
        self.machine_type_combo.addItems([""] + machine_types)
        if current:
            self.machine_type_combo.setCurrentText(current)
        self.machine_type_combo.blockSignals(False)
        self._on_machine_type_changed(self.machine_type_combo.currentText())

    def _sorted_tiers(self, tiers: list[str]) -> list[str]:
        tier_list = self._get_tier_list()
        order = {tier: idx for idx, tier in enumerate(tier_list)}
        extras = sorted([tier for tier in tiers if tier not in order])
        ordered = sorted([tier for tier in tiers if tier in order], key=lambda t: order[t])
        return ordered + extras

    def _on_machine_type_changed(self, machine_type: str) -> None:
        self._update_current_metadata()
        machine_type = (machine_type or "").strip()
        tiers = [tier for (m_type, tier) in self._metadata.keys() if m_type == machine_type]
        self._loading = True
        self.tier_list.clear()
        for tier in self._sorted_tiers(tiers):
            self.tier_list.addItem(tier)
        self._loading = False
        if self.tier_list.count() > 0:
            self.tier_list.setCurrentRow(0)
        else:
            self._current_key = None
            self._set_form_enabled(False)

    def _on_tier_selected(self, row: int) -> None:
        if self._loading:
            return
        self._update_current_metadata()
        machine_type = (self.machine_type_combo.currentText() or "").strip()
        tier = self.tier_list.item(row).text() if 0 <= row < self.tier_list.count() else ""
        if not machine_type or not tier:
            self._current_key = None
            self._set_form_enabled(False)
            return
        self._current_key = (machine_type, tier)
        self._load_form_values(self._metadata.get(self._current_key, {}))

    def _set_form_enabled(self, enabled: bool) -> None:
        self.machine_name_edit.setEnabled(enabled)
        for key, (checkbox, spin) in self.slot_widgets.items():
            checkbox.setEnabled(enabled and key not in self._required_slot_keys)
            spin.setEnabled(enabled)
        for spin in self.capacity_widgets.values():
            spin.setEnabled(enabled)
        for label in self.capacity_labels.values():
            label.setEnabled(enabled)

    def _add_slot_row(
        self,
        key: str,
        label: str,
        minimum: int,
        maximum: int,
        *,
        required: bool = False,
        with_capacity: str | None = None,
    ) -> None:
        row = self.form.rowCount()
        checkbox = QtWidgets.QCheckBox(label)
        spin = QtWidgets.QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(self._slot_defaults.get(key, 0))
        self.form.addWidget(checkbox, row, 0)
        self.form.addWidget(spin, row, 1)
        self.slot_widgets[key] = (checkbox, spin)
        spin.valueChanged.connect(lambda _=0, k=key: self._on_value_changed(k))
        checkbox.toggled.connect(lambda checked, k=key: self._on_slot_toggled(k, checked))
        if required:
            checkbox.setChecked(True)
            checkbox.setEnabled(False)
            self._required_slot_keys.add(key)

        if with_capacity:
            cap_row = self.form.rowCount()
            cap_label = QtWidgets.QLabel("Capacity (L)")
            cap_spin = QtWidgets.QSpinBox()
            cap_spin.setRange(0, 10**9)
            cap_spin.setValue(self._slot_defaults.get(with_capacity, 0))
            cap_spin.valueChanged.connect(lambda _=0, k=with_capacity: self._on_value_changed(k))
            self.form.addWidget(cap_label, cap_row, 0)
            self.form.addWidget(cap_spin, cap_row, 1)
            self.capacity_labels[with_capacity] = cap_label
            self.capacity_widgets[with_capacity] = cap_spin

    def _on_slot_toggled(self, key: str, checked: bool) -> None:
        if self._loading:
            return
        slot = self.slot_widgets.get(key)
        if slot is None:
            return
        checkbox, spin = slot
        if checked and spin.value() == 0:
            spin.setValue(max(1, spin.minimum()))
        spin.setVisible(checked)
        if key == "input_tanks":
            self._toggle_capacity("input_tank_capacity_l", checked)
        elif key == "output_tanks":
            self._toggle_capacity("output_tank_capacity_l", checked)
        self._on_value_changed(key)

    def _toggle_capacity(self, key: str, visible: bool) -> None:
        label = self.capacity_labels.get(key)
        spin = self.capacity_widgets.get(key)
        if label:
            label.setVisible(visible)
        if spin:
            spin.setVisible(visible)

    def _on_value_changed(self, _key: str) -> None:
        if self._loading:
            return
        self._update_current_metadata()

    def _load_form_values(self, values: dict[str, object]) -> None:
        self._loading = True
        self.machine_name_edit.setText((values.get("machine_name") or "").strip())
        for key, (checkbox, spin) in self.slot_widgets.items():
            value = int(values.get(key, self._slot_defaults.get(key, 0)))
            checkbox.setChecked(value > 0)
            spin.setVisible(value > 0)
            spin.setValue(max(spin.minimum(), value))
        for key, spin in self.capacity_widgets.items():
            value = int(values.get(key, self._slot_defaults.get(key, 0)))
            spin.setValue(max(spin.minimum(), value))
        self._loading = False

        input_checked = self.slot_widgets["input_tanks"][0].isChecked()
        output_checked = self.slot_widgets["output_tanks"][0].isChecked()
        self._toggle_capacity("input_tank_capacity_l", input_checked)
        self._toggle_capacity("output_tank_capacity_l", output_checked)
        self._set_form_enabled(True)

    def _update_current_metadata(self) -> None:
        if self._current_key is None:
            return
        values: dict[str, object] = {
            "machine_name": (self.machine_name_edit.text() or "").strip()
        }
        for key, (checkbox, spin) in self.slot_widgets.items():
            if checkbox.isEnabled() and not checkbox.isChecked():
                values[key] = 0
            else:
                values[key] = int(spin.value())
        for key, spin in self.capacity_widgets.items():
            tank_key = "input_tanks" if "input" in key else "output_tanks"
            tank_checkbox = self.slot_widgets[tank_key][0]
            values[key] = int(spin.value()) if tank_checkbox.isChecked() else 0
        self._metadata[self._current_key] = values

    def _add_tier(self) -> None:
        machine_type = (self.machine_type_combo.currentText() or "").strip()
        if not machine_type:
            QtWidgets.QMessageBox.warning(self, "Missing machine type", "Enter a machine type first.")
            return
        tier = (self.tier_combo.currentText() or "").strip()
        if not tier:
            QtWidgets.QMessageBox.warning(self, "Missing tier", "Select a tier to add.")
            return
        key = (machine_type, tier)
        if key in self._metadata:
            QtWidgets.QMessageBox.information(self, "Tier exists", f"{machine_type} already has tier '{tier}'.")
            return
        self._metadata[key] = {"machine_name": f"{tier} {machine_type}", **dict(self._slot_defaults)}
        self._refresh_machine_types()
        self._select_tier(machine_type, tier)

    def _select_tier(self, machine_type: str, tier: str) -> None:
        self.machine_type_combo.setCurrentText(machine_type)
        for idx in range(self.tier_list.count()):
            if self.tier_list.item(idx).text() == tier:
                self.tier_list.setCurrentRow(idx)
                return

    def _remove_selected_tier(self) -> None:
        if self._current_key is None:
            return
        machine_type, tier = self._current_key
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Remove tier?",
            f"Remove tier '{tier}' from {machine_type}?",
        )
        if confirm != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self._metadata.pop(self._current_key, None)
        self._current_key = None
        self._refresh_machine_types()

    def _remove_machine_type(self) -> None:
        machine_type = (self.machine_type_combo.currentText() or "").strip()
        if not machine_type:
            return
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Remove machine type?",
            f"Remove all tiers for '{machine_type}'?",
        )
        if confirm != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        for key in list(self._metadata.keys()):
            if key[0] == machine_type:
                self._metadata.pop(key, None)
        self._current_key = None
        self._refresh_machine_types()

    def _open_tier_manager(self) -> None:
        if not hasattr(self.app, "editor_enabled") or not self.app.editor_enabled:
            QtWidgets.QMessageBox.information(
                self,
                "Editor locked",
                "Editing tiers is only available in editor mode.",
            )
            return
        dlg = TierManagerDialog(self.app, parent=self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.tier_combo.clear()
            self.tier_combo.addItems(self._get_tier_list())

    def _validate_rows(self) -> list[tuple] | None:
        rows: list[tuple] = []
        for (machine_type, tier), values in sorted(self._metadata.items()):
            if not machine_type or not tier:
                continue
            machine_name = (values.get("machine_name") or "").strip()
            if not machine_name:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Missing machine name",
                    f"Enter a machine name for {machine_type} ({tier}).",
                )
                return None
            input_slots = max(1, int(values.get("input_slots", 1)))
            output_slots = max(1, int(values.get("output_slots", 1)))
            rows.append(
                (
                    machine_type,
                    tier,
                    machine_name,
                    input_slots,
                    output_slots,
                    0,
                    int(values.get("storage_slots", 0)),
                    int(values.get("power_slots", 0)),
                    int(values.get("circuit_slots", 0)),
                    int(values.get("input_tanks", 0)),
                    int(values.get("input_tank_capacity_l", 0)),
                    int(values.get("output_tanks", 0)),
                    int(values.get("output_tank_capacity_l", 0)),
                )
            )
        return rows

    def _save(self) -> None:
        self._update_current_metadata()
        rows = self._validate_rows()
        if rows is None:
            return
        try:
            replace_machine_metadata(self.app.conn, rows)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Save failed", str(exc))
            return

        if hasattr(self.app, "refresh_items"):
            self.app.refresh_items()
        if hasattr(self.app, "refresh_recipes"):
            self.app.refresh_recipes()
        if hasattr(self.app, "_machines_load_from_db"):
            self.app._machines_load_from_db()
        self.accept()


class MaterialManagerDialog(QtWidgets.QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("Manage Materials")
        self.setModal(True)
        self.resize(640, 420)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Define materials to associate with items."))

        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Name", "Attributes"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, stretch=1)

        controls = QtWidgets.QHBoxLayout()
        self.add_row_btn = QtWidgets.QPushButton("Add Row")
        self.add_row_btn.clicked.connect(self._add_row)
        self.remove_row_btn = QtWidgets.QPushButton("Remove Selected")
        self.remove_row_btn.clicked.connect(self._remove_selected_rows)
        controls.addWidget(self.add_row_btn)
        controls.addWidget(self.remove_row_btn)
        controls.addStretch(1)
        layout.addLayout(controls)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._existing_ids: set[int] = set()
        self._load_rows()

    def _load_rows(self) -> None:
        self.table.setRowCount(0)
        rows = fetch_materials(self.app.conn)
        self._existing_ids = {int(row["id"]) for row in rows}
        for row in rows:
            self._add_row(row)
        if self.table.rowCount() == 0:
            self._add_row()

    def _add_row(self, row=None) -> None:
        focus_new_row = isinstance(row, bool)
        if focus_new_row:
            row = None
        row_idx = self.table.rowCount()
        self.table.insertRow(row_idx)

        name_item = QtWidgets.QTableWidgetItem((row["name"] or "").strip() if row else "")
        if row:
            name_item.setData(QtCore.Qt.ItemDataRole.UserRole, int(row["id"]))
        self.table.setItem(row_idx, 0, name_item)

        attributes_item = QtWidgets.QTableWidgetItem((row["attributes"] or "").strip() if row else "")
        self.table.setItem(row_idx, 1, attributes_item)

        if focus_new_row:
            self.table.setCurrentCell(row_idx, 0)
            self.table.editItem(name_item)

    def _remove_selected_rows(self) -> None:
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()}, reverse=True)
        for row_idx in rows:
            self.table.removeRow(row_idx)

    def _validate_rows(self) -> list[dict] | None:
        rows: list[dict] = []
        seen: set[str] = set()
        for row_idx in range(self.table.rowCount()):
            name_item = self.table.item(row_idx, 0)
            name = (name_item.text() if name_item else "").strip()
            if not name:
                QtWidgets.QMessageBox.warning(self, "Missing name", f"Row {row_idx + 1} needs a material name.")
                return None
            canon = name.casefold()
            if canon in seen:
                QtWidgets.QMessageBox.warning(self, "Duplicate name", f"Material '{name}' is listed twice.")
                return None
            seen.add(canon)
            attributes_item = self.table.item(row_idx, 1)
            attributes = (attributes_item.text() if attributes_item else "").strip() or None
            material_id = None
            if name_item is not None:
                material_id = name_item.data(QtCore.Qt.ItemDataRole.UserRole)
            rows.append({"id": material_id, "name": name, "attributes": attributes})
        return rows

    def _save(self) -> None:
        rows = self._validate_rows()
        if rows is None:
            return

        current_ids = {int(r["id"]) for r in rows if r["id"] is not None}
        removed_ids = self._existing_ids - current_ids
        try:
            for material_id in removed_ids:
                delete_material(self.app.conn, int(material_id))
            for row in rows:
                if row["id"] is None:
                    add_material(self.app.conn, row["name"], row["attributes"])
                else:
                    update_material(self.app.conn, int(row["id"]), row["name"], row["attributes"])
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Save failed", str(exc))
            return

        if hasattr(self.app, "refresh_items"):
            self.app.refresh_items()
        self.accept()


class TierManagerDialog(QtWidgets.QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("Manage Tiers")
        self.setModal(True)
        self.resize(520, 420)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Define the tier list used across dropdowns and filters."))

        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Tier Name", "Sort Order"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, stretch=1)

        controls = QtWidgets.QHBoxLayout()
        self.add_row_btn = QtWidgets.QPushButton("Add Row")
        self.add_row_btn.clicked.connect(self._add_row)
        self.remove_row_btn = QtWidgets.QPushButton("Remove Selected")
        self.remove_row_btn.clicked.connect(self._remove_selected_rows)
        controls.addWidget(self.add_row_btn)
        controls.addWidget(self.remove_row_btn)
        controls.addStretch(1)
        layout.addLayout(controls)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_rows()

    def _load_rows(self) -> None:
        self.table.setRowCount(0)
        tiers = self.app.get_all_tiers() if hasattr(self.app, "get_all_tiers") else list(ALL_TIERS)
        for idx, tier in enumerate(tiers):
            self._add_row({"name": tier, "order": idx + 1})
        if self.table.rowCount() == 0:
            self._add_row()

    def _add_row(self, row=None) -> None:
        if isinstance(row, bool):
            row = None
        row_idx = self.table.rowCount()
        self.table.insertRow(row_idx)

        name_item = QtWidgets.QTableWidgetItem((row["name"] or "").strip() if row else "")
        self.table.setItem(row_idx, 0, name_item)

        order_val = str(row["order"]) if row and row.get("order") else str(row_idx + 1)
        order_item = QtWidgets.QTableWidgetItem(order_val)
        self.table.setItem(row_idx, 1, order_item)

    def _remove_selected_rows(self) -> None:
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()}, reverse=True)
        for row_idx in rows:
            self.table.removeRow(row_idx)

    def _validate_rows(self) -> list[str] | None:
        rows: list[tuple[int, str]] = []
        seen: set[str] = set()
        for row_idx in range(self.table.rowCount()):
            name_item = self.table.item(row_idx, 0)
            name = (name_item.text() if name_item else "").strip()
            if not name:
                QtWidgets.QMessageBox.warning(self, "Missing name", f"Row {row_idx + 1} needs a tier name.")
                return None
            canon = name.casefold()
            if canon in seen:
                QtWidgets.QMessageBox.warning(self, "Duplicate name", f"Tier '{name}' is listed twice.")
                return None
            seen.add(canon)

            order_item = self.table.item(row_idx, 1)
            order_text = (order_item.text() if order_item else "").strip()
            try:
                order = int(order_text or row_idx + 1)
            except ValueError:
                QtWidgets.QMessageBox.warning(self, "Invalid order", f"Row {row_idx + 1} has an invalid sort order.")
                return None
            rows.append((order, name))
        if not rows:
            QtWidgets.QMessageBox.warning(self, "Missing tiers", "Define at least one tier.")
            return None
        rows.sort(key=lambda item: item[0])
        return [name for _, name in rows]

    def _save(self) -> None:
        tiers = self._validate_rows()
        if tiers is None:
            return
        if hasattr(self.app, "set_all_tiers"):
            self.app.set_all_tiers(tiers)
        enabled = [tier for tier in self.app.get_enabled_tiers() if tier in tiers]
        if not enabled:
            enabled = [tiers[0]]
        self.app.set_enabled_tiers(enabled)
        self.app.set_crafting_6x6_unlocked(self.app.is_crafting_6x6_unlocked())

        if hasattr(self.app, "_tiers_load_from_db"):
            self.app._tiers_load_from_db()
        if hasattr(self.app, "refresh_recipes"):
            self.app.refresh_recipes()
        if hasattr(self.app, "_machines_load_from_db"):
            self.app._machines_load_from_db()
        if hasattr(self.app, "status_bar"):
            self.app.status_bar.showMessage("Updated tier list.")
        self.accept()


class CraftingGridManagerDialog(QtWidgets.QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("Manage Crafting Grids")
        self.setModal(True)
        self.resize(420, 320)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Define the crafting grid sizes available in recipes and items."))

        self.table = QtWidgets.QTableWidget(0, 1)
        self.table.setHorizontalHeaderLabels(["Grid Size (e.g. 3x3)"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, stretch=1)

        controls = QtWidgets.QHBoxLayout()
        self.add_row_btn = QtWidgets.QPushButton("Add Row")
        self.add_row_btn.clicked.connect(self._add_row)
        self.remove_row_btn = QtWidgets.QPushButton("Remove Selected")
        self.remove_row_btn.clicked.connect(self._remove_selected_rows)
        controls.addWidget(self.add_row_btn)
        controls.addWidget(self.remove_row_btn)
        controls.addStretch(1)
        layout.addLayout(controls)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_rows()

    def _load_rows(self) -> None:
        self.table.setRowCount(0)
        grids = self.app.get_crafting_grids() if hasattr(self.app, "get_crafting_grids") else ["2x2", "3x3"]
        for grid in grids:
            self._add_row({"size": grid})
        if self.table.rowCount() == 0:
            self._add_row()

    def _add_row(self, row=None) -> None:
        if isinstance(row, bool):
            row = None
        row_idx = self.table.rowCount()
        self.table.insertRow(row_idx)
        size_item = QtWidgets.QTableWidgetItem((row["size"] or "").strip() if row else "")
        self.table.setItem(row_idx, 0, size_item)

    def _remove_selected_rows(self) -> None:
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()}, reverse=True)
        for row_idx in rows:
            self.table.removeRow(row_idx)

    @staticmethod
    def _parse_grid_size(value: str) -> tuple[int, int] | None:
        raw = (value or "").strip().lower().replace("×", "x")
        if "x" not in raw:
            return None
        parts = [p.strip() for p in raw.split("x", 1)]
        if len(parts) != 2:
            return None
        if not parts[0].isdigit() or not parts[1].isdigit():
            return None
        rows = int(parts[0])
        cols = int(parts[1])
        if rows <= 0 or cols <= 0:
            return None
        return rows, cols

    def _validate_rows(self) -> list[str] | None:
        grids: list[str] = []
        seen: set[str] = set()
        for row_idx in range(self.table.rowCount()):
            size_item = self.table.item(row_idx, 0)
            size = (size_item.text() if size_item else "").strip()
            if not size:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Missing grid size",
                    f"Row {row_idx + 1} needs a grid size.",
                )
                return None
            if not self._parse_grid_size(size):
                QtWidgets.QMessageBox.warning(
                    self,
                    "Invalid grid size",
                    f"Row {row_idx + 1} must be in NxM format (e.g. 3x3).",
                )
                return None
            canon = size.lower()
            if canon in seen:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Duplicate grid size",
                    f"Grid size '{size}' is listed twice.",
                )
                return None
            seen.add(canon)
            grids.append(size)
        if not grids:
            QtWidgets.QMessageBox.warning(self, "Missing grids", "Define at least one crafting grid size.")
            return None
        return grids

    def _save(self) -> None:
        grids = self._validate_rows()
        if grids is None:
            return
        if hasattr(self.app, "set_crafting_grids"):
            self.app.set_crafting_grids(grids)
        if hasattr(self.app, "status_bar"):
            self.app.status_bar.showMessage("Updated crafting grids.")
        self.accept()


class ItemKindManagerDialog(QtWidgets.QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("Manage Item Kinds")
        self.setModal(True)
        self.resize(640, 420)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Define item kinds for item classification and grouping."))

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Sort Order", "Applies To", "Built-in"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, stretch=1)

        controls = QtWidgets.QHBoxLayout()
        self.add_row_btn = QtWidgets.QPushButton("Add Row")
        self.add_row_btn.clicked.connect(self._add_row)
        self.remove_row_btn = QtWidgets.QPushButton("Remove Selected")
        self.remove_row_btn.clicked.connect(self._remove_selected_rows)
        controls.addWidget(self.add_row_btn)
        controls.addWidget(self.remove_row_btn)
        controls.addStretch(1)
        layout.addLayout(controls)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._existing_ids: set[int] = set()
        self._load_rows()

    def _load_rows(self) -> None:
        self.table.setRowCount(0)
        rows = self.app.conn.execute(
            "SELECT id, name, sort_order, is_builtin, applies_to "
            "FROM item_kinds ORDER BY sort_order ASC, name COLLATE NOCASE ASC"
        ).fetchall()
        self._existing_ids = {int(row["id"]) for row in rows}
        for row in rows:
            self._add_row(row)
        if self.table.rowCount() == 0:
            self._add_row()

    def _add_row(self, row=None) -> None:
        if isinstance(row, bool):
            row = None
        row_idx = self.table.rowCount()
        self.table.insertRow(row_idx)

        name_item = QtWidgets.QTableWidgetItem((row["name"] or "").strip() if row else "")
        if row:
            name_item.setData(QtCore.Qt.ItemDataRole.UserRole, int(row["id"]))
        self.table.setItem(row_idx, 0, name_item)

        sort_item = QtWidgets.QTableWidgetItem(str(row["sort_order"]) if row else "0")
        self.table.setItem(row_idx, 1, sort_item)

        applies_combo = QtWidgets.QComboBox()
        applies_combo.addItems(["Item", "Fluid"])
        applies_to = (row["applies_to"] or "item").strip().lower() if row else "item"
        applies_combo.setCurrentText("Fluid" if applies_to == "fluid" else "Item")
        self.table.setCellWidget(row_idx, 2, applies_combo)

        builtin_item = QtWidgets.QTableWidgetItem("Yes" if row and row["is_builtin"] else "No")
        builtin_item.setFlags(builtin_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
        if row and row["is_builtin"]:
            builtin_item.setData(QtCore.Qt.ItemDataRole.UserRole, True)
        self.table.setItem(row_idx, 3, builtin_item)

    def _remove_selected_rows(self) -> None:
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()}, reverse=True)
        for row_idx in rows:
            builtin_item = self.table.item(row_idx, 3)
            if builtin_item and builtin_item.data(QtCore.Qt.ItemDataRole.UserRole):
                QtWidgets.QMessageBox.warning(
                    self, "Cannot remove built-in", "Built-in kinds cannot be removed."
                )
                continue
            self.table.removeRow(row_idx)

    def _validate_rows(self) -> list[dict] | None:
        rows: list[dict] = []
        seen: set[str] = set()
        for row_idx in range(self.table.rowCount()):
            name_item = self.table.item(row_idx, 0)
            name = (name_item.text() if name_item else "").strip()
            if not name:
                QtWidgets.QMessageBox.warning(self, "Missing name", f"Row {row_idx + 1} needs a kind name.")
                return None
            canon = name.casefold()
            if canon in seen:
                QtWidgets.QMessageBox.warning(self, "Duplicate name", f"Kind '{name}' is listed twice.")
                return None
            seen.add(canon)
            sort_item = self.table.item(row_idx, 1)
            sort_raw = (sort_item.text() if sort_item else "").strip()
            try:
                sort_order = int(sort_raw) if sort_raw != "" else 0
            except ValueError:
                QtWidgets.QMessageBox.warning(self, "Invalid sort order", f"Row {row_idx + 1} needs a number.")
                return None
            applies_combo = self.table.cellWidget(row_idx, 2)
            applies_to = "item"
            if isinstance(applies_combo, QtWidgets.QComboBox):
                applies_to_raw = (applies_combo.currentText() or "").strip().lower()
                applies_to = "fluid" if applies_to_raw == "fluid" else "item"
            kind_id = None
            if name_item is not None:
                kind_id = name_item.data(QtCore.Qt.ItemDataRole.UserRole)
            rows.append({"id": kind_id, "name": name, "sort_order": sort_order, "applies_to": applies_to})
        return rows

    def _save(self) -> None:
        rows = self._validate_rows()
        if rows is None:
            return

        current_ids = {int(r["id"]) for r in rows if r["id"] is not None}
        removed_ids = self._existing_ids - current_ids
        try:
            for kind_id in removed_ids:
                row = self.app.conn.execute(
                    "SELECT is_builtin FROM item_kinds WHERE id=?",
                    (int(kind_id),),
                ).fetchone()
                if row and int(row["is_builtin"] or 0) == 1:
                    continue
                self.app.conn.execute("UPDATE items SET item_kind_id=NULL WHERE item_kind_id=?", (int(kind_id),))
                self.app.conn.execute("DELETE FROM item_kinds WHERE id=?", (int(kind_id),))
            for row in rows:
                if row["id"] is None:
                    self.app.conn.execute(
                        "INSERT INTO item_kinds(name, sort_order, is_builtin, applies_to) VALUES(?, ?, 0, ?)",
                        (row["name"], row["sort_order"], row["applies_to"]),
                    )
                else:
                    self.app.conn.execute(
                        "UPDATE item_kinds SET name=?, sort_order=?, applies_to=? WHERE id=?",
                        (row["name"], row["sort_order"], row["applies_to"], int(row["id"])),
                    )
            self.app.conn.commit()
        except Exception as exc:
            self.app.conn.rollback()
            QtWidgets.QMessageBox.critical(self, "Save failed", str(exc))
            return

        if hasattr(self.app, "refresh_items"):
            self.app.refresh_items()
        self.accept()
