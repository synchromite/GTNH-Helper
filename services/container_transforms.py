from __future__ import annotations

import sqlite3


VALID_TRANSFORM_KINDS = {"bidirectional", "empty_only", "fill_only"}


def fetch_container_transforms(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            t.id,
            t.priority,
            t.container_item_id,
            c.display_name AS container_name,
            t.empty_item_id,
            e.display_name AS empty_name,
            t.content_item_id,
            i.display_name AS content_name,
            i.kind AS content_kind,
            t.content_qty,
            t.transform_kind
        FROM item_container_transforms t
        JOIN items c ON c.id=t.container_item_id
        JOIN items e ON e.id=t.empty_item_id
        JOIN items i ON i.id=t.content_item_id
        ORDER BY t.priority ASC, t.id ASC
        """
    ).fetchall()


def replace_container_transforms(conn: sqlite3.Connection, rows: list[dict]) -> None:
    with conn:
        conn.execute("DELETE FROM item_container_transforms")
        conn.executemany(
            """
            INSERT INTO item_container_transforms(
                priority,
                container_item_id,
                empty_item_id,
                content_item_id,
                content_qty,
                transform_kind
            ) VALUES(?,?,?,?,?,?)
            """,
            [
                (
                    int(row.get("priority", 0)),
                    int(row["container_item_id"]),
                    int(row["empty_item_id"]),
                    int(row["content_item_id"]),
                    int(row["content_qty"]),
                    str(row["transform_kind"]),
                )
                for row in rows
            ],
        )

