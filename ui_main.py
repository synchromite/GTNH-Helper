#!/usr/bin/env python3
import datetime
import sqlite3
import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from services.db import DEFAULT_DB_PATH, find_item_merge_conflicts, find_missing_attributes
from services.db_lifecycle import DbLifecycle
from services.items import fetch_items
from services.recipes import fetch_recipes
from services.tab_config import apply_tab_reorder, config_path, load_tab_config, save_tab_config
from ui_dialogs import (
    CraftingGridManagerDialog,
    ItemKindManagerDialog,
    ItemMergeConflictDialog,
    MaterialManagerDialog,
    TierManagerDialog,
)
from ui_tabs.inventory_tab import InventoryTab
from ui_tabs.items_tab_qt import ItemsTab, FluidsTab, GasesTab
from ui_tabs.recipes_tab_qt import RecipesTab
from ui_tabs.planner_tab_qt import PlannerTab
from ui_tabs.tiers_tab import TiersTab
from ui_tabs.machines_tab import MachinesTab
from ui_constants import DARK_STYLESHEET, LIGHT_STYLESHEET


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


class DetachedTabWindow(QtWidgets.QMainWindow):
    def __init__(
        self,
        tab_id: str,
        label: str,
        widget: QtWidgets.QWidget,
        on_reattach: callable,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        self._tab_id = tab_id
        self._label = label
        self._on_reattach = on_reattach
        self._is_reattaching = False

        self.setWindowTitle(f"{label} — Detached")
        self.setCentralWidget(widget)
        widget.show()

        menu = self.menuBar().addMenu("Tab")
        action = QtGui.QAction("Reattach", self)
        action.triggered.connect(self.request_reattach)
        menu.addAction(action)

    def request_reattach(self) -> None:
        if self._is_reattaching:
            return
        self._is_reattaching = True
        self._on_reattach(self._tab_id)

    def closeEvent(self, event) -> None:
        if not self._is_reattaching:
            self.request_reattach()
        event.accept()


class App(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1100, 700)

        # Set the application icon (visible in the dock/task switcher)
        icon_path = Path(__file__).parent / "images" / "Helper_Icon.png"
        icon = QtGui.QIcon(str(icon_path))
        self.setWindowIcon(icon)
        QtWidgets.QApplication.instance().setWindowIcon(icon)

        # Default behavior is "client mode". Creating a file named `.enable_editor`
        # next to this script enables editor capabilities.
        self.editor_enabled = self._detect_editor_enabled()

        self.db = DbLifecycle(editor_enabled=self.editor_enabled, db_path=DEFAULT_DB_PATH)
        self._sync_db_handles()
        self._apply_theme(self.db.get_theme())
        if self.db.last_open_error:
            QtWidgets.QMessageBox.warning(
                self,
                "Database open failed",
                "Failed to open the content database. The app is using a temporary in-memory database.\n\n"
                f"Details: {self.db.last_open_error}",
            )

        self.status_bar = self.statusBar()
        self.status_bar.showMessage("Ready")
        self.planner_state: dict[str, object] = {}
        self._ui_config_save_failed = False
        self._db_recovery_notified_for: Path | None = None

        self.tab_registry = {
            "items": {"label": "Items"},
            "fluids": {"label": "Fluids"},
            "gases": {"label": "Gases"},
            "recipes": {"label": "Recipes"},
            "inventory": {"label": "Inventory"},
            "planner": {"label": "Planner"},
            "tiers": {"label": "Tiers"},
            "machines": {"label": "Machines"},
        }
        self.tab_order, self.enabled_tabs = self._load_ui_config()
        self.tab_actions: dict[str, QtGui.QAction] = {}
        self.tab_widgets: dict[str, QtWidgets.QWidget] = {}
        self.detached_tabs: dict[str, DetachedTabWindow] = {}

        self._build_menu()
        self._update_title()

        self.items: list = []
        self.recipes: list = []
        self.recipe_focus_id: int | None = None
        self.last_added_item_id: int | None = None

        self.nb = QtWidgets.QTabWidget()
        self.nb.tabBar().setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.nb.tabBar().customContextMenuRequested.connect(self._open_tab_context_menu)
        self.setCentralWidget(self.nb)

        self._rebuild_tabs()

        self.refresh_items()
        self.refresh_recipes()
        self._tiers_load_from_db()
        self._machines_load_from_db()

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
        if self._ui_config_save_failed:
            return
        path = self._config_path()
        try:
            save_tab_config(path, self.tab_order, self.enabled_tabs)
        except Exception as exc:
            self._ui_config_save_failed = True
            QtWidgets.QMessageBox.warning(
                self,
                "Config save failed",
                f"Could not save tab preferences.\n\nDetails: {exc}",
            )

    def _create_tab_widget(self, tab_id: str) -> QtWidgets.QWidget:
        label = self.tab_registry[tab_id]["label"]
        if tab_id == "items":
            widget = ItemsTab(self, self)
        elif tab_id == "fluids":
            widget = FluidsTab(self, self)
        elif tab_id == "gases":
            widget = GasesTab(self, self)
        elif tab_id == "recipes":
            widget = RecipesTab(self, self)
        elif tab_id == "inventory":
            widget = InventoryTab(self, self)
        elif tab_id == "tiers":
            widget = TiersTab(self, self)
        elif tab_id == "planner":
            widget = PlannerTab(self, self)
        elif tab_id == "machines":
            widget = MachinesTab(self, self)
        else:
            widget = PlaceholderTab(label)
        widget.setProperty("tab_id", tab_id)
        return widget

    def _clear_tabs(self) -> None:
        while self.nb.count() > 0:
            self.nb.removeTab(0)

    def _insert_tab_in_order(self, tab_id: str, widget: QtWidgets.QWidget) -> None:
        index = 0
        for candidate in self.tab_order:
            if candidate == tab_id:
                break
            if candidate in self.enabled_tabs and candidate not in self.detached_tabs:
                index += 1
        label = self.tab_registry[tab_id]["label"]
        self.nb.insertTab(index, widget, label)

    def _rebuild_tabs(self) -> None:
        self._clear_tabs()
        for tab_id in self.tab_order:
            if tab_id not in self.enabled_tabs or tab_id in self.detached_tabs:
                continue
            widget = self.tab_widgets.get(tab_id) or self._create_tab_widget(tab_id)
            self.tab_widgets[tab_id] = widget
            self.nb.addTab(widget, self.tab_registry[tab_id]["label"])

    def _open_tab_context_menu(self, pos) -> None:
        index = self.nb.tabBar().tabAt(pos)
        if index < 0:
            return
        widget = self.nb.widget(index)
        tab_id = widget.property("tab_id")
        if not tab_id:
            return
        menu = QtWidgets.QMenu(self)
        detach_action = menu.addAction("Detach")
        detach_action.triggered.connect(lambda checked=False, tid=tab_id: self._detach_tab(tid))
        menu.exec(self.nb.tabBar().mapToGlobal(pos))

    def _detach_tab(self, tab_id: str) -> None:
        if tab_id in self.detached_tabs:
            return
        widget = self.tab_widgets.get(tab_id)
        if widget is None:
            widget = self._create_tab_widget(tab_id)
            self.tab_widgets[tab_id] = widget
        index = self.nb.indexOf(widget)
        if index >= 0:
            self.nb.removeTab(index)
        widget.setParent(None)
        window = DetachedTabWindow(tab_id, self.tab_registry[tab_id]["label"], widget, self._reattach_tab, self)
        self.detached_tabs[tab_id] = window
        window.show()
        self._refresh_detached_tab(tab_id)

    def _reattach_tab(self, tab_id: str) -> None:
        window = self.detached_tabs.pop(tab_id, None)
        if window is None:
            return
        widget = window.takeCentralWidget()
        if widget is None:
            return
        window.deleteLater()
        self._insert_tab_in_order(tab_id, widget)
        widget.show()
        self.nb.setCurrentWidget(widget)
        self._refresh_detached_tab(tab_id)

    def _refresh_detached_tab(self, tab_id: str) -> None:
        widget = self.tab_widgets.get(tab_id)
        if widget is None:
            return
        if tab_id == "items" and hasattr(widget, "render_items"):
            widget.render_items(self.items)
        elif tab_id == "fluids" and hasattr(widget, "render_items"):
            widget.render_items(self.items)
        elif tab_id == "gases" and hasattr(widget, "render_items"):
            widget.render_items(self.items)
        elif tab_id == "recipes" and hasattr(widget, "render_recipes"):
            widget.render_recipes(self.recipes)
        elif tab_id == "inventory" and hasattr(widget, "render_items"):
            widget.render_items(self.items)
        elif tab_id == "tiers" and hasattr(widget, "load_from_db"):
            widget.load_from_db()
        elif tab_id == "machines" and hasattr(widget, "load_from_db"):
            widget.load_from_db()

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
        if tab_id not in self.enabled_tabs and tab_id in self.detached_tabs:
            window = self.detached_tabs.pop(tab_id, None)
            if window:
                window.takeCentralWidget()
                window.deleteLater()
        self._save_ui_config()
        self._rebuild_tabs()
        self.refresh_items()
        self.refresh_recipes()
        self._tiers_load_from_db()
        self._machines_load_from_db()

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
        self._machines_load_from_db()

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

        view_menu = menubar.addMenu("View")
        theme_group = QtGui.QActionGroup(self)
        theme_group.setExclusive(True)
        light_action = QtGui.QAction("Light Theme", self, checkable=True)
        dark_action = QtGui.QAction("Dark Theme", self, checkable=True)
        theme_group.addAction(light_action)
        theme_group.addAction(dark_action)
        view_menu.addActions([light_action, dark_action])
        current_theme = self.db.get_theme()
        if current_theme == "light":
            light_action.setChecked(True)
        else:
            dark_action.setChecked(True)
        light_action.triggered.connect(lambda checked=False: self._apply_theme("light"))
        dark_action.triggered.connect(lambda checked=False: self._apply_theme("dark"))

        tools_menu = menubar.addMenu("Tools")
        materials_action = QtGui.QAction("Manage Materials…", self)
        materials_action.setEnabled(self.editor_enabled)
        materials_action.triggered.connect(self.menu_manage_materials)
        tools_menu.addAction(materials_action)
        kinds_action = QtGui.QAction("Manage Item Kinds…", self)
        kinds_action.setEnabled(self.editor_enabled)
        kinds_action.triggered.connect(self.menu_manage_item_kinds)
        tools_menu.addAction(kinds_action)
        tiers_action = QtGui.QAction("Manage Tiers…", self)
        tiers_action.setEnabled(self.editor_enabled)
        tiers_action.triggered.connect(self.menu_manage_tiers)
        tools_menu.addAction(tiers_action)
        grids_action = QtGui.QAction("Manage Crafting Grids…", self)
        grids_action.triggered.connect(self.menu_manage_crafting_grids)
        tools_menu.addAction(grids_action)

    def _apply_theme(self, theme: str) -> None:
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        if theme == "light":
            app.setStyleSheet(LIGHT_STYLESHEET)
        else:
            theme = "dark"
            app.setStyleSheet(DARK_STYLESHEET)
        self.db.set_theme(theme)

    def _update_title(self) -> None:
        try:
            name = self.db_path.name
        except Exception:
            name = "(unknown)"
        mode = "Editor" if self.editor_enabled else "Client"
        self.setWindowTitle(f"GTNH Helper — {mode} — {name}")

    def closeEvent(self, event) -> None:
        try:
            self.db.close()
        finally:
            event.accept()

    def _switch_db(self, new_path: Path) -> None:
        """Close current DB connection and open a new one."""
        self.db.switch_db(Path(new_path))
        self._db_recovery_notified_for = None
        self._sync_db_handles()
        self._update_title()
        self._apply_theme(self.db.get_theme())
        if self.db.last_open_error:
            QtWidgets.QMessageBox.warning(
                self,
                "Database open failed",
                "Failed to open the content database. The app is using a temporary in-memory database.\n\n"
                f"Details: {self.db.last_open_error}",
            )

        # Reload UI from the new DB
        self.refresh_items()
        self.refresh_recipes()
        self._tiers_load_from_db()
        self._machines_load_from_db()
        self.planner_state = {}

    def _recover_closed_connection(self, source: str) -> None:
        """Try to recover after a closed DB connection and notify the user."""
        target_path = Path(self.db_path)
        self.db.switch_db(target_path)
        self._sync_db_handles()

        if self._db_recovery_notified_for == target_path:
            return

        self._db_recovery_notified_for = target_path
        if self.db.last_open_error:
            QtWidgets.QMessageBox.warning(
                self,
                "Database connection lost",
                "The database connection was closed unexpectedly while refreshing data. "
                f"The app tried to re-open '{target_path}', but that failed. "
                "The app is now using a temporary in-memory database.\n\n"
                f"Source: {source}\n"
                f"Details: {self.db.last_open_error}",
            )
            self.status_bar.showMessage("Database reconnect failed; using temporary in-memory DB")
            return

        QtWidgets.QMessageBox.information(
            self,
            "Database connection restored",
            "The database connection was closed unexpectedly while refreshing data. "
            f"The app re-opened '{target_path}'.",
        )
        self.status_bar.showMessage(f"Database connection restored: {target_path.name}")

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

    def _warn_missing_attributes(self) -> None:
        missing = find_missing_attributes(self.conn)
        lines = []
        if missing.get("item_kind", 0):
            lines.append(f"Items missing Item Kind: {missing['item_kind']}")
        if missing.get("material", 0):
            lines.append(f"Items missing Material: {missing['material']}")
        if missing.get("machine_type", 0):
            lines.append(f"Machines missing Type: {missing['machine_type']}")
        if missing.get("machine_tier", 0):
            lines.append(f"Machines missing Tier: {missing['machine_tier']}")
        if not lines:
            return
        message = "Some imported items are missing new attributes:\n\n" + "\n".join(lines)
        QtWidgets.QMessageBox.warning(self, "Missing attributes", message)

    def menu_manage_materials(self) -> None:
        if not self.editor_enabled:
            QtWidgets.QMessageBox.information(
                self,
                "Editor locked",
                "This copy is running in client mode.\n\n"
                "To enable editing, create a file named '.enable_editor' next to the app.",
            )
            return
        dlg = MaterialManagerDialog(self, parent=self)
        dlg.exec()

    def menu_manage_item_kinds(self) -> None:
        if not self.editor_enabled:
            QtWidgets.QMessageBox.information(
                self,
                "Editor locked",
                "This copy is running in client mode.\n\n"
                "To enable editing, create a file named '.enable_editor' next to the app.",
            )
            return
        dlg = ItemKindManagerDialog(self, parent=self)
        dlg.exec()

    def menu_manage_tiers(self) -> None:
        if not self.editor_enabled:
            QtWidgets.QMessageBox.information(
                self,
                "Editor locked",
                "This copy is running in client mode.\n\n"
                "To enable editing, create a file named '.enable_editor' next to the app.",
            )
            return
        dlg = TierManagerDialog(self, parent=self)
        dlg.exec()

    def menu_manage_crafting_grids(self) -> None:
        dlg = CraftingGridManagerDialog(self, parent=self)
        dlg.exec()

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

        item_conflicts = {}
        conflicts = find_item_merge_conflicts(self.conn, Path(path))
        if conflicts:
            dlg = ItemMergeConflictDialog(conflicts, parent=self)
            if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                return
            item_conflicts = dlg.result or {}

        try:
            stats = self.db.merge_db(Path(path), item_conflicts=item_conflicts)
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
        self._warn_missing_attributes()

    # ---------- Tiers ----------
    def get_enabled_tiers(self):
        return self.db.get_enabled_tiers()

    def set_enabled_tiers(self, tiers: list[str]) -> None:
        self.db.set_enabled_tiers(tiers)

    def get_all_tiers(self) -> list[str]:
        return self.db.get_all_tiers()

    def set_all_tiers(self, tiers: list[str]) -> None:
        self.db.set_all_tiers(tiers)

    # ---------- Crafting grid unlocks ----------
    def is_crafting_6x6_unlocked(self) -> bool:
        return self.db.is_crafting_6x6_unlocked()

    def set_crafting_6x6_unlocked(self, unlocked: bool) -> None:
        self.db.set_crafting_6x6_unlocked(unlocked)

    def get_crafting_grids(self) -> list[str]:
        return self.db.get_crafting_grids()

    def set_crafting_grids(self, grids: list[str]) -> None:
        self.db.set_crafting_grids(grids)

    # ---------- Machines tab UI preferences ----------
    def get_machine_sort_mode(self) -> str:
        return self.db.get_machine_sort_mode()

    def set_machine_sort_mode(self, mode: str) -> None:
        self.db.set_machine_sort_mode(mode)

    def get_machine_tier_filter(self) -> str:
        return self.db.get_machine_tier_filter()

    def set_machine_tier_filter(self, tier: str) -> None:
        self.db.set_machine_tier_filter(tier)

    def get_machine_unlocked_only(self) -> bool:
        return self.db.get_machine_unlocked_only()

    def set_machine_unlocked_only(self, unlocked_only: bool) -> None:
        self.db.set_machine_unlocked_only(unlocked_only)

    def get_machine_search(self) -> str:
        return self.db.get_machine_search()

    def set_machine_search(self, value: str) -> None:
        self.db.set_machine_search(value)

    # ---------- Tab delegates ----------
    def refresh_items(self) -> None:
        try:
            self.items = fetch_items(self.conn)
        except sqlite3.ProgrammingError as exc:
            if "closed" not in str(exc).lower():
                raise
            self._recover_closed_connection("items refresh")
            self.items = fetch_items(self.conn)
        widget = self.tab_widgets.get("items")
        if widget and hasattr(widget, "render_items"):
            widget.render_items(self.items)
        widget = self.tab_widgets.get("fluids")
        if widget and hasattr(widget, "render_items"):
            widget.render_items(self.items)
        widget = self.tab_widgets.get("gases")
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
            self._recover_closed_connection("recipes refresh")
            self.recipes = fetch_recipes(self.conn, self.get_enabled_tiers())
        widget = self.tab_widgets.get("recipes")
        if widget and hasattr(widget, "render_recipes"):
            widget.render_recipes(self.recipes)

    def _tiers_load_from_db(self) -> None:
        widget = self.tab_widgets.get("tiers")
        if widget and hasattr(widget, "load_from_db"):
            widget.load_from_db()

    def _machines_load_from_db(self) -> None:
        widget = self.tab_widgets.get("machines")
        if widget and hasattr(widget, "load_from_db"):
            widget.load_from_db()


    def list_storage_units(self) -> list[dict[str, int | str]]:
        return self.db.list_storage_units()

    def get_active_storage_id(self) -> int | None:
        return self.db.get_active_storage_id()

    def set_active_storage_id(self, storage_id: int) -> None:
        self.db.set_active_storage_id(storage_id)

    def get_machine_availability(self, machine_type: str, tier: str) -> dict[str, int]:
        return self.db.get_machine_availability(machine_type, tier)

    def set_machine_availability(self, rows: list[tuple[str, str, int, int]]) -> None:
        self.db.set_machine_availability(rows)
        planner_widget = self.tab_widgets.get("planner")
        if planner_widget and hasattr(planner_widget, "clear_planner_cache"):
            planner_widget.clear_planner_cache()

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
