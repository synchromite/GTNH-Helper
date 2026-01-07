#!/usr/bin/env python3
import shutil
import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path("gtnh.db")
ALL_TIERS = [
    "Stone Age",
    "Steam Age",
    "ULV",
    "LV",
    "MV",
    "HV",
    "EV",
    "IV",
    "LuV",
    "ZPM",
    "UV",
    "UHV",
    "UEV",
    "UIV",
    "UMV",
    "UXV",
    "OpV",
    "MAX",
]


def connect_profile(db_path: Path | str) -> sqlite3.Connection:
    """Connect to a per-user profile DB.

    The profile DB stores player-specific settings (enabled tiers, unlocks, etc.)
    and MUST remain writable in client mode.
    """
    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory (
            item_id INTEGER PRIMARY KEY,
            qty_count REAL,
            qty_liters REAL
        )
        """
    )
    conn.commit()
    return conn


def connect(db_path: Path | str = DEFAULT_DB_PATH, *, read_only: bool = False) -> sqlite3.Connection:
    """Connect to a GTNH Recipe *content* DB.

    In client mode, pass read_only=True to prevent content edits.
    NOTE: When read_only=True, schema migrations are NOT performed.
    """
    db_path = Path(db_path)
    if read_only:
        # Open as read-only (fails if the file doesn't exist).
        uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if not read_only:
        ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    # Item kinds (Ore, Dust, Ingot, Plate, etc.) are a user-editable taxonomy.
    # NOTE: The existing `items.kind` column is reserved for the high-level
    # type (item vs fluid). The more detailed classification lives in
    # `items.item_kind_id`.

    conn.execute(
        """
    CREATE TABLE IF NOT EXISTS item_kinds (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        sort_order INTEGER NOT NULL DEFAULT 0,
        is_builtin INTEGER NOT NULL DEFAULT 0
    )
    """
    )

    conn.execute(
        """
    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL UNIQUE,
        display_name TEXT,
        kind TEXT NOT NULL CHECK(kind IN ('item','fluid')),
        is_base INTEGER NOT NULL DEFAULT 0
    )
    """
    )

    # ---- Lightweight migrations (keep existing DBs working) ----
    def _has_col(table: str, col: str) -> bool:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r["name"] == col for r in rows)

    # Machine tagging for items (so recipes can pick from known machines)
    if not _has_col("items", "is_machine"):
        conn.execute("ALTER TABLE items ADD COLUMN is_machine INTEGER NOT NULL DEFAULT 0")
    if not _has_col("items", "machine_tier"):
        conn.execute("ALTER TABLE items ADD COLUMN machine_tier TEXT")
    if not _has_col("items", "machine_output_slots"):
        # Output slots (how many distinct output stacks a machine can emit per run).
        # Common early machines have 1; higher tiers may have more.
        conn.execute("ALTER TABLE items ADD COLUMN machine_output_slots INTEGER")

    if not _has_col("items", "machine_input_slots"):
        # Input slots (how many distinct input stacks a machine can accept per run).
        conn.execute("ALTER TABLE items ADD COLUMN machine_input_slots INTEGER")

    if not _has_col("items", "machine_storage_slots"):
        # Extra storage slots beyond input/output.
        conn.execute("ALTER TABLE items ADD COLUMN machine_storage_slots INTEGER")

    if not _has_col("items", "machine_power_slots"):
        # Dedicated power/battery slots.
        conn.execute("ALTER TABLE items ADD COLUMN machine_power_slots INTEGER")

    if not _has_col("items", "machine_circuit_slots"):
        # Ghost/programmable circuit slots.
        conn.execute("ALTER TABLE items ADD COLUMN machine_circuit_slots INTEGER")

    if not _has_col("items", "machine_input_tanks"):
        conn.execute("ALTER TABLE items ADD COLUMN machine_input_tanks INTEGER")

    if not _has_col("items", "machine_input_tank_capacity_l"):
        conn.execute("ALTER TABLE items ADD COLUMN machine_input_tank_capacity_l INTEGER")

    if not _has_col("items", "machine_output_tanks"):
        conn.execute("ALTER TABLE items ADD COLUMN machine_output_tanks INTEGER")

    if not _has_col("items", "machine_output_tank_capacity_l"):
        conn.execute("ALTER TABLE items ADD COLUMN machine_output_tank_capacity_l INTEGER")

    # Detailed item classification (user-editable list of kinds)
    if not _has_col("items", "item_kind_id"):
        conn.execute("ALTER TABLE items ADD COLUMN item_kind_id INTEGER")

    # Per-machine IO slot typing (each machine slot can accept item or fluid)
    conn.execute(
        """
    CREATE TABLE IF NOT EXISTS machine_io_slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        machine_item_id INTEGER NOT NULL,
        direction TEXT NOT NULL CHECK(direction IN ('in','out')),
        slot_index INTEGER NOT NULL,
        content_kind TEXT NOT NULL CHECK(content_kind IN ('item','fluid')),
        label TEXT,
        UNIQUE(machine_item_id, direction, slot_index),
        FOREIGN KEY(machine_item_id) REFERENCES items(id) ON DELETE CASCADE
    )
    """
    )
    if not _has_col("machine_io_slots", "label"):
        conn.execute("ALTER TABLE machine_io_slots ADD COLUMN label TEXT")

    # Seed defaults for item_kinds (only if the table is empty)
    existing = conn.execute("SELECT COUNT(1) AS c FROM item_kinds").fetchone()["c"]
    if int(existing or 0) == 0:
        defaults = [
            # rough GTNH mental buckets
            ("Ore", 10),
            ("Crushed Ore", 20),
            ("Purified Ore", 30),
            ("Dust", 40),
            ("Tiny Dust", 41),
            ("Small Dust", 42),
            ("Ingot", 50),
            ("Nugget", 51),
            ("Plate", 60),
            ("Rod", 61),
            ("Bolt", 62),
            ("Screw", 63),
            ("Gear", 64),
            ("Wire", 65),
            ("Cable", 66),
            ("Circuit", 70),
            ("Component", 80),
            ("Machine", 90),
            ("Tool", 100),
            ("Other", 1000),
        ]
        conn.executemany(
            "INSERT INTO item_kinds(name, sort_order, is_builtin) VALUES(?,?,1)",
            defaults,
        )

    # Keep machine tagging consistent between the legacy columns and Item Kind.
    # Item Kind = 'Machine' is now the primary way to mark machines in the UI.
    # We keep the legacy columns for compatibility (existing DBs, imports, etc.).
    mk = conn.execute("SELECT id FROM item_kinds WHERE LOWER(name)=LOWER('Machine')").fetchone()
    if mk:
        machine_kind_id = mk["id"]
        if _has_col("items", "is_machine"):
            # If Item Kind says Machine, ensure legacy flag is set.
            conn.execute(
                "UPDATE items SET is_machine=1 WHERE kind='item' AND item_kind_id=?",
                (machine_kind_id,),
            )
            # If legacy flag says machine, backfill Item Kind if missing.
            conn.execute(
                "UPDATE items SET item_kind_id=? WHERE kind='item' AND is_machine=1 AND item_kind_id IS NULL",
                (machine_kind_id,),
            )


    # Backfill sensible defaults for newly-added slot count columns
    if _has_col("items", "machine_input_slots"):
        conn.execute(
            "UPDATE items SET machine_input_slots=1 "
            "WHERE kind='item' AND (machine_input_slots IS NULL OR machine_input_slots<=0) "
            "AND (is_machine=1 OR item_kind_id IN (SELECT id FROM item_kinds WHERE LOWER(name)=LOWER('Machine')))"
        )
    if _has_col("items", "machine_output_slots"):
        conn.execute(
            "UPDATE items SET machine_output_slots=1 "
            "WHERE kind='item' AND (machine_output_slots IS NULL OR machine_output_slots<=0) "
            "AND (is_machine=1 OR item_kind_id IN (SELECT id FROM item_kinds WHERE LOWER(name)=LOWER('Machine')))"
        )
    conn.execute(
        """
    CREATE TABLE IF NOT EXISTS recipes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,

        -- Recipe "method" keeps things flexible:
        --  - machine: uses the Machine field (string for now)
        --  - crafting: uses grid_size (+ optional station_item_id)
        method TEXT NOT NULL DEFAULT 'machine',

        -- Machine recipes
        machine TEXT,
        machine_item_id INTEGER,

        -- Crafting recipes
        grid_size TEXT,
        station_item_id INTEGER,

        circuit INTEGER,
        tier TEXT,
        duration_ticks INTEGER,
        eu_per_tick INTEGER,
        notes TEXT
    )
    """
    )

    # ---- Lightweight migrations for recipes ----
    if not _has_col("recipes", "method"):
        conn.execute("ALTER TABLE recipes ADD COLUMN method TEXT NOT NULL DEFAULT 'machine'")
    if not _has_col("recipes", "grid_size"):
        conn.execute("ALTER TABLE recipes ADD COLUMN grid_size TEXT")
    if not _has_col("recipes", "station_item_id"):
        conn.execute("ALTER TABLE recipes ADD COLUMN station_item_id INTEGER")
    if not _has_col("recipes", "machine_item_id"):
        conn.execute("ALTER TABLE recipes ADD COLUMN machine_item_id INTEGER")

    conn.execute(
        """
    CREATE TABLE IF NOT EXISTS recipe_lines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recipe_id INTEGER NOT NULL,
        direction TEXT NOT NULL CHECK(direction IN ('in','out')),
        item_id INTEGER NOT NULL,
        qty_count REAL,
        qty_liters REAL,
        chance_percent REAL,
        output_slot_index INTEGER,
        FOREIGN KEY(recipe_id) REFERENCES recipes(id) ON DELETE CASCADE,
        FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE RESTRICT
    )
    """
    )

    if not _has_col("recipe_lines", "chance_percent"):
        conn.execute("ALTER TABLE recipe_lines ADD COLUMN chance_percent REAL")
    if not _has_col("recipe_lines", "output_slot_index"):
        conn.execute("ALTER TABLE recipe_lines ADD COLUMN output_slot_index INTEGER")

    def _get_user_version() -> int:
        row = conn.execute("PRAGMA user_version").fetchone()
        return int(row[0]) if row else 0

    user_version = _get_user_version()
    if user_version < 1:
        machine_rows = conn.execute(
            """
            SELECT machine_item_id
            FROM machine_io_slots
            GROUP BY machine_item_id
            HAVING SUM(CASE WHEN slot_index=0 THEN 1 ELSE 0 END)=0
               AND MIN(slot_index) >= 1
            """
        ).fetchall()
        for row in machine_rows:
            conn.execute(
                "UPDATE machine_io_slots SET slot_index=slot_index-1 WHERE machine_item_id=?",
                (row["machine_item_id"],),
            )

        recipe_machine_rows = conn.execute(
            """
            SELECT r.machine_item_id AS machine_item_id
            FROM recipes r
            JOIN recipe_lines rl ON rl.recipe_id = r.id
            WHERE r.machine_item_id IS NOT NULL
              AND rl.direction='out'
              AND rl.output_slot_index IS NOT NULL
            GROUP BY r.machine_item_id
            HAVING SUM(CASE WHEN rl.output_slot_index=0 THEN 1 ELSE 0 END)=0
               AND MIN(rl.output_slot_index) >= 1
            """
        ).fetchall()
        for row in recipe_machine_rows:
            conn.execute(
                """
                UPDATE recipe_lines
                SET output_slot_index=output_slot_index-1
                WHERE recipe_id IN (SELECT id FROM recipes WHERE machine_item_id=?)
                  AND direction='out'
                  AND output_slot_index IS NOT NULL
                """,
                (row["machine_item_id"],),
            )

        conn.execute("PRAGMA user_version=1")

    conn.execute(
        """
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """
    )

    conn.commit()


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()


def export_db(conn: sqlite3.Connection, dest_path: Path | str) -> None:
    """Create a safe copy of the current DB to dest_path.

    Uses SQLite's backup API which is safe even if the DB is in WAL mode.
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dst = sqlite3.connect(str(dest_path))
    try:
        conn.backup(dst)
    finally:
        dst.close()


def merge_db(dest_conn: sqlite3.Connection, src_path: Path | str) -> dict[str, int]:
    """Merge an external DB file into the currently-open DB.

    KISS behavior:
      - Item Kinds are merged by (case-insensitive) name.
      - Items are merged by `key` (unique). Existing items are only "filled in" (no destructive overwrites).
      - Recipes are imported as new entries. Name conflicts get a suffix: " (import 2)", etc.
      - Recipe lines are copied and remapped by item key.

    Returns simple counters for UI display.
    """
    src_path = Path(src_path)
    src = sqlite3.connect(str(src_path))
    src.row_factory = sqlite3.Row
    src.execute("PRAGMA foreign_keys=ON")
    ensure_schema(src)

    stats = {
        "kinds_added": 0,
        "items_added": 0,
        "items_updated": 0,
        "recipes_added": 0,
        "lines_added": 0,
    }

    try:
        # ---- Kind mapping ----
        dest_kind_map: dict[int, int] = {}
        src_kinds = src.execute("SELECT id, name, sort_order FROM item_kinds ORDER BY id").fetchall()
        for k in src_kinds:
            name = (k["name"] or "").strip()
            if not name:
                continue
            row = dest_conn.execute(
                "SELECT id FROM item_kinds WHERE LOWER(name)=LOWER(?)",
                (name,),
            ).fetchone()
            if row:
                dest_kind_map[k["id"]] = row["id"]
                continue
            dest_conn.execute(
                "INSERT INTO item_kinds(name, sort_order, is_builtin) VALUES(?, ?, 0)",
                (name, int(k["sort_order"] or 0)),
            )
            new_id = dest_conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            dest_kind_map[k["id"]] = new_id
            stats["kinds_added"] += 1

        # Grab Machine kind id for backfills
        mk = dest_conn.execute("SELECT id FROM item_kinds WHERE LOWER(name)=LOWER('Machine')").fetchone()
        dest_machine_kind_id = mk["id"] if mk else None

        # ---- Items ----
        src_items = src.execute(
            "SELECT id, key, display_name, kind, is_base, is_machine, machine_tier, machine_input_slots, machine_output_slots, "
            "       machine_storage_slots, machine_power_slots, machine_circuit_slots, machine_input_tanks, "
            "       machine_input_tank_capacity_l, machine_output_tanks, machine_output_tank_capacity_l, item_kind_id "
            "FROM items ORDER BY id"
        ).fetchall()

        item_key_to_dest_id: dict[str, int] = {}
        for it in src_items:
            key = (it["key"] or "").strip()
            if not key:
                continue

            dest_row = dest_conn.execute(
                "SELECT id, display_name, kind, is_base, is_machine, machine_tier, machine_input_slots, machine_output_slots, "
                "       machine_storage_slots, machine_power_slots, machine_circuit_slots, machine_input_tanks, "
                "       machine_input_tank_capacity_l, machine_output_tanks, machine_output_tank_capacity_l, item_kind_id "
                "FROM items WHERE key=?",
                (key,),
            ).fetchone()

            mapped_kind_id = None
            if it["item_kind_id"] is not None:
                mapped_kind_id = dest_kind_map.get(int(it["item_kind_id"]), None)

            if not dest_row:
                insert_sql = (
                    "INSERT INTO items(key, display_name, kind, is_base, is_machine, machine_tier, "
                    "machine_input_slots, machine_output_slots, machine_storage_slots, machine_power_slots, "
                    "machine_circuit_slots, machine_input_tanks, machine_input_tank_capacity_l, "
                    "machine_output_tanks, machine_output_tank_capacity_l, item_kind_id) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                )
                insert_values = (
                    key,
                    it["display_name"],
                    it["kind"],
                    int(it["is_base"] or 0),
                    int(it["is_machine"] or 0),
                    it["machine_tier"],
                    it["machine_input_slots"],
                    it["machine_output_slots"],
                    it["machine_storage_slots"],
                    it["machine_power_slots"],
                    it["machine_circuit_slots"],
                    it["machine_input_tanks"],
                    it["machine_input_tank_capacity_l"],
                    it["machine_output_tanks"],
                    it["machine_output_tank_capacity_l"],
                    mapped_kind_id,
                )
                dest_conn.execute(insert_sql, insert_values)
                new_id = dest_conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
                item_key_to_dest_id[key] = new_id
                stats["items_added"] += 1
                continue

            # Fill-in updates only (don't overwrite user edits)
            updates: dict[str, Any] = {}
            if (dest_row["display_name"] is None or str(dest_row["display_name"]).strip() == "") and (it["display_name"] or "").strip():
                updates["display_name"] = it["display_name"]
            if (dest_row["item_kind_id"] is None) and mapped_kind_id is not None:
                updates["item_kind_id"] = mapped_kind_id
            if int(it["is_base"] or 0) and not int(dest_row["is_base"] or 0):
                updates["is_base"] = 1

            # Machine logic: OR the flags, and backfill item_kind_id to Machine when possible.
            src_is_machine = int(it["is_machine"] or 0)
            if src_is_machine and not int(dest_row["is_machine"] or 0):
                updates["is_machine"] = 1
            if src_is_machine and dest_machine_kind_id is not None and dest_row["item_kind_id"] is None:
                updates["item_kind_id"] = dest_machine_kind_id
            if (dest_row["machine_tier"] is None or str(dest_row["machine_tier"] or "").strip() == "") and (it["machine_tier"] or "").strip():
                updates["machine_tier"] = it["machine_tier"]

            if (dest_row["machine_input_slots"] is None or int(dest_row["machine_input_slots"] or 0) == 0) and it["machine_input_slots"] is not None:
                try:
                    mis = int(it["machine_input_slots"])
                except Exception:
                    mis = None
                if mis is not None and mis > 0:
                    updates["machine_input_slots"] = mis
            if (dest_row["machine_output_slots"] is None or int(dest_row["machine_output_slots"] or 0) == 0) and it["machine_output_slots"] is not None:
                try:
                    mos = int(it["machine_output_slots"])
                except Exception:
                    mos = None
                if mos is not None and mos > 0:
                    updates["machine_output_slots"] = mos
            if (dest_row["machine_storage_slots"] is None or int(dest_row["machine_storage_slots"] or 0) == 0) and it["machine_storage_slots"] is not None:
                try:
                    mss = int(it["machine_storage_slots"])
                except Exception:
                    mss = None
                if mss is not None and mss > 0:
                    updates["machine_storage_slots"] = mss
            if (dest_row["machine_power_slots"] is None or int(dest_row["machine_power_slots"] or 0) == 0) and it["machine_power_slots"] is not None:
                try:
                    mps = int(it["machine_power_slots"])
                except Exception:
                    mps = None
                if mps is not None and mps > 0:
                    updates["machine_power_slots"] = mps
            if (dest_row["machine_circuit_slots"] is None or int(dest_row["machine_circuit_slots"] or 0) == 0) and it["machine_circuit_slots"] is not None:
                try:
                    mcs = int(it["machine_circuit_slots"])
                except Exception:
                    mcs = None
                if mcs is not None and mcs > 0:
                    updates["machine_circuit_slots"] = mcs
            if (dest_row["machine_input_tanks"] is None or int(dest_row["machine_input_tanks"] or 0) == 0) and it["machine_input_tanks"] is not None:
                try:
                    mit = int(it["machine_input_tanks"])
                except Exception:
                    mit = None
                if mit is not None and mit > 0:
                    updates["machine_input_tanks"] = mit
            if (dest_row["machine_input_tank_capacity_l"] is None or int(dest_row["machine_input_tank_capacity_l"] or 0) == 0) and it["machine_input_tank_capacity_l"] is not None:
                try:
                    mic = int(it["machine_input_tank_capacity_l"])
                except Exception:
                    mic = None
                if mic is not None and mic > 0:
                    updates["machine_input_tank_capacity_l"] = mic
            if (dest_row["machine_output_tanks"] is None or int(dest_row["machine_output_tanks"] or 0) == 0) and it["machine_output_tanks"] is not None:
                try:
                    mot = int(it["machine_output_tanks"])
                except Exception:
                    mot = None
                if mot is not None and mot > 0:
                    updates["machine_output_tanks"] = mot
            if (dest_row["machine_output_tank_capacity_l"] is None or int(dest_row["machine_output_tank_capacity_l"] or 0) == 0) and it["machine_output_tank_capacity_l"] is not None:
                try:
                    moc = int(it["machine_output_tank_capacity_l"])
                except Exception:
                    moc = None
                if moc is not None and moc > 0:
                    updates["machine_output_tank_capacity_l"] = moc

            if updates:
                sets = ", ".join([f"{k}=?" for k in updates.keys()])
                params = list(updates.values()) + [dest_row["id"]]
                dest_conn.execute(f"UPDATE items SET {sets} WHERE id=?", tuple(params))
                stats["items_updated"] += 1

            item_key_to_dest_id[key] = dest_row["id"]

        # ---- Recipes ----
        src_recipes = src.execute(
            "SELECT id, name, method, machine, machine_item_id, grid_size, station_item_id, circuit, tier, duration_ticks, eu_per_tick, notes "
            "FROM recipes ORDER BY id"
        ).fetchall()

        recipe_id_map: dict[int, int] = {}
        # prefetch existing names for quick uniqueness checks
        existing_names = set(r["name"] for r in dest_conn.execute("SELECT name FROM recipes").fetchall())

        def _unique_recipe_name(base: str) -> str:
            base = (base or "").strip() or "Recipe"
            if base not in existing_names:
                existing_names.add(base)
                return base
            n = 2
            while True:
                cand = f"{base} (import {n})"
                if cand not in existing_names:
                    existing_names.add(cand)
                    return cand
                n += 1

        # helper: map src station_item_id / machine_item_id -> dest id
        src_item_id_to_key = {r["id"]: r["key"] for r in src.execute("SELECT id, key FROM items").fetchall()}

        for r in src_recipes:
            new_name = _unique_recipe_name(r["name"])
            station_dest_id = None
            if r["station_item_id"] is not None:
                k = src_item_id_to_key.get(int(r["station_item_id"]))
                if k:
                    station_dest_id = item_key_to_dest_id.get(k)

            machine_dest_id = None
            if r["machine_item_id"] is not None:
                k = src_item_id_to_key.get(int(r["machine_item_id"]))
                if k:
                    machine_dest_id = item_key_to_dest_id.get(k)

            dest_conn.execute(
                "INSERT INTO recipes(name, method, machine, machine_item_id, grid_size, station_item_id, circuit, tier, duration_ticks, eu_per_tick, notes) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    new_name,
                    r["method"],
                    r["machine"],
                    machine_dest_id,
                    r["grid_size"],
                    station_dest_id,
                    r["circuit"],
                    r["tier"],
                    r["duration_ticks"],
                    r["eu_per_tick"],
                    r["notes"],
                ),
            )
            new_id = dest_conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            recipe_id_map[int(r["id"])] = int(new_id)
            stats["recipes_added"] += 1

        # ---- Recipe lines ----
        src_lines = src.execute(
            "SELECT recipe_id, direction, item_id, qty_count, qty_liters, chance_percent, output_slot_index "
            "FROM recipe_lines ORDER BY id"
        ).fetchall()

        for ln in src_lines:
            new_recipe_id = recipe_id_map.get(int(ln["recipe_id"]))
            if not new_recipe_id:
                continue
            src_item_key = src_item_id_to_key.get(int(ln["item_id"]))
            if not src_item_key:
                continue
            new_item_id = item_key_to_dest_id.get(src_item_key)
            if not new_item_id:
                continue

            dest_conn.execute(
                "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_count, qty_liters, chance_percent, output_slot_index) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    new_recipe_id,
                    ln["direction"],
                    new_item_id,
                    ln["qty_count"],
                    ln["qty_liters"],
                    ln["chance_percent"],
                    ln["output_slot_index"],
                ),
            )
            stats["lines_added"] += 1

        dest_conn.commit()
        return stats

    finally:
        src.close()



def merge_database(dest_conn: sqlite3.Connection, src_path: Path | str) -> dict[str, int]:
    """Alias for merge_db (kept for readability in UI layer)."""
    return merge_db(dest_conn, src_path)


def copy_file(src_path: Path | str, dst_path: Path | str) -> None:
    """Simple file copy helper (used rarely; prefer export_db for SQLite safety)."""
    shutil.copy2(str(src_path), str(dst_path))
