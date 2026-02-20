from services.db import connect_profile
from services.storage import create_storage_unit
from ui_tabs.planner_tab_qt import PlannerTab


class _DummyApp:
    def __init__(self, conn):
        self.profile_conn = conn
        self.items = [{"id": 1, "kind": "item"}]
        self._active_storage_id = None

    def get_active_storage_id(self):
        return self._active_storage_id


class _DummyTab:
    _planner_storage_id = PlannerTab._planner_storage_id
    _adjust_inventory_qty = PlannerTab._adjust_inventory_qty

    def __init__(self, app):
        self.app = app


def test_adjust_inventory_qty_cascades_deductions_in_aggregate_view() -> None:
    conn = connect_profile(":memory:")
    app = _DummyApp(conn)
    tab = _DummyTab(app)

    alpha_id = create_storage_unit(conn, name="Alpha", priority=5)
    beta_id = create_storage_unit(conn, name="Beta", priority=1)

    conn.execute(
        "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters) VALUES(?, 1, 10, NULL)",
        (alpha_id,),
    )
    conn.execute(
        "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters) VALUES(?, 1, 90, NULL)",
        (beta_id,),
    )
    conn.commit()

    tab._adjust_inventory_qty(1, -80)

    alpha_row = conn.execute(
        "SELECT qty_count FROM storage_assignments WHERE storage_id=? AND item_id=1",
        (alpha_id,),
    ).fetchone()
    beta_qty = conn.execute(
        "SELECT qty_count FROM storage_assignments WHERE storage_id=? AND item_id=1",
        (beta_id,),
    ).fetchone()["qty_count"]

    assert alpha_row is None
    assert beta_qty == 20


def test_adjust_inventory_qty_aggregate_deduction_keeps_active_mode_behavior() -> None:
    conn = connect_profile(":memory:")
    app = _DummyApp(conn)
    tab = _DummyTab(app)

    main_id = conn.execute("SELECT id FROM storage_units WHERE name='Main Storage'").fetchone()["id"]
    overflow_id = create_storage_unit(conn, name="Overflow", priority=99)

    conn.execute(
        "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters) VALUES(?, 1, 10, NULL)",
        (main_id,),
    )
    conn.execute(
        "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters) VALUES(?, 1, 90, NULL)",
        (overflow_id,),
    )
    conn.commit()

    app._active_storage_id = main_id
    tab._adjust_inventory_qty(1, -20)

    main_row = conn.execute(
        "SELECT qty_count FROM storage_assignments WHERE storage_id=? AND item_id=1",
        (main_id,),
    ).fetchone()
    overflow_qty = conn.execute(
        "SELECT qty_count FROM storage_assignments WHERE storage_id=? AND item_id=1",
        (overflow_id,),
    ).fetchone()["qty_count"]

    assert main_row is None
    assert overflow_qty == 90


def test_adjust_inventory_qty_aggregate_deduction_bottoms_out_at_zero() -> None:
    conn = connect_profile(":memory:")
    app = _DummyApp(conn)
    tab = _DummyTab(app)

    alpha_id = create_storage_unit(conn, name="Alpha", priority=5)
    beta_id = create_storage_unit(conn, name="Beta", priority=1)

    conn.execute(
        "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters) VALUES(?, 1, 10, NULL)",
        (alpha_id,),
    )
    conn.execute(
        "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters) VALUES(?, 1, 90, NULL)",
        (beta_id,),
    )
    conn.commit()

    tab._adjust_inventory_qty(1, -150)

    remaining_rows = conn.execute(
        "SELECT storage_id, qty_count FROM storage_assignments WHERE item_id=1"
    ).fetchall()

    assert remaining_rows == []

def test_adjust_inventory_qty_aggregate_skips_disallowed_and_locked_rows() -> None:
    conn = connect_profile(":memory:")
    app = _DummyApp(conn)
    tab = _DummyTab(app)

    allowed_id = create_storage_unit(conn, name="Allowed", priority=10, allow_planner_use=True)
    blocked_id = create_storage_unit(conn, name="Blocked", priority=20, allow_planner_use=False)
    locked_id = create_storage_unit(conn, name="Locked", priority=30, allow_planner_use=True)

    conn.execute(
        "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters, locked) VALUES(?, 1, 50, NULL, 0)",
        (allowed_id,),
    )
    conn.execute(
        "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters, locked) VALUES(?, 1, 50, NULL, 0)",
        (blocked_id,),
    )
    conn.execute(
        "INSERT INTO storage_assignments(storage_id, item_id, qty_count, qty_liters, locked) VALUES(?, 1, 50, NULL, 1)",
        (locked_id,),
    )
    conn.commit()

    tab._adjust_inventory_qty(1, -40)

    allowed_qty = conn.execute(
        "SELECT qty_count FROM storage_assignments WHERE storage_id=? AND item_id=1",
        (allowed_id,),
    ).fetchone()["qty_count"]
    blocked_qty = conn.execute(
        "SELECT qty_count FROM storage_assignments WHERE storage_id=? AND item_id=1",
        (blocked_id,),
    ).fetchone()["qty_count"]
    locked_qty = conn.execute(
        "SELECT qty_count FROM storage_assignments WHERE storage_id=? AND item_id=1",
        (locked_id,),
    ).fetchone()["qty_count"]

    assert allowed_qty == 10
    assert blocked_qty == 50
    assert locked_qty == 50
