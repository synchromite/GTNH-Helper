import sqlite3

import pytest

from services.db import ensure_schema, connect_profile
from services.planner import PlannerService, apply_overclock


def _setup_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


def _insert_item(
    conn,
    *,
    key,
    name,
    kind="item",
    is_base=0,
    content_fluid_id=None,
    content_qty_liters=None,
):
    conn.execute(
        "INSERT INTO items(key, display_name, kind, is_base, content_fluid_id, content_qty_liters) "
        "VALUES(?,?,?,?,?,?)",
        (key, name, kind, is_base, content_fluid_id, content_qty_liters),
    )
    return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def _insert_recipe(conn, *, name, method="crafting", duration_ticks=None, eu_per_tick=None):
    conn.execute(
        "INSERT INTO recipes(name, method, duration_ticks, eu_per_tick) VALUES(?, ?, ?, ?)",
        (name, method, duration_ticks, eu_per_tick),
    )
    return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def _insert_line(
    conn,
    *,
    recipe_id,
    direction,
    item_id,
    qty_count=None,
    qty_liters=None,
    consumption_chance=None,
):
    conn.execute(
        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_count, qty_liters, consumption_chance) "
        "VALUES(?,?,?,?,?,?)",
        (recipe_id, direction, item_id, qty_count, qty_liters, consumption_chance),
    )


def _set_recipe_machine(conn, *, recipe_id, machine, tier):
    conn.execute(
        "UPDATE recipes SET machine=?, tier=? WHERE id=?",
        (machine, tier, recipe_id),
    )


def _set_machine_availability(conn, *, machine_type, tier, owned, online):
    conn.execute(
        "INSERT INTO machine_availability(machine_type, tier, owned, online) VALUES(?,?,?,?)",
        (machine_type, tier, owned, online),
    )


def test_plan_simple_chain_with_inventory_override():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    item_a = _insert_item(conn, key="item_a", name="Item A", is_base=1)
    item_b = _insert_item(conn, key="item_b", name="Item B")
    item_c = _insert_item(conn, key="item_c", name="Item C")

    recipe_b = _insert_recipe(conn, name="Make B")
    _insert_line(conn, recipe_id=recipe_b, direction="out", item_id=item_b, qty_count=1)
    _insert_line(conn, recipe_id=recipe_b, direction="in", item_id=item_a, qty_count=2)

    recipe_c = _insert_recipe(conn, name="Make C")
    _insert_line(conn, recipe_id=recipe_c, direction="out", item_id=item_c, qty_count=1)
    _insert_line(conn, recipe_id=recipe_c, direction="in", item_id=item_b, qty_count=1)

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        item_c,
        1,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
        inventory_override={item_a: 1},
    )

    assert result.errors == []
    assert result.missing_recipes == []
    assert result.shopping_list == [("Item A", 1, "count")]
    assert result.required_base_list == [("Item A", 2, 1, "count")]
    assert result.storage_requirements == [("Item A", 2, 1, "count")]
    assert [step.output_item_name for step in result.steps] == ["Item B", "Item C"]


def test_plan_inserts_emptying_step_for_fluid_container():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    water = _insert_item(conn, key="water", name="Water", kind="fluid")
    empty_cell = _insert_item(conn, key="cell", name="Cell", kind="item")
    water_cell = _insert_item(
        conn,
        key="water_cell",
        name="Water Cell",
        kind="item",
        content_fluid_id=water,
        content_qty_liters=1,
    )
    output = _insert_item(conn, key="output_item", name="Output Item")

    recipe = _insert_recipe(conn, name="Make Output")
    _insert_line(conn, recipe_id=recipe, direction="out", item_id=output, qty_count=1)
    _insert_line(conn, recipe_id=recipe, direction="in", item_id=water, qty_liters=2)

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        output,
        1,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
        inventory_override={water_cell: 2},
    )

    assert result.errors == []
    assert result.missing_recipes == []
    assert result.shopping_list == []
    assert [step.recipe_name for step in result.steps] == ["Emptying", "Make Output"]
    assert result.steps[0].byproducts == [(empty_cell, "Cell", 2, "count", 100.0)]


def test_plan_accounts_for_non_consumed_inputs():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    circuit = _insert_item(conn, key="programmed_circuit", name="Programmed Circuit", is_base=1)
    input_item = _insert_item(conn, key="input_item", name="Input Item", is_base=1)
    output = _insert_item(conn, key="output_item", name="Output Item")

    recipe = _insert_recipe(conn, name="Make Output")
    _insert_line(conn, recipe_id=recipe, direction="out", item_id=output, qty_count=1)
    _insert_line(
        conn,
        recipe_id=recipe,
        direction="in",
        item_id=circuit,
        qty_count=1,
        consumption_chance=0.0,
    )
    _insert_line(conn, recipe_id=recipe, direction="in", item_id=input_item, qty_count=2)

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        output,
        3,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
    )

    assert result.errors == []
    assert result.missing_recipes == []
    assert ("Programmed Circuit", 1, "count") in result.shopping_list
    assert ("Input Item", 6, "count") in result.shopping_list




def test_plan_reuses_non_consumed_tool_from_inventory():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    hammer = _insert_item(conn, key="hammer", name="Hammer")
    plank = _insert_item(conn, key="plank", name="Plank", is_base=1)
    part_a = _insert_item(conn, key="part_a", name="Part A")
    part_b = _insert_item(conn, key="part_b", name="Part B")
    final = _insert_item(conn, key="final", name="Final")

    recipe_a = _insert_recipe(conn, name="Make A")
    _insert_line(conn, recipe_id=recipe_a, direction="out", item_id=part_a, qty_count=1)
    _insert_line(conn, recipe_id=recipe_a, direction="in", item_id=plank, qty_count=1)
    _insert_line(
        conn,
        recipe_id=recipe_a,
        direction="in",
        item_id=hammer,
        qty_count=1,
        consumption_chance=0,
    )

    recipe_b = _insert_recipe(conn, name="Make B")
    _insert_line(conn, recipe_id=recipe_b, direction="out", item_id=part_b, qty_count=1)
    _insert_line(conn, recipe_id=recipe_b, direction="in", item_id=plank, qty_count=1)
    _insert_line(
        conn,
        recipe_id=recipe_b,
        direction="in",
        item_id=hammer,
        qty_count=1,
        consumption_chance=0,
    )

    recipe_final = _insert_recipe(conn, name="Make Final")
    _insert_line(conn, recipe_id=recipe_final, direction="out", item_id=final, qty_count=1)
    _insert_line(conn, recipe_id=recipe_final, direction="in", item_id=part_a, qty_count=1)
    _insert_line(conn, recipe_id=recipe_final, direction="in", item_id=part_b, qty_count=1)

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        final,
        1,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
        inventory_override={hammer: 1},
    )

    assert result.errors == []
    assert result.missing_recipes == []
    assert result.shopping_list == [("Plank", 2, "count")]
    assert result.required_base_list == [("Plank", 2, 2, "count")]
    assert result.storage_requirements == [("Plank", 2, 2, "count"), ("Hammer", 2, 0, "count")]


def test_plan_aggregates_duplicate_inputs_before_inventory_usage():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    gravel = _insert_item(conn, key="gravel", name="Gravel", is_base=1)
    flint = _insert_item(conn, key="flint", name="Flint")
    target = _insert_item(conn, key="target", name="Target")

    recipe_flint = _insert_recipe(conn, name="Make Flint")
    _insert_line(conn, recipe_id=recipe_flint, direction="out", item_id=flint, qty_count=1)
    _insert_line(conn, recipe_id=recipe_flint, direction="in", item_id=gravel, qty_count=3)

    recipe_target = _insert_recipe(conn, name="Make Target")
    _insert_line(conn, recipe_id=recipe_target, direction="out", item_id=target, qty_count=1)
    _insert_line(conn, recipe_id=recipe_target, direction="in", item_id=flint, qty_count=1)
    _insert_line(conn, recipe_id=recipe_target, direction="in", item_id=flint, qty_count=1)

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        target,
        1,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
    )

    assert result.errors == []
    assert result.missing_recipes == []
    assert result.shopping_list == [("Gravel", 6, "count")]


def test_plan_reports_required_and_missing_base_items_with_inventory():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    ore = _insert_item(conn, key="ore", name="Ore", is_base=1)
    plate = _insert_item(conn, key="plate", name="Plate")

    recipe = _insert_recipe(conn, name="Smelt Plate")
    _insert_line(conn, recipe_id=recipe, direction="out", item_id=plate, qty_count=1)
    _insert_line(conn, recipe_id=recipe, direction="in", item_id=ore, qty_count=3)

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        plate,
        2,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
        inventory_override={ore: 2},
    )

    assert result.errors == []
    assert result.missing_recipes == []
    assert result.required_base_list == [("Ore", 6, 4, "count")]
    assert result.storage_requirements == [("Ore", 6, 4, "count")]
    assert result.shopping_list == [("Ore", 4, "count")]


def test_plan_merges_duplicate_created_item_steps_across_branches():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    steel_ingot = _insert_item(conn, key="steel_ingot", name="Steel Ingot", is_base=1)
    steel_rod = _insert_item(conn, key="steel_rod", name="Steel Rod")
    assembly_a = _insert_item(conn, key="assembly_a", name="Assembly A")
    assembly_b = _insert_item(conn, key="assembly_b", name="Assembly B")
    final = _insert_item(conn, key="final_build", name="Final Build")

    rod_recipe = _insert_recipe(conn, name="Make Steel Rod")
    _insert_line(conn, recipe_id=rod_recipe, direction="out", item_id=steel_rod, qty_count=2)
    _insert_line(conn, recipe_id=rod_recipe, direction="in", item_id=steel_ingot, qty_count=2)

    assembly_a_recipe = _insert_recipe(conn, name="Make Assembly A")
    _insert_line(conn, recipe_id=assembly_a_recipe, direction="out", item_id=assembly_a, qty_count=1)
    _insert_line(conn, recipe_id=assembly_a_recipe, direction="in", item_id=steel_rod, qty_count=10)

    assembly_b_recipe = _insert_recipe(conn, name="Make Assembly B")
    _insert_line(conn, recipe_id=assembly_b_recipe, direction="out", item_id=assembly_b, qty_count=1)
    _insert_line(conn, recipe_id=assembly_b_recipe, direction="in", item_id=steel_rod, qty_count=15)

    final_recipe = _insert_recipe(conn, name="Make Final Build")
    _insert_line(conn, recipe_id=final_recipe, direction="out", item_id=final, qty_count=1)
    _insert_line(conn, recipe_id=final_recipe, direction="in", item_id=assembly_a, qty_count=1)
    _insert_line(conn, recipe_id=final_recipe, direction="in", item_id=assembly_b, qty_count=1)

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        final,
        1,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
    )

    rod_steps = [step for step in result.steps if step.output_item_id == steel_rod]
    assert len(rod_steps) == 1



def test_plan_missing_recipe_reports_error():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    item_a = _insert_item(conn, key="item_a", name="Item A")

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        item_a,
        3,
        use_inventory=False,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
    )

    assert result.errors == ["No recipe found for Item A."]
    assert result.missing_recipes == [(item_a, "Item A", 3)]
    assert result.steps == []
    assert result.shopping_list == []


def test_plan_selects_online_machine_tier_recipe():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    item_input = _insert_item(conn, key="input_item", name="Input Item", is_base=1)
    item_output = _insert_item(conn, key="output_item", name="Output Item")

    recipe_lv = _insert_recipe(conn, name="Make Output LV", method="machine", duration_ticks=400)
    _set_recipe_machine(conn, recipe_id=recipe_lv, machine="lathe", tier="LV")
    _insert_line(conn, recipe_id=recipe_lv, direction="out", item_id=item_output, qty_count=1)
    _insert_line(conn, recipe_id=recipe_lv, direction="in", item_id=item_input, qty_count=1)

    recipe_mv = _insert_recipe(conn, name="Make Output MV", method="machine", duration_ticks=120)
    _set_recipe_machine(conn, recipe_id=recipe_mv, machine="lathe", tier="MV")
    _insert_line(conn, recipe_id=recipe_mv, direction="out", item_id=item_output, qty_count=1)
    _insert_line(conn, recipe_id=recipe_mv, direction="in", item_id=item_input, qty_count=1)

    _set_machine_availability(profile_conn, machine_type="lathe", tier="MV", owned=1, online=1)

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        item_output,
        1,
        use_inventory=False,
        enabled_tiers=["LV", "MV"],
        crafting_6x6_unlocked=True,
    )

    assert result.errors == []
    assert [step.recipe_name for step in result.steps] == ["Make Output MV"]


def test_plan_falls_back_when_no_machines_online():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    item_input = _insert_item(conn, key="input_item", name="Input Item", is_base=1)
    item_output = _insert_item(conn, key="output_item", name="Output Item")

    recipe_lv = _insert_recipe(conn, name="Make Output LV", method="machine")
    _set_recipe_machine(conn, recipe_id=recipe_lv, machine="lathe", tier="LV")
    _insert_line(conn, recipe_id=recipe_lv, direction="out", item_id=item_output, qty_count=1)
    _insert_line(conn, recipe_id=recipe_lv, direction="in", item_id=item_input, qty_count=1)

    recipe_mv = _insert_recipe(conn, name="Make Output MV", method="machine")
    _set_recipe_machine(conn, recipe_id=recipe_mv, machine="lathe", tier="MV")
    _insert_line(conn, recipe_id=recipe_mv, direction="out", item_id=item_output, qty_count=1)
    _insert_line(conn, recipe_id=recipe_mv, direction="in", item_id=item_input, qty_count=1)

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        item_output,
        1,
        use_inventory=False,
        enabled_tiers=["LV", "MV"],
        crafting_6x6_unlocked=True,
    )

    assert result.errors == []
    assert [step.recipe_name for step in result.steps] == ["Make Output LV"]



def test_plan_refreshes_machine_availability_after_cache_clear():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    item_input = _insert_item(conn, key="input_item", name="Input Item", is_base=1)
    item_output = _insert_item(conn, key="output_item", name="Output Item")

    recipe_lv = _insert_recipe(conn, name="Make Output LV", method="machine", duration_ticks=120)
    _set_recipe_machine(conn, recipe_id=recipe_lv, machine="lathe", tier="LV")
    _insert_line(conn, recipe_id=recipe_lv, direction="out", item_id=item_output, qty_count=1)
    _insert_line(conn, recipe_id=recipe_lv, direction="in", item_id=item_input, qty_count=1)

    recipe_mv = _insert_recipe(conn, name="Make Output MV", method="machine", duration_ticks=400)
    _set_recipe_machine(conn, recipe_id=recipe_mv, machine="macerator", tier="MV")
    _insert_line(conn, recipe_id=recipe_mv, direction="out", item_id=item_output, qty_count=1)
    _insert_line(conn, recipe_id=recipe_mv, direction="in", item_id=item_input, qty_count=1)

    planner = PlannerService(conn, profile_conn)

    initial_result = planner.plan(
        item_output,
        1,
        use_inventory=False,
        enabled_tiers=["LV", "MV"],
        crafting_6x6_unlocked=True,
    )
    assert [step.recipe_name for step in initial_result.steps] == ["Make Output LV"]

    _set_machine_availability(profile_conn, machine_type="macerator", tier="MV", owned=1, online=1)
    profile_conn.commit()

    stale_result = planner.plan(
        item_output,
        1,
        use_inventory=False,
        enabled_tiers=["LV", "MV"],
        crafting_6x6_unlocked=True,
    )
    assert [step.recipe_name for step in stale_result.steps] == ["Make Output LV"]

    planner.clear_cache()
    refreshed_result = planner.plan(
        item_output,
        1,
        use_inventory=False,
        enabled_tiers=["LV", "MV"],
        crafting_6x6_unlocked=True,
    )
    assert [step.recipe_name for step in refreshed_result.steps] == ["Make Output MV"]

def test_apply_overclock_scales_duration_and_power():
    scaled_duration, scaled_eu = apply_overclock(200, 32, "LV", "MV")

    assert scaled_duration == 100
    assert scaled_eu == 128


def test_get_calculated_tier_uses_first_configured_tier_for_non_eu_recipe(monkeypatch):
    from services import planner as planner_module

    monkeypatch.setattr(planner_module, "ALL_TIERS", ["Primitive", "LV", "MV"])
    row = {"tier": "", "method": "machine", "eu_per_tick": 0}

    assert planner_module.get_calculated_tier(row) == "Primitive"
