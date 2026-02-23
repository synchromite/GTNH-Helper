# GTNH Helper Exporter Mod (Companion)

This is a **companion Minecraft mod scaffold** that exports a player's inventory to the JSON format consumed by GTNH Helper.

## What it does
- Adds command: `/gtnhhelper export_inventory`
- Exports current player inventory (main + armor + offhand) as item counts.
- Writes JSON to:
  - `config/gtnh-helper/snapshots/<player>_<timestamp>.json`

## Snapshot format
```json
{
  "schema_version": 1,
  "entries": [
    {"item_key": "minecraft:iron_ingot", "qty_count": 64},
    {"item_key": "minecraft:cobblestone", "qty_count": 128}
  ]
}
```

## Notes
- This is currently scaffolded for Fabric 1.20.1 as a starting point.
- GTNH itself is 1.7.10, so if your target runtime is real GTNH, this should be treated as implementation reference and ported to the GTNH modding stack.
- Fluids are not exported in this first pass; item stacks only.
