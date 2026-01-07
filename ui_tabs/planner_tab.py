import tkinter as tk
from tkinter import ttk, messagebox

from services.planner import PlannerService
from ui_dialogs import AddRecipeDialog, ItemPickerDialog


class PlannerTab(ttk.Frame):
    def __init__(self, notebook: ttk.Notebook, app):
        super().__init__(notebook, padding=10)
        self.app = app
        self.planner = PlannerService(app.conn, app.profile_conn)

        self.target_item_id = None
        self.target_item_kind = None

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
        ttk.Button(btns, text="Clear", command=self.clear_results).pack(anchor="e")

        controls.columnconfigure(1, weight=1)

        results = ttk.Frame(self)
        results.pack(fill="both", expand=True, pady=(8, 0))

        shopping_frame = ttk.LabelFrame(results, text="Shopping List", padding=8)
        shopping_frame.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.shopping_text = tk.Text(shopping_frame, wrap="word", height=18)
        self.shopping_text.pack(fill="both", expand=True)
        self._set_text(self.shopping_text, "Run a plan to see required items.")

        steps_frame = ttk.LabelFrame(results, text="Process Steps", padding=8)
        steps_frame.pack(side="right", fill="both", expand=True)
        self.show_steps_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            steps_frame,
            text="Show process steps",
            variable=self.show_steps_var,
            command=self._toggle_steps,
        ).pack(anchor="w", pady=(0, 6))
        self.steps_text = tk.Text(steps_frame, wrap="word", height=18)
        self.steps_text.pack(fill="both", expand=True)
        self._set_text(self.steps_text, "Run a plan to see steps.")

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

    def run_plan(self):
        self.planner = PlannerService(self.app.conn, self.app.profile_conn)
        if self.target_item_id is None:
            messagebox.showinfo("Select an item", "Choose a target item first.")
            return
        raw_qty = self.target_qty_var.get().strip()
        if raw_qty == "":
            messagebox.showerror("Invalid quantity", "Enter a whole number.")
            return
        try:
            qty_float = float(raw_qty)
        except ValueError:
            messagebox.showerror("Invalid quantity", "Enter a whole number.")
            return
        if not qty_float.is_integer() or qty_float <= 0:
            messagebox.showerror("Invalid quantity", "Enter a whole number.")
            return
        qty = int(qty_float)

        if not self._has_recipes():
            messagebox.showinfo("No recipes", "There are no recipes to plan against.")
            return

        result = self.planner.plan(
            self.target_item_id,
            qty,
            use_inventory=self.use_inventory_var.get(),
            enabled_tiers=self.app.get_enabled_tiers(),
            crafting_6x6_unlocked=self.app.is_crafting_6x6_unlocked(),
        )

        if result.errors:
            self._handle_plan_errors(result.errors)
            return

        if not result.shopping_list:
            self._set_text(self.shopping_text, "Nothing needed. Inventory already covers this request.")
        else:
            lines = [f"{name} × {qty} {unit}" for name, qty, unit in result.shopping_list]
            self._set_text(self.shopping_text, "\n".join(lines))

        if result.steps:
            steps_lines = []
            for idx, step in enumerate(result.steps, start=1):
                inputs = ", ".join([f"{name} × {qty} {unit}" for name, qty, unit in step.inputs])
                steps_lines.append(
                    f"{idx}. {step.recipe_name} → {step.output_item_name} "
                    f"(x{step.multiplier}, output {step.output_qty})\n"
                    f"   Inputs: {inputs if inputs else '(none)'}"
                )
            self._set_text(self.steps_text, "\n\n".join(steps_lines))
        else:
            self._set_text(self.steps_text, "No process steps generated.")

        self.app.status.set("Planner run complete")

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

    def _toggle_steps(self):
        if self.show_steps_var.get():
            self.steps_text.pack(fill="both", expand=True)
        else:
            self.steps_text.pack_forget()

    def clear_results(self):
        self._set_text(self.shopping_text, "")
        self._set_text(self.steps_text, "")
        self.app.status.set("Planner cleared")

    def _set_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _has_recipes(self) -> bool:
        try:
            row = self.app.conn.execute("SELECT COUNT(1) AS c FROM recipes").fetchone()
        except Exception:
            return False
        return bool(row and int(row["c"] or 0) > 0)
