from __future__ import annotations

from dataclasses import dataclass
import math
import sqlite3
from typing import Iterable


@dataclass
class PlanStep:
    recipe_id: int
    recipe_name: str
    method: str
    machine: str | None
    machine_item_id: int | None
    machine_item_name: str
    grid_size: str | None
    station_item_id: int | None
    station_item_name: str
    circuit: str | None
    output_item_id: int
    output_item_name: str
    output_qty: int
    output_unit: str
    multiplier: int
    inputs: list[tuple[int, str, int, str]]
    byproducts: list[tuple[int, str, int, str, float]]


@dataclass
class PlanResult:
    shopping_list: list[tuple[str, int, str]]
    steps: list[PlanStep]
    errors: list[str]
    missing_recipes: list[tuple[int, str, int]]


class PlannerService:
    def __init__(self, conn: sqlite3.Connection, profile_conn: sqlite3.Connection):
        self.conn = conn
        self.profile_conn = profile_conn

    # ---------- Public API ----------
    def plan(
        self,
        target_item_id: int,
        target_qty: int,
        *,
        use_inventory: bool,
        enabled_tiers: Iterable[str],
        crafting_6x6_unlocked: bool,
        inventory_override: dict[int, int] | None = None,
    ) -> PlanResult:
        items = self._load_items()
        if inventory_override is not None:
            inventory = dict(inventory_override)
        else:
            inventory = self._load_inventory() if use_inventory else {}
        errors: list[str] = []
        missing_recipes: list[tuple[int, str, int]] = []
        steps: list[PlanStep] = []
        shopping_needed: dict[int, int] = {}
        visiting: set[int] = set()

        stack = [
            {
                "state": "enter",
                "item_id": target_item_id,
                "qty_needed": target_qty,
            }
        ]

        while stack:
            frame = stack.pop()
            state = frame["state"]
            if state == "exit":
                item_id = frame["item_id"]
                plan_data = frame["plan_data"]
                steps.append(
                    PlanStep(
                        recipe_id=plan_data["recipe_id"],
                        recipe_name=plan_data["recipe_name"],
                        method=plan_data["method"],
                        machine=plan_data["machine"],
                        machine_item_id=plan_data["machine_item_id"],
                        machine_item_name=plan_data["machine_item_name"],
                        grid_size=plan_data["grid_size"],
                        station_item_id=plan_data["station_item_id"],
                        station_item_name=plan_data["station_item_name"],
                        circuit=plan_data["circuit"],
                        output_item_id=item_id,
                        output_item_name=plan_data["output_item_name"],
                        output_qty=plan_data["output_qty"],
                        output_unit=plan_data["output_unit"],
                        multiplier=plan_data["multiplier"],
                        inputs=plan_data["inputs"],
                        byproducts=plan_data["byproducts"],
                    )
                )
                visiting.remove(item_id)
                continue

            item_id = frame["item_id"]
            qty_needed = frame["qty_needed"]
            if qty_needed <= 0:
                continue

            if use_inventory:
                available = inventory.get(item_id, 0)
                if available > 0:
                    used = min(available, qty_needed)
                    inventory[item_id] = available - used
                    qty_needed -= used
                    if qty_needed <= 0:
                        continue

            item = items.get(item_id)
            if not item:
                errors.append("Unknown item selected.")
                continue

            if item["is_base"]:
                shopping_needed[item_id] = shopping_needed.get(item_id, 0) + qty_needed
                continue

            if item_id in visiting:
                errors.append(f"Detected cyclic dependency for {item['name']}.")
                continue

            recipe = self._pick_recipe_for_item(item_id, enabled_tiers, crafting_6x6_unlocked)
            if not recipe:
                errors.append(f"No recipe found for {item['name']}.")
                missing_recipes.append((item_id, item["name"], qty_needed))
                continue

            output_qty = self._recipe_output_qty(recipe["id"], item_id, item["kind"])
            if output_qty <= 0:
                errors.append(f"Recipe '{recipe['name']}' has no usable output for {item['name']}.")
                continue

            multiplier = max(1, math.ceil(qty_needed / output_qty))
            inputs = []
            input_frames = []
            input_lines = self._recipe_inputs(recipe["id"])
            for line in input_lines:
                input_item = items.get(line["item_id"])
                if not input_item:
                    continue
                input_qty = self._line_qty(line, input_item["kind"])
                if input_qty <= 0:
                    continue
                total_qty = input_qty * multiplier
                inputs.append(
                    (
                        input_item["id"],
                        input_item["name"],
                        total_qty,
                        self._unit_for_kind(input_item["kind"]),
                    )
                )
                input_frames.append(
                    {
                        "state": "enter",
                        "item_id": line["item_id"],
                        "qty_needed": total_qty,
                    }
                )

            byproducts = []
            output_lines = self._recipe_outputs(recipe["id"])
            for line in output_lines:
                if line["item_id"] == item_id:
                    continue
                output_item = items.get(line["item_id"])
                if not output_item:
                    continue
                output_qty_line = self._line_qty(line, output_item["kind"])
                if output_qty_line <= 0:
                    continue
                chance = line["chance_percent"]
                chance_value = float(chance) if chance is not None else 100.0
                byproducts.append(
                    (
                        output_item["id"],
                        output_item["name"],
                        output_qty_line * multiplier,
                        self._unit_for_kind(output_item["kind"]),
                        chance_value,
                    )
                )

            machine_item_name = ""
            if recipe["machine_item_id"] is not None:
                machine_item = items.get(recipe["machine_item_id"])
                if machine_item:
                    machine_item_name = machine_item["name"]

            station_item_name = ""
            if recipe["station_item_id"] is not None:
                station_item = items.get(recipe["station_item_id"])
                if station_item:
                    station_item_name = station_item["name"]

            visiting.add(item_id)
            stack.append(
                {
                    "state": "exit",
                    "item_id": item_id,
                    "plan_data": {
                        "recipe_id": recipe["id"],
                        "recipe_name": recipe["name"],
                        "method": (recipe["method"] or "machine").strip().lower(),
                        "machine": recipe["machine"],
                        "machine_item_id": recipe["machine_item_id"],
                        "machine_item_name": machine_item_name,
                        "grid_size": recipe["grid_size"],
                        "station_item_id": recipe["station_item_id"],
                        "station_item_name": station_item_name,
                        "circuit": None if recipe["circuit"] is None else str(recipe["circuit"]),
                        "output_item_name": item["name"],
                        "output_qty": output_qty,
                        "output_unit": self._unit_for_kind(item["kind"]),
                        "multiplier": multiplier,
                        "inputs": inputs,
                        "byproducts": byproducts,
                    },
                }
            )
            for input_frame in reversed(input_frames):
                stack.append(input_frame)

        shopping_list = []
        for item_id, qty in shopping_needed.items():
            item = items.get(item_id)
            if not item:
                continue
            shopping_list.append((item["name"], qty, self._unit_for_kind(item["kind"])))

        shopping_list.sort(key=lambda row: row[0].lower())

        return PlanResult(
            shopping_list=shopping_list,
            steps=steps,
            errors=errors,
            missing_recipes=missing_recipes,
        )

    # ---------- Data loaders ----------
    def _load_items(self) -> dict[int, dict]:
        rows = self.conn.execute(
            "SELECT id, COALESCE(display_name, key) AS name, kind, is_base FROM items ORDER BY name"
        ).fetchall()
        return {row["id"]: row for row in rows}

    def _load_inventory(self) -> dict[int, int]:
        rows = self.profile_conn.execute("SELECT item_id, qty_count, qty_liters FROM inventory").fetchall()
        inventory: dict[int, int] = {}
        for row in rows:
            qty = row["qty_liters"] if row["qty_liters"] is not None else row["qty_count"]
            if qty is None:
                continue
            try:
                qty_int = int(float(qty))
            except (TypeError, ValueError):
                continue
            inventory[row["item_id"]] = max(qty_int, 0)
        return inventory

    def load_inventory(self) -> dict[int, int]:
        return self._load_inventory()

    # ---------- Recipe helpers ----------
    def _pick_recipe_for_item(
        self,
        item_id: int,
        enabled_tiers: Iterable[str],
        crafting_6x6_unlocked: bool,
    ):
        tiers = list(enabled_tiers)
        placeholders = ",".join(["?"] * len(tiers))
        if tiers:
            tier_clause = f"AND (r.tier IS NULL OR TRIM(r.tier)='' OR r.tier IN ({placeholders})) "
        else:
            tier_clause = "AND (r.tier IS NULL OR TRIM(r.tier)='') "
        sql = (
            "SELECT r.id, r.name, r.method, r.machine, r.machine_item_id, r.grid_size, "
            "r.station_item_id, r.circuit, r.tier, "
            "COALESCE(SUM(CASE WHEN rl_in.direction='in' THEN 1 ELSE 0 END), 0) AS input_count, "
            "COALESCE(SUM(CASE WHEN rl_in.direction='in' "
            "THEN COALESCE(rl_in.qty_count, rl_in.qty_liters, 1) ELSE 0 END), 0) AS input_qty "
            "FROM recipes r "
            "JOIN recipe_lines rl_out ON rl_out.recipe_id = r.id "
            "LEFT JOIN recipe_lines rl_in ON rl_in.recipe_id = r.id AND rl_in.direction='in' "
            "WHERE rl_out.direction='out' AND rl_out.item_id=? "
            f"{tier_clause}"
            "GROUP BY r.id "
            "ORDER BY r.name"
        )
        params = [item_id]
        if tiers:
            params.extend(tiers)
        rows = self.conn.execute(sql, params).fetchall()
        if not crafting_6x6_unlocked:
            rows = [r for r in rows if not (r["method"] == "crafting" and (r["grid_size"] or "").strip() == "6x6")]
        if not rows:
            return None

        tier_order = {tier: index for index, tier in enumerate(tiers)}

        def recipe_rank(row) -> tuple[int, int, float, str]:
            tier = (row["tier"] or "").strip()
            if not tier:
                tier_rank = -1
            else:
                tier_rank = tier_order.get(tier, len(tier_order) + 1)
            return (
                tier_rank,
                int(row["input_count"] or 0),
                float(row["input_qty"] or 0),
                (row["name"] or "").lower(),
            )

        return min(rows, key=recipe_rank)

    def _recipe_output_qty(self, recipe_id: int, item_id: int, kind: str) -> int:
        row = self.conn.execute(
            "SELECT qty_count, qty_liters FROM recipe_lines WHERE recipe_id=? AND direction='out' AND item_id=?",
            (recipe_id, item_id),
        ).fetchone()
        if not row:
            return 0
        return self._qty_from_row(row, kind)

    def _recipe_inputs(self, recipe_id: int):
        return self.conn.execute(
            "SELECT item_id, qty_count, qty_liters FROM recipe_lines WHERE recipe_id=? AND direction='in'",
            (recipe_id,),
        ).fetchall()

    def _recipe_outputs(self, recipe_id: int):
        return self.conn.execute(
            "SELECT item_id, qty_count, qty_liters, chance_percent FROM recipe_lines "
            "WHERE recipe_id=? AND direction='out'",
            (recipe_id,),
        ).fetchall()

    # ---------- Quantity helpers ----------
    def _qty_from_row(self, row, kind: str) -> int:
        qty = row["qty_liters"] if kind == "fluid" else row["qty_count"]
        if qty is None:
            return 1
        try:
            qty_int = int(float(qty))
        except (TypeError, ValueError):
            return 0
        return max(qty_int, 0)

    def _line_qty(self, line, kind: str) -> int:
        return self._qty_from_row(line, kind)

    def _unit_for_kind(self, kind: str) -> str:
        return "L" if (kind or "").strip().lower() == "fluid" else "count"
