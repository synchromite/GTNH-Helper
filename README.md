# GTNH Helper

A recipe database browser and inventory helper for GregTech New Horizons.

> **Status:** The app is focused on the GTNH 2.7.4 data set.

## Features
- **Browse items, fluids, gases, and recipes** with full input/output details.
- **Inventory tracking** stored per profile database, with optional per-storage container management.
- **Tier filtering** (plus 6x6 crafting unlock toggle) to narrow recipe lists.
- **Recipe Planner** that builds a dependency tree from your inventory and generates a shopping list.
  - Uses storage policy filters (`allow_planner_use`, `locked`) and deterministic priority-based consumption.
  - Applies machine-capacity hard filtering (item slots + fluid tanks) so impossible machine variants are excluded before ranking.
- **Interactive Build Mode** with step-by-step instructions tied to inventory updates.
- **Machine tracking** for owned/online availability used by planning and machine selection.
- **Automation tracker tab** for manually building full processing chains (machine -> output -> next machine), including optional byproducts and per-step status.
- **Storage-aware inventory workflows**: active storage selection, aggregate read-only mode, per-storage totals, and storage CRUD management.
  - Storage list ordering is now aligned with planner consumption ordering (`priority DESC`, then name/id tie-breakers).
  - `Main Storage` uses its configured priority like any other storage unit.
- **Capacity-aware validation**: slot/liter fit checks with stack-size-aware slot math and container placement tracking.
- **Editor mode** (optional) for adding/editing items, recipes, materials, item kinds, and machine metadata.
- **Container transform manager** (editor mode) for explicit fill/empty mapping rows used by planner transform handling.
- **Smarter metadata review flags during DB merge**:
  - Material is required only for material-dependent item kinds (e.g., dust/ingot/plate families).
  - Machine items still require machine type + tier.
  - Standard items still require an item kind.
- **Fluid unit convention:** all fluid/gas quantities are stored and displayed as liters (`L`) where **1 L = 1 mB**.
- **Tab customization**: enable/disable, reorder, and detach tabs.
- **Theme toggle**: light/dark theme switching.
- **DB utilities**: open, export content/profile DBs, and merge content DBs (editor mode only).
- **Minecraft mod sync foundation**: import inventory snapshots from a companion mod JSON export using stable item keys (unknown keys are reported, not silently dropped).

## Modes
The app runs in **client mode** by default:
- Content database is opened **read-only**.
- Editing features are disabled.
- Creating new DBs and merging DBs are disabled.

To enable **editor mode**, create a file named `.enable_editor` next to `app.py`.
Remove the file to switch back to client mode.

## Data storage
- **Content DB:** `gtnh.db` (items, recipes, machine metadata).
- **Profile DB:** `profile.db` (tiers, unlocks, inventory, machine availability, UI settings).

If you open a non-default content DB, the profile DB is created alongside it as
`<content_stem>_profile.db`.

Profile data is kept separate so your progress survives content DB updates.

## Inventory Containers status
- The Inventory & Containers project is complete in the current codebase.
- Planner consumption policy behavior is implemented and covered by tests (`allow_planner_use`, `locked`, deterministic priority ordering).
- Generic container transform behavior is implemented for fill/empty flows with deterministic priority ordering, plus editor-mode CRUD support.
- The former tracking document `INVENTORY_CONTAINERS_PROJECT_PLAN.md` has been retired.

## In progress
- Qt UI polish - Ongoing

## Planned
- Feature requests are open

## Requirements
- Python 3.10+
- PySide6 (Qt UI toolkit)

## Releases
- Windows Installer - Coming Soon
- Mac Installer - Coming Soon
- Linux Installer (.deb) - Coming Soon

## Build it yourself (right now)
```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
pyinstaller --clean --noconfirm gtnh_helper.spec
```

Packaged outputs are written to `dist/`.

## Run from Python
```bash
python -m pip install -r requirements.txt
python app.py
```

## Mod integration (early foundation)
A first-pass backend sync utility is available in `services/mod_sync.py` for importing inventory snapshots exported by a Minecraft mod.

Snapshot schema (v1):
```json
{
  "schema_version": 1,
  "entries": [
    {"item_key": "minecraft:iron_ingot", "qty_count": 64},
    {"item_key": "water", "qty_liters": 1000}
  ]
}
```

Notes:
- `item_key` must match `items.key` in the content DB.
- At least one of `qty_count` or `qty_liters` is required per entry.
- Unknown `item_key` values are returned in the sync report so the UI can surface mismatches.


## Companion Minecraft mod (JSON exporter)
A companion mod scaffold is now included at `minecraft_mod/gtnh-helper-exporter/`. It exports in-game inventory to JSON so GTNH Helper can import it.

- Command: `/gtnhhelper export_inventory`
- Output path: `config/gtnh-helper/snapshots/<player>_<timestamp>.json`
- Output schema matches the app snapshot format (`schema_version: 1`, `entries[]` with `item_key` + `qty_count`).

See `minecraft_mod/gtnh-helper-exporter/README.md` for setup and caveats.
