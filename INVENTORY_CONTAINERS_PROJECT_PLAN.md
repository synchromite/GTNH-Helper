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

## Milestone 1: Data Model (Clean-Slate Iteration Mode)
**Outcome:** Storage-aware schema works in current clean-reset development workflow.

### Issues
1. **Profile DB schema for storage units - COMPLETE**
   - Add `storage_units` in `services/db.py` via `connect_profile()`:
     - `id`, `name`, `kind`, `slot_count`, `liter_capacity`, `priority`, `allow_planner_use`, `notes`.
   - Keep `PRAGMA foreign_keys=ON` and define FK behavior deliberately.

2. **Per-storage inventory assignments**
   - Add `storage_assignments` table:
     - `(storage_id, item_id, qty_count, qty_liters, locked)`.
   - Composite PK `(storage_id, item_id)`, and FK with `ON DELETE CASCADE` on storage rows.

3. **Reset-friendly bootstrap (no migration yet)**
   - Seed a default storage unit (`Main Storage`) on fresh profile init.
   - Do not add legacy migration complexity while schema is changing.

4. **Storage service abstraction**
   - Add `services/storage.py` for storage CRUD, assignment CRUD, and quantity aggregation helpers.
   - Keep fit/capacity math out of UI widgets.

### Exit Criteria
- Fresh DB initialization supports storage units and assignments end-to-end.
- Deleting a storage unit cleans up assignments predictably.

---

## Milestone 2: Planner Compatibility Layer
**Outcome:** Planner can consume aggregated storage inventory while preserving current outputs.

### Issues
1. **Aggregate inventory loader**
   - Update planner load path (`services/planner.py`) to aggregate storage assignments into the existing planner inventory map shape.

2. **Unit-aware aggregation parity**
   - Preserve current count/liter semantics by item kind.

3. **Temporary compatibility simplification**
   - Skip legacy fallback while app runtime assumes clean DB creation.
   - Track migration/fallback as post-stabilization hardening.

4. **Regression test coverage**
   - Confirm unchanged behavior for:
     - simple chain recipes,
     - inventory override,
     - fluid container emptying + byproducts,
     - non-consumed inputs.

### Exit Criteria
- Existing planner tests continue to pass.
- New tests prove storage-aggregate parity.
- Migration/backfill behavior is version-gated and covered by targeted migration tests.

---

## Milestone 3: Inventory UI – Storage-Aware Workflows
**Outcome:** Users can manage specific storages without forcing strict bookkeeping.

### Issues
1. **Active storage selector in inventory tab**
   - Add a `QComboBox` in `ui_tabs/inventory_tab.py`:
     - `Main Storage` and other named storages,
     - `All Storages` aggregate option.

2. **Edit rules by selection**
   - Editing applies to selected concrete storage only.
   - `All Storages` is read-only to avoid ambiguous/phantom writes.

3. **Storage CRUD dialogs**
   - Add create/edit/delete storage unit flows in `ui_dialogs.py`.
   - Validate unique names and non-negative capacities.

4. **Baseline summary panel**
   - Display per-storage totals and aggregate totals.
   - Keep advanced capacity visualizations optional until M4.

### Exit Criteria
- Users can stay simple (single `Main Storage`) or opt into detailed storage tracking.
- Aggregate totals remain coherent with per-storage entries.
- Active storage default behavior is deterministic: unset always resolves to `Main Storage`.
- Aggregate mode is verified as fully read-only for inventory persistence paths.

---

## Milestone 4: Capacity & Fit Validation (Optional After Phase 0/M3)
**Outcome:** Prevent impossible storage states and report overflow clearly.

### Issues
1. **Item stack-size metadata**
   - Add `max_stack_size` to `items` schema (default 64).

2. **Capacity math helpers in service layer**
   - Implement slot/liter fit checks in `services/storage.py`.

3. **Save-time validation/warnings**
   - Validate against storage limits before persisting.

4. **Automated edge-case tests**
   - Cover stack size 1/non-stackables and boundary cases.

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
