import tkinter as tk
from tkinter import ttk, messagebox


class InventoryTab(ttk.Frame):
    def __init__(self, notebook: ttk.Notebook, app):
        super().__init__(notebook, padding=10)
        self.app = app

        notebook.add(self, text="Inventory")

        ttk.Label(self, text="Track what you currently have in storage.").pack(anchor="w")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, pady=10)

        left = ttk.Frame(body)
        left.pack(side="left", fill="y")

        right = ttk.Frame(body)
        right.pack(side="right", fill="both", expand=True, padx=(12, 0))

        self.inventory_list = tk.Listbox(left, width=40)
        self.inventory_list.pack(fill="y", expand=True)
        self.inventory_list.bind("<<ListboxSelect>>", self.on_inventory_select)

        self.inventory_item_name = tk.StringVar(value="")
        ttk.Label(right, textvariable=self.inventory_item_name, font=("TkDefaultFont", 11, "bold")).pack(
            anchor="w",
            pady=(0, 10),
        )

        qty_row = ttk.Frame(right)
        qty_row.pack(anchor="w")
        ttk.Label(qty_row, text="Quantity:").pack(side="left")
        self.inventory_qty_var = tk.StringVar(value="")
        self.inventory_qty_entry = ttk.Entry(qty_row, textvariable=self.inventory_qty_var, width=14)
        self.inventory_qty_entry.pack(side="left", padx=(6, 6))
        self.inventory_unit_var = tk.StringVar(value="")
        ttk.Label(qty_row, textvariable=self.inventory_unit_var).pack(side="left")

        btns = ttk.Frame(right)
        btns.pack(anchor="w", pady=(10, 0))
        ttk.Button(btns, text="Save", command=self.save_inventory_item).pack(side="left")
        ttk.Button(btns, text="Clear", command=self.clear_inventory_item).pack(side="left", padx=(6, 0))

        ttk.Label(
            right,
            text="Tip: items use counts; fluids use liters (L).",
            foreground="#666",
        ).pack(anchor="w", pady=(12, 0))

    def refresh_items_list(self):
        self.inventory_list.delete(0, tk.END)
        for it in self.app.items:
            self.inventory_list.insert(tk.END, it["name"])

    def _inventory_selected_item(self):
        sel = self.inventory_list.curselection()
        if not sel:
            return None
        if not self.app.items:
            return None
        return self.app.items[sel[0]]

    def _inventory_unit_for_item(self, item) -> str:
        kind = (item["kind"] or "").strip().lower()
        return "L" if kind == "fluid" else "count"

    def on_inventory_select(self, _evt=None):
        item = self._inventory_selected_item()
        if not item:
            return
        self.inventory_item_name.set(item["name"])
        unit = self._inventory_unit_for_item(item)
        self.inventory_unit_var.set(unit)

        row = self.app.profile_conn.execute(
            "SELECT qty_count, qty_liters FROM inventory WHERE item_id=?",
            (item["id"],),
        ).fetchone()
        if unit == "L":
            qty = row["qty_liters"] if row else None
        else:
            qty = row["qty_count"] if row else None
        self.inventory_qty_var.set("" if qty is None else self._format_inventory_qty(qty))

    def _format_inventory_qty(self, qty: float | int) -> str:
        try:
            qty_f = float(qty)
        except (TypeError, ValueError):
            return ""
        if qty_f.is_integer():
            return str(int(qty_f))
        return ""

    def save_inventory_item(self):
        item = self._inventory_selected_item()
        if not item:
            messagebox.showinfo("Select an item", "Click an item first.")
            return

        raw = self.inventory_qty_var.get().strip()
        if raw == "":
            self.app.profile_conn.execute("DELETE FROM inventory WHERE item_id=?", (item["id"],))
            self.app.profile_conn.commit()
            self.app.status.set(f"Cleared inventory for: {item['name']}")
            return

        try:
            qty_float = float(raw)
        except ValueError:
            messagebox.showerror("Invalid quantity", "Enter a whole number.")
            return

        if not qty_float.is_integer():
            messagebox.showerror("Invalid quantity", "Enter a whole number.")
            return

        qty = int(qty_float)

        unit = self._inventory_unit_for_item(item)
        qty_count = qty if unit == "count" else None
        qty_liters = qty if unit == "L" else None
        self.app.profile_conn.execute(
            "INSERT INTO inventory(item_id, qty_count, qty_liters) VALUES(?, ?, ?) "
            "ON CONFLICT(item_id) DO UPDATE SET qty_count=excluded.qty_count, qty_liters=excluded.qty_liters",
            (item["id"], qty_count, qty_liters),
        )
        self.app.profile_conn.commit()
        self.inventory_qty_var.set(str(qty))
        self.app.status.set(f"Saved inventory for: {item['name']}")

    def clear_inventory_item(self):
        self.inventory_qty_var.set("")
        self.save_inventory_item()
