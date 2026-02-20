import sqlite3

from services.db import ensure_schema
from services.machines import replace_machine_metadata


def _setup_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


def test_replace_machine_metadata_creates_machine_items() -> None:
    conn = _setup_conn()

    replace_machine_metadata(
        conn,
        [
            ("Cutting Machine", "LV", "Basic Cutting Machine", 1, 1, 0, 0, 0, 0, 0, 0, 0, 0),
            ("Cutting Machine", "MV", "Advanced Cutting Machine", 2, 1, 0, 0, 0, 0, 0, 0, 0, 0),
        ],
    )

    rows = conn.execute(
        """
        SELECT kind, machine_type, machine_tier, display_name, is_machine
        FROM items
        WHERE kind='machine'
        ORDER BY machine_tier
        """
    ).fetchall()

    assert len(rows) == 2
    assert [row["display_name"] for row in rows] == [
        "Basic Cutting Machine",
        "Advanced Cutting Machine",
    ]
    assert all(row["machine_type"] == "Cutting Machine" for row in rows)
    assert [row["machine_tier"] for row in rows] == ["LV", "MV"]
    assert all(int(row["is_machine"] or 0) == 1 for row in rows)


def test_replace_machine_metadata_updates_existing_machine_item_name() -> None:
    conn = _setup_conn()
    conn.execute(
        """
        INSERT INTO items(key, display_name, kind, is_base, is_machine, machine_tier, machine_type, is_multiblock)
        VALUES('machine_cutting_machine_lv', 'Old Name', 'machine', 0, 1, 'LV', 'Cutting Machine', 0)
        """
    )
    conn.commit()

    replace_machine_metadata(
        conn,
        [
            ("Cutting Machine", "LV", "Basic Cutting Machine", 1, 1, 0, 0, 0, 0, 0, 0, 0, 0),
        ],
    )

    rows = conn.execute(
        "SELECT id, display_name FROM items WHERE kind='machine' AND machine_type='Cutting Machine' AND machine_tier='LV'"
    ).fetchall()

    assert len(rows) == 1
    assert rows[0]["display_name"] == "Basic Cutting Machine"


def test_replace_machine_metadata_deletes_machine_items_not_in_metadata() -> None:
    conn = _setup_conn()
    conn.execute(
        """
        INSERT INTO items(key, display_name, kind, is_base, is_machine, machine_tier, machine_type, is_multiblock)
        VALUES('machine_cutting_machine_lv', 'Basic Cutting Machine', 'machine', 0, 1, 'LV', 'Cutting Machine', 0)
        """
    )
    conn.execute(
        """
        INSERT INTO items(key, display_name, kind, is_base, is_machine, machine_tier, machine_type, is_multiblock)
        VALUES('machine_macerator_mv', 'Advanced Macerator', 'machine', 0, 1, 'MV', 'Macerator', 0)
        """
    )
    conn.commit()

    replace_machine_metadata(
        conn,
        [
            ("Cutting Machine", "LV", "Basic Cutting Machine", 1, 1, 0, 0, 0, 0, 0, 0, 0, 0),
        ],
    )

    rows = conn.execute(
        "SELECT machine_type, machine_tier, display_name FROM items WHERE kind='machine' ORDER BY id"
    ).fetchall()

    assert len(rows) == 1
    assert rows[0]["machine_type"] == "Cutting Machine"
    assert rows[0]["machine_tier"] == "LV"
    assert rows[0]["display_name"] == "Basic Cutting Machine"


def test_replace_machine_metadata_works_inside_existing_transaction() -> None:
    conn = _setup_conn()

    with conn:
        replace_machine_metadata(
            conn,
            [
                ("Cutting Machine", "LV", "Basic Cutting Machine", 1, 1, 0, 0, 0, 0, 0, 0, 0, 0),
            ],
        )

    row = conn.execute(
        "SELECT display_name FROM items WHERE kind='machine' AND machine_type='Cutting Machine' AND machine_tier='LV'"
    ).fetchone()

    assert row is not None
    assert row["display_name"] == "Basic Cutting Machine"
