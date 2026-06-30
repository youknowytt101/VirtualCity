# Game Editor Core Completion Design

## Goal

Complete the game editor core refactor so the editor is no longer centered on
`game_workbench.js`, while preserving the current WorldBuilder page, static
frontend delivery, Three.js viewport behavior, Houdini whitebox import, and
workspace compatibility API.

The completion scope is intentionally bounded:

- No scene save/load feature.
- No publishing feature.
- No backend route changes.
- No React, Vue, Vite, TypeScript, or frontend build pipeline migration.
- No visual redesign of the existing editor page.

## Current State

Phase 1 added `editor/` ES modules for `SceneDocument`, command factories,
`EditorState`, `editor_app.js`, and `legacy_bridge.js`.

Phase 2 added `legacy_sync.js` and started syncing legacy edit mutations into
the new editor state through `window.VC_GAME_EDITOR_SYNC`.

The remaining problem is that `game_workbench.js` is still the editor kernel. It
still owns:

- Three.js scene setup, renderer, camera, lights, grid, render loop, and resize.
- Character construction, material setup, outline meshes, and entity arrays.
- Selection, transform mode, transform controls, scene outline, and shortcuts.
- Whitebox import registration and layer material handling.
- Picking, ground placement, walkable whitebox detection, and collision helpers.
- Play mode, player movement, runtime camera, and runtime input.
- Toolbar drag/drop, run controls, side panel resizing, status text, and undo.

The completed architecture must move these responsibilities behind focused
editor modules and make `SceneDocument` the authoritative edit-state source.

## Completion Standard

The refactor is complete when these statements are true:

- `SceneDocument` is the only authoritative source for edit entities, selection,
  transform mode, and edit/play mode.
- Every document edit flows through command dispatch.
- Three.js objects are render/runtime projections of document entities, not the
  source of identity or edit state.
- Viewport, controls, transform gizmo, picking, assets, runtime, and UI panels
  live in focused modules under `Scripts/app/area_picker/frontend/editor/`.
- `game_workbench.js` is either removed from `index.html` or reduced to a thin
  compatibility shim with no editor state ownership.
- `window.VC_GAME_WORKBENCH` keeps the same public methods used by
  `workspace.js`: `init`, `resize`, `setActive`, `loadGLB`, and
  `syncFromHoudini`.
- Existing editor workflows remain working: open editor, import whitebox, add a
  character, select it, change transform mode, duplicate/delete, undo/redo, run
  play mode, exit play mode, and resize the viewport/panels.

## Approaches Considered

### Approach A: Incremental Kernel Extraction

Move behavior out of `game_workbench.js` in dependency order while keeping the
compatibility API stable after every slice.

Order:

1. Move IDs, entity factories, and document-facing commands.
2. Move Three viewport creation and document-to-object rendering.
3. Move picking, transform gizmo, and viewport controls.
4. Move whitebox asset import and Houdini bridge.
5. Move runtime play mode and collision.
6. Move toolbar, outline, status bar, shortcuts, and panel resize UI.
7. Replace `game_workbench.js` with the module-backed app entry.

Trade-off: more commits and more temporary adapters, but the editor remains
testable and usable throughout.

### Approach B: Big-Bang Rewrite Inside `editor_app.js`

Build a new editor app in parallel, then switch `index.html` from
`game_workbench.js` to the new app once it reaches feature parity.

Trade-off: fewer transitional shims, but high risk of visual and behavior
regressions because all workflows land at once.

### Approach C: Framework or Build-System Migration

Introduce a frontend framework, bundler, or TypeScript and rebuild the editor on
top of that foundation.

Trade-off: cleaner long-term tooling, but it violates the current constraints
and would mix architecture migration with toolchain migration.

## Chosen Approach

Use Approach A: incremental kernel extraction.

This matches the existing codebase and the approved scope. It keeps static
script delivery, preserves the editor's current surface, and allows each module
boundary to be protected by focused tests before the next extraction.

## Target File Layout

```text
Scripts/app/area_picker/frontend/editor/
  editor_app.js
  legacy_bridge.js

  core/
    ids.js
    scene_document.js
    commands.js
    editor_state.js
    entity_factories.js

  viewport/
    three_viewport.js
    viewport_controls.js
    transform_gizmo.js
    picking.js

  assets/
    asset_registry.js
    glb_importer.js
    houdini_bridge.js

  runtime/
    play_mode.js
    character_collision.js

  ui/
    toolbar.js
    scene_outline.js
    status_bar.js
    shortcuts.js
    side_panel_resize.js
```

`vc_glb.js` and `viewport_grid.js` stay as shared low-level scripts. The editor
modules can consume them through injected browser globals until a future
toolchain change exists.

## Module Responsibilities

### Core

`ids.js` generates stable entity IDs for characters and whitebox layers.

`entity_factories.js` creates plain character and whitebox entity records. It
does not create Three.js objects.

`scene_document.js` normalizes and mutates plain documents immutably.

`commands.js` owns all document-changing command constructors:

- `AddEntityCommand`
- `DeleteSelectionCommand`
- `DuplicateSelectionCommand`
- `TransformEntityCommand`
- `SetSelectionCommand`
- `SetTransformModeCommand`
- `ImportWhiteboxCommand`
- `SetEditorModeCommand`

`editor_state.js` owns dispatch, undo, redo, and subscriptions.

### Viewport

`three_viewport.js` owns scene, camera, renderer, lights, grid, resize, render
loop, and the `entityId -> Object3D` map.

It subscribes to `EditorState` and reconciles the rendered scene from the
document:

```text
document entity added -> create object
document entity removed -> remove object
document entity transform changed -> update object transform
document selection changed -> update highlight and gizmo attachment
document mode changed -> update edit/runtime overlays
```

`viewport_controls.js` owns editor camera movement only.

`transform_gizmo.js` wraps Three `TransformControls`. It reads selected entity
IDs from the document and dispatches `TransformEntityCommand` when user edits
finish.

`picking.js` owns raycast helpers and returns entity IDs or placement points. It
never mutates editor state directly.

### Assets

`asset_registry.js` defines asset references:

- `builtin:character`
- `houdini:whitebox.glb#terrain`
- `houdini:whitebox.glb#buildings`
- `houdini:whitebox.glb#roads`

`glb_importer.js` adapts `window.VC_GLB.load(url)` into whitebox layer entities
and render resource metadata. A failed GLB load must leave the current document
unchanged.

`houdini_bridge.js` reads `window.VC_HOUDINI_PREVIEW.getWhitebox()` and returns
the import URL used by `glb_importer.js`.

### Runtime

`play_mode.js` owns entering, updating, and exiting runtime simulation.

Entering play mode snapshots the edit document. Runtime movement may mutate
runtime Three objects, but not the edit document. Exiting play mode restores the
edit document projection.

`character_collision.js` owns capsule dimensions, walkable hit detection,
whitebox surface snapping, and movement blocking. It reads viewport collision
meshes by entity ID but does not know about DOM controls.

### UI

`toolbar.js` owns asset drag/drop, run/stop button behavior, and transform mode
buttons.

`scene_outline.js` renders document entities and dispatches selection commands.

`status_bar.js` exposes a small status API used by app modules.

`shortcuts.js` owns keyboard command routing.

`side_panel_resize.js` owns the game outline panel resizer.

UI modules may dispatch commands or call public app methods, but they must not
directly mutate Three.js objects.

## Data Flow

Normal edit flow:

```text
DOM or viewport event
  -> command factory
  -> EditorState.dispatch(command)
  -> SceneDocument replacement
  -> EditorState subscribers
  -> viewport/UI sync
```

Whitebox import flow:

```text
syncFromHoudini()
  -> houdini_bridge.getLatestWhitebox()
  -> glb_importer.loadWhitebox(url)
  -> ImportWhiteboxCommand(layerEntities)
  -> three_viewport reconciles layer objects
  -> scene_outline rerenders entities
```

Play flow:

```text
run button or Space
  -> SetEditorModeCommand("play")
  -> play_mode captures edit snapshot
  -> runtime updates viewport objects only
  -> exit play mode
  -> SetEditorModeCommand("edit")
  -> viewport returns to edit projection
```

## Error Handling

- Missing Three.js: `init()` returns `false` and status says Three.js is not
  loaded.
- Missing `VC_GLB`: `loadGLB()` returns a rejected promise and the document is
  unchanged.
- Missing whitebox URL: `syncFromHoudini()` keeps the editor active and shows an
  import-specific status.
- GLB load failure: previous whitebox entities and viewport objects remain.
- Invalid command input: command dispatch throws or returns the current document
  without pushing undo history.
- Play mode without a character: editor stays in edit mode and status asks the
  user to select or add a character.

## Migration Rules

- Preserve `window.VC_GAME_WORKBENCH` throughout the migration.
- Do not import ES modules from `game_workbench.js`; new module entry points
  replace it.
- Keep each extraction behavior-preserving unless the spec explicitly says
  otherwise.
- Prefer plain objects, arrays, and browser APIs; do not add dependencies.
- Keep generated logs out of commits.
- Add tests before implementation for each module boundary.
- Each migration slice must leave `python -m pytest -q` passing.

## Testing Strategy

Static guard tests stay in `tests/test_area_picker.py` for script wiring and
module contracts.

Behavior tests should cover:

- `ids.js` generates stable non-conflicting IDs.
- entity factories produce normalized character and whitebox entities.
- commands update and undo document state.
- viewport module exposes `createThreeViewport`.
- viewport reconciliation creates/removes objects by entity ID.
- picking returns IDs and placement points without dispatching commands.
- transform gizmo emits `TransformEntityCommand` only after edits finish.
- whitebox importer does not mutate the document on failed load.
- play mode snapshots and restores edit state boundaries.
- UI modules dispatch commands instead of mutating legacy arrays.

Browser or Node smoke checks should verify:

- `legacy_bridge.js` imports without syntax errors.
- `window.VC_GAME_WORKBENCH` exposes the same public methods.
- adding a character creates a document entity and a viewport object.
- selecting an outline row changes `document.selection.ids`.
- changing transform mode updates `document.editor.transformMode`.
- importing whitebox creates terrain, buildings, and roads entities.
- entering and exiting play mode returns to edit mode with the edit document
  intact.

## Acceptance Checklist

- `game_workbench.js` no longer contains editor-owned arrays such as
  `characters`, `whiteboxLayers`, `selectedObject`, or `undoStack`.
- `game_workbench.js` no longer owns Three scene setup, render loop, picking,
  play mode, whitebox import, collision, toolbar, outline, or status behavior.
- `index.html` loads the module-backed editor entry instead of relying on the
  legacy workbench as the kernel.
- All document-changing UI and viewport interactions use command dispatch.
- Undo and redo are served by `EditorState`.
- The public compatibility API remains stable for `workspace.js`.
- Full test suite passes.
