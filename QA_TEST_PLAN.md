# QA Test Plan — GTNH Helper (Blank Database)

This document is a step-by-step QA checklist for validating the application when starting from a **blank database**. It is intended for testers with no prior experience using the app. The flow follows a complete use path from an empty DB, through data entry, planning, and finally export/import/merge validation.

---

## 0) Environment, Editor Mode, & Clean DB Setup

**Goal:** Start from a blank database and confirm the app launches cleanly.

1. **Confirm requirements are installed**
   - Run:
     ```bash
     python -m pip install -r requirements.txt
     ```
   - **Expected:** Install succeeds without errors.

2. **Enable editor mode**
   - Create a file named `.enable_editor` next to `app.py`.
   - **Expected:** Editing controls (Add/Edit/Delete) are available in the UI after launch.

3. **Start from a blank database**
   - Ensure no `gtnh.db` or `profile.db` is present in the app folder.
   - If they exist, back them up and move them elsewhere.
   - **Expected:** App creates new blank DBs when started or via **File → New DB…**.

4. **Launch the app**
   - Run:
     ```bash
     python ui_main.py
     ```
   - **Expected:** App window opens with no error dialog.

---

## 1) Main Window UI & Menus (Coverage of All Top-Level Controls)

**Goal:** Touch every top-level menu and window control at least once.

1. **File menu**
   - **Open DB…**: choose a valid DB file; confirm the app refreshes lists.
   - **New DB…**: create a new blank DB in a new location.
   - **Export Content DB…** and **Export Profile DB…**: export to a known location.
   - **Merge DB…**: select a second DB and verify import completes.
   - **Quit**: confirm the app closes without errors.

2. **Tabs menu**
   - Toggle each tab (Items, Fluids, Gases, Recipes, Inventory, Tiers, Planner, Machines) off/on.
   - **Reorder Tabs…**: reorder tabs and confirm the new order persists after restart.

3. **View menu**
   - Switch between light/dark themes and confirm UI updates.

4. **Tools menu**
   - **Manage Materials**: open and close the dialog (detailed in Step 6).
   - **Manage Item Kinds**: open and close the dialog (detailed in Step 6).

5. **Tab context menu**
   - Right-click any tab and use **Detach**, then reattach the window.
   - **Expected:** Detached tab continues to update data and reattaches cleanly.

---

## 2) Machine Metadata Baseline

**Goal:** Machine stats live in `machine_metadata`, so at least one machine definition must exist before machine items will show accurate stats.

1. Open **Machines** tab.
2. Click **Edit Specs…** (editor mode required).
3. Add a row:
   - **Machine Type:** `Lathe`
   - **Tier:** `LV`
   - **Input Slots:** `1`
   - **Output Slots:** `1`
   - **Input Tanks:** `0`
   - **Output Tanks:** `0`
4. Save and close.

**Expected:** The metadata row is saved in the editor dialog and persists after reopening it.

---

## 3) Add Core Items (Machines + Materials)

**Goal:** Items should reference machines by **machine_type + machine_tier**, not by item name.

1. Open **Items** tab.
2. Click **Add Item**.
3. Fill fields:
   - **Display Name:** `Basic Lathe`
   - **Kind:** `machine`
   - **Machine Type:** `Lathe`
   - **Tier:** `LV`
4. Save.

**Expected:** The item appears under the Machines category in the Items list.

---

## 4) Verify Machine Specs in Machine Details

**Goal:** Machine stats should resolve through metadata, not from per-item columns.

1. Open **Machines** tab.
2. Select the machine item (`Basic Lathe`) in the list.
3. Look at the **details panel** on the right.

**Expected:** You see machine stats (Input Slots, Output Slots, Tanks, etc.) matching the metadata entered in Step 2.

---

## 5) Add Fluids, Gases, and Fluid Containers

**Goal:** Validate items across Fluids/Gases tabs and container behavior.

1. Switch to the **Fluids** tab.
2. Add a **Fluid** item:
   - Display Name: `Water`
   - Kind: `fluid`
   - Save.
3. Switch to the **Gases** tab.
4. Add a **Gas** item:
   - Display Name: `Oxygen`
   - Kind: `gas`
   - Save.
5. Switch back to the **Items** tab.
6. Add a **Container** item:
   - Display Name: `Water Cell`
   - Kind: `item`
   - Check **Is Fluid Container?**
   - Set **Contains Fluid** = `Water`
   - Set **Amount (L)** = `1000`
   - Save.

**Expected:**
- The container item saves successfully.
- Re-opening the item shows the selected fluid and amount.
- The Fluids and Gases lists show the entries created.

---

## 6) Materials + Item Kinds (Tools Menu Coverage)

**Goal:** Verify materials and kinds can be managed and assigned to items before recipe creation.

1. Open **Tools → Manage Materials**.
2. Add a row:
   - **Name:** `Iron`
   - **Attributes:** (leave blank)
3. Save and close.
4. Open **Tools → Manage Item Kinds**.
5. Add a row:
   - **Name:** `component`
   - **Sort Order:** `10`
6. Save and close.
7. Open **Items** tab.
8. Add item:
   - Display Name: `Iron Ingot`
   - Kind: `item`
   - Check **Has Material?**
   - Select **Material** = `Iron`
   - Save.
9. Add item:
   - Display Name: `Iron Rod`
   - Kind: `item`
   - Check **Has Material?**
   - Select **Material** = `Iron`
   - Save.
10. Edit `Iron Rod` and set **Kind** = `component`.

**Expected:**
- The `Iron` material is available and assignable.
- The custom item kind appears in the Kind dropdown.
- Both items save with the selected material/kind.

---

## 7) Create a Simple Recipe (Machine)

**Goal:** Validate recipe creation with machine metadata-driven constraints.

1. Open **Recipes** tab → **Add Recipe**.
2. Recipe info:
   - **Name:** `Lathe Test`
   - **Method:** Machine
   - **Machine Item:** `Basic Lathe`
3. Add one input and one output:
   - Input: `Iron Ingot` × 1
   - Output: `Iron Rod` × 1
4. Save recipe.

**Expected:**
- Recipe saves.
- Output slots are determined by machine metadata.

---

## 8) Verify Recipe Detail Panel & Filters

**Goal:** Confirm UI reflects machine metadata and tier filters.

1. Select the `Lathe Test` recipe in the list.
2. Inspect details on the right.
3. Open **Tiers** tab and enable only low tiers (e.g., `LV`).
4. Return to **Recipes** and confirm filters update the list.

**Expected:**
- Machine line shows output slots derived from metadata (e.g., “output slots: 1”).
- Recipe list respects tier selection.

---

## 9) Set Machine Availability

**Goal:** Verify Owned/Online availability tracking.

1. Open **Machines** tab.
2. Double-click `Basic Lathe (LV)` in the list.
3. In the **Availability** dialog, set **Owned** to `1` and **Online** to `1`.
4. Click **Save**.

**Expected:**
- Owned/Online values persist after closing and reopening the app.

---

## 10) Inventory, Planner, & Build Mode Smoke Test

**Goal:** Ensure inventory and planner run end-to-end with the new schema.

**Populate inventory (also validates the Inventory tab)**
1. Open **Inventory** tab.
2. Find `Iron Ingot` and set its quantity to `1`.
3. Find `Iron Rod` and set its quantity to `0`.
4. Save/confirm the inventory update if prompted.

**Run the planner**
5. Open **Planner** tab.
6. Click **Select…** and choose `Iron Rod`.
7. Set quantity to `1`.
8. Click **Plan**.

**Run build mode**
9. Click **Build**.
10. Step through the build checklist, confirming steps auto-check when inventory allows it.

**Expected:**
- Shopping list and process steps appear without errors.
- Planner uses inventory quantities when **Use Inventory Data** is checked.
- Build steps show status updates and no errors.

---

## 11) Export, Quit, Move DB, Import, Merge (Full Use Path)

**Goal:** Validate DB portability and merging after real data entry.

1. **Export both DBs**
   - Use **File → Export Content DB…** and **File → Export Profile DB…** to a known folder.
2. **Quit the app** (File → Quit).
3. **Move databases**
   - Move `gtnh.db` and `profile.db` from the app folder to a different location.
4. **Restart the app**
   - **Expected:** The app starts with blank/new DBs.
5. **Import/Merge**
   - Use **File → Merge DB…** and select the exported content DB.
   - Re-open items, recipes, and inventory to confirm data is restored/merged.

**Expected:**
- Exported files are created and non-empty.
- The app starts cleanly after removing DBs.
- Merge/import restores items, recipes, and inventory without crashes or missing fields.

---

## 12) Failure Mode Checks (All UI Elements)

**Goal:** Confirm user-facing errors appear and prevent invalid saves or actions. Each failure should show a clear message and leave data unchanged.

### Items / Fluids / Gases
1. **Add Item — missing name**
   - Open **Add Item**, leave Display Name blank, click **Save**.
   - **Expected:** Warning dialog about missing name; item is not created.
2. **Add Item — invalid machine fields**
   - Set **Kind = machine** but leave Machine Type or Tier empty.
   - **Expected:** Validation error; item is not created.
3. **Fluid Container — missing fluid or amount**
   - Check **Is Fluid Container?** but leave fluid or amount empty.
   - **Expected:** Validation error; item is not created.

### Materials / Item Kinds (Tools)
4. **Materials — empty name**
   - Add a materials row with a blank name and try to save.
   - **Expected:** Error or validation prevents save.
5. **Item Kinds — empty name or invalid sort order**
   - Enter blank name or non-numeric sort order.
   - **Expected:** Validation prevents save or warns the user.

### Recipes
6. **Recipes — missing output item**
   - In **Add Recipe**, set a name but remove all outputs for that item.
   - **Expected:** Warning that outputs must include the selected item.
7. **Recipes — missing machine for method**
   - Choose **Method: Machine** without selecting a machine item.
   - **Expected:** Validation error and recipe not saved.

### Planner / Build Mode
8. **Planner — no target item**
   - Open **Planner** tab, click **Plan** without selecting an item.
   - **Expected:** “Choose a target item first” dialog.
9. **Planner — invalid quantity**
   - Select a target item but enter a non-integer or 0.
   - **Expected:** “Invalid quantity” dialog; plan does not run.
10. **Build — no plan**
    - Click **Build** without running Plan first.
    - **Expected:** Status bar message indicating build cannot start.

### Tiers
11. **Tiers — save with nothing selected**
    - Uncheck all tiers and click **Save**.
    - **Expected:** Error dialog: “Enable at least one tier.”

### Inventory
12. **Inventory — invalid quantity**
    - Enter a negative or non-numeric quantity and attempt to save.
    - **Expected:** Validation prevents save or warns the user.

### Machines
13. **Delete item referenced by a recipe**
    - Try deleting `Iron Ingot` (or any item in a recipe) from **Items**.
    - **Expected:** Error dialog saying it’s referenced by a recipe; item remains.
14. **Machine availability — invalid values**
    - Enter non-numeric or negative values for Owned/Online.
    - **Expected:** Validation error; values not saved.

### Tabs / UI Controls
15. **Tabs — disable all tabs**
    - Attempt to uncheck the final enabled tab.
    - **Expected:** Message warns that at least one tab must remain enabled.
16. **Detach tab with unsaved edits**
    - Edit a list entry, detach the tab, and confirm edits are preserved or clearly discarded.

### File Operations
17. **Open DB — wrong file type**
    - Choose a non-DB file in **File → Open DB…**.
    - **Expected:** Error dialog, no crash.
18. **Merge DB — invalid DB**
    - Try merging a DB missing required tables.
    - **Expected:** Error dialog, no crash.
19. **Export DB — read-only location**
    - Export to a folder without write permissions.
    - **Expected:** Error dialog and no crash.

---

## Pass/Fail Recording

For each section, record:
- **Pass/Fail**
- **Notes** (e.g., error messages, missing values, UI glitches)

---

## If Anything Fails

Capture:
- The exact step number
- Screenshot or exact error text
- Whether the app froze or recovered

---
