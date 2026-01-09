from __future__ import annotations

import sqlite3


def fetch_materials(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, name, attributes FROM materials ORDER BY name COLLATE NOCASE ASC"
    ).fetchall()


def add_material(conn: sqlite3.Connection, name: str, attributes: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO materials(name, attributes) VALUES(?, ?)",
        (name, attributes),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_material(conn: sqlite3.Connection, material_id: int, name: str, attributes: str | None = None) -> None:
    conn.execute(
        "UPDATE materials SET name=?, attributes=? WHERE id=?",
        (name, attributes, material_id),
    )
    conn.commit()


def delete_material(conn: sqlite3.Connection, material_id: int) -> None:
    conn.execute("DELETE FROM materials WHERE id=?", (material_id,))
    conn.commit()
