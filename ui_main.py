#!/usr/bin/env python3
import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from db import (
    connect,
    connect_profile,
    get_setting,
    set_setting,
    DEFAULT_DB_PATH,
    export_db,
    merge_database,
)
from ui_dialogs import AddItemDialog, EditItemDialog, AddRecipeDialog, EditRecipeDialog

ALL_TIERS = [
    "Stone Age",
    "Steam Age",
    "ULV", "LV", "MV", "HV", "EV", "IV",
    "LuV", "ZPM", "UV",
    "UHV", "UEV", "UIV", "UMV", "UXV",
    "OpV", "MAX",
]

SETTINGS_ENABLED_TIERS = "enabled_tiers"
SETTINGS_CRAFT_6X6_UNLOCKED = "crafting_6x6_unlocked"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.geometry("1100x700")

        # Default behavior is "client mode". Creating a file named `.enable_editor`
        # next to this script enables editor capabilities.
        self.editor_enabled = self._detect_editor_enabled()

        self.db_path: Path = DEFAULT_DB_PATH
        self.conn = self._open_content_db(self.db_path)

        # Per-user profile DB (stores tiers/unlocks/etc). Kept separate from content
        # so players can keep progress across content DB updates.
        self.profile_db_path: Path = self._profile_path_for_content(self.db_path)
        self.profile_conn = connect_profile(self.profile_db_path)

        # Backward-compat: older versions stored tiers/unlocks in the content DB.
        # If we detect those and the profile is empty, copy them over.
        self._migrate_profile_settings_if_needed()

        self.status = tk.StringVar(value="Ready")

        self._build_menu()
        self._update_title()

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        self._build_items_tab()
        self._build_recipes_tab()
        self._build_inventory_tab()
        self._build_tiers_tab()

        statusbar = ttk.Label(self, textvariable=self.status, anchor="w")
        statusbar.pack(fill="x")

        self.refresh_items()
        self.refresh_recipes()
        self._tiers_load_from_db()

    # ---------- Mode detection ----------
    def _detect_editor_enabled(self) -> bool:
        try:
            here = Path(__file__).resolve().parent
            return (here / ".enable_editor").exists()
        except Exception:
            return False

    def _profile_path_for_content(self, content_path: Path) -> Path:
        try:
            content_path = Path(content_path)
            # Keep the profile next to the content DB for portability.
            stem = content_path.stem or "gtnh"
            return content_path.with_name(f"{stem}.profile.db")
        except Exception:
            return Path("gtnh.profile.db")

    def _open_content_db(self, path: Path):
        """Open content DB respecting client/editor mode.

        In client mode, we open the content DB read-only. If the file does not
        exist yet, we fall back to an empty in-memory DB and prompt the user to
        open a content DB.
        """
        try:
            return connect(path, read_only=(not self.editor_enabled))
        except Exception:
            # Client-mode bootstrap: allow the app to start even without a DB.
            # Users can File -> Open DB… to select the shipped content DB.
            return connect(":memory:")

    def _migrate_profile_settings_if_needed(self) -> None:
        """One-time migration from content DB -> profile DB."""
        try:
            for k in (SETTINGS_ENABLED_TIERS, SETTINGS_CRAFT_6X6_UNLOCKED):
                prof_v = get_setting(self.profile_conn, k, None)
                if prof_v is not None and str(prof_v).strip() != "":
                    continue
                src_v = get_setting(self.conn, k, None)
                if src_v is None or str(src_v).strip() == "":
                    continue
                set_setting(self.profile_conn, k, str(src_v))
        except Exception:
            # Non-fatal: worst case users re-check tiers once.
            pass

    # ---------- Menu / DB handling ----------
    def _build_menu(self):
        menubar = tk.Menu(self)

        filem = tk.Menu(menubar, tearoff=0)
        filem.add_command(label="Open DB…", command=self.menu_open_db)
        if self.editor_enabled:
            filem.add_command(label="New DB…", command=self.menu_new_db)
            filem.add_separator()
            filem.add_command(label="Export Content DB…", command=self.menu_export_content_db)
            filem.add_command(label="Export Profile DB…", command=self.menu_export_profile_db)
            filem.add_command(label="Merge DB…", command=self.menu_merge_db)
        else:
            filem.add_separator()
            filem.add_command(label="Export Content DB…", command=self.menu_export_content_db)
            filem.add_command(label="Export Profile DB…", command=self.menu_export_profile_db)
        filem.add_separator()
        filem.add_command(label="Quit", command=self.destroy)

        menubar.add_cascade(label="File", menu=filem)
        self.config(menu=menubar)

    def _update_title(self):
        try:
            name = self.db_path.name
        except Exception:
            name = "(unknown)"
        mode = "Editor" if self.editor_enabled else "Client"
        self.title(f"GTNH Recipe DB — {mode} — {name}")

    def _switch_db(self, new_path: Path):
        """Close current DB connection and open a new one."""
        try:
            if getattr(self, "conn", None) is not None:
                self.conn.commit()
                self.conn.close()
        except Exception:
            pass

        try:
            if getattr(self, "profile_conn", None) is not None:
                self.profile_conn.commit()
                self.profile_conn.close()
        except Exception:
            pass

        self.db_path = Path(new_path)
        self.conn = self._open_content_db(self.db_path)

        self.profile_db_path = self._profile_path_for_content(self.db_path)
        self.profile_conn = connect_profile(self.profile_db_path)
        self._migrate_profile_settings_if_needed()
        self._update_title()

        # Reload UI from the new DB
        self.refresh_items()
        self.refresh_recipes()
        self._tiers_load_from_db()
        self._item_details_set("")
        self._recipe_details_set("")

    def menu_open_db(self):
        path = filedialog.askopenfilename(
            title="Open GTNH DB",
            filetypes=[("SQLite DB", "*.db"), ("All files", "*")],
        )
        if not path:
            return
        self._switch_db(Path(path))
        self.status.set(f"Opened DB: {Path(path).name}")

    def menu_new_db(self):
        if not self.editor_enabled:
            messagebox.showinfo("Editor locked", "This copy is running in client mode.\n\nTo enable editing, create a file named '.enable_editor' next to the app.")
            return
        path = filedialog.asksaveasfilename(
            title="Create / Choose DB",
            defaultextension=".db",
            filetypes=[("SQLite DB", "*.db"), ("All files", "*")],
            initialfile="gtnh.db",
        )
        if not path:
            return
        self._switch_db(Path(path))
        self.status.set(f"Using DB: {Path(path).name}")

    def menu_export_content_db(self):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default = f"gtnh_export_{ts}.db"
        path = filedialog.asksaveasfilename(
            title="Export Content DB",
            defaultextension=".db",
            filetypes=[("SQLite DB", "*.db"), ("All files", "*")],
            initialfile=default,
        )
        if not path:
            return
        try:
            export_db(self.conn, Path(path))
        except Exception as e:
            messagebox.showerror("Export failed", f"Could not export DB.\n\nDetails: {e}")
            return
        self.status.set(f"Exported content DB to: {Path(path).name}")
        messagebox.showinfo("Export complete", f"Exported content DB to:\n\n{path}")

    def menu_export_profile_db(self):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default = f"gtnh_profile_export_{ts}.db"
        path = filedialog.asksaveasfilename(
            title="Export Profile DB",
            defaultextension=".db",
            filetypes=[("SQLite DB", "*.db"), ("All files", "*")],
            initialfile=default,
        )
        if not path:
            return
        try:
            export_db(self.profile_conn, Path(path))
        except Exception as e:
            messagebox.showerror("Export failed", f"Could not export profile DB.\n\nDetails: {e}")
            return
        self.status.set(f"Exported profile DB to: {Path(path).name}")
        messagebox.showinfo("Export complete", f"Exported profile DB to:\n\n{path}")

    def menu_merge_db(self):
        if not self.editor_enabled:
            messagebox.showinfo("Editor locked", "Merging is only available in editor mode.")
            return
        path = filedialog.askopenfilename(
            title="Merge another DB into this one",
            filetypes=[("SQLite DB", "*.db"), ("All files", "*")],
        )
        if not path:
            return

        ok = messagebox.askyesno(
            "Merge DB?",
            "This will import Items, Recipes, and Recipe Lines from another DB into your current DB.\n\n"
            "It will NOT delete anything.\n"
            "If recipe names collide, imported recipes get a suffix like '(import 2)'.\n\n"
            "Continue?",
        )
        if not ok:
            return

        try:
            stats = merge_database(self.conn, Path(path))
        except Exception as e:
            messagebox.showerror("Merge failed", f"Could not merge DB.\n\nDetails: {e}")
            return

        self.refresh_items()
        self.refresh_recipes()

        msg = (
            f"Merge complete from {Path(path).name}:\n\n"
            f"Item kinds added: {stats.get('kinds_added', 0)}\n"
            f"Items added: {stats.get('items_added', 0)}\n"
            f"Items updated (filled blanks): {stats.get('items_updated', 0)}\n"
            f"Recipes added: {stats.get('recipes_added', 0)}\n"
            f"Recipe lines added: {stats.get('lines_added', 0)}"
        )
        self.status.set("Merge complete")
        messagebox.showinfo("Merge complete", msg)

    # ---------- Tiers ----------
    def get_enabled_tiers(self):
        # Stored per-player in the profile DB.
        raw = get_setting(self.profile_conn, SETTINGS_ENABLED_TIERS, "")
        if not raw:
            return ["Stone Age"]  # default on first run
        tiers = [t.strip() for t in raw.split(",") if t.strip()]
        return tiers if tiers else ["Stone Age"]

    def set_enabled_tiers(self, tiers: list[str]):
        set_setting(self.profile_conn, SETTINGS_ENABLED_TIERS, ",".join(tiers))

    # ---------- Crafting grid unlocks ----------
    def is_crafting_6x6_unlocked(self) -> bool:
        raw = (get_setting(self.profile_conn, SETTINGS_CRAFT_6X6_UNLOCKED, "0") or "0").strip()
        return raw == "1"

    def set_crafting_6x6_unlocked(self, unlocked: bool) -> None:
        set_setting(self.profile_conn, SETTINGS_CRAFT_6X6_UNLOCKED, "1" if unlocked else "0")

    # ---------- Items tab ----------
    def _build_items_tab(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="Items")

        left = ttk.Frame(tab, padding=8)
        left.pack(side="left", fill="y")

        right = ttk.Frame(tab, padding=8)
        right.pack(side="right", fill="both", expand=True)

        self.item_list = tk.Listbox(left, width=40)
        self.item_list.pack(fill="y", expand=True)
        self.item_list.bind("<<ListboxSelect>>", self.on_item_select)
        if self.editor_enabled:
            self.item_list.bind("<Double-Button-1>", lambda _e: self.open_edit_item_dialog())

        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(8, 0))
        self.btn_add_item = ttk.Button(btns, text="Add Item", command=self.open_add_item_dialog)
        self.btn_edit_item = ttk.Button(btns, text="Edit Item", command=self.open_edit_item_dialog)
        self.btn_del_item = ttk.Button(btns, text="Delete Item", command=self.delete_selected_item)
        self.btn_add_item.pack(side="left")
        self.btn_edit_item.pack(side="left", padx=6)
        self.btn_del_item.pack(side="left")
        if not self.editor_enabled:
            self.btn_add_item.configure(state="disabled")
            self.btn_edit_item.configure(state="disabled")
            self.btn_del_item.configure(state="disabled")

        self.item_details = tk.Text(right, height=10, wrap="word")
        self.item_details.pack(fill="both", expand=True)
        self.item_details.configure(state="disabled")

        self.items = []

    def refresh_items(self):
        self.items = self.conn.execute(
            "SELECT i.id, i.key, COALESCE(i.display_name, i.key) AS name, i.kind, i.is_base, i.is_machine, i.machine_tier, i.machine_input_slots, i.machine_output_slots, "
            "       k.name AS item_kind_name "
            "FROM items i "
            "LEFT JOIN item_kinds k ON k.id = i.item_kind_id "
            "ORDER BY name"
        ).fetchall()
        self.item_list.delete(0, tk.END)
        for it in self.items:
            self.item_list.insert(tk.END, it["name"])
        if hasattr(self, "inventory_list"):
            self.inventory_list.delete(0, tk.END)
            for it in self.items:
                self.inventory_list.insert(tk.END, it["name"])

    def on_item_select(self, _evt=None):
        sel = self.item_list.curselection()
        if not sel:
            return
        it = self.items[sel[0]]
        txt = (
            f"Name: {it['name']}\n"
            f"Kind: {it['kind']}\n"
            f"Item Kind: {it['item_kind_name'] or ''}\n"
            f"Base: {'Yes' if it['is_base'] else 'No'}\n"
        )
        is_machine_kind = ((it['item_kind_name'] or '').strip().lower() == 'machine') or bool(it['is_machine'])
        if is_machine_kind:
            txt += f"Machine Tier: {it['machine_tier'] or ''}\n"
            mis = it["machine_input_slots"]
            try:
                mis_i = int(mis) if mis is not None else 1
            except Exception:
                mis_i = 1
            txt += f"Input Slots: {mis_i}\n"
            mos = it["machine_output_slots"]
            try:
                mos_i = int(mos) if mos is not None else 1
            except Exception:
                mos_i = 1
            txt += f"Output Slots: {mos_i}\n"
        self._item_details_set(txt)

    def _item_details_set(self, txt: str):
        self.item_details.configure(state="normal")
        self.item_details.delete("1.0", tk.END)
        self.item_details.insert("1.0", txt)
        self.item_details.configure(state="disabled")

    def open_add_item_dialog(self):
        if not self.editor_enabled:
            messagebox.showinfo(
                "Editor locked",
                "This copy is running in client mode.\n\nTo enable editing, create a file named '.enable_editor' next to the app.",
            )
            return
        dlg = AddItemDialog(self)
        self.wait_window(dlg)
        self.refresh_items()

    def open_edit_item_dialog(self):
        if not self.editor_enabled:
            messagebox.showinfo("Editor locked", "Editing Items is only available in editor mode.")
            return
        sel = self.item_list.curselection()
        if not sel:
            messagebox.showinfo("Select an item", "Click an item first.")
            return
        item_id = self.items[sel[0]]["id"]
        dlg = EditItemDialog(self, item_id)
        self.wait_window(dlg)
        self.refresh_items()

    def delete_selected_item(self):
        if not self.editor_enabled:
            messagebox.showinfo("Editor locked", "Deleting Items is only available in editor mode.")
            return
        sel = self.item_list.curselection()
        if not sel:
            messagebox.showinfo("Select an item", "Click an item first.")
            return
        it = self.items[sel[0]]
        ok = messagebox.askyesno("Delete item?", f"Delete item:\n\n{it['name']}")
        if not ok:
            return
        try:
            self.conn.execute("DELETE FROM items WHERE id=?", (it["id"],))
            self.conn.commit()
        except Exception as e:
            messagebox.showerror(
                "Cannot delete",
                "This item is referenced by a recipe.\nRemove it from recipes first.\n\n"
                f"Details: {e}",
            )
            return
        self.refresh_items()
        self._item_details_set("")
        self.status.set(f"Deleted item: {it['name']}")

    # ---------- Recipes tab ----------
    def _build_recipes_tab(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="Recipes")

        left = ttk.Frame(tab, padding=8)
        left.pack(side="left", fill="y")

        right = ttk.Frame(tab, padding=8)
        right.pack(side="right", fill="both", expand=True)

        self.recipe_list = tk.Listbox(left, width=40)
        self.recipe_list.pack(fill="y", expand=True)
        self.recipe_list.bind("<<ListboxSelect>>", self.on_recipe_select)
        if self.editor_enabled:
            self.recipe_list.bind("<Double-Button-1>", lambda _e: self.open_edit_recipe_dialog())

        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(8, 0))
        self.btn_add_recipe = ttk.Button(btns, text="Add Recipe", command=self.open_add_recipe_dialog)
        self.btn_edit_recipe = ttk.Button(btns, text="Edit Recipe", command=self.open_edit_recipe_dialog)
        self.btn_del_recipe = ttk.Button(btns, text="Delete Recipe", command=self.delete_selected_recipe)
        self.btn_add_recipe.pack(side="left")
        self.btn_edit_recipe.pack(side="left", padx=6)
        self.btn_del_recipe.pack(side="left")
        if not self.editor_enabled:
            self.btn_add_recipe.configure(state="disabled")
            self.btn_edit_recipe.configure(state="disabled")
            self.btn_del_recipe.configure(state="disabled")

        self.recipe_details = tk.Text(right, wrap="word")
        self.recipe_details.pack(fill="both", expand=True)
        self.recipe_details.configure(state="disabled")

        self.recipes = []

    def refresh_recipes(self):
        # Filter recipes to enabled tiers, but always show recipes with no tier set.
        enabled = self.get_enabled_tiers()
        placeholders = ",".join(["?"] * len(enabled))
        sql = (
            "SELECT id, name, method, machine, machine_item_id, grid_size, station_item_id, tier, circuit, duration_ticks, eu_per_tick "
            "FROM recipes "
            f"WHERE (tier IS NULL OR TRIM(tier)='' OR tier IN ({placeholders})) "
            "ORDER BY name"
        )
        self.recipes = self.conn.execute(sql, tuple(enabled)).fetchall()
        self.recipe_list.delete(0, tk.END)
        for r in self.recipes:
            self.recipe_list.insert(tk.END, r["name"])

    def on_recipe_select(self, _evt=None):
        sel = self.recipe_list.curselection()
        if not sel:
            return
        r = self.recipes[sel[0]]

        lines = self.conn.execute(
            """
            SELECT rl.direction, COALESCE(i.display_name, i.key) AS name, rl.qty_count, rl.qty_liters, rl.chance_percent, rl.output_slot_index
            FROM recipe_lines rl
            JOIN items i ON i.id = rl.item_id
            WHERE rl.recipe_id=?
            ORDER BY rl.id
            """,
            (r["id"],),
        ).fetchall()

        ins = []
        outs = []
        for x in lines:
            if x["qty_liters"] is not None:
                s = f"{x['name']} × {x['qty_liters']} L"
            else:
                s = f"{x['name']} × {x['qty_count']}"

            # Chance outputs (e.g., macerator byproducts)
            if x["direction"] == "out":
                slot_idx = x["output_slot_index"]
                if slot_idx:
                    s = f"{s} (Slot {slot_idx})"
                ch = x["chance_percent"]
                if ch is not None:
                    try:
                        ch_f = float(ch)
                    except Exception:
                        ch_f = 100.0
                    if ch_f < 99.999:
                        s = f"{s} ({ch_f:g}%)"

            (ins if x["direction"] == "in" else outs).append(s)

        duration_s = None
        if r["duration_ticks"] is not None:
            duration_s = int(r["duration_ticks"] / 20)

        # Method display
        method = (r["method"] or "machine").strip().lower()
        method_label = "Crafting" if method == "crafting" else "Machine"

        station_name = ""
        if method == "crafting" and r["station_item_id"] is not None:
            row = self.conn.execute(
                "SELECT COALESCE(display_name, key) AS name FROM items WHERE id=?",
                (r["station_item_id"],),
            ).fetchone()
            station_name = row["name"] if row else ""

        method_lines = [f"Method: {method_label}"]
        if method == "crafting":
            method_lines.append(f"Grid: {r['grid_size'] or ''}")
            method_lines.append(f"Station: {station_name}")
        else:
            mline = f"Machine: {r['machine'] or ''}"
            if r.get("machine_item_id") is not None if isinstance(r, dict) else r["machine_item_id"] is not None:
                mid = r.get("machine_item_id") if isinstance(r, dict) else r["machine_item_id"]
                mrow = self.conn.execute(
                    "SELECT machine_output_slots FROM items WHERE id=?",
                    (mid,),
                ).fetchone()
                if mrow:
                    try:
                        mos = int(mrow["machine_output_slots"] or 1)
                    except Exception:
                        mos = 1
                    mline = f"{mline} (output slots: {mos})"
            method_lines.append(mline)

        txt = (
            f"Name: {r['name']}\n"
            + "\n".join(method_lines)
            + "\n"
            f"Tier: {r['tier'] or ''}\n"
            f"Circuit: {'' if r['circuit'] is None else r['circuit']}\n"
            f"Duration: {'' if duration_s is None else str(duration_s)+'s'}\n"
            f"EU/t: {'' if r['eu_per_tick'] is None else r['eu_per_tick']}\n\n"
            f"Inputs:\n  "
            + ("\n  ".join(ins) if ins else "(none)")
            + "\n\n"
            f"Outputs:\n  "
            + ("\n  ".join(outs) if outs else "(none)")
            + "\n"
        )
        self._recipe_details_set(txt)

    def _recipe_details_set(self, txt: str):
        self.recipe_details.configure(state="normal")
        self.recipe_details.delete("1.0", tk.END)
        self.recipe_details.insert("1.0", txt)
        self.recipe_details.configure(state="disabled")

    def open_add_recipe_dialog(self):
        if not self.editor_enabled:
            messagebox.showinfo("Editor locked", "Adding Recipes is only available in editor mode.")
            return
        dlg = AddRecipeDialog(self)
        self.wait_window(dlg)
        self.refresh_recipes()

    def open_edit_recipe_dialog(self):
        if not self.editor_enabled:
            messagebox.showinfo("Editor locked", "Editing Recipes is only available in editor mode.")
            return
        sel = self.recipe_list.curselection()
        if not sel:
            messagebox.showinfo("Select a recipe", "Click a recipe first.")
            return
        recipe_id = self.recipes[sel[0]]["id"]
        dlg = EditRecipeDialog(self, recipe_id)
        self.wait_window(dlg)
        self.refresh_recipes()

    def delete_selected_recipe(self):
        if not self.editor_enabled:
            messagebox.showinfo("Editor locked", "Deleting Recipes is only available in editor mode.")
            return
        sel = self.recipe_list.curselection()
        if not sel:
            messagebox.showinfo("Select a recipe", "Click a recipe first.")
            return
        r = self.recipes[sel[0]]
        ok = messagebox.askyesno("Delete recipe?", f"Delete recipe:\n\n{r['name']}")
        if not ok:
            return
        self.conn.execute("DELETE FROM recipes WHERE id=?", (r["id"],))
        self.conn.commit()
        self.refresh_recipes()
        self._recipe_details_set("")
        self.status.set(f"Deleted recipe: {r['name']}")

    # ---------- Inventory tab ----------
    def _build_inventory_tab(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="Inventory")

        ttk.Label(tab, text="Track what you currently have in storage.").pack(anchor="w")

        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True, pady=10)

        left = ttk.Frame(body)
        left.pack(side="left", fill="y")

        right = ttk.Frame(body)
        right.pack(side="right", fill="both", expand=True, padx=(12, 0))

        self.inventory_list = tk.Listbox(left, width=40)
        self.inventory_list.pack(fill="y", expand=True)
        self.inventory_list.bind("<<ListboxSelect>>", self.on_inventory_select)

        self.inventory_item_name = tk.StringVar(value="")
        ttk.Label(right, textvariable=self.inventory_item_name, font=("TkDefaultFont", 11, "bold")).pack(
            anchor="w",
            pady=(0, 10),
        )

        qty_row = ttk.Frame(right)
        qty_row.pack(anchor="w")
        ttk.Label(qty_row, text="Quantity:").pack(side="left")
        self.inventory_qty_var = tk.StringVar(value="")
        self.inventory_qty_entry = ttk.Entry(qty_row, textvariable=self.inventory_qty_var, width=14)
        self.inventory_qty_entry.pack(side="left", padx=(6, 6))
        self.inventory_unit_var = tk.StringVar(value="")
        ttk.Label(qty_row, textvariable=self.inventory_unit_var).pack(side="left")

        btns = ttk.Frame(right)
        btns.pack(anchor="w", pady=(10, 0))
        ttk.Button(btns, text="Save", command=self.save_inventory_item).pack(side="left")
        ttk.Button(btns, text="Clear", command=self.clear_inventory_item).pack(side="left", padx=(6, 0))

        ttk.Label(
            right,
            text="Tip: items use counts; fluids use liters (L).",
            foreground="#666",
        ).pack(anchor="w", pady=(12, 0))

    def _inventory_selected_item(self):
        sel = self.inventory_list.curselection()
        if not sel:
            return None
        if not self.items:
            return None
        return self.items[sel[0]]

    def _inventory_unit_for_item(self, item) -> str:
        kind = (item["kind"] or "").strip().lower()
        return "L" if kind == "fluid" else "count"

    def on_inventory_select(self, _evt=None):
        item = self._inventory_selected_item()
        if not item:
            return
        self.inventory_item_name.set(item["name"])
        unit = self._inventory_unit_for_item(item)
        self.inventory_unit_var.set(unit)

        row = self.profile_conn.execute(
            "SELECT qty_count, qty_liters FROM inventory WHERE item_id=?",
            (item["id"],),
        ).fetchone()
        if unit == "L":
            qty = row["qty_liters"] if row else None
        else:
            qty = row["qty_count"] if row else None
        self.inventory_qty_var.set("" if qty is None else self._format_inventory_qty(qty))

    def _format_inventory_qty(self, qty: float | int) -> str:
        try:
            qty_f = float(qty)
        except (TypeError, ValueError):
            return ""
        if qty_f.is_integer():
            return str(int(qty_f))
        return str(qty_f)

    def save_inventory_item(self):
        item = self._inventory_selected_item()
        if not item:
            messagebox.showinfo("Select an item", "Click an item first.")
            return

        raw = self.inventory_qty_var.get().strip()
        if raw == "":
            self.profile_conn.execute("DELETE FROM inventory WHERE item_id=?", (item["id"],))
            self.profile_conn.commit()
            self.status.set(f"Cleared inventory for: {item['name']}")
            return

        try:
            qty = float(raw)
        except ValueError:
            messagebox.showerror("Invalid quantity", "Enter a valid number.")
            return

        if qty.is_integer():
            qty = int(qty)

        unit = self._inventory_unit_for_item(item)
        qty_count = qty if unit == "count" else None
        qty_liters = qty if unit == "L" else None
        self.profile_conn.execute(
            "INSERT INTO inventory(item_id, qty_count, qty_liters) VALUES(?, ?, ?) "
            "ON CONFLICT(item_id) DO UPDATE SET qty_count=excluded.qty_count, qty_liters=excluded.qty_liters",
            (item["id"], qty_count, qty_liters),
        )
        self.profile_conn.commit()
        self.status.set(f"Saved inventory for: {item['name']}")

    def clear_inventory_item(self):
        self.inventory_qty_var.set("")
        self.save_inventory_item()

    # ---------- Tiers tab ----------
    def _build_tiers_tab(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="Tiers")

        ttk.Label(tab, text="Select tiers you currently have access to.").pack(anchor="w")

        self.tier_vars = {}
        grid = ttk.Frame(tab)
        grid.pack(fill="x", pady=10)

        # 3 columns grid
        cols = 3
        for i, t in enumerate(ALL_TIERS):
            var = tk.BooleanVar(value=False)
            self.tier_vars[t] = var
            r = i // cols
            c = i % cols
            ttk.Checkbutton(
                grid,
                text=t,
                variable=var,
                command=lambda tier=t: self._on_tier_toggle(tier),
            ).grid(row=r, column=c, sticky="w", padx=8, pady=4)

        btns = ttk.Frame(tab)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Save", command=self._tiers_save_to_db).pack(side="left")

        # Crafting grid unlocks
        unlocks = ttk.LabelFrame(tab, text="Crafting", padding=10)
        unlocks.pack(fill="x", pady=(12, 0))
        self.unlocked_6x6_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            unlocks,
            text="6x6 Crafting unlocked (once you've made a crafting table with a crafting grid)",
            variable=self.unlocked_6x6_var,
        ).pack(anchor="w")

        ttk.Label(
            tab,
            text="Note: this controls dropdown tiers and filters the Recipes list (no planner logic yet).",
            foreground="#666",
        ).pack(anchor="w", pady=(10, 0))

    def _tiers_load_from_db(self):
        enabled = set(self.get_enabled_tiers())
        for t, var in self.tier_vars.items():
            var.set(t in enabled)

        if hasattr(self, "unlocked_6x6_var"):
            self.unlocked_6x6_var.set(self.is_crafting_6x6_unlocked())

    def _on_tier_toggle(self, tier: str) -> None:
        var = self.tier_vars.get(tier)
        if not var:
            return

        try:
            tier_index = ALL_TIERS.index(tier)
        except ValueError:
            return

        if var.get():
            for lower_tier in ALL_TIERS[: tier_index + 1]:
                lower_var = self.tier_vars.get(lower_tier)
                if lower_var and not lower_var.get():
                    lower_var.set(True)

            if "Steam Age" in ALL_TIERS[: tier_index + 1]:
                if hasattr(self, "unlocked_6x6_var") and not self.unlocked_6x6_var.get():
                    self.unlocked_6x6_var.set(True)
        else:
            for higher_tier in ALL_TIERS[tier_index + 1 :]:
                higher_var = self.tier_vars.get(higher_tier)
                if higher_var and higher_var.get():
                    higher_var.set(False)

            steam_var = self.tier_vars.get("Steam Age")
            if steam_var is not None and not steam_var.get():
                if hasattr(self, "unlocked_6x6_var") and self.unlocked_6x6_var.get():
                    self.unlocked_6x6_var.set(False)

    def _tiers_save_to_db(self):
        enabled = [t for t, var in self.tier_vars.items() if var.get()]
        if not enabled:
            messagebox.showerror("Pick at least one", "Enable at least one tier.")
            return
        self.set_enabled_tiers(enabled)

        if hasattr(self, "unlocked_6x6_var"):
            self.set_crafting_6x6_unlocked(bool(self.unlocked_6x6_var.get()))

        self.refresh_recipes()
        self._recipe_details_set("")
        self.status.set(f"Saved tiers: {', '.join(enabled)}")
