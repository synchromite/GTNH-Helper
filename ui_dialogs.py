#!/usr/bin/env python3
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from services.db import ALL_TIERS
from services.machines import fetch_machine_metadata, replace_machine_metadata
from services.materials import add_material, delete_material, fetch_materials, update_material


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


class ItemPickerDialog(QtWidgets.QDialog):
    """Searchable tree picker for Items.

    Returns: self.result = {"id": int, "name": str, "kind": "item"|"fluid"}
    """

    def __init__(self, app, title: str = "Pick Item", machines_only: bool = False, kinds: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.app = app
        self.machines_only = machines_only
        self.kinds = kinds
        self._base_kinds = set(kinds) if kinds else {"item", "fluid", "gas", "machine"}
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
        if self.machines_only:
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
            added_any = False
            for row in self._items:
                if not _matches(row):
                    continue
                child = QtWidgets.QTreeWidgetItem(p_machines, [self._label_for(row)])
                self._display_map[child] = row
                added_any = True
            if not added_any:
                QtWidgets.QTreeWidgetItem(p_machines, ["(no matches)"])
            self._select_first_child(p_machines)
            return

        active_kinds = self._active_kinds()
        show_items = "item" in active_kinds
        show_fluids = "fluid" in active_kinds
        show_gases = "gas" in active_kinds
        show_machines = "machine" in active_kinds

        p_items = QtWidgets.QTreeWidgetItem(self.tree, ["Items"]) if show_items else None
        p_fluids = QtWidgets.QTreeWidgetItem(self.tree, ["Fluids"]) if show_fluids else None
        p_gases = QtWidgets.QTreeWidgetItem(self.tree, ["Gases"]) if show_gases else None
        p_machines = QtWidgets.QTreeWidgetItem(self.tree, ["Machines"]) if show_machines else None

        if p_items: p_items.setExpanded(True)
        if p_fluids: p_fluids.setExpanded(True)
        if p_gases: p_gases.setExpanded(True)
        if p_machines: p_machines.setExpanded(True)

        added_any = {"item": False, "fluid": False, "gas": False, "machine": False}
        item_kind_nodes: dict[str, QtWidgets.QTreeWidgetItem] = {}

        for row in self._items:
            if not _matches(row):
                continue

            parent = None
            # Helper to get/create generic kind group nodes
            def _get_kind_parent(p_root, default_label):
                if p_root is None: return None
                try:
                    k_name = (row["item_kind_name"] or "").strip()
                except Exception:
                    k_name = ""
                k_name = k_name if k_name else default_label
                if k_name not in item_kind_nodes:
                    item_kind_nodes[k_name] = QtWidgets.QTreeWidgetItem(p_root, [k_name])
                    item_kind_nodes[k_name].setExpanded(bool(query))
                return item_kind_nodes[k_name]

            if row["kind"] == "item":
                parent = _get_kind_parent(p_items, "(no type)")
            elif row["kind"] == "fluid":
                parent = _get_kind_parent(p_fluids, "(fluid)")
            elif row["kind"] == "gas":
                parent = _get_kind_parent(p_gases, "(gas)")
            elif row["kind"] == "machine":
                parent = _get_kind_parent(p_machines, "(machine)")
            
            if parent is None:
                continue

            child = QtWidgets.QTreeWidgetItem(parent, [self._label_for(row)])
            self._display_map[child] = row
            added_any[row["kind"]] = True

        if p_items and not added_any["item"]: QtWidgets.QTreeWidgetItem(p_items, ["(no matches)"])
        if p_fluids and not added_any["fluid"]: QtWidgets.QTreeWidgetItem(p_fluids, ["(no matches)"])
        if p_gases and not added_any["gas"]: QtWidgets.QTreeWidgetItem(p_gases, ["(no matches)"])
        if p_machines and not added_any["machine"]: QtWidgets.QTreeWidgetItem(p_machines, ["(no matches)"])

        for p in [p_items, p_fluids, p_gases, p_machines]:
            if p is not None:
                for k_parent in self._children(p):
                    if self._select_first_child(k_parent):
                        return
                self._select_first_child(p)

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
        
        # Safe access to new columns if they exist in _row, else None
        self.content_fluid_id_val = _row_get(row, "content_fluid_id")
        self.content_qty_val = _row_get(row, "content_qty_liters")

        self._all_item_kinds: list[dict] = []
        self._kind_usage: dict[int, set[str]] = {}
        self._kind_name_to_id: dict[str, int] = {}
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
        kind_values = allowed_kinds or ["item", "fluid", "gas", "machine"]
        self.kind_combo.addItems(kind_values)
        form.addWidget(self.kind_combo, 1, 1)

        self.item_kind_label = QtWidgets.QLabel("Item Type")
        form.addWidget(self.item_kind_label, 2, 0)
        self.item_kind_combo = QtWidgets.QComboBox()
        form.addWidget(self.item_kind_combo, 2, 1)

        # Has Material Checkbox (Row 3)
        self.has_material_check = QtWidgets.QCheckBox("Has Material?")
        form.addWidget(self.has_material_check, 3, 1)

        # Row 4: Material OR Machine Type
        self.material_label = QtWidgets.QLabel("Material")
        self.material_combo = QtWidgets.QComboBox()
        form.addWidget(self.material_label, 4, 0)
        form.addWidget(self.material_combo, 4, 1)

        self.machine_type_label = QtWidgets.QLabel("Machine Type")
        self.machine_type_combo = QtWidgets.QComboBox()
        self.machine_type_combo.setEditable(True)
        form.addWidget(self.machine_type_label, 4, 0)
        form.addWidget(self.machine_type_combo, 4, 1)
        self.machine_type_label.hide()
        self.machine_type_combo.hide()

        self.tier_label = QtWidgets.QLabel("Tier")
        self.tier_combo = QtWidgets.QComboBox()
        self.tier_combo.addItems([NONE_TIER_LABEL] + list(ALL_TIERS))
        form.addWidget(self.tier_label, 5, 0)
        form.addWidget(self.tier_combo, 5, 1)
        self.tier_label.hide()
        self.tier_combo.hide()
        
        # Row 6: Fluid Container options
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
        form.addWidget(self.container_group, 6, 0, 1, 2)

        self.is_base_check = QtWidgets.QCheckBox("Base resource (planner stops here later)")
        form.addWidget(self.is_base_check, 7, 1)

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
            form.addWidget(self.availability_group, 8, 0, 1, 2)

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

        self.kind_combo.currentTextChanged.connect(self._on_high_level_kind_changed)
        self.item_kind_combo.currentTextChanged.connect(self._on_item_kind_selected)
        self.material_combo.currentTextChanged.connect(self._on_material_selected)
        self.machine_type_combo.currentTextChanged.connect(self._on_machine_type_selected)
        self.has_material_check.toggled.connect(self._on_has_material_toggled)
        self.is_container_check.toggled.connect(self._on_is_container_toggled)
        self.content_fluid_combo.currentTextChanged.connect(self._on_content_fluid_selected)

        self._load_row_defaults()
        self._on_high_level_kind_changed()
        self._on_item_kind_selected()

    def _load_row_defaults(self) -> None:
        if not self._row:
            self.display_name_edit.setText("")
            if self._default_kind:
                self.kind_combo.setCurrentText(self._default_kind)
            else:
                self.kind_combo.setCurrentText(self.kind_combo.itemText(0))
            self.item_kind_combo.setCurrentText(NONE_KIND_LABEL)
            self.material_combo.setCurrentText(NONE_MATERIAL_LABEL)
            self.is_base_check.setChecked(False)
            self.has_material_check.setChecked(False)
            self.is_container_check.setChecked(False)
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
        self.kind_combo.setCurrentText(self._row["kind"])
        item_kind_name = (self._row["item_kind_name"] or "") or NONE_KIND_LABEL
        self.item_kind_combo.setCurrentText(item_kind_name)

        if (item_kind_name.strip().lower() == "machine") or bool(self._row["is_machine"]):
            # Prefer machine_type, fallback to display_name for legacy/migration
            m_type = _row_get(self._row, "machine_type")
            if not m_type:
                 m_type = self._row["display_name"]
            self.machine_type_combo.setCurrentText(m_type or "")
            self.tier_combo.setCurrentText(self._row["machine_tier"] or NONE_TIER_LABEL)

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
            "SELECT id, name FROM item_kinds ORDER BY sort_order ASC, name COLLATE NOCASE ASC"
        ).fetchall()
        self._all_item_kinds = rows
        self._kind_name_to_id = {r["name"]: r["id"] for r in rows}
        self.machine_kind_id = next((r["id"] for r in rows if (r["name"] or "").strip().lower() == "machine"), None)

        # 2. Fetch usages to filter types (e.g. items vs fluids vs gases)
        usage_rows = self.app.conn.execute(
            "SELECT DISTINCT item_kind_id, kind FROM items WHERE item_kind_id IS NOT NULL"
        ).fetchall()
        self._kind_usage = {}
        for r in usage_rows:
            kid = r["item_kind_id"]
            if kid not in self._kind_usage:
                self._kind_usage[kid] = set()
            self._kind_usage[kid].add(r["kind"])

        self._update_item_kind_combo()

    def _update_item_kind_combo(self) -> None:
        current_kind_super = (self.kind_combo.currentText() or "").strip().lower()
        if not current_kind_super:
            current_kind_super = "item"

        # Determine which names to show
        filtered_names = [NONE_KIND_LABEL]
        
        for r in self._all_item_kinds:
            kid = r["id"]
            usages = self._kind_usage.get(kid, set())
            
            # Show if:
            # 1. It is used by the current high-level kind (e.g. 'gas')
            # We strictly filter out unused kinds so they don't leak into other categories.
            # (New kinds are handled in _on_item_kind_selected)
            if current_kind_super in usages:
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

    def _reload_machine_types(self) -> None:
        rows = fetch_machine_metadata(self.app.conn)
        types = sorted({(row["machine_type"] or "").strip() for row in rows if row["machine_type"]})
        self.machine_type_combo.blockSignals(True)
        self.machine_type_combo.clear()
        self.machine_type_combo.addItems([""] + types)
        self.machine_type_combo.blockSignals(False)

    def _ensure_item_kind(self, name: str) -> str | None:
        name = (name or "").strip()
        if not name:
            return None
        row = self.app.conn.execute(
            "SELECT name FROM item_kinds WHERE LOWER(name)=LOWER(?)",
            (name,),
        ).fetchone()
        if row:
            return row["name"]
        self.app.conn.execute(
            "INSERT INTO item_kinds(name, sort_order, is_builtin) VALUES(?, 500, 0)",
            (name,),
        )
        self.app.conn.commit()
        return name

    def _on_item_kind_selected(self) -> None:
        v = (self.item_kind_combo.currentText() or "").strip()
        kind_high = (self.kind_combo.currentText() or "").strip().lower()

        # "Machine" is now a top-level Kind
        is_machine_kind = kind_high == "machine"
        is_fluid_like = kind_high in ("fluid", "gas")

        self.item_kind_label.setVisible(not is_machine_kind)
        self.item_kind_combo.setVisible(not is_machine_kind)

        # Machine-specific fields depend on KIND, not Item Type
        self.machine_type_label.setVisible(is_machine_kind)
        self.machine_type_combo.setVisible(is_machine_kind)
        self.tier_label.setVisible(is_machine_kind)
        self.tier_combo.setVisible(is_machine_kind)
        self.is_base_check.setVisible(not is_machine_kind)
        if is_machine_kind:
            self.is_base_check.setChecked(False)

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
        if is_machine_kind or is_fluid_like:
            self.has_material_check.setVisible(False)
            self.material_label.setVisible(False)
            self.material_combo.setVisible(False)
            self.material_id = None

            self.container_group.setVisible(False)
            self.is_container_check.setChecked(False)
            self._on_is_container_toggled()
        else:
            self.has_material_check.setVisible(True)
            self._on_has_material_toggled()

            self.container_group.setVisible(True)
            self._on_is_container_toggled()

        canonical = None
        if v == ADD_NEW_KIND_LABEL:
            new_name, ok = QtWidgets.QInputDialog.getText(self, "Add Item Kind", "New kind name:")
            if not ok or not new_name.strip():
                self.item_kind_combo.setCurrentText(NONE_KIND_LABEL)
                self.item_kind_id = None
                return
            canonical = self._ensure_item_kind(new_name)

        if v == ADD_NEW_KIND_LABEL:
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
        else:
            self.item_kind_id = self._kind_name_to_id.get(v2) if v2 and v2 != NONE_KIND_LABEL else None

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
        if (self.kind_combo.currentText() or "").strip().lower() == "machine":
            self.item_kind_combo.setEnabled(False)
        else:
            self.item_kind_combo.setEnabled(True)

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
        allowed_set = set(allowed_kinds or ["item", "fluid", "gas", "machine"])
        super().__init__(
            app,
            title,
            parent=parent,
            allowed_kinds=allowed_kinds,
            default_kind=default_kind,
            show_availability="machine" in allowed_set,
        )

    def save(self) -> None:
        display_name = (self.display_name_edit.text() or "").strip()
        if not display_name:
            QtWidgets.QMessageBox.warning(self, "Missing name", "Display Name is required.")
            return

        key = self._slugify(display_name)

        kind = (self.kind_combo.currentText() or "").strip().lower()
        if kind not in ("item", "fluid", "gas", "machine"):
            QtWidgets.QMessageBox.warning(self, "Invalid kind", "Kind must be item, fluid, gas, or machine.")
            return

        is_base = 1 if self.is_base_check.isChecked() else 0

        # "Machine" is now a top-level Kind
        is_machine = 1 if kind == "machine" else 0
        item_kind_id = self.item_kind_id

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

        cur = self.app.conn.execute("SELECT 1 FROM items WHERE key=?", (key,)).fetchone()
        if cur:
            base = key
            n = 2
            while self.app.conn.execute("SELECT 1 FROM items WHERE key=?", (f"{base}_{n}",)).fetchone():
                n += 1
            key = f"{base}_{n}"

        try:
            cur = self.app.conn.execute(
                "INSERT INTO items(key, display_name, kind, is_base, is_machine, item_kind_id, material_id, "
                "machine_type, machine_tier, content_fluid_id, content_qty_liters) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
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
                    content_fluid_id,
                    content_qty,
                ),
            )
            item_id = cur.lastrowid

            self.app.conn.commit()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self,
                "Save failed",
                f"Could not add item.\n\nDetails: {exc}",
            )
            return

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
        self.accept()


class EditItemDialog(_ItemDialogBase):
    def __init__(self, app, item_id: int, parent=None):
        row = app.conn.execute(
            "SELECT i.id, i.key, COALESCE(i.display_name, i.key) AS name, i.display_name, i.kind, "
            "       i.is_base, i.is_machine, i.machine_type, i.machine_tier, "
            "       i.content_fluid_id, i.content_qty_liters, "
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

        kind = (self.kind_combo.currentText() or "").strip().lower()
        if kind not in ("item", "fluid", "gas", "machine"):
            QtWidgets.QMessageBox.warning(self, "Invalid kind", "Kind must be item, fluid, gas, or machine.")
            return

        is_base = 1 if self.is_base_check.isChecked() else 0

        # "Machine" is now a top-level Kind
        is_machine = 1 if kind == "machine" else 0
        item_kind_id = self.item_kind_id

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
                "machine_type=?, machine_tier=?, content_fluid_id=?, content_qty_liters=? "
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
                    content_fluid_id,
                    content_qty,
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
        self.accept()

class ItemLineDialog(QtWidgets.QDialog):
    def __init__(
        self,
        app,
        title: str,
        *,
        show_chance: bool = False,
        show_consumption: bool = False,
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
        grid_values = ["4x4"]
        if hasattr(self.app, "is_crafting_6x6_unlocked") and self.app.is_crafting_6x6_unlocked():
            grid_values.append("6x6")
        self.grid_combo.addItems(grid_values)
        grid_frame = QtWidgets.QWidget()
        grid_layout = QtWidgets.QHBoxLayout(grid_frame)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.addWidget(self.grid_combo)

        self.method_field_stack = QtWidgets.QStackedWidget()
        self.method_field_stack.addWidget(machine_frame)
        self.method_field_stack.addWidget(grid_frame)
        form.addWidget(self.method_field_stack, 2, 1)

        form.addWidget(QtWidgets.QLabel("Tier"), 2, 2)
        self.tier_combo = QtWidgets.QComboBox()
        form.addWidget(self.tier_combo, 2, 3)

        form.addWidget(QtWidgets.QLabel("Circuit"), 3, 0)
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

        form.addWidget(QtWidgets.QLabel("Duration (seconds)"), 4, 0)
        self.duration_edit = QtWidgets.QLineEdit()
        self.duration_edit.setValidator(QtGui.QDoubleValidator(0.0, 10**9, 3))
        form.addWidget(self.duration_edit, 4, 1)

        form.addWidget(QtWidgets.QLabel("EU/t"), 4, 2)
        self.eut_edit = QtWidgets.QLineEdit()
        self.eut_edit.setValidator(QtGui.QIntValidator(0, 10**9))
        form.addWidget(self.eut_edit, 4, 3)

        form.addWidget(QtWidgets.QLabel("Notes"), 5, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        self.notes_edit = QtWidgets.QTextEdit()
        form.addWidget(self.notes_edit, 5, 1, 1, 3)

        lists_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(lists_layout, stretch=1)

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
        self._toggle_method_fields()

    def _set_variant_visible(self, visible: bool) -> None:
        self.variant_label.setVisible(visible)
        self.variant_combo.setVisible(visible)

    def _toggle_method_fields(self) -> None:
        method = (self.method_combo.currentText() or "Machine").strip().lower()
        is_crafting = method == "crafting"

        self.method_label_stack.setCurrentIndex(1 if is_crafting else 0)
        self.method_field_stack.setCurrentIndex(1 if is_crafting else 0)

        self.station_label.setVisible(is_crafting)
        self.station_frame.setVisible(is_crafting)

    def pick_machine(self) -> None:
        d = ItemPickerDialog(self.app, title="Pick Machine", machines_only=True, parent=self)
        if d.exec() == QtWidgets.QDialog.DialogCode.Accepted and d.result:
            self.machine_item_id = d.result["id"]
            self.machine_edit.setText(d.result["name"])

    def clear_machine(self) -> None:
        self.machine_item_id = None
        self.machine_edit.setText("")

    def pick_station(self) -> None:
        d = ItemPickerDialog(self.app, title="Pick Station", kinds=["item"], parent=self)
        if d.exec() == QtWidgets.QDialog.DialogCode.Accepted and d.result:
            self.station_item_id = d.result["id"]
            self.station_edit.setText(d.result["name"])

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

    def save(self) -> None:
        raise NotImplementedError

    # --- Shared List Management Methods (Moved from EditRecipeDialog) ---

    def add_input(self) -> None:
        d = ItemLineDialog(self.app, "Add Input", parent=self, show_consumption=True)
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
            dialog_kwargs = {"show_consumption": True}
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
        
        # Connect shared buttons from base class
        self.btn_add_input.clicked.connect(self.add_input)
        self.btn_add_output.clicked.connect(self.add_output)
        
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
            grid_size = (self.grid_combo.currentText() or "4x4").strip()
            station_item_id = self.station_item_id
        else:
            method_db = "machine"
            machine = self.machine_edit.text().strip() or None
            machine_item_id = None if machine is None else self.machine_item_id
            grid_size = None
            station_item_id = None
        tier_raw = (self.tier_combo.currentText() or "").strip()
        tier = None if (tier_raw == "" or tier_raw == NONE_TIER_LABEL) else tier_raw
        notes = self.notes_edit.toPlainText().strip() or None

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
            cur = self.app.conn.execute(
                """INSERT INTO recipes(name, method, machine, machine_item_id, grid_size, station_item_id, circuit, tier, duration_ticks, eu_per_tick, notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (name, method_db, machine, machine_item_id, grid_size, station_item_id, circuit, tier, duration_ticks, eut, notes),
            )
            recipe_id = cur.lastrowid
            self.app.recipe_focus_id = int(recipe_id)

            for line in self.inputs:
                if line["kind"] in ("fluid", "gas"):
                    self.app.conn.execute(
                        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_liters, chance_percent, consumption_chance, output_slot_index) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (
                            recipe_id,
                            "in",
                            line["item_id"],
                            line["qty_liters"],
                            None,
                            line.get("consumption_chance", 1.0),
                            None,
                        ),
                    )
                else:
                    self.app.conn.execute(
                        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_count, chance_percent, consumption_chance, output_slot_index) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (
                            recipe_id,
                            "in",
                            line["item_id"],
                            line["qty_count"],
                            None,
                            line.get("consumption_chance", 1.0),
                            None,
                        ),
                    )

            for line in self.outputs:
                if line["kind"] in ("fluid", "gas"):
                    self.app.conn.execute(
                        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_liters, chance_percent, output_slot_index) "
                        "VALUES(?,?,?,?,?,?)",
                        (
                            recipe_id,
                            "out",
                            line["item_id"],
                            line["qty_liters"],
                            line.get("chance_percent", 100.0),
                            line.get("output_slot_index"),
                        ),
                    )
                else:
                    self.app.conn.execute(
                        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_count, chance_percent, output_slot_index) "
                        "VALUES(?,?,?,?,?,?)",
                        (
                            recipe_id,
                            "out",
                            line["item_id"],
                            line["qty_count"],
                            line.get("chance_percent", 100.0),
                            line.get("output_slot_index"),
                        ),
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
        self._set_variant_visible(True)
        self.variant_combo.currentIndexChanged.connect(self._on_variant_change)
        self._load_recipe(recipe_id)

        # Connect shared buttons
        self.btn_add_input.clicked.connect(self.add_input)
        self.btn_add_output.clicked.connect(self.add_output)

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
        self.notes_edit.setPlainText(r["notes"] or "")

        self.station_item_id = r["station_item_id"]
        self.station_edit.setText("")
        if self.station_item_id is not None:
            row = self.app.conn.execute(
                "SELECT COALESCE(display_name, key) AS name FROM items WHERE id=?",
                (self.station_item_id,),
            ).fetchone()
            if row:
                self.station_edit.setText(row["name"])

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
                   rl.qty_count, rl.qty_liters, rl.chance_percent, rl.consumption_chance, rl.output_slot_index
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
                   rl.qty_count, rl.qty_liters, rl.chance_percent, rl.output_slot_index
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
            grid_size = (self.grid_combo.currentText() or "4x4").strip()
            station_item_id = self.station_item_id
        else:
            method_db = "machine"
            machine = self.machine_edit.text().strip() or None
            machine_item_id = None if machine is None else self.machine_item_id
            grid_size = None
            station_item_id = None
        tier_raw = (self.tier_combo.currentText() or "").strip()
        tier = None if (tier_raw == "" or tier_raw == NONE_TIER_LABEL) else tier_raw
        notes = self.notes_edit.toPlainText().strip() or None

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
            for line in self.inputs:
                if line["kind"] in ("fluid", "gas"):
                    self.app.conn.execute(
                        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_liters, chance_percent, consumption_chance, output_slot_index) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (
                            self.recipe_id,
                            "in",
                            line["item_id"],
                            line["qty_liters"],
                            None,
                            line.get("consumption_chance", 1.0),
                            None,
                        ),
                    )
                else:
                    self.app.conn.execute(
                        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_count, chance_percent, consumption_chance, output_slot_index) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (
                            self.recipe_id,
                            "in",
                            line["item_id"],
                            line["qty_count"],
                            None,
                            line.get("consumption_chance", 1.0),
                            None,
                        ),
                    )

            for line in self.outputs:
                if line["kind"] in ("fluid", "gas"):
                    self.app.conn.execute(
                        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_liters, chance_percent, output_slot_index) "
                        "VALUES(?,?,?,?,?,?)",
                        (
                            self.recipe_id,
                            "out",
                            line["item_id"],
                            line["qty_liters"],
                            line.get("chance_percent", 100.0),
                            line.get("output_slot_index"),
                        ),
                    )
                else:
                    self.app.conn.execute(
                        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_count, chance_percent, output_slot_index) "
                        "VALUES(?,?,?,?,?,?)",
                        (
                            self.recipe_id,
                            "out",
                            line["item_id"],
                            line["qty_count"],
                            line.get("chance_percent", 100.0),
                            line.get("output_slot_index"),
                        ),
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
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("Edit Machine Metadata")
        self.setModal(True)
        self.resize(980, 520)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(
            QtWidgets.QLabel(
                "Define per-tier machine slot capabilities. Byproduct slots must be less than output slots."
            )
        )

        self.table = QtWidgets.QTableWidget(0, 12)
        self.table.setHorizontalHeaderLabels(
            [
                "Machine Type",
                "Tier",
                "Input Slots",
                "Output Slots",
                "Byproduct Slots",
                "Storage Slots",
                "Power Slots",
                "Circuit Slots",
                "Input Tanks",
                "Input Tank Cap (L)",
                "Output Tanks",
                "Output Tank Cap (L)",
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Interactive)
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
        for row in fetch_machine_metadata(self.app.conn):
            self._add_row(row)
        if self.table.rowCount() == 0:
            self._add_row()

    def _make_spin(self, minimum: int, maximum: int, value: int) -> QtWidgets.QSpinBox:
        spin = QtWidgets.QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin

    def _add_row(self, row=None) -> None:
        if isinstance(row, bool):
            row = None
        def _as_int(value, default=0):
            try:
                return int(value)
            except Exception:
                return default

        row_idx = self.table.rowCount()
        self.table.insertRow(row_idx)

        machine_edit = QtWidgets.QLineEdit()
        if row is not None:
            machine_edit.setText((row["machine_type"] or "").strip())
        self.table.setCellWidget(row_idx, 0, machine_edit)

        tier_combo = QtWidgets.QComboBox()
        tier_combo.setEditable(True)
        tier_combo.addItems(ALL_TIERS)
        if row is not None:
            tier_val = (row["tier"] or "").strip()
            if tier_val:
                if tier_val not in ALL_TIERS:
                    tier_combo.addItem(tier_val)
                tier_combo.setCurrentText(tier_val)
        self.table.setCellWidget(row_idx, 1, tier_combo)

        input_slots = _as_int(row["input_slots"], default=1) if row is not None else 1
        output_slots = _as_int(row["output_slots"], default=1) if row is not None else 1
        byproduct_slots = _as_int(row["byproduct_slots"]) if row is not None else 0
        storage_slots = _as_int(row["storage_slots"]) if row is not None else 0
        power_slots = _as_int(row["power_slots"]) if row is not None else 0
        circuit_slots = _as_int(row["circuit_slots"]) if row is not None else 0
        input_tanks = _as_int(row["input_tanks"]) if row is not None else 0
        input_tank_cap = _as_int(row["input_tank_capacity_l"]) if row is not None else 0
        output_tanks = _as_int(row["output_tanks"]) if row is not None else 0
        output_tank_cap = _as_int(row["output_tank_capacity_l"]) if row is not None else 0

        self.table.setCellWidget(row_idx, 2, self._make_spin(1, 64, max(1, input_slots)))
        self.table.setCellWidget(row_idx, 3, self._make_spin(1, 64, max(1, output_slots)))
        self.table.setCellWidget(row_idx, 4, self._make_spin(0, 64, max(0, byproduct_slots)))
        self.table.setCellWidget(row_idx, 5, self._make_spin(0, 64, max(0, storage_slots)))
        self.table.setCellWidget(row_idx, 6, self._make_spin(0, 16, max(0, power_slots)))
        self.table.setCellWidget(row_idx, 7, self._make_spin(0, 16, max(0, circuit_slots)))
        self.table.setCellWidget(row_idx, 8, self._make_spin(0, 32, max(0, input_tanks)))
        self.table.setCellWidget(row_idx, 9, self._make_spin(0, 10**9, max(0, input_tank_cap)))
        self.table.setCellWidget(row_idx, 10, self._make_spin(0, 32, max(0, output_tanks)))
        self.table.setCellWidget(row_idx, 11, self._make_spin(0, 10**9, max(0, output_tank_cap)))

    def _remove_selected_rows(self) -> None:
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()}, reverse=True)
        for row_idx in rows:
            self.table.removeRow(row_idx)

    def _validate_rows(self) -> list[tuple] | None:
        rows: list[tuple] = []
        seen: set[tuple[str, str]] = set()
        for row_idx in range(self.table.rowCount()):
            machine_edit = self.table.cellWidget(row_idx, 0)
            tier_combo = self.table.cellWidget(row_idx, 1)
            if machine_edit is None or tier_combo is None:
                continue
            machine_type = (machine_edit.text() or "").strip()
            tier = (tier_combo.currentText() or "").strip()
            if not machine_type:
                QtWidgets.QMessageBox.warning(self, "Missing machine type", f"Row {row_idx + 1} needs a machine type.")
                return None
            if not tier:
                QtWidgets.QMessageBox.warning(self, "Missing tier", f"Row {row_idx + 1} needs a tier.")
                return None
            key = (machine_type.lower(), tier)
            if key in seen:
                QtWidgets.QMessageBox.warning(
                    self, "Duplicate row", f"Row {row_idx + 1} duplicates machine/tier '{machine_type} / {tier}'."
                )
                return None
            seen.add(key)

            def _spin_value(col: int) -> int:
                widget = self.table.cellWidget(row_idx, col)
                return int(widget.value()) if isinstance(widget, QtWidgets.QSpinBox) else 0

            input_slots = _spin_value(2)
            output_slots = _spin_value(3)
            byproduct_slots = _spin_value(4)
            storage_slots = _spin_value(5)
            power_slots = _spin_value(6)
            circuit_slots = _spin_value(7)
            input_tanks = _spin_value(8)
            input_tank_cap = _spin_value(9)
            output_tanks = _spin_value(10)
            output_tank_cap = _spin_value(11)

            if input_slots < 1 or output_slots < 1:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Invalid slots",
                    f"Row {row_idx + 1} requires at least 1 input and 1 output slot.",
                )
                return None
            if byproduct_slots > max(output_slots - 1, 0):
                QtWidgets.QMessageBox.warning(
                    self,
                    "Invalid byproducts",
                    f"Row {row_idx + 1} has {byproduct_slots} byproduct slots but only {output_slots} output slots.",
                )
                return None

            rows.append(
                (
                    machine_type,
                    tier,
                    input_slots,
                    output_slots,
                    byproduct_slots,
                    storage_slots,
                    power_slots,
                    circuit_slots,
                    input_tanks,
                    input_tank_cap,
                    output_tanks,
                    output_tank_cap,
                )
            )
        return rows

    def _save(self) -> None:
        rows = self._validate_rows()
        if rows is None:
            return
        try:
            replace_machine_metadata(self.app.conn, rows)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Save failed", str(exc))
            return
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
        if isinstance(row, bool):
            row = None
        row_idx = self.table.rowCount()
        self.table.insertRow(row_idx)

        name_item = QtWidgets.QTableWidgetItem((row["name"] or "").strip() if row else "")
        if row:
            name_item.setData(QtCore.Qt.ItemDataRole.UserRole, int(row["id"]))
        self.table.setItem(row_idx, 0, name_item)

        attributes_item = QtWidgets.QTableWidgetItem((row["attributes"] or "").strip() if row else "")
        self.table.setItem(row_idx, 1, attributes_item)

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
