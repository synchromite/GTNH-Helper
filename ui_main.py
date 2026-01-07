#!/usr/bin/env python3
import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from services.db import DEFAULT_DB_PATH
from services.db_lifecycle import DbLifecycle
from services.items import fetch_items
from services.tab_config import apply_tab_reorder, config_path, load_tab_config, save_tab_config
from ui_tabs.inventory_tab import InventoryTab
from ui_tabs.items_tab import ItemsTab
from ui_tabs.planner_tab import PlannerTab
from ui_tabs.recipes_tab import RecipesTab
from ui_tabs.tiers_tab import TiersTab


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.geometry("1100x700")

        # Default behavior is "client mode". Creating a file named `.enable_editor`
        # next to this script enables editor capabilities.
        self.editor_enabled = self._detect_editor_enabled()

        self.db = DbLifecycle(editor_enabled=self.editor_enabled, db_path=DEFAULT_DB_PATH)
        self._sync_db_handles()

        self.status = tk.StringVar(value="Ready")
        self.planner_state: dict[str, object] = {}

        self.tab_registry = {
            "items": {"label": "Items", "class": ItemsTab, "attr": "items_tab"},
            "recipes": {"label": "Recipes", "class": RecipesTab, "attr": "recipes_tab"},
            "inventory": {"label": "Inventory", "class": InventoryTab, "attr": "inventory_tab"},
            "planner": {"label": "Planner", "class": PlannerTab, "attr": "planner_tab"},
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

    def _sync_db_handles(self) -> None:
        self.db_path = self.db.db_path
        self.profile_db_path = self.db.profile_db_path
        self.conn = self.db.conn
        self.profile_conn = self.db.profile_conn

    # ---------- Tab configuration ----------
    def _config_path(self) -> Path:
        try:
            here = Path(__file__).resolve().parent
            return config_path(here)
        except Exception:
            return config_path(Path("."))

    def _load_ui_config(self) -> tuple[list[str], list[str]]:
        path = self._config_path()
        config = load_tab_config(path, self.tab_registry.keys())
        return config.order, config.enabled

    def _save_ui_config(self) -> None:
        path = self._config_path()
        try:
            save_tab_config(path, self.tab_order, self.enabled_tabs)
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
                orders[tab_id] = order_val

            try:
                config = apply_tab_reorder(self.tab_order, self.enabled_tabs, orders)
            except ValueError as exc:
                messagebox.showerror("Invalid order", str(exc))
                return

            self.tab_order = config.order
            self.enabled_tabs = config.enabled
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

    def destroy(self):
        try:
            self.db.close()
        finally:
            super().destroy()

    def _switch_db(self, new_path: Path):
        """Close current DB connection and open a new one."""
        self.db.switch_db(Path(new_path))
        self._sync_db_handles()
        self._update_title()

        # Reload UI from the new DB
        self.refresh_items()
        self.refresh_recipes()
        self._tiers_load_from_db()
        if getattr(self, "items_tab", None) is not None:
            self.items_tab._item_details_set("")
        if getattr(self, "recipes_tab", None) is not None:
            self.recipes_tab._recipe_details_set("")
        self.planner_state = {}
        if getattr(self, "planner_tab", None) is not None:
            self.planner_tab.reset_state()

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
            self.db.export_content_db(Path(path))
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
            self.db.export_profile_db(Path(path))
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
            stats = self.db.merge_db(Path(path))
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
        return self.db.get_enabled_tiers()

    def set_enabled_tiers(self, tiers: list[str]):
        self.db.set_enabled_tiers(tiers)

    # ---------- Crafting grid unlocks ----------
    def is_crafting_6x6_unlocked(self) -> bool:
        return self.db.is_crafting_6x6_unlocked()

    def set_crafting_6x6_unlocked(self, unlocked: bool) -> None:
        self.db.set_crafting_6x6_unlocked(unlocked)

    # ---------- Tab delegates ----------
    def refresh_items(self) -> None:
        self.items = fetch_items(self.conn)
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

    def notify_inventory_change(self) -> None:
        if getattr(self, "planner_tab", None) is not None:
            self.planner_tab.on_inventory_changed()
