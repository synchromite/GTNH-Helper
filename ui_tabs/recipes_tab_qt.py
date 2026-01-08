from __future__ import annotations

from PySide6 import QtWidgets

from services.recipes import fetch_item_name, fetch_machine_output_slots, fetch_recipe_lines
from ui_dialogs import AddRecipeDialog, EditRecipeDialog


class RecipesTab(QtWidgets.QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.recipes: list = []
        root_layout = QtWidgets.QHBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)

        left = QtWidgets.QVBoxLayout()
        root_layout.addLayout(left, stretch=0)

        right = QtWidgets.QVBoxLayout()
        root_layout.addLayout(right, stretch=1)

        self.recipe_list = QtWidgets.QListWidget()
        self.recipe_list.setMinimumWidth(240)
        self.recipe_list.currentRowChanged.connect(self.on_recipe_select)
        if self.app.editor_enabled:
            self.recipe_list.itemDoubleClicked.connect(lambda _item: self.open_edit_recipe_dialog())
        left.addWidget(self.recipe_list, stretch=1)

        btns = QtWidgets.QHBoxLayout()
        left.addLayout(btns)
        self.btn_add_recipe = QtWidgets.QPushButton("Add Recipe")
        self.btn_edit_recipe = QtWidgets.QPushButton("Edit Recipe")
        self.btn_del_recipe = QtWidgets.QPushButton("Delete Recipe")
        self.btn_add_recipe.clicked.connect(self.open_add_recipe_dialog)
        self.btn_edit_recipe.clicked.connect(self.open_edit_recipe_dialog)
        self.btn_del_recipe.clicked.connect(self.delete_selected_recipe)
        btns.addWidget(self.btn_add_recipe)
        btns.addWidget(self.btn_edit_recipe)
        btns.addWidget(self.btn_del_recipe)
        btns.addStretch(1)

        if not self.app.editor_enabled:
            self.btn_add_recipe.setEnabled(False)
            self.btn_edit_recipe.setEnabled(False)
            self.btn_del_recipe.setEnabled(False)

        self.recipe_details = QtWidgets.QTextEdit()
        self.recipe_details.setReadOnly(True)
        right.addWidget(self.recipe_details)

    def render_recipes(self, recipes: list) -> None:
        selected_id = None
        current_row = self.recipe_list.currentRow()
        if 0 <= current_row < len(self.recipes):
            try:
                selected_id = self.recipes[current_row]["id"]
            except Exception:
                selected_id = None

        self.recipes = list(recipes)
        self.recipe_list.clear()
        for recipe in self.recipes:
            self.recipe_list.addItem(recipe["name"])

        if selected_id is not None:
            for idx, recipe in enumerate(self.recipes):
                try:
                    recipe_id = recipe["id"]
                except Exception:
                    recipe_id = None
                if recipe_id == selected_id:
                    self.recipe_list.setCurrentRow(idx)
                    break
        elif self.recipes:
            self.recipe_list.setCurrentRow(0)

    def on_recipe_select(self, row: int) -> None:
        if row < 0 or row >= len(self.recipes):
            self._recipe_details_set("")
            return
        recipe = self.recipes[row]
        lines = fetch_recipe_lines(self.app.conn, recipe["id"])

        ins: list[str] = []
        outs: list[str] = []

        def fmt_qty(value):
            if value is None:
                return None
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return value

        for line in lines:
            if line["qty_liters"] is not None:
                qty = fmt_qty(line["qty_liters"])
                label = f"{line['name']} × {qty} L"
            else:
                qty = fmt_qty(line["qty_count"])
                label = f"{line['name']} × {qty}"

            if line["direction"] == "out":
                slot_idx = line["output_slot_index"]
                if slot_idx is not None:
                    label = f"{label} (Slot {slot_idx})"
                chance = line["chance_percent"]
                if chance is not None:
                    try:
                        chance_val = float(chance)
                    except Exception:
                        chance_val = 100.0
                    if chance_val < 99.999:
                        label = f"{label} ({chance_val:g}%)"

            (ins if line["direction"] == "in" else outs).append(label)

        duration_s = None
        if recipe["duration_ticks"] is not None:
            duration_s = int(recipe["duration_ticks"] / 20)

        method = (recipe["method"] or "machine").strip().lower()
        method_label = "Crafting" if method == "crafting" else "Machine"

        station_name = ""
        if method == "crafting" and recipe["station_item_id"] is not None:
            station_name = fetch_item_name(self.app.conn, recipe["station_item_id"])

        method_lines = [f"Method: {method_label}"]
        if method == "crafting":
            method_lines.append(f"Grid: {recipe['grid_size'] or ''}")
            method_lines.append(f"Station: {station_name}")
        else:
            machine_line = f"Machine: {recipe['machine'] or ''}"
            machine_item_id = recipe["machine_item_id"]
            if machine_item_id is not None:
                mos = fetch_machine_output_slots(self.app.conn, machine_item_id)
                if mos is not None:
                    machine_line = f"{machine_line} (output slots: {mos})"
            method_lines.append(machine_line)

        txt = (
            f"Name: {recipe['name']}\n"
            + "\n".join(method_lines)
            + "\n"
            f"Tier: {recipe['tier'] or ''}\n"
            f"Circuit: {'' if recipe['circuit'] is None else recipe['circuit']}\n"
            f"Duration: {'' if duration_s is None else str(duration_s) + 's'}\n"
            f"EU/t: {'' if recipe['eu_per_tick'] is None else recipe['eu_per_tick']}\n\n"
            "Inputs:\n  "
            + ("\n  ".join(ins) if ins else "(none)")
            + "\n\n"
            "Outputs:\n  "
            + ("\n  ".join(outs) if outs else "(none)")
            + "\n"
        )
        self._recipe_details_set(txt)

    def _recipe_details_set(self, txt: str) -> None:
        self.recipe_details.setPlainText(txt)

    def open_add_recipe_dialog(self) -> None:
        if not self.app.editor_enabled:
            QtWidgets.QMessageBox.information(self, "Editor locked", "Adding Recipes is only available in editor mode.")
            return
        dialog = AddRecipeDialog(self.app, parent=self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.app.refresh_recipes()

    def open_edit_recipe_dialog(self) -> None:
        if not self.app.editor_enabled:
            QtWidgets.QMessageBox.information(
                self,
                "Editor locked",
                "Editing Recipes is only available in editor mode.",
            )
            return
        row = self.recipe_list.currentRow()
        if row < 0:
            QtWidgets.QMessageBox.information(self, "Select a recipe", "Click a recipe first.")
            return
        recipe_id = self.recipes[row]["id"]
        dialog = EditRecipeDialog(self.app, recipe_id, parent=self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.app.refresh_recipes()

    def delete_selected_recipe(self) -> None:
        if not self.app.editor_enabled:
            QtWidgets.QMessageBox.information(
                self,
                "Editor locked",
                "Deleting Recipes is only available in editor mode.",
            )
            return
        row = self.recipe_list.currentRow()
        if row < 0:
            QtWidgets.QMessageBox.information(self, "Select a recipe", "Click a recipe first.")
            return
        recipe = self.recipes[row]
        ok = QtWidgets.QMessageBox.question(
            self,
            "Delete recipe?",
            f"Delete recipe:\n\n{recipe['name']}",
        )
        if ok != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.app.conn.execute("DELETE FROM recipes WHERE id=?", (recipe["id"],))
        self.app.conn.commit()
        self.app.refresh_recipes()
        self._recipe_details_set("")
        self.app.status_bar.showMessage(f"Deleted recipe: {recipe['name']}")
