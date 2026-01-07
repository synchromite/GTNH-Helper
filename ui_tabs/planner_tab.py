import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

from services.planner import PlannerService
from ui_dialogs import AddRecipeDialog, ItemPickerDialog


class PlannerTab(ttk.Frame):
    def __init__(self, notebook: ttk.Notebook, app):
        super().__init__(notebook, padding=10)
        self.app = app
        self.planner = PlannerService(app.conn, app.profile_conn)

        self.target_item_id = None
        self.target_item_kind = None
        self.last_plan_run = False
        self.last_plan_used_inventory = False
        self.build_steps: list = []
        self.build_step_vars: list[tk.BooleanVar] = []
        self.build_step_checks: list[ttk.Checkbutton] = []
        self.build_step_labels: list[ttk.Label] = []
        self.build_step_dependencies: list[set[int]] = []
        self.build_completed_steps: set[int] = set()
        self.build_base_inventory: dict[int, int] = {}
        self.build_step_byproducts: dict[int, list[tuple[int, int]]] = {}

        notebook.add(self, text="Planner")

        ttk.Label(self, text="Plan a target item into a shopping list and optional process steps.").pack(anchor="w")

        controls = ttk.Frame(self)
        controls.pack(fill="x", pady=(10, 6))

        ttk.Label(controls, text="Target Item:").grid(row=0, column=0, sticky="w")
        self.target_item_name = tk.StringVar(value="(none)")
        ttk.Label(controls, textvariable=self.target_item_name, width=36).grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Button(controls, text="Select…", command=self.pick_target_item).grid(row=0, column=2, padx=(6, 0))

        ttk.Label(controls, text="Quantity:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.target_qty_var = tk.StringVar(value="1")
        self.target_qty_entry = ttk.Entry(controls, textvariable=self.target_qty_var, width=12)
        self.target_qty_entry.grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(6, 0))
        self.target_qty_unit = tk.StringVar(value="")
        ttk.Label(controls, textvariable=self.target_qty_unit).grid(row=1, column=2, sticky="w", padx=(6, 0), pady=(6, 0))

        self.use_inventory_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text="Use Inventory Data", variable=self.use_inventory_var).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        btns = ttk.Frame(controls)
        btns.grid(row=0, column=3, rowspan=3, sticky="e", padx=(20, 0))
        ttk.Button(btns, text="Plan", command=self.run_plan).pack(anchor="e", pady=(0, 6))
        ttk.Button(btns, text="Build", command=self.run_build).pack(anchor="e", pady=(0, 6))
        ttk.Button(btns, text="Clear", command=self.clear_results).pack(anchor="e", pady=(0, 6))
        ttk.Button(btns, text="Save Plan…", command=self.save_plan).pack(anchor="e", pady=(0, 6))
        ttk.Button(btns, text="Load Plan…", command=self.load_plan).pack(anchor="e")

        controls.columnconfigure(1, weight=1)

        self.main_pane = tk.PanedWindow(self, orient="vertical")
        self.main_pane.pack(fill="both", expand=True, pady=(8, 0))

        self.results_pane = tk.PanedWindow(self.main_pane, orient="horizontal")
        self.main_pane.add(self.results_pane, minsize=220, stretch="always")

        shopping_frame = ttk.LabelFrame(self.results_pane, text="Shopping List", padding=8)
        shopping_header = ttk.Frame(shopping_frame)
        shopping_header.pack(fill="x", pady=(0, 6))
        shopping_buttons = ttk.Frame(shopping_header)
        shopping_buttons.pack(side="right")
        ttk.Button(
            shopping_buttons,
            text="Save…",
            command=lambda: self._save_text(self.shopping_text, "shopping_list.txt"),
        ).pack(side="right")
        ttk.Button(
            shopping_buttons,
            text="Copy",
            command=lambda: self._copy_text(self.shopping_text, "Shopping list is empty."),
        ).pack(side="right", padx=(0, 6))
        self.shopping_text = tk.Text(shopping_frame, wrap="word", height=18)
        self.shopping_text.pack(fill="both", expand=True)
        self._set_text(self.shopping_text, "Run a plan to see required items.")

        self.steps_frame = ttk.LabelFrame(self.results_pane, text="Process Steps", padding=8)
        steps_header = ttk.Frame(self.steps_frame)
        steps_header.pack(fill="x", pady=(0, 6))
        steps_buttons = ttk.Frame(steps_header)
        steps_buttons.pack(side="right")
        ttk.Button(
            steps_buttons,
            text="Save…",
            command=lambda: self._save_text(self.steps_text, "process_steps.txt"),
        ).pack(side="right")
        ttk.Button(
            steps_buttons,
            text="Copy",
            command=lambda: self._copy_text(self.steps_text, "Process steps are empty."),
        ).pack(side="right", padx=(0, 6))
        self.steps_text = tk.Text(self.steps_frame, wrap="word", height=18)
        self.steps_text.pack(fill="both", expand=True)
        self._set_text(self.steps_text, "Run a plan to see steps.")

        self.results_pane.add(shopping_frame, minsize=240, stretch="always")

        self.show_steps_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            controls,
            text="Show Process Steps",
            variable=self.show_steps_var,
            command=self._toggle_steps,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        build_frame = ttk.LabelFrame(self.main_pane, text="Build Steps", padding=8)
        self.main_pane.add(build_frame, minsize=200, stretch="always")
        build_header = ttk.Frame(build_frame)
        build_header.pack(fill="x", pady=(0, 6))
        ttk.Label(build_header, text="Check off each step as you complete it.").pack(side="left")
        build_buttons = ttk.Frame(build_header)
        build_buttons.pack(side="right")
        ttk.Button(build_buttons, text="Reset Checks", command=self.reset_build_steps).pack(side="right")

        self.build_canvas = tk.Canvas(build_frame, borderwidth=0, highlightthickness=0)
        self.build_scrollbar = ttk.Scrollbar(build_frame, orient="vertical", command=self.build_canvas.yview)
        self.build_canvas.configure(yscrollcommand=self.build_scrollbar.set)
        self.build_canvas.pack(side="left", fill="both", expand=True)
        self.build_scrollbar.pack(side="right", fill="y")
        self.build_steps_container = ttk.Frame(self.build_canvas)
        self.build_canvas.create_window((0, 0), window=self.build_steps_container, anchor="nw")
        self.build_steps_container.bind(
            "<Configure>",
            lambda _e: self.build_canvas.configure(scrollregion=self.build_canvas.bbox("all")),
        )
        self._bind_mousewheel(self.build_canvas)
        self._set_build_placeholder("Run a plan, then click Build to get step-by-step instructions.")
        self._restore_state()

    def pick_target_item(self):
        if not self.app.items:
            messagebox.showinfo("No items", "There are no items to plan against.")
            return
        dlg = ItemPickerDialog(self.app, title="Pick target item")
        self.app.wait_window(dlg)
        if not dlg.result:
            return
        self.target_item_id = dlg.result["id"]
        self.target_item_kind = dlg.result["kind"]
        self.target_item_name.set(dlg.result["name"])
        self.target_qty_unit.set("L" if self.target_item_kind == "fluid" else "count")
        self._persist_state()

    def run_plan(self):
        self.planner = PlannerService(self.app.conn, self.app.profile_conn)
        if self.target_item_id is None:
            messagebox.showinfo("Select an item", "Choose a target item first.")
            return
        qty = self._parse_target_qty(show_errors=True)
        if qty is None:
            return

        self._run_plan_with_qty(qty, set_status=True)
        self.clear_build_steps(persist=False)

    def on_inventory_changed(self) -> None:
        if not self.last_plan_run or not self.last_plan_used_inventory or not self.use_inventory_var.get():
            return
        if self.target_item_id is None:
            return
        qty = self._parse_target_qty(show_errors=False)
        if qty is None:
            self.app.status.set("Planner not updated: invalid quantity.")
            return
        self._run_plan_with_qty(qty, set_status=False)
        self._refresh_build_inventory()
        self._refresh_build_steps_on_inventory_change(qty)

    def _parse_target_qty(self, *, show_errors: bool) -> int | None:
        raw_qty = self.target_qty_var.get().strip()
        if raw_qty == "":
            if show_errors:
                messagebox.showerror("Invalid quantity", "Enter a whole number.")
            return None
        try:
            qty_float = float(raw_qty)
        except ValueError:
            if show_errors:
                messagebox.showerror("Invalid quantity", "Enter a whole number.")
            return None
        if not qty_float.is_integer() or qty_float <= 0:
            if show_errors:
                messagebox.showerror("Invalid quantity", "Enter a whole number.")
            return None
        return int(qty_float)

    def _run_plan_with_qty(self, qty: int, *, set_status: bool) -> None:

        if not self._has_recipes():
            messagebox.showinfo("No recipes", "There are no recipes to plan against.")
            if set_status:
                self.app.status.set("Planner failed: missing recipes")
            return

        result = self.planner.plan(
            self.target_item_id,
            qty,
            use_inventory=self.use_inventory_var.get(),
            enabled_tiers=self.app.get_enabled_tiers(),
            crafting_6x6_unlocked=self.app.is_crafting_6x6_unlocked(),
        )

        if result.errors:
            filtered_errors = self._filter_plan_errors(result)
            if filtered_errors:
                self._handle_plan_errors(filtered_errors)
                self._set_text(self.shopping_text, "")
                self._set_text(self.steps_text, "")
                self.last_plan_run = False
                self.last_plan_used_inventory = False
                self._persist_state()
                return

        if not result.shopping_list:
            self._set_text(self.shopping_text, "Nothing needed. Inventory already covers this request.")
        else:
            lines = [f"{name} × {qty} {unit}" for name, qty, unit in result.shopping_list]
            self._set_text(self.shopping_text, "\n".join(lines))

        if result.steps:
            steps_lines = []
            for idx, step in enumerate(result.steps, start=1):
                inputs = ", ".join([f"{name} × {qty} {unit}" for _item_id, name, qty, unit in step.inputs])
                input_names = " + ".join([name for _item_id, name, _qty, _unit in step.inputs]) if step.inputs else "(none)"
                steps_lines.append(
                    f"{idx}. {input_names} → {step.output_item_name} "
                    f"(x{step.multiplier}, output {step.output_qty})\n"
                    f"   Inputs: {inputs if inputs else '(none)'}"
                )
            self._set_text(self.steps_text, "\n\n".join(steps_lines))
        else:
            self._set_text(self.steps_text, "No process steps generated.")

        self.last_plan_run = True
        self.last_plan_used_inventory = self.use_inventory_var.get()
        if set_status:
            self.app.status.set("Planner run complete")
        self._persist_state()

    def run_build(self) -> None:
        self.planner = PlannerService(self.app.conn, self.app.profile_conn)
        if self.target_item_id is None:
            messagebox.showinfo("Select an item", "Choose a target item first.")
            return
        qty = self._parse_target_qty(show_errors=True)
        if qty is None:
            return
        if not self._has_recipes():
            messagebox.showinfo("No recipes", "There are no recipes to plan against.")
            self.app.status.set("Build failed: missing recipes")
            return

        self.build_base_inventory = self.planner.load_inventory() if self.use_inventory_var.get() else {}
        self.build_completed_steps = set()
        self.build_step_byproducts = {}
        result = self.planner.plan(
            self.target_item_id,
            qty,
            use_inventory=self.use_inventory_var.get(),
            enabled_tiers=self.app.get_enabled_tiers(),
            crafting_6x6_unlocked=self.app.is_crafting_6x6_unlocked(),
        )

        if result.errors:
            self._handle_plan_errors(result.errors)
            self.clear_build_steps(persist=False)
            return

        self.build_steps = result.steps
        self._build_step_dependencies()
        self._render_build_steps()
        self._recalculate_build_steps()
        self.app.status.set("Build steps ready")

    def _build_step_dependencies(self) -> None:
        producers: dict[int, list[int]] = {}
        for idx, step in enumerate(self.build_steps):
            producers.setdefault(step.output_item_id, []).append(idx)

        self.build_step_dependencies = []
        for step in self.build_steps:
            deps: set[int] = set()
            for item_id, _name, _qty, _unit in step.inputs:
                deps.update(producers.get(item_id, []))
            self.build_step_dependencies.append(deps)

    def _render_build_steps(self) -> None:
        for widget in self.build_steps_container.winfo_children():
            widget.destroy()
        self.build_step_vars = []
        self.build_step_checks = []
        self.build_step_labels = []

        if not self.build_steps:
            self._set_build_placeholder("No build steps generated.")
            return

        for idx, step in enumerate(self.build_steps, start=1):
            row = ttk.Frame(self.build_steps_container)
            row.pack(fill="x", anchor="w", pady=2)
            var = tk.BooleanVar(value=False)
            chk = ttk.Checkbutton(
                row,
                variable=var,
                command=lambda i=idx - 1: self._on_build_step_toggle(i),
            )
            chk.pack(side="left")
            label = ttk.Label(row, text=self._format_build_step(idx, step), justify="left")
            label.pack(side="left", fill="x", expand=True, padx=(4, 0))
            self.build_step_vars.append(var)
            self.build_step_checks.append(chk)
            self.build_step_labels.append(label)

    def _format_build_step(self, idx: int, step) -> str:
        total_output = step.output_qty * step.multiplier
        input_lines = [f"{name} × {qty} {unit}" for _item_id, name, qty, unit in step.inputs]
        inputs_text = ", ".join(input_lines) if input_lines else "(none)"
        method = (step.method or "machine").strip().lower()
        if method == "crafting":
            station = step.station_item_name or "(none)"
            grid = step.grid_size or ""
            grid_label = f" ({grid})" if grid else ""
            machine_line = f"Crafting{grid_label} at {station}"
        else:
            machine_name = step.machine_item_name or step.machine or "(unknown)"
            machine_line = f"Machine: {machine_name}"
        circuit_text = "(none)" if step.circuit in (None, "") else step.circuit
        return (
            f"{idx}. Inputs: {inputs_text}\n"
            f"   {machine_line}\n"
            f"   Circuit: {circuit_text}\n"
            f"   Output: {step.output_item_name} × {total_output} {step.output_unit}"
        )

    def _set_build_placeholder(self, text: str) -> None:
        for widget in self.build_steps_container.winfo_children():
            widget.destroy()
        label = ttk.Label(self.build_steps_container, text=text, justify="left")
        label.pack(anchor="w")
        self.build_step_vars = []
        self.build_step_checks = []
        self.build_step_labels = []

    def _bind_mousewheel(self, widget: tk.Widget) -> None:
        widget.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        widget.bind_all("<Button-4>", self._on_mousewheel, add="+")
        widget.bind_all("<Button-5>", self._on_mousewheel, add="+")

    def _is_descendant(self, widget: tk.Widget | None, ancestor: tk.Widget) -> bool:
        while widget is not None:
            if widget == ancestor:
                return True
            widget = widget.master
        return False

    def _on_mousewheel(self, event) -> None:
        try:
            widget_at = self.winfo_containing(event.x_root, event.y_root)
        except KeyError:
            return
        if not self._is_descendant(widget_at, self.build_canvas):
            return
        if event.num == 4:
            delta = -1
        elif event.num == 5:
            delta = 1
        else:
            delta = -1 * int(event.delta / 120) if event.delta else 0
        if delta:
            self.build_canvas.yview_scroll(delta, "units")

    def _on_build_step_toggle(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.build_steps):
            return
        if self.build_step_vars[idx].get():
            if self.use_inventory_var.get() and not self._apply_step_inventory(idx):
                self.build_step_vars[idx].set(False)
                return
            self.build_completed_steps.add(idx)
            self._mark_dependency_chain(idx)
        else:
            if self.use_inventory_var.get() and idx in self.build_completed_steps:
                self._apply_step_inventory(idx, reverse=True)
            self.build_completed_steps.discard(idx)
        self._recalculate_build_steps()

    def _mark_dependency_chain(self, idx: int) -> None:
        stack = list(self.build_step_dependencies[idx])
        while stack:
            dep = stack.pop()
            if dep in self.build_completed_steps:
                continue
            self.build_completed_steps.add(dep)
            stack.extend(self.build_step_dependencies[dep])

    def _effective_build_inventory(self) -> dict[int, int]:
        inventory = dict(self.build_base_inventory)
        for idx in self.build_completed_steps:
            if idx < 0 or idx >= len(self.build_steps):
                continue
            step = self.build_steps[idx]
            qty = step.output_qty * step.multiplier
            inventory[step.output_item_id] = inventory.get(step.output_item_id, 0) + qty
        return inventory

    def _recalculate_build_steps(self) -> None:
        inventory = self._effective_build_inventory()
        for idx, step in enumerate(self.build_steps):
            needed = step.output_qty * step.multiplier
            auto_done = inventory.get(step.output_item_id, 0) >= needed
            is_done = auto_done or idx in self.build_completed_steps
            self.build_step_vars[idx].set(is_done)
            label = self.build_step_labels[idx]
            label.configure(foreground="gray" if is_done else "")

    def _refresh_build_inventory(self) -> None:
        if not self.build_steps:
            return
        if self.use_inventory_var.get():
            self.build_base_inventory = self.planner.load_inventory()
        else:
            self.build_base_inventory = {}
        self._recalculate_build_steps()

    def _refresh_build_steps_on_inventory_change(self, qty: int) -> None:
        if not self.build_steps or not self.use_inventory_var.get():
            return
        if not self._has_recipes():
            return

        result = self.planner.plan(
            self.target_item_id,
            qty,
            use_inventory=self.use_inventory_var.get(),
            enabled_tiers=self.app.get_enabled_tiers(),
            crafting_6x6_unlocked=self.app.is_crafting_6x6_unlocked(),
        )
        if result.errors:
            self.app.status.set("Build steps not updated: missing recipe")
            return
        self.build_base_inventory = self.planner.load_inventory()
        self.build_steps = result.steps
        self.build_completed_steps = set()
        self.build_step_byproducts = {}
        self._build_step_dependencies()
        self._render_build_steps()
        self._recalculate_build_steps()

    def _apply_step_inventory(self, idx: int, *, reverse: bool = False) -> bool:
        step = self.build_steps[idx]
        if not reverse:
            inventory = self._effective_build_inventory()
            missing = []
            for item_id, name, qty, unit in step.inputs:
                available = inventory.get(item_id, 0)
                if available < qty:
                    missing.append((item_id, name, qty, unit, available))

            if missing:
                missing_lines = [
                    f"{name}: need {qty} {unit}, have {available}"
                    for _item_id, name, qty, unit, available in missing
                ]
                message = "You don't have enough inventory to complete this step:\n\n" + "\n".join(missing_lines)
                if not messagebox.askyesno("Missing inventory", f"{message}\n\nAdd missing items to inventory?"):
                    messagebox.showinfo("Build step blocked", "Step not checked off due to missing inventory.")
                    return False

                for item_id, name, qty, unit, available in missing:
                    add_qty = simpledialog.askinteger(
                        "Add inventory",
                        f"Add how many {name} ({unit})?\nMissing {qty - available} {unit}.",
                        initialvalue=max(qty - available, 0),
                        minvalue=0,
                    )
                    if add_qty:
                        self._adjust_inventory_qty(item_id, add_qty)

                self.build_base_inventory = self.planner.load_inventory()
                inventory = self._effective_build_inventory()
                still_missing = [
                    (item_id, name, qty, unit, inventory.get(item_id, 0))
                    for item_id, name, qty, unit, _available in missing
                    if inventory.get(item_id, 0) < qty
                ]
                if still_missing:
                    messagebox.showinfo("Build step blocked", "Step not checked off due to missing inventory.")
                    return False

        direction = -1 if reverse else 1
        for item_id, _name, qty, _unit in step.inputs:
            self._adjust_inventory_qty(item_id, -qty * direction)

        output_qty = step.output_qty * step.multiplier
        self._adjust_inventory_qty(step.output_item_id, output_qty * direction)
        if not self._apply_step_byproducts(idx, direction):
            return False
        self.build_base_inventory = self.planner.load_inventory()
        return True

    def _apply_step_byproducts(self, idx: int, direction: int) -> bool:
        if direction < 0:
            applied = self.build_step_byproducts.pop(idx, [])
            for item_id, qty in applied:
                self._adjust_inventory_qty(item_id, -qty)
            return True

        step = self.build_steps[idx]
        applied: list[tuple[int, int]] = []
        for item_id, name, qty, unit, chance in step.byproducts:
            if chance >= 100:
                self._adjust_inventory_qty(item_id, qty)
                applied.append((item_id, qty))
                continue
            if not messagebox.askyesno(
                "Byproduct check",
                f"Did this step produce any {name} ({unit})?",
            ):
                continue
            add_qty = simpledialog.askinteger(
                "Add byproduct",
                f"How many {name} ({unit}) were produced?",
                minvalue=0,
            )
            if add_qty:
                self._adjust_inventory_qty(item_id, add_qty)
                applied.append((item_id, add_qty))
        if applied:
            self.build_step_byproducts[idx] = applied
        return True

    def _adjust_inventory_qty(self, item_id: int, delta: int) -> None:
        item = next((item for item in self.app.items if item["id"] == item_id), None)
        if not item:
            return
        column = "qty_liters" if (item["kind"] or "").strip().lower() == "fluid" else "qty_count"
        row = self.app.profile_conn.execute(
            f"SELECT {column} FROM inventory WHERE item_id=?",
            (item_id,),
        ).fetchone()
        current = 0
        if row and row[column] is not None:
            try:
                current = int(float(row[column]))
            except (TypeError, ValueError):
                current = 0
        new_qty = max(current + delta, 0)
        if new_qty <= 0:
            self.app.profile_conn.execute("DELETE FROM inventory WHERE item_id=?", (item_id,))
        else:
            count_val = new_qty if column == "qty_count" else None
            liter_val = new_qty if column == "qty_liters" else None
            self.app.profile_conn.execute(
                "INSERT INTO inventory(item_id, qty_count, qty_liters) VALUES(?, ?, ?) "
                "ON CONFLICT(item_id) DO UPDATE SET qty_count=excluded.qty_count, qty_liters=excluded.qty_liters",
                (item_id, count_val, liter_val),
            )
        self.app.profile_conn.commit()

    def reset_build_steps(self) -> None:
        if not self.build_steps:
            return
        self.build_completed_steps = set()
        self.build_step_byproducts = {}
        self._recalculate_build_steps()

    def clear_build_steps(self, *, persist: bool = True) -> None:
        self.build_steps = []
        self.build_completed_steps = set()
        self.build_step_dependencies = []
        self.build_base_inventory = {}
        self.build_step_byproducts = {}
        self._set_build_placeholder("Run a plan, then click Build to get step-by-step instructions.")
        if persist:
            self._persist_state()

    def _handle_plan_errors(self, errors: list[str]) -> None:
        message = "\n".join(errors)
        if self.app.editor_enabled:
            add = messagebox.askyesno(
                "Planner warning",
                f"{message}\n\nWould you like to add a recipe now?",
            )
            if add:
                dlg = AddRecipeDialog(self.app)
                self.app.wait_window(dlg)
        else:
            messagebox.askokcancel(
                "Planner warning",
                f"{message}\n\nNotify the developer or switch to edit mode and add a recipe.",
            )
        self.app.status.set("Planner failed: missing recipe")

    def _filter_plan_errors(self, result) -> list[str]:
        if not self.use_inventory_var.get():
            return result.errors
        inventory = self.planner.load_inventory()
        missing_map = {item_id: (name, qty) for item_id, name, qty in result.missing_recipes}
        filtered = [
            err
            for err in result.errors
            if not err.startswith("No recipe found for ")
        ]
        for item_id, (name, qty_needed) in missing_map.items():
            if inventory.get(item_id, 0) < qty_needed:
                filtered.append(f"No recipe found for {name}.")
        return filtered

    def _toggle_steps(self):
        self._toggle_steps_visibility()

    def _toggle_steps_visibility(self, *, persist: bool = True) -> None:
        panes = {str(pane) for pane in self.results_pane.panes()}
        steps_id = str(self.steps_frame)
        if self.show_steps_var.get():
            if steps_id not in panes:
                self.results_pane.add(self.steps_frame, minsize=200, stretch="always")
        else:
            if steps_id in panes:
                self.results_pane.forget(self.steps_frame)
        if persist:
            self._persist_state()

    def clear_results(self):
        self._set_text(self.shopping_text, "")
        self._set_text(self.steps_text, "")
        self.last_plan_run = False
        self.last_plan_used_inventory = False
        self.clear_build_steps(persist=False)
        self.app.status.set("Planner cleared")
        self._persist_state()

    def _set_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _copy_text(self, widget: tk.Text, empty_message: str) -> None:
        text = widget.get("1.0", tk.END).strip()
        if not text:
            messagebox.showinfo("Nothing to copy", empty_message)
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.app.status.set("Copied to clipboard")

    def _save_text(self, widget: tk.Text, default_name: str) -> None:
        text = widget.get("1.0", tk.END).strip()
        if not text:
            messagebox.showinfo("Nothing to save", "There is no content to save yet.")
            return
        path = filedialog.asksaveasfilename(
            title="Save Planner Output",
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[("Text Files", "*.txt"), ("All Files", "*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
        except Exception as exc:
            messagebox.showerror("Save failed", f"Could not save file.\n\nDetails: {exc}")
            return
        self.app.status.set(f"Saved planner output to {path}")

    def save_plan(self) -> None:
        state = self._current_state()
        if not state.get("shopping_text") and not state.get("steps_text"):
            messagebox.showinfo("Nothing to save", "Run a plan or load content before saving.")
            return
        path = filedialog.asksaveasfilename(
            title="Save Plan",
            defaultextension=".json",
            initialfile="planner_plan.json",
            filetypes=[("Planner Plan", "*.json"), ("All Files", "*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2)
        except Exception as exc:
            messagebox.showerror("Save failed", f"Could not save plan.\n\nDetails: {exc}")
            return
        self.app.status.set(f"Saved planner plan to {path}")

    def load_plan(self) -> None:
        path = filedialog.askopenfilename(
            title="Load Plan",
            filetypes=[("Planner Plan", "*.json"), ("All Files", "*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:
            messagebox.showerror("Load failed", f"Could not read plan.\n\nDetails: {exc}")
            return
        if not isinstance(data, dict):
            messagebox.showerror("Load failed", "Plan file is not valid.")
            return
        self._apply_loaded_state(data)
        self._persist_state()
        self.app.status.set(f"Loaded planner plan from {path}")

    def _persist_state(self) -> None:
        self.app.planner_state = self._current_state()

    def _current_state(self) -> dict[str, object]:
        return {
            "version": 1,
            "target_item_id": self.target_item_id,
            "target_item_kind": self.target_item_kind,
            "target_item_name": self.target_item_name.get(),
            "target_qty": self.target_qty_var.get(),
            "target_unit": self.target_qty_unit.get(),
            "use_inventory": self.use_inventory_var.get(),
            "shopping_text": self.shopping_text.get("1.0", tk.END).rstrip(),
            "steps_text": self.steps_text.get("1.0", tk.END).rstrip(),
            "show_steps": self.show_steps_var.get(),
            "last_plan_run": self.last_plan_run,
            "last_plan_used_inventory": self.last_plan_used_inventory,
        }

    def _restore_state(self) -> None:
        state = getattr(self.app, "planner_state", {}) or {}
        if not state:
            return
        self._apply_loaded_state(state)

    def _apply_loaded_state(self, state: dict[str, object]) -> None:
        item_id = state.get("target_item_id")
        item_name = state.get("target_item_name") or "(none)"
        item_kind = state.get("target_item_kind")
        matched = None
        if item_id is not None:
            matched = next((item for item in self.app.items if item["id"] == item_id), None)
        if matched is None and item_name:
            matched = next((item for item in self.app.items if item["name"] == item_name), None)
        if matched:
            self.target_item_id = matched["id"]
            self.target_item_kind = matched["kind"]
            self.target_item_name.set(matched["name"])
            self.target_qty_unit.set(self._unit_for_kind(matched["kind"]))
        else:
            self.target_item_id = item_id if isinstance(item_id, int) else None
            self.target_item_kind = item_kind if isinstance(item_kind, str) else None
            self.target_item_name.set(item_name)
            self.target_qty_unit.set(state.get("target_unit") or "")

        self.target_qty_var.set(state.get("target_qty") or "1")
        self.use_inventory_var.set(bool(state.get("use_inventory", True)))
        self.show_steps_var.set(bool(state.get("show_steps", False)))
        self._toggle_steps_visibility(persist=False)
        self._set_text(self.shopping_text, state.get("shopping_text", ""))
        self._set_text(self.steps_text, state.get("steps_text", ""))
        self.last_plan_run = bool(state.get("last_plan_run", bool(state.get("shopping_text") or state.get("steps_text"))))
        self.last_plan_used_inventory = bool(state.get("last_plan_used_inventory", self.use_inventory_var.get()))

    def reset_state(self) -> None:
        self.target_item_id = None
        self.target_item_kind = None
        self.target_item_name.set("(none)")
        self.target_qty_var.set("1")
        self.target_qty_unit.set("")
        self.use_inventory_var.set(True)
        self.show_steps_var.set(False)
        self.last_plan_run = False
        self.last_plan_used_inventory = False
        self._toggle_steps_visibility(persist=False)
        self._set_text(self.shopping_text, "Run a plan to see required items.")
        self._set_text(self.steps_text, "Run a plan to see steps.")
        self.clear_build_steps(persist=False)

    def _has_recipes(self) -> bool:
        try:
            row = self.app.conn.execute("SELECT COUNT(1) AS c FROM recipes").fetchone()
        except Exception:
            return False
        return bool(row and int(row["c"] or 0) > 0)

    def _unit_for_kind(self, kind: str | None) -> str:
        return "L" if (kind or "").strip().lower() == "fluid" else "count"
