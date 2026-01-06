#!/usr/bin/env python3
import datetime
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from db import connect, connect_profile, get_setting, set_setting, DEFAULT_DB_PATH, export_db, merge_database
from ui_constants import SETTINGS_CRAFT_6X6_UNLOCKED, SETTINGS_ENABLED_TIERS
from ui_tabs.inventory_tab import InventoryTab
from ui_tabs.items_tab import ItemsTab
from ui_tabs.recipes_tab import RecipesTab
from ui_tabs.tiers_tab import TiersTab


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

        self.tab_registry = {
            "items": {"label": "Items", "class": ItemsTab, "attr": "items_tab"},
            "recipes": {"label": "Recipes", "class": RecipesTab, "attr": "recipes_tab"},
            "inventory": {"label": "Inventory", "class": InventoryTab, "attr": "inventory_tab"},
            "tiers": {"label": "Tiers", "class": TiersTab, "attr": "tiers_tab"},
        }
        self.tab_order, self.enabled_tabs = self._load_ui_config()
        self.tab_vars: dict[str, tk.BooleanVar] = {}

        self._build_menu()
        self._update_title()

        self.items: list = []
        self.recipes: list = []

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        self._rebuild_tabs()

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

    # ---------- Tab configuration ----------
    def _config_path(self) -> Path:
        try:
            here = Path(__file__).resolve().parent
            return here / "ui_config.json"
        except Exception:
            return Path("ui_config.json")

    def _load_ui_config(self) -> tuple[list[str], list[str]]:
        default_order = list(self.tab_registry.keys())
        default_enabled = list(default_order)
        path = self._config_path()
        try:
            raw = json.loads(path.read_text())
        except Exception:
            return default_order, default_enabled

        order = raw.get("tab_order", default_order)
        enabled = raw.get("enabled_tabs", default_enabled)
        order = [tid for tid in order if tid in self.tab_registry]
        for tid in default_order:
            if tid not in order:
                order.append(tid)
        enabled = [tid for tid in enabled if tid in self.tab_registry]
        if not enabled:
            enabled = list(default_enabled)
        enabled_ordered = [tid for tid in order if tid in enabled]
        return order, enabled_ordered

    def _save_ui_config(self) -> None:
        path = self._config_path()
        data = {"enabled_tabs": self.enabled_tabs, "tab_order": self.tab_order}
        try:
            path.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            messagebox.showwarning("Config save failed", f"Could not save tab preferences.\n\nDetails: {exc}")

    def _rebuild_tabs(self) -> None:
        for meta in self.tab_registry.values():
            attr = meta["attr"]
            tab = getattr(self, attr, None)
            if tab is not None:
                try:
                    self.nb.forget(tab)
                except Exception:
                    pass
                tab.destroy()
            setattr(self, attr, None)

        for tab_id in self.tab_order:
            if tab_id not in self.enabled_tabs:
                continue
            meta = self.tab_registry[tab_id]
            tab = meta["class"](self.nb, self)
            setattr(self, meta["attr"], tab)

    def _toggle_tab(self, tab_id: str) -> None:
        enabled = set(self.enabled_tabs)
        if self.tab_vars[tab_id].get():
            enabled.add(tab_id)
        else:
            if tab_id in enabled and len(enabled) == 1:
                messagebox.showinfo("Tabs", "At least one tab must remain enabled.")
                self.tab_vars[tab_id].set(True)
                return
            enabled.discard(tab_id)

        self.enabled_tabs = [tid for tid in self.tab_order if tid in enabled]
        self._save_ui_config()
        self._rebuild_tabs()
        self.refresh_items()
        self.refresh_recipes()
        self._tiers_load_from_db()

    def _open_reorder_tabs_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Reorder Tabs")
        dialog.transient(self)
        dialog.grab_set()

        ttk.Label(
            dialog,
            text="Set the order number for each tab (1 = first).",
        ).pack(anchor="w", padx=10, pady=(10, 0))

        body = ttk.Frame(dialog, padding=10)
        body.pack(fill="both", expand=True)

        rows: list[tuple[str, tk.StringVar]] = []
        for idx, tab_id in enumerate(self.tab_order, start=1):
            label = self.tab_registry[tab_id]["label"]
            ttk.Label(body, text=label).grid(row=idx, column=0, sticky="w", padx=(0, 12), pady=4)
            var = tk.StringVar(value=str(idx))
            spin = ttk.Spinbox(body, from_=1, to=len(self.tab_order), textvariable=var, width=6)
            spin.grid(row=idx, column=1, sticky="w", pady=4)
            rows.append((tab_id, var))

        btns = ttk.Frame(dialog, padding=(10, 0, 10, 10))
        btns.pack(fill="x")

        def apply_changes() -> None:
            orders: dict[str, int] = {}
            for tab_id, var in rows:
                try:
                    order_val = int(var.get())
                except ValueError:
                    messagebox.showerror("Invalid order", "Each tab must have a numeric order.")
                    return
                if order_val < 1 or order_val > len(self.tab_order):
                    messagebox.showerror("Invalid order", "Order values must be within the allowed range.")
                    return
                orders[tab_id] = order_val

            if len(set(orders.values())) != len(self.tab_order):
                messagebox.showerror("Invalid order", "Order values must be unique.")
                return

            self.tab_order = [tid for tid, _ in sorted(orders.items(), key=lambda item: item[1])]
            enabled_set = set(self.enabled_tabs)
            self.enabled_tabs = [tid for tid in self.tab_order if tid in enabled_set]
            self._save_ui_config()
            self._rebuild_tabs()
            self.refresh_items()
            self.refresh_recipes()
            self._tiers_load_from_db()
            dialog.destroy()

        ttk.Button(btns, text="Apply", command=apply_changes).pack(side="right")
        ttk.Button(btns, text="Cancel", command=dialog.destroy).pack(side="right", padx=(0, 8))

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

        tabs_menu = tk.Menu(menubar, tearoff=0)
        for tab_id, meta in self.tab_registry.items():
            var = tk.BooleanVar(value=tab_id in self.enabled_tabs)
            self.tab_vars[tab_id] = var
            tabs_menu.add_checkbutton(
                label=meta["label"],
                variable=var,
                command=lambda tid=tab_id: self._toggle_tab(tid),
            )
        tabs_menu.add_separator()
        tabs_menu.add_command(label="Reorder Tabs…", command=self._open_reorder_tabs_dialog)
        menubar.add_cascade(label="Tabs", menu=tabs_menu)

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
        if getattr(self, "items_tab", None) is not None:
            self.items_tab._item_details_set("")
        if getattr(self, "recipes_tab", None) is not None:
            self.recipes_tab._recipe_details_set("")

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

    # ---------- Tab delegates ----------
    def refresh_items(self) -> None:
        self.items = self.conn.execute(
            "SELECT i.id, i.key, COALESCE(i.display_name, i.key) AS name, i.kind, i.is_base, i.is_machine, i.machine_tier, "
            "       i.machine_input_slots, i.machine_output_slots, i.machine_storage_slots, i.machine_power_slots, "
            "       i.machine_circuit_slots, i.machine_input_tanks, i.machine_input_tank_capacity_l, "
            "       i.machine_output_tanks, i.machine_output_tank_capacity_l, "
            "       k.name AS item_kind_name "
            "FROM items i "
            "LEFT JOIN item_kinds k ON k.id = i.item_kind_id "
            "ORDER BY name"
        ).fetchall()
        if getattr(self, "items_tab", None) is not None:
            self.items_tab.render_items(self.items)
        if getattr(self, "inventory_tab", None) is not None:
            self.inventory_tab.render_items(self.items)

    def refresh_recipes(self) -> None:
        if getattr(self, "recipes_tab", None) is not None:
            self.recipes_tab.refresh_recipes()

    def _tiers_load_from_db(self) -> None:
        if getattr(self, "tiers_tab", None) is not None:
            self.tiers_tab.load_from_db()
