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
- Represent characters with a lightweight capsule collider so nearby whitebox
  faces cannot cut through the body volume
- Preserve the existing fallback behavior when no Houdini whitebox is loaded

Out of scope:

- Full rigid-body physics
- Wall sliding, jumping, gravity simulation, or dynamic rigid-body response
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
  - cast downward rays from the character capsule footprint, not only the root
    point
  - return the highest valid walkable hit on collision-enabled whitebox meshes
  - fall back to the ground plane when no hit exists
- Character grounding:
  - treat the character group origin as the character foot position
  - keep the root `position.z` on top of the highest footprint support surface
- Character blocking:
  - store a capsule-style runtime collider on each character
  - filter walkable surfaces by face normal, similar to a slope limit
  - during WASD movement, sweep center/side probes at several capsule heights
    and block movement into non-walkable whitebox faces

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
2. The play controller keeps the previous character position for collision
   resolution.
3. The workbench resolves the desired position against the whitebox collision
   mesh: non-walkable faces can block XY movement, and walkable footprint
   support updates `position.z`.
4. Camera follow and character animation use the resolved root position.

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
- characters carry a capsule collider definition for runtime collision
- surface grounding samples the capsule footprint instead of a single point
- play mode movement calls a reusable character collision resolver after XY
  movement
- runtime movement blocks non-walkable whitebox penetration from center and
  side probes
- the implementation keeps a no-whitebox fallback path

These tests match the existing frontend test style, which verifies the local
JavaScript contracts without requiring a browser runtime.

## Risks

- Large whitebox GLBs may make naive mesh raycasts expensive if many meshes are
  present.
- Raycasting against visual geometry means very dense whitebox GLBs can make
  multi-probe queries more expensive than a dedicated simplified collision mesh.
- Buildings may become walkable rooftops, which is useful for editor placement
  but may need filtering later if only terrain and roads should be playable.

Mitigation for this pass:

- Query only whitebox collision meshes, not all scene objects.
- Use walkable-normal filtering so steep/vertical faces are not treated as
  grounding surfaces.
- Use a small capsule-footprint probe set rather than arbitrary mesh physics.
- Keep the collision role explicit so later filters can disable buildings or
  replace visual geometry with simplified collision meshes.

## Recommended Implementation Shape

- Add small helpers near the existing placement functions:
  - `getWhiteboxCollisionMeshes()`
  - `screenToWhiteboxSurface(clientX, clientY)`
  - `snapPointToWhiteboxSurface(point, options)`
  - `resolveCharacterWhiteboxCollision(character, desiredPosition, previousPosition)`
  - `groundCharacterOnWhitebox(character, previousPosition)`
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
