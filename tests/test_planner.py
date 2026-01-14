import sqlite3

import pytest

from services.db import ensure_schema, connect_profile
from services.planner import PlannerService, apply_overclock


def _setup_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


def _insert_item(conn, *, key, name, kind="item", is_base=0):
    conn.execute(
        "INSERT INTO items(key, display_name, kind, is_base) VALUES(?,?,?,?)",
        (key, name, kind, is_base),
    )
    return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def _insert_recipe(conn, *, name, method="crafting", duration_ticks=None, eu_per_tick=None):
    conn.execute(
        "INSERT INTO recipes(name, method, duration_ticks, eu_per_tick) VALUES(?, ?, ?, ?)",
        (name, method, duration_ticks, eu_per_tick),
    )
    return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def _insert_line(conn, *, recipe_id, direction, item_id, qty_count=None, qty_liters=None):
    conn.execute(
        "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_count, qty_liters) "
        "VALUES(?,?,?,?,?)",
        (recipe_id, direction, item_id, qty_count, qty_liters),
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
    assert [step.output_item_name for step in result.steps] == ["Item B", "Item C"]


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


def test_apply_overclock_scales_duration_and_power():
    scaled_duration, scaled_eu = apply_overclock(200, 32, "LV", "MV")

    assert scaled_duration == 100
    assert scaled_eu == 128
