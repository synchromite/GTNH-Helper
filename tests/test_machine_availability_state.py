import sqlite3

import pytest

from services import db


def test_machine_availability_rejects_online_over_owned():
    conn = db.connect_profile(":memory:")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO machine_availability(machine_type, tier, owned, online) VALUES(?,?,?,?)",
                ("lathe", "MV", 1, 2),
            )
    finally:
        conn.close()


def test_machine_availability_rejects_invalid_transition():
    conn = db.connect_profile(":memory:")
    try:
        conn.execute(
            "INSERT INTO machine_availability(machine_type, tier, owned, online) VALUES(?,?,?,?)",
            ("lathe", "MV", 1, 1),
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE machine_availability SET owned=?, online=? WHERE machine_type=? AND tier=?",
                (0, 1, "lathe", "MV"),
            )
    finally:
        conn.close()
