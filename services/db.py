#!/usr/bin/env python3
import shutil
import sqlite3
from difflib import SequenceMatcher
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

def set_all_tiers(tiers: list[str]) -> None:
    ALL_TIERS.clear()
    ALL_TIERS.extend(tiers)


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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS machine_metadata (
            machine_type TEXT NOT NULL,
            tier TEXT NOT NULL,
            input_slots INTEGER,
            output_slots INTEGER,
            byproduct_slots INTEGER,
            storage_slots INTEGER,
            power_slots INTEGER,
            circuit_slots INTEGER,
            input_tanks INTEGER,
            input_tank_capacity_l INTEGER,
            output_tanks INTEGER,
            output_tank_capacity_l INTEGER,
            PRIMARY KEY (machine_type, tier)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS machine_availability (
            machine_type TEXT NOT NULL,
            tier TEXT NOT NULL,
            owned INTEGER NOT NULL DEFAULT 0 CHECK(owned >= 0),
            online INTEGER NOT NULL DEFAULT 0 CHECK(online >= 0 AND online <= owned),
            PRIMARY KEY (machine_type, tier)
        )
        """
    )
    conn.commit()
    return conn


def connect(db_path: Path | str = DEFAULT_DB_PATH, *, read_only: bool = False) -> sqlite3.Connection:
    """Connect to a GTNH Recipe *content* DB.

    In client mode, pass read_only=True to prevent content edits.
    Schema migrations are still applied so older DB files remain readable.
    """
    db_path = Path(db_path)
    if read_only:
        # Open read/write to allow schema migrations, but require the DB file
        # to exist (same failure behavior as strict read-only mode).
        uri = f"file:{db_path.as_posix()}?mode=rw"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_schema(conn)
    if read_only:
        # Enforce read-only behavior for the remainder of this connection.
        conn.execute("PRAGMA query_only=ON")
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
        is_builtin INTEGER NOT NULL DEFAULT 0,
        applies_to TEXT NOT NULL DEFAULT 'item' CHECK(applies_to IN ('item','fluid'))
    )
    """
    )

    conn.execute(
        """
    CREATE TABLE IF NOT EXISTS materials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        attributes TEXT
    )
    """
    )

    conn.execute(
        """
    CREATE TABLE IF NOT EXISTS machine_metadata (
        machine_type TEXT NOT NULL,
        tier TEXT NOT NULL,
        input_slots INTEGER,
        output_slots INTEGER,
        byproduct_slots INTEGER,
        storage_slots INTEGER,
        power_slots INTEGER,
        circuit_slots INTEGER,
        input_tanks INTEGER,
        input_tank_capacity_l INTEGER,
        output_tanks INTEGER,
        output_tank_capacity_l INTEGER,
        PRIMARY KEY (machine_type, tier)
    )
    """
    )

    conn.execute(
        """
    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL UNIQUE,
        display_name TEXT,
        kind TEXT NOT NULL CHECK(kind IN ('item','fluid','gas','machine','crafting_grid')),
        is_base INTEGER NOT NULL DEFAULT 0,
        material_id INTEGER,
        FOREIGN KEY(material_id) REFERENCES materials(id) ON DELETE SET NULL
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
    if not _has_col("items", "machine_type"):
        conn.execute("ALTER TABLE items ADD COLUMN machine_type TEXT")
    if not _has_col("items", "is_multiblock"):
        conn.execute("ALTER TABLE items ADD COLUMN is_multiblock INTEGER NOT NULL DEFAULT 0")
    # Drop legacy machine stats columns if they exist (migrated to machine_metadata)
    for col in [
        "machine_input_slots",
        "machine_output_slots",
        "machine_storage_slots",
        "machine_power_slots",
        "machine_circuit_slots",
        "machine_input_tanks",
        "machine_input_tank_capacity_l",
        "machine_output_tanks",
        "machine_output_tank_capacity_l",
    ]:
        if _has_col("items", col):
            conn.execute(f"ALTER TABLE items DROP COLUMN {col}")

    if not _has_col("items", "content_fluid_id"):
        conn.execute("ALTER TABLE items ADD COLUMN content_fluid_id INTEGER")

    if not _has_col("items", "content_qty_liters"):
        conn.execute("ALTER TABLE items ADD COLUMN content_qty_liters INTEGER")
    if not _has_col("items", "crafting_grid_size"):
        conn.execute("ALTER TABLE items ADD COLUMN crafting_grid_size TEXT")

    # Detailed item classification (user-editable list of kinds)
    if not _has_col("items", "item_kind_id"):
        conn.execute("ALTER TABLE items ADD COLUMN item_kind_id INTEGER")
    if not _has_col("item_kinds", "applies_to"):
        conn.execute("ALTER TABLE item_kinds ADD COLUMN applies_to TEXT NOT NULL DEFAULT 'item'")

    if not _has_col("items", "material_id"):
        conn.execute("ALTER TABLE items ADD COLUMN material_id INTEGER")
    if not _has_col("items", "needs_review"):
        conn.execute("ALTER TABLE items ADD COLUMN needs_review INTEGER NOT NULL DEFAULT 0")

    def _has_kind_constraint() -> bool:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='items'"
        ).fetchone()
        if not row:
            return True
        sql = (row["sql"] or "").lower()
        return "crafting_grid" in sql

    def _rebuild_items_table() -> None:
        columns = [r["name"] for r in conn.execute("PRAGMA table_info(items)").fetchall()]
        col_set = set(columns)
        desired_cols = [
            "id",
            "key",
            "display_name",
            "kind",
            "is_base",
            "material_id",
            "is_machine",
            "machine_tier",
            "machine_type",
            "is_multiblock",
            "content_fluid_id",
            "content_qty_liters",
            "item_kind_id",
            "needs_review",
            "crafting_grid_size",
        ]
        select_cols = [
            col if col in col_set else f"NULL AS {col}"
            for col in desired_cols
        ]

        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            """
            CREATE TABLE items_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL UNIQUE,
                display_name TEXT,
                kind TEXT NOT NULL CHECK(kind IN ('item','fluid','gas','machine','crafting_grid')),
                is_base INTEGER NOT NULL DEFAULT 0,
                material_id INTEGER,
                is_machine INTEGER NOT NULL DEFAULT 0,
                machine_tier TEXT,
                machine_type TEXT,
                is_multiblock INTEGER NOT NULL DEFAULT 0,
                content_fluid_id INTEGER,
                content_qty_liters INTEGER,
                item_kind_id INTEGER,
                needs_review INTEGER NOT NULL DEFAULT 0,
                crafting_grid_size TEXT,
                FOREIGN KEY(material_id) REFERENCES materials(id) ON DELETE SET NULL
            )
            """
        )
        conn.execute(
            f"INSERT INTO items_new({', '.join(desired_cols)}) "
            f"SELECT {', '.join(select_cols)} FROM items"
        )
        conn.execute("DROP TABLE items")
        conn.execute("ALTER TABLE items_new RENAME TO items")
        conn.execute("PRAGMA foreign_keys=ON")

    if not _has_kind_constraint():
        _rebuild_items_table()

    # Per-machine IO slot typing (each machine slot can accept item or fluid)
    conn.execute(
        """
    CREATE TABLE IF NOT EXISTS machine_io_slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        machine_item_id INTEGER NOT NULL,
        direction TEXT NOT NULL CHECK(direction IN ('in','out')),
        slot_index INTEGER NOT NULL,
        content_kind TEXT NOT NULL CHECK(content_kind IN ('item','fluid','gas','machine')), 
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
            "INSERT INTO item_kinds(name, sort_order, is_builtin, applies_to) VALUES(?,?,1,'item')",
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
        notes TEXT,
        duplicate_of_recipe_id INTEGER
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
    if not _has_col("recipes", "duplicate_of_recipe_id"):
        conn.execute("ALTER TABLE recipes ADD COLUMN duplicate_of_recipe_id INTEGER")

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
        consumption_chance REAL DEFAULT 1.0,
        output_slot_index INTEGER,
        input_slot_index INTEGER,
        FOREIGN KEY(recipe_id) REFERENCES recipes(id) ON DELETE CASCADE,
        FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE RESTRICT
    )
    """
    )

    if not _has_col("recipe_lines", "chance_percent"):
        conn.execute("ALTER TABLE recipe_lines ADD COLUMN chance_percent REAL")
    if not _has_col("recipe_lines", "output_slot_index"):
        conn.execute("ALTER TABLE recipe_lines ADD COLUMN output_slot_index INTEGER")
    if not _has_col("recipe_lines", "input_slot_index"):
        conn.execute("ALTER TABLE recipe_lines ADD COLUMN input_slot_index INTEGER")
    if not _has_col("recipe_lines", "consumption_chance"):
        conn.execute("ALTER TABLE recipe_lines ADD COLUMN consumption_chance REAL DEFAULT 1.0")
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


def _canonical_kind_name(name: str) -> str:
    return " ".join((name or "").split()).strip().casefold()


def _canonical_item_label(name: str) -> str:
    return " ".join((name or "").split()).strip().casefold()


def _canonical_recipe_name(name: str) -> str:
    return " ".join((name or "").split()).strip().casefold()


def _recipe_line_signature(line: dict[str, Any] | sqlite3.Row) -> tuple:
    if isinstance(line, sqlite3.Row):
        try:
            consumption_chance = line["consumption_chance"]
        except Exception:
            consumption_chance = 1.0
    else:
        consumption_chance = line.get("consumption_chance", 1.0)
    return (
        line["direction"],
        line["item_key"],
        line["qty_count"],
        line["qty_liters"],
        line["chance_percent"],
        consumption_chance,
        line["output_slot_index"],
        line["input_slot_index"],
    )


def _recipe_signature(recipe: sqlite3.Row, line_sigs: list[tuple]) -> tuple:
    return (
        (recipe["method"] or "").strip(),
        (recipe["machine"] or "").strip(),
        recipe["machine_item_id"],
        (recipe["grid_size"] or "").strip(),
        recipe["station_item_id"],
        recipe["circuit"],
        (recipe["tier"] or "").strip(),
        recipe["duration_ticks"],
        recipe["eu_per_tick"],
        (recipe["notes"] or "").strip(),
        tuple(sorted(line_sigs)),
    )


def find_item_merge_conflicts(dest_conn: sqlite3.Connection, src_path: Path | str) -> list[dict[str, Any]]:
    src_path = Path(src_path)
    src = sqlite3.connect(str(src_path))
    src.row_factory = sqlite3.Row
    src.execute("PRAGMA foreign_keys=ON")
    ensure_schema(src)
    try:
        dest_rows = dest_conn.execute(
            "SELECT id, key, COALESCE(NULLIF(TRIM(display_name), ''), key) AS label FROM items"
        ).fetchall()
        dest_by_label: dict[str, list[sqlite3.Row]] = {}
        for row in dest_rows:
            canon = _canonical_item_label(row["label"])
            if not canon:
                continue
            dest_by_label.setdefault(canon, []).append(row)

        dest_keys = {row["key"] for row in dest_rows}

        conflicts: list[dict[str, Any]] = []
        src_rows = src.execute(
            "SELECT id, key, COALESCE(NULLIF(TRIM(display_name), ''), key) AS label FROM items"
        ).fetchall()
        for row in src_rows:
            if row["key"] in dest_keys:
                continue
            canon = _canonical_item_label(row["label"])
            if not canon:
                continue
            matches = dest_by_label.get(canon, [])
            if len(matches) != 1:
                continue
            dest_match = matches[0]
            conflicts.append(
                {
                    "src_id": row["id"],
                    "src_key": row["key"],
                    "src_label": row["label"],
                    "dest_id": dest_match["id"],
                    "dest_key": dest_match["key"],
                    "dest_label": dest_match["label"],
                }
            )
        return conflicts
    finally:
        src.close()


def find_missing_attributes(conn: sqlite3.Connection) -> dict[str, int]:
    missing = {}
    missing["item_kind"] = conn.execute(
        "SELECT COUNT(1) AS c FROM items WHERE kind='item' AND item_kind_id IS NULL"
    ).fetchone()["c"]
    missing["material"] = conn.execute(
        "SELECT COUNT(1) AS c FROM items WHERE kind='item' AND material_id IS NULL"
    ).fetchone()["c"]
    missing["machine_type"] = conn.execute(
        """
        SELECT COUNT(1) AS c
        FROM items
        WHERE (kind='machine' OR is_machine=1)
          AND (machine_type IS NULL OR TRIM(machine_type)='')
        """
    ).fetchone()["c"]
    missing["machine_tier"] = conn.execute(
        """
        SELECT COUNT(1) AS c
        FROM items
        WHERE (kind='machine' OR is_machine=1)
          AND (machine_tier IS NULL OR TRIM(machine_tier)='')
        """
    ).fetchone()["c"]
    return {key: int(value or 0) for key, value in missing.items()}


def merge_db(
    dest_conn: sqlite3.Connection,
    src_path: Path | str,
    *,
    item_conflicts: dict[int, int] | None = None,
) -> dict[str, int]:
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
        # ---- Material mapping ----
        dest_material_map: dict[int, int] = {}
        dest_material_by_canon: dict[str, int] = {}
        for row in dest_conn.execute("SELECT id, name FROM materials").fetchall():
            canon = _canonical_kind_name(row["name"] or "")
            if not canon:
                continue
            dest_material_by_canon[canon] = row["id"]

        src_materials = src.execute("SELECT id, name, attributes FROM materials ORDER BY id").fetchall()
        for mat in src_materials:
            name = (mat["name"] or "").strip()
            if not name:
                continue
            canon = _canonical_kind_name(name)
            dest_id = dest_material_by_canon.get(canon)
            if dest_id is not None:
                dest_material_map[mat["id"]] = dest_id
                continue
            dest_conn.execute(
                "INSERT INTO materials(name, attributes) VALUES(?, ?)",
                (name, mat["attributes"]),
            )
            new_id = dest_conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            dest_material_map[mat["id"]] = new_id
            if canon:
                dest_material_by_canon[canon] = new_id

        # ---- Kind mapping ----
        dest_kind_map: dict[int, int] = {}
        dest_kind_by_canon: dict[str, list[int]] = {}
        for row in dest_conn.execute("SELECT id, name, applies_to FROM item_kinds").fetchall():
            canon = _canonical_kind_name(row["name"] or "")
            if not canon:
                continue
            dest_kind_by_canon.setdefault(canon, []).append(row["id"])
        src_kinds = src.execute(
            "SELECT id, name, sort_order, applies_to FROM item_kinds ORDER BY id"
        ).fetchall()
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
            applies_to = (k["applies_to"] or "item").strip().lower()
            if applies_to not in ("item", "fluid"):
                applies_to = "item"
            canonical_name = _canonical_kind_name(name)
            singular_match_id = None
            if canonical_name.endswith("s") and len(canonical_name) > 3:
                singular_canon = canonical_name[:-1]
                singular_matches = dest_kind_by_canon.get(singular_canon, [])
                if len(singular_matches) == 1:
                    singular_match_id = singular_matches[0]
            if singular_match_id is not None:
                dest_kind_map[k["id"]] = singular_match_id
                continue
            dest_conn.execute(
                "INSERT INTO item_kinds(name, sort_order, is_builtin, applies_to) VALUES(?, ?, 0, ?)",
                (name, int(k["sort_order"] or 0), applies_to),
            )
            new_id = dest_conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            dest_kind_map[k["id"]] = new_id
            if canonical_name:
                dest_kind_by_canon.setdefault(canonical_name, []).append(new_id)
            stats["kinds_added"] += 1

        # Grab Machine kind id for backfills
        mk = dest_conn.execute("SELECT id FROM item_kinds WHERE LOWER(name)=LOWER('Machine')").fetchone()
        dest_machine_kind_id = mk["id"] if mk else None

        # ---- Items ----
        src_items = src.execute(
            "SELECT id, key, display_name, kind, is_base, is_machine, machine_tier, machine_type, "
            "       item_kind_id, material_id, crafting_grid_size, content_fluid_id, content_qty_liters "
            "FROM items ORDER BY id"
        ).fetchall()

        item_key_to_dest_id: dict[str, int] = {}
        src_id_to_key = {r["id"]: r["key"] for r in src_items}
        pending_fluid_links: list[tuple[int, str, int | None]] = []
        def _needs_review_for_item(
            *,
            kind: str,
            item_kind_id: int | None,
            material_id: int | None,
            is_machine: int,
            machine_type: str | None,
            machine_tier: str | None,
        ) -> bool:
            kind = (kind or "").strip().lower()
            if kind == "item":
                if item_kind_id is None or material_id is None:
                    return True
            if kind == "machine" or int(is_machine or 0):
                if not (machine_type or "").strip():
                    return True
                if not (machine_tier or "").strip():
                    return True
            return False

        for it in src_items:
            key = (it["key"] or "").strip()
            if not key:
                continue
            if item_conflicts and it["id"] in item_conflicts:
                dest_id = item_conflicts[it["id"]]
                item_key_to_dest_id[key] = dest_id
                dest_row = dest_conn.execute(
                    "SELECT kind, item_kind_id, material_id, is_machine, machine_type, machine_tier FROM items WHERE id=?",
                    (dest_id,),
                ).fetchone()
                if dest_row:
                    needs_review = _needs_review_for_item(
                        kind=dest_row["kind"],
                        item_kind_id=dest_row["item_kind_id"],
                        material_id=dest_row["material_id"],
                        is_machine=int(dest_row["is_machine"] or 0),
                        machine_type=dest_row["machine_type"],
                        machine_tier=dest_row["machine_tier"],
                    )
                    dest_conn.execute(
                        "UPDATE items SET needs_review=? WHERE id=?",
                        (1 if needs_review else 0, dest_id),
                    )
                continue

            dest_row = dest_conn.execute(
                "SELECT id, display_name, kind, is_base, is_machine, machine_tier, machine_type, "
                "       item_kind_id, material_id, crafting_grid_size, content_fluid_id, content_qty_liters "
                "FROM items WHERE key=?",
                (key,),
            ).fetchone()

            mapped_kind_id = None
            if it["item_kind_id"] is not None:
                mapped_kind_id = dest_kind_map.get(int(it["item_kind_id"]), None)

            mapped_material_id = None
            if it["material_id"] is not None:
                mapped_material_id = dest_material_map.get(int(it["material_id"]), None)

            mapped_content_fluid_id = None
            if it["content_fluid_id"] is not None:
                src_fluid_key = src_id_to_key.get(int(it["content_fluid_id"]))
                if src_fluid_key:
                    mapped_content_fluid_id = item_key_to_dest_id.get(src_fluid_key)

            if not dest_row:
                insert_sql = (
                    "INSERT INTO items(key, display_name, kind, is_base, is_machine, machine_tier, machine_type, "
                    "item_kind_id, material_id, crafting_grid_size, content_fluid_id, content_qty_liters, needs_review) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"
                )
                needs_review = _needs_review_for_item(
                    kind=it["kind"],
                    item_kind_id=mapped_kind_id,
                    material_id=mapped_material_id,
                    is_machine=int(it["is_machine"] or 0),
                    machine_type=it["machine_type"],
                    machine_tier=it["machine_tier"],
                )
                insert_values = (
                    key,
                    it["display_name"],
                    it["kind"],
                    int(it["is_base"] or 0),
                    int(it["is_machine"] or 0),
                    it["machine_tier"],
                    it["machine_type"],
                    mapped_kind_id,
                    mapped_material_id,
                    it["crafting_grid_size"],
                    mapped_content_fluid_id,
                    it["content_qty_liters"],
                    1 if needs_review else 0,
                )
                dest_conn.execute(insert_sql, insert_values)
                new_id = dest_conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
                item_key_to_dest_id[key] = new_id
                if it["content_fluid_id"] is not None and mapped_content_fluid_id is None:
                    src_fluid_key = src_id_to_key.get(int(it["content_fluid_id"]))
                    if src_fluid_key:
                        pending_fluid_links.append((new_id, src_fluid_key, it["content_qty_liters"]))
                stats["items_added"] += 1
                continue

            # Fill-in updates only (don't overwrite user edits)
            updates: dict[str, Any] = {}
            if (dest_row["display_name"] is None or str(dest_row["display_name"]).strip() == "") and (it["display_name"] or "").strip():
                updates["display_name"] = it["display_name"]
            if (dest_row["item_kind_id"] is None) and mapped_kind_id is not None:
                updates["item_kind_id"] = mapped_kind_id
            if (dest_row["material_id"] is None) and mapped_material_id is not None:
                updates["material_id"] = mapped_material_id
            if int(it["is_base"] or 0) and not int(dest_row["is_base"] or 0):
                updates["is_base"] = 1
            if dest_row["content_fluid_id"] is None and mapped_content_fluid_id is not None:
                updates["content_fluid_id"] = mapped_content_fluid_id
                if dest_row["content_qty_liters"] is None and it["content_qty_liters"] is not None:
                    updates["content_qty_liters"] = it["content_qty_liters"]

            # Machine logic: OR the flags, and backfill item_kind_id to Machine when possible.
            src_is_machine = int(it["is_machine"] or 0)
            if src_is_machine and not int(dest_row["is_machine"] or 0):
                updates["is_machine"] = 1
            if src_is_machine and dest_machine_kind_id is not None and dest_row["item_kind_id"] is None:
                updates["item_kind_id"] = dest_machine_kind_id
            if (dest_row["machine_tier"] is None or str(dest_row["machine_tier"] or "").strip() == "") and (it["machine_tier"] or "").strip():
                updates["machine_tier"] = it["machine_tier"]
            if (dest_row["machine_type"] is None or str(dest_row["machine_type"] or "").strip() == "") and (it["machine_type"] or "").strip():
                updates["machine_type"] = it["machine_type"]
            if (
                dest_row["crafting_grid_size"] is None
                or str(dest_row["crafting_grid_size"] or "").strip() == ""
            ) and (it["crafting_grid_size"] or "").strip():
                updates["crafting_grid_size"] = it["crafting_grid_size"]
            if (
                dest_row["content_qty_liters"] is None
                and it["content_qty_liters"] is not None
                and mapped_content_fluid_id is not None
                and dest_row["content_fluid_id"] is None
            ):
                updates["content_fluid_id"] = mapped_content_fluid_id
                updates["content_qty_liters"] = it["content_qty_liters"]
            if it["content_fluid_id"] is not None and mapped_content_fluid_id is None:
                src_fluid_key = src_id_to_key.get(int(it["content_fluid_id"]))
                if src_fluid_key:
                    pending_fluid_links.append((dest_row["id"], src_fluid_key, it["content_qty_liters"]))

            if updates:
                sets = ", ".join([f"{k}=?" for k in updates.keys()])
                params = list(updates.values()) + [dest_row["id"]]
                dest_conn.execute(f"UPDATE items SET {sets} WHERE id=?", tuple(params))
                stats["items_updated"] += 1

            item_key_to_dest_id[key] = dest_row["id"]
            final_values = {
                "kind": dest_row["kind"],
                "item_kind_id": updates.get("item_kind_id", dest_row["item_kind_id"]),
                "material_id": updates.get("material_id", dest_row["material_id"]),
                "is_machine": int(updates.get("is_machine", dest_row["is_machine"]) or 0),
                "machine_type": updates.get("machine_type", dest_row["machine_type"]),
                "machine_tier": updates.get("machine_tier", dest_row["machine_tier"]),
            }
            needs_review = _needs_review_for_item(**final_values)
            dest_conn.execute(
                "UPDATE items SET needs_review=? WHERE id=?",
                (1 if needs_review else 0, dest_row["id"]),
            )

        # ---- Machine IO Slots ----
        src_slots = src.execute(
            "SELECT machine_item_id, direction, slot_index, content_kind, label FROM machine_io_slots"
        ).fetchall()

        for dest_id, src_fluid_key, content_qty in pending_fluid_links:
            mapped_fluid_id = item_key_to_dest_id.get(src_fluid_key)
            if mapped_fluid_id is None:
                continue
            dest_conn.execute(
                "UPDATE items SET content_fluid_id=?, content_qty_liters=? WHERE id=? AND content_fluid_id IS NULL",
                (mapped_fluid_id, content_qty, dest_id),
            )

        for row in src_slots:
            k = src_id_to_key.get(row["machine_item_id"])
            if not k:
                continue
            dest_id = item_key_to_dest_id.get(k)
            if not dest_id:
                continue

            dest_conn.execute(
                "INSERT OR IGNORE INTO machine_io_slots(machine_item_id, direction, slot_index, content_kind, label) "
                "VALUES(?, ?, ?, ?, ?)",
                (dest_id, row["direction"], row["slot_index"], row["content_kind"], row["label"]),
            )

        # ---- Recipes ----
        src_recipes = src.execute(
            "SELECT id, name, method, machine, machine_item_id, grid_size, station_item_id, circuit, tier, duration_ticks, eu_per_tick, notes "
            "FROM recipes ORDER BY id"
        ).fetchall()

        recipe_id_map: dict[int, int] = {}
        # prefetch existing names for quick uniqueness checks
        existing_names = set(r["name"] for r in dest_conn.execute("SELECT name FROM recipes").fetchall())
        dest_recipes = dest_conn.execute(
            "SELECT id, name, method, machine, machine_item_id, grid_size, station_item_id, circuit, tier, duration_ticks, eu_per_tick, notes "
            "FROM recipes"
        ).fetchall()
        dest_name_keys = {r["id"]: _canonical_recipe_name(r["name"]) for r in dest_recipes}
        dest_lines_rows = dest_conn.execute(
            """
            SELECT rl.recipe_id, rl.direction, i.key AS item_key, rl.qty_count, rl.qty_liters,
                   rl.chance_percent, rl.consumption_chance, rl.output_slot_index, rl.input_slot_index
            FROM recipe_lines rl
            JOIN items i ON i.id = rl.item_id
            """
        ).fetchall()
        dest_line_map: dict[int, list[tuple]] = {}
        for row in dest_lines_rows:
            dest_line_map.setdefault(row["recipe_id"], []).append(_recipe_line_signature(row))
        dest_signatures = {
            r["id"]: _recipe_signature(r, dest_line_map.get(r["id"], []))
            for r in dest_recipes
        }
        dest_signature_ids: dict[tuple, list[int]] = {}
        for recipe_id, signature in dest_signatures.items():
            dest_signature_ids.setdefault(signature, []).append(recipe_id)

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

        def _closest_recipe_id(name: str) -> int | None:
            canon = _canonical_recipe_name(name)
            best_id = None
            best_ratio = 0.0
            for r in dest_recipes:
                ratio = SequenceMatcher(None, canon, dest_name_keys[r["id"]]).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_id = r["id"]
            return best_id if best_ratio >= 0.88 else None

        # helper: map src station_item_id / machine_item_id -> dest id
        src_item_rows = src.execute("SELECT id, key FROM items").fetchall()
        src_item_id_to_key = {r["id"]: r["key"] for r in src_item_rows}
        dest_item_id_to_key = {
            r["id"]: r["key"] for r in dest_conn.execute("SELECT id, key FROM items").fetchall()
        }
        src_lines_rows = src.execute(
            """
            SELECT rl.recipe_id, rl.item_id, rl.direction, i.key AS item_key, rl.qty_count, rl.qty_liters,
                   rl.chance_percent, rl.consumption_chance, rl.output_slot_index, rl.input_slot_index
            FROM recipe_lines rl
            JOIN items i ON i.id = rl.item_id
            """
        ).fetchall()
        src_line_map: dict[int, list[tuple]] = {}
        for row in src_lines_rows:
            if item_conflicts and row["item_id"] in item_conflicts:
                dest_key = dest_item_id_to_key.get(item_conflicts[row["item_id"]])
                if dest_key:
                    row = dict(row)
                    row["item_key"] = dest_key
            src_line_map.setdefault(row["recipe_id"], []).append(_recipe_line_signature(row))

        for r in src_recipes:
            close_match_id = _closest_recipe_id(r["name"])
            src_signature = _recipe_signature(r, src_line_map.get(r["id"], []))
            if src_signature in dest_signature_ids:
                recipe_id_map[int(r["id"])] = None
                continue
            if close_match_id is not None and dest_signatures.get(close_match_id) == src_signature:
                recipe_id_map[int(r["id"])] = None
                continue

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
                "INSERT INTO recipes(name, method, machine, machine_item_id, grid_size, station_item_id, circuit, tier, duration_ticks, eu_per_tick, notes, duplicate_of_recipe_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
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
                    close_match_id,
                ),
            )
            new_id = dest_conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            recipe_id_map[int(r["id"])] = int(new_id)
            stats["recipes_added"] += 1

        # ---- Recipe lines ----
        src_lines = src.execute(
            "SELECT recipe_id, direction, item_id, qty_count, qty_liters, chance_percent, consumption_chance, output_slot_index, input_slot_index "
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
                "INSERT INTO recipe_lines(recipe_id, direction, item_id, qty_count, qty_liters, chance_percent, consumption_chance, output_slot_index, input_slot_index) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    new_recipe_id,
                    ln["direction"],
                    new_item_id,
                    ln["qty_count"],
                    ln["qty_liters"],
                    ln["chance_percent"],
                    ln["consumption_chance"] if "consumption_chance" in ln.keys() else 1.0,
                    ln["output_slot_index"],
                    ln["input_slot_index"],
                ),
            )
            stats["lines_added"] += 1

        dest_conn.commit()
        return stats

    finally:
        src.close()



def merge_database(
    dest_conn: sqlite3.Connection,
    src_path: Path | str,
    *,
    item_conflicts: dict[int, int] | None = None,
) -> dict[str, int]:
    """Alias for merge_db (kept for readability in UI layer)."""
    return merge_db(dest_conn, src_path, item_conflicts=item_conflicts)


def copy_file(src_path: Path | str, dst_path: Path | str) -> None:
    """Simple file copy helper (used rarely; prefer export_db for SQLite safety)."""
    shutil.copy2(str(src_path), str(dst_path))
