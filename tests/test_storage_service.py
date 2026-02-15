import sqlite3

from services.db import connect_profile
from services.storage import (
    MAIN_STORAGE_NAME,
    aggregate_assignment_for_item,
    aggregated_assignment_rows,
    create_storage_unit,
    default_storage_id,
    delete_assignment,
    delete_storage_unit,
    get_assignment,
    has_storage_tables,
    list_storage_units,
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
