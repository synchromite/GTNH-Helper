from __future__ import annotations

from PySide6 import QtWidgets

from services.db import ALL_TIERS


class TiersTab(QtWidgets.QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.tier_checks: dict[str, QtWidgets.QCheckBox] = {}

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        layout.addWidget(QtWidgets.QLabel("Select tiers you currently have access to."))

        grid = QtWidgets.QGridLayout()
        layout.addLayout(grid)

        cols = 3
        for i, tier in enumerate(ALL_TIERS):
            checkbox = QtWidgets.QCheckBox(tier)
            checkbox.toggled.connect(lambda checked, t=tier: self._on_tier_toggle(t, checked))
            self.tier_checks[tier] = checkbox
            row, col = divmod(i, cols)
            grid.addWidget(checkbox, row, col)

        btns = QtWidgets.QHBoxLayout()
        layout.addLayout(btns)
        save_btn = QtWidgets.QPushButton("Save")
        save_btn.clicked.connect(self._tiers_save_to_db)
        btns.addWidget(save_btn)
        btns.addStretch(1)

        unlocks = QtWidgets.QGroupBox("Crafting")
        unlocks_layout = QtWidgets.QVBoxLayout(unlocks)
        self.unlocked_6x6_checkbox = QtWidgets.QCheckBox(
            "6x6 Crafting unlocked (once you've made a crafting table with a crafting grid)"
        )
        unlocks_layout.addWidget(self.unlocked_6x6_checkbox)
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
        enabled = set(self.app.get_enabled_tiers())
        for tier, checkbox in self.tier_checks.items():
            prev = checkbox.blockSignals(True)
            checkbox.setChecked(tier in enabled)
            checkbox.blockSignals(prev)

        self.unlocked_6x6_checkbox.setChecked(self.app.is_crafting_6x6_unlocked())

    def _on_tier_toggle(self, tier: str, checked: bool) -> None:
        try:
            tier_index = ALL_TIERS.index(tier)
        except ValueError:
            return

        if checked:
            for lower_tier in ALL_TIERS[: tier_index + 1]:
                self._set_tier_checked(lower_tier, True)

            if "Steam Age" in ALL_TIERS[: tier_index + 1]:
                if not self.unlocked_6x6_checkbox.isChecked():
                    self.unlocked_6x6_checkbox.setChecked(True)
        else:
            for higher_tier in ALL_TIERS[tier_index + 1 :]:
                self._set_tier_checked(higher_tier, False)

            steam_checkbox = self.tier_checks.get("Steam Age")
            if steam_checkbox is not None and not steam_checkbox.isChecked():
                if self.unlocked_6x6_checkbox.isChecked():
                    self.unlocked_6x6_checkbox.setChecked(False)

    def _tiers_save_to_db(self) -> None:
        enabled = [t for t, checkbox in self.tier_checks.items() if checkbox.isChecked()]
        if not enabled:
            QtWidgets.QMessageBox.critical(self, "Pick at least one", "Enable at least one tier.")
            return
        self.app.set_enabled_tiers(enabled)
        self.app.set_crafting_6x6_unlocked(bool(self.unlocked_6x6_checkbox.isChecked()))

        if hasattr(self.app, "refresh_recipes"):
            self.app.refresh_recipes()
        widget = getattr(self.app, "tab_widgets", {}).get("recipes")
        if widget and hasattr(widget, "_recipe_details_set"):
            widget._recipe_details_set("")
        if hasattr(self.app, "_machines_load_from_db"):
            self.app._machines_load_from_db()

        if hasattr(self.app, "status_bar"):
            self.app.status_bar.showMessage(f"Saved tiers: {', '.join(enabled)}")
