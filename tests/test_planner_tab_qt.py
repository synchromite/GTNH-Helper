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


class _StatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, message):
        self.messages.append(message)


class _InventoryChangeTab:
    on_inventory_changed = PlannerTab.on_inventory_changed

    def __init__(self):
        self.last_plan_run = True
        self.last_plan_used_inventory = True
        self.target_item_id = 1
        self.build_steps = [object()]
        self.build_completed_steps = {0}
        self.app = type("_App", (), {"status_bar": _StatusBar()})()
        self._plan_run_called = False
        self._refresh_inventory_called = False
        self._refresh_steps_called = False

    class _UseInventory:
        @staticmethod
        def isChecked():
            return True

    use_inventory_checkbox = _UseInventory()

    @staticmethod
    def _parse_target_qty(*, show_errors):
        assert show_errors is False
        return 1

    def _run_plan_with_qty(self, qty, *, set_status):
        self._plan_run_called = True

    def _refresh_build_inventory(self):
        self._refresh_inventory_called = True

    def _refresh_build_steps_on_inventory_change(self, qty):
        self._refresh_steps_called = True


def test_on_inventory_changed_skips_replan_during_active_build_progress() -> None:
    tab = _InventoryChangeTab()

    tab.on_inventory_changed()

    assert tab._plan_run_called is False
    assert tab._refresh_inventory_called is False
    assert tab._refresh_steps_called is False
    assert tab.app.status_bar.messages
    assert "skipped auto re-plan" in tab.app.status_bar.messages[-1]
