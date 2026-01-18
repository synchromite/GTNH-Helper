from __future__ import annotations

from PySide6 import QtWidgets

from services.db import ALL_TIERS


class TiersTab(QtWidgets.QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.tier_checks: dict[str, QtWidgets.QCheckBox] = {}
        self._tier_list: list[str] = []

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        layout.addWidget(QtWidgets.QLabel("Select tiers you currently have access to."))

        self.grid = QtWidgets.QGridLayout()
        layout.addLayout(self.grid)

        self._build_tier_grid(self._get_tier_list())

        unlocks = QtWidgets.QGroupBox("Crafting")
        unlocks_layout = QtWidgets.QVBoxLayout(unlocks)
        self.unlocked_6x6_checkbox = QtWidgets.QCheckBox(
            "6x6 Crafting unlocked (once you've made a crafting table with a crafting grid)"
        )
        self.unlocked_6x6_checkbox.toggled.connect(lambda _: self._tiers_save_to_db())
        unlocks_layout.addWidget(self.unlocked_6x6_checkbox)

        unlocks_layout.addWidget(QtWidgets.QLabel("Crafting grid sizes (NxM):"))
        self.grid_sizes_list = QtWidgets.QListWidget()
        unlocks_layout.addWidget(self.grid_sizes_list)
        grid_btns = QtWidgets.QHBoxLayout()
        self.add_grid_btn = QtWidgets.QPushButton("Add Grid Size")
        self.add_grid_btn.clicked.connect(self._add_grid_size)
        self.remove_grid_btn = QtWidgets.QPushButton("Remove Grid Size")
        self.remove_grid_btn.clicked.connect(self._remove_grid_size)
        grid_btns.addWidget(self.add_grid_btn)
        grid_btns.addWidget(self.remove_grid_btn)
        grid_btns.addStretch(1)
        unlocks_layout.addLayout(grid_btns)
        layout.addWidget(unlocks)

        note = QtWidgets.QLabel(
            "Note: this controls dropdown tiers and filters the Recipes list (no planner logic yet)."
        )
        note.setStyleSheet("color: #666;")
        layout.addWidget(note)
        layout.addStretch(1)

    def _set_tier_checked(self, tier: str, checked: bool) -> None:
        checkbox = self.tier_checks.get(tier)
        if not checkbox:
            return
        prev = checkbox.blockSignals(True)
        checkbox.setChecked(checked)
        checkbox.blockSignals(prev)

    def load_from_db(self) -> None:
        tiers = self._get_tier_list()
        if tiers != self._tier_list:
            self._build_tier_grid(tiers)
        enabled = set(self.app.get_enabled_tiers())
        for tier, checkbox in self.tier_checks.items():
            prev = checkbox.blockSignals(True)
            checkbox.setChecked(tier in enabled)
            checkbox.blockSignals(prev)

        prev = self.unlocked_6x6_checkbox.blockSignals(True)
        self.unlocked_6x6_checkbox.setChecked(self.app.is_crafting_6x6_unlocked())
        self.unlocked_6x6_checkbox.blockSignals(prev)
        self._reload_grid_sizes()

    def _on_tier_toggle(self, tier: str, checked: bool) -> None:
        tier_list = self._tier_list or self._get_tier_list()
        try:
            tier_index = tier_list.index(tier)
        except ValueError:
            return

        if checked:
            for lower_tier in tier_list[: tier_index + 1]:
                self._set_tier_checked(lower_tier, True)

            if "Steam Age" in tier_list[: tier_index + 1]:
                if not self.unlocked_6x6_checkbox.isChecked():
                    prev = self.unlocked_6x6_checkbox.blockSignals(True)
                    self.unlocked_6x6_checkbox.setChecked(True)
                    self.unlocked_6x6_checkbox.blockSignals(prev)
        else:
            for higher_tier in tier_list[tier_index + 1 :]:
                self._set_tier_checked(higher_tier, False)

            steam_checkbox = self.tier_checks.get("Steam Age")
            if steam_checkbox is not None and not steam_checkbox.isChecked():
                if self.unlocked_6x6_checkbox.isChecked():
                    prev = self.unlocked_6x6_checkbox.blockSignals(True)
                    self.unlocked_6x6_checkbox.setChecked(False)
                    self.unlocked_6x6_checkbox.blockSignals(prev)

        self._tiers_save_to_db()

    def _tiers_save_to_db(self) -> None:
        enabled = [t for t, checkbox in self.tier_checks.items() if checkbox.isChecked()]
        if not enabled:
            QtWidgets.QMessageBox.critical(self, "Pick at least one", "Enable at least one tier.")
            return
        self.app.set_enabled_tiers(enabled)
        self.app.set_crafting_6x6_unlocked(bool(self.unlocked_6x6_checkbox.isChecked()))
        self.app.set_crafting_grids(self._current_grid_sizes())

        if hasattr(self.app, "refresh_recipes"):
            self.app.refresh_recipes()
        widget = getattr(self.app, "tab_widgets", {}).get("recipes")
        if widget and hasattr(widget, "_recipe_details_set"):
            widget._recipe_details_set("")
        if hasattr(self.app, "_machines_load_from_db"):
            self.app._machines_load_from_db()

        if hasattr(self.app, "status_bar"):
            self.app.status_bar.showMessage(f"Saved tiers: {', '.join(enabled)}")

    def _get_tier_list(self) -> list[str]:
        if hasattr(self.app, "get_all_tiers"):
            return list(self.app.get_all_tiers())
        return list(ALL_TIERS)

    def _build_tier_grid(self, tiers: list[str]) -> None:
        self._tier_list = list(tiers)
        self.tier_checks = {}
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        cols = 3
        for i, tier in enumerate(tiers):
            checkbox = QtWidgets.QCheckBox(tier)
            checkbox.toggled.connect(lambda checked, t=tier: self._on_tier_toggle(t, checked))
            self.tier_checks[tier] = checkbox
            row, col = divmod(i, cols)
            self.grid.addWidget(checkbox, row, col)

    def _reload_grid_sizes(self) -> None:
        self.grid_sizes_list.clear()
        grid_values = self.app.get_crafting_grids() if hasattr(self.app, "get_crafting_grids") else ["2x2", "3x3"]
        for grid in grid_values:
            self.grid_sizes_list.addItem(grid)

    def _current_grid_sizes(self) -> list[str]:
        grids = []
        for idx in range(self.grid_sizes_list.count()):
            text = (self.grid_sizes_list.item(idx).text() or "").strip()
            if text:
                grids.append(text)
        return grids

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

    def _add_grid_size(self) -> None:
        value, ok = QtWidgets.QInputDialog.getText(self, "Add Grid Size", "Grid size (NxM):")
        if not ok:
            return
        dims = self._parse_grid_size(value)
        if not dims:
            QtWidgets.QMessageBox.warning(self, "Invalid grid size", "Enter a grid size like 2x2 or 3x3.")
            return
        rows, cols = dims
        label = f"{rows}x{cols}"
        existing = {self.grid_sizes_list.item(i).text() for i in range(self.grid_sizes_list.count())}
        if label in existing:
            QtWidgets.QMessageBox.information(self, "Already added", f"{label} is already in the list.")
            return
        self.grid_sizes_list.addItem(label)
        self._tiers_save_to_db()

    def _remove_grid_size(self) -> None:
        row = self.grid_sizes_list.currentRow()
        if row < 0:
            return
        item = self.grid_sizes_list.item(row)
        if not item:
            return
        if item.text().strip() == "2x2":
            QtWidgets.QMessageBox.warning(self, "Cannot remove", "The 2x2 grid is required.")
            return
        self.grid_sizes_list.takeItem(row)
        self._tiers_save_to_db()
