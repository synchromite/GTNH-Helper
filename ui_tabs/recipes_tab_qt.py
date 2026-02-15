from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from services.recipes import fetch_item_name, fetch_machine_output_slots, fetch_recipe_lines
from ui_dialogs import AddRecipeDialog, EditRecipeDialog


class RecipesTab(QtWidgets.QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.recipes: list = []
        self.recipe_item_node_map: dict[QtWidgets.QTreeWidgetItem, int] = {}
        root_layout = QtWidgets.QHBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)

        left = QtWidgets.QVBoxLayout()
        root_layout.addLayout(left, stretch=0)

        right = QtWidgets.QVBoxLayout()
        root_layout.addLayout(right, stretch=1)

        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("Search by item name...")
        self.search_edit.textChanged.connect(self._on_search_changed)
        left.addWidget(self.search_edit)

        self.recipe_tree = QtWidgets.QTreeWidget()
        self.recipe_tree.setHeaderHidden(True)
        self.recipe_tree.setMinimumWidth(240)
        self.recipe_tree.currentItemChanged.connect(self.on_recipe_select)
        if self.app.editor_enabled:
            self.recipe_tree.itemDoubleClicked.connect(lambda _item, _column=0: self.open_edit_recipe_dialog())
        left.addWidget(self.recipe_tree, stretch=1)

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
        self._all_recipes: list = []

    def render_recipes(self, recipes: list) -> None:
        selected_item_id = None
        focus_id = getattr(self.app, "recipe_focus_id", None)
        current_item = self.recipe_tree.currentItem()
        if current_item is not None:
            selected_item_id = self.recipe_item_node_map.get(current_item)

        self._all_recipes = list(recipes)
        search_text = (self.search_edit.text() or "").strip()
        self.recipes = self._filter_recipes_by_item_name(self._all_recipes, search_text)
        self.recipe_tree.clear()

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

        self.recipe_item_node_map = {}
        item_nodes: dict[int, QtWidgets.QTreeWidgetItem] = {}
        output_rows = self._fetch_recipe_outputs(normal)
        grouped: dict[str, dict[str, dict[str | None, dict[int, dict]]]] = {
            "item": {},
            "fluid": {},
            "gas": {},
        }

        def _label(value: str | None, fallback: str) -> str:
            if value is None:
                return fallback
            value = value.strip().replace("_", " ")
            return value if value else fallback

        recipes_by_id = {recipe["id"]: recipe for recipe in normal}
        outputs_by_recipe: dict[int, list[dict]] = {}
        for row in output_rows:
            outputs_by_recipe.setdefault(row["recipe_id"], []).append(row)

        preferred_output_item: dict[int, int] = {}
        for recipe_id, rows in outputs_by_recipe.items():
            recipe = recipes_by_id.get(recipe_id)
            if recipe is None:
                continue
            recipe_name = self._canonical_name(recipe["name"])
            preferred_item_id = rows[0]["item_id"]
            if recipe_name:
                for row in rows:
                    if self._canonical_name(row["item_name"]) == recipe_name:
                        preferred_item_id = row["item_id"]
                        break
            preferred_output_item[recipe_id] = preferred_item_id
            if focus_id is not None and recipe_id == focus_id:
                selected_item_id = preferred_item_id
                self.app.recipe_focus_id = None

        for row in output_rows:
            recipe = recipes_by_id.get(row["recipe_id"])
            if recipe is None:
                continue
            kind = (row["kind"] or "item").strip().lower()
            if kind not in grouped:
                kind = "item"
            item_kind_label = _label(row["item_kind_name"], "(No kind)")
            material_label = row["material_name"]
            if material_label is not None:
                material_label = material_label.strip()
                if not material_label:
                    material_label = None
            grouped.setdefault(kind, {})
            grouped[kind].setdefault(item_kind_label, {})
            grouped[kind][item_kind_label].setdefault(material_label, {})
            item_group = grouped[kind][item_kind_label][material_label]
            item_id = row["item_id"]
            if item_id not in item_group:
                item_group[item_id] = {"name": row["item_name"]}

        group_order = [("Items", "item"), ("Fluids", "fluid"), ("Gases", "gas")]
        for label, kind in group_order:
            kind_groups = grouped.get(kind, {})
            if not kind_groups:
                continue
            parent = QtWidgets.QTreeWidgetItem([label])
            parent.setExpanded(True)
            self.recipe_tree.addTopLevelItem(parent)
            for item_kind_label in sorted(kind_groups.keys(), key=lambda val: val.casefold()):
                item_kind_node = QtWidgets.QTreeWidgetItem([item_kind_label])
                parent.addChild(item_kind_node)
                material_groups = kind_groups[item_kind_label]
                for material_label in sorted(
                    material_groups.keys(),
                    key=lambda val: "" if val is None else val.casefold(),
                ):
                    item_groups = material_groups[material_label]
                    if material_label is None:
                        material_node = item_kind_node
                    else:
                        material_node = QtWidgets.QTreeWidgetItem([material_label])
                        item_kind_node.addChild(material_node)
                    for item_id in sorted(
                        item_groups.keys(),
                        key=lambda val: item_groups[val]["name"].casefold(),
                    ):
                        item_info = item_groups[item_id]
                        item_node = QtWidgets.QTreeWidgetItem([item_info["name"]])
                        item_node.setData(0, QtCore.Qt.UserRole, item_id)
                        material_node.addChild(item_node)
                        self.recipe_item_node_map[item_node] = item_id
                        item_nodes[item_id] = item_node

        if selected_item_id is not None:
            target_item = item_nodes.get(selected_item_id)
            if target_item is not None:
                self.recipe_tree.setCurrentItem(target_item)
                self._expand_to_item(target_item)
        elif item_nodes:
            first_item = next(iter(item_nodes.values()))
            self.recipe_tree.setCurrentItem(first_item)
            self._expand_to_item(first_item)
        else:
            self._recipe_details_set("")

    def _on_search_changed(self, _value: str) -> None:
        self.render_recipes(self._all_recipes)

    def _filter_recipes_by_item_name(self, recipes: list[dict], search_text: str) -> list[dict]:
        query = search_text.strip().casefold()
        if not query:
            return list(recipes)

        recipe_ids = [recipe["id"] for recipe in recipes]
        if not recipe_ids:
            return []

        placeholders = ",".join(["?"] * len(recipe_ids))
        rows = self.app.conn.execute(
            f"""
            SELECT DISTINCT rl.recipe_id
            FROM recipe_lines rl
            JOIN items i ON i.id = rl.item_id
            LEFT JOIN item_kinds k ON k.id = i.item_kind_id
            LEFT JOIN materials m ON m.id = i.material_id
            WHERE rl.recipe_id IN ({placeholders})
              AND rl.direction='out'
              AND (
                LOWER(COALESCE(i.display_name, i.key, '')) LIKE ?
                OR LOWER(COALESCE(k.name, '')) LIKE ?
                OR LOWER(COALESCE(m.name, '')) LIKE ?
                OR LOWER(COALESCE(i.kind, '')) LIKE ?
              )
            """,
            (*recipe_ids, f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%"),
        ).fetchall()
        matched_ids = {row["recipe_id"] for row in rows}
        if not matched_ids:
            return []
        return [recipe for recipe in recipes if recipe["id"] in matched_ids]

    def on_recipe_select(
        self,
        current: QtWidgets.QTreeWidgetItem | None,
        _previous: QtWidgets.QTreeWidgetItem | None = None,
    ) -> None:
        if current is None:
            self._recipe_details_set("")
            return
        item_id = self.recipe_item_node_map.get(current)
        if item_id is None:
            self._recipe_details_set("")
            return
        self._render_item_recipes(item_id)

    def _expand_to_item(self, item: QtWidgets.QTreeWidgetItem) -> None:
        current = item
        while current is not None:
            current.setExpanded(True)
            current = current.parent()

    def _recipe_details_set(self, txt: str) -> None:
        self.recipe_details.setPlainText(txt)

    def _render_item_recipes(self, item_id: int) -> None:
        item_name = fetch_item_name(self.app.conn, item_id)
        recipes = self._fetch_recipes_for_item(item_id)
        details = [f"Item: {item_name}\n"]
        for idx, recipe_row in enumerate(recipes, start=1):
            details.append(self._format_recipe_details(recipe_row, index=idx))
        self._recipe_details_set("\n\n".join(details))

    @staticmethod
    def _canonical_name(name: str) -> str:
        return " ".join((name or "").split()).strip().casefold()

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

    def _fetch_recipe_outputs(self, recipes: list[dict]) -> list[dict]:
        recipe_ids = [recipe["id"] for recipe in recipes]
        if not recipe_ids:
            return []
        placeholders = ",".join(["?"] * len(recipe_ids))
        return self.app.conn.execute(
            f"""
            SELECT rl.recipe_id,
                   rl.item_id,
                   i.kind,
                   COALESCE(i.display_name, i.key) AS item_name,
                   k.name AS item_kind_name,
                   m.name AS material_name
            FROM recipe_lines rl
            JOIN items i ON i.id = rl.item_id
            LEFT JOIN item_kinds k ON k.id = i.item_kind_id
            LEFT JOIN materials m ON m.id = i.material_id
            WHERE rl.direction='out' AND rl.recipe_id IN ({placeholders})
            ORDER BY rl.recipe_id, rl.id
            """,
            tuple(recipe_ids),
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
        recipe_id = self._select_recipe_for_current_item()
        if recipe_id is None:
            return
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
        recipe_id = self._select_recipe_for_current_item()
        if recipe_id is None:
            return
        recipe = self.app.conn.execute("SELECT id, name, duplicate_of_recipe_id FROM recipes WHERE id=?", (recipe_id,)).fetchone()
        if recipe is None:
            QtWidgets.QMessageBox.information(self, "Select a recipe", "Select a recipe entry first.")
            return
        ok = QtWidgets.QMessageBox.question(
            self,
            "Delete recipe?",
            f"Delete recipe:\n\n{recipe['name']}",
        )
        if ok != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        duplicate_of = recipe["duplicate_of_recipe_id"]
        self.app.conn.execute("DELETE FROM recipes WHERE id=?", (recipe_id,))
        if duplicate_of is None:
            dup_rows = self.app.conn.execute(
                "SELECT id FROM recipes WHERE duplicate_of_recipe_id=? ORDER BY id",
                (recipe_id,),
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

    def _select_recipe_for_current_item(self) -> int | None:
        current_item = self.recipe_tree.currentItem()
        item_id = self.recipe_item_node_map.get(current_item) if current_item is not None else None
        if item_id is None:
            QtWidgets.QMessageBox.information(self, "Select a recipe", "Select an item with recipes first.")
            return None
        recipes = self._fetch_recipes_for_item(item_id)
        if not recipes:
            QtWidgets.QMessageBox.information(self, "Select a recipe", "No recipes found for this item.")
            return None
        if len(recipes) == 1:
            return recipes[0]["id"]
        labels = []
        recipe_by_label = {}
        for recipe in recipes:
            method = (recipe["method"] or "machine").strip().title()
            machine = (recipe["machine"] or "").strip()
            label = f"{recipe['name']} ({method}{' - ' + machine if machine else ''})"
            labels.append(label)
            recipe_by_label[label] = recipe["id"]
        choice, ok = QtWidgets.QInputDialog.getItem(
            self,
            "Select recipe",
            "Choose a recipe:",
            labels,
            0,
            False,
        )
        if not ok:
            return None
        return recipe_by_label.get(choice)
