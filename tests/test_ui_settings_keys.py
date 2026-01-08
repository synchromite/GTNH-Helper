from services.db_lifecycle import DbLifecycle
from ui_constants import SETTINGS_CRAFT_6X6_UNLOCKED, SETTINGS_ENABLED_TIERS, SETTINGS_THEME


def test_ui_settings_keys_are_preserved():
    assert SETTINGS_ENABLED_TIERS == "enabled_tiers"
    assert SETTINGS_CRAFT_6X6_UNLOCKED == "crafting_6x6_unlocked"
    assert SETTINGS_THEME == "theme"


def test_qt_ui_uses_settings_keys(tmp_path):
    lifecycle = DbLifecycle(editor_enabled=False, db_path=tmp_path / "content.db")
    try:
        profile_conn = lifecycle.profile_conn
        assert profile_conn is not None

        profile_conn.execute("DELETE FROM app_settings")
        profile_conn.execute(
            "INSERT INTO app_settings(key, value) VALUES (?, ?)",
            (SETTINGS_ENABLED_TIERS, "Stone Age,LV"),
        )
        profile_conn.execute(
            "INSERT INTO app_settings(key, value) VALUES (?, ?)",
            (SETTINGS_CRAFT_6X6_UNLOCKED, "1"),
        )
        profile_conn.execute(
            "INSERT INTO app_settings(key, value) VALUES (?, ?)",
            (SETTINGS_THEME, "light"),
        )
        profile_conn.commit()

        assert lifecycle.get_enabled_tiers() == ["Stone Age", "LV"]
        assert lifecycle.is_crafting_6x6_unlocked() is True
        assert lifecycle.get_theme() == "light"

        lifecycle.set_enabled_tiers(["MV"])
        lifecycle.set_crafting_6x6_unlocked(False)
        lifecycle.set_theme("dark")

        row = profile_conn.execute(
            "SELECT value FROM app_settings WHERE key=?",
            (SETTINGS_ENABLED_TIERS,),
        ).fetchone()
        assert row["value"] == "MV"

        row = profile_conn.execute(
            "SELECT value FROM app_settings WHERE key=?",
            (SETTINGS_CRAFT_6X6_UNLOCKED,),
        ).fetchone()
        assert row["value"] == "0"

        row = profile_conn.execute(
            "SELECT value FROM app_settings WHERE key=?",
            (SETTINGS_THEME,),
        ).fetchone()
        assert row["value"] == "dark"
    finally:
        lifecycle.close()
