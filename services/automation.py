from __future__ import annotations

import sqlite3


def list_plans(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, name, COALESCE(notes, '') AS notes
        FROM automation_plans
        ORDER BY name COLLATE NOCASE
        """
    ).fetchall()


def create_plan(conn: sqlite3.Connection, name: str, notes: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO automation_plans(name, notes) VALUES(?, ?)",
        (name.strip(), notes.strip() or None),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_steps(conn: sqlite3.Connection, plan_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, step_order,
               machine_item_id, machine_name,
               input_item_id, input_name,
               output_item_id, output_name,
               byproduct_item_id, COALESCE(byproduct_name, '') AS byproduct_name,
               status, COALESCE(notes, '') AS notes
        FROM automation_steps
        WHERE plan_id = ?
        ORDER BY step_order, id
        """,
        (plan_id,),
    ).fetchall()


def add_step(
    conn: sqlite3.Connection,
    *,
    plan_id: int,
    machine_item_id: int,
    machine_name: str,
    input_item_id: int,
    input_name: str,
    output_item_id: int,
    output_name: str,
    byproduct_item_id: int | None = None,
    byproduct_name: str = "",
    notes: str = "",
) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(step_order), 0) + 1 AS next_order FROM automation_steps WHERE plan_id = ?",
        (plan_id,),
    ).fetchone()
    next_order = int(row["next_order"] if row is not None else 1)
    cur = conn.execute(
        """
        INSERT INTO automation_steps(
            plan_id,
            step_order,
            machine_item_id,
            machine_name,
            input_item_id,
            input_name,
            output_item_id,
            output_name,
            byproduct_item_id,
            byproduct_name,
            notes
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            plan_id,
            next_order,
            machine_item_id,
            machine_name.strip(),
            input_item_id,
            input_name.strip(),
            output_item_id,
            output_name.strip(),
            byproduct_item_id,
            byproduct_name.strip() or None,
            notes.strip() or None,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_step_status(conn: sqlite3.Connection, step_id: int, status: str) -> None:
    conn.execute(
        "UPDATE automation_steps SET status = ? WHERE id = ?",
        (status, step_id),
    )
    conn.commit()


def delete_step(conn: sqlite3.Connection, step_id: int) -> None:
    conn.execute("DELETE FROM automation_steps WHERE id = ?", (step_id,))
    conn.commit()
