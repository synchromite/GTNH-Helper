#!/usr/bin/env python3
import datetime
import sqlite3
import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from services.db import DEFAULT_DB_PATH
from services.db_lifecycle import DbLifecycle
from services.items import fetch_items
from services.recipes import fetch_recipes
from services.tab_config import apply_tab_reorder, config_path, load_tab_config, save_tab_config
from ui_tabs.inventory_tab import InventoryTab
from ui_tabs.items_tab_qt import ItemsTab
from ui_tabs.recipes_tab_qt import RecipesTab
from ui_tabs.planner_tab_qt import PlannerTab
from ui_tabs.tiers_tab import TiersTab


class ReorderTabsDialog(QtWidgets.QDialog):
    def __init__(self, tab_order: list[str], tab_registry: dict[str, dict[str, str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reorder Tabs")
        self._tab_order = tab_order
        self._tab_registry = tab_registry
        self._spins: dict[str, QtWidgets.QSpinBox] = {}

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Set the order number for each tab (1 = first)."))

        form = QtWidgets.QFormLayout()
        for idx, tab_id in enumerate(tab_order, start=1):
            label = tab_registry[tab_id]["label"]
            spin = QtWidgets.QSpinBox()
            spin.setMinimum(1)
            spin.setMaximum(len(tab_order))
            spin.setValue(idx)
            form.addRow(label, spin)
            self._spins[tab_id] = spin

        layout.addLayout(form)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def build_orders(self) -> dict[str, int]:
        return {tab_id: spin.value() for tab_id, spin in self._spins.items()}


class PlaceholderTab(QtWidgets.QWidget):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(f"{label} (Qt UI pending)", alignment=QtCore.Qt.AlignmentFlag.AlignCenter))


class App(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1100, 700)

        # Default behavior is "client mode". Creating a file named `.enable_editor`
        # next to this script enables editor capabilities.
        self.editor_enabled = self._detect_editor_enabled()

        self.db = DbLifecycle(editor_enabled=self.editor_enabled, db_path=DEFAULT_DB_PATH)
        self._sync_db_handles()

        self.status_bar = self.statusBar()
        self.status_bar.showMessage("Ready")
        self.planner_state: dict[str, object] = {}

        self.tab_registry = {
            "items": {"label": "Items"},
            "recipes": {"label": "Recipes"},
            "inventory": {"label": "Inventory"},
            "planner": {"label": "Planner"},
            "tiers": {"label": "Tiers"},
        }
        self.tab_order, self.enabled_tabs = self._load_ui_config()
        self.tab_actions: dict[str, QtGui.QAction] = {}
        self.tab_widgets: dict[str, QtWidgets.QWidget] = {}

        self._build_menu()
        self._update_title()

        self.items: list = []
        self.recipes: list = []

        self.nb = QtWidgets.QTabWidget()
        self.setCentralWidget(self.nb)

        self._rebuild_tabs()

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
            QtWidgets.QMessageBox.warning(
                self,
                "Config save failed",
                f"Could not save tab preferences.\n\nDetails: {exc}",
            )

    def _create_tab_widget(self, tab_id: str) -> QtWidgets.QWidget:
        label = self.tab_registry[tab_id]["label"]
        if tab_id == "items":
            return ItemsTab(self, self)
        if tab_id == "recipes":
            return RecipesTab(self, self)
        if tab_id == "inventory":
            return InventoryTab(self, self)
        if tab_id == "tiers":
            return TiersTab(self, self)
        if tab_id == "planner":
            return PlannerTab(self, self)
        return PlaceholderTab(label)

    def _rebuild_tabs(self) -> None:
        self.nb.clear()
        self.tab_widgets = {}
        for tab_id in self.tab_order:
            if tab_id not in self.enabled_tabs:
                continue
            widget = self._create_tab_widget(tab_id)
            self.tab_widgets[tab_id] = widget
            self.nb.addTab(widget, self.tab_registry[tab_id]["label"])

    def _toggle_tab(self, tab_id: str, checked: bool) -> None:
        enabled = set(self.enabled_tabs)
        if checked:
            enabled.add(tab_id)
        else:
            if tab_id in enabled and len(enabled) == 1:
                QtWidgets.QMessageBox.information(self, "Tabs", "At least one tab must remain enabled.")
                self.tab_actions[tab_id].setChecked(True)
                return
            enabled.discard(tab_id)

        self.enabled_tabs = [tid for tid in self.tab_order if tid in enabled]
        self._save_ui_config()
        self._rebuild_tabs()
        self.refresh_items()
        self.refresh_recipes()
        self._tiers_load_from_db()

    def _open_reorder_tabs_dialog(self) -> None:
        dialog = ReorderTabsDialog(self.tab_order, self.tab_registry, self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        orders = dialog.build_orders()
        try:
            config = apply_tab_reorder(self.tab_order, self.enabled_tabs, orders)
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid order", str(exc))
            return

        self.tab_order = config.order
        self.enabled_tabs = config.enabled
        self._save_ui_config()
        self._rebuild_tabs()
        self.refresh_items()
        self.refresh_recipes()
        self._tiers_load_from_db()

    # ---------- Menu / DB handling ----------
    def _build_menu(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")
        file_menu.addAction("Open DB…", self.menu_open_db)
        if self.editor_enabled:
            file_menu.addAction("New DB…", self.menu_new_db)
            file_menu.addSeparator()
            file_menu.addAction("Export Content DB…", self.menu_export_content_db)
            file_menu.addAction("Export Profile DB…", self.menu_export_profile_db)
            file_menu.addAction("Merge DB…", self.menu_merge_db)
        else:
            file_menu.addSeparator()
            file_menu.addAction("Export Content DB…", self.menu_export_content_db)
            file_menu.addAction("Export Profile DB…", self.menu_export_profile_db)
        file_menu.addSeparator()
        file_menu.addAction("Quit", self.close)

        tabs_menu = menubar.addMenu("Tabs")
        for tab_id, meta in self.tab_registry.items():
            action = QtGui.QAction(meta["label"], self)
            action.setCheckable(True)
            action.setChecked(tab_id in self.enabled_tabs)
            action.toggled.connect(lambda checked, tid=tab_id: self._toggle_tab(tid, checked))
            tabs_menu.addAction(action)
            self.tab_actions[tab_id] = action
        tabs_menu.addSeparator()
        tabs_menu.addAction("Reorder Tabs…", self._open_reorder_tabs_dialog)

    def _update_title(self) -> None:
        try:
            name = self.db_path.name
        except Exception:
            name = "(unknown)"
        mode = "Editor" if self.editor_enabled else "Client"
        self.setWindowTitle(f"GTNH Recipe DB — {mode} — {name}")

    def closeEvent(self, event) -> None:
        try:
            self.db.close()
        finally:
            event.accept()

    def _switch_db(self, new_path: Path) -> None:
        """Close current DB connection and open a new one."""
        self.db.switch_db(Path(new_path))
        self._sync_db_handles()
        self._update_title()

        # Reload UI from the new DB
        self.refresh_items()
        self.refresh_recipes()
        self._tiers_load_from_db()
        self.planner_state = {}

    def menu_open_db(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open GTNH DB",
            str(self.db_path),
            "SQLite DB (*.db);;All files (*)",
        )
        if not path:
            return
        self._switch_db(Path(path))
        self.status_bar.showMessage(f"Opened DB: {Path(path).name}")

    def menu_new_db(self) -> None:
        if not self.editor_enabled:
            QtWidgets.QMessageBox.information(
                self,
                "Editor locked",
                "This copy is running in client mode.\n\n"
                "To enable editing, create a file named '.enable_editor' next to the app.",
            )
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Create / Choose DB",
            "gtnh.db",
            "SQLite DB (*.db);;All files (*)",
        )
        if not path:
            return
        self._switch_db(Path(path))
        self.status_bar.showMessage(f"Using DB: {Path(path).name}")

    def menu_export_content_db(self) -> None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default = f"gtnh_export_{ts}.db"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Content DB",
            default,
            "SQLite DB (*.db);;All files (*)",
        )
        if not path:
            return
        try:
            self.db.export_content_db(Path(path))
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Export failed", f"Could not export DB.\n\nDetails: {exc}")
            return
        self.status_bar.showMessage(f"Exported content DB to: {Path(path).name}")
        QtWidgets.QMessageBox.information(self, "Export complete", f"Exported content DB to:\n\n{path}")

    def menu_export_profile_db(self) -> None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default = f"gtnh_profile_export_{ts}.db"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Profile DB",
            default,
            "SQLite DB (*.db);;All files (*)",
        )
        if not path:
            return
        try:
            self.db.export_profile_db(Path(path))
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Export failed", f"Could not export profile DB.\n\nDetails: {exc}"
            )
            return
        self.status_bar.showMessage(f"Exported profile DB to: {Path(path).name}")
        QtWidgets.QMessageBox.information(self, "Export complete", f"Exported profile DB to:\n\n{path}")

    def menu_merge_db(self) -> None:
        if not self.editor_enabled:
            QtWidgets.QMessageBox.information(self, "Editor locked", "Merging is only available in editor mode.")
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Merge another DB into this one",
            str(self.db_path),
            "SQLite DB (*.db);;All files (*)",
        )
        if not path:
            return

        ok = QtWidgets.QMessageBox.question(
            self,
            "Merge DB?",
            "This will import Items, Recipes, and Recipe Lines from another DB into your current DB.\n\n"
            "It will NOT delete anything.\n"
            "If recipe names collide, imported recipes get a suffix like '(import 2)'.\n\n"
            "Continue?",
        )
        if ok != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        try:
            stats = self.db.merge_db(Path(path))
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Merge failed", f"Could not merge DB.\n\nDetails: {exc}")
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
        self.status_bar.showMessage("Merge complete")
        QtWidgets.QMessageBox.information(self, "Merge complete", msg)

    # ---------- Tiers ----------
    def get_enabled_tiers(self):
        return self.db.get_enabled_tiers()

    def set_enabled_tiers(self, tiers: list[str]) -> None:
        self.db.set_enabled_tiers(tiers)

    # ---------- Crafting grid unlocks ----------
    def is_crafting_6x6_unlocked(self) -> bool:
        return self.db.is_crafting_6x6_unlocked()

    def set_crafting_6x6_unlocked(self, unlocked: bool) -> None:
        self.db.set_crafting_6x6_unlocked(unlocked)

    # ---------- Tab delegates ----------
    def refresh_items(self) -> None:
        try:
            self.items = fetch_items(self.conn)
        except sqlite3.ProgrammingError as exc:
            if "closed" not in str(exc).lower():
                raise
            self.db.switch_db(self.db_path)
            self._sync_db_handles()
            self.items = fetch_items(self.conn)
        widget = self.tab_widgets.get("items")
        if widget and hasattr(widget, "render_items"):
            widget.render_items(self.items)
        inventory_widget = self.tab_widgets.get("inventory")
        if inventory_widget and hasattr(inventory_widget, "render_items"):
            inventory_widget.render_items(self.items)

    def refresh_recipes(self) -> None:
        try:
            self.recipes = fetch_recipes(self.conn, self.get_enabled_tiers())
        except sqlite3.ProgrammingError as exc:
            if "closed" not in str(exc).lower():
                raise
            self.db.switch_db(self.db_path)
            self._sync_db_handles()
            self.recipes = fetch_recipes(self.conn, self.get_enabled_tiers())
        widget = self.tab_widgets.get("recipes")
        if widget and hasattr(widget, "render_recipes"):
            widget.render_recipes(self.recipes)

    def _tiers_load_from_db(self) -> None:
        widget = self.tab_widgets.get("tiers")
        if widget and hasattr(widget, "load_from_db"):
            widget.load_from_db()

    def notify_inventory_change(self) -> None:
        widget = self.tab_widgets.get("planner")
        if widget and hasattr(widget, "on_inventory_changed"):
            widget.on_inventory_changed()
        return None


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = App()
    window.show()
    sys.exit(app.exec())
