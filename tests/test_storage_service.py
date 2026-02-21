import sqlite3

from services.db import connect_profile
from services.storage import (
    MAIN_STORAGE_NAME,
    adjust_assignment_qty_for_storage,
    aggregate_assignment_for_item,
    assignment_slot_usage,
    aggregated_assignment_rows,
    consume_assignment_qty_for_planner,
    create_storage_unit,
    default_storage_id,
    delete_assignment,
    delete_storage_unit,
    get_assignment,
    has_storage_tables,
    list_storage_units,
    planner_consumption_candidates,
    storage_inventory_totals,
    validate_storage_fit_for_item,
    update_storage_unit,
    upsert_assignment,
)


def test_storage_service_crud_and_aggregation(tmp_path) -> None:
    conn = connect_profile(tmp_path / "profile.db")
    try:
        assert has_storage_tables(conn)

        main_storage = default_storage_id(conn)
        assert main_storage is not None

        overflow_storage = create_storage_unit(conn, name="Overflow", slot_count=27, liter_capacity=16000)
        conn.commit()

        storages = list_storage_units(conn)
        assert storages[0]["name"] == MAIN_STORAGE_NAME
        assert any(row["id"] == overflow_storage for row in storages)

        update_storage_unit(conn, overflow_storage, notes="Bulk overflow", allow_planner_use=False)
        conn.commit()
        updated = [row for row in list_storage_units(conn) if row["id"] == overflow_storage][0]
        assert updated["notes"] == "Bulk overflow"
        assert updated["allow_planner_use"] == 0

        upsert_assignment(conn, storage_id=main_storage, item_id=11, qty_count=2, qty_liters=None)
        upsert_assignment(conn, storage_id=overflow_storage, item_id=11, qty_count=3, qty_liters=None)
        upsert_assignment(conn, storage_id=overflow_storage, item_id=12, qty_count=None, qty_liters=1500)
        conn.commit()

        one_assignment = get_assignment(conn, storage_id=overflow_storage, item_id=11)
        assert one_assignment is not None
        assert int(one_assignment["qty_count"]) == 3

        aggregate = aggregate_assignment_for_item(conn, 11)
        assert aggregate is not None
        assert int(aggregate["qty_count"]) == 5

        all_rows = {int(row["item_id"]): row for row in aggregated_assignment_rows(conn)}
        assert int(all_rows[11]["qty_count"]) == 5
        assert int(all_rows[12]["qty_liters"]) == 1500

        totals_all = storage_inventory_totals(conn)
        assert totals_all == {"entry_count": 3, "total_count": 5, "total_liters": 1500}

        totals_overflow = storage_inventory_totals(conn, overflow_storage)
        assert totals_overflow == {"entry_count": 2, "total_count": 3, "total_liters": 1500}

        delete_assignment(conn, storage_id=overflow_storage, item_id=11)
        conn.commit()
        assert get_assignment(conn, storage_id=overflow_storage, item_id=11) is None

        delete_storage_unit(conn, overflow_storage)
        conn.commit()
        assert conn.execute("SELECT 1 FROM storage_units WHERE id=?", (overflow_storage,)).fetchone() is None
    finally:
        conn.close()


def test_default_storage_id_prefers_main_storage_name(tmp_path) -> None:
    conn = sqlite3.connect(tmp_path / "profile.db")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE storage_units(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE)")
    conn.execute("INSERT INTO storage_units(name) VALUES('Zeta')")
    conn.execute("INSERT INTO storage_units(name) VALUES('Main Storage')")
    conn.commit()

    try:
        assert default_storage_id(conn) == 2
    finally:
        conn.close()


def test_assignment_slot_usage_handles_non_stackables() -> None:
    assert assignment_slot_usage(0, 64) == 0
    assert assignment_slot_usage(1, 1) == 1
    assert assignment_slot_usage(2, 1) == 2
    assert assignment_slot_usage(65, 64) == 2


def test_validate_storage_fit_for_item_boundary_cases(tmp_path) -> None:
    conn = connect_profile(tmp_path / "profile.db")
    try:
        main_storage = default_storage_id(conn)
        assert main_storage is not None
        conn.execute(
            "UPDATE storage_units SET slot_count=?, liter_capacity=? WHERE id=?",
            (2, 1000, main_storage),
        )
        conn.execute(
            "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters) VALUES(?, ?, ?, ?)",
            (main_storage, 100, 64, None),
        )
        conn.execute(
            "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters) VALUES(?, ?, ?, ?)",
            (main_storage, 101, None, 1000),
        )

        exact_fit = validate_storage_fit_for_item(
            conn,
            storage_id=main_storage,
            item_id=100,
            qty_count=128,
            qty_liters=None,
            item_max_stack_size=64,
            known_item_stack_sizes={100: 64},
        )
        assert exact_fit["fits"] is True
        assert exact_fit["slot_usage"] == 2

        slot_overflow = validate_storage_fit_for_item(
            conn,
            storage_id=main_storage,
            item_id=102,
            qty_count=2,
            qty_liters=None,
            item_max_stack_size=1,
            known_item_stack_sizes={100: 64, 102: 1},
        )
        assert slot_overflow["fits_slots"] is False
        assert slot_overflow["slot_overflow"] == 1

        liter_overflow = validate_storage_fit_for_item(
            conn,
            storage_id=main_storage,
            item_id=101,
            qty_count=None,
            qty_liters=1001,
            item_max_stack_size=64,
            known_item_stack_sizes={100: 64},
        )
        assert liter_overflow["fits_liters"] is False
        assert int(liter_overflow["liter_overflow"]) == 1
    finally:
        conn.close()

def test_storage_service_supports_container_counts(tmp_path) -> None:
    conn = connect_profile(tmp_path / "profile.db")
    try:
        storage_id = create_storage_unit(
            conn,
            name="Iron Chests",
            slot_count=108,
            container_item_id=42,
            owned_count=4,
            placed_count=2,
        )
        conn.commit()

        row = conn.execute(
            "SELECT slot_count, container_item_id, owned_count, placed_count FROM storage_units WHERE id=?",
            (storage_id,),
        ).fetchone()
        assert row is not None
        assert row["slot_count"] == 108
        assert row["container_item_id"] == 42
        assert row["owned_count"] == 4
        assert row["placed_count"] == 2
    finally:
        conn.close()

def test_recompute_storage_slot_capacities_uses_player_slots_and_placements(tmp_path) -> None:
    from services.storage import recompute_storage_slot_capacities, set_storage_container_placement

    conn = connect_profile(tmp_path / "profile.db")
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT, display_name TEXT, storage_slot_count INTEGER)"
        )
        conn.execute(
            "INSERT INTO items(key, display_name, storage_slot_count) VALUES(?,?,?)",
            ("wood_chest", "Wood Chest", 27),
        )
        conn.execute(
            "INSERT INTO items(key, display_name, storage_slot_count) VALUES(?,?,?)",
            ("diamond_chest", "Diamond Chest", 104),
        )
        conn.execute("INSERT INTO storage_units(name, kind) VALUES('Ore Storage', 'ore')")
        conn.commit()

        main_storage = conn.execute("SELECT id FROM storage_units WHERE name='Main Storage'").fetchone()["id"]
        ore_storage = conn.execute("SELECT id FROM storage_units WHERE name='Ore Storage'").fetchone()["id"]

        set_storage_container_placement(conn, storage_id=main_storage, item_id=1, placed_count=1)
        set_storage_container_placement(conn, storage_id=ore_storage, item_id=2, placed_count=1)
        recompute_storage_slot_capacities(conn, player_slots=36, content_conn=conn)
        conn.commit()

        main_slots = conn.execute("SELECT slot_count FROM storage_units WHERE id=?", (main_storage,)).fetchone()["slot_count"]
        ore_slots = conn.execute("SELECT slot_count FROM storage_units WHERE id=?", (ore_storage,)).fetchone()["slot_count"]
        assert main_slots == 63
        assert ore_slots == 104
    finally:
        conn.close()

def test_storage_slot_usage_ignores_container_items(tmp_path) -> None:
    from services.storage import storage_slot_usage

    conn = connect_profile(tmp_path / "profile.db")
    try:
        main_storage = conn.execute("SELECT id FROM storage_units WHERE name='Main Storage'").fetchone()["id"]
        conn.execute(
            "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters) VALUES(?, ?, ?, ?)",
            (main_storage, 1, 64, None),
        )
        conn.execute(
            "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters) VALUES(?, ?, ?, ?)",
            (main_storage, 2, 64, None),
        )
        conn.execute("UPDATE storage_units SET slot_count=? WHERE id=?", (10, main_storage))
        conn.commit()

        usage = storage_slot_usage(
            conn,
            storage_id=main_storage,
            known_item_stack_sizes={1: 64, 2: 64},
            known_container_item_ids={2},
        )
        assert usage["slot_used"] == 1
        assert usage["slot_free"] == 9
    finally:
        conn.close()


def test_placed_container_count_excludes_selected_storage(tmp_path) -> None:
    from services.storage import placed_container_count, set_storage_container_placement

    conn = connect_profile(tmp_path / "profile.db")
    try:
        conn.execute("INSERT INTO storage_units(name, kind) VALUES('Dust Storage', 'dust')")
        conn.execute("INSERT INTO storage_units(name, kind) VALUES('Ore Storage', 'ore')")
        conn.commit()

        dust_id = conn.execute("SELECT id FROM storage_units WHERE name='Dust Storage'").fetchone()["id"]
        ore_id = conn.execute("SELECT id FROM storage_units WHERE name='Ore Storage'").fetchone()["id"]

        set_storage_container_placement(conn, storage_id=dust_id, item_id=11, placed_count=2)
        set_storage_container_placement(conn, storage_id=ore_id, item_id=11, placed_count=1)
        conn.commit()

        assert placed_container_count(conn, item_id=11) == 3
        assert placed_container_count(conn, item_id=11, exclude_storage_id=dust_id) == 1
    finally:
        conn.close()


def test_planner_consumption_candidates_respect_policy_and_priority(tmp_path) -> None:
    conn = connect_profile(tmp_path / "profile.db")
    try:
        item_id = 99
        high = create_storage_unit(conn, name="High", priority=10, allow_planner_use=True)
        low = create_storage_unit(conn, name="Low", priority=1, allow_planner_use=True)
        blocked = create_storage_unit(conn, name="Blocked", priority=100, allow_planner_use=False)
        locked = create_storage_unit(conn, name="Locked", priority=50, allow_planner_use=True)

        upsert_assignment(conn, storage_id=high, item_id=item_id, qty_count=5, qty_liters=None, locked=False)
        upsert_assignment(conn, storage_id=low, item_id=item_id, qty_count=5, qty_liters=None, locked=False)
        upsert_assignment(conn, storage_id=blocked, item_id=item_id, qty_count=5, qty_liters=None, locked=False)
        upsert_assignment(conn, storage_id=locked, item_id=item_id, qty_count=5, qty_liters=None, locked=True)
        conn.commit()

        rows = planner_consumption_candidates(conn, item_id=item_id, item_kind="item")
        assert [int(r["storage_id"]) for r in rows] == [high, low]
    finally:
        conn.close()


def test_consume_assignment_qty_for_planner_uses_deterministic_tiebreaker(tmp_path) -> None:
    conn = connect_profile(tmp_path / "profile.db")
    try:
        item_id = 101
        first = create_storage_unit(conn, name="A", priority=7, allow_planner_use=True)
        second = create_storage_unit(conn, name="B", priority=7, allow_planner_use=True)

        upsert_assignment(conn, storage_id=first, item_id=item_id, qty_count=4, qty_liters=None, locked=False)
        upsert_assignment(conn, storage_id=second, item_id=item_id, qty_count=4, qty_liters=None, locked=False)
        conn.commit()

        consumed = consume_assignment_qty_for_planner(conn, item_id=item_id, qty=6, item_kind="item")
        conn.commit()

        assert consumed == 6
        first_row = get_assignment(conn, storage_id=first, item_id=item_id)
        second_row = get_assignment(conn, storage_id=second, item_id=item_id)
        assert first_row is None
        assert second_row is not None
        assert int(second_row["qty_count"]) == 2
    finally:
        conn.close()


def test_adjust_assignment_qty_for_storage_active_mode_preserves_locked_flag(tmp_path) -> None:
    conn = connect_profile(tmp_path / "profile.db")
    try:
        storage_id = create_storage_unit(conn, name="Manual", allow_planner_use=False)
        upsert_assignment(conn, storage_id=storage_id, item_id=77, qty_count=10, qty_liters=None, locked=True)
        conn.commit()

        remaining = adjust_assignment_qty_for_storage(
            conn,
            storage_id=storage_id,
            item_id=77,
            delta=-3,
            item_kind="item",
            respect_locked=False,
        )
        conn.commit()

        assert remaining == 7
        row = get_assignment(conn, storage_id=storage_id, item_id=77)
        assert row is not None
        assert int(row["qty_count"]) == 7
        assert int(row["locked"]) == 1
    finally:
        conn.close()


def test_adjust_assignment_qty_for_storage_can_enforce_locked_guard(tmp_path) -> None:
    conn = connect_profile(tmp_path / "profile.db")
    try:
        storage_id = create_storage_unit(conn, name="Guarded")
        upsert_assignment(conn, storage_id=storage_id, item_id=88, qty_count=9, qty_liters=None, locked=True)
        conn.commit()

        remaining = adjust_assignment_qty_for_storage(
            conn,
            storage_id=storage_id,
            item_id=88,
            delta=-4,
            item_kind="item",
            respect_locked=True,
        )
        conn.commit()

        assert remaining == 9
        row = get_assignment(conn, storage_id=storage_id, item_id=88)
        assert row is not None
        assert int(row["qty_count"]) == 9
        assert int(row["locked"]) == 1
    finally:
        conn.close()
