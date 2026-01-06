import tkinter as tk
from tkinter import ttk, messagebox

from ui_dialogs import AddItemDialog, EditItemDialog


class ItemsTab(ttk.Frame):
    def __init__(self, notebook: ttk.Notebook, app):
        super().__init__(notebook)
        self.app = app
        self.items = []

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

    def refresh_items(self):
        self.items = self.app.conn.execute(
            "SELECT i.id, i.key, COALESCE(i.display_name, i.key) AS name, i.kind, i.is_base, i.is_machine, i.machine_tier, i.machine_input_slots, i.machine_output_slots, "
            "       k.name AS item_kind_name "
            "FROM items i "
            "LEFT JOIN item_kinds k ON k.id = i.item_kind_id "
            "ORDER BY name"
        ).fetchall()
        self.app.items = list(self.items)
        self.item_list.delete(0, tk.END)
        for it in self.items:
            self.item_list.insert(tk.END, it["name"])

        if hasattr(self.app, "inventory_tab"):
            self.app.inventory_tab.refresh_items_list()

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
            mis = it["machine_input_slots"]
            try:
                mis_i = int(mis) if mis is not None else 1
            except Exception:
                mis_i = 1
            txt += f"Input Slots: {mis_i}\n"
            mos = it["machine_output_slots"]
            try:
                mos_i = int(mos) if mos is not None else 1
            except Exception:
                mos_i = 1
            txt += f"Output Slots: {mos_i}\n"
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
        self.refresh_items()

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
        self.refresh_items()

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
        self.refresh_items()
        self._item_details_set("")
        self.app.status.set(f"Deleted item: {it['name']}")
