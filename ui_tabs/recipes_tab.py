import tkinter as tk
from tkinter import ttk, messagebox

from services.recipes import (
    fetch_item_name,
    fetch_machine_output_slots,
    fetch_recipe_lines,
    fetch_recipes,
)
from ui_dialogs import AddRecipeDialog, EditRecipeDialog


class RecipesTab(ttk.Frame):
    def __init__(self, notebook: ttk.Notebook, app):
        super().__init__(notebook)
        self.app = app
        self.recipes = []

        notebook.add(self, text="Recipes")

        left = ttk.Frame(self, padding=8)
        left.pack(side="left", fill="y")

        right = ttk.Frame(self, padding=8)
        right.pack(side="right", fill="both", expand=True)

        self.recipe_list = tk.Listbox(left, width=40)
        self.recipe_list.pack(fill="y", expand=True)
        self.recipe_list.bind("<<ListboxSelect>>", self.on_recipe_select)
        if self.app.editor_enabled:
            self.recipe_list.bind("<Double-Button-1>", lambda _e: self.open_edit_recipe_dialog())

        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(8, 0))
        self.btn_add_recipe = ttk.Button(btns, text="Add Recipe", command=self.open_add_recipe_dialog)
        self.btn_edit_recipe = ttk.Button(btns, text="Edit Recipe", command=self.open_edit_recipe_dialog)
        self.btn_del_recipe = ttk.Button(btns, text="Delete Recipe", command=self.delete_selected_recipe)
        self.btn_add_recipe.pack(side="left")
        self.btn_edit_recipe.pack(side="left", padx=6)
        self.btn_del_recipe.pack(side="left")
        if not self.app.editor_enabled:
            self.btn_add_recipe.configure(state="disabled")
            self.btn_edit_recipe.configure(state="disabled")
            self.btn_del_recipe.configure(state="disabled")

        self.recipe_details = tk.Text(right, wrap="word")
        self.recipe_details.pack(fill="both", expand=True)
        self.recipe_details.configure(state="disabled")

    def refresh_recipes(self):
        enabled = self.app.get_enabled_tiers()
        self.recipes = fetch_recipes(self.app.conn, enabled)
        self.recipe_list.delete(0, tk.END)
        for r in self.recipes:
            self.recipe_list.insert(tk.END, r["name"])

    def on_recipe_select(self, _evt=None):
        sel = self.recipe_list.curselection()
        if not sel:
            return
        r = self.recipes[sel[0]]

        lines = fetch_recipe_lines(self.app.conn, r["id"])

        ins = []
        outs = []

        def fmt_qty(val):
            if val is None:
                return None
            try:
                return int(float(val))
            except (TypeError, ValueError):
                return val

        for x in lines:
            if x["qty_liters"] is not None:
                qty = fmt_qty(x["qty_liters"])
                s = f"{x['name']} × {qty} L"
            else:
                qty = fmt_qty(x["qty_count"])
                s = f"{x['name']} × {qty}"

            if x["direction"] == "out":
                slot_idx = x["output_slot_index"]
                if slot_idx is not None:
                    s = f"{s} (Slot {slot_idx})"
                ch = x["chance_percent"]
                if ch is not None:
                    try:
                        ch_f = float(ch)
                    except Exception:
                        ch_f = 100.0
                    if ch_f < 99.999:
                        s = f"{s} ({ch_f:g}%)"

            (ins if x["direction"] == "in" else outs).append(s)

        duration_s = None
        if r["duration_ticks"] is not None:
            duration_s = int(r["duration_ticks"] / 20)

        method = (r["method"] or "machine").strip().lower()
        method_label = "Crafting" if method == "crafting" else "Machine"

        station_name = ""
        if method == "crafting" and r["station_item_id"] is not None:
            station_name = fetch_item_name(self.app.conn, r["station_item_id"])

        method_lines = [f"Method: {method_label}"]
        if method == "crafting":
            method_lines.append(f"Grid: {r['grid_size'] or ''}")
            method_lines.append(f"Station: {station_name}")
        else:
            mline = f"Machine: {r['machine'] or ''}"
            mid = r["machine_item_id"]
            if mid is not None:
                mos = fetch_machine_output_slots(self.app.conn, mid)
                if mos is not None:
                    mline = f"{mline} (output slots: {mos})"
            method_lines.append(mline)

        txt = (
            f"Name: {r['name']}\n"
            + "\n".join(method_lines)
            + "\n"
            f"Tier: {r['tier'] or ''}\n"
            f"Circuit: {'' if r['circuit'] is None else r['circuit']}\n"
            f"Duration: {'' if duration_s is None else str(duration_s)+'s'}\n"
            f"EU/t: {'' if r['eu_per_tick'] is None else r['eu_per_tick']}\n\n"
            f"Inputs:\n  "
            + ("\n  ".join(ins) if ins else "(none)")
            + "\n\n"
            f"Outputs:\n  "
            + ("\n  ".join(outs) if outs else "(none)")
            + "\n"
        )
        self._recipe_details_set(txt)

    def _recipe_details_set(self, txt: str):
        self.recipe_details.configure(state="normal")
        self.recipe_details.delete("1.0", tk.END)
        self.recipe_details.insert("1.0", txt)
        self.recipe_details.configure(state="disabled")

    def open_add_recipe_dialog(self):
        if not self.app.editor_enabled:
            messagebox.showinfo("Editor locked", "Adding Recipes is only available in editor mode.")
            return
        dlg = AddRecipeDialog(self.app)
        self.app.wait_window(dlg)
        self.refresh_recipes()

    def open_edit_recipe_dialog(self):
        if not self.app.editor_enabled:
            messagebox.showinfo("Editor locked", "Editing Recipes is only available in editor mode.")
            return
        sel = self.recipe_list.curselection()
        if not sel:
            messagebox.showinfo("Select a recipe", "Click a recipe first.")
            return
        recipe_id = self.recipes[sel[0]]["id"]
        dlg = EditRecipeDialog(self.app, recipe_id)
        self.app.wait_window(dlg)
        self.refresh_recipes()

    def delete_selected_recipe(self):
        if not self.app.editor_enabled:
            messagebox.showinfo("Editor locked", "Deleting Recipes is only available in editor mode.")
            return
        sel = self.recipe_list.curselection()
        if not sel:
            messagebox.showinfo("Select a recipe", "Click a recipe first.")
            return
        r = self.recipes[sel[0]]
        ok = messagebox.askyesno("Delete recipe?", f"Delete recipe:\n\n{r['name']}")
        if not ok:
            return
        self.app.conn.execute("DELETE FROM recipes WHERE id=?", (r["id"],))
        self.app.conn.commit()
        self.refresh_recipes()
        self._recipe_details_set("")
        self.app.status.set(f"Deleted recipe: {r['name']}")
