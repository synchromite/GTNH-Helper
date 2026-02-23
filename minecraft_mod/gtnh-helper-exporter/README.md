# GTNH Helper Content Export Mod (Forge / GTNH-oriented)

This companion mod is for **one-time / occasional content extraction**, not gameplay sync.

## What it does
- Adds server command: `/gtnhhelper_export_content`
- Exports registries and recipes into one unique JSON file:
  - Item ID map (`id` + `key`)
  - Fluid ID map (`id` + `key`)
  - Recipe list with recipe type, ingredient option sets, and primary output
- Writes JSON to:
  - `config/gtnh-helper/content-exports/content_seed_<sender>_<timestamp>_<uuid>.json`

## Why this exists
Use this file to seed your app DB with a stable, ID-based snapshot so backend calculations can use IDs instead of names.

## Stack
- **Minecraft:** 1.7.10
- **Mod loader:** Forge (ForgeGradle 1.2 scaffold)

## Notes
- This is intentionally focused on offline content seeding for a specific pack/version pass.
- Runtime app sync/update behavior should be implemented as a separate mod workflow.
