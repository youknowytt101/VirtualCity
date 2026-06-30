# Whitebox Character Collision Design

## Goal

Make Houdini-imported whitebox models act as walkable collision surfaces in the
game editor, so characters:

- can recognize imported whitebox layers as collision-enabled model surfaces
- snap to the whitebox surface when dropped into the editor
- stay grounded on the whitebox surface during runtime WASD movement

The implementation should match the current lightweight Three.js editor model
and avoid introducing a full physics engine in this pass.

## Scope

In scope:

- Tag imported `VC_whitebox_terrain`, `VC_whitebox_buildings`, and
  `VC_whitebox_roads` layers as collision-enabled walkable surfaces
- Add a reusable surface query for finding the whitebox height at an XY position
- Use that query when placing a dragged-in character
- Use that query during play mode movement so the character remains grounded
- Preserve the existing fallback behavior when no Houdini whitebox is loaded

Out of scope:

- Full rigid-body physics
- Character capsule blocking, wall sliding, jumping, or gravity simulation
- Editing the Houdini GLB export format
- Adding a separate collision mesh export contract
- Reworking the game editor UI

## Current System

`game_workbench.js` owns the editor scene, character drag/drop, runtime movement,
TransformControls, and Houdini whitebox import into the game workspace.

Today:

- `registerWhiteboxLayers(root)` finds `VC_whitebox_*` layer groups and makes
  them selectable editor objects
- `screenToGround(clientX, clientY)` intersects the mouse ray with an infinite
  `z=0` plane
- `placeCharacterAt(point)` creates a character and always sets
  `character.position.z` to `0`
- play mode moves the selected character in XY and never adjusts Z from scene
  geometry

This means the imported whitebox is visible and selectable, but it is not yet a
runtime placement or grounding surface.

## Proposed Architecture

Keep collision ownership inside `game_workbench.js` for now. The feature should
be implemented as a small walkable-surface layer over the existing Three.js
scene:

- Whitebox collision registration:
  - mark each imported layer with `userData.collisionEnabled = true`
  - mark each imported layer with `userData.collisionRole = 'walkable'`
  - mark descendant meshes with a reference back to their collision layer
- Collision mesh collection:
  - collect only meshes under collision-enabled whitebox layers
  - exclude characters, editor helpers, shadows, grids, and TransformControls
- Surface query:
  - cast a ray downward from above the target XY position
  - return the first valid hit on a collision-enabled whitebox mesh
  - fall back to the ground plane when no hit exists
- Character grounding:
  - treat the character group origin as the character foot position
  - assign the character root `position.z` from the surface hit Z

This keeps visual mesh import and runtime walkable behavior connected without
requiring backend or Houdini export changes.

## Data Flow

Whitebox import:

1. The editor loads `/whitebox.glb` through `VC_GLB.load(url)`.
2. `registerWhiteboxLayers(root)` tags imported `VC_whitebox_*` layer groups.
3. Each tagged layer becomes selectable and collision-enabled.
4. Descendant meshes become candidates for walkable surface raycasts.

Character drag/drop:

1. The asset toolbar starts the existing pointer drag.
2. On pointer release, the editor computes a placement ray from the screen
   position.
3. The ray first tests imported whitebox collision meshes.
4. If a whitebox surface is hit, the character is created at that hit point.
5. If not, placement falls back to the current `z=0` ground-plane behavior.

Runtime movement:

1. WASD movement updates the character XY position as it does today.
2. After XY movement, the play controller asks the workbench to ground the
   character at the new XY location.
3. The grounding query adjusts only `position.z`.
4. Camera follow and character animation use the updated root position.

## Error Handling

- If Three.js, the raycaster, or the scene is unavailable, skip collision logic
  and preserve current behavior.
- If no whitebox is loaded, use the ground plane at `z=0`.
- If the pointer release is outside the viewport or cannot form a ray, do not
  create a character.
- If a surface query misses the whitebox at runtime, keep the character on the
  ground-plane fallback instead of leaving stale Z.
- If a whitebox layer has no meshes, it remains selectable but contributes no
  walkable surface.

## Testing

Add focused guard coverage in `tests/test_area_picker.py`:

- `game_workbench.js` registers whitebox layers with collision metadata
- descendant whitebox meshes are linked back to a collision root
- dragged character placement uses a whitebox surface placement function before
  falling back to the ground plane
- play mode movement calls a reusable character grounding function after XY
  movement
- the implementation keeps a no-whitebox fallback path

These tests match the existing frontend test style, which verifies the local
JavaScript contracts without requiring a browser runtime.

## Risks

- Large whitebox GLBs may make naive mesh raycasts expensive if many meshes are
  present.
- Raycasting against visual geometry means steep walls or vertical faces can be
  hit if the query starts over them.
- Buildings may become walkable rooftops, which is useful for editor placement
  but may need filtering later if only terrain and roads should be playable.

Mitigation for this pass:

- Query only whitebox collision meshes, not all scene objects.
- Use a vertical downward ray from the character XY position for runtime
  grounding, which naturally ignores most vertical side faces.
- Keep the collision role explicit so later filters can disable buildings or
  replace visual geometry with simplified collision meshes.

## Recommended Implementation Shape

- Add small helpers near the existing placement functions:
  - `getWhiteboxCollisionMeshes()`
  - `screenToWhiteboxSurface(clientX, clientY)`
  - `snapPointToWhiteboxSurface(point)`
  - `groundCharacterOnWhitebox(character)`
- Change `placeCharacterAt(point)` to honor the point Z instead of forcing `0`.
- Change `endAssetDrag(event)` to prefer `screenToWhiteboxSurface()`.
- Pass `groundCharacterOnWhitebox` into `createPlayModeController()` and call it
  after runtime XY movement.
- Keep all behavior contained to `game_workbench.js` plus guard tests.

## Open Decision

Assumption for implementation:

- All imported Houdini whitebox layers are walkable collision surfaces for this
  pass, including terrain, roads, and building roofs.

If this becomes too permissive during editor use, the next iteration should add
a layer filter or per-layer collision toggle instead of changing the core
grounding query.
