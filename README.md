# GTNH Helper

A recipe database browser and inventory helper for GregTech New Horizons.

> **Status:** The app is focused on the GTNH 2.7.4 data set.

## Features
- **Browse items, fluids, gases, and recipes** with full input/output details.
- **Inventory tracking** stored per profile database.
- **Tier filtering** (plus 6x6 crafting unlock toggle) to narrow recipe lists.
- **Recipe Planner** that builds a dependency tree from your inventory and generates a shopping list.
- **Interactive Build Mode** with step-by-step instructions tied to inventory updates.
- **Machine tracking** for owned/online availability used by planning and machine selection.
- **Editor mode** (optional) for adding/editing items, recipes, materials, item kinds, and machine metadata.
- **Tab customization**: enable/disable, reorder, and detach tabs.
- **Theme toggle**: light/dark theme switching.
- **DB utilities**: open, export content/profile DBs, and merge content DBs (editor mode only).

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

## In progress
- Qt UI polish - Ongoing
- Planner Polishing - Ongoing
  
## Planned
- Feature requests are open

## Requirements
- Python 3.10+
- PySide6 (Qt UI toolkit)

## Install
python -m pip install -r requirements.txt
