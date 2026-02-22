import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

import ui_main


class _DummyStatusBar:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, message: str) -> None:
        self.messages.append(message)


class _DummyDb:
    def __init__(self, *, fail_open: bool = False) -> None:
        self.db_path = Path("missing.db")
        self.profile_db_path = Path("missing_profile.db")
        self.conn = object()
        self.profile_conn = object()
        self.last_open_error = None
        self.switch_calls: list[Path] = []
        self._fail_open = fail_open

    def switch_db(self, new_path: Path) -> None:
        self.switch_calls.append(Path(new_path))
        self.db_path = Path(new_path)
        self.profile_db_path = self.db_path.with_name(f"{self.db_path.stem}_profile.db")
        self.conn = object()
        self.profile_conn = object()
        self.last_open_error = OSError("db file missing") if self._fail_open else None



def _make_app(dummy_db: _DummyDb) -> ui_main.App:
    app = ui_main.App.__new__(ui_main.App)
    app.db = dummy_db
    app.db_path = dummy_db.db_path
    app.conn = dummy_db.conn
    app.profile_conn = dummy_db.profile_conn
    app.status_bar = _DummyStatusBar()
    app._db_recovery_notified_for = None
    app.tab_widgets = {}
    app.items = []
    return app


def test_refresh_items_closed_connection_notifies_and_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _make_app(_DummyDb())

    calls = {"count": 0}

    def fake_fetch_items(_conn):
        calls["count"] += 1
        if calls["count"] == 1:
            raise sqlite3.ProgrammingError("Cannot operate on a closed database.")
        return []

    infos: list[tuple[str, str]] = []
    monkeypatch.setattr(ui_main, "fetch_items", fake_fetch_items)
    monkeypatch.setattr(
        ui_main.QtWidgets.QMessageBox,
        "information",
        lambda _parent, title, message: infos.append((title, message)),
    )

    app.refresh_items()

    assert calls["count"] == 2
    assert app.db.switch_calls == [Path("missing.db")]
    assert len(infos) == 1
    assert "connection was closed unexpectedly" in infos[0][1].lower()


def test_recover_closed_connection_open_failure_warns_once(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _make_app(_DummyDb(fail_open=True))

    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        ui_main.QtWidgets.QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    app._recover_closed_connection("items refresh")
    app._recover_closed_connection("items refresh")

    assert app.db.switch_calls == [Path("missing.db"), Path("missing.db")]
    assert len(warnings) == 1
    assert "tried to re-open" in warnings[0][1].lower()


def test_switch_db_failure_keeps_current_handles(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _make_app(_DummyDb())

    class _FailingDb(_DummyDb):
        def switch_db(self, new_path: Path) -> None:  # noqa: ARG002
            raise OSError("boom")

    app.db = _FailingDb()
    original_conn = app.conn = object()
    original_profile_conn = app.profile_conn = object()

    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        ui_main.QtWidgets.QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    app._switch_db(Path("other.db"))

    assert app.conn is original_conn
    assert app.profile_conn is original_profile_conn
    assert len(warnings) == 1
    assert "current database remains open" in warnings[0][1].lower()
