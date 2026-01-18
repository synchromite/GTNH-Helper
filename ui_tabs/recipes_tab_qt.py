from __future__ import annotations

from PySide6 import QtWidgets

from services.recipes import fetch_item_name, fetch_machine_output_slots, fetch_recipe_lines
from ui_dialogs import AddRecipeDialog, EditRecipeDialog


class RecipesTab(QtWidgets.QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.recipes: list = []
        self.recipe_entries: list[dict | None] = []
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
        focus_id = getattr(self.app, "recipe_focus_id", None)
        if focus_id is not None:
            selected_id = focus_id
            self.app.recipe_focus_id = None
        else:
            current_row = self.recipe_list.currentRow()
            if 0 <= current_row < len(self.recipe_entries):
                entry = self.recipe_entries[current_row]
                if entry is not None:
                    selected_id = entry["id"]

        self.recipes = list(recipes)
        self.recipe_list.clear()

        canonical_names = {
            self._canonical_name(recipe["name"])
            for recipe in self.recipes
            if recipe["duplicate_of_recipe_id"] is None and recipe["name"]
        }

        normal = []
        for recipe in self.recipes:
            if recipe["duplicate_of_recipe_id"] is None:
                normal.append(recipe)
                continue
            name = (recipe["name"] or "").strip()
            if not name:
                continue
            if self._canonical_name(name) not in canonical_names:
                normal.append(recipe)

        self.recipe_entries = []
        for recipe in normal:
            self.recipe_list.addItem(recipe["name"])
            self.recipe_entries.append(recipe)

        if selected_id is not None:
            for idx, entry in enumerate(self.recipe_entries):
                if entry is not None and entry["id"] == selected_id:
                    self.recipe_list.setCurrentRow(idx)
                    self.recipe_list.scrollToItem(self.recipe_list.item(idx))
                    break
        elif self.recipe_entries:
            for idx, entry in enumerate(self.recipe_entries):
                if entry is not None:
                    self.recipe_list.setCurrentRow(idx)
                    self.recipe_list.scrollToItem(self.recipe_list.item(idx))
                    break

    def on_recipe_select(self, row: int) -> None:
        if row < 0 or row >= len(self.recipe_entries):
            self._recipe_details_set("")
            return
        entry = self.recipe_entries[row]
        if entry is None:
            self._recipe_details_set("")
            return
        recipe = entry
        item_id = self._resolve_recipe_item_id(recipe)
        if item_id is None:
            self._recipe_details_set("Item not found for selected recipe.")
            return
        item_name = fetch_item_name(self.app.conn, item_id)
        recipes = self._fetch_recipes_for_item(item_id)
        details = [f"Item: {item_name}\n"]
        for idx, recipe_row in enumerate(recipes, start=1):
            details.append(self._format_recipe_details(recipe_row, index=idx))
        self._recipe_details_set("\n\n".join(details))

    def _recipe_details_set(self, txt: str) -> None:
        self.recipe_details.setPlainText(txt)

    @staticmethod
    def _canonical_name(name: str) -> str:
        return " ".join((name or "").split()).strip().casefold()

    def _resolve_recipe_item_id(self, recipe: dict) -> int | None:
        name = (recipe["name"] or "").strip()
        if name:
            row = self.app.conn.execute(
                "SELECT id FROM items WHERE COALESCE(display_name, key)=?",
                (name,),
            ).fetchone()
            if row:
                return int(row["id"])

        rows = self.app.conn.execute(
            """
            SELECT rl.item_id, COALESCE(i.display_name, i.key) AS name
            FROM recipe_lines rl
            JOIN items i ON i.id = rl.item_id
            WHERE rl.recipe_id=? AND rl.direction='out'
            ORDER BY rl.id
            """,
            (recipe["id"],),
        ).fetchall()
        if not rows:
            return None
        return int(rows[0]["item_id"])

    def _fetch_recipes_for_item(self, item_id: int) -> list:
        return self.app.conn.execute(
            """
            SELECT r.id, r.name, r.method, r.machine, r.machine_item_id, r.grid_size,
                   r.station_item_id, r.tier, r.circuit, r.duration_ticks, r.eu_per_tick
            FROM recipes r
            JOIN recipe_lines rl ON rl.recipe_id = r.id
            WHERE rl.direction='out' AND rl.item_id=?
            GROUP BY r.id
            ORDER BY r.name, r.method, r.machine, r.tier, r.id
            """,
            (item_id,),
        ).fetchall()

    def _format_recipe_details(self, recipe: dict, *, index: int) -> str:
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
            elif line["direction"] == "in":
                slot_idx = line["input_slot_index"]
                if slot_idx is not None:
                    label = f"{label} (Slot {slot_idx})"

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

        return (
            f"Recipe {index}:\n"
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
        if row < 0 or row >= len(self.recipe_entries):
            QtWidgets.QMessageBox.information(self, "Select a recipe", "Click a recipe first.")
            return
        entry = self.recipe_entries[row]
        if entry is None:
            QtWidgets.QMessageBox.information(self, "Select a recipe", "Click a recipe first.")
            return
        recipe_id = entry["id"]
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
        if row < 0 or row >= len(self.recipe_entries):
            QtWidgets.QMessageBox.information(self, "Select a recipe", "Click a recipe first.")
            return
        recipe = self.recipe_entries[row]
        if recipe is None:
            QtWidgets.QMessageBox.information(self, "Select a recipe", "Click a recipe first.")
            return
        ok = QtWidgets.QMessageBox.question(
            self,
            "Delete recipe?",
            f"Delete recipe:\n\n{recipe['name']}",
        )
        if ok != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        duplicate_of = recipe["duplicate_of_recipe_id"]
        self.app.conn.execute("DELETE FROM recipes WHERE id=?", (recipe["id"],))
        if duplicate_of is None:
            dup_rows = self.app.conn.execute(
                "SELECT id FROM recipes WHERE duplicate_of_recipe_id=? ORDER BY id",
                (recipe["id"],),
            ).fetchall()
            if dup_rows:
                new_canonical_id = dup_rows[0]["id"]
                self.app.conn.execute(
                    "UPDATE recipes SET duplicate_of_recipe_id=NULL WHERE id=?",
                    (new_canonical_id,),
                )
                remaining_ids = [row["id"] for row in dup_rows[1:]]
                if remaining_ids:
                    placeholders = ",".join(["?"] * len(remaining_ids))
                    self.app.conn.execute(
                        f"UPDATE recipes SET duplicate_of_recipe_id=? WHERE id IN ({placeholders})",
                        (new_canonical_id, *remaining_ids),
                    )
        self.app.conn.commit()
        self.app.refresh_recipes()
        self._recipe_details_set("")
        self.app.status_bar.showMessage(f"Deleted recipe: {recipe['name']}")
