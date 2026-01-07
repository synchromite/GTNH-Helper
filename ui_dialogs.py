#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from services.db import ALL_TIERS


def _row_get(row, key: str, default=None):
    """Safe key access for sqlite3.Row/dicts."""
    try:
        if row is None:
            return default
        if hasattr(row, "keys") and key in row.keys():
            return row[key]
        if hasattr(row, "get"):
            return row.get(key, default)
        # last resort
        return row[key]
    except Exception:
        return default


TPS = 20  # Minecraft target ticks per second

def _safe_grab(win, tries=20):
    """Make dialog modal safely; some WMs need the window to be viewable first."""
    try:
        win.update_idletasks()
        win.wait_visibility()        # wait until mapped (viewable)
        win.grab_set()
        win.focus_force()
        return
    except tk.TclError:
        if tries <= 0:
            return
        win.after(50, lambda: _safe_grab(win, tries - 1))

# User-facing label for "no tier" (stored as NULL in DB)
NONE_TIER_LABEL = "— none —"

# Separate label for Item Kind "none" (stored as NULL)
NONE_KIND_LABEL = "— none —"

ADD_NEW_KIND_LABEL = "+ Add new…"


class ItemPickerDialog(tk.Toplevel):
    """Searchable tree picker for Items.

    Returns: self.result = {"id": int, "name": str, "kind": "item"|"fluid"}
    """

    def __init__(self, app, title: str = "Pick Item", machines_only: bool = False, kinds: list[str] | None = None):
        super().__init__(app)
        self.app = app
        self.machines_only = machines_only
        # Optional kind filter: ["item"], ["fluid"], or ["item","fluid"].
        self.kinds = kinds
        self.title(title)
        self.geometry("520x520")
        self.transient(app)
        self.after(0, lambda: _safe_grab(self))

        self.result = None
        self._items = []  # list[sqlite3.Row]-like
        self._display_map = {}  # tree iid -> item row

        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        # Search
        top = ttk.Frame(frm)
        top.pack(fill="x")

        ttk.Label(top, text="Search").pack(side="left")
        self.search_var = tk.StringVar()
        ent = ttk.Entry(top, textvariable=self.search_var)
        ent.pack(side="left", fill="x", expand=True, padx=(8, 0))
        ent.bind("<Return>", lambda _e: self.on_ok())

        # Tree
        self.tree = ttk.Treeview(frm, show="tree")
        self.tree.pack(fill="both", expand=True, pady=(10, 0))
        self.tree.bind("<Double-1>", lambda _e: self.on_ok())

        # Buttons
        bottom = ttk.Frame(frm)
        bottom.pack(fill="x", pady=(10, 0))
        ttk.Button(bottom, text="New Item…", command=self.new_item).pack(side="left")
        ttk.Button(bottom, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="OK", command=self.on_ok).pack(side="right", padx=8)

        # Live updates
        self.search_var.trace_add("write", lambda *_: self.rebuild_tree())

        self.reload_items()
        self.rebuild_tree()
        ent.focus_set()

    def reload_items(self):
        # Keep key internal; user should not see it by default.
        if self.machines_only:
            enabled = self.app.get_enabled_tiers() if hasattr(self.app, "get_enabled_tiers") else ALL_TIERS
            placeholders = ",".join(["?"] * len(enabled))
            # Machines are now identified primarily by Item Kind = 'Machine'.
            # For backward compatibility, we also include legacy is_machine=1 items.
            sql = (
                "SELECT i.id, i.key, COALESCE(i.display_name, i.key) AS name, i.kind, "
                "       i.machine_tier, i.is_machine, k.name AS item_kind_name "
                "FROM items i "
                "LEFT JOIN item_kinds k ON k.id = i.item_kind_id "
                "WHERE i.kind='item' AND (LOWER(COALESCE(k.name,''))=LOWER('Machine') OR i.is_machine=1) "
                f"AND (i.machine_tier IS NULL OR TRIM(i.machine_tier)='' OR i.machine_tier IN ({placeholders})) "
                "ORDER BY name"
            )
            self._items = self.app.conn.execute(sql, tuple(enabled)).fetchall()
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
        """User-facing label for a row.

        If there are duplicate names (within the same kind), append an id suffix
        to avoid confusion.
        """
        name = row["name"]
        kind = row["kind"]
        # detect duplicates of (kind, name)
        dup = 0
        for r in self._items:
            if r["kind"] == kind and r["name"] == name:
                dup += 1
                if dup > 1:
                    break
        if dup > 1:
            return f"{name}  (#{row['id']})"
        return name

    def rebuild_tree(self):
        for child in self.tree.get_children(""):
            self.tree.delete(child)
        self._display_map.clear()

        q = (self.search_var.get() or "").strip().lower()

        # Parents
        if self.machines_only:
            p_machines = self.tree.insert("", "end", text="Machines", open=True)
            p_items = p_fluids = None
        else:
            show_items = True
            show_fluids = True
            if self.kinds:
                show_items = "item" in self.kinds
                show_fluids = "fluid" in self.kinds
            p_items = self.tree.insert("", "end", text="Items", open=True) if show_items else None
            p_fluids = self.tree.insert("", "end", text="Fluids", open=True) if show_fluids else None

        def _matches(row) -> bool:
            if not q:
                return True
            return q in (row["name"] or "").lower()

        added_any = {"item": False, "fluid": False, "machine": False}

        item_kind_nodes: dict[str, str] = {}
        if not self.machines_only and p_items is not None:
            # Lazily create kind-group nodes under Items.
            # We create them only when there is at least one matching item.
            item_kind_nodes = {}

        for row in self._items:
            if not _matches(row):
                continue
            if self.machines_only:
                parent = p_machines
            else:
                if row["kind"] == "item":
                    try:
                        kind_name = (row["item_kind_name"] or "").strip()
                    except Exception:
                        kind_name = ""
                    kind_name = kind_name if kind_name else "(no kind)" 
                    if kind_name not in item_kind_nodes:
                        item_kind_nodes[kind_name] = self.tree.insert(p_items, "end", text=kind_name, open=bool(q))
                    parent = item_kind_nodes[kind_name]
                else:
                    parent = p_fluids
            iid = self.tree.insert(parent, "end", text=self._label_for(row))
            self._display_map[iid] = row
            if self.machines_only:
                added_any["machine"] = True
            else:
                added_any[row["kind"]] = True

        # If a branch has no children, keep it collapsed and show a hint.
        if self.machines_only:
            if not added_any["machine"]:
                self.tree.insert(p_machines, "end", text="(no matches)")
        else:
            if p_items is not None and not added_any["item"]:
                self.tree.insert(p_items, "end", text="(no matches)")
            if p_fluids is not None and not added_any["fluid"]:
                self.tree.insert(p_fluids, "end", text="(no matches)")

        # Auto-select first real item if possible.
        if self.machines_only:
            for iid in self.tree.get_children(p_machines):
                if iid in self._display_map:
                    self.tree.selection_set(iid)
                    self.tree.focus(iid)
                    return
        else:
            # Items might be nested under kind groups.
            if p_items is not None:
                for k_parent in self.tree.get_children(p_items):
                    for iid in self.tree.get_children(k_parent):
                        if iid in self._display_map:
                            self.tree.selection_set(iid)
                            self.tree.focus(iid)
                            return
            if p_fluids is not None:
                for iid in self.tree.get_children(p_fluids):
                    if iid in self._display_map:
                        self.tree.selection_set(iid)
                        self.tree.focus(iid)
                        return

    def get_selected_row(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self._display_map.get(sel[0])

    def new_item(self):
        dlg = AddItemDialog(self.app)
        self.wait_window(dlg)
        self.reload_items()
        self.rebuild_tree()

    def on_ok(self):
        row = self.get_selected_row()
        if not row:
            messagebox.showerror("Missing selection", "Select an item.")
            return
        self.result = {"id": row["id"], "name": row["name"], "kind": row["kind"]}
        self.destroy()

class AddItemDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Add Item")
        self.resizable(False, False)
        self.transient(app)
        self.after(0, lambda: _safe_grab(self))

        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Display Name").grid(row=0, column=0, sticky="w")
        self.display_name_var = tk.StringVar()
        display_entry = ttk.Entry(frm, textvariable=self.display_name_var, width=40)
        display_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=4)

        # Key is an internal stable identifier (used for merges/import later).
        # We auto-generate it from Display Name and keep it hidden to reduce user-facing clutter.

        ttk.Label(frm, text="Kind").grid(row=1, column=0, sticky="w")
        self.kind_var = tk.StringVar(value="item")
        kind_combo = ttk.Combobox(frm, textvariable=self.kind_var, values=["item", "fluid"], state="readonly", width=10)
        kind_combo.grid(row=1, column=1, sticky="w", padx=8, pady=4)

        # Detailed classification (Ore/Dust/Ingot/Plate/etc.)
        ttk.Label(frm, text="Item Kind").grid(row=2, column=0, sticky="w")
        self.item_kind_var = tk.StringVar(value=NONE_KIND_LABEL)
        self.item_kind_id = None
        self._kind_name_to_id = {}
        self.item_kind_combo = ttk.Combobox(frm, textvariable=self.item_kind_var, state="readonly", width=20)
        self.item_kind_combo.grid(row=2, column=1, sticky="w", padx=8, pady=4)
        self.item_kind_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_item_kind_selected())
        self._reload_item_kinds()

        self.kind_var.trace_add("write", lambda *_: self._on_high_level_kind_changed())

        self.is_base_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Base resource (planner stops here later)", variable=self.is_base_var)\
            .grid(row=3, column=1, sticky="w", padx=8, pady=(6, 0))
        # Machine Tier is enabled automatically when Item Kind is set to 'Machine'.

        ttk.Label(frm, text="Machine Tier").grid(row=4, column=0, sticky="w")
        self.machine_tier_var = tk.StringVar(value=NONE_TIER_LABEL)
        mt_values = [NONE_TIER_LABEL] + list(ALL_TIERS)
        self.machine_tier_combo = ttk.Combobox(
            frm,
            textvariable=self.machine_tier_var,
            values=mt_values,
            state="readonly",
            width=12,
        )
        self.machine_tier_combo.grid(row=4, column=1, sticky="w", padx=8, pady=4)
        self.machine_tier_combo.current(0)

        ttk.Label(frm, text="Input Slots").grid(row=5, column=0, sticky="w")
        self.machine_input_slots_var = tk.StringVar(value="1")
        self.machine_input_slots_spin = ttk.Spinbox(
            frm,
            from_=1,
            to=32,
            textvariable=self.machine_input_slots_var,
            width=6,
            command=self._on_slots_changed,
        )
        self.machine_input_slots_spin.grid(row=5, column=1, sticky="w", padx=8, pady=4)

        ttk.Label(frm, text="Output Slots").grid(row=6, column=0, sticky="w")
        self.machine_output_slots_var = tk.StringVar(value="1")
        self.machine_output_slots_spin = ttk.Spinbox(
            frm,
            from_=1,
            to=32,
            textvariable=self.machine_output_slots_var,
            width=6,
            command=self._on_slots_changed,
        )
        self.machine_output_slots_spin.grid(row=6, column=1, sticky="w", padx=8, pady=4)

        self.extra_machine_lf = ttk.LabelFrame(frm, text="Extra Machine Slots / Tanks", padding=6)
        self.extra_machine_lf.grid(row=7, column=0, columnspan=2, sticky="ew", padx=2, pady=(8, 0))
        self.extra_machine_lf.columnconfigure(1, weight=1)
        self.extra_machine_lf.columnconfigure(3, weight=1)

        ttk.Label(self.extra_machine_lf, text="Storage Slots").grid(row=0, column=0, sticky="w", padx=6, pady=2)
        self.machine_storage_slots_var = tk.StringVar(value="0")
        self.machine_storage_slots_spin = ttk.Spinbox(
            self.extra_machine_lf,
            from_=0,
            to=32,
            textvariable=self.machine_storage_slots_var,
            width=6,
        )
        self.machine_storage_slots_spin.grid(row=0, column=1, sticky="w", padx=6, pady=2)

        ttk.Label(self.extra_machine_lf, text="Power Slots").grid(row=0, column=2, sticky="w", padx=6, pady=2)
        self.machine_power_slots_var = tk.StringVar(value="0")
        self.machine_power_slots_spin = ttk.Spinbox(
            self.extra_machine_lf,
            from_=0,
            to=8,
            textvariable=self.machine_power_slots_var,
            width=6,
        )
        self.machine_power_slots_spin.grid(row=0, column=3, sticky="w", padx=6, pady=2)

        ttk.Label(self.extra_machine_lf, text="Circuit Slots").grid(row=1, column=0, sticky="w", padx=6, pady=2)
        self.machine_circuit_slots_var = tk.StringVar(value="0")
        self.machine_circuit_slots_spin = ttk.Spinbox(
            self.extra_machine_lf,
            from_=0,
            to=8,
            textvariable=self.machine_circuit_slots_var,
            width=6,
        )
        self.machine_circuit_slots_spin.grid(row=1, column=1, sticky="w", padx=6, pady=2)

        ttk.Label(self.extra_machine_lf, text="Input Tanks").grid(row=2, column=0, sticky="w", padx=6, pady=2)
        self.machine_input_tanks_var = tk.StringVar(value="0")
        self.machine_input_tanks_spin = ttk.Spinbox(
            self.extra_machine_lf,
            from_=0,
            to=16,
            textvariable=self.machine_input_tanks_var,
            width=6,
        )
        self.machine_input_tanks_spin.grid(row=2, column=1, sticky="w", padx=6, pady=2)

        ttk.Label(self.extra_machine_lf, text="Input Tank Capacity (L)").grid(row=2, column=2, sticky="w", padx=6, pady=2)
        self.machine_input_tank_capacity_var = tk.StringVar()
        self.machine_input_tank_capacity_entry = ttk.Entry(
            self.extra_machine_lf,
            textvariable=self.machine_input_tank_capacity_var,
            width=10,
        )
        self.machine_input_tank_capacity_entry.grid(
            row=2, column=3, sticky="w", padx=6, pady=2
        )

        ttk.Label(self.extra_machine_lf, text="Output Tanks").grid(row=3, column=0, sticky="w", padx=6, pady=2)
        self.machine_output_tanks_var = tk.StringVar(value="0")
        self.machine_output_tanks_spin = ttk.Spinbox(
            self.extra_machine_lf,
            from_=0,
            to=16,
            textvariable=self.machine_output_tanks_var,
            width=6,
        )
        self.machine_output_tanks_spin.grid(row=3, column=1, sticky="w", padx=6, pady=2)

        ttk.Label(self.extra_machine_lf, text="Output Tank Capacity (L)").grid(row=3, column=2, sticky="w", padx=6, pady=2)
        self.machine_output_tank_capacity_var = tk.StringVar()
        self.machine_output_tank_capacity_entry = ttk.Entry(
            self.extra_machine_lf,
            textvariable=self.machine_output_tank_capacity_var,
            width=10,
        )
        self.machine_output_tank_capacity_entry.grid(
            row=3, column=3, sticky="w", padx=6, pady=2
        )

        self._extra_machine_widgets = [
            self.machine_storage_slots_spin,
            self.machine_power_slots_spin,
            self.machine_circuit_slots_spin,
            self.machine_input_tanks_spin,
            self.machine_output_tanks_spin,
            self.machine_input_tank_capacity_entry,
            self.machine_output_tank_capacity_entry,
        ]

        # Per-slot content kinds (item vs fluid)
        self.inputs_lf = ttk.LabelFrame(frm, text="Input Slot Types", padding=6)
        self.inputs_lf.grid(row=8, column=0, columnspan=2, sticky="ew", padx=2, pady=(8, 0))
        self.outputs_lf = ttk.LabelFrame(frm, text="Output Slot Types", padding=6)
        self.outputs_lf.grid(row=9, column=0, columnspan=2, sticky="ew", padx=2, pady=(8, 0))

        self.in_slot_kind_vars = []
        self.out_slot_kind_vars = []
        self.in_slot_label_vars = []
        self.out_slot_label_vars = []

        # Keep slot UI in sync with slot counts
        self.machine_input_slots_var.trace_add("write", lambda *_: self._on_slots_changed())
        self.machine_output_slots_var.trace_add("write", lambda *_: self._on_slots_changed())

        self._toggle_machine_fields()

        btns = ttk.Frame(frm)
        btns.grid(row=10, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="Save", command=self.save).pack(side="right", padx=8)

        frm.columnconfigure(1, weight=1)
        display_entry.focus_set()

        # Apply initial field enabling
        self._on_high_level_kind_changed()

    def _toggle_machine_fields(self):
        # Machines are only valid for "item" (not "fluid").
        if (self.kind_var.get() or "").strip().lower() == "fluid":
            self.machine_tier_combo.configure(state="disabled")
            self.machine_tier_var.set(NONE_TIER_LABEL)
            self.machine_input_slots_spin.configure(state="disabled")
            self.machine_output_slots_spin.configure(state="disabled")
            self.machine_input_slots_var.set("1")
            self.machine_output_slots_var.set("1")
            self.machine_storage_slots_var.set("0")
            self.machine_power_slots_var.set("0")
            self.machine_circuit_slots_var.set("0")
            self.machine_input_tanks_var.set("0")
            self.machine_input_tank_capacity_var.set("")
            self.machine_output_tanks_var.set("0")
            self.machine_output_tank_capacity_var.set("")
            for w in self._extra_machine_widgets:
                w.configure(state="disabled")
            self._rebuild_slot_type_ui(0, 0)
            return

        # Enabled automatically when Item Kind is set to 'Machine'
        is_m = False
        if getattr(self, "machine_kind_id", None) is not None and self.item_kind_id is not None:
            is_m = self.item_kind_id == self.machine_kind_id
        else:
            is_m = ((self.item_kind_var.get() or "").strip().lower() == "machine")

        self.machine_tier_combo.configure(state="readonly" if is_m else "disabled")
        self.machine_input_slots_spin.configure(state="normal" if is_m else "disabled")
        self.machine_output_slots_spin.configure(state="normal" if is_m else "disabled")
        for w in self._extra_machine_widgets:
            w.configure(state="normal" if is_m else "disabled")

        if not is_m:
            self.machine_tier_var.set(NONE_TIER_LABEL)
            self.machine_input_slots_var.set("1")
            self.machine_output_slots_var.set("1")
            self.machine_storage_slots_var.set("0")
            self.machine_power_slots_var.set("0")
            self.machine_circuit_slots_var.set("0")
            self.machine_input_tanks_var.set("0")
            self.machine_input_tank_capacity_var.set("")
            self.machine_output_tanks_var.set("0")
            self.machine_output_tank_capacity_var.set("")
            self._rebuild_slot_type_ui(0, 0)
            return

        # Machine: ensure slot UI exists
        self._on_slots_changed()

    def _parse_slots(self, s: str, default: int = 1) -> int:
        s = (s or "").strip()
        try:
            v = int(float(s))
        except Exception:
            v = default
        return max(0, v)

    def _parse_int_nonneg(self, s: str, default: int = 0) -> int:
        s = (s or "").strip()
        if s == "":
            return default
        try:
            v = int(float(s))
        except Exception as exc:
            raise ValueError("Must be a whole number.") from exc
        if v < 0:
            raise ValueError("Must be 0 or greater.")
        return v

    def _parse_int_opt(self, s: str) -> int | None:
        s = (s or "").strip()
        if s == "":
            return None
        if not s.isdigit():
            raise ValueError("Must be a whole number.")
        return int(s)

    def _on_slots_changed(self):
        # Only rebuild when machine fields are enabled
        is_enabled = self.machine_tier_combo.cget("state") != "disabled"
        if not is_enabled:
            return
        in_n = self._parse_slots(self.machine_input_slots_var.get(), default=1)
        out_n = self._parse_slots(self.machine_output_slots_var.get(), default=1)
        self._rebuild_slot_type_ui(in_n, out_n)

    def _rebuild_slot_type_ui(self, in_n: int, out_n: int):
        # Clear existing widgets
        for w in list(self.inputs_lf.winfo_children()):
            w.destroy()
        for w in list(self.outputs_lf.winfo_children()):
            w.destroy()

        def _resize(vars_list, n, *, default=""):
            while len(vars_list) < n:
                vars_list.append(tk.StringVar(value=default))
            while len(vars_list) > n:
                vars_list.pop()
            return vars_list

        self.in_slot_kind_vars = _resize(getattr(self, "in_slot_kind_vars", []), in_n, default="item")
        self.out_slot_kind_vars = _resize(getattr(self, "out_slot_kind_vars", []), out_n, default="item")
        self.in_slot_label_vars = _resize(getattr(self, "in_slot_label_vars", []), in_n)
        self.out_slot_label_vars = _resize(getattr(self, "out_slot_label_vars", []), out_n)

        values = ["item", "fluid"]

        for i in range(in_n):
            ttk.Label(self.inputs_lf, text=f"In {i + 1}").grid(row=i, column=0, sticky="w", padx=8, pady=2)
            ttk.Combobox(
                self.inputs_lf,
                textvariable=self.in_slot_kind_vars[i],
                values=values,
                state="readonly",
                width=8,
            ).grid(row=i, column=1, sticky="w", padx=8, pady=2)
            ttk.Entry(
                self.inputs_lf,
                textvariable=self.in_slot_label_vars[i],
                width=14,
            ).grid(row=i, column=2, sticky="w", padx=(4, 8), pady=2)

        for i in range(out_n):
            ttk.Label(self.outputs_lf, text=f"Out {i + 1}").grid(row=i, column=0, sticky="w", padx=8, pady=2)
            ttk.Combobox(
                self.outputs_lf,
                textvariable=self.out_slot_kind_vars[i],
                values=values,
                state="readonly",
                width=8,
            ).grid(row=i, column=1, sticky="w", padx=8, pady=2)
            ttk.Entry(
                self.outputs_lf,
                textvariable=self.out_slot_label_vars[i],
                width=14,
            ).grid(row=i, column=2, sticky="w", padx=(4, 8), pady=2)

    def _reload_item_kinds(self):
        """Reload the Item Kind dropdown from the DB."""
        rows = self.app.conn.execute(
            "SELECT id, name FROM item_kinds ORDER BY sort_order ASC, name COLLATE NOCASE ASC"
        ).fetchall()
        self.machine_kind_id = next((r['id'] for r in rows if (r['name'] or '').strip().lower() == 'machine'), None)
        self._kind_name_to_id = {r["name"]: r["id"] for r in rows}

        values = [NONE_KIND_LABEL] + [r["name"] for r in rows] + [ADD_NEW_KIND_LABEL]
        self.item_kind_combo.configure(values=values)

        # Keep selection if possible
        cur = self.item_kind_var.get()
        if cur not in values:
            self.item_kind_var.set(NONE_KIND_LABEL)
        try:
            self.item_kind_combo.current(values.index(self.item_kind_var.get()))
        except Exception:
            self.item_kind_combo.current(0)

        # Refresh cached id
        v = (self.item_kind_var.get() or "").strip()
        self.item_kind_id = self._kind_name_to_id.get(v) if v and v != NONE_KIND_LABEL else None

    def _ensure_item_kind(self, name: str) -> str | None:
        name = (name or "").strip()
        if not name:
            return None
        # Case-insensitive match
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

    def _on_item_kind_selected(self):
        v = (self.item_kind_var.get() or "").strip()
        if v == ADD_NEW_KIND_LABEL:
            new_name = simpledialog.askstring("Add Item Kind", "New kind name:", parent=self)
            if not new_name:
                self.item_kind_var.set(NONE_KIND_LABEL)
                return
            canonical = self._ensure_item_kind(new_name)
            self._reload_item_kinds()
            if canonical:
                self.item_kind_var.set(canonical)
        # Update cached id (or None)
        v2 = (self.item_kind_var.get() or "").strip()
        self.item_kind_id = self._kind_name_to_id.get(v2) if v2 and v2 != NONE_KIND_LABEL else None
        self._toggle_machine_fields()

    def _on_high_level_kind_changed(self):
        """Enable/disable Item Kind + machine fields based on kind=item/fluid."""
        k = (self.kind_var.get() or "").strip().lower()
        if k == "fluid":
            # Item-kind classification is mostly for items; keep it optional but disabled for fluids.
            self.item_kind_var.set(NONE_KIND_LABEL)
            self.item_kind_combo.configure(state="disabled")
            self.item_kind_id = None
        else:
            self.item_kind_combo.configure(state="readonly")
        self._toggle_machine_fields()

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

    def save(self):
        display_name = (self.display_name_var.get() or "").strip()
        if not display_name:
            messagebox.showerror("Missing name", "Display Name is required.")
            return

        key = self._slugify(display_name)

        kind = (self.kind_var.get() or "").strip().lower()
        if kind not in ("item", "fluid"):
            messagebox.showerror("Invalid kind", "Kind must be item or fluid.")
            return

        is_base = 1 if self.is_base_var.get() else 0

        # Machine is derived from Item Kind selection
        is_machine = 0
        if kind == "item":
            if getattr(self, "machine_kind_id", None) is not None and self.item_kind_id is not None:
                is_machine = 1 if self.item_kind_id == self.machine_kind_id else 0
            else:
                is_machine = 1 if ((self.item_kind_var.get() or "").strip().lower() == "machine") else 0

        machine_tier = None
        machine_input_slots = None
        machine_output_slots = None
        machine_storage_slots = None
        machine_power_slots = None
        machine_circuit_slots = None
        machine_input_tanks = None
        machine_input_tank_capacity_l = None
        machine_output_tanks = None
        machine_output_tank_capacity_l = None

        if is_machine:
            mt_raw = (self.machine_tier_var.get() or "").strip()
            if mt_raw and mt_raw != NONE_TIER_LABEL:
                machine_tier = mt_raw

            in_n = self._parse_slots(self.machine_input_slots_var.get(), default=1)
            out_n = self._parse_slots(self.machine_output_slots_var.get(), default=1)
            if in_n < 1 or out_n < 1:
                messagebox.showerror("Invalid slots", "Input/Output slots must be at least 1 for machines.")
                return
            machine_input_slots = in_n
            machine_output_slots = out_n
            try:
                machine_storage_slots = self._parse_int_nonneg(self.machine_storage_slots_var.get(), default=0)
                machine_power_slots = self._parse_int_nonneg(self.machine_power_slots_var.get(), default=0)
                machine_circuit_slots = self._parse_int_nonneg(self.machine_circuit_slots_var.get(), default=0)
                machine_input_tanks = self._parse_int_nonneg(self.machine_input_tanks_var.get(), default=0)
                machine_input_tank_capacity_l = self._parse_int_opt(self.machine_input_tank_capacity_var.get())
                machine_output_tanks = self._parse_int_nonneg(self.machine_output_tanks_var.get(), default=0)
                machine_output_tank_capacity_l = self._parse_int_opt(self.machine_output_tank_capacity_var.get())
            except ValueError as e:
                messagebox.showerror("Invalid number", str(e))
                return
            if machine_input_tanks == 0:
                machine_input_tank_capacity_l = None
            if machine_output_tanks == 0:
                machine_output_tank_capacity_l = None

        # If the item is a fluid, clear machine + item-kind fields
        if kind == "fluid":
            is_machine = 0
            machine_tier = None
            machine_input_slots = None
            machine_output_slots = None
            machine_storage_slots = None
            machine_power_slots = None
            machine_circuit_slots = None
            machine_input_tanks = None
            machine_input_tank_capacity_l = None
            machine_output_tanks = None
            machine_output_tank_capacity_l = None
            item_kind_id = None
        else:
            item_kind_id = self.item_kind_id

        # Ensure unique key
        cur = self.app.conn.execute("SELECT 1 FROM items WHERE key=?", (key,)).fetchone()
        if cur:
            base = key
            n = 2
            while self.app.conn.execute("SELECT 1 FROM items WHERE key=?", (f"{base}_{n}",)).fetchone():
                n += 1
            key = f"{base}_{n}"

        try:
            cur = self.app.conn.execute(
                "INSERT INTO items(key, display_name, kind, is_base, is_machine, machine_tier, machine_input_slots, machine_output_slots, "
                "machine_storage_slots, machine_power_slots, machine_circuit_slots, machine_input_tanks, "
                "machine_input_tank_capacity_l, machine_output_tanks, machine_output_tank_capacity_l, item_kind_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    key,
                    display_name,
                    kind,
                    is_base,
                    is_machine,
                    machine_tier,
                    machine_input_slots,
                    machine_output_slots,
                    machine_storage_slots,
                    machine_power_slots,
                    machine_circuit_slots,
                    machine_input_tanks,
                    machine_input_tank_capacity_l,
                    machine_output_tanks,
                    machine_output_tank_capacity_l,
                    item_kind_id,
                ),
            )
            item_id = cur.lastrowid

            # Rewrite per-slot IO typing
            self.app.conn.execute("DELETE FROM machine_io_slots WHERE machine_item_id=?", (item_id,))
            if is_machine:
                self._rebuild_slot_type_ui(machine_input_slots, machine_output_slots)  # ensure var lists sized
                for i, v in enumerate(self.in_slot_kind_vars, start=0):
                    label_val = (self.in_slot_label_vars[i].get() or "").strip()
                    self.app.conn.execute(
                        "INSERT INTO machine_io_slots(machine_item_id, direction, slot_index, content_kind, label) "
                        "VALUES(?,?,?,?,?)",
                        (item_id, "in", i, (v.get() or "item").strip().lower(), label_val),
                    )
                for i, v in enumerate(self.out_slot_kind_vars, start=0):
                    label_val = (self.out_slot_label_vars[i].get() or "").strip()
                    self.app.conn.execute(
                        "INSERT INTO machine_io_slots(machine_item_id, direction, slot_index, content_kind, label) "
                        "VALUES(?,?,?,?,?)",
                        (item_id, "out", i, (v.get() or "item").strip().lower(), label_val),
                    )

            self.app.conn.commit()
        except Exception as e:
            messagebox.showerror("Save failed", f"Could not add item.\n\nDetails: {e}")
            return

        if hasattr(self.app, "status"):
            self.app.status.set(f"Added item: {display_name}")

        self.destroy()

class EditItemDialog(tk.Toplevel):
    def __init__(self, app, item_id: int):
        super().__init__(app)
        self.app = app
        self.item_id = item_id
        self.title("Edit Item")
        self.resizable(False, False)
        self.transient(app)
        self.after(0, lambda: _safe_grab(self))

        row = self.app.conn.execute(
            "SELECT i.id, i.key, COALESCE(i.display_name, i.key) AS name, i.display_name, i.kind, "
            "       i.is_base, i.is_machine, i.machine_tier, i.machine_input_slots, i.machine_output_slots, "
            "       i.machine_storage_slots, i.machine_power_slots, i.machine_circuit_slots, i.machine_input_tanks, "
            "       i.machine_input_tank_capacity_l, i.machine_output_tanks, i.machine_output_tank_capacity_l, "
            "       i.item_kind_id, k.name AS item_kind_name "
            "FROM items i "
            "LEFT JOIN item_kinds k ON k.id = i.item_kind_id "
            "WHERE i.id=?",
            (item_id,)
        ).fetchone()
        if not row:
            messagebox.showerror("Not found", "Item not found.")
            self.destroy()
            return

        self.original_key = row["key"]

        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Display Name").grid(row=0, column=0, sticky="w")
        self.display_name_var = tk.StringVar(value=row["display_name"] or row["key"])
        display_entry = ttk.Entry(frm, textvariable=self.display_name_var, width=40)
        display_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=4)

        ttk.Label(frm, text="Kind").grid(row=1, column=0, sticky="w")
        self.kind_var = tk.StringVar(value=row["kind"])
        kind_combo = ttk.Combobox(frm, textvariable=self.kind_var, values=["item", "fluid"], state="readonly", width=10)
        kind_combo.grid(row=1, column=1, sticky="w", padx=8, pady=4)

        # Detailed classification (Ore/Dust/Ingot/Plate/etc.)
        ttk.Label(frm, text="Item Kind").grid(row=2, column=0, sticky="w")
        self.item_kind_id = row["item_kind_id"]
        self.item_kind_var = tk.StringVar(value=(row["item_kind_name"] or "") or NONE_KIND_LABEL)
        self._kind_name_to_id = {}
        self.item_kind_combo = ttk.Combobox(frm, textvariable=self.item_kind_var, state="readonly", width=20)
        self.item_kind_combo.grid(row=2, column=1, sticky="w", padx=8, pady=4)
        self.item_kind_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_item_kind_selected())
        self._reload_item_kinds()

        self.kind_var.trace_add("write", lambda *_: self._on_high_level_kind_changed())

        self.is_base_var = tk.BooleanVar(value=bool(row["is_base"]))
        ttk.Checkbutton(frm, text="Base resource (planner stops here later)", variable=self.is_base_var)\
            .grid(row=3, column=1, sticky="w", padx=8, pady=(6, 0))
        # Machine Tier is enabled automatically when Item Kind is set to 'Machine'.

        ttk.Label(frm, text="Machine Tier").grid(row=4, column=0, sticky="w")
        current_mt = (row["machine_tier"] or "").strip()
        mt_values = [NONE_TIER_LABEL] + list(ALL_TIERS)
        if current_mt and current_mt not in mt_values:
            mt_values.insert(1, current_mt)
        self.machine_tier_var = tk.StringVar(value=current_mt or NONE_TIER_LABEL)
        self.machine_tier_combo = ttk.Combobox(frm, textvariable=self.machine_tier_var, values=mt_values, state="readonly", width=12)
        self.machine_tier_combo.grid(row=4, column=1, sticky="w", padx=8, pady=4)
        if self.machine_tier_var.get() in mt_values:
            self.machine_tier_combo.current(mt_values.index(self.machine_tier_var.get()))
        else:
            self.machine_tier_combo.current(0)

        ttk.Label(frm, text="Input Slots").grid(row=5, column=0, sticky="w")
        mis0 = _row_get(row, "machine_input_slots", None)
        try:
            mis_i = int(mis0) if mis0 is not None else 1
        except Exception:
            mis_i = 1
        self.machine_input_slots_var = tk.StringVar(value=str(mis_i))
        self.machine_input_slots_spin = ttk.Spinbox(
            frm,
            from_=1,
            to=32,
            textvariable=self.machine_input_slots_var,
            width=6,
            command=self._on_slots_changed,
        )
        self.machine_input_slots_spin.grid(row=5, column=1, sticky="w", padx=8, pady=4)

        ttk.Label(frm, text="Output Slots").grid(row=6, column=0, sticky="w")
        mos0 = row["machine_output_slots"]
        try:
            mos_i = int(mos0) if mos0 is not None else 1
        except Exception:
            mos_i = 1
        self.machine_output_slots_var = tk.StringVar(value=str(mos_i))
        self.machine_output_slots_spin = ttk.Spinbox(
            frm,
            from_=1,
            to=32,
            textvariable=self.machine_output_slots_var,
            width=6,
            command=self._on_slots_changed,
        )
        self.machine_output_slots_spin.grid(row=6, column=1, sticky="w", padx=8, pady=4)

        self.extra_machine_lf = ttk.LabelFrame(frm, text="Extra Machine Slots / Tanks", padding=6)
        self.extra_machine_lf.grid(row=7, column=0, columnspan=2, sticky="ew", padx=2, pady=(8, 0))
        self.extra_machine_lf.columnconfigure(1, weight=1)
        self.extra_machine_lf.columnconfigure(3, weight=1)

        ttk.Label(self.extra_machine_lf, text="Storage Slots").grid(row=0, column=0, sticky="w", padx=6, pady=2)
        mss0 = row["machine_storage_slots"]
        self.machine_storage_slots_var = tk.StringVar(value=str(int(mss0 or 0)))
        self.machine_storage_slots_spin = ttk.Spinbox(
            self.extra_machine_lf,
            from_=0,
            to=32,
            textvariable=self.machine_storage_slots_var,
            width=6,
        )
        self.machine_storage_slots_spin.grid(row=0, column=1, sticky="w", padx=6, pady=2)

        ttk.Label(self.extra_machine_lf, text="Power Slots").grid(row=0, column=2, sticky="w", padx=6, pady=2)
        mps0 = row["machine_power_slots"]
        self.machine_power_slots_var = tk.StringVar(value=str(int(mps0 or 0)))
        self.machine_power_slots_spin = ttk.Spinbox(
            self.extra_machine_lf,
            from_=0,
            to=8,
            textvariable=self.machine_power_slots_var,
            width=6,
        )
        self.machine_power_slots_spin.grid(row=0, column=3, sticky="w", padx=6, pady=2)

        ttk.Label(self.extra_machine_lf, text="Circuit Slots").grid(row=1, column=0, sticky="w", padx=6, pady=2)
        mcs0 = row["machine_circuit_slots"]
        self.machine_circuit_slots_var = tk.StringVar(value=str(int(mcs0 or 0)))
        self.machine_circuit_slots_spin = ttk.Spinbox(
            self.extra_machine_lf,
            from_=0,
            to=8,
            textvariable=self.machine_circuit_slots_var,
            width=6,
        )
        self.machine_circuit_slots_spin.grid(row=1, column=1, sticky="w", padx=6, pady=2)

        ttk.Label(self.extra_machine_lf, text="Input Tanks").grid(row=2, column=0, sticky="w", padx=6, pady=2)
        mit0 = row["machine_input_tanks"]
        self.machine_input_tanks_var = tk.StringVar(value=str(int(mit0 or 0)))
        self.machine_input_tanks_spin = ttk.Spinbox(
            self.extra_machine_lf,
            from_=0,
            to=16,
            textvariable=self.machine_input_tanks_var,
            width=6,
        )
        self.machine_input_tanks_spin.grid(row=2, column=1, sticky="w", padx=6, pady=2)

        ttk.Label(self.extra_machine_lf, text="Input Tank Capacity (L)").grid(row=2, column=2, sticky="w", padx=6, pady=2)
        mic0 = row["machine_input_tank_capacity_l"]
        self.machine_input_tank_capacity_var = tk.StringVar(value="" if mic0 is None else str(int(mic0)))
        self.machine_input_tank_capacity_entry = ttk.Entry(
            self.extra_machine_lf,
            textvariable=self.machine_input_tank_capacity_var,
            width=10,
        )
        self.machine_input_tank_capacity_entry.grid(row=2, column=3, sticky="w", padx=6, pady=2)

        ttk.Label(self.extra_machine_lf, text="Output Tanks").grid(row=3, column=0, sticky="w", padx=6, pady=2)
        mot0 = row["machine_output_tanks"]
        self.machine_output_tanks_var = tk.StringVar(value=str(int(mot0 or 0)))
        self.machine_output_tanks_spin = ttk.Spinbox(
            self.extra_machine_lf,
            from_=0,
            to=16,
            textvariable=self.machine_output_tanks_var,
            width=6,
        )
        self.machine_output_tanks_spin.grid(row=3, column=1, sticky="w", padx=6, pady=2)

        ttk.Label(self.extra_machine_lf, text="Output Tank Capacity (L)").grid(row=3, column=2, sticky="w", padx=6, pady=2)
        moc0 = row["machine_output_tank_capacity_l"]
        self.machine_output_tank_capacity_var = tk.StringVar(value="" if moc0 is None else str(int(moc0)))
        self.machine_output_tank_capacity_entry = ttk.Entry(
            self.extra_machine_lf,
            textvariable=self.machine_output_tank_capacity_var,
            width=10,
        )
        self.machine_output_tank_capacity_entry.grid(row=3, column=3, sticky="w", padx=6, pady=2)

        self._extra_machine_widgets = [
            self.machine_storage_slots_spin,
            self.machine_power_slots_spin,
            self.machine_circuit_slots_spin,
            self.machine_input_tanks_spin,
            self.machine_output_tanks_spin,
            self.machine_input_tank_capacity_entry,
            self.machine_output_tank_capacity_entry,
        ]

        # Per-slot content kinds (item vs fluid)
        self.inputs_lf = ttk.LabelFrame(frm, text="Input Slot Types", padding=6)
        self.inputs_lf.grid(row=8, column=0, columnspan=2, sticky="ew", padx=2, pady=(8, 0))
        self.outputs_lf = ttk.LabelFrame(frm, text="Output Slot Types", padding=6)
        self.outputs_lf.grid(row=9, column=0, columnspan=2, sticky="ew", padx=2, pady=(8, 0))

        self.in_slot_kind_vars = []
        self.out_slot_kind_vars = []
        self.in_slot_label_vars = []
        self.out_slot_label_vars = []

        # Load existing per-slot types
        slot_rows = self.app.conn.execute(
            "SELECT direction, slot_index, content_kind, label FROM machine_io_slots WHERE machine_item_id=? ORDER BY direction, slot_index",
            (self.item_id,),
        ).fetchall()
        in_map = {}
        out_map = {}
        in_label_map = {}
        out_label_map = {}
        for r in slot_rows:
            d = (r["direction"] or "").strip().lower()
            idx = int(r["slot_index"])
            ck = (r["content_kind"] or "item").strip().lower()
            label = (r["label"] or "").strip()
            if d == "in":
                in_map[idx] = ck
                in_label_map[idx] = label
            elif d == "out":
                out_map[idx] = ck
                out_label_map[idx] = label

        def _normalize_slot_map(slot_map: dict[int, str]) -> dict[int, str]:
            if not slot_map:
                return slot_map
            if 0 in slot_map:
                return slot_map
            min_idx = min(slot_map)
            if min_idx >= 1:
                return {idx - 1: val for idx, val in slot_map.items() if idx > 0}
            return slot_map

        in_map = _normalize_slot_map(in_map)
        out_map = _normalize_slot_map(out_map)
        in_label_map = _normalize_slot_map(in_label_map)
        out_label_map = _normalize_slot_map(out_label_map)

        # Pre-size var lists and set values
        for i in range(mis_i):
            self.in_slot_kind_vars.append(tk.StringVar(value=in_map.get(i, "item")))
            self.in_slot_label_vars.append(tk.StringVar(value=in_label_map.get(i, "")))
        for i in range(mos_i):
            self.out_slot_kind_vars.append(tk.StringVar(value=out_map.get(i, "item")))
            self.out_slot_label_vars.append(tk.StringVar(value=out_label_map.get(i, "")))

        # Keep slot UI in sync with slot counts
        self.machine_input_slots_var.trace_add("write", lambda *_: self._on_slots_changed())
        self.machine_output_slots_var.trace_add("write", lambda *_: self._on_slots_changed())

        # Build initial slot UI
        self._rebuild_slot_type_ui(mis_i, mos_i)

        btns = ttk.Frame(frm)
        btns.grid(row=10, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="Save", command=self.save).pack(side="right", padx=8)

        frm.columnconfigure(1, weight=1)
        display_entry.focus_set()

        self._on_high_level_kind_changed()


    def _parse_slots(self, s: str, default: int = 1) -> int:
        s = (s or "").strip()
        try:
            v = int(float(s))
        except Exception:
            v = default
        return max(0, v)

    def _parse_int_nonneg(self, s: str, default: int = 0) -> int:
        s = (s or "").strip()
        if s == "":
            return default
        try:
            v = int(float(s))
        except Exception as exc:
            raise ValueError("Must be a whole number.") from exc
        if v < 0:
            raise ValueError("Must be 0 or greater.")
        return v

    def _parse_int_opt(self, s: str) -> int | None:
        s = (s or "").strip()
        if s == "":
            return None
        if not s.isdigit():
            raise ValueError("Must be a whole number.")
        return int(s)

    def _on_slots_changed(self):
        # Only rebuild when machine fields are enabled
        is_enabled = self.machine_tier_combo.cget("state") != "disabled"
        if not is_enabled:
            return
        in_n = self._parse_slots(self.machine_input_slots_var.get(), default=1)
        out_n = self._parse_slots(self.machine_output_slots_var.get(), default=1)
        self._rebuild_slot_type_ui(in_n, out_n)

    def _rebuild_slot_type_ui(self, in_n: int, out_n: int):
        # Clear existing widgets
        for w in list(self.inputs_lf.winfo_children()):
            w.destroy()
        for w in list(self.outputs_lf.winfo_children()):
            w.destroy()

        def _resize(vars_list, n, *, default=""):
            while len(vars_list) < n:
                vars_list.append(tk.StringVar(value=default))
            while len(vars_list) > n:
                vars_list.pop()
            return vars_list

        self.in_slot_kind_vars = _resize(getattr(self, "in_slot_kind_vars", []), in_n, default="item")
        self.out_slot_kind_vars = _resize(getattr(self, "out_slot_kind_vars", []), out_n, default="item")
        self.in_slot_label_vars = _resize(getattr(self, "in_slot_label_vars", []), in_n)
        self.out_slot_label_vars = _resize(getattr(self, "out_slot_label_vars", []), out_n)

        values = ["item", "fluid"]

        for i in range(in_n):
            ttk.Label(self.inputs_lf, text=f"In {i + 1}").grid(row=i, column=0, sticky="w", padx=8, pady=2)
            ttk.Combobox(
                self.inputs_lf,
                textvariable=self.in_slot_kind_vars[i],
                values=values,
                state="readonly",
                width=8,
            ).grid(row=i, column=1, sticky="w", padx=8, pady=2)
            ttk.Entry(
                self.inputs_lf,
                textvariable=self.in_slot_label_vars[i],
                width=14,
            ).grid(row=i, column=2, sticky="w", padx=(4, 8), pady=2)

        for i in range(out_n):
            ttk.Label(self.outputs_lf, text=f"Out {i + 1}").grid(row=i, column=0, sticky="w", padx=8, pady=2)
            ttk.Combobox(
                self.outputs_lf,
                textvariable=self.out_slot_kind_vars[i],
                values=values,
                state="readonly",
                width=8,
            ).grid(row=i, column=1, sticky="w", padx=8, pady=2)
            ttk.Entry(
                self.outputs_lf,
                textvariable=self.out_slot_label_vars[i],
                width=14,
            ).grid(row=i, column=2, sticky="w", padx=(4, 8), pady=2)

    def _reload_item_kinds(self):
        rows = self.app.conn.execute(
            "SELECT id, name FROM item_kinds ORDER BY sort_order ASC, name COLLATE NOCASE ASC"
        ).fetchall()
        self.machine_kind_id = next((r['id'] for r in rows if (r['name'] or '').strip().lower() == 'machine'), None)
        self._kind_name_to_id = {r["name"]: r["id"] for r in rows}
        values = [NONE_KIND_LABEL] + [r["name"] for r in rows] + [ADD_NEW_KIND_LABEL]
        self.item_kind_combo.configure(values=values)

        # Keep selection if possible
        cur = self.item_kind_var.get()
        if cur not in values:
            self.item_kind_var.set(NONE_KIND_LABEL)
        try:
            self.item_kind_combo.current(values.index(self.item_kind_var.get()))
        except Exception:
            self.item_kind_combo.current(0)

        v = (self.item_kind_var.get() or "").strip()
        self.item_kind_id = self._kind_name_to_id.get(v) if v and v != NONE_KIND_LABEL else None

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

    def _on_item_kind_selected(self):
        v = (self.item_kind_var.get() or "").strip()
        if v == ADD_NEW_KIND_LABEL:
            new_name = simpledialog.askstring("Add Item Kind", "New kind name:", parent=self)
            if not new_name:
                self.item_kind_var.set(NONE_KIND_LABEL)
                self.item_kind_id = None
                return
            canonical = self._ensure_item_kind(new_name)
            self._reload_item_kinds()
            if canonical:
                self.item_kind_var.set(canonical)
        v2 = (self.item_kind_var.get() or "").strip()
        self.item_kind_id = self._kind_name_to_id.get(v2) if v2 and v2 != NONE_KIND_LABEL else None
        self._toggle_machine_fields()

    def _on_high_level_kind_changed(self):
        k = (self.kind_var.get() or "").strip().lower()
        if k == "fluid":
            self.item_kind_var.set(NONE_KIND_LABEL)
            self.item_kind_combo.configure(state="disabled")
            self.item_kind_id = None
        else:
            self.item_kind_combo.configure(state="readonly")
        self._toggle_machine_fields()


    def save(self):
        display_name = (self.display_name_var.get() or "").strip()
        if not display_name:
            messagebox.showerror("Missing name", "Display Name is required.")
            return

        kind = (self.kind_var.get() or "").strip().lower()
        if kind not in ("item", "fluid"):
            messagebox.showerror("Invalid kind", "Kind must be item or fluid.")
            return

        is_base = 1 if self.is_base_var.get() else 0

        # Machine is derived from Item Kind selection
        is_machine = 0
        if kind == "item":
            if getattr(self, "machine_kind_id", None) is not None and self.item_kind_id is not None:
                is_machine = 1 if self.item_kind_id == self.machine_kind_id else 0
            else:
                is_machine = 1 if ((self.item_kind_var.get() or "").strip().lower() == "machine") else 0

        machine_tier = None
        machine_input_slots = None
        machine_output_slots = None
        machine_storage_slots = None
        machine_power_slots = None
        machine_circuit_slots = None
        machine_input_tanks = None
        machine_input_tank_capacity_l = None
        machine_output_tanks = None
        machine_output_tank_capacity_l = None

        if is_machine:
            mt_raw = (self.machine_tier_var.get() or "").strip()
            if mt_raw and mt_raw != NONE_TIER_LABEL:
                machine_tier = mt_raw

            in_n = self._parse_slots(self.machine_input_slots_var.get(), default=1)
            out_n = self._parse_slots(self.machine_output_slots_var.get(), default=1)
            if in_n < 1 or out_n < 1:
                messagebox.showerror("Invalid slots", "Input/Output slots must be at least 1 for machines.")
                return
            machine_input_slots = in_n
            machine_output_slots = out_n
            try:
                machine_storage_slots = self._parse_int_nonneg(self.machine_storage_slots_var.get(), default=0)
                machine_power_slots = self._parse_int_nonneg(self.machine_power_slots_var.get(), default=0)
                machine_circuit_slots = self._parse_int_nonneg(self.machine_circuit_slots_var.get(), default=0)
                machine_input_tanks = self._parse_int_nonneg(self.machine_input_tanks_var.get(), default=0)
                machine_input_tank_capacity_l = self._parse_int_opt(self.machine_input_tank_capacity_var.get())
                machine_output_tanks = self._parse_int_nonneg(self.machine_output_tanks_var.get(), default=0)
                machine_output_tank_capacity_l = self._parse_int_opt(self.machine_output_tank_capacity_var.get())
            except ValueError as e:
                messagebox.showerror("Invalid number", str(e))
                return
            if machine_input_tanks == 0:
                machine_input_tank_capacity_l = None
            if machine_output_tanks == 0:
                machine_output_tank_capacity_l = None

        # If the item is a fluid, clear machine + item-kind fields
        if kind == "fluid":
            is_machine = 0
            machine_tier = None
            machine_input_slots = None
            machine_output_slots = None
            machine_storage_slots = None
            machine_power_slots = None
            machine_circuit_slots = None
            machine_input_tanks = None
            machine_input_tank_capacity_l = None
            machine_output_tanks = None
            machine_output_tank_capacity_l = None
            item_kind_id = None
        else:
            item_kind_id = self.item_kind_id

        try:
            self.app.conn.execute(
                "UPDATE items SET display_name=?, kind=?, is_base=?, is_machine=?, machine_tier=?, machine_input_slots=?, "
                "machine_output_slots=?, machine_storage_slots=?, machine_power_slots=?, machine_circuit_slots=?, "
                "machine_input_tanks=?, machine_input_tank_capacity_l=?, machine_output_tanks=?, machine_output_tank_capacity_l=?, "
                "item_kind_id=? "
                "WHERE id=?",
                (
                    display_name,
                    kind,
                    is_base,
                    is_machine,
                    machine_tier,
                    machine_input_slots,
                    machine_output_slots,
                    machine_storage_slots,
                    machine_power_slots,
                    machine_circuit_slots,
                    machine_input_tanks,
                    machine_input_tank_capacity_l,
                    machine_output_tanks,
                    machine_output_tank_capacity_l,
                    item_kind_id,
                    self.item_id,
                ),
            )

            # Rewrite per-slot IO typing
            self.app.conn.execute("DELETE FROM machine_io_slots WHERE machine_item_id=?", (self.item_id,))
            if is_machine:
                self._rebuild_slot_type_ui(machine_input_slots, machine_output_slots)  # ensure var lists sized
                for i, v in enumerate(self.in_slot_kind_vars, start=0):
                    label_val = (self.in_slot_label_vars[i].get() or "").strip()
                    self.app.conn.execute(
                        "INSERT INTO machine_io_slots(machine_item_id, direction, slot_index, content_kind, label) "
                        "VALUES(?,?,?,?,?)",
                        (self.item_id, "in", i, (v.get() or "item").strip().lower(), label_val),
                    )
                for i, v in enumerate(self.out_slot_kind_vars, start=0):
                    label_val = (self.out_slot_label_vars[i].get() or "").strip()
                    self.app.conn.execute(
                        "INSERT INTO machine_io_slots(machine_item_id, direction, slot_index, content_kind, label) "
                        "VALUES(?,?,?,?,?)",
                        (self.item_id, "out", i, (v.get() or "item").strip().lower(), label_val),
                    )

            self.app.conn.commit()
        except Exception as e:
            messagebox.showerror("Save failed", f"Could not update item.\n\nDetails: {e}")
            return

        if hasattr(self.app, "status"):
            self.app.status.set(f"Updated item: {display_name}")

        self.destroy()

class EditRecipeDialog(tk.Toplevel):
    def __init__(self, app, recipe_id: int):
        super().__init__(app)
        self.app = app
        self.recipe_id = recipe_id
        self.title("Edit Recipe")
        self.geometry("850x520")
        self.transient(app)
        self.after(0, lambda: _safe_grab(self))

        self.inputs = []
        self.outputs = []

        r = self.app.conn.execute("SELECT * FROM recipes WHERE id=?", (recipe_id,)).fetchone()
        if not r:
            messagebox.showerror("Not found", "Recipe not found.")
            self.destroy()
            return

        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        # Row 0
        ttk.Label(frm, text="Name").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=r["name"])
        ttk.Entry(frm, textvariable=self.name_var).grid(row=0, column=1, sticky="ew", padx=8)

        ttk.Label(frm, text="Method").grid(row=0, column=2, sticky="w")
        self.method_var = tk.StringVar(value="Machine")
        self.method_combo = ttk.Combobox(
            frm,
            textvariable=self.method_var,
            values=["Machine", "Crafting"],
            state="readonly",
            width=12,
        )
        self.method_combo.grid(row=0, column=3, sticky="w", padx=8)

        # Row 1 (method-specific on left, tier on right)
        self.machine_lbl = ttk.Label(frm, text="Machine")
        self.machine_lbl.grid(row=1, column=0, sticky="w")
        self.machine_var = tk.StringVar(value=r["machine"] or "")
        self.machine_item_id = r["machine_item_id"]
        self.machine_frame = ttk.Frame(frm)
        self.machine_frame.grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Entry(self.machine_frame, textvariable=self.machine_var).pack(side="left", fill="x", expand=True)
        ttk.Button(self.machine_frame, text="Pick…", command=self.pick_machine).pack(side="left", padx=(6, 0))
        ttk.Button(self.machine_frame, text="Clear", command=self.clear_machine).pack(side="left", padx=(6, 0))

        self.grid_lbl = ttk.Label(frm, text="Grid")
        self.grid_var = tk.StringVar(value=(r["grid_size"] or "4x4"))
        grid_values = ["4x4"]
        if hasattr(self.app, "is_crafting_6x6_unlocked") and self.app.is_crafting_6x6_unlocked():
            grid_values.append("6x6")
        if self.grid_var.get() and self.grid_var.get() not in grid_values:
            grid_values.append(self.grid_var.get())
        self.grid_combo = ttk.Combobox(frm, textvariable=self.grid_var, values=grid_values, state="readonly", width=12)

        ttk.Label(frm, text="Tier").grid(row=1, column=2, sticky="w")

        enabled_tiers = self.app.get_enabled_tiers() if hasattr(self.app, "get_enabled_tiers") else ALL_TIERS
        current_tier = (r["tier"] or "").strip()

        # Only show enabled tiers (+ a "none" option). If editing an older recipe whose tier
        # is now disabled, include its current value so it doesn't get lost.
        tiers = list(enabled_tiers)
        values = [NONE_TIER_LABEL]
        if current_tier and current_tier not in tiers:
            values.append(current_tier)
        values.extend(tiers)

        self.tier_var = tk.StringVar(value=current_tier or NONE_TIER_LABEL)
        tier_combo = ttk.Combobox(frm, textvariable=self.tier_var, values=values, state="readonly", width=12)
        tier_combo.grid(row=1, column=3, sticky="w", padx=8)

        # Try to select current tier if present; otherwise default to "none".
        if self.tier_var.get() in values:
            tier_combo.current(values.index(self.tier_var.get()))
        else:
            tier_combo.current(0)

        # Row 2 (Circuit on left; Station on right for crafting)
        ttk.Label(frm, text="Circuit").grid(row=2, column=0, sticky="w")
        self.circuit_var = tk.StringVar(value="" if r["circuit"] is None else str(r["circuit"]))
        ttk.Entry(frm, textvariable=self.circuit_var, width=10).grid(row=2, column=1, sticky="w", padx=8)

        self.station_lbl = ttk.Label(frm, text="Station")
        self.station_var = tk.StringVar(value="")
        self.station_item_id = r["station_item_id"]
        if self.station_item_id is not None:
            row = self.app.conn.execute(
                "SELECT COALESCE(display_name, key) AS name FROM items WHERE id=?",
                (self.station_item_id,)
            ).fetchone()
            if row:
                self.station_var.set(row["name"])
        self.station_frame = ttk.Frame(frm)
        station_entry = ttk.Entry(self.station_frame, textvariable=self.station_var, state="readonly")
        station_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(self.station_frame, text="Pick…", command=self.pick_station).pack(side="left", padx=(6, 0))
        ttk.Button(self.station_frame, text="Clear", command=self.clear_station).pack(side="left", padx=(6, 0))

        # Row 3 (seconds input; stored as ticks)
        ttk.Label(frm, text="Duration (seconds)").grid(row=3, column=0, sticky="w")
        seconds = "" if r["duration_ticks"] is None else f"{(r['duration_ticks'] / TPS):g}"
        self.duration_seconds_var = tk.StringVar(value=seconds)
        ttk.Entry(frm, textvariable=self.duration_seconds_var, width=10).grid(row=3, column=1, sticky="w", padx=8)

        ttk.Label(frm, text="EU/t").grid(row=3, column=2, sticky="w")
        self.eut_var = tk.StringVar(value="" if r["eu_per_tick"] is None else str(r["eu_per_tick"]))
        ttk.Entry(frm, textvariable=self.eut_var, width=10).grid(row=3, column=3, sticky="w", padx=8)

        # Notes
        ttk.Label(frm, text="Notes").grid(row=4, column=0, sticky="nw")
        self.notes_txt = tk.Text(frm, height=3, wrap="word")
        self.notes_txt.grid(row=4, column=1, columnspan=3, sticky="ew", padx=8, pady=(0, 8))
        self.notes_txt.insert("1.0", r["notes"] or "")

        # Lists
        lists = ttk.Frame(frm)
        lists.grid(row=5, column=0, columnspan=4, sticky="nsew", pady=(8, 0))
        lists.columnconfigure(0, weight=1)
        lists.columnconfigure(1, weight=1)
        lists.rowconfigure(1, weight=1)

        ttk.Label(lists, text="Inputs").grid(row=0, column=0, sticky="w")
        self.in_list = tk.Listbox(lists)
        self.in_list.grid(row=1, column=0, sticky="nsew", padx=(0, 8))

        in_btns = ttk.Frame(lists)
        in_btns.grid(row=2, column=0, sticky="ew", padx=(0, 8), pady=(6, 0))
        ttk.Button(in_btns, text="Add Input", command=self.add_input).pack(side="left")
        ttk.Button(in_btns, text="Edit", command=lambda: self.edit_selected(self.in_list, self.inputs)).pack(side="left", padx=6)
        ttk.Button(in_btns, text="Remove", command=lambda: self.remove_selected(self.in_list, self.inputs)).pack(side="left", padx=6)

        ttk.Label(lists, text="Outputs").grid(row=0, column=1, sticky="w")
        self.out_list = tk.Listbox(lists)
        self.out_list.grid(row=1, column=1, sticky="nsew")

        out_btns = ttk.Frame(lists)
        out_btns.grid(row=2, column=1, sticky="ew", pady=(6, 0))
        ttk.Button(out_btns, text="Add Output", command=self.add_output).pack(side="left")
        ttk.Button(out_btns, text="Edit", command=lambda: self.edit_selected(self.out_list, self.outputs, is_output=True)).pack(side="left", padx=6)
        ttk.Button(out_btns, text="Remove", command=lambda: self.remove_selected(self.out_list, self.outputs)).pack(side="left", padx=6)

        ins = self.app.conn.execute("""
            SELECT rl.id, rl.item_id, COALESCE(i.display_name, i.key) AS name, i.kind,
                   rl.qty_count, rl.qty_liters, rl.chance_percent, rl.output_slot_index
            FROM recipe_lines rl
            JOIN items i ON i.id = rl.item_id
            WHERE rl.recipe_id=? AND rl.direction='in'
            ORDER BY rl.id
        """, (recipe_id,)).fetchall()

        outs = self.app.conn.execute("""
            SELECT rl.id, rl.item_id, COALESCE(i.display_name, i.key) AS name, i.kind,
                   rl.qty_count, rl.qty_liters, rl.chance_percent, rl.output_slot_index
            FROM recipe_lines rl
            JOIN items i ON i.id = rl.item_id
            WHERE rl.recipe_id=? AND rl.direction='out'
            ORDER BY rl.id
        """, (recipe_id,)).fetchall()

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
                "output_slot_index": row["output_slot_index"],
            }
            self.inputs.append(line)
            self.in_list.insert(tk.END, self._fmt_line(line))

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
            self.out_list.insert(tk.END, self._fmt_line(line, is_output=True))

        bottom = ttk.Frame(frm)
        bottom.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        ttk.Label(bottom, text="Tip: Close window or Cancel to discard. No partial saves.").pack(side="left")
        ttk.Button(bottom, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="Save", command=self.save).pack(side="right", padx=8)

        frm.columnconfigure(1, weight=1)
        frm.columnconfigure(3, weight=1)
        frm.rowconfigure(5, weight=1)

        # Set initial method + toggle UI
        initial_method = (r["method"] or "machine").strip().lower()
        self.method_var.set("Crafting" if initial_method == "crafting" else "Machine")
        if self.method_var.get() in ("Machine", "Crafting"):
            self.method_combo.current(0 if self.method_var.get() == "Machine" else 1)
        self.method_var.trace_add("write", lambda *_: self._toggle_method_fields())
        self._toggle_method_fields()

    def pick_machine(self):
        d = ItemPickerDialog(self.app, title="Pick Machine", machines_only=True)
        self.wait_window(d)
        if d.result:
            self.machine_item_id = d.result["id"]
            self.machine_var.set(d.result["name"])

    def clear_machine(self):
        self.machine_item_id = None
        self.machine_var.set("")

    def pick_station(self):
        d = ItemPickerDialog(self.app, title="Pick Station", kinds=["item"])
        self.wait_window(d)
        if d.result:
            self.station_item_id = d.result["id"]
            self.station_var.set(d.result["name"])

    def clear_station(self):
        self.station_item_id = None
        self.station_var.set("")

    def _toggle_method_fields(self):
        method = (self.method_var.get() or "Machine").strip().lower()
        is_crafting = method == "crafting"

        if is_crafting:
            self.machine_lbl.grid_remove()
            self.machine_frame.grid_remove()

            self.grid_lbl.grid(row=1, column=0, sticky="w")
            self.grid_combo.grid(row=1, column=1, sticky="w", padx=8)

            self.station_lbl.grid(row=2, column=2, sticky="w")
            self.station_frame.grid(row=2, column=3, sticky="ew", padx=8)
        else:
            self.grid_lbl.grid_remove()
            self.grid_combo.grid_remove()
            self.station_lbl.grid_remove()
            self.station_frame.grid_remove()

            self.machine_lbl.grid(row=1, column=0, sticky="w")
            self.machine_frame.grid(row=1, column=1, sticky="ew", padx=8)

    def add_input(self):
        d = ItemLineDialog(self.app, "Add Input")
        self.wait_window(d)
        if d.result:
            if d.result.get("kind") == "fluid" and not self._check_tank_limit(direction="in"):
                return
            self.inputs.append(d.result)
            self.in_list.insert(tk.END, self._fmt_line(d.result))

    def add_output(self):
        dialog_kwargs = self._get_output_dialog_kwargs()
        d = ItemLineDialog(self.app, "Add Output", **dialog_kwargs)
        self.wait_window(d)
        if d.result:
            if d.result.get("kind") == "fluid" and not self._check_tank_limit(direction="out"):
                return
            self.outputs.append(d.result)
            self.out_list.insert(tk.END, self._fmt_line(d.result, is_output=True))

    def edit_selected(self, listbox: tk.Listbox, backing_list: list, *, is_output: bool = False):
        sel = listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        line = backing_list[idx]
        dialog_kwargs = {}
        if is_output:
            dialog_kwargs = self._get_output_dialog_kwargs(current_slot=line.get("output_slot_index"))
        d = ItemLineDialog(
            self.app,
            "Edit Output" if is_output else "Edit Input",
            initial_line=line,
            **dialog_kwargs,
        )
        self.wait_window(d)
        if d.result:
            if d.result.get("kind") == "fluid":
                if is_output and not self._check_tank_limit(direction="out", exclude_idx=idx):
                    return
                if not is_output and not self._check_tank_limit(direction="in", exclude_idx=idx):
                    return
            new_line = d.result
            new_line["id"] = line.get("id")
            backing_list[idx] = new_line
            listbox.delete(idx)
            listbox.insert(idx, self._fmt_line(new_line, is_output=is_output))

    def remove_selected(self, listbox: tk.Listbox, backing_list: list):
        sel = listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        listbox.delete(idx)
        del backing_list[idx]

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
        if line["kind"] == "fluid":
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
            "SELECT machine_output_slots FROM items WHERE id=?",
            (self.machine_item_id,),
        ).fetchone()
        if not row:
            return None
        try:
            mos = int(row["machine_output_slots"] or 1)
        except Exception:
            mos = 1
        return mos if mos > 0 else 1

    def _get_machine_tank_limits(self) -> tuple[int | None, int | None]:
        if self.machine_item_id is None:
            return None, None
        row = self.app.conn.execute(
            "SELECT machine_input_tanks, machine_output_tanks FROM items WHERE id=?",
            (self.machine_item_id,),
        ).fetchone()
        if not row:
            return None, None
        try:
            in_tanks = int(row["machine_input_tanks"] or 0)
        except Exception:
            in_tanks = 0
        try:
            out_tanks = int(row["machine_output_tanks"] or 0)
        except Exception:
            out_tanks = 0
        return (in_tanks if in_tanks > 0 else None, out_tanks if out_tanks > 0 else None)

    @staticmethod
    def _count_fluid_lines(lines: list[dict], *, exclude_idx: int | None = None) -> int:
        count = 0
        for idx, line in enumerate(lines):
            if exclude_idx is not None and idx == exclude_idx:
                continue
            if line.get("kind") == "fluid":
                count += 1
        return count

    def _check_tank_limit(self, *, direction: str, exclude_idx: int | None = None) -> bool:
        in_tanks, out_tanks = self._get_machine_tank_limits()
        limit = in_tanks if direction == "in" else out_tanks
        if limit is None:
            return True
        lines = self.inputs if direction == "in" else self.outputs
        if self._count_fluid_lines(lines, exclude_idx=exclude_idx) >= limit:
            messagebox.showerror(
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
        method = (self.method_var.get() or "Machine").strip().lower()
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

    def save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Missing name", "Recipe name is required.")
            return

        # Method-specific fields
        method = (self.method_var.get() or "Machine").strip().lower()
        if method == "crafting":
            method_db = "crafting"
            machine = None
            machine_item_id = None
            grid_size = (self.grid_var.get() or "4x4").strip()
            station_item_id = self.station_item_id
        else:
            method_db = "machine"
            machine = self.machine_var.get().strip() or None
            machine_item_id = None if machine is None else self.machine_item_id
            grid_size = None
            station_item_id = None
        tier_raw = (self.tier_var.get() or "").strip()
        tier = None if (tier_raw == "" or tier_raw == NONE_TIER_LABEL) else tier_raw
        notes = self.notes_txt.get("1.0", tk.END).strip() or None

        try:
            circuit = self._parse_int_opt(self.circuit_var.get())
            duration_s = self._parse_float_opt(self.duration_seconds_var.get())
            eut = self._parse_int_opt(self.eut_var.get())
        except ValueError as e:
            messagebox.showerror("Invalid number", str(e))
            return

        duration_ticks = None if duration_s is None else int(round(duration_s * TPS))

        if not self.inputs and not self.outputs:
            if not messagebox.askyesno("No lines?", "No inputs/outputs added. Save anyway?"):
                return

        try:
            self.app.conn.execute("BEGIN")
            self.app.conn.execute(
                "UPDATE recipes SET name=?, method=?, machine=?, machine_item_id=?, grid_size=?, station_item_id=?, circuit=?, tier=?, duration_ticks=?, eu_per_tick=?, notes=? WHERE id=?",
                (name, method_db, machine, machine_item_id, grid_size, station_item_id, circuit, tier, duration_ticks, eut, notes, self.recipe_id)
            )
            self.app.conn.execute("DELETE FROM recipe_lines WHERE recipe_id=?", (self.recipe_id,))

            for line in self.inputs:
                if line["kind"] == "fluid":
                    self.app.conn.execute(
                        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_liters, chance_percent, output_slot_index) "
                        "VALUES(?,?,?,?,?,?)",
                        (self.recipe_id, "in", line["item_id"], line["qty_liters"], None, None)
                    )
                else:
                    self.app.conn.execute(
                        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_count, chance_percent, output_slot_index) "
                        "VALUES(?,?,?,?,?,?)",
                        (self.recipe_id, "in", line["item_id"], line["qty_count"], None, None)
                    )

            for line in self.outputs:
                chance = line.get("chance_percent", 100.0)
                if line["kind"] == "fluid":
                    self.app.conn.execute(
                        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_liters, chance_percent, output_slot_index) "
                        "VALUES(?,?,?,?,?,?)",
                        (
                            self.recipe_id,
                            "out",
                            line["item_id"],
                            line["qty_liters"],
                            chance,
                            line.get("output_slot_index"),
                        )
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
                            chance,
                            line.get("output_slot_index"),
                        )
                    )
            self.app.conn.commit()
        except Exception as e:
            self.app.conn.rollback()
            messagebox.showerror("Save failed", str(e))
            return

        if hasattr(self.app, "status"):
            self.app.status.set(f"Updated recipe: {name}")

        self.destroy()

class ItemLineDialog(tk.Toplevel):
    def __init__(
        self,
        app,
        title: str,
        *,
        show_chance: bool = False,
        output_slot_choices: list[int] | None = None,
        fixed_output_slot: int | None = None,
        require_chance: bool = False,
        initial_line: dict | None = None,
    ):
        super().__init__(app)
        self.app = app
        self.title(title)
        self.show_chance = show_chance
        self.output_slot_choices = output_slot_choices
        self.fixed_output_slot = fixed_output_slot
        self.require_chance = require_chance
        self.resizable(False, False)
        self.transient(app)
        self.after(0, lambda: _safe_grab(self))

        self.result = None
        self._selected = None  # {id, name, kind}

        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Item").grid(row=0, column=0, sticky="w")
        self.item_label_var = tk.StringVar(value="(none selected)")
        ttk.Label(frm, textvariable=self.item_label_var).grid(row=0, column=1, sticky="w", padx=8, pady=4)

        btns_item = ttk.Frame(frm)
        btns_item.grid(row=0, column=2, sticky="e")
        ttk.Button(btns_item, text="Pick…", command=self.pick_item).pack(side="left")
        ttk.Button(btns_item, text="New Item…", command=self.new_item).pack(side="left", padx=(6, 0))

        ttk.Label(frm, text="Kind").grid(row=1, column=0, sticky="w")
        self.kind_lbl = ttk.Label(frm, text="(select an item)")
        self.kind_lbl.grid(row=1, column=1, sticky="w", padx=8)

        self.qty_label = ttk.Label(frm, text="Quantity")
        self.qty_label.grid(row=2, column=0, sticky="w")
        self.qty_var = tk.StringVar()
        self.qty_entry = ttk.Entry(frm, textvariable=self.qty_var, width=20)
        self.qty_entry.grid(row=2, column=1, sticky="w", padx=8, pady=4)

        row_btn = 3
        if self.fixed_output_slot is not None or self.output_slot_choices:
            ttk.Label(frm, text="Output Slot").grid(row=row_btn, column=0, sticky="w")
            if self.fixed_output_slot is not None:
                self.output_slot_var = tk.StringVar(value=str(self.fixed_output_slot))
                ttk.Label(frm, textvariable=self.output_slot_var).grid(row=row_btn, column=1, sticky="w", padx=8, pady=4)
            else:
                values = [str(v) for v in (self.output_slot_choices or [])]
                self.output_slot_var = tk.StringVar(value=(values[0] if values else ""))
                ttk.Combobox(frm, textvariable=self.output_slot_var, values=values, state="readonly", width=10).grid(
                    row=row_btn, column=1, sticky="w", padx=8, pady=4
                )
            row_btn += 1
        if self.show_chance:
            ttk.Label(frm, text="Chance (%)").grid(row=row_btn, column=0, sticky="w")
            self.chance_var = tk.StringVar(value="")
            ttk.Entry(frm, textvariable=self.chance_var, width=20).grid(row=row_btn, column=1, sticky="w", padx=8, pady=4)
            chance_note = "Chance is required for extra output slots." if self.require_chance else "Leave blank for 100% (guaranteed)"
            ttk.Label(frm, text=chance_note).grid(row=row_btn, column=2, sticky="w", padx=8)
            row_btn += 1

        btns = ttk.Frame(frm)
        btns.grid(row=row_btn, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="OK", command=self.save).pack(side="right", padx=8)

        frm.columnconfigure(1, weight=1)

        # Start with an item selected if there's exactly one item.
        row = self.app.conn.execute(
            "SELECT COUNT(*) AS c FROM items"
        ).fetchone()
        if row and row["c"] == 1:
            only = self.app.conn.execute(
                "SELECT id, COALESCE(display_name, key) AS name, kind FROM items LIMIT 1"
            ).fetchone()
            if only:
                self._set_selected({"id": only["id"], "name": only["name"], "kind": only["kind"]})
        if initial_line:
            row = self.app.conn.execute(
                "SELECT id, COALESCE(display_name, key) AS name, kind FROM items WHERE id=?",
                (initial_line.get("item_id"),)
            ).fetchone()
            if row:
                self._set_selected({"id": row["id"], "name": row["name"], "kind": row["kind"]})
            if initial_line.get("qty_liters") is not None:
                self.qty_var.set(str(self._coerce_whole_number(initial_line["qty_liters"])))
            elif initial_line.get("qty_count") is not None:
                self.qty_var.set(str(self._coerce_whole_number(initial_line["qty_count"])))
            if self.show_chance:
                chance = initial_line.get("chance_percent")
                if chance is None or abs(float(chance) - 100.0) < 1e-9:
                    self.chance_var.set("")
                else:
                    self.chance_var.set(str(chance))
            if (self.fixed_output_slot is None and self.output_slot_choices is not None
                    and initial_line.get("output_slot_index") is not None):
                self.output_slot_var.set(str(initial_line["output_slot_index"]))
        self.update_kind_ui()

    @staticmethod
    def _coerce_whole_number(value):
        if value is None:
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return value

    def _set_selected(self, sel: dict | None):
        self._selected = sel
        if not sel:
            self.item_label_var.set("(none selected)")
        else:
            self.item_label_var.set(sel["name"])
        self.update_kind_ui()

    def update_kind_ui(self):
        if not self._selected:
            self.kind_lbl.config(text="(select an item)")
            self.qty_label.config(text="Quantity")
            return

        kind = self._selected["kind"]
        self.kind_lbl.config(text=kind)
        self.qty_label.config(text="Liters (L)" if kind == "fluid" else "Count")

    def pick_item(self):
        d = ItemPickerDialog(self.app, title="Pick Item")
        self.wait_window(d)
        if d.result:
            self._set_selected({"id": d.result["id"], "name": d.result["name"], "kind": d.result["kind"]})

    def new_item(self):
        dlg = AddItemDialog(self.app)
        self.wait_window(dlg)

        # Auto-select newest item (highest id)
        newest = self.app.conn.execute(
            "SELECT id, COALESCE(display_name, key) AS name, kind "
            "FROM items ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if newest:
            self._set_selected({"id": newest["id"], "name": newest["name"], "kind": newest["kind"]})

    def save(self):
        it = self._selected
        if not it:
            messagebox.showerror("Missing item", "Select an item.")
            return

        qty_s = (self.qty_var.get() or "").strip()
        try:
            if not qty_s.isdigit():
                raise ValueError
            qty = int(qty_s)
        except ValueError:
            messagebox.showerror("Invalid quantity", "Quantity must be a whole number.")
            return
        if qty <= 0:
            messagebox.showerror("Invalid quantity", "Quantity must be > 0.")
            return

        # Output dict matches what AddRecipeDialog will write into recipe_lines
        if it["kind"] == "fluid":
            self.result = {"item_id": it["id"], "name": it["name"], "kind": it["kind"], "qty_liters": qty, "qty_count": None}
        else:
            self.result = {"item_id": it["id"], "name": it["name"], "kind": it["kind"], "qty_liters": None, "qty_count": qty}

        if self.show_chance:
            ch_s = (getattr(self, "chance_var", tk.StringVar(value="")).get() or "").strip()
            if ch_s == "":
                if self.require_chance:
                    slot_val = None
                    if self.fixed_output_slot is not None:
                        slot_val = self.fixed_output_slot
                    elif getattr(self, "output_slot_var", None):
                        try:
                            slot_val = int(self.output_slot_var.get())
                        except Exception:
                            slot_val = None
                    if slot_val is not None and slot_val <= 0:
                        chance = 100.0
                        self.result["chance_percent"] = chance
                    else:
                        messagebox.showerror("Invalid chance", "Chance is required for extra output slots.")
                        return
                else:
                    chance = 100.0
                    self.result["chance_percent"] = chance
            else:
                try:
                    chance = float(ch_s)
                except ValueError:
                    messagebox.showerror("Invalid chance", "Chance must be a number between 0 and 100.")
                    return
                if chance <= 0 or chance > 100:
                    messagebox.showerror("Invalid chance", "Chance must be > 0 and <= 100.")
                    return
                self.result["chance_percent"] = chance

        if self.fixed_output_slot is not None or self.output_slot_choices:
            try:
                self.result["output_slot_index"] = int(self.output_slot_var.get())
            except Exception:
                messagebox.showerror("Invalid output slot", "Select a valid output slot.")
                return

        self.destroy()

class AddRecipeDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Add Recipe")
        self.geometry("850x520")
        self.transient(app)
        self.after(0, lambda: _safe_grab(self))

        self.inputs = []
        self.outputs = []

        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        # Row 0
        ttk.Label(frm, text="Name").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.name_var).grid(row=0, column=1, sticky="ew", padx=8)

        ttk.Label(frm, text="Method").grid(row=0, column=2, sticky="w")
        self.method_var = tk.StringVar(value="Machine")
        self.method_combo = ttk.Combobox(
            frm,
            textvariable=self.method_var,
            values=["Machine", "Crafting"],
            state="readonly",
            width=12,
        )
        self.method_combo.grid(row=0, column=3, sticky="w", padx=8)
        self.method_combo.current(0)

        # Row 1 (method-specific on left, tier on right)
        self.machine_lbl = ttk.Label(frm, text="Machine")
        self.machine_lbl.grid(row=1, column=0, sticky="w")
        self.machine_var = tk.StringVar()
        self.machine_item_id = None
        self.machine_frame = ttk.Frame(frm)
        self.machine_frame.grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Entry(self.machine_frame, textvariable=self.machine_var).pack(side="left", fill="x", expand=True)
        ttk.Button(self.machine_frame, text="Pick…", command=self.pick_machine).pack(side="left", padx=(6, 0))
        ttk.Button(self.machine_frame, text="Clear", command=self.clear_machine).pack(side="left", padx=(6, 0))

        self.grid_lbl = ttk.Label(frm, text="Grid")
        self.grid_var = tk.StringVar(value="4x4")
        grid_values = ["4x4"]
        if hasattr(self.app, "is_crafting_6x6_unlocked") and self.app.is_crafting_6x6_unlocked():
            grid_values.append("6x6")
        self.grid_combo = ttk.Combobox(frm, textvariable=self.grid_var, values=grid_values, state="readonly", width=12)

        ttk.Label(frm, text="Tier").grid(row=1, column=2, sticky="w")

        enabled_tiers = self.app.get_enabled_tiers() if hasattr(self.app, "get_enabled_tiers") else ALL_TIERS
        values = [NONE_TIER_LABEL] + list(enabled_tiers)

        # Default new recipes to "no tier" so they always show regardless of enabled tiers.
        self.tier_var = tk.StringVar(value=NONE_TIER_LABEL)
        tier_combo = ttk.Combobox(frm, textvariable=self.tier_var, values=values, state="readonly", width=12)
        tier_combo.grid(row=1, column=3, sticky="w", padx=8)
        tier_combo.current(0)

        # Row 2 (Circuit on left; Station on right for crafting)
        ttk.Label(frm, text="Circuit").grid(row=2, column=0, sticky="w")
        self.circuit_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.circuit_var, width=10).grid(row=2, column=1, sticky="w", padx=8)

        self.station_lbl = ttk.Label(frm, text="Station")
        self.station_var = tk.StringVar(value="")
        self.station_item_id = None
        self.station_frame = ttk.Frame(frm)
        station_entry = ttk.Entry(self.station_frame, textvariable=self.station_var, state="readonly")
        station_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(self.station_frame, text="Pick…", command=self.pick_station).pack(side="left", padx=(6, 0))
        ttk.Button(self.station_frame, text="Clear", command=self.clear_station).pack(side="left", padx=(6, 0))

        # Row 3 (seconds input; stored as ticks)
        ttk.Label(frm, text="Duration (seconds)").grid(row=3, column=0, sticky="w")
        self.duration_seconds_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.duration_seconds_var, width=10).grid(row=3, column=1, sticky="w", padx=8)

        ttk.Label(frm, text="EU/t").grid(row=3, column=2, sticky="w")
        self.eut_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.eut_var, width=10).grid(row=3, column=3, sticky="w", padx=8)

        # Notes
        ttk.Label(frm, text="Notes").grid(row=4, column=0, sticky="nw")
        self.notes_txt = tk.Text(frm, height=3, wrap="word")
        self.notes_txt.grid(row=4, column=1, columnspan=3, sticky="ew", padx=8, pady=(0, 8))

        # Lists
        lists = ttk.Frame(frm)
        lists.grid(row=5, column=0, columnspan=4, sticky="nsew", pady=(8, 0))
        lists.columnconfigure(0, weight=1)
        lists.columnconfigure(1, weight=1)
        lists.rowconfigure(1, weight=1)

        ttk.Label(lists, text="Inputs").grid(row=0, column=0, sticky="w")
        self.in_list = tk.Listbox(lists)
        self.in_list.grid(row=1, column=0, sticky="nsew", padx=(0, 8))

        in_btns = ttk.Frame(lists)
        in_btns.grid(row=2, column=0, sticky="ew", padx=(0, 8), pady=(6, 0))
        ttk.Button(in_btns, text="Add Input", command=self.add_input).pack(side="left")
        ttk.Button(in_btns, text="Remove", command=lambda: self.remove_selected(self.in_list, self.inputs)).pack(side="left", padx=6)

        ttk.Label(lists, text="Outputs").grid(row=0, column=1, sticky="w")
        self.out_list = tk.Listbox(lists)
        self.out_list.grid(row=1, column=1, sticky="nsew")

        out_btns = ttk.Frame(lists)
        out_btns.grid(row=2, column=1, sticky="ew", pady=(6, 0))
        ttk.Button(out_btns, text="Add Output", command=self.add_output).pack(side="left")
        ttk.Button(out_btns, text="Remove", command=lambda: self.remove_selected(self.out_list, self.outputs)).pack(side="left", padx=6)

        bottom = ttk.Frame(frm)
        bottom.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        ttk.Label(bottom, text="Tip: Close window or Cancel to discard. No partial saves.").pack(side="left")
        ttk.Button(bottom, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="Save", command=self.save).pack(side="right", padx=8)

        frm.columnconfigure(1, weight=1)
        frm.columnconfigure(3, weight=1)
        frm.rowconfigure(5, weight=1)

        # Live toggle for Machine vs Crafting
        self.method_var.trace_add("write", lambda *_: self._toggle_method_fields())
        self._toggle_method_fields()

    def pick_machine(self):
        d = ItemPickerDialog(self.app, title="Pick Machine", machines_only=True)
        self.wait_window(d)
        if d.result:
            self.machine_item_id = d.result["id"]
            self.machine_var.set(d.result["name"])

    def clear_machine(self):
        self.machine_item_id = None
        self.machine_var.set("")

    def pick_station(self):
        d = ItemPickerDialog(self.app, title="Pick Station", kinds=["item"])
        self.wait_window(d)
        if d.result:
            self.station_item_id = d.result["id"]
            self.station_var.set(d.result["name"])

    def clear_station(self):
        self.station_item_id = None
        self.station_var.set("")

    def _toggle_method_fields(self):
        method = (self.method_var.get() or "Machine").strip().lower()
        is_crafting = method == "crafting"

        if is_crafting:
            # Replace Machine widgets with Grid widgets
            self.machine_lbl.grid_remove()
            self.machine_frame.grid_remove()

            self.grid_lbl.grid(row=1, column=0, sticky="w")
            self.grid_combo.grid(row=1, column=1, sticky="w", padx=8)

            # Station on row 2, right side
            self.station_lbl.grid(row=2, column=2, sticky="w")
            self.station_frame.grid(row=2, column=3, sticky="ew", padx=8)
        else:
            # Show Machine widgets
            self.grid_lbl.grid_remove()
            self.grid_combo.grid_remove()
            self.station_lbl.grid_remove()
            self.station_frame.grid_remove()

            self.machine_lbl.grid(row=1, column=0, sticky="w")
            self.machine_frame.grid(row=1, column=1, sticky="ew", padx=8)

    def add_input(self):
        d = ItemLineDialog(self.app, "Add Input")
        self.wait_window(d)
        if d.result:
            if d.result.get("kind") == "fluid" and not self._check_tank_limit(direction="in"):
                return
            self.inputs.append(d.result)
            self.in_list.insert(tk.END, self._fmt_line(d.result))

    def add_output(self):
        method = (self.method_var.get() or "Machine").strip().lower()
        if method == "machine" and self.machine_item_id is not None:
            mos = self._get_machine_output_slots() or 1
            used_slots = self._get_used_output_slots()
            if not self.outputs:
                d = ItemLineDialog(self.app, "Add Output", fixed_output_slot=0)
            else:
                if mos <= 1:
                    messagebox.showerror("No extra slots", "This machine only has 1 output slot.")
                    return
                available = [i for i in range(1, mos) if i not in used_slots]
                if not available:
                    messagebox.showerror("No extra slots", "All additional output slots are already used.")
                    return
                d = ItemLineDialog(
                    self.app,
                    "Add Output",
                    show_chance=True,
                    output_slot_choices=available,
                    require_chance=True,
                )
        else:
            d = ItemLineDialog(self.app, "Add Output", show_chance=True)
        self.wait_window(d)
        if d.result:
            if d.result.get("kind") == "fluid" and not self._check_tank_limit(direction="out"):
                return
            self.outputs.append(d.result)
            self.out_list.insert(tk.END, self._fmt_line(d.result, is_output=True))

    def remove_selected(self, listbox: tk.Listbox, backing_list: list):
        sel = listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        listbox.delete(idx)
        del backing_list[idx]

    def _fmt_line(self, line: dict, *, is_output: bool = False) -> str:
        chance = line.get("chance_percent")
        chance_txt = ""
        if chance is not None:
            try:
                c = float(chance)
            except Exception:
                c = None
            if c is not None and c < 99.999:
                # Display as a percent; keep it compact.
                if abs(c - int(c)) < 1e-9:
                    chance_txt = f" ({int(c)}%)"
                else:
                    chance_txt = f" ({c}%)"
        slot_txt = ""
        if is_output:
            slot_idx = line.get("output_slot_index")
            if slot_idx is not None:
                slot_txt = f" (Slot {slot_idx})"
        if line["kind"] == "fluid":
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
            "SELECT machine_output_slots FROM items WHERE id=?",
            (self.machine_item_id,),
        ).fetchone()
        if not row:
            return None
        try:
            mos = int(row["machine_output_slots"] or 1)
        except Exception:
            mos = 1
        return mos if mos > 0 else 1

    def _get_machine_tank_limits(self) -> tuple[int | None, int | None]:
        if self.machine_item_id is None:
            return None, None
        row = self.app.conn.execute(
            "SELECT machine_input_tanks, machine_output_tanks FROM items WHERE id=?",
            (self.machine_item_id,),
        ).fetchone()
        if not row:
            return None, None
        try:
            in_tanks = int(row["machine_input_tanks"] or 0)
        except Exception:
            in_tanks = 0
        try:
            out_tanks = int(row["machine_output_tanks"] or 0)
        except Exception:
            out_tanks = 0
        return (in_tanks if in_tanks > 0 else None, out_tanks if out_tanks > 0 else None)

    @staticmethod
    def _count_fluid_lines(lines: list[dict]) -> int:
        return sum(1 for line in lines if line.get("kind") == "fluid")

    def _check_tank_limit(self, *, direction: str) -> bool:
        in_tanks, out_tanks = self._get_machine_tank_limits()
        limit = in_tanks if direction == "in" else out_tanks
        if limit is None:
            return True
        lines = self.inputs if direction == "in" else self.outputs
        if self._count_fluid_lines(lines) >= limit:
            messagebox.showerror(
                "No tank available",
                f"This machine only has {limit} fluid {direction} tank(s).",
            )
            return False
        return True

    def _get_used_output_slots(self) -> set[int]:
        used = set()
        for line in self.outputs:
            slot_idx = line.get("output_slot_index")
            if slot_idx is not None:
                used.add(int(slot_idx))
        return used

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

    def _get_or_create_item_confirm(self, key: str, kind: str):
        row = self.app.conn.execute("SELECT id FROM items WHERE key=?", (key,)).fetchone()
        if row:
            return row["id"]

        ok = messagebox.askyesno(
            "Create new item?",
            f"Item not found:\n\n{key}\n\nKind: {kind}\n\nCreate it?"
        )
        if not ok:
            return None

        # display_name defaults to key for now
        self.app.conn.execute(
            "INSERT INTO items(key, display_name, kind, is_base) VALUES(?,?,?,0)",
            (key, key, kind)
        )
        return self.app.conn.execute("SELECT id FROM items WHERE key=?", (key,)).fetchone()["id"]

    def save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Missing name", "Recipe name is required.")
            return

        # Method-specific fields
        method = (self.method_var.get() or "Machine").strip().lower()
        if method == "crafting":
            method_db = "crafting"
            machine = None
            grid_size = (self.grid_var.get() or "4x4").strip()
            station_item_id = self.station_item_id
        else:
            method_db = "machine"
            machine = self.machine_var.get().strip() or None
            grid_size = None
            station_item_id = None
        tier_raw = (self.tier_var.get() or "").strip()
        tier = None if (tier_raw == "" or tier_raw == NONE_TIER_LABEL) else tier_raw
        notes = self.notes_txt.get("1.0", tk.END).strip() or None

        try:
            circuit = self._parse_int_opt(self.circuit_var.get())
            duration_s = self._parse_float_opt(self.duration_seconds_var.get())
            eut = self._parse_int_opt(self.eut_var.get())
        except ValueError as e:
            messagebox.showerror("Invalid number", str(e))
            return

        duration_ticks = None if duration_s is None else int(round(duration_s * TPS))

        if not self.inputs and not self.outputs:
            if not messagebox.askyesno("No lines?", "No inputs/outputs added. Save anyway?"):
                return

        try:
            self.app.conn.execute("BEGIN")

            if method_db == "crafting":
                machine = None
                self.machine_item_id = None

            cur = self.app.conn.execute(
                """INSERT INTO recipes(name, method, machine, machine_item_id, grid_size, station_item_id, circuit, tier, duration_ticks, eu_per_tick, notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (name, method_db, machine, self.machine_item_id, grid_size, station_item_id, circuit, tier, duration_ticks, eut, notes)
            )
            recipe_id = cur.lastrowid

            # Inputs
            for line in self.inputs:
                if line["kind"] == "fluid":
                    self.app.conn.execute(
                        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_liters, chance_percent, output_slot_index) "
                        "VALUES(?,?,?,?,?,?)",
                        (recipe_id, "in", line["item_id"], line["qty_liters"], None, None)
                    )
                else:
                    self.app.conn.execute(
                        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_count, chance_percent, output_slot_index) "
                        "VALUES(?,?,?,?,?,?)",
                        (recipe_id, "in", line["item_id"], line["qty_count"], None, None)
                    )

            # Outputs
            for line in self.outputs:
                if line["kind"] == "fluid":
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
                        )
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
                        )
                    )

            self.app.conn.commit()
        except Exception as e:
            self.app.conn.rollback()
            messagebox.showerror("Save failed", str(e))
            return

        if hasattr(self.app, "refresh_items"):
            self.app.refresh_items()
        if hasattr(self.app, "refresh_recipes"):
            self.app.refresh_recipes()
        self.destroy()
