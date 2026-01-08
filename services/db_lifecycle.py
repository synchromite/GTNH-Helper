"""Database lifecycle helpers for content and profile DB handling."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from services.db import (
    DEFAULT_DB_PATH,
    connect,
    connect_profile,
    export_db,
    get_setting,
    merge_database,
    set_setting,
)
from ui_constants import SETTINGS_CRAFT_6X6_UNLOCKED, SETTINGS_ENABLED_TIERS, SETTINGS_THEME


@dataclass
class DbLifecycle:
    editor_enabled: bool
    db_path: Path = DEFAULT_DB_PATH
    conn: sqlite3.Connection | None = field(init=False, default=None)
    profile_db_path: Path | None = field(init=False, default=None)
    profile_conn: sqlite3.Connection | None = field(init=False, default=None)
    last_open_error: Exception | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path)
        self.conn = self._open_content_db(self.db_path)
        self.profile_db_path = self._profile_path_for_content(self.db_path)
        self.profile_conn = connect_profile(self.profile_db_path)
        self._migrate_profile_settings_if_needed()

    def close(self) -> None:
        try:
            if self.conn is not None:
                self.conn.commit()
                self.conn.close()
        except Exception:
            pass
        finally:
            self.conn = None

        try:
            if self.profile_conn is not None:
                self.profile_conn.commit()
                self.profile_conn.close()
        except Exception:
            pass
        finally:
            self.profile_conn = None

    def switch_db(self, new_path: Path) -> None:
        self.close()
        self.db_path = Path(new_path)
        self.conn = self._open_content_db(self.db_path)
        self.profile_db_path = self._profile_path_for_content(self.db_path)
        self.profile_conn = connect_profile(self.profile_db_path)
        self._migrate_profile_settings_if_needed()

    def export_content_db(self, target: Path) -> None:
        export_db(self.conn, target)

    def export_profile_db(self, target: Path) -> None:
        export_db(self.profile_conn, target)

    def merge_db(self, source: Path, *, item_conflicts: dict[int, int] | None = None) -> dict[str, int]:
        return merge_database(self.conn, source, item_conflicts=item_conflicts)

    def get_enabled_tiers(self) -> list[str]:
        raw = get_setting(self.profile_conn, SETTINGS_ENABLED_TIERS, "")
        if not raw:
            return ["Stone Age"]
        tiers = [t.strip() for t in raw.split(",") if t.strip()]
        return tiers if tiers else ["Stone Age"]

    def set_enabled_tiers(self, tiers: list[str]) -> None:
        set_setting(self.profile_conn, SETTINGS_ENABLED_TIERS, ",".join(tiers))

    def is_crafting_6x6_unlocked(self) -> bool:
        raw = (get_setting(self.profile_conn, SETTINGS_CRAFT_6X6_UNLOCKED, "0") or "0").strip()
        return raw == "1"

    def set_crafting_6x6_unlocked(self, unlocked: bool) -> None:
        set_setting(self.profile_conn, SETTINGS_CRAFT_6X6_UNLOCKED, "1" if unlocked else "0")

    def get_theme(self) -> str:
        raw = (get_setting(self.profile_conn, SETTINGS_THEME, "dark") or "dark").strip().lower()
        return raw if raw in {"dark", "light"} else "dark"

    def set_theme(self, theme: str) -> None:
        value = theme.strip().lower()
        set_setting(self.profile_conn, SETTINGS_THEME, value)

    def get_machine_availability(self, machine_type: str, tier: str) -> dict[str, int]:
        if self.profile_conn is None:
            return {"owned": 0, "online": 0}
        row = self.profile_conn.execute(
            """
            SELECT owned, online
            FROM machine_availability
            WHERE machine_type = ? AND tier = ?
            """,
            (machine_type, tier),
        ).fetchone()
        if row is None:
            return {"owned": 0, "online": 0}
        return {"owned": int(row["owned"] or 0), "online": int(row["online"] or 0)}

    def _profile_path_for_content(self, content_path: Path) -> Path:
        content_path = Path(content_path)
        base_dir = content_path.parent
        if content_path.name == DEFAULT_DB_PATH.name:
            return base_dir / "profile.db"
        suffix = content_path.suffix or ".db"
        return base_dir / f"{content_path.stem}_profile{suffix}"

    def _migrate_profile_settings_if_needed(self) -> None:
        if self.conn is None or self.profile_conn is None:
            return
        for key, default in (
            (SETTINGS_ENABLED_TIERS, ""),
            (SETTINGS_CRAFT_6X6_UNLOCKED, "0"),
            (SETTINGS_THEME, "dark"),
        ):
            existing = get_setting(self.profile_conn, key, None)
            if existing is not None:
                continue
            legacy_value = get_setting(self.conn, key, None)
            if legacy_value is not None:
                set_setting(self.profile_conn, key, legacy_value)

    def _open_content_db(self, path: Path) -> sqlite3.Connection:
        try:
            conn = connect(path, read_only=(not self.editor_enabled))
        except Exception as exc:
            self.last_open_error = exc
            return connect(":memory:")
        self.last_open_error = None
        return conn
