# GTNH Helper Content Export Mod (Companion)

This companion mod is for **one-time / occasional content extraction**, not normal gameplay sync.

## What it does
- Adds command: `/gtnhhelper export_content`
- Exports registries and recipes into one unique JSON file:
  - Item ID map (`id` + `key`)
  - Fluid ID map (`id` + `key`)
  - Recipe list with recipe id/type/serializer, ingredient options, and primary output
- Writes JSON to:
  - `config/gtnh-helper/content-exports/content_seed_<player>_<timestamp>_<uuid>.json`

## Why this exists
Use this file to seed your app DB with a stable, ID-based snapshot so backend calculations can use IDs instead of names.

## Export shape (simplified)
```json
{
  "export_kind": "content_seed",
  "schema_version": 1,
  "ids": {
    "items": [{"id": 1, "key": "minecraft:stone"}],
    "fluids": [{"id": 1, "key": "minecraft:water"}]
  },
  "recipes": [
    {
      "id": "minecraft:stone_pickaxe",
      "recipe_type": "minecraft:crafting",
      "serializer": "minecraft:crafting_shaped",
      "inputs": [{"options": [{"item_id": 1, "item_key": "minecraft:stone"}]}],
      "output": {"item_id": 257, "item_key": "minecraft:stone_pickaxe", "count": 1}
    }
  ]
}
```

## Notes
- Scaffolded for Fabric 1.20.1 as a reference implementation.
- GTNH runtime is 1.7.10; port to the GTNH modding stack when targeting real GTNH extraction.
- This exporter is intentionally "offline seed" focused; real-time app sync should be a separate mod/pass.
