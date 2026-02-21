# Inventory & Containers Project Plan

## Goal
Add first-class inventory container management (chests/drawers/barrels/tanks) while preserving existing global inventory behavior and current fluid-container emptying support.

## Guiding Constraints (Current Reality)
- Profile DB schema is still in flux.
- During development iterations, DBs are routinely reset and recreated.
- Avoid migration hardening work until schema stabilizes.
- Keep bookkeeping optional: users can stay on a single `Main Storage` and get near-current behavior.

## Scope
- Introduce storage entities and per-storage inventory assignments in profile data.
- Keep planner compatibility by aggregating per-storage inventory into a global view.
- Add storage-aware UX in inventory management with an explicit active storage selector.
- Defer advanced policies/capacity constraints until baseline architecture is proven useful.

## Non-Goals (Near Term)
- Legacy profile migration and upgrade-path hardening.
- Auto-sync with in-game data sources.
- Networked multi-user conflict resolution.
- Perfect per-mod storage simulation for every GTNH edge case.

---

## Phase 0 (Recommended): Minimal Architecture Slice - COMPLETE
**Purpose:** Prove value and avoid scope creep before full M1–M6 rollout.

### Deliverables
1. Add `storage_units` with one seeded default row: `Main Storage`.
2. Track item quantities by `storage_id` (via `storage_assignments`, or an equivalent schema simplification).
3. Update planner inventory load to `SUM` quantities across storages into current global dictionary shape.
4. Keep Inventory UI mostly unchanged except for selecting active storage and read-only behavior in aggregate mode.

### Success Criteria
- Planner output remains stable compared to current behavior.
- Users can ignore storage complexity by using only `Main Storage`.
- Codebase has the right architectural seam for future capacity/policy features.
- Unset active storage defaults to `Main Storage` (name/id semantics), not lexical sort order.
- `All Storages` aggregate mode blocks all persistence-affecting inventory actions (quantity edits, clear/save, and related inventory-write side effects).
- Legacy `inventory` -> `storage_assignments` backfill runs only under explicit versioned migration conditions, not merely when assignments are empty.

---

## Milestones

## Milestone 1: Data Model (Clean-Slate Iteration Mode) - COMPLETE
**Outcome:** Storage-aware schema works in current clean-reset development workflow.

### Issues
1. **Profile DB schema for storage units - COMPLETE**
   - Add `storage_units` in `services/db.py` via `connect_profile()`:
     - `id`, `name`, `kind`, `slot_count`, `liter_capacity`, `priority`, `allow_planner_use`, `notes`.
   - Keep `PRAGMA foreign_keys=ON` and define FK behavior deliberately.

2. **Per-storage inventory assignments - COMPLETE**
   - Add `storage_assignments` table:
     - `(storage_id, item_id, qty_count, qty_liters, locked)`.
   - Composite PK `(storage_id, item_id)`, and FK with `ON DELETE CASCADE` on storage rows.

3. **Reset-friendly bootstrap (no migration yet) - COMPLETE**
   - Seed a default storage unit (`Main Storage`) on fresh profile init.
   - Do not add legacy migration complexity while schema is changing.

4. **Storage service abstraction - COMPLETE**
   - Add `services/storage.py` for storage CRUD, assignment CRUD, and quantity aggregation helpers.
   - Keep fit/capacity math out of UI widgets.

### Exit Criteria
- Fresh DB initialization supports storage units and assignments end-to-end.
- Deleting a storage unit cleans up assignments predictably.

---

## Milestone 2: Planner Compatibility Layer - COMPLETE
**Outcome:** Planner can consume aggregated storage inventory while preserving current outputs.

### Issues
1. **Aggregate inventory loader - COMPLETE**
   - Update planner load path (`services/planner.py`) to aggregate storage assignments into the existing planner inventory map shape.

2. **Unit-aware aggregation parity - COMPLETE**
   - Preserve current count/liter semantics by item kind.

3. **Temporary compatibility simplification - COMPLETE**
   - Runtime inventory loading now relies on `storage_assignments` aggregation only.
   - Legacy `inventory` fallback/migration behavior remains explicitly deferred as post-stabilization hardening.

4. **Regression test coverage - COMPLETE**
   - Confirm unchanged behavior for:
     - simple chain recipes,
     - inventory override,
     - fluid container emptying + byproducts,
     - non-consumed inputs.

### Regression Coverage Status (Review)
- ✅ `tests/test_planner.py::test_plan_simple_chain_with_inventory_override` validates simple chain + override behavior.
- ✅ `tests/test_planner.py::test_plan_inserts_emptying_step_for_fluid_container` validates fluid-container emptying and byproduct handling.
- ✅ `tests/test_planner.py::test_plan_accounts_for_non_consumed_inputs` validates non-consumed input accounting.
- ✅ `tests/test_planner.py::test_load_inventory_sums_all_storage_units` and
  `tests/test_planner.py::test_load_inventory_preserves_unit_column_by_item_kind` validate storage aggregate parity.
- ✅ `tests/test_planner.py::test_load_inventory_does_not_fallback_to_legacy_inventory_table` and
  `tests/test_profile_db.py::test_connect_profile_does_not_backfill_storage_assignments_from_inventory` confirm migration/backfill remains deferred.

### Exit Criteria
- Existing planner tests continue to pass.
- New tests prove storage-aggregate parity.
- Migration/backfill behavior remains deferred until schema stabilization.

---

## Milestone 3: Inventory UI – Storage-Aware Workflows - COMPLETE
**Outcome:** Users can manage specific storages without forcing strict bookkeeping.

### Issues
1. **Active storage selector in inventory tab - COMPLETE**
   - Add a `QComboBox` in `ui_tabs/inventory_tab.py`:
     - `Main Storage` and other named storages,
     - `All Storages` aggregate option.

2. **Edit rules by selection - COMPLETE**
   - Editing applies to selected concrete storage only.
   - `All Storages` is read-only to avoid ambiguous/phantom writes.

3. **Storage CRUD dialogs - COMPLETE**
   - Add create/edit/delete storage unit flows in `ui_dialogs.py`.
   - Validate unique names and non-negative capacities.

4. **Baseline summary panel - COMPLETE**
   - Display per-storage totals and aggregate totals.
   - Keep advanced capacity visualizations optional until M4.


### Milestone 3 Coverage Status (Review)
- ✅ Inventory tab includes an active `Storage` selector with concrete storages plus `All Storages (Aggregate)`.
- ✅ Selection-based edit behavior is enforced:
  - concrete storage selection enables quantity edits,
  - aggregate mode blocks inventory quantity writes,
  - aggregate mode also blocks machine-availability persistence side effects.
- ✅ Storage CRUD dialog flows exist (create/edit/delete) with unique-name validation, non-negative capacity validation, and `Main Storage` delete protection.
- ✅ Baseline summary panel reports selected-storage totals and aggregate totals.
- ✅ Active storage fallback remains deterministic (`Main Storage` when unset/invalid).

### Exit Criteria
- Users can stay simple (single `Main Storage`) or opt into detailed storage tracking.
- Aggregate totals remain coherent with per-storage entries.
- Active storage default behavior is deterministic: unset always resolves to `Main Storage`.
- Aggregate mode is verified as fully read-only for inventory persistence paths.

---

## Milestone 4: Capacity & Fit Validation (Optional After Phase 0/M3) - COMPLETE
**Outcome:** Prevent impossible storage states and report overflow clearly.

### Issues
1. **Item stack-size metadata - COMPLETE**
   - Added `max_stack_size` to `items` schema with default `64` and compatibility migration support.

2. **Capacity math helpers in service layer - COMPLETE**
   - Implemented deterministic slot/liter fit helpers in `services/storage.py`, including stack-aware slot math.

3. **Save-time validation/warnings - COMPLETE**
   - Inventory save now validates selected-storage fit before persisting and reports overflow details.

4. **Automated edge-case tests - COMPLETE**
   - Added tests for stack size `1` non-stackables and slot/liter boundary overflow conditions.

### Milestone 4 Coverage Status (Review)
- ✅ Item schema now includes stack-size metadata (`max_stack_size`) with migration-safe defaults.
- ✅ Storage service exposes slot-usage math and per-storage fit validation for pending writes.
- ✅ Inventory tab blocks impossible saves and surfaces clear overflow warnings instead of persisting invalid states.
- ✅ Automated tests cover non-stackables (`max_stack_size=1`), exact-fit boundaries, and slot/liter overflow cases.

### Exit Criteria
- Capacity behavior is deterministic and covered by tests.

---

## Milestone 5: Planner Consumption Policies (Optional)
**Outcome:** Planner can consume inventory by configurable storage policy.

### Issues
1. Respect `allow_planner_use` and `locked` semantics.
2. Priority-based deterministic consumption.
3. Basic policy control in settings/UI.
4. Policy test matrix across mixed storages.

### Implementation Notes for M5
- Treat policy evaluation order as a stable contract: filter by `allow_planner_use`, then `locked`, then consume by explicit priority and deterministic tie-breakers (for example, storage `id`).
- Keep planner consumption deterministic even when inventories are highly fragmented across many storage units.
- Add regression coverage for large mixed-storage scenarios to ensure planner output does not drift due to row ordering or query-plan variance.

### Execution Plan for M5
1. **Planner query + service contract update**
   - Add storage-selection helpers in `services/storage.py` that return a stable, policy-filtered candidate list.
   - Make deterministic ordering explicit at SQL level (`ORDER BY priority DESC, id ASC`) and in Python fallbacks.
2. **Planner consumption integration**
   - Update planner inventory-consumption path in `services/planner.py` to consume from policy-filtered candidates only.
   - Ensure `locked` inventory remains visible for reporting but excluded from consumption.
3. **Policy configuration UX**
   - Add minimal settings/UI controls for policy toggles and defaults.
   - Keep default behavior equivalent to current single-storage expectations when users do not opt in.
4. **Validation + test matrix**
   - Add table-driven tests for: mixed `allow_planner_use`, mixed `locked`, equal priority tie-breakers, and highly fragmented inventories.
   - Add deterministic replay checks to confirm identical outputs across repeated runs.

### Suggested PR Slices for M5
- **PR 1 (services):** policy selection helpers + deterministic ordering tests.
- **PR 2 (planner):** consumption integration + regression tests.
- **PR 3 (ui/settings):** basic policy controls and persistence wiring.

### Exit Criteria
- Planner output remains deterministic under configured policy.

---

## Milestone 6: Generic Container Transform System (Optional)
**Outcome:** Extend fluid emptying into a general transform framework.

### Issues
1. Introduce transform mapping model (`item_container_transforms` or equivalent).
2. Refactor fluid-specific emptying logic to generic transform pass in planner.
3. Add editor support for defining transforms.
4. Preserve current fluid-cell behavior via regression tests.

### Implementation Notes for M6
- Preserve fluid emptying as the first compatibility transform implemented in the generic pipeline.
- Ensure transform execution remains deterministic (stable ordering + explicit matching rules) so future transform types (e.g., gas or specialty containers) can compose safely.
- Keep transform metadata schema generic enough to support additional container mechanics without planner rewrites.

### Execution Plan for M6
1. **Schema + data model foundation**
   - Introduce a generic transform table (`item_container_transforms`) with explicit input/output item refs, unit semantics, and optional byproduct fields.
   - Include a deterministic sort key (`priority`, then `id`) for transform application order.
2. **Planner transform engine extraction**
   - Isolate current fluid-emptying logic into a reusable transform pass.
   - Run transform pass before core recipe resolution, preserving existing planner expectations.
3. **Compatibility bootstrap**
   - Seed current fluid-cell behavior as transform rows rather than planner special-cases.
   - Keep existing fluid tests unchanged to prove behavior parity.
4. **Editor + extensibility pass**
   - Add basic editor support to create/edit transforms with guardrails for invalid mappings.
   - Add at least one non-fluid transform fixture (e.g., gas canister or specialty container) and validate end-to-end planning.

### Suggested PR Slices for M6
- **PR 1 (schema/services):** transform schema + CRUD service + unit tests.
- **PR 2 (planner):** generic transform pass + fluid compatibility regression.
- **PR 3 (ui):** transform editor + non-fluid transform integration test.

### Exit Criteria
- Fluid behavior is unchanged and at least one non-fluid transform works end-to-end.

---

## Suggested Epics / Labels
- **Epic A:** Storage data model
- **Epic B:** Planner integration
- **Epic C:** Inventory UI
- **Epic D:** Capacity validation
- **Epic E:** Planner policy
- **Epic F:** Generic transforms

Label suggestions:
- `area:db`, `area:planner`, `area:ui`, `area:tests`, `schema-flux`, `feature:inventory`, `feature:containers`

---

## Suggested Delivery Sequence (Right-Sized)
1. **Phase 0 + M1 + M2** (minimum robust architecture, low churn).
2. **M3** (active storage UX and aggregate-read-only mode).
3. Decide based on real usage whether to implement **M4/M5/M6**.

---

## Risk Register
1. **Schema churn risk**
   - Risk: frequent table/column refactors during implementation.
   - Mitigation: clean-slate workflow + narrow early slice (Phase 0).

2. **Planner output drift**
   - Risk: changed shopping list/step order.
   - Mitigation: regression tests around current planner scenarios.

3. **Bookkeeping burden**
   - Risk: feature feels like a chore.
   - Mitigation: default `Main Storage` path keeps old behavior for casual users.

4. **UI complexity creep**
   - Risk: too many controls in inventory tab.
   - Mitigation: keep M3 minimal; defer advanced controls to optional milestones.

---

## Definition of Done (Near-Term)
- Phase 0 and Milestones 1–3 are complete.
- Existing test suite passes.
- New tests cover clean DB bootstrap, storage aggregation, planner parity, and active-storage UI behavior.
- `Main Storage`-only usage path remains straightforward.
- Acceptance tests explicitly verify: (1) unset active storage defaults to `Main Storage`, (2) aggregate mode prevents all inventory persistence writes, and (3) legacy backfill is versioned-migration gated.

---

## Post-Stabilization Follow-up (Out of Current Scope)
When schema stabilizes, add a hardening milestone for:
- legacy profile migration from `inventory` to storage-based tables,
- rollback/upgrade safety checks,
- migration-path test coverage.

### Stabilization Trigger for Migration Hardening
- Milestone 4 introduced stack-size metadata and compatibility migrations, so migration hardening should be scheduled as soon as Milestone 5 scope is finalized.
- Define a versioned, repeatable migration path for legacy inventory tables before broad rollout of policy semantics to existing user profiles.
