from __future__ import annotations

from dataclasses import dataclass
import math
import sqlite3
from typing import Iterable

from services.db import ALL_TIERS

GT_VOLTAGES = [
    (8, "ULV"), (32, "LV"), (128, "MV"), (512, "HV"), (2048, "EV"),
    (8192, "IV"), (32768, "LuV"), (131072, "ZPM"), (524288, "UV"),
    (2147483647, "MAX")
]
TIER_ORDER = {tier: idx for idx, tier in enumerate(ALL_TIERS)}


def set_tier_order(tiers: Iterable[str]) -> None:
    TIER_ORDER.clear()
    for idx, tier in enumerate(tiers):
        TIER_ORDER[str(tier)] = idx


def _tier_rank(tier: str | None) -> int | None:
    if not tier:
        return None
    return TIER_ORDER.get(tier.strip())


def _highest_tier(tiers: Iterable[str]) -> str | None:
    best = None
    best_rank = -1
    for tier in tiers:
        rank = _tier_rank(tier)
        if rank is None:
            continue
        if rank > best_rank:
            best_rank = rank
            best = tier
    return best


def apply_overclock(
    duration_ticks: float | int | None,
    eu_per_tick: float | int | None,
    recipe_tier: str | None,
    machine_tier: str | None,
) -> tuple[int | None, int | None]:
    if not machine_tier:
        return duration_ticks, eu_per_tick
    recipe_rank = _tier_rank(recipe_tier)
    machine_rank = _tier_rank(machine_tier)
    if recipe_rank is None or machine_rank is None or machine_rank <= recipe_rank:
        return duration_ticks, eu_per_tick
    diff = machine_rank - recipe_rank

    scaled_duration = duration_ticks
    if duration_ticks is not None:
        duration_value = float(duration_ticks)
        if duration_value > 0:
            scaled_duration = max(1, int(math.ceil(duration_value / (2**diff))))

    scaled_eu = eu_per_tick
    if eu_per_tick is not None:
        eu_value = float(eu_per_tick)
        if eu_value > 0:
            scaled_eu = max(0, int(math.ceil(eu_value * (4**diff))))

    return scaled_duration, scaled_eu

def get_calculated_tier(row: sqlite3.Row) -> str:
    """Determine the effective tier of a recipe from its explicit tier OR its voltage."""
    # 1. Trust explicit DB tier if present (e.g. "Steam Age", "Stone Age", "LV")
    tier_str = (row["tier"] or "").strip()
    if tier_str:
        return tier_str

    # 2. Crafting recipes default to Stone Age if no tier specified
    method = (row["method"] or "").strip().lower()
    if method == "crafting":
        return "Stone Age"

    # 3. Fallback: Calculate electrical tier from EU/t
    try:
        eu = int(float(row["eu_per_tick"] or 0))
    except (ValueError, TypeError):
        eu = 0
        
    if eu <= 0:
        return "Stone Age" # Assume manual/primitive if 0 EU

    for voltage, name in GT_VOLTAGES:
        if eu <= voltage:
            return name
    return "MAX"


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
    required_base_list: list[tuple[str, int, int, str]]
    storage_requirements: list[tuple[str, int, int, str]]
    steps: list[PlanStep]
    errors: list[str]
    missing_recipes: list[tuple[int, str, int]]


class PlannerService:
    def __init__(self, conn: sqlite3.Connection, profile_conn: sqlite3.Connection):
        self.conn = conn
        self.profile_conn = profile_conn
        self._machine_availability_cache: dict[str, set[str]] | None = None

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
            inventory = self._load_inventory(items) if use_inventory else {}
        errors: list[str] = []
        missing_recipes: list[tuple[int, str, int]] = []
        steps: list[PlanStep] = []
        shopping_needed: dict[int, int] = {}
        required_base_needed: dict[int, int] = {}
        storage_used: dict[int, int] = {}
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
                produced_qty = plan_data["output_qty"] * plan_data["multiplier"]
                if produced_qty > 0:
                    inventory[item_id] = inventory.get(item_id, 0) + produced_qty
                for reusable_item_id, reusable_qty in plan_data.get("reusable_inputs", []):
                    if reusable_qty <= 0:
                        continue
                    inventory[reusable_item_id] = inventory.get(reusable_item_id, 0) + reusable_qty
                for byproduct_id, _name, qty, _unit, chance in plan_data["byproducts"]:
                    if chance < 100:
                        continue
                    inventory[byproduct_id] = inventory.get(byproduct_id, 0) + qty
                visiting.remove(item_id)
                continue

            item_id = frame["item_id"]
            qty_needed = frame["qty_needed"]
            requested_qty = qty_needed
            if qty_needed <= 0:
                continue

            if use_inventory:
                available = inventory.get(item_id, 0)
                if available > 0:
                    used = min(available, qty_needed)
                    inventory[item_id] = available - used
                    storage_used[item_id] = storage_used.get(item_id, 0) + used
                    qty_needed -= used
                    if qty_needed <= 0:
                        continue

            item = items.get(item_id)
            if not item:
                errors.append("Unknown item selected.")
                continue

            if use_inventory and qty_needed > 0 and item["kind"] in ("fluid", "gas"):
                qty_needed, emptying_steps, consumed_containers = self._empty_containers_for_fluid(
                    fluid_item=item,
                    qty_needed=qty_needed,
                    inventory=inventory,
                    items=items,
                )
                if consumed_containers:
                    for consumed_item_id, consumed_qty in consumed_containers.items():
                        storage_used[consumed_item_id] = storage_used.get(consumed_item_id, 0) + consumed_qty
                if emptying_steps:
                    steps.extend(emptying_steps)
                if qty_needed <= 0:
                    continue

            if item["is_base"]:
                required_base_needed[item_id] = required_base_needed.get(item_id, 0) + requested_qty
                shopping_needed[item_id] = shopping_needed.get(item_id, 0) + qty_needed
                continue

            if item_id in visiting:
                shopping_needed[item_id] = shopping_needed.get(item_id, 0) + qty_needed
                continue

            # Pass 'items' to helper to access machine stats
            recipe = self._pick_recipe_for_item(item_id, enabled_tiers, crafting_6x6_unlocked, items)
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
            input_requirements: dict[int, dict[str, int | str]] = {}
            reusable_requirements: dict[int, int] = {}
            input_lines = self._recipe_inputs(recipe["id"])
            for line in input_lines:
                input_item = items.get(line["item_id"])
                if not input_item:
                    continue
                input_qty = self._line_qty(line, input_item["kind"])
                if input_qty <= 0:
                    continue
                consumption_chance = self._normalize_consumption_chance(line["consumption_chance"])
                total_qty = self._required_input_qty(
                    input_qty=input_qty,
                    multiplier=multiplier,
                    consumption_chance=consumption_chance,
                )
                if consumption_chance <= 0:
                    reusable_requirements[input_item["id"]] = reusable_requirements.get(input_item["id"], 0) + input_qty
                existing = input_requirements.get(input_item["id"])
                if existing:
                    existing["qty"] = int(existing["qty"]) + total_qty
                else:
                    input_requirements[input_item["id"]] = {
                        "id": input_item["id"],
                        "name": input_item["name"],
                        "qty": total_qty,
                        "unit": self._unit_for_kind(input_item["kind"]),
                    }
            for requirement in input_requirements.values():
                inputs.append(
                    (
                        requirement["id"],
                        requirement["name"],
                        int(requirement["qty"]),
                        requirement["unit"],
                    )
                )
                input_frames.append(
                    {
                        "state": "enter",
                        "item_id": requirement["id"],
                        "qty_needed": int(requirement["qty"]),
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
                        "reusable_inputs": list(reusable_requirements.items()),
                        "byproducts": byproducts,
                    },
                }
            )
            for input_frame in reversed(input_frames):
                stack.append(input_frame)

        shopping_list = []
        required_base_list = []
        storage_requirements = []
        for item_id, qty in shopping_needed.items():
            item = items.get(item_id)
            if not item:
                continue
            name = item["name"] or item.get("key") or f"Item {item_id}"
            shopping_list.append((name, qty, self._unit_for_kind(item["kind"])))

        for item_id, qty in required_base_needed.items():
            item = items.get(item_id)
            if not item:
                continue
            name = item["name"] or item.get("key") or f"Item {item_id}"
            missing_qty = shopping_needed.get(item_id, 0)
            required_base_list.append((name, qty, missing_qty, self._unit_for_kind(item["kind"])))

        for item_id in set(storage_used) | set(shopping_needed):
            item = items.get(item_id)
            if not item:
                continue
            name = item["name"] or item.get("key") or f"Item {item_id}"
            used_qty = storage_used.get(item_id, 0)
            missing_qty = shopping_needed.get(item_id, 0)
            required_qty = used_qty + missing_qty
            storage_requirements.append((name, required_qty, missing_qty, self._unit_for_kind(item["kind"])))

        shopping_list.sort(key=lambda row: (row[0] or "").lower())
        required_base_list.sort(key=lambda row: (row[0] or "").lower())
        storage_requirements.sort(key=lambda row: (row[2] == 0, (row[0] or "").lower()))

        return PlanResult(
            shopping_list=shopping_list,
            required_base_list=required_base_list,
            storage_requirements=storage_requirements,
            steps=steps,
            errors=errors,
            missing_recipes=missing_recipes,
        )

    # ---------- Data loaders ----------
    def _load_items(self) -> dict[int, dict]:
        # Updated to join machine_metadata for slot/tank counts
        rows = self.conn.execute(
            """
            SELECT 
                i.id, 
                i.key, 
                COALESCE(i.display_name, i.key) AS name, 
                i.kind, 
                i.is_base, 
                i.is_machine, 
                i.machine_tier, 
                i.machine_type,
                i.content_fluid_id,
                i.content_qty_liters,
                COALESCE(mm.input_slots, 1) AS machine_input_slots,
                COALESCE(mm.output_slots, 1) AS machine_output_slots,
                COALESCE(mm.storage_slots, 0) AS machine_storage_slots,
                COALESCE(mm.power_slots, 0) AS machine_power_slots,
                COALESCE(mm.circuit_slots, 0) AS machine_circuit_slots,
                COALESCE(mm.input_tanks, 0) AS machine_input_tanks,
                COALESCE(mm.input_tank_capacity_l, 0) AS machine_input_tank_capacity_l,
                COALESCE(mm.output_tanks, 0) AS machine_output_tanks,
                COALESCE(mm.output_tank_capacity_l, 0) AS machine_output_tank_capacity_l,
                i.material_id
            FROM items i 
            LEFT JOIN machine_metadata mm ON (
                mm.machine_type = i.machine_type 
                AND mm.tier = i.machine_tier
            )
            ORDER BY name
            """
        ).fetchall()
        return {row["id"]: row for row in rows}

    def _load_inventory(self, items: dict[int, dict] | None = None) -> dict[int, int]:
        rows = self.profile_conn.execute("SELECT item_id, qty_count, qty_liters FROM inventory").fetchall()
        inventory: dict[int, int] = {}
        for row in rows:
            item_id = row["item_id"]
            if items is not None:
                item = items.get(item_id)
                kind = ((item["kind"] if item else "") or "").strip().lower()
                if kind in ("fluid", "gas"):
                    qty = row["qty_liters"] if row["qty_liters"] is not None else row["qty_count"]
                else:
                    qty = row["qty_count"] if row["qty_count"] is not None else row["qty_liters"]
            else:
                qty = row["qty_liters"] if row["qty_liters"] is not None else row["qty_count"]
            if qty is None:
                continue
            try:
                qty_int = int(float(qty))
            except (TypeError, ValueError):
                continue
            inventory[item_id] = max(qty_int, 0)
        return inventory

    def load_inventory(self, items: dict[int, dict] | None = None) -> dict[int, int]:
        return self._load_inventory(items)

    def _empty_containers_for_fluid(
        self,
        *,
        fluid_item: dict,
        qty_needed: int,
        inventory: dict[int, int],
        items: dict[int, dict],
    ) -> tuple[int, list[PlanStep], dict[int, int]]:
        if qty_needed <= 0:
            return 0, [], {}
        fluid_id = fluid_item["id"]
        containers = [
            item
            for item in items.values()
            if item["content_fluid_id"] == fluid_id
        ]
        if not containers:
            return qty_needed, [], {}
        containers.sort(key=lambda row: (row["name"] or "").lower())
        steps: list[PlanStep] = []
        consumed: dict[int, int] = {}
        remaining = qty_needed
        for container in containers:
            available = inventory.get(container["id"], 0)
            if available <= 0:
                continue
            try:
                per_container = int(container["content_qty_liters"] or 0)
            except (TypeError, ValueError):
                per_container = 0
            if per_container <= 0:
                continue
            needed_containers = math.ceil(remaining / per_container)
            use_containers = min(available, needed_containers)
            if use_containers <= 0:
                continue
            provided_qty = per_container * use_containers
            remaining = max(remaining - provided_qty, 0)
            inventory[container["id"]] = available - use_containers
            consumed[container["id"]] = consumed.get(container["id"], 0) + use_containers
            steps.append(
                PlanStep(
                    recipe_id=0,
                    recipe_name="Emptying",
                    method="emptying",
                    machine=None,
                    machine_item_id=None,
                    machine_item_name="",
                    grid_size=None,
                    station_item_id=None,
                    station_item_name="",
                    circuit=None,
                    output_item_id=fluid_id,
                    output_item_name=fluid_item["name"],
                    output_qty=per_container,
                    output_unit=self._unit_for_kind(fluid_item["kind"]),
                    multiplier=use_containers,
                    inputs=[
                        (
                            container["id"],
                            container["name"],
                            use_containers,
                            self._unit_for_kind(container["kind"]),
                        )
                    ],
                    byproducts=self._container_byproducts(
                        container=container,
                        fluid_item=fluid_item,
                        use_containers=use_containers,
                        items=items,
                    ),
                )
            )
            for byproduct_id, _name, qty, _unit, chance in steps[-1].byproducts:
                if chance < 100:
                    continue
                inventory[byproduct_id] = inventory.get(byproduct_id, 0) + qty
            if remaining <= 0:
                break
        return remaining, steps, consumed

    # ---------- Recipe helpers ----------
    def _pick_recipe_for_item(
        self,
        item_id: int,
        enabled_tiers: Iterable[str],
        crafting_6x6_unlocked: bool,
        items: dict[int, dict],
    ):
        # 1. Fetch ALL recipes, calculating separate input counts for items vs fluids
        sql = (
            "SELECT r.id, r.name, r.method, r.machine, r.machine_item_id, r.grid_size, "
            "r.station_item_id, r.circuit, r.tier, r.duration_ticks, r.eu_per_tick, "
            "mi.machine_tier AS machine_item_tier, "
            "COALESCE(mi.display_name, mi.key) AS machine_item_name, "
            # Calculate item input count vs fluid input count
            "COALESCE(SUM(CASE WHEN rl_in.direction='in' AND (input_item.kind IN ('fluid','gas')) THEN 1 ELSE 0 END), 0) AS fluid_req_count, "
            "COALESCE(SUM(CASE WHEN rl_in.direction='in' AND (input_item.kind NOT IN ('fluid','gas') OR input_item.kind IS NULL) THEN 1 ELSE 0 END), 0) AS item_req_count, "
            
            "COALESCE(SUM(CASE WHEN rl_in.direction='in' "
            "THEN COALESCE(rl_in.qty_count, rl_in.qty_liters, 1) ELSE 0 END), 0) AS input_qty "
            ", COALESCE(MAX(CASE WHEN rl_out.direction='out' "
            "THEN COALESCE(rl_out.qty_count, rl_out.qty_liters, 1) ELSE NULL END), 0) AS output_qty "
            "FROM recipes r "
            "LEFT JOIN items mi ON mi.id = r.machine_item_id "
            "JOIN recipe_lines rl_out ON rl_out.recipe_id = r.id "
            "LEFT JOIN recipe_lines rl_in ON rl_in.recipe_id = r.id AND rl_in.direction='in' "
            "LEFT JOIN items input_item ON input_item.id = rl_in.item_id "
            "WHERE rl_out.direction='out' AND rl_out.item_id=? "
            "GROUP BY r.id "
            "ORDER BY r.name"
        )
        
        rows = self.conn.execute(sql, [item_id]).fetchall()
        
        # 2. Hard Filter: 6x6 Crafting
        if not crafting_6x6_unlocked:
            rows = [r for r in rows if not (r["method"] == "crafting" and (r["grid_size"] or "").strip() == "6x6")]
        
        if not rows:
            return None

        # 3. Setup Availability
        available_machines = self._load_machine_availability()
        enabled_tiers_set = set(enabled_tiers)
        tier_sort_map = {name: i for i, name in enumerate(ALL_TIERS)}
        
        def recipe_rank(row) -> tuple:
            # We want the lowest score (tuple comparison).
            
            # --- PRE-CALCULATION ---
            req_tier = get_calculated_tier(row)
            method = (row["method"] or "machine").strip().lower()
            machine_type = (row["machine"] or "").strip().lower()
            machine_tier = self._pick_machine_tier(row, available_machines)
            
            # --- CRITERIA 1: AVAILABILITY SCORE ---
            # 0 = Owned / Immediate
            # 1 = Unlocked Tier
            # 2 = Locked Tier
            # 3 = Capacity Error (Impossible)
            
            avail_score = 2 
            
            # Check Capacity First
            if row["machine_item_id"]:
                m_item = items.get(row["machine_item_id"])
                if m_item:
                    req_items = int(row["item_req_count"] or 0)
                    req_fluids = int(row["fluid_req_count"] or 0)
                    avail_slots = int(m_item["machine_input_slots"] or 1)
                    avail_tanks = int(m_item["machine_input_tanks"] or 0)
                    
                    if req_items > avail_slots or req_fluids > avail_tanks:
                        avail_score = 3
            
            if avail_score != 3:
                # Normal ownership logic
                if method == "crafting":
                    avail_score = 0
                elif method == "machine" and machine_type:
                    if machine_type in available_machines:
                        owned_tiers = available_machines[machine_type]
                        if self._tier_available(req_tier, owned_tiers):
                            avail_score = 0

                if avail_score > 0:
                    if req_tier in enabled_tiers_set:
                        avail_score = 1
                    elif req_tier == "Stone Age":
                        avail_score = 1

            # --- CRITERIA 2: MACHINE COUNT (Prefer more available machines) ---
            machine_count = 0
            if method == "machine" and machine_type:
                machine_count = self._machine_count_for_tier(machine_type, machine_tier, available_machines)

            # --- CRITERIA 3: EFFICIENCY (Input per Output) ---
            output_qty = float(row["output_qty"] or 1)
            input_unit_count = float(row["item_req_count"] or 0) + float(row["fluid_req_count"] or 0)
            ratio = input_unit_count / output_qty if output_qty > 0 else 999.0

            # --- CRITERIA 4: SPEED + POWER ---
            scaled_duration, scaled_eu = apply_overclock(
                row["duration_ticks"],
                row["eu_per_tick"],
                req_tier,
                machine_tier,
            )
            duration_value = scaled_duration
            if method == "crafting" and (duration_value is None or float(duration_value) <= 0):
                duration_value = 200
            duration = float(duration_value or 0)
            time_per_item = duration / output_qty if output_qty > 0 else duration

            # --- CRITERIA 5: ENERGY COST ---
            if method == "crafting" and scaled_eu is None:
                scaled_eu = 0
            if scaled_eu is None or duration_value is None:
                energy_per_item = float("inf")
            else:
                energy_per_item = (float(scaled_eu) * float(duration_value)) / output_qty if output_qty > 0 else 0.0

            # --- CRITERIA 6: TIER RANK ---
            t_rank = tier_sort_map.get(req_tier, 999)

            return (
                avail_score,
                -machine_count,
                ratio,
                time_per_item,
                energy_per_item,
                t_rank,
            )

        return min(rows, key=recipe_rank)

    def _load_machine_availability(self) -> dict[str, dict[str, dict[str, int]]]:
        if self._machine_availability_cache is not None:
            return self._machine_availability_cache
        if self.profile_conn is None:
            self._machine_availability_cache = {}
            return self._machine_availability_cache
        rows = self.profile_conn.execute(
            "SELECT machine_type, tier, owned, online FROM machine_availability"
        ).fetchall()
        available: dict[str, dict[str, dict[str, int]]] = {}
        for row in rows:
            owned = int(row["owned"] or 0)
            online = int(row["online"] or 0)
            if owned <= 0 and online <= 0:
                continue
            machine_type = (row["machine_type"] or "").strip().lower()
            if not machine_type:
                continue
            tier = (row["tier"] or "").strip()
            available.setdefault(machine_type, {})[tier] = {"owned": owned, "online": online}
        self._machine_availability_cache = available
        return available

    def _tier_available(self, required_tier: str, owned_tiers: dict[str, dict[str, int]]) -> bool:
        if required_tier in owned_tiers:
            return True
        required_rank = _tier_rank(required_tier)
        if required_rank is None:
            return False
        for owned in owned_tiers.keys():
            owned_rank = _tier_rank(owned)
            if owned_rank is not None and owned_rank >= required_rank:
                return True
        return False

    def _machine_count_for_tier(
        self,
        machine_type: str,
        machine_tier: str | None,
        available_machines: dict[str, dict[str, dict[str, int]]],
    ) -> int:
        tiers = available_machines.get(machine_type, {})
        if not tiers:
            return 0
        if machine_tier and machine_tier in tiers:
            record = tiers[machine_tier]
            return max(int(record.get("online", 0)), int(record.get("owned", 0)))
        best = 0
        for record in tiers.values():
            count = max(int(record.get("online", 0)), int(record.get("owned", 0)))
            if count > best:
                best = count
        return best

    def _pick_machine_tier(
        self,
        row: sqlite3.Row,
        available_machines: dict[str, dict[str, dict[str, int]]],
    ) -> str | None:
        method = (row["method"] or "machine").strip().lower()
        if method != "machine":
            return None
        machine_type = (row["machine"] or "").strip().lower()
        if not machine_type:
            return None
        tiers = available_machines.get(machine_type)
        if tiers:
            return _highest_tier(tiers.keys())
        machine_item_tier = (row["machine_item_tier"] or "").strip()
        return machine_item_tier or None

    def _recipe_machine_available(
        self,
        row: sqlite3.Row,
        available_machines: dict[str, dict[str, dict[str, int]]],
    ) -> bool:
        # Legacy method kept for safety, but main logic is now in ranking
        method = (row["method"] or "machine").strip().lower()
        if method != "machine":
            return True
        machine_name = (row["machine_item_name"] or "").strip()
        machine_type = (machine_name or row["machine"] or "").strip().lower()
        if not machine_type:
            return True
        tiers = available_machines.get(machine_type)
        if not tiers:
            return False
        tier = (row["tier"] or "").strip() or (row["machine_item_tier"] or "").strip()
        if not tier:
            return True
        if tier in tiers:
            return True
        return False

    def _recipe_machine_match_rank(
        self,
        row: sqlite3.Row,
        available_machines: dict[str, dict[str, dict[str, int]]],
    ) -> int:
        if not available_machines:
            return 1
        method = (row["method"] or "machine").strip().lower()
        if method != "machine":
            return 1
        machine_name = (row["machine_item_name"] or "").strip()
        machine_type = (machine_name or row["machine"] or "").strip().lower()
        if not machine_type:
            return 1
        tiers = available_machines.get(machine_type)
        if not tiers:
            return 1
        tier = (row["tier"] or "").strip() or (row["machine_item_tier"] or "").strip()
        if tier and tier in tiers:
            return 0
        return 1

    def _recipe_output_qty(self, recipe_id: int, item_id: int, kind: str) -> int:
        rows = self.conn.execute(
            "SELECT qty_count, qty_liters FROM recipe_lines WHERE recipe_id=? AND direction='out' AND item_id=?",
            (recipe_id, item_id),
        ).fetchall()
        
        if not rows:
            return 0
            
        total_qty = 0
        for row in rows:
            total_qty += self._qty_from_row(row, kind)
        return total_qty

    def _recipe_inputs(self, recipe_id: int):
        return self.conn.execute(
            "SELECT item_id, qty_count, qty_liters, consumption_chance "
            "FROM recipe_lines WHERE recipe_id=? AND direction='in'",
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
        normalized_kind = (kind or "").strip().lower()
        if normalized_kind == "fluid":
            primary_qty = row["qty_liters"]
            fallback_qty = row["qty_count"]
        else:
            primary_qty = row["qty_count"]
            fallback_qty = row["qty_liters"]
        qty = primary_qty if primary_qty is not None else fallback_qty
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
        return "L" if (kind or "").strip().lower() in ("fluid", "gas") else "count"

    def _normalize_consumption_chance(self, value: float | int | None) -> float:
        if value is None:
            return 1.0
        try:
            chance = float(value)
        except (TypeError, ValueError):
            return 1.0
        if chance > 1:
            if chance <= 100:
                return chance / 100.0
            return 1.0
        if chance < 0:
            return 0.0
        return chance

    def _required_input_qty(
        self,
        *,
        input_qty: int,
        multiplier: int,
        consumption_chance: float,
    ) -> int:
        if input_qty <= 0:
            return 0
        if consumption_chance <= 0:
            return input_qty
        expected_consumed = math.ceil(input_qty * multiplier * consumption_chance)
        return max(input_qty, expected_consumed)

    def _container_byproducts(
        self,
        *,
        container: dict,
        fluid_item: dict,
        use_containers: int,
        items: dict[int, dict],
    ) -> list[tuple[int, str, int, str, float]]:
        empty_container = self._find_empty_container(container, fluid_item, items)
        if not empty_container:
            return []
        return [
            (
                empty_container["id"],
                empty_container["name"],
                use_containers,
                self._unit_for_kind(empty_container["kind"]),
                100.0,
            )
        ]

    def _find_empty_container(
        self,
        container: dict,
        fluid_item: dict,
        items: dict[int, dict],
    ) -> dict | None:
        if not container or not fluid_item:
            return None
        if self._row_value(container, "content_fluid_id") is None:
            return None
        fluid_key = (self._row_value(fluid_item, "key") or "").strip()
        fluid_name = (self._row_value(fluid_item, "name") or "").strip()
        container_key = (self._row_value(container, "key") or "").strip()
        container_name = (self._row_value(container, "name") or "").strip()

        candidate_keys: list[str] = []
        candidate_names: list[str] = []

        if fluid_key and container_key:
            if container_key.startswith(f"{fluid_key}_"):
                candidate_keys.append(container_key[len(fluid_key) + 1 :])
            if container_key.endswith(f"_{fluid_key}"):
                candidate_keys.append(container_key[: -len(fluid_key) - 1])

        if fluid_name and container_name:
            lower_container = container_name.lower()
            lower_fluid = fluid_name.lower()
            if lower_container.startswith(lower_fluid):
                candidate_names.append(container_name[len(fluid_name) :].strip(" -"))
            if lower_container.endswith(lower_fluid):
                candidate_names.append(container_name[: -len(fluid_name)].strip(" -"))
            candidate_names.append(container_name.replace(fluid_name, "").strip(" -"))

        candidate_keys = [candidate for candidate in candidate_keys if candidate]
        candidate_names = [candidate for candidate in candidate_names if candidate]

        def _match_item(predicate):
            for item in items.values():
                if self._row_value(item, "content_fluid_id") is not None:
                    continue
                if predicate(item):
                    return item
            return None

        for key in candidate_keys:
            match = _match_item(
                lambda item: (self._row_value(item, "key") or "").strip().lower() == key.lower()
            )
            if match:
                return match
        for name in candidate_names:
            match = _match_item(
                lambda item: (self._row_value(item, "name") or "").strip().lower() == name.lower()
            )
            if match:
                return match
        return None

    def _row_value(self, row: dict | sqlite3.Row, key: str):
        if isinstance(row, sqlite3.Row):
            return row[key]
        return row.get(key)
