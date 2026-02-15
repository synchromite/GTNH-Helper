import sqlite3

from services.db import connect_profile
from services.storage import (
    MAIN_STORAGE_NAME,
    aggregate_assignment_for_item,
    assignment_slot_usage,
    aggregated_assignment_rows,
    create_storage_unit,
    default_storage_id,
    delete_assignment,
    delete_storage_unit,
    get_assignment,
    has_storage_tables,
    list_storage_units,
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
