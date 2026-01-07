# GTNH Helper

A recipe database browser and inventory helper for GregTech New Horizons.

> **Status:** The app is focused on the GTNH 2.7.4 data set.

## Features
- **Browse items & recipes**: with full input/output details.
- **Inventory tracking**: stored per-profile.
- **Tier filtering**: (and 6x6 crafting unlock toggle) to narrow the recipe list.
- **Tab customization**: enable/disable tabs and reorder them from the **Tabs** menu.
- **Editor mode**: (optional) to add/edit/delete items and recipes.
- **Recipe Planner**: Plan Recipes based on what you have in inventory. Punch in a complex recipe and it will go thru the process till it find's either something in your inventory or until it finds a base item, like an ore.  Then it gives you a shopping list letting you know what you need to gather.

## Modes
The app runs in **client mode** by default:
- Content database is opened **read-only**.
- Editing features are disabled.

To enable **editor mode**, create a file named `.enable_editor` next to `app.py`.
Remove the file to switch back to client mode.

## Data storage
- **Content DB:** `gtnh.db` (items/recipes).
- **Profile DB:** `profile.db` (tiers, unlocks, inventory).

Profile data is kept separate so your progress survives content DB updates.

## In progress
- Planner Polishing - 2026.01.07
- Build Button in Planner - 2026.01.07

## Planned
- Machine tier dropdown/display polish.
- Optional hiding of Item/Recipe tabs when editor mode is disabled.
- Machine Tab

