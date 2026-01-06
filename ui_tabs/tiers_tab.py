import tkinter as tk
from tkinter import ttk, messagebox

from db import ALL_TIERS


class TiersTab(ttk.Frame):
    def __init__(self, notebook: ttk.Notebook, app):
        super().__init__(notebook, padding=10)
        self.app = app
        self.tier_vars: dict[str, tk.BooleanVar] = {}

        notebook.add(self, text="Tiers")

        ttk.Label(self, text="Select tiers you currently have access to.").pack(anchor="w")

        grid = ttk.Frame(self)
        grid.pack(fill="x", pady=10)

        cols = 3
        for i, t in enumerate(ALL_TIERS):
            var = tk.BooleanVar(value=False)
            self.tier_vars[t] = var
            r = i // cols
            c = i % cols
            ttk.Checkbutton(
                grid,
                text=t,
                variable=var,
                command=lambda tier=t: self._on_tier_toggle(tier),
            ).grid(row=r, column=c, sticky="w", padx=8, pady=4)

        btns = ttk.Frame(self)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Save", command=self._tiers_save_to_db).pack(side="left")

        unlocks = ttk.LabelFrame(self, text="Crafting", padding=10)
        unlocks.pack(fill="x", pady=(12, 0))
        self.unlocked_6x6_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            unlocks,
            text="6x6 Crafting unlocked (once you've made a crafting table with a crafting grid)",
            variable=self.unlocked_6x6_var,
        ).pack(anchor="w")

        ttk.Label(
            self,
            text="Note: this controls dropdown tiers and filters the Recipes list (no planner logic yet).",
            foreground="#666",
        ).pack(anchor="w", pady=(10, 0))

    def load_from_db(self):
        enabled = set(self.app.get_enabled_tiers())
        for t, var in self.tier_vars.items():
            var.set(t in enabled)

        self.unlocked_6x6_var.set(self.app.is_crafting_6x6_unlocked())

    def _on_tier_toggle(self, tier: str) -> None:
        var = self.tier_vars.get(tier)
        if not var:
            return

        try:
            tier_index = ALL_TIERS.index(tier)
        except ValueError:
            return

        if var.get():
            for lower_tier in ALL_TIERS[: tier_index + 1]:
                lower_var = self.tier_vars.get(lower_tier)
                if lower_var and not lower_var.get():
                    lower_var.set(True)

            if "Steam Age" in ALL_TIERS[: tier_index + 1]:
                if not self.unlocked_6x6_var.get():
                    self.unlocked_6x6_var.set(True)
        else:
            for higher_tier in ALL_TIERS[tier_index + 1 :]:
                higher_var = self.tier_vars.get(higher_tier)
                if higher_var and higher_var.get():
                    higher_var.set(False)

            steam_var = self.tier_vars.get("Steam Age")
            if steam_var is not None and not steam_var.get():
                if self.unlocked_6x6_var.get():
                    self.unlocked_6x6_var.set(False)

    def _tiers_save_to_db(self):
        enabled = [t for t, var in self.tier_vars.items() if var.get()]
        if not enabled:
            messagebox.showerror("Pick at least one", "Enable at least one tier.")
            return
        self.app.set_enabled_tiers(enabled)

        self.app.set_crafting_6x6_unlocked(bool(self.unlocked_6x6_var.get()))

        self.app.recipes_tab.refresh_recipes()
        self.app.recipes_tab._recipe_details_set("")
        self.app.status.set(f"Saved tiers: {', '.join(enabled)}")
