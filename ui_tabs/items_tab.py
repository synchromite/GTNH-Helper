import tkinter as tk
from tkinter import ttk, messagebox

from ui_dialogs import AddItemDialog, EditItemDialog


class ItemsTab(ttk.Frame):
    def __init__(self, notebook: ttk.Notebook, app):
        super().__init__(notebook)
        self.app = app
        self.items: list = []

        notebook.add(self, text="Items")

        left = ttk.Frame(self, padding=8)
        left.pack(side="left", fill="y")

        right = ttk.Frame(self, padding=8)
        right.pack(side="right", fill="both", expand=True)

        self.item_list = tk.Listbox(left, width=40)
        self.item_list.pack(fill="y", expand=True)
        self.item_list.bind("<<ListboxSelect>>", self.on_item_select)
        if self.app.editor_enabled:
            self.item_list.bind("<Double-Button-1>", lambda _e: self.open_edit_item_dialog())

        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(8, 0))
        self.btn_add_item = ttk.Button(btns, text="Add Item", command=self.open_add_item_dialog)
        self.btn_edit_item = ttk.Button(btns, text="Edit Item", command=self.open_edit_item_dialog)
        self.btn_del_item = ttk.Button(btns, text="Delete Item", command=self.delete_selected_item)
        self.btn_add_item.pack(side="left")
        self.btn_edit_item.pack(side="left", padx=6)
        self.btn_del_item.pack(side="left")
        if not self.app.editor_enabled:
            self.btn_add_item.configure(state="disabled")
            self.btn_edit_item.configure(state="disabled")
            self.btn_del_item.configure(state="disabled")

        self.item_details = tk.Text(right, height=10, wrap="word")
        self.item_details.pack(fill="both", expand=True)
        self.item_details.configure(state="disabled")

    def render_items(self, items: list) -> None:
        self.items = list(items)
        self.item_list.delete(0, tk.END)
        for it in self.items:
            self.item_list.insert(tk.END, it["name"])

    def on_item_select(self, _evt=None):
        sel = self.item_list.curselection()
        if not sel:
            return
        it = self.items[sel[0]]
        txt = (
            f"Name: {it['name']}\n"
            f"Kind: {it['kind']}\n"
            f"Item Kind: {it['item_kind_name'] or ''}\n"
            f"Base: {'Yes' if it['is_base'] else 'No'}\n"
        )
        is_machine_kind = ((it["item_kind_name"] or "").strip().lower() == "machine") or bool(it["is_machine"])
        if is_machine_kind:
            txt += f"Machine Tier: {it['machine_tier'] or ''}\n"
            def _as_int(value, default=0):
                try:
                    return int(value)
                except Exception:
                    return default

            mis_i = _as_int(it["machine_input_slots"], default=1) or 1
            txt += f"Input Slots: {mis_i}\n"
            mos_i = _as_int(it["machine_output_slots"], default=1) or 1
            txt += f"Output Slots: {mos_i}\n"
            txt += f"Storage Slots: {_as_int(it['machine_storage_slots'])}\n"
            txt += f"Power Slots: {_as_int(it['machine_power_slots'])}\n"
            txt += f"Circuit Slots: {_as_int(it['machine_circuit_slots'])}\n"
            in_tanks = _as_int(it["machine_input_tanks"])
            in_cap = _as_int(it["machine_input_tank_capacity_l"])
            if in_tanks > 0 or in_cap > 0:
                cap_txt = f" ({in_cap} L)" if in_cap > 0 else ""
                txt += f"Input Tanks: {in_tanks}{cap_txt}\n"
            out_tanks = _as_int(it["machine_output_tanks"])
            out_cap = _as_int(it["machine_output_tank_capacity_l"])
            if out_tanks > 0 or out_cap > 0:
                cap_txt = f" ({out_cap} L)" if out_cap > 0 else ""
                txt += f"Output Tanks: {out_tanks}{cap_txt}\n"
        self._item_details_set(txt)

    def _item_details_set(self, txt: str):
        self.item_details.configure(state="normal")
        self.item_details.delete("1.0", tk.END)
        self.item_details.insert("1.0", txt)
        self.item_details.configure(state="disabled")

    def open_add_item_dialog(self):
        if not self.app.editor_enabled:
            messagebox.showinfo(
                "Editor locked",
                "This copy is running in client mode.\n\nTo enable editing, create a file named '.enable_editor' next to the app.",
            )
            return
        dlg = AddItemDialog(self.app)
        self.app.wait_window(dlg)
        self.app.refresh_items()

    def open_edit_item_dialog(self):
        if not self.app.editor_enabled:
            messagebox.showinfo("Editor locked", "Editing Items is only available in editor mode.")
            return
        sel = self.item_list.curselection()
        if not sel:
            messagebox.showinfo("Select an item", "Click an item first.")
            return
        item_id = self.items[sel[0]]["id"]
        dlg = EditItemDialog(self.app, item_id)
        self.app.wait_window(dlg)
        self.app.refresh_items()

    def delete_selected_item(self):
        if not self.app.editor_enabled:
            messagebox.showinfo("Editor locked", "Deleting Items is only available in editor mode.")
            return
        sel = self.item_list.curselection()
        if not sel:
            messagebox.showinfo("Select an item", "Click an item first.")
            return
        it = self.items[sel[0]]
        ok = messagebox.askyesno("Delete item?", f"Delete item:\n\n{it['name']}")
        if not ok:
            return
        try:
            self.app.conn.execute("DELETE FROM items WHERE id=?", (it["id"],))
            self.app.conn.commit()
        except Exception as e:
            messagebox.showerror(
                "Cannot delete",
                "This item is referenced by a recipe.\nRemove it from recipes first.\n\n"
                f"Details: {e}",
            )
            return
        self.app.refresh_items()
        self._item_details_set("")
        self.app.status.set(f"Deleted item: {it['name']}")
