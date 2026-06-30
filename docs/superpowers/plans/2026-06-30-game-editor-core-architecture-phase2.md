# Game Editor Core Architecture Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Start syncing legacy game workbench edit actions into the new editor core state.

**Architecture:** Add a legacy sync adapter that owns all communication from `game_workbench.js` to `EditorState`. The adapter exposes `window.VC_GAME_EDITOR_SYNC` for the legacy script and internally dispatches the new command factories, preserving existing viewport/runtime behavior while making the core document observe character, selection, transform-mode, and whitebox-layer changes.

**Tech Stack:** Plain browser JavaScript ES modules, existing global Three.js workbench, Python static frontend guards, Node REPL import checks.

## Global Constraints

- Keep `game_workbench.js` as a classic script in this phase.
- Do not import ES modules from `game_workbench.js`.
- Sync through one global adapter: `window.VC_GAME_EDITOR_SYNC`.
- Existing legacy undo behavior remains unchanged in this phase.
- Do not commit generated run logs.

---

## File Structure

- Create `Scripts/app/area_picker/frontend/editor/legacy_sync.js`: builds sync methods around `EditorState` and command factories.
- Modify `Scripts/app/area_picker/frontend/editor/legacy_bridge.js`: install `window.VC_GAME_EDITOR_SYNC`.
- Modify `Scripts/app/area_picker/frontend/game_workbench.js`: call the sync adapter from selected edit mutation points.
- Modify `Scripts/app/area_picker/server.py`: include `legacy_sync.js` in frontend asset versioning.
- Modify `tests/test_area_picker.py`: add guard tests for the adapter and legacy call sites.

## Task 1: Add Failing Tests

**Files:**
- Modify: `tests/test_area_picker.py`

**Interfaces:**
- Produces tests requiring:
  - `editor/legacy_sync.js`
  - `window.VC_GAME_EDITOR_SYNC`
  - `sync.characterAdded`
  - `sync.characterDeleted`
  - `sync.selectionChanged`
  - `sync.transformModeChanged`
  - `sync.whiteboxImported`

- [ ] **Step 1: Add `editor/legacy_sync.js` to `_EDITOR_CORE_SCRIPT_NAMES`**

Add it after `editor/editor_app.js` and before `editor/legacy_bridge.js`.

- [ ] **Step 2: Add adapter contract test**

Assert `legacy_sync.js` imports command factories and exports `createLegacyWorkbenchSync`.

- [ ] **Step 3: Add legacy call-site test**

Assert `game_workbench.js` contains calls for character add/delete/select/transform mode and whitebox import.

- [ ] **Step 4: Run focused tests to verify RED**

Run:

```powershell
python -m pytest tests/test_area_picker.py::TestPickerHtml::test_game_editor_legacy_sync_adapter_contract tests/test_area_picker.py::TestPickerHtml::test_game_workbench_syncs_edit_actions_to_editor_core -q
```

Expected: fail because `legacy_sync.js` and the legacy call sites do not exist.

## Task 2: Implement Legacy Sync Adapter

**Files:**
- Create: `Scripts/app/area_picker/frontend/editor/legacy_sync.js`
- Modify: `Scripts/app/area_picker/frontend/editor/legacy_bridge.js`
- Modify: `Scripts/app/area_picker/server.py`

**Interfaces:**
- Produces `createLegacyWorkbenchSync(editorState)` returning:
  - `characterAdded(character)`
  - `characterDeleted(character)`
  - `selectionChanged(object)`
  - `transformModeChanged(mode)`
  - `whiteboxImported(layers)`

- [ ] **Step 1: Create adapter module**

Convert Three object snapshots to plain entities. Use object name or `userData.entityId` as the entity ID.

- [ ] **Step 2: Install global sync from bridge**

In `legacy_bridge.js`, import `createLegacyWorkbenchSync`, then set:

```javascript
window.VC_GAME_EDITOR_SYNC = createLegacyWorkbenchSync(app.getEditorState());
```

- [ ] **Step 3: Add asset fingerprint coverage**

Add `(FRONTEND_ROOT, "editor/legacy_sync.js")` to `_frontend_asset_version()`.

## Task 3: Wire Legacy Workbench Call Sites

**Files:**
- Modify: `Scripts/app/area_picker/frontend/game_workbench.js`

**Interfaces:**
- Consumes `window.VC_GAME_EDITOR_SYNC`.

- [ ] **Step 1: Add helper**

Add `editorSync()` and `syncEntityId(object)` helpers near the status helpers.

- [ ] **Step 2: Sync character add/delete**

Call `editorSync().characterAdded(character)` after character placement and `editorSync().characterDeleted(character)` before/after delete removes it.

- [ ] **Step 3: Sync selection and transform mode**

Call `editorSync().selectionChanged(selectedObject)` in `selectCharacter()` and `editorSync().transformModeChanged(mode)` in `setTransformMode()`.

- [ ] **Step 4: Sync whitebox import**

After `registerWhiteboxLayers(root)`, call `editorSync().whiteboxImported(whiteboxLayers)`.

## Task 4: Verify Phase 2

**Files:**
- Verify frontend tests, full tests, and Node import.

- [ ] **Step 1: Run focused tests**

Run the focused tests from Task 1. Expected: pass.

- [ ] **Step 2: Run frontend tests**

Run:

```powershell
python -m pytest tests/test_area_picker.py -q
```

Expected: pass.

- [ ] **Step 3: Run full tests**

Run:

```powershell
python -m pytest -q
```

Expected: pass.

- [ ] **Step 4: Import bridge with browser stubs**

Use Node REPL with a stub legacy workbench. Expected: `window.VC_GAME_EDITOR_SYNC.characterAdded` exists.
