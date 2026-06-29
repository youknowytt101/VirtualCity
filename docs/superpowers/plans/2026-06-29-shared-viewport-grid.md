# Shared Viewport Grid Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the editor and Houdini preview grid implementations with one shared shader-based viewport grid module.

**Architecture:** Add `Scripts/app/area_picker/frontend/viewport_grid.js` as the only owner of procedural grid rendering. `game_workbench.js` and `houdini_preview.js` create and update grid handles through `window.VC_VIEWPORT_GRID`; Houdini keeps its camera orbit and gets an optional vertical Z-axis helper.

**Tech Stack:** Plain browser JavaScript, global Three.js (`window.THREE`), existing `tests/test_area_picker.py` guard tests, `node --check`.

---

## File Structure

- Create `Scripts/app/area_picker/frontend/viewport_grid.js`: shared grid API, fullscreen shader mesh, optional Z-axis line, update/dispose helpers.
- Modify `Scripts/app/area_picker/frontend/index.html`: load `viewport_grid.js` after `vc_glb.js` and before `game_workbench.js`/`houdini_preview.js`.
- Modify `Scripts/app/area_picker/frontend/game_workbench.js`: replace local editor grid material/plane with `VC_VIEWPORT_GRID`.
- Modify `Scripts/app/area_picker/frontend/houdini_preview.js`: replace CPU-rebuilt LineSegments grid with `VC_VIEWPORT_GRID`; preserve orbit, zoom, preview framing, and visibility behavior.
- Modify `Scripts/app/area_picker/server.py`: include `viewport_grid.js` in frontend asset fingerprinting.
- Modify `tests/test_area_picker.py`: update static guard tests to target the shared module contract.
- Modify `docs/GRID_OPTIMIZATION_HANDOFF.md`: correct current state and document the revised plan.

## Task 1: Update Tests First

**Files:**
- Modify: `tests/test_area_picker.py`

- [ ] **Step 1: Include `viewport_grid.js` in frontend script aggregation**

Add `"viewport_grid.js"` to `_PICKER_SCRIPT_NAMES` after `"vc_glb.js"` so shared module source participates in frontend-wide assertions.

- [ ] **Step 2: Replace Houdini CPU-grid expectations**

Update the Houdini grid tests to assert:
- `window.VC_VIEWPORT_GRID.create(scene, camera, ...)`
- `window.VC_VIEWPORT_GRID.update(previewGrid, camera)`
- `window.VC_VIEWPORT_GRID.dispose(previewGrid)`
- `planeZ: PREVIEW_GRID_Z`
- `showZAxis: true`
- no `updatePreviewGridLod`, `createFadedGridMaterial`, `niceGridStep`, or per-LOD `new THREE.BufferGeometry()` grid rebuild.

- [ ] **Step 3: Replace editor local-shader expectations**

Update the editor grid test to assert:
- `window.VC_VIEWPORT_GRID.create(scene, camera, ...)`
- `window.VC_VIEWPORT_GRID.update(editorGrid, camera)`
- no local `createEditorGridMaterial`
- no editor `new THREE.PlaneGeometry(1, 1)` grid plane
- no `EDITOR_GRID_SIZE`

- [ ] **Step 4: Add shared module and script-order tests**

Assert the new module contains:
- `window.VC_VIEWPORT_GRID`
- `create: createViewportGrid`
- `update: updateViewportGrid`
- `dispose: disposeViewportGrid`
- `new THREE.ShaderMaterial`
- `fwidth(coord)`
- `uViewProjectionInverse`
- `uPlaneZ`
- `showZAxis`

Assert `index.html` loads `/area-picker/viewport_grid.js?v=__VERSION__` before `/area-picker/game_workbench.js?v=__VERSION__` and `/area-picker/houdini_preview.js?v=__VERSION__`.

- [ ] **Step 5: Add asset fingerprint coverage**

In `_frontend_asset_version` tests, create `viewport_grid.js` in the temporary frontend root and mutate it once to confirm the version string changes.

- [ ] **Step 6: Run focused tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_area_picker.py::TestPickerHtml::test_shared_viewport_grid_module_contract tests/test_area_picker.py::TestPickerHtml::test_viewport_grid_script_loads_before_consumers tests/test_area_picker.py::TestPickerHtml::test_houdini_preview_uses_shared_shader_viewport_grid tests/test_area_picker.py::TestPickerHtml::test_game_editor_grid_uses_shared_shader_viewport_grid tests/test_area_picker.py::TestFrontendAssetVersion::test_version_changes_when_asset_content_changes -q
```

Expected: fail because `viewport_grid.js` does not exist and consumers still use local grid implementations.

## Task 2: Implement Shared Grid Module

**Files:**
- Create: `Scripts/app/area_picker/frontend/viewport_grid.js`

- [ ] **Step 1: Add public API**

Expose:

```javascript
window.VC_VIEWPORT_GRID = {
  create: createViewportGrid,
  update: updateViewportGrid,
  setOptions: setViewportGridOptions,
  dispose: disposeViewportGrid
};
```

- [ ] **Step 2: Build one fullscreen grid mesh**

Create a `THREE.BufferGeometry` triangle with clip-space positions `[-1,-1,0]`, `[3,-1,0]`, `[-1,3,0]`, a `THREE.ShaderMaterial`, `transparent: true`, `depthWrite: false`, `depthTest` configurable, `frustumCulled = false`, and `renderOrder` configurable.

- [ ] **Step 3: Reconstruct world position in shader**

Use `uViewProjectionInverse`, `uCameraPosition`, and `uPlaneZ` to reconstruct near/far world points, intersect the ray with the Z-up plane, discard invalid intersections, and compute AA minor/major lines with `fwidth(coord)`.

- [ ] **Step 4: Preserve editor shader behavior**

Carry forward decade LOD fade, minor/major colors, X/Y axis colors, origin highlight, distance fade, and grazing fade. Remove finite plane edge fade.

- [ ] **Step 5: Add optional Z-axis helper**

When `showZAxis` is true, create a small `THREE.LineSegments` helper for the vertical Z axis. Update its length from `axisLength`, avoid per-frame rebuilds, and dispose it with the grid handle.

## Task 3: Wire Consumers

**Files:**
- Modify: `Scripts/app/area_picker/frontend/index.html`
- Modify: `Scripts/app/area_picker/frontend/game_workbench.js`
- Modify: `Scripts/app/area_picker/frontend/houdini_preview.js`
- Modify: `Scripts/app/area_picker/server.py`

- [ ] **Step 1: Add the script tag**

Load:

```html
<script src="/area-picker/viewport_grid.js?v=__VERSION__"></script>
```

before both `game_workbench.js` and `houdini_preview.js`.

- [ ] **Step 2: Replace editor grid creation/update**

Use the shared module in `createGrid()` and `updateEditorGrid()`. Keep editor fade distances close to the current shader: `fadeStart: 700`, `fadeEnd: 1850`, `lodPixels: 64`, `showZAxis: false`, `planeZ: 0`.

- [ ] **Step 3: Replace Houdini grid creation/update/disposal**

Use the shared module in `createPreviewGrid()`, `updatePreviewCameraOrbit()`, `tick()`, and `disposePreview()`. Keep `PREVIEW_GRID_Z = 0.02`, use smaller preview fade distances, and set `showZAxis: true`.

- [ ] **Step 4: Update asset fingerprinting**

Add `viewport_grid.js` to `_frontend_asset_version()` between `vc_glb.js` and `game_workbench.js`.

## Task 4: Verify and Review

**Files:**
- Verify changed JavaScript and tests.

- [ ] **Step 1: Run RED/GREEN focused tests**

Run the focused viewport and asset-version tests from Task 1. Expected after implementation: all pass.

- [ ] **Step 2: Run JavaScript syntax checks**

Run:

```powershell
node --check Scripts/app/area_picker/frontend/viewport_grid.js
node --check Scripts/app/area_picker/frontend/game_workbench.js
node --check Scripts/app/area_picker/frontend/houdini_preview.js
```

Expected: exit code 0 for all.

- [ ] **Step 3: Run area picker tests**

Run:

```powershell
python -m pytest tests/test_area_picker.py -q
```

Expected: all tests pass.

- [ ] **Step 4: Review diff**

Run:

```powershell
git diff -- docs/GRID_OPTIMIZATION_HANDOFF.md docs/superpowers/plans/2026-06-29-shared-viewport-grid.md Scripts/app/area_picker/frontend/viewport_grid.js Scripts/app/area_picker/frontend/game_workbench.js Scripts/app/area_picker/frontend/houdini_preview.js Scripts/app/area_picker/frontend/index.html Scripts/app/area_picker/server.py tests/test_area_picker.py
```

Expected: diff is limited to shared viewport grid docs, tests, module creation, consumer wiring, and asset versioning.
