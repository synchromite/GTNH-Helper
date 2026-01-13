# QA Test Plan — GTNH Helper (Blank Database)

This document is a step-by-step QA checklist for validating the application when starting from a **blank database**. It is intended for testers with no prior experience using the app.

---

## 0) Environment & Setup

**Goal:** Ensure the app starts cleanly and dependencies are installed.

1. **Confirm requirements are installed**
   - Run:
     ```bash
     python -m pip install -r requirements.txt
     ```
   - **Expected:** Install succeeds without errors.

2. **Launch the app**
   - Run:
     ```bash
     python ui_main.py
     ```
   - **Expected:** App window opens with no error dialog.

---

## 1) Machine Metadata Baseline

**Goal:** Machine stats live in `machine_metadata`, so at least one machine definition must exist before machine items will show accurate stats.

1. Open **Machines** tab.
2. Click **Edit Metadata…**.
3. Add a row:
   - **Machine Type:** `Lathe`
   - **Tier:** `LV`
   - **Input Slots:** `1`
   - **Output Slots:** `1`
   - **Input Tanks:** `0`
   - **Output Tanks:** `0`
4. Save and close.

**Expected:** The metadata row is listed in the Machines tab and persists after closing/reopening the dialog.

---

## 2) Add a Machine Item

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

## 3) Verify Machine Specs in Item Details

**Goal:** Machine stats should resolve through metadata, not from per-item columns.

1. In **Items** tab, click the machine item (`Basic Lathe`).
2. Look at the **details panel** on the right.

**Expected:** You see machine stats (Input Slots, Output Slots, Tanks, etc.) matching the metadata entered in Step 1.

---

## 4) Add a Fluid + Container Item

**Goal:** Verify the fluid container group works on a blank database.

1. Add a **Fluid** item:
   - Display Name: `Water`
   - Kind: `fluid`
   - Save.
2. Add a **Container** item:
   - Display Name: `Water Cell`
   - Kind: `item`
   - Check **Is Fluid Container?**
   - Set **Contains Fluid** = `Water`
   - Set **Amount (L)** = `1000`
   - Save.

**Expected:**
- The container item saves successfully.
- Re-opening the item shows the selected fluid and amount.

---

## 5) Create a Simple Recipe (Machine)

**Goal:** Validate recipe creation with machine metadata-driven constraints.

1. Open **Recipes** tab → **Add Recipe**.
2. Recipe info:
   - **Name:** `Lathe Test`
   - **Method:** Machine
   - **Machine Item:** `Basic Lathe`
3. Add one input and one output (create new items if necessary):
   - Input: `Iron Ingot` × 1
   - Output: `Iron Rod` × 1
4. Save recipe.

**Expected:**
- Recipe saves.
- Output slots are determined by machine metadata.

---

## 6) Verify Recipe Detail Panel

**Goal:** Confirm UI reflects machine metadata.

1. Select the `Lathe Test` recipe in the list.
2. Inspect details on the right.

**Expected:**
- Machine line shows output slots derived from metadata (e.g., “output slots: 1”).

---

## 7) Set Machine Availability

**Goal:** Verify Owned/Online availability tracking.

1. Open **Machines** tab.
2. Find `Lathe / LV` row.
3. Check **Owned** and **Online**.
4. Click **Save**.

**Expected:**
- Owned/Online values persist after closing and reopening the app.

---

## 8) Planner Smoke Test

**Goal:** Ensure planner runs end-to-end with the new schema.

1. Open **Planner** tab.
2. Click **Select…** and choose `Iron Rod`.
3. Set quantity to `1`.
4. Click **Plan**.

**Expected:**
- Shopping list and process steps appear without errors.

---

## 9) Optional: Merge/Import Sanity

**Goal:** Confirm merge/import doesn’t crash when recipe lines include consumption chance.

1. Use any existing DB export with recipes and import/merge into the blank DB.
2. Confirm:
   - No crash during import.
   - Recipes and lines show after import.

**Expected:** Import completes successfully, no missing outputs.

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
