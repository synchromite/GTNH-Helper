import sqlite3

from services import db


def test_settings_round_trip():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.ensure_schema(conn)

    assert db.get_setting(conn, "missing", "default") == "default"

    db.set_setting(conn, "foo", "bar")
    assert db.get_setting(conn, "foo") == "bar"

    db.set_setting(conn, "foo", "baz")
    assert db.get_setting(conn, "foo") == "baz"
