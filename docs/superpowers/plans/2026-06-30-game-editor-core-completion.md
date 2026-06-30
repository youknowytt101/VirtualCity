# Game Editor Core Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the editor core refactor so `SceneDocument` and command dispatch own edit state, while the existing WorldBuilder page and `window.VC_GAME_WORKBENCH` compatibility API keep working.

**Architecture:** Use incremental kernel extraction. Move the remaining `game_workbench.js` responsibilities into focused ES modules under `Scripts/app/area_picker/frontend/editor/`, then stop loading the legacy workbench as the editor kernel. Preserve static script delivery and browser globals for shared low-level services.

**Tech Stack:** Plain browser JavaScript ES modules, existing Three.js globals, existing `vc_glb.js` and `viewport_grid.js`, Python `pytest` static/frontend guard tests, Node REPL smoke checks.

## Global Constraints

- No scene save/load feature.
- No publishing feature.
- No backend route changes.
- No React, Vue, Vite, TypeScript, or frontend build pipeline migration.
- No visual redesign of the existing editor page.
- Preserve `window.VC_GAME_WORKBENCH.init`, `resize`, `setActive`, `loadGLB`, and `syncFromHoudini`.
- `SceneDocument` is the only authoritative source for edit entities, selection, transform mode, and edit/play mode.
- Every document edit flows through command dispatch.
- Three.js objects are render/runtime projections of document entities, not the source of identity or edit state.
- Keep generated logs out of commits.

---

## File Structure

- Create `Scripts/app/area_picker/frontend/editor/core/ids.js`: stable entity ID allocation.
- Create `Scripts/app/area_picker/frontend/editor/core/entity_factories.js`: plain character and whitebox entity factories.
- Modify `Scripts/app/area_picker/frontend/editor/core/scene_document.js`: normalize new entity fields and editor mode command support.
- Modify `Scripts/app/area_picker/frontend/editor/core/commands.js`: add `SetEditorModeCommand` and tighten transform/selection command behavior.
- Modify `Scripts/app/area_picker/frontend/editor/core/editor_state.js`: keep undo/redo as the only document undo path.
- Create `Scripts/app/area_picker/frontend/editor/viewport/three_viewport.js`: Three scene, camera, renderer, lights, grid, resize, render loop, and entity object map.
- Create `Scripts/app/area_picker/frontend/editor/viewport/viewport_controls.js`: editor camera movement.
- Create `Scripts/app/area_picker/frontend/editor/viewport/transform_gizmo.js`: TransformControls wrapper and transform command emission.
- Create `Scripts/app/area_picker/frontend/editor/viewport/picking.js`: raycast picking and placement helpers.
- Create `Scripts/app/area_picker/frontend/editor/assets/asset_registry.js`: asset reference constants and labels.
- Create `Scripts/app/area_picker/frontend/editor/assets/glb_importer.js`: whitebox GLB loading and layer entity extraction.
- Create `Scripts/app/area_picker/frontend/editor/assets/houdini_bridge.js`: Houdini preview URL adapter.
- Create `Scripts/app/area_picker/frontend/editor/runtime/character_collision.js`: capsule collision and whitebox walkability helpers.
- Create `Scripts/app/area_picker/frontend/editor/runtime/play_mode.js`: edit/play mode runtime controller.
- Create `Scripts/app/area_picker/frontend/editor/ui/status_bar.js`: status text adapter.
- Create `Scripts/app/area_picker/frontend/editor/ui/scene_outline.js`: scene outline adapter.
- Create `Scripts/app/area_picker/frontend/editor/ui/toolbar.js`: toolbar drag/drop and run/transform controls.
- Create `Scripts/app/area_picker/frontend/editor/ui/shortcuts.js`: keyboard shortcut routing.
- Create `Scripts/app/area_picker/frontend/editor/ui/side_panel_resize.js`: game side panel resize behavior.
- Modify `Scripts/app/area_picker/frontend/editor/editor_app.js`: compose all editor modules and expose the compatibility API.
- Modify `Scripts/app/area_picker/frontend/editor/legacy_bridge.js`: become the module-backed editor entry instead of wrapping the legacy workbench.
- Modify `Scripts/app/area_picker/frontend/index.html`: stop loading `game_workbench.js` as the editor kernel and load the module-backed bridge.
- Modify `Scripts/app/area_picker/server.py`: include all new editor modules in asset versioning.
- Modify `Scripts/app/area_picker/frontend/README.md`: document the completed editor module ownership.
- Modify `tests/test_area_picker.py`: add completion guard tests, module contract tests, and source-boundary tests.

## Task 1: Complete Core Data Model and Commands

**Files:**
- Create: `Scripts/app/area_picker/frontend/editor/core/ids.js`
- Create: `Scripts/app/area_picker/frontend/editor/core/entity_factories.js`
- Modify: `Scripts/app/area_picker/frontend/editor/core/scene_document.js`
- Modify: `Scripts/app/area_picker/frontend/editor/core/commands.js`
- Modify: `Scripts/app/area_picker/frontend/editor/core/editor_state.js`
- Modify: `tests/test_area_picker.py`

**Interfaces:**
- Produces `createIdAllocator(seedIds)` with `next(prefix)`.
- Produces `createCharacterEntity(options)`.
- Produces `createWhiteboxLayerEntity(options)`.
- Produces `SetEditorModeCommand(mode)`.
- Keeps `createEditorState(initialDocument).dispatch(command)` as the only document mutation API.

- [ ] **Step 1: Write failing module contract tests**

Add `editor/core/ids.js` and `editor/core/entity_factories.js` to `_EDITOR_CORE_SCRIPT_NAMES`.

Add `test_game_editor_core_completion_modules_exist_and_define_contracts` near the existing editor core tests. Assert these source tokens:

```python
expected = {
    "editor/core/ids.js": (
        "export function createIdAllocator",
        "next: next",
    ),
    "editor/core/entity_factories.js": (
        "export function createCharacterEntity",
        "export function createWhiteboxLayerEntity",
        "assetRef: 'builtin:character'",
        "type: 'whiteboxLayer'",
    ),
    "editor/core/commands.js": (
        "export function SetEditorModeCommand",
        "setEditorMode(document, mode)",
    ),
}
```

- [ ] **Step 2: Write failing source-boundary tests**

Add `test_game_editor_core_owns_document_mutation_contract`. Assert:

```python
commands_js = (FRONTEND_ROOT / "editor" / "core" / "commands.js").read_text(encoding="utf-8")
editor_state_js = (FRONTEND_ROOT / "editor" / "core" / "editor_state.js").read_text(encoding="utf-8")
self.assertIn("SetEditorModeCommand", commands_js)
self.assertIn("undoStack", editor_state_js)
self.assertIn("redoStack", editor_state_js)
self.assertNotIn("window.", editor_state_js)
self.assertNotIn("document.", editor_state_js)
```

- [ ] **Step 3: Verify RED**

Run:

```powershell
python -m pytest tests/test_area_picker.py::TestPickerHtml::test_game_editor_core_completion_modules_exist_and_define_contracts tests/test_area_picker.py::TestPickerHtml::test_game_editor_core_owns_document_mutation_contract -q
```

Expected: fail because `ids.js`, `entity_factories.js`, and `SetEditorModeCommand` do not exist.

- [ ] **Step 4: Implement `ids.js`**

Create `ids.js` with:

```javascript
// Domain: game-editor-ids
// Owns: stable entity id allocation for editor documents.

export function createIdAllocator(seedIds) {
  var seen = {};
  (seedIds || []).forEach(function(id) {
    if (typeof id === 'string' && id) seen[id] = true;
  });

  function next(prefix) {
    var base = String(prefix || 'entity').replace(/[^a-zA-Z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'entity';
    var index = 1;
    var candidate = base + '-' + String(index).padStart(2, '0');
    while (seen[candidate]) {
      index += 1;
      candidate = base + '-' + String(index).padStart(2, '0');
    }
    seen[candidate] = true;
    return candidate;
  }

  return {
    next: next
  };
}
```

- [ ] **Step 5: Implement `entity_factories.js`**

Create factories that return plain objects only. Use these exact exported names:

- `export function createCharacterEntity(options)`
- `export function createWhiteboxLayerEntity(options)`

`createCharacterEntity` must produce:

```javascript
{
  id: id,
  type: 'character',
  name: name,
  assetRef: 'builtin:character',
  transform: {
    position: [x, y, z],
    rotation: [rx, ry, rz],
    scale: [sx, sy, sz]
  },
  collider: {
    type: 'capsule',
    radius: 0.36,
    height: 1.76,
    skinWidth: 0.04,
    stepHeight: 0.45,
    walkableSlopeDegrees: 60
  }
}
```

`createWhiteboxLayerEntity` must produce `type: 'whiteboxLayer'`, `assetRef: 'houdini:whitebox.glb#' + key`, and collision `{ enabled: true, role: 'walkable', shape: 'triangle-mesh' }`.

- [ ] **Step 6: Add `SetEditorModeCommand`**

In `commands.js`, import `setEditorMode` and export:

```javascript
export function SetEditorModeCommand(mode) {
  return createDocumentCommand('set-editor-mode', function(document) {
    return setEditorMode(document, mode);
  });
}
```

- [ ] **Step 7: Run focused GREEN**

Run the command from Step 3. Expected: pass.

- [ ] **Step 8: Run frontend tests**

Run:

```powershell
python -m pytest tests/test_area_picker.py -q
```

Expected: pass.

- [ ] **Step 9: Commit Task 1**

```powershell
git add Scripts/app/area_picker/frontend/editor/core/ids.js Scripts/app/area_picker/frontend/editor/core/entity_factories.js Scripts/app/area_picker/frontend/editor/core/scene_document.js Scripts/app/area_picker/frontend/editor/core/commands.js Scripts/app/area_picker/frontend/editor/core/editor_state.js tests/test_area_picker.py
git commit -m "feat(editor): complete core document commands"
```

## Task 2: Extract Three Viewport Kernel

**Files:**
- Create: `Scripts/app/area_picker/frontend/editor/viewport/three_viewport.js`
- Modify: `Scripts/app/area_picker/frontend/editor/editor_app.js`
- Modify: `Scripts/app/area_picker/server.py`
- Modify: `tests/test_area_picker.py`

**Interfaces:**
- Produces `createThreeViewport(options)`.
- Consumes `editorState`, `statusBar`, `window.THREE`, and `window.VC_VIEWPORT_GRID`.
- Produces a viewport object with `init(host)`, `resize()`, `setActive(active)`, `render()`, `sync(document)`, `getObjectByEntityId(id)`, `getCollisionMeshes()`, and `dispose()`.

- [ ] **Step 1: Write failing viewport contract test**

Add `editor/viewport/three_viewport.js` to `_EDITOR_CORE_SCRIPT_NAMES`.

Add `test_game_editor_three_viewport_module_contract`:

```python
viewport_js = (FRONTEND_ROOT / "editor" / "viewport" / "three_viewport.js").read_text(encoding="utf-8")
self.assertIn("export function createThreeViewport", viewport_js)
self.assertIn("init: init", viewport_js)
self.assertIn("resize: resize", viewport_js)
self.assertIn("sync: sync", viewport_js)
self.assertIn("getObjectByEntityId: getObjectByEntityId", viewport_js)
self.assertIn("getCollisionMeshes: getCollisionMeshes", viewport_js)
self.assertIn("window.VC_VIEWPORT_GRID.create", viewport_js)
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m pytest tests/test_area_picker.py::TestPickerHtml::test_game_editor_three_viewport_module_contract -q
```

Expected: fail because `three_viewport.js` does not exist.

- [ ] **Step 3: Implement `three_viewport.js`**

Move these responsibilities from `game_workbench.js` into `three_viewport.js`:

- `safeThree`
- toon material helpers
- character mesh construction
- outline mesh creation and selection highlight
- `createGrid`
- `updateEditorGrid`
- `createGround`
- scene, renderer, camera, lights, clock, render loop
- `registerWhiteboxLayers` render-resource tagging
- `fitSunShadow`
- resize and active render loop control

The module must reconcile from `SceneDocument.entities`. Character entities create built-in character objects. Whitebox layer entities use render metadata supplied by the asset importer in Task 4; until Task 4 lands, keep support for imported root objects passed through `setWhiteboxRoot(root, layers)`.

- [ ] **Step 4: Wire viewport into `editor_app.js` without removing legacy workbench yet**

Instantiate the viewport when `init()` runs. Keep delegating to the legacy workbench until Task 6, but expose the viewport through `app.getViewport()` for later tasks.

- [ ] **Step 5: Add asset version coverage**

Add `(FRONTEND_ROOT, "editor/viewport/three_viewport.js")` to `_frontend_asset_version()`.

- [ ] **Step 6: Run focused GREEN**

Run the command from Step 2. Expected: pass.

- [ ] **Step 7: Run frontend tests**

Run:

```powershell
python -m pytest tests/test_area_picker.py -q
```

Expected: pass.

- [ ] **Step 8: Commit Task 2**

```powershell
git add Scripts/app/area_picker/frontend/editor/viewport/three_viewport.js Scripts/app/area_picker/frontend/editor/editor_app.js Scripts/app/area_picker/server.py tests/test_area_picker.py
git commit -m "feat(editor): extract three viewport kernel"
```

## Task 3: Extract Viewport Controls, Picking, and Transform Gizmo

**Files:**
- Create: `Scripts/app/area_picker/frontend/editor/viewport/viewport_controls.js`
- Create: `Scripts/app/area_picker/frontend/editor/viewport/picking.js`
- Create: `Scripts/app/area_picker/frontend/editor/viewport/transform_gizmo.js`
- Modify: `Scripts/app/area_picker/frontend/editor/editor_app.js`
- Modify: `Scripts/app/area_picker/server.py`
- Modify: `tests/test_area_picker.py`

**Interfaces:**
- Produces `createViewportControls(options)`.
- Produces `createPickingService(options)`.
- Produces `createTransformGizmo(options)`.
- Picking returns `{ entityId, point, object }` or `null`.
- Transform gizmo dispatches `TransformEntityCommand(entityId, transform)` after edits.

- [ ] **Step 1: Write failing module contract tests**

Add all three viewport module paths to `_EDITOR_CORE_SCRIPT_NAMES`.

Add `test_game_editor_viewport_interaction_modules_define_contracts`:

```python
expected = {
    "editor/viewport/viewport_controls.js": (
        "export function createViewportControls",
        "handlePointerDown: handlePointerDown",
        "handlePointerMove: handlePointerMove",
        "handlePointerUp: handlePointerUp",
        "update: update",
    ),
    "editor/viewport/picking.js": (
        "export function createPickingService",
        "pickEntity: pickEntity",
        "screenToGround: screenToGround",
        "screenToWhiteboxSurface: screenToWhiteboxSurface",
    ),
    "editor/viewport/transform_gizmo.js": (
        "export function createTransformGizmo",
        "TransformEntityCommand",
        "setMode: setMode",
        "attachSelection: attachSelection",
    ),
}
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m pytest tests/test_area_picker.py::TestPickerHtml::test_game_editor_viewport_interaction_modules_define_contracts -q
```

Expected: fail because the three modules do not exist.

- [ ] **Step 3: Implement `viewport_controls.js`**

Move camera look, pan, orbit, dolly, speed input, and camera update behavior from `createGameCameraController()` into `createViewportControls(options)`.

The returned object must expose:

```javascript
{
  setMoveSpeed,
  adjustMoveSpeed,
  syncRotationFromCamera,
  handlePointerDown,
  handlePointerMove,
  handlePointerUp,
  isLooking,
  pressKey,
  releaseKey,
  clearState,
  update
}
```

- [ ] **Step 4: Implement `picking.js`**

Move ground raycast, whitebox surface snapping, walkable hit filtering, footprint probing, and entity picking helpers into `createPickingService(options)`.

The service must not call `editorState.dispatch`. It returns data to `editor_app.js`, which dispatches commands.

- [ ] **Step 5: Implement `transform_gizmo.js`**

Wrap dynamic import of `/static/three/TransformControls.js`. Attach by selected entity ID using `viewport.getObjectByEntityId(id)`. Dispatch `TransformEntityCommand` when TransformControls fires a completed edit signal. Keep `isActive()` for picking suppression.

- [ ] **Step 6: Wire modules into `editor_app.js`**

Use picking and transform gizmo for selection and transform mode. Keep old workbench delegation active until Task 6, but new modules must be importable and wired behind `app.getViewportControls()`, `app.getPicking()`, and `app.getTransformGizmo()`.

- [ ] **Step 7: Add asset version coverage**

Add the three module files to `_frontend_asset_version()`.

- [ ] **Step 8: Run focused GREEN**

Run the command from Step 2. Expected: pass.

- [ ] **Step 9: Run frontend tests**

Run:

```powershell
python -m pytest tests/test_area_picker.py -q
```

Expected: pass.

- [ ] **Step 10: Commit Task 3**

```powershell
git add Scripts/app/area_picker/frontend/editor/viewport/viewport_controls.js Scripts/app/area_picker/frontend/editor/viewport/picking.js Scripts/app/area_picker/frontend/editor/viewport/transform_gizmo.js Scripts/app/area_picker/frontend/editor/editor_app.js Scripts/app/area_picker/server.py tests/test_area_picker.py
git commit -m "feat(editor): extract viewport interactions"
```

## Task 4: Extract Whitebox Asset Import

**Files:**
- Create: `Scripts/app/area_picker/frontend/editor/assets/asset_registry.js`
- Create: `Scripts/app/area_picker/frontend/editor/assets/glb_importer.js`
- Create: `Scripts/app/area_picker/frontend/editor/assets/houdini_bridge.js`
- Modify: `Scripts/app/area_picker/frontend/editor/editor_app.js`
- Modify: `Scripts/app/area_picker/server.py`
- Modify: `tests/test_area_picker.py`

**Interfaces:**
- Produces `WHITEBOX_LAYER_DEFS`.
- Produces `loadWhiteboxGLB(url, services)`.
- Produces `getLatestWhiteboxUrl(houdiniPreview)`.
- `loadWhiteboxGLB` returns `{ root, layers }`, where `layers` are plain whitebox entities with render metadata sufficient for `three_viewport`.

- [ ] **Step 1: Write failing asset module tests**

Add asset module paths to `_EDITOR_CORE_SCRIPT_NAMES`.

Add `test_game_editor_asset_modules_define_contracts`:

```python
expected = {
    "editor/assets/asset_registry.js": (
        "export var WHITEBOX_LAYER_DEFS",
        "houdini:whitebox.glb#terrain",
        "houdini:whitebox.glb#buildings",
        "houdini:whitebox.glb#roads",
    ),
    "editor/assets/glb_importer.js": (
        "export function loadWhiteboxGLB",
        "window.VC_GLB.load",
        "createWhiteboxLayerEntity",
    ),
    "editor/assets/houdini_bridge.js": (
        "export function getLatestWhiteboxUrl",
        "VC_HOUDINI_PREVIEW",
    ),
}
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m pytest tests/test_area_picker.py::TestPickerHtml::test_game_editor_asset_modules_define_contracts -q
```

Expected: fail because asset modules do not exist.

- [ ] **Step 3: Implement asset registry**

Define terrain, buildings, and roads labels, keys, asset refs, collision role, and shadow behavior in `WHITEBOX_LAYER_DEFS`.

- [ ] **Step 4: Implement GLB importer**

Move whitebox layer traversal, material cloning, shadow tagging, and layer entity creation out of `game_workbench.js`.

On failure, reject without dispatching `ImportWhiteboxCommand`.

- [ ] **Step 5: Implement Houdini bridge**

Return `(window.VC_HOUDINI_PREVIEW.getWhitebox() || {}).url` when available. Fallback to `'/whitebox.glb?t=' + Date.now()` to preserve current behavior.

- [ ] **Step 6: Wire `loadGLB` and `syncFromHoudini` through `editor_app.js`**

`loadGLB(url)` must:

1. Call `loadWhiteboxGLB(url, services)`.
2. Dispatch `ImportWhiteboxCommand(layers)`.
3. Pass imported render root/layers to `viewport`.
4. Show success or failure through `status_bar`.

- [ ] **Step 7: Add asset version coverage**

Add the three asset module files to `_frontend_asset_version()`.

- [ ] **Step 8: Run focused GREEN**

Run the command from Step 2. Expected: pass.

- [ ] **Step 9: Run frontend tests**

Run:

```powershell
python -m pytest tests/test_area_picker.py -q
```

Expected: pass.

- [ ] **Step 10: Commit Task 4**

```powershell
git add Scripts/app/area_picker/frontend/editor/assets/asset_registry.js Scripts/app/area_picker/frontend/editor/assets/glb_importer.js Scripts/app/area_picker/frontend/editor/assets/houdini_bridge.js Scripts/app/area_picker/frontend/editor/editor_app.js Scripts/app/area_picker/server.py tests/test_area_picker.py
git commit -m "feat(editor): extract whitebox asset import"
```

## Task 5: Extract Runtime Play Mode and Collision

**Files:**
- Create: `Scripts/app/area_picker/frontend/editor/runtime/character_collision.js`
- Create: `Scripts/app/area_picker/frontend/editor/runtime/play_mode.js`
- Modify: `Scripts/app/area_picker/frontend/editor/editor_app.js`
- Modify: `Scripts/app/area_picker/server.py`
- Modify: `tests/test_area_picker.py`

**Interfaces:**
- Produces `createCharacterCollision(options)`.
- Produces `createPlayModeController(options)`.
- Play mode consumes `editorState`, `viewport`, `collision`, `statusBar`, and `onChange`.

- [ ] **Step 1: Write failing runtime module tests**

Add runtime module paths to `_EDITOR_CORE_SCRIPT_NAMES`.

Add `test_game_editor_runtime_modules_define_contracts`:

```python
expected = {
    "editor/runtime/character_collision.js": (
        "export function createCharacterCollision",
        "snapPointToWhiteboxSurface",
        "resolveCharacterWhiteboxCollision",
        "walkableSlopeDegrees",
    ),
    "editor/runtime/play_mode.js": (
        "export function createPlayModeController",
        "enter: enter",
        "exit: exit",
        "update: update",
        "SetEditorModeCommand",
    ),
}
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m pytest tests/test_area_picker.py::TestPickerHtml::test_game_editor_runtime_modules_define_contracts -q
```

Expected: fail because runtime modules do not exist.

- [ ] **Step 3: Implement `character_collision.js`**

Move default collider constants, walkable hit checks, footprint probes, whitebox snapping, and movement blocking from `game_workbench.js`.

The module must read collision meshes from `viewport.getCollisionMeshes()` and must not read DOM nodes.

- [ ] **Step 4: Implement `play_mode.js`**

Move runtime enter/exit, pointer lock, WASD input, player movement, runtime camera, and animation update from `createPlayModeController()`.

Entering play mode dispatches `SetEditorModeCommand('play')`. Exiting dispatches `SetEditorModeCommand('edit')`. Runtime motion mutates viewport objects only.

- [ ] **Step 5: Wire runtime into `editor_app.js`**

`toggleRun()` becomes an app method. Toolbar and shortcuts call the app method instead of legacy functions.

- [ ] **Step 6: Add asset version coverage**

Add the two runtime module files to `_frontend_asset_version()`.

- [ ] **Step 7: Run focused GREEN**

Run the command from Step 2. Expected: pass.

- [ ] **Step 8: Run frontend tests**

Run:

```powershell
python -m pytest tests/test_area_picker.py -q
```

Expected: pass.

- [ ] **Step 9: Commit Task 5**

```powershell
git add Scripts/app/area_picker/frontend/editor/runtime/character_collision.js Scripts/app/area_picker/frontend/editor/runtime/play_mode.js Scripts/app/area_picker/frontend/editor/editor_app.js Scripts/app/area_picker/server.py tests/test_area_picker.py
git commit -m "feat(editor): extract play mode runtime"
```

## Task 6: Extract Editor UI Adapters

**Files:**
- Create: `Scripts/app/area_picker/frontend/editor/ui/status_bar.js`
- Create: `Scripts/app/area_picker/frontend/editor/ui/scene_outline.js`
- Create: `Scripts/app/area_picker/frontend/editor/ui/toolbar.js`
- Create: `Scripts/app/area_picker/frontend/editor/ui/shortcuts.js`
- Create: `Scripts/app/area_picker/frontend/editor/ui/side_panel_resize.js`
- Modify: `Scripts/app/area_picker/frontend/editor/editor_app.js`
- Modify: `Scripts/app/area_picker/server.py`
- Modify: `tests/test_area_picker.py`

**Interfaces:**
- Produces `createStatusBar(options)`.
- Produces `createSceneOutline(options)`.
- Produces `createToolbar(options)`.
- Produces `createShortcutController(options)`.
- Produces `createSidePanelResize(options)`.

- [ ] **Step 1: Write failing UI module tests**

Add UI module paths to `_EDITOR_CORE_SCRIPT_NAMES`.

Add `test_game_editor_ui_modules_define_contracts`:

```python
expected = {
    "editor/ui/status_bar.js": (
        "export function createStatusBar",
        "setStatus: setStatus",
    ),
    "editor/ui/scene_outline.js": (
        "export function createSceneOutline",
        "SetSelectionCommand",
        "render: render",
    ),
    "editor/ui/toolbar.js": (
        "export function createToolbar",
        "AddEntityCommand",
        "SetTransformModeCommand",
        "bind: bind",
    ),
    "editor/ui/shortcuts.js": (
        "export function createShortcutController",
        "DuplicateSelectionCommand",
        "DeleteSelectionCommand",
        "handleKeyDown: handleKeyDown",
    ),
    "editor/ui/side_panel_resize.js": (
        "export function createSidePanelResize",
        "setHeight: setHeight",
    ),
}
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m pytest tests/test_area_picker.py::TestPickerHtml::test_game_editor_ui_modules_define_contracts -q
```

Expected: fail because UI modules do not exist.

- [ ] **Step 3: Implement `status_bar.js`**

Move status text updates out of `game_workbench.js`. The module must handle a missing status element by keeping the last message in memory.

- [ ] **Step 4: Implement `scene_outline.js`**

Render `document.entities` with whitebox layers before characters to preserve current ordering. Clicking a row dispatches `SetSelectionCommand([entity.id])`.

- [ ] **Step 5: Implement `toolbar.js`**

Move asset drag/drop, run button, move speed input, and transform mode buttons. Character drops dispatch `AddEntityCommand(createCharacterEntity({ id, name, position }))` and rely on viewport sync to render the object.

- [ ] **Step 6: Implement `shortcuts.js`**

Move W/E/R transform shortcuts, Space run toggle, Ctrl/Cmd+Z undo, Ctrl/Cmd+D duplicate, Delete/Backspace delete, F focus, and viewport movement key routing.

- [ ] **Step 7: Implement `side_panel_resize.js`**

Move game outline panel resizing. Keep existing CSS variable `--game-outline-height`.

- [ ] **Step 8: Wire UI modules into `editor_app.js`**

`editor_app.js` owns module lifecycle:

```javascript
init()
  -> create status bar
  -> create viewport
  -> create picking/controls/gizmo
  -> create runtime
  -> bind toolbar, outline, shortcuts, side panel resize
```

- [ ] **Step 9: Add asset version coverage**

Add all five UI module files to `_frontend_asset_version()`.

- [ ] **Step 10: Run focused GREEN**

Run the command from Step 2. Expected: pass.

- [ ] **Step 11: Run frontend tests**

Run:

```powershell
python -m pytest tests/test_area_picker.py -q
```

Expected: pass.

- [ ] **Step 12: Commit Task 6**

```powershell
git add Scripts/app/area_picker/frontend/editor/ui/status_bar.js Scripts/app/area_picker/frontend/editor/ui/scene_outline.js Scripts/app/area_picker/frontend/editor/ui/toolbar.js Scripts/app/area_picker/frontend/editor/ui/shortcuts.js Scripts/app/area_picker/frontend/editor/ui/side_panel_resize.js Scripts/app/area_picker/frontend/editor/editor_app.js Scripts/app/area_picker/server.py tests/test_area_picker.py
git commit -m "feat(editor): extract editor ui adapters"
```

## Task 7: Remove Legacy Workbench as the Editor Kernel

**Files:**
- Modify: `Scripts/app/area_picker/frontend/index.html`
- Modify: `Scripts/app/area_picker/frontend/editor/legacy_bridge.js`
- Modify: `Scripts/app/area_picker/frontend/game_workbench.js`
- Modify: `Scripts/app/area_picker/frontend/README.md`
- Modify: `Scripts/app/area_picker/server.py`
- Modify: `tests/test_area_picker.py`

**Interfaces:**
- `legacy_bridge.js` sets `window.VC_GAME_WORKBENCH = app.getPublicApi()` without first reading a legacy workbench.
- `index.html` no longer loads `/area-picker/game_workbench.js?v=__VERSION__` for the game editor kernel.
- `game_workbench.js` is reduced to a compatibility note or deleted from the page's script list.

- [ ] **Step 1: Write failing legacy-removal tests**

Add `test_game_editor_no_longer_loads_legacy_workbench_kernel`:

```python
self.assertNotIn('/area-picker/game_workbench.js?v=__VERSION__', _PICKER_INDEX_HTML)
self.assertIn('type="module" src="/area-picker/editor/legacy_bridge.js?v=__VERSION__"', _PICKER_INDEX_HTML)
```

Add `test_game_editor_legacy_workbench_no_longer_owns_core_state`:

```python
game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
for token in (
    "var characters = []",
    "var whiteboxLayers = []",
    "var selectedObject = null",
    "var undoStack = []",
    "function createPlayModeController",
    "function createGameCameraController",
    "function registerWhiteboxLayers",
):
    self.assertNotIn(token, game_js)
```

Add `test_game_editor_module_entry_exposes_compatibility_api`:

```python
bridge_js = (FRONTEND_ROOT / "editor" / "legacy_bridge.js").read_text(encoding="utf-8")
self.assertIn("window.VC_GAME_WORKBENCH = app.getPublicApi();", bridge_js)
self.assertNotIn("var legacyWorkbench = window.VC_GAME_WORKBENCH || {}", bridge_js)
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m pytest tests/test_area_picker.py::TestPickerHtml::test_game_editor_no_longer_loads_legacy_workbench_kernel tests/test_area_picker.py::TestPickerHtml::test_game_editor_legacy_workbench_no_longer_owns_core_state tests/test_area_picker.py::TestPickerHtml::test_game_editor_module_entry_exposes_compatibility_api -q
```

Expected: fail because `index.html` still loads `game_workbench.js` and `legacy_bridge.js` still wraps the legacy workbench.

- [ ] **Step 3: Convert `legacy_bridge.js` to module-backed entry**

Remove legacy capture. Keep:

```javascript
import { createEditorApp } from './editor_app.js';

var app = createEditorApp();

window.VC_GAME_EDITOR_APP = app;
window.VC_GAME_WORKBENCH = app.getPublicApi();
```

- [ ] **Step 4: Stop loading `game_workbench.js` from `index.html`**

Remove:

```html
<script src="/area-picker/game_workbench.js?v=__VERSION__"></script>
```

Keep the module bridge script before scripts that call `window.VC_GAME_WORKBENCH`.

- [ ] **Step 5: Reduce `game_workbench.js`**

Replace the large legacy kernel with a small compatibility file that contains no editor-owned state:

```javascript
// Domain: legacy-game-workbench-removed
// Owns: compatibility note only. The game editor kernel lives in editor/.
(function() {
  'use strict';
  window.VC_LEGACY_GAME_WORKBENCH_REMOVED = true;
})();
```

Keep the file present to avoid broken direct requests during cache rollout.

- [ ] **Step 6: Update asset versioning and README**

Remove `game_workbench.js` from frontend asset versioning if it is no longer loaded by `index.html`. Document that `editor/legacy_bridge.js` owns the public compatibility API.

- [ ] **Step 7: Run focused GREEN**

Run the command from Step 2. Expected: pass.

- [ ] **Step 8: Run frontend tests**

Run:

```powershell
python -m pytest tests/test_area_picker.py -q
```

Expected: pass.

- [ ] **Step 9: Commit Task 7**

```powershell
git add Scripts/app/area_picker/frontend/index.html Scripts/app/area_picker/frontend/editor/legacy_bridge.js Scripts/app/area_picker/frontend/game_workbench.js Scripts/app/area_picker/frontend/README.md Scripts/app/area_picker/server.py tests/test_area_picker.py
git commit -m "feat(editor): remove legacy workbench kernel"
```

## Task 8: Final Verification and Browser Smoke

**Files:**
- Verify: all editor modules, frontend tests, full tests, and browser/module smoke checks.

- [ ] **Step 1: Run full test suite**

Run:

```powershell
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Import module entry with Node REPL**

Use Node REPL to import:

```javascript
C:/Users/YT/Documents/VirtualCity/Scripts/app/area_picker/frontend/editor/legacy_bridge.js
```

Stub:

```javascript
globalThis.window = {
  THREE: {},
  VC_VIEWPORT_GRID: { create() {}, update() {} },
  VC_GLB: { load() { return Promise.reject(new Error('stub')); } },
  VC_HOUDINI_PREVIEW: { getWhitebox() { return { url: '/whitebox.glb' }; } }
};
globalThis.document = {
  readyState: 'complete',
  getElementById() { return null; },
  addEventListener() {},
  querySelector() { return null; },
  querySelectorAll() { return []; }
};
```

Expected:

```json
{
  "hasWorkbench": true,
  "hasApp": true,
  "hasEditorState": true
}
```

- [ ] **Step 3: Run browser smoke if local server is available**

Start the existing area picker server if it is not already running. Open the editor page and verify:

- `window.VC_GAME_WORKBENCH.init` is a function.
- `window.VC_GAME_EDITOR_APP.getEditorState().getDocument()` returns a document.
- Clicking the game workspace tab initializes the viewport without a blank canvas error.
- Import whitebox button calls the module-backed `syncFromHoudini`.

- [ ] **Step 4: Confirm source-boundary acceptance**

Run:

```powershell
rg -n "var characters = \\[\\]|var whiteboxLayers = \\[\\]|var selectedObject = null|var undoStack = \\[\\]|function createPlayModeController|function createGameCameraController|function registerWhiteboxLayers" Scripts/app/area_picker/frontend/game_workbench.js
```

Expected: no matches.

Run:

```powershell
rg -n "export function createThreeViewport|export function createPlayModeController|export function createToolbar|export function loadWhiteboxGLB" Scripts/app/area_picker/frontend/editor
```

Expected: matches in the new module files.

- [ ] **Step 5: Restore generated test artifacts**

If `Reports/build_history/run_test.md` changes during tests, restore only the generated timestamp changes and keep the file out of the final commit.

- [ ] **Step 6: Commit final verification docs if needed**

If README or tests need final wording changes, commit them:

```powershell
git add Scripts/app/area_picker/frontend/README.md tests/test_area_picker.py
git commit -m "docs(editor): document completed core architecture"
```

Skip this commit if there are no final doc/test wording changes.

- [ ] **Step 7: Push branch**

Run:

```powershell
git push origin codex/game-editor-core-architecture
```

Expected: branch push succeeds.
