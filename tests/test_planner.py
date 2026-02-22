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


def _insert_recipe(
    conn,
    *,
    name,
    method="crafting",
    duration_ticks=None,
    eu_per_tick=None,
    tier=None,
    max_tier=None,
    is_perfect_overclock=0,
):
    conn.execute(
        "INSERT INTO recipes(name, method, duration_ticks, eu_per_tick, tier, max_tier, is_perfect_overclock) VALUES(?, ?, ?, ?, ?, ?, ?)",
        (name, method, duration_ticks, eu_per_tick, tier, max_tier, is_perfect_overclock),
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


def test_plan_inserts_filling_step_for_fluid_container_output():
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

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        water_cell,
        2,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
        inventory_override={water: 2, empty_cell: 2},
    )

    assert result.errors == []
    assert result.missing_recipes == []
    assert result.shopping_list == []
    assert [step.recipe_name for step in result.steps] == ["Filling"]
    assert result.steps[0].inputs == [
        (water, "Water", 2, "L"),
        (empty_cell, "Cell", 2, "count"),
    ]


def test_plan_builds_fluid_then_fills_container_without_container_recipe():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    salt = _insert_item(conn, key="salt", name="Salt", is_base=1)
    chlorine = _insert_item(conn, key="chlorine", name="Chlorine", kind="gas")
    empty_cell = _insert_item(conn, key="cell", name="Cell", kind="item", is_base=1)
    chlorine_cell = _insert_item(
        conn,
        key="chlorine_cell",
        name="Chlorine Cell",
        kind="item",
        content_fluid_id=chlorine,
        content_qty_liters=1,
    )

    chlorine_recipe = _insert_recipe(conn, name="Make Chlorine")
    _insert_line(conn, recipe_id=chlorine_recipe, direction="out", item_id=chlorine, qty_liters=1)
    _insert_line(conn, recipe_id=chlorine_recipe, direction="in", item_id=salt, qty_count=1)

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        chlorine_cell,
        1,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
    )

    assert result.errors == []
    assert result.missing_recipes == []
    assert [step.recipe_name for step in result.steps] == ["Make Chlorine", "Filling"]
    assert ("Salt", 1, "count") in result.shopping_list
    assert ("Cell", 1, "count") in result.shopping_list


def test_plan_recipe_requiring_cell_uses_fluid_and_empty_cell_from_inventory():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    chlorine = _insert_item(conn, key="chlorine", name="Chlorine", kind="gas")
    empty_cell = _insert_item(conn, key="cell", name="Cell", kind="item")
    chlorine_cell = _insert_item(
        conn,
        key="chlorine_cell",
        name="Chlorine Cell",
        kind="item",
        content_fluid_id=chlorine,
        content_qty_liters=1,
    )
    product = _insert_item(conn, key="bleach", name="Bleach")

    recipe = _insert_recipe(conn, name="Make Bleach")
    _insert_line(conn, recipe_id=recipe, direction="out", item_id=product, qty_count=1)
    _insert_line(conn, recipe_id=recipe, direction="in", item_id=chlorine_cell, qty_count=1)

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        product,
        1,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
        inventory_override={chlorine: 1, empty_cell: 1},
    )

    assert result.errors == []
    assert result.missing_recipes == []
    assert result.shopping_list == []
    assert [step.recipe_name for step in result.steps] == ["Filling", "Make Bleach"]


def test_plan_recipe_requiring_cell_matches_empty_cell_name_and_key_variants():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    chlorine = _insert_item(conn, key="chlorine", name="Chlorine", kind="gas")
    empty_cell = _insert_item(conn, key="empty_cell", name="Empty Cell", kind="item", is_base=1)
    chlorine_cell = _insert_item(
        conn,
        key="chlorine_cell",
        name="Chlorine Cell",
        kind="item",
        content_fluid_id=chlorine,
        content_qty_liters=1000,
    )
    acid = _insert_item(conn, key="hydrochloric_acid", name="Hydrochloric Acid", kind="fluid")

    make_chlorine = _insert_recipe(conn, name="Make Chlorine")
    _insert_line(conn, recipe_id=make_chlorine, direction="out", item_id=chlorine, qty_liters=1000)

    make_acid = _insert_recipe(conn, name="Make Hydrochloric Acid")
    _insert_line(conn, recipe_id=make_acid, direction="out", item_id=acid, qty_liters=1000)
    _insert_line(conn, recipe_id=make_acid, direction="in", item_id=chlorine_cell, qty_count=1)

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        acid,
        12000,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
    )

    assert result.errors == []
    assert result.missing_recipes == []
    assert [step.recipe_name for step in result.steps] == [
        "Make Chlorine",
        "Filling",
        "Make Hydrochloric Acid",
    ]
    assert ("Empty Cell", 12, "count") in result.shopping_list


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


def test_plan_aggregates_duplicate_probabilistic_inputs_before_rounding():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    catalyst = _insert_item(conn, key="catalyst", name="Catalyst", is_base=1)
    output = _insert_item(conn, key="output", name="Output")

    recipe = _insert_recipe(conn, name="Chance Recipe")
    _insert_line(conn, recipe_id=recipe, direction="out", item_id=output, qty_count=1)
    _insert_line(
        conn,
        recipe_id=recipe,
        direction="in",
        item_id=catalyst,
        qty_count=1,
        consumption_chance=0.1,
    )
    _insert_line(
        conn,
        recipe_id=recipe,
        direction="in",
        item_id=catalyst,
        qty_count=1,
        consumption_chance=0.1,
    )

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        output,
        1,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
    )

    assert result.errors == []
    assert result.missing_recipes == []
    assert result.shopping_list == [("Catalyst", 2, "count")]
    assert result.steps[0].inputs == [(catalyst, "Catalyst", 2, "count")]


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


def test_plan_step_exposes_reusable_inputs_for_ui():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    mold = _insert_item(conn, key="mold", name="Mold", is_base=1)
    dust = _insert_item(conn, key="dust", name="Dust", is_base=1)
    plate = _insert_item(conn, key="plate", name="Plate")

    recipe = _insert_recipe(conn, name="Press Plate")
    _insert_line(conn, recipe_id=recipe, direction="out", item_id=plate, qty_count=1)
    _insert_line(conn, recipe_id=recipe, direction="in", item_id=mold, qty_count=1, consumption_chance=0)
    _insert_line(conn, recipe_id=recipe, direction="in", item_id=dust, qty_count=2)

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        plate,
        1,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
    )

    assert result.errors == []
    assert result.steps[0].reusable_inputs == [(mold, "Mold", 1, "count")]


def test_plan_merge_does_not_duplicate_reusable_input_requirements():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    mold = _insert_item(conn, key="mold", name="Mold", is_base=1)
    steel_ingot = _insert_item(conn, key="steel_ingot", name="Steel Ingot", is_base=1)
    steel_rod = _insert_item(conn, key="steel_rod", name="Steel Rod")
    assembly_a = _insert_item(conn, key="assembly_a", name="Assembly A")
    assembly_b = _insert_item(conn, key="assembly_b", name="Assembly B")
    final = _insert_item(conn, key="final_build", name="Final Build")

    rod_recipe = _insert_recipe(conn, name="Make Steel Rod")
    _insert_line(conn, recipe_id=rod_recipe, direction="out", item_id=steel_rod, qty_count=2)
    _insert_line(conn, recipe_id=rod_recipe, direction="in", item_id=steel_ingot, qty_count=2)
    _insert_line(conn, recipe_id=rod_recipe, direction="in", item_id=mold, qty_count=1, consumption_chance=0)

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

    rod_step = next(step for step in result.steps if step.output_item_id == steel_rod)

    assert (mold, "Mold", 1, "count") in rod_step.inputs
    assert any(item_id == steel_ingot and qty > 0 for item_id, _name, qty, _unit in rod_step.inputs)
    assert rod_step.reusable_inputs == [(mold, "Mold", 1, "count")]


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

    refreshed_result = planner.plan(
        item_output,
        1,
        use_inventory=False,
        enabled_tiers=["LV", "MV"],
        crafting_6x6_unlocked=True,
    )
    assert [step.recipe_name for step in refreshed_result.steps] == ["Make Output MV"]



def test_machine_availability_cache_reused_when_profile_unchanged():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    item_input = _insert_item(conn, key="input", name="Input", is_base=1)
    item_output = _insert_item(conn, key="output", name="Output")

    recipe = _insert_recipe(conn, name="Make Output", method="machine", duration_ticks=200)
    _set_recipe_machine(conn, recipe_id=recipe, machine="macerator", tier="LV")
    _insert_line(conn, recipe_id=recipe, direction="out", item_id=item_output, qty_count=1)
    _insert_line(conn, recipe_id=recipe, direction="in", item_id=item_input, qty_count=1)

    _set_machine_availability(profile_conn, machine_type="macerator", tier="LV", owned=1, online=1)
    profile_conn.commit()

    select_count = 0

    def trace_callback(sql: str) -> None:
        nonlocal select_count
        if "FROM machine_availability" in sql:
            select_count += 1

    profile_conn.set_trace_callback(trace_callback)
    planner = PlannerService(conn, profile_conn)

    planner.plan(
        item_output,
        1,
        use_inventory=False,
        enabled_tiers=["LV"],
        crafting_6x6_unlocked=True,
    )
    planner.plan(
        item_output,
        1,
        use_inventory=False,
        enabled_tiers=["LV"],
        crafting_6x6_unlocked=True,
    )

    profile_conn.set_trace_callback(None)

    assert select_count == 1



def test_machine_availability_cache_ignores_unrelated_profile_writes():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    item_input = _insert_item(conn, key="input", name="Input", is_base=1)
    item_output = _insert_item(conn, key="output", name="Output")

    recipe = _insert_recipe(conn, name="Make Output", method="machine", duration_ticks=200)
    _set_recipe_machine(conn, recipe_id=recipe, machine="macerator", tier="LV")
    _insert_line(conn, recipe_id=recipe, direction="out", item_id=item_output, qty_count=1)
    _insert_line(conn, recipe_id=recipe, direction="in", item_id=item_input, qty_count=1)

    _set_machine_availability(profile_conn, machine_type="macerator", tier="LV", owned=1, online=1)
    profile_conn.commit()

    select_count = 0

    def trace_callback(sql: str) -> None:
        nonlocal select_count
        if "FROM machine_availability" in sql:
            select_count += 1

    profile_conn.set_trace_callback(trace_callback)
    planner = PlannerService(conn, profile_conn)

    planner.plan(
        item_output,
        1,
        use_inventory=False,
        enabled_tiers=["LV"],
        crafting_6x6_unlocked=True,
    )

    profile_conn.execute(
        "INSERT INTO app_settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        ("unrelated_setting", "changed"),
    )
    profile_conn.commit()

    planner.plan(
        item_output,
        1,
        use_inventory=False,
        enabled_tiers=["LV"],
        crafting_6x6_unlocked=True,
    )

    profile_conn.set_trace_callback(None)

    assert select_count == 1

def test_apply_overclock_scales_duration_and_power():
    scaled_duration, scaled_eu = apply_overclock(200, 32, "LV", "MV")

    assert scaled_duration == 100
    assert scaled_eu == 128




def test_apply_overclock_supports_perfect_overclock_speed_scaling():
    scaled_duration, scaled_eu = apply_overclock(256, 32, "LV", "HV", is_perfect_overclock=True)

    assert scaled_duration == 16
    assert scaled_eu == 512


def test_apply_overclock_rejects_machine_above_recipe_max_tier():
    scaled_duration, scaled_eu = apply_overclock(200, 32, "LV", "EV", max_tier="HV")

    assert scaled_duration is None
    assert scaled_eu is None
def test_apply_overclock_rejects_lower_tier_machine():
    scaled_duration, scaled_eu = apply_overclock(200, 32, "MV", "LV")

    assert scaled_duration is None
    assert scaled_eu is None


def test_get_calculated_tier_uses_first_configured_tier_for_non_eu_recipe(monkeypatch):
    from services import planner as planner_module

    monkeypatch.setattr(planner_module, "ALL_TIERS", ["Primitive", "LV", "MV"])
    row = {"tier": "", "method": "machine", "eu_per_tick": 0}

    assert planner_module.get_calculated_tier(row) == "Primitive"


def test_load_inventory_sums_all_storage_units():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    item = _insert_item(conn, key="item_a", name="Item A", is_base=1)
    main_storage = profile_conn.execute("SELECT id FROM storage_units WHERE name='Main Storage'").fetchone()["id"]
    profile_conn.execute("INSERT INTO storage_units(name) VALUES('Overflow')")
    overflow_storage = profile_conn.execute("SELECT id FROM storage_units WHERE name='Overflow'").fetchone()["id"]
    profile_conn.execute(
        "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters) VALUES(?,?,?,?)",
        (main_storage, item, 2, None),
    )
    profile_conn.execute(
        "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters) VALUES(?,?,?,?)",
        (overflow_storage, item, 3, None),
    )
    profile_conn.commit()

    planner = PlannerService(conn, profile_conn)
    inventory = planner.load_inventory()
    assert inventory[item] == 5


def test_load_inventory_does_not_fallback_to_legacy_inventory_table():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    item = _insert_item(conn, key="item_a", name="Item A", is_base=1)
    profile_conn.execute(
        "INSERT INTO inventory(item_id, qty_count, qty_liters) VALUES(?,?,?)",
        (item, 99, None),
    )
    profile_conn.commit()

    planner = PlannerService(conn, profile_conn)
    inventory = planner.load_inventory()

    assert inventory == {}


def test_load_inventory_preserves_unit_column_by_item_kind():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    item_solid = _insert_item(conn, key="item_a", name="Item A", kind="item", is_base=1)
    item_fluid = _insert_item(conn, key="fluid_a", name="Fluid A", kind="fluid", is_base=1)
    main_storage = profile_conn.execute("SELECT id FROM storage_units WHERE name='Main Storage'").fetchone()["id"]
    profile_conn.execute(
        "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters) VALUES(?,?,?,?)",
        (main_storage, item_solid, 7, 700),
    )
    profile_conn.execute(
        "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters) VALUES(?,?,?,?)",
        (main_storage, item_fluid, 8, 800),
    )
    profile_conn.commit()

    planner = PlannerService(conn, profile_conn)
    inventory = planner.load_inventory()

    assert inventory[item_solid] == 7
    assert inventory[item_fluid] == 800

def test_load_inventory_excludes_locked_and_disallowed_storage_rows():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    item = _insert_item(conn, key="item_a", name="Item A", is_base=1)
    main_storage = profile_conn.execute("SELECT id FROM storage_units WHERE name='Main Storage'").fetchone()["id"]
    blocked_storage = profile_conn.execute(
        "INSERT INTO storage_units(name, allow_planner_use) VALUES('Blocked', 0) RETURNING id"
    ).fetchone()["id"]
    locked_storage = profile_conn.execute(
        "INSERT INTO storage_units(name, allow_planner_use) VALUES('Locked', 1) RETURNING id"
    ).fetchone()["id"]
    profile_conn.execute(
        "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters, locked) VALUES(?,?,?,?,?)",
        (main_storage, item, 2, None, 0),
    )
    profile_conn.execute(
        "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters, locked) VALUES(?,?,?,?,?)",
        (blocked_storage, item, 3, None, 0),
    )
    profile_conn.execute(
        "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters, locked) VALUES(?,?,?,?,?)",
        (locked_storage, item, 4, None, 1),
    )
    profile_conn.commit()

    planner = PlannerService(conn, profile_conn)
    inventory = planner.load_inventory()

    assert inventory[item] == 2


def test_plan_uses_explicit_container_transform_for_emptying_with_non_matching_names():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    oxygen = _insert_item(conn, key="oxygen", name="Oxygen", kind="gas")
    canister_empty = _insert_item(conn, key="canister_empty", name="Steel Canister", kind="item")
    canister_full = _insert_item(
        conn,
        key="oxygen_canister_pressurized",
        name="Pressurized Oxygen Canister",
        kind="item",
        content_fluid_id=oxygen,
        content_qty_liters=1000,
    )
    output = _insert_item(conn, key="oxygenated_mix", name="Oxygenated Mix")

    conn.execute(
        """
        INSERT INTO item_container_transforms(
            container_item_id,
            empty_item_id,
            content_item_id,
            content_qty,
            transform_kind
        ) VALUES(?,?,?,?,?)
        """,
        (canister_full, canister_empty, oxygen, 1000, "bidirectional"),
    )

    recipe = _insert_recipe(conn, name="Make Oxygenated Mix")
    _insert_line(conn, recipe_id=recipe, direction="out", item_id=output, qty_count=1)
    _insert_line(conn, recipe_id=recipe, direction="in", item_id=oxygen, qty_liters=1000)

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        output,
        1,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
        inventory_override={canister_full: 1},
    )

    assert result.errors == []
    assert result.shopping_list == []
    assert [step.recipe_name for step in result.steps] == ["Emptying", "Make Oxygenated Mix"]
    assert result.steps[0].byproducts == [(canister_empty, "Steel Canister", 1, "count", 100.0)]


def test_plan_uses_explicit_container_transform_for_filling_when_names_do_not_match():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    naphtha = _insert_item(conn, key="naphtha", name="Naphtha", kind="fluid")
    steel_drum = _insert_item(conn, key="drum_empty", name="Steel Drum", kind="item")
    filled_drum = _insert_item(
        conn,
        key="naphtha_drum_special",
        name="Industrial Feed Drum",
        kind="item",
        content_fluid_id=naphtha,
        content_qty_liters=2000,
    )

    conn.execute(
        """
        INSERT INTO item_container_transforms(
            container_item_id,
            empty_item_id,
            content_item_id,
            content_qty,
            transform_kind
        ) VALUES(?,?,?,?,?)
        """,
        (filled_drum, steel_drum, naphtha, 2000, "bidirectional"),
    )

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        filled_drum,
        1,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
        inventory_override={naphtha: 2000, steel_drum: 1},
    )

    assert result.errors == []
    assert result.shopping_list == []
    assert [step.recipe_name for step in result.steps] == ["Filling"]
    assert result.steps[0].inputs == [
        (naphtha, "Naphtha", 2000, "L"),
        (steel_drum, "Steel Drum", 1, "count"),
    ]


def test_plan_prefers_lower_priority_transform_for_emptying():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    oxygen = _insert_item(conn, key="oxygen", name="Oxygen", kind="gas")
    canister_empty = _insert_item(conn, key="canister_empty", name="Steel Canister", kind="item")
    canister_a = _insert_item(conn, key="oxygen_canister_a", name="Canister A", kind="item", content_fluid_id=oxygen, content_qty_liters=1000)
    canister_b = _insert_item(conn, key="oxygen_canister_b", name="Canister B", kind="item", content_fluid_id=oxygen, content_qty_liters=1000)
    output = _insert_item(conn, key="oxygenated_mix", name="Oxygenated Mix")

    conn.execute(
        """
        INSERT INTO item_container_transforms(priority, container_item_id, empty_item_id, content_item_id, content_qty, transform_kind)
        VALUES(?,?,?,?,?,?)
        """,
        (5, canister_a, canister_empty, oxygen, 1000, "bidirectional"),
    )
    conn.execute(
        """
        INSERT INTO item_container_transforms(priority, container_item_id, empty_item_id, content_item_id, content_qty, transform_kind)
        VALUES(?,?,?,?,?,?)
        """,
        (0, canister_b, canister_empty, oxygen, 1000, "bidirectional"),
    )

    recipe = _insert_recipe(conn, name="Make Oxygenated Mix")
    _insert_line(conn, recipe_id=recipe, direction="out", item_id=output, qty_count=1)
    _insert_line(conn, recipe_id=recipe, direction="in", item_id=oxygen, qty_liters=1000)

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        output,
        1,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
        inventory_override={canister_a: 1, canister_b: 1},
    )

    assert result.errors == []
    assert result.shopping_list == []
    assert [step.recipe_name for step in result.steps] == ["Emptying", "Make Oxygenated Mix"]
    assert result.steps[0].inputs[0][0] == canister_b


def test_plan_prefers_lower_priority_transform_for_filling_same_container():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    naphtha = _insert_item(conn, key="naphtha", name="Naphtha", kind="fluid")
    water = _insert_item(conn, key="water", name="Water", kind="fluid")
    drum_empty = _insert_item(conn, key="drum_empty", name="Steel Drum", kind="item")
    drum = _insert_item(conn, key="naphtha_drum_a", name="Naphtha Drum A", kind="item", content_fluid_id=naphtha, content_qty_liters=2000)

    conn.execute(
        """
        INSERT INTO item_container_transforms(priority, container_item_id, empty_item_id, content_item_id, content_qty, transform_kind)
        VALUES(?,?,?,?,?,?)
        """,
        (10, drum, drum_empty, water, 1000, "bidirectional"),
    )
    conn.execute(
        """
        INSERT INTO item_container_transforms(priority, container_item_id, empty_item_id, content_item_id, content_qty, transform_kind)
        VALUES(?,?,?,?,?,?)
        """,
        (0, drum, drum_empty, naphtha, 2000, "bidirectional"),
    )

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        drum,
        1,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
        inventory_override={naphtha: 2000, water: 0, drum_empty: 1},
    )

    assert result.errors == []
    assert [step.recipe_name for step in result.steps] == ["Filling"]
    assert result.steps[0].inputs[0][0] == naphtha


def test_plan_applies_empty_only_transform_for_non_fluid_container_emptying():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    hydrogen = _insert_item(conn, key="hydrogen", name="Hydrogen", kind="gas")
    canister_empty = _insert_item(conn, key="canister_empty", name="Titanium Canister", kind="item")
    canister_full = _insert_item(
        conn,
        key="hydrogen_canister_full",
        name="Hydrogen Canister",
        kind="item",
        content_fluid_id=hydrogen,
        content_qty_liters=1000,
    )
    output = _insert_item(conn, key="hydrogen_mix", name="Hydrogen Mix")

    conn.execute(
        """
        INSERT INTO item_container_transforms(
            container_item_id,
            empty_item_id,
            content_item_id,
            content_qty,
            transform_kind
        ) VALUES(?,?,?,?,?)
        """,
        (canister_full, canister_empty, hydrogen, 1000, "empty_only"),
    )

    recipe = _insert_recipe(conn, name="Make Hydrogen Mix")
    _insert_line(conn, recipe_id=recipe, direction="out", item_id=output, qty_count=1)
    _insert_line(conn, recipe_id=recipe, direction="in", item_id=hydrogen, qty_liters=1000)

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        output,
        1,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
        inventory_override={canister_full: 1},
    )

    assert result.errors == []
    assert result.shopping_list == []
    assert [step.recipe_name for step in result.steps] == ["Emptying", "Make Hydrogen Mix"]
    assert result.steps[0].byproducts == [(canister_empty, "Titanium Canister", 1, "count", 100.0)]




def test_plan_does_not_return_consumed_empty_container_byproduct():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    water = _insert_item(conn, key="water", name="Water", kind="fluid")
    vial_empty = _insert_item(conn, key="vial_empty", name="Fragile Vial", kind="item")
    vial_full = _insert_item(
        conn,
        key="vial_water",
        name="Water Vial",
        kind="item",
        content_fluid_id=water,
        content_qty_liters=250,
    )
    output = _insert_item(conn, key="hydrated_dust", name="Hydrated Dust")

    conn.execute(
        """
        INSERT INTO item_container_transforms(
            container_item_id,
            empty_item_id,
            empty_item_is_consumed,
            content_item_id,
            content_qty,
            transform_kind
        ) VALUES(?,?,?,?,?,?)
        """,
        (vial_full, vial_empty, 1, water, 250, "empty_only"),
    )

    recipe = _insert_recipe(conn, name="Wet Blend")
    _insert_line(conn, recipe_id=recipe, direction="out", item_id=output, qty_count=1)
    _insert_line(conn, recipe_id=recipe, direction="in", item_id=water, qty_liters=250)

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        output,
        1,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
        inventory_override={vial_full: 1},
    )

    assert result.errors == []
    assert result.steps[0].recipe_name == "Emptying"
    assert result.steps[0].byproducts == []

def test_plan_does_not_apply_empty_only_transform_for_filling_request():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    hydrogen = _insert_item(conn, key="hydrogen", name="Hydrogen", kind="gas")
    canister_empty = _insert_item(conn, key="canister_empty", name="Titanium Canister", kind="item")
    canister_full = _insert_item(
        conn,
        key="hydrogen_canister_full",
        name="Hydrogen Canister",
        kind="item",
        content_fluid_id=hydrogen,
        content_qty_liters=1000,
    )

    conn.execute(
        """
        INSERT INTO item_container_transforms(
            container_item_id,
            empty_item_id,
            content_item_id,
            content_qty,
            transform_kind
        ) VALUES(?,?,?,?,?)
        """,
        (canister_full, canister_empty, hydrogen, 1000, "empty_only"),
    )

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        canister_full,
        1,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
        inventory_override={hydrogen: 1000, canister_empty: 1},
    )

    assert result.errors == ["No recipe found for Hydrogen Canister."]
    assert result.steps == []
    assert result.shopping_list == []


def test_plan_applies_fill_only_transform_for_non_fluid_container_filling():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    hydrogen = _insert_item(conn, key="hydrogen", name="Hydrogen", kind="gas")
    canister_empty = _insert_item(conn, key="canister_empty", name="Titanium Canister", kind="item")
    canister_full = _insert_item(
        conn,
        key="hydrogen_canister_full",
        name="Hydrogen Canister",
        kind="item",
        content_fluid_id=hydrogen,
        content_qty_liters=1000,
    )

    conn.execute(
        """
        INSERT INTO item_container_transforms(
            container_item_id,
            empty_item_id,
            content_item_id,
            content_qty,
            transform_kind
        ) VALUES(?,?,?,?,?)
        """,
        (canister_full, canister_empty, hydrogen, 1000, "fill_only"),
    )

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        canister_full,
        1,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
        inventory_override={hydrogen: 1000, canister_empty: 1},
    )

    assert result.errors == []
    assert [step.recipe_name for step in result.steps] == ["Filling"]


def test_plan_does_not_apply_fill_only_transform_for_emptying_request():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    hydrogen = _insert_item(conn, key="hydrogen", name="Hydrogen", kind="gas")
    canister_empty = _insert_item(conn, key="canister_empty", name="Titanium Canister", kind="item")
    canister_full = _insert_item(
        conn,
        key="hydrogen_canister_full",
        name="Hydrogen Canister",
        kind="item",
        content_fluid_id=hydrogen,
        content_qty_liters=1000,
    )
    output = _insert_item(conn, key="hydrogen_mix", name="Hydrogen Mix")

    conn.execute(
        """
        INSERT INTO item_container_transforms(
            container_item_id,
            empty_item_id,
            content_item_id,
            content_qty,
            transform_kind
        ) VALUES(?,?,?,?,?)
        """,
        (canister_full, canister_empty, hydrogen, 1000, "fill_only"),
    )

    recipe = _insert_recipe(conn, name="Make Hydrogen Mix")
    _insert_line(conn, recipe_id=recipe, direction="out", item_id=output, qty_count=1)
    _insert_line(conn, recipe_id=recipe, direction="in", item_id=hydrogen, qty_liters=1000)

    planner = PlannerService(conn, profile_conn)
    result = planner.plan(
        output,
        1,
        use_inventory=True,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
        inventory_override={canister_full: 1},
    )

    assert result.errors == ["No recipe found for Hydrogen."]
    assert [step.recipe_name for step in result.steps] == ["Make Hydrogen Mix"]
    assert result.shopping_list == []


def test_pick_recipe_handles_zero_output_qty_without_division_errors():
    conn = _setup_conn()
    profile_conn = connect_profile(":memory:")

    input_item = _insert_item(conn, key="input_item", name="Input", is_base=1)
    output_item = _insert_item(conn, key="output_item", name="Output")

    bad_recipe = _insert_recipe(conn, name="Bad Recipe", method="machine", duration_ticks=200, eu_per_tick=30)
    _insert_line(conn, recipe_id=bad_recipe, direction="out", item_id=output_item, qty_count=0)
    _insert_line(conn, recipe_id=bad_recipe, direction="in", item_id=input_item, qty_count=1)

    good_recipe = _insert_recipe(conn, name="Good Recipe", method="machine", duration_ticks=200, eu_per_tick=30)
    _insert_line(conn, recipe_id=good_recipe, direction="out", item_id=output_item, qty_count=1)
    _insert_line(conn, recipe_id=good_recipe, direction="in", item_id=input_item, qty_count=1)

    planner = PlannerService(conn, profile_conn)

    picked = planner._pick_recipe_for_item(
        output_item,
        enabled_tiers=[],
        crafting_6x6_unlocked=True,
        items=planner._load_items(),
    )

    assert picked is not None
    assert picked["id"] == good_recipe
