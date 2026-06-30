# Game Editor Core Architecture Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the first working slice of the game editor core architecture without breaking the existing Three.js workbench.

**Architecture:** Add ES module editor internals under `Scripts/app/area_picker/frontend/editor/`, expose a compatibility bridge through `window.VC_GAME_WORKBENCH`, and keep the current `game_workbench.js` as the legacy implementation during migration. The new core owns `SceneDocument`, `EditorState`, and command primitives so later tasks can move viewport, runtime, and UI behavior one boundary at a time.

**Tech Stack:** Plain browser JavaScript ES modules, existing global Three.js workbench, Python `unittest`/`pytest` static frontend guards, Node REPL import check.

## Global Constraints

- Keep the current plain browser frontend and static script delivery.
- Use ES modules for editor internals.
- Keep `window.VC_GAME_WORKBENCH` as the public compatibility API used by `workspace.js`.
- Add a clear `SceneDocument`, command system, viewport adapter, runtime layer, and UI adapters.
- Avoid React, Vue, Vite, TypeScript, or a full frontend rebuild in this phase.
- Preserve current editor behavior while introducing the new core.
- Do not commit generated run logs.

---

## File Structure

- Create `Scripts/app/area_picker/frontend/editor/core/scene_document.js`: pure document helpers for entity lookup, selection, transform, add, delete, duplicate, and whitebox import.
- Create `Scripts/app/area_picker/frontend/editor/core/commands.js`: command constructors with `execute`, `undo`, and `changesDocument`.
- Create `Scripts/app/area_picker/frontend/editor/core/editor_state.js`: document store, subscriptions, dispatch, undo, redo, and editor mode helpers.
- Create `Scripts/app/area_picker/frontend/editor/editor_app.js`: owns the new core instance and delegates legacy runtime calls.
- Create `Scripts/app/area_picker/frontend/editor/legacy_bridge.js`: wraps the existing `window.VC_GAME_WORKBENCH` API after `game_workbench.js` loads.
- Modify `Scripts/app/area_picker/frontend/index.html`: load `legacy_bridge.js` as a module after `game_workbench.js`.
- Modify `Scripts/app/area_picker/server.py`: include the new editor module files in frontend asset versioning.
- Modify `tests/test_area_picker.py`: add focused guard tests for the module files, script order, public API compatibility, and core source contracts.
- Modify `Scripts/app/area_picker/frontend/README.md`: document the new editor core boundary.

## Task 1: Add Failing Frontend Core Boundary Tests

**Files:**
- Modify: `tests/test_area_picker.py`

**Interfaces:**
- Consumes: existing `FRONTEND_ROOT`, `_PICKER_INDEX_HTML`, and `_PICKER_SCRIPT_NAMES`.
- Produces: tests requiring `editor/core/scene_document.js`, `editor/core/commands.js`, `editor/core/editor_state.js`, `editor/editor_app.js`, `editor/legacy_bridge.js`, and script loading for `/area-picker/editor/legacy_bridge.js?v=__VERSION__`.

- [ ] **Step 1: Add editor module names to the test aggregation**

Add an `_EDITOR_CORE_SCRIPT_NAMES` tuple:

```python
_EDITOR_CORE_SCRIPT_NAMES = (
    "editor/core/scene_document.js",
    "editor/core/commands.js",
    "editor/core/editor_state.js",
    "editor/editor_app.js",
    "editor/legacy_bridge.js",
)
```

Update `_PICKER_FRONTEND` to include these files when they exist:

```python
_PICKER_FRONTEND = "\n".join(
    (FRONTEND_ROOT / name).read_text(encoding="utf-8")
    for name in _PICKER_SCRIPT_NAMES
)
```

Do not change `_PICKER_FRONTEND` in this task. The initial tests should fail because the files do not exist.

- [ ] **Step 2: Add module existence and contract test**

Add:

```python
    def test_game_editor_core_modules_exist_and_define_contracts(self):
        expected = {
            "editor/core/scene_document.js": (
                "export function createSceneDocument",
                "export function addEntity",
                "export function setSelection",
                "export function importWhiteboxLayers",
            ),
            "editor/core/commands.js": (
                "export function AddEntityCommand",
                "export function ImportWhiteboxCommand",
                "changesDocument: true",
            ),
            "editor/core/editor_state.js": (
                "export function createEditorState",
                "dispatch(command)",
                "undo()",
                "redo()",
            ),
            "editor/editor_app.js": (
                "export function createEditorApp",
                "getEditorState",
                "legacyWorkbench",
            ),
            "editor/legacy_bridge.js": (
                "import { createEditorApp } from './editor_app.js';",
                "window.VC_GAME_WORKBENCH",
                "window.VC_GAME_EDITOR_APP",
            ),
        }
        for rel_path, tokens in expected.items():
            source = (FRONTEND_ROOT / rel_path).read_text(encoding="utf-8")
            for token in tokens:
                self.assertIn(token, source)
```

- [ ] **Step 3: Add script order test**

Add:

```python
    def test_game_editor_legacy_bridge_loads_after_legacy_workbench(self):
        legacy_script = '/area-picker/game_workbench.js?v=__VERSION__'
        bridge_script = '/area-picker/editor/legacy_bridge.js?v=__VERSION__'
        self.assertIn(legacy_script, _PICKER_INDEX_HTML)
        self.assertIn(bridge_script, _PICKER_INDEX_HTML)
        self.assertLess(_PICKER_INDEX_HTML.index(legacy_script), _PICKER_INDEX_HTML.index(bridge_script))
        self.assertIn('type="module" src="/area-picker/editor/legacy_bridge.js?v=__VERSION__"', _PICKER_INDEX_HTML)
```

- [ ] **Step 4: Add asset version coverage**

Update the temporary-root asset version test file lists to include:

```python
"editor/core/scene_document.js",
"editor/core/commands.js",
"editor/core/editor_state.js",
"editor/editor_app.js",
"editor/legacy_bridge.js",
```

Create parent directories before writing nested files:

```python
path = root / name
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(f"v{i}-{name}", encoding="utf-8")
```

- [ ] **Step 5: Run tests to verify RED**

Run:

```powershell
python -m pytest tests/test_area_picker.py::TestPickerHtml::test_game_editor_core_modules_exist_and_define_contracts tests/test_area_picker.py::TestPickerHtml::test_game_editor_legacy_bridge_loads_after_legacy_workbench -q
```

Expected: fail because editor core module files and bridge script tag do not exist.

## Task 2: Implement SceneDocument, Commands, and EditorState

**Files:**
- Create: `Scripts/app/area_picker/frontend/editor/core/scene_document.js`
- Create: `Scripts/app/area_picker/frontend/editor/core/commands.js`
- Create: `Scripts/app/area_picker/frontend/editor/core/editor_state.js`

**Interfaces:**
- Produces:
  - `createSceneDocument(seed)`
  - `addEntity(document, entity)`
  - `deleteEntities(document, ids)`
  - `duplicateEntities(document, ids)`
  - `setSelection(document, ids)`
  - `setTransformMode(document, mode)`
  - `setEntityTransform(document, id, transform)`
  - `importWhiteboxLayers(document, layers)`
  - command factories named in Task 1
  - `createEditorState(initialDocument)`

- [ ] **Step 1: Add SceneDocument helper implementation**

Implement immutable document updates. Use arrays and plain objects only. Default document:

```javascript
{
  version: 1,
  entities: [],
  selection: { ids: [] },
  editor: { mode: 'edit', transformMode: 'translate', activeTool: 'select' }
}
```

- [ ] **Step 2: Add command factories**

Each command returns:

```javascript
{
  type: 'add-entity',
  changesDocument: true,
  execute: function(document) { return nextDocument; },
  undo: function(document) { return previousDocument; }
}
```

For undo, capture the previous document during `execute`.

- [ ] **Step 3: Add EditorState**

Expose:

```javascript
{
  getDocument,
  getSelection,
  getEditorMode,
  setEditorMode,
  dispatch,
  undo,
  redo,
  subscribe
}
```

Notify listeners with `{ document, command }` after successful document changes.

- [ ] **Step 4: Run focused tests**

Run the RED tests from Task 1. Expected: module contract test passes; script order test still fails until Task 3.

## Task 3: Add Compatibility Bridge and Static Loading

**Files:**
- Create: `Scripts/app/area_picker/frontend/editor/editor_app.js`
- Create: `Scripts/app/area_picker/frontend/editor/legacy_bridge.js`
- Modify: `Scripts/app/area_picker/frontend/index.html`
- Modify: `Scripts/app/area_picker/server.py`
- Modify: `Scripts/app/area_picker/frontend/README.md`

**Interfaces:**
- Consumes: legacy `window.VC_GAME_WORKBENCH`.
- Produces: wrapped `window.VC_GAME_WORKBENCH`, `window.VC_GAME_EDITOR_APP`, and `createEditorApp({ legacyWorkbench })`.

- [ ] **Step 1: Implement `createEditorApp`**

Create one `EditorState`, retain `legacyWorkbench`, and delegate:

```javascript
function init() { if (legacyWorkbench && legacyWorkbench.init) legacyWorkbench.init(); }
function resize() { if (legacyWorkbench && legacyWorkbench.resize) legacyWorkbench.resize(); }
function setActive(active) { if (legacyWorkbench && legacyWorkbench.setActive) legacyWorkbench.setActive(active); }
function loadGLB(url) { return legacyWorkbench && legacyWorkbench.loadGLB ? legacyWorkbench.loadGLB(url) : undefined; }
function syncFromHoudini() { return legacyWorkbench && legacyWorkbench.syncFromHoudini ? legacyWorkbench.syncFromHoudini() : undefined; }
```

- [ ] **Step 2: Implement `legacy_bridge.js`**

Capture the legacy workbench, create the app, expose both globals:

```javascript
var legacyWorkbench = window.VC_GAME_WORKBENCH || {};
var app = createEditorApp({ legacyWorkbench: legacyWorkbench });
window.VC_GAME_EDITOR_APP = app;
window.VC_GAME_WORKBENCH = app.getPublicApi();
```

- [ ] **Step 3: Load bridge after legacy workbench**

Add to `index.html` immediately after `game_workbench.js`:

```html
<script type="module" src="/area-picker/editor/legacy_bridge.js?v=__VERSION__"></script>
```

- [ ] **Step 4: Include new files in asset versioning**

Add each new editor module file to `_frontend_asset_version()` in `server.py`.

- [ ] **Step 5: Document the boundary**

Add a README entry explaining that `editor/` owns the new core while `game_workbench.js` remains the legacy viewport/runtime during migration.

## Task 4: Verify Phase 1

**Files:**
- Verify: frontend modules, tests, docs, and git diff.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
python -m pytest tests/test_area_picker.py::TestPickerHtml::test_game_editor_core_modules_exist_and_define_contracts tests/test_area_picker.py::TestPickerHtml::test_game_editor_legacy_bridge_loads_after_legacy_workbench -q
```

Expected: pass.

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

Use the Node REPL with browser stubs to import `legacy_bridge.js`. Expected: `window.VC_GAME_WORKBENCH`, `window.VC_GAME_EDITOR_APP`, and `window.VC_GAME_EDITOR_APP.getEditorState()` exist.

- [ ] **Step 5: Review diff**

Run:

```powershell
git diff -- Scripts/app/area_picker/frontend/index.html Scripts/app/area_picker/frontend/editor Scripts/app/area_picker/frontend/README.md Scripts/app/area_picker/server.py tests/test_area_picker.py docs/superpowers/plans/2026-06-30-game-editor-core-architecture-phase1.md
```

Expected: only Phase 1 editor core files, tests, asset versioning, README, and this plan changed.
