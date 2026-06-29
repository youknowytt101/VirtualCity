# Viewport Grid Optimization Handoff

**Scope:** unify the planar reference grid used by:
- Editor 3D viewport: `Scripts/app/area_picker/frontend/game_workbench.js`
- Houdini preview pane: `Scripts/app/area_picker/frontend/houdini_preview.js`

**Goal:** move both views onto one shared shader-based grid module:
`Scripts/app/area_picker/frontend/viewport_grid.js`.

## Current State

- The editor viewport already uses a procedural shader grid, but it is drawn on a finite camera-following plane. It still depends on `EDITOR_GRID_SIZE` and has an edge fade to hide the finite plane boundary.
- The Houdini preview currently uses CPU-rebuilt `LineSegments` grid geometry with a faded material. This works, but it keeps a separate implementation and still allocates/disposes grid geometry when the LOD key changes.
- `houdini_preview.js` is no longer truncated. It currently parses with `node --check`.
- `computeTerrainPreviewPivot()` is a separate camera-framing concern. It is called once during `loadWhitebox()` after the GLB loads, not per frame.
- Existing tests contain string guards for the current implementation details. They must be updated before production code changes so the shared-module refactor has useful red/green coverage.

## Architecture

Add `window.VC_VIEWPORT_GRID`:

```js
window.VC_VIEWPORT_GRID = {
  create: createViewportGrid,
  update: updateViewportGrid,
  setOptions: setViewportGridOptions,
  dispose: disposeViewportGrid
};
```

The shared module owns:
- a fullscreen triangle grid mesh
- the shader material
- camera inverse view-projection uniforms
- Z-up plane intersection
- minor/major grid line LOD
- X/Y axis coloring and origin highlight
- optional vertical Z-axis helper for preview panes that need it
- disposal of owned geometry/materials

Consumers only create, update, and dispose a handle.

## Shader Requirements

- World is Z-up; the ground/reference plane is XY.
- Reconstruct each fragment ray from clip space through `uViewProjectionInverse`.
- Intersect the ray with `Z = uPlaneZ`.
- Discard fragments when the ray does not hit the plane in front of the camera.
- Draw anti-aliased minor/major lines with `fwidth(coord)`.
- Use smooth LOD fade so zooming does not pop.
- Keep distance and grazing-angle fade.
- Do not use finite-plane edge fade.
- Depth behavior must be explicit. If grid depth testing against scene meshes is needed, add a correct fragment-depth path or use a documented depth-test fallback.

## Consumer Settings

Editor viewport:
- `planeZ: 0`
- `showZAxis: false`
- keep current editor colors and fade distances (`fadeStart: 700`, `fadeEnd: 1850`, `lodPixels: 64`)
- remove `EDITOR_GRID_SIZE`, camera-following plane scale, and local shader material

Houdini preview:
- keep `PREVIEW_GRID_Z = 0.02` so the grid remains visible on the preview origin plane
- `showZAxis: true`
- keep camera orbit, drag, wheel zoom, whitebox framing, and visibility pause behavior
- remove CPU grid rebuild helpers: `niceGridStep`, `gridCameraDisplayExtent`, `gridWorldPerPixel`, `updatePreviewGridLod`, `updatePreviewAxes`, and `createFadedGridMaterial`

## Required File Changes

1. Add `Scripts/app/area_picker/frontend/viewport_grid.js`.
2. Add `<script src="/area-picker/viewport_grid.js?v=__VERSION__"></script>` in `index.html` before `game_workbench.js` and `houdini_preview.js`.
3. Add `viewport_grid.js` to `_frontend_asset_version()` in `Scripts/app/area_picker/server.py`.
4. Replace editor grid creation/update with `VC_VIEWPORT_GRID`.
5. Replace Houdini grid creation/update/disposal with `VC_VIEWPORT_GRID`.
6. Update `tests/test_area_picker.py` so it checks the shared module contract instead of old local implementation names.

## Acceptance Criteria

- `node --check` passes for `viewport_grid.js`, `game_workbench.js`, and `houdini_preview.js`.
- Focused viewport/static asset tests pass.
- `tests/test_area_picker.py` passes.
- Both consumers call the shared grid module.
- No grid code rebuilds `BufferGeometry` per camera LOD update.
- Editor no longer has a hard finite-plane boundary.
- Houdini keeps a visible preview grid and vertical Z-axis cue.
