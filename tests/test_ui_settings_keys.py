from services.db_lifecycle import DbLifecycle
from ui_constants import (
    SETTINGS_CRAFT_6X6_UNLOCKED,
    SETTINGS_ENABLED_TIERS,
    SETTINGS_ACTIVE_STORAGE_ID,
    SETTINGS_MACHINE_SEARCH,
    SETTINGS_MACHINE_SORT_MODE,
    SETTINGS_MACHINE_TIER_FILTER,
    SETTINGS_MACHINE_UNLOCKED_ONLY,
    SETTINGS_TIER_LIST,
    SETTINGS_THEME,
)


def test_ui_settings_keys_are_preserved():
    assert SETTINGS_ENABLED_TIERS == "enabled_tiers"
    assert SETTINGS_CRAFT_6X6_UNLOCKED == "crafting_6x6_unlocked"
    assert SETTINGS_THEME == "theme"
    assert SETTINGS_MACHINE_TIER_FILTER == "machine_tier_filter"
    assert SETTINGS_MACHINE_UNLOCKED_ONLY == "machine_unlocked_only"
    assert SETTINGS_MACHINE_SORT_MODE == "machine_sort_mode"
    assert SETTINGS_MACHINE_SEARCH == "machine_search"
    assert SETTINGS_TIER_LIST == "tier_list"
    assert SETTINGS_ACTIVE_STORAGE_ID == "active_storage_id"


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
        profile_conn.execute(
            "INSERT INTO app_settings(key, value) VALUES (?, ?)",
            (SETTINGS_MACHINE_TIER_FILTER, "LV"),
        )
        profile_conn.execute(
            "INSERT INTO app_settings(key, value) VALUES (?, ?)",
            (SETTINGS_MACHINE_UNLOCKED_ONLY, "0"),
        )
        profile_conn.execute(
            "INSERT INTO app_settings(key, value) VALUES (?, ?)",
            (SETTINGS_MACHINE_SORT_MODE, "Tier (progression)"),
        )
        profile_conn.execute(
            "INSERT INTO app_settings(key, value) VALUES (?, ?)",
            (SETTINGS_MACHINE_SEARCH, "assembler"),
        )
        profile_conn.execute(
            "INSERT INTO app_settings(key, value) VALUES (?, ?)",
            (SETTINGS_TIER_LIST, "Stone Age,LV,HV"),
        )
        profile_conn.commit()

        assert lifecycle.get_enabled_tiers() == ["Stone Age", "LV"]
        assert lifecycle.is_crafting_6x6_unlocked() is True
        assert lifecycle.get_theme() == "light"
        assert lifecycle.get_machine_tier_filter() == "LV"
        assert lifecycle.get_machine_unlocked_only() is False
        assert lifecycle.get_machine_sort_mode() == "Tier (progression)"
        assert lifecycle.get_machine_search() == "assembler"
        assert lifecycle.get_all_tiers() == ["Stone Age", "LV", "HV"]
        lifecycle.set_enabled_tiers(["MV"])
        lifecycle.set_crafting_6x6_unlocked(False)
        lifecycle.set_theme("dark")
        lifecycle.set_machine_tier_filter("All tiers")
        lifecycle.set_machine_unlocked_only(True)
        lifecycle.set_machine_sort_mode("Machine (Z→A)")
        lifecycle.set_machine_search("")
        lifecycle.set_all_tiers(["ULV", "LV"])

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

        row = profile_conn.execute(
            "SELECT value FROM app_settings WHERE key=?",
            (SETTINGS_MACHINE_TIER_FILTER,),
        ).fetchone()
        assert row["value"] == "All tiers"

        row = profile_conn.execute(
            "SELECT value FROM app_settings WHERE key=?",
            (SETTINGS_MACHINE_UNLOCKED_ONLY,),
        ).fetchone()
        assert row["value"] == "1"

        row = profile_conn.execute(
            "SELECT value FROM app_settings WHERE key=?",
            (SETTINGS_MACHINE_SORT_MODE,),
        ).fetchone()
        assert row["value"] == "Machine (Z→A)"

        row = profile_conn.execute(
            "SELECT value FROM app_settings WHERE key=?",
            (SETTINGS_MACHINE_SEARCH,),
        ).fetchone()
        assert row["value"] == ""

        row = profile_conn.execute(
            "SELECT value FROM app_settings WHERE key=?",
            (SETTINGS_TIER_LIST,),
        ).fetchone()
        assert row["value"] == "ULV,LV"

    finally:
        lifecycle.close()


def test_enabled_tiers_default_to_first_configured_tier(tmp_path):
    lifecycle = DbLifecycle(editor_enabled=False, db_path=tmp_path / "content.db")
    try:
        profile_conn = lifecycle.profile_conn
        assert profile_conn is not None

        lifecycle.set_all_tiers(["Primitive", "LV", "MV"])
        profile_conn.execute("DELETE FROM app_settings WHERE key=?", (SETTINGS_ENABLED_TIERS,))
        profile_conn.commit()

        assert lifecycle.get_enabled_tiers() == ["Primitive"]
    finally:
        lifecycle.close()


def test_active_storage_setting_supports_aggregate_mode(tmp_path):
    lifecycle = DbLifecycle(editor_enabled=False, db_path=tmp_path / "content.db")
    try:
        profile_conn = lifecycle.profile_conn
        assert profile_conn is not None

        lifecycle.set_active_storage_id(None)

        row = profile_conn.execute(
            "SELECT value FROM app_settings WHERE key=?",
            (SETTINGS_ACTIVE_STORAGE_ID,),
        ).fetchone()
        assert row["value"] == "aggregate"
        assert lifecycle.get_active_storage_id() is None
    finally:
        lifecycle.close()
