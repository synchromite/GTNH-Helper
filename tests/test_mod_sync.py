import json
import sqlite3

import pytest

from services.db import connect_profile
from services.mod_sync import (
    apply_inventory_snapshot,
    build_inventory_snapshot,
    load_inventory_snapshot,
    write_inventory_snapshot,
)


def _content_conn_with_items() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE)")
    conn.execute("INSERT INTO items(id, key) VALUES(1, 'minecraft:iron_ingot')")
    conn.execute("INSERT INTO items(id, key) VALUES(2, 'water')")
    conn.commit()
    return conn


def test_load_inventory_snapshot_validates_schema(tmp_path) -> None:
    path = tmp_path / "snapshot.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [{"item_key": "minecraft:iron_ingot", "qty_count": 32}],
            }
        ),
        encoding="utf-8",
    )

    snapshot = load_inventory_snapshot(path)
    assert snapshot["schema_version"] == 1
    assert snapshot["entries"][0]["item_key"] == "minecraft:iron_ingot"


def test_load_inventory_snapshot_rejects_bad_payload(tmp_path) -> None:
    path = tmp_path / "snapshot_bad.json"
    path.write_text(json.dumps({"schema_version": 2, "entries": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported snapshot schema_version"):
        load_inventory_snapshot(path)


def test_apply_inventory_snapshot_imports_rows_and_tracks_unknown_keys(tmp_path) -> None:
    profile_conn = connect_profile(tmp_path / "profile.db")
    content_conn = _content_conn_with_items()
    try:
        report = apply_inventory_snapshot(
            profile_conn,
            content_conn,
            {
                "schema_version": 1,
                "entries": [
                    {"item_key": "minecraft:iron_ingot", "qty_count": 64},
                    {"item_key": "water", "qty_liters": 1000},
                    {"item_key": "minecraft:unknown_item", "qty_count": 1},
                ],
            },
        )

        rows = profile_conn.execute(
            "SELECT item_id, qty_count, qty_liters FROM inventory ORDER BY item_id"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["item_id"] == 1
        assert int(rows[0]["qty_count"]) == 64
        assert rows[1]["item_id"] == 2
        assert int(rows[1]["qty_liters"]) == 1000

        assert report.imported_rows == 2
        assert report.unknown_item_keys == ["minecraft:unknown_item"]
    finally:
        content_conn.close()
        profile_conn.close()


def test_build_inventory_snapshot_exports_profile_inventory(tmp_path) -> None:
    profile_conn = connect_profile(tmp_path / "profile.db")
    content_conn = _content_conn_with_items()
    try:
        profile_conn.execute(
            "INSERT INTO inventory(item_id, qty_count, qty_liters) VALUES(?, ?, ?)",
            (1, 12, None),
        )
        profile_conn.execute(
            "INSERT INTO inventory(item_id, qty_count, qty_liters) VALUES(?, ?, ?)",
            (2, None, 2000),
        )
        profile_conn.execute(
            "INSERT INTO inventory(item_id, qty_count, qty_liters) VALUES(?, ?, ?)",
            (999, 3, None),
        )
        profile_conn.commit()

        snapshot = build_inventory_snapshot(profile_conn, content_conn)

        assert snapshot["schema_version"] == 1
        assert snapshot["entries"] == [
            {"item_key": "minecraft:iron_ingot", "qty_count": 12},
            {"item_key": "water", "qty_liters": 2000},
        ]
    finally:
        content_conn.close()
        profile_conn.close()


def test_write_inventory_snapshot_writes_json_file(tmp_path) -> None:
    profile_conn = connect_profile(tmp_path / "profile.db")
    content_conn = _content_conn_with_items()
    try:
        profile_conn.execute(
            "INSERT INTO inventory(item_id, qty_count, qty_liters) VALUES(?, ?, ?)",
            (1, 7, None),
        )
        profile_conn.commit()

        out_path = tmp_path / "out" / "snapshot.json"
        write_inventory_snapshot(out_path, profile_conn, content_conn)

        loaded = json.loads(out_path.read_text(encoding="utf-8"))
        assert loaded["entries"] == [{"item_key": "minecraft:iron_ingot", "qty_count": 7}]
    finally:
        content_conn.close()
        profile_conn.close()
