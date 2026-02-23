from services.automation import add_step, create_plan, list_plans, list_steps, update_step_status, delete_step
from services.db import connect_profile


def test_automation_plan_lifecycle(tmp_path):
    conn = connect_profile(tmp_path / "profile.db")

    plan_id = create_plan(conn, "Ore Processing")
    plans = list_plans(conn)
    assert [row["name"] for row in plans] == ["Ore Processing"]

    step_id = add_step(
        conn,
        plan_id=plan_id,
        machine_name="Macerator",
        input_name="Iron Ore",
        output_name="Crushed Iron Ore",
        byproduct_name="Stone Dust",
    )
    steps = list_steps(conn, plan_id)
    assert len(steps) == 1
    assert steps[0]["id"] == step_id
    assert steps[0]["step_order"] == 1
    assert steps[0]["status"] == "planned"

    update_step_status(conn, step_id, "active")
    steps = list_steps(conn, plan_id)
    assert steps[0]["status"] == "active"

    delete_step(conn, step_id)
    assert list_steps(conn, plan_id) == []
