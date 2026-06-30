# Whitebox Character Collision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Houdini-imported whitebox layers behave as walkable collision surfaces for character drag/drop placement and runtime grounding in the game editor.

**Architecture:** Keep the feature inside `Scripts/app/area_picker/frontend/game_workbench.js`, where the editor scene, whitebox import, character placement, and play mode already live. Add a small raycast-based walkable-surface layer over existing Three.js objects instead of introducing a full physics engine.

**Tech Stack:** Vanilla JavaScript, Three.js `Raycaster`, existing Python `unittest` static frontend guard tests.

## Global Constraints

- Do not introduce a physics engine in this pass.
- Do not change Houdini GLB export format or backend whitebox status contracts.
- Treat `VC_whitebox_terrain`, `VC_whitebox_buildings`, and `VC_whitebox_roads` as walkable whitebox collision layers for this pass.
- Preserve the current no-whitebox fallback: characters can still be placed and run on the `z=0` ground plane.
- Keep all runtime behavior changes in `Scripts/app/area_picker/frontend/game_workbench.js`.

---

## File Structure

- Modify `Scripts/app/area_picker/frontend/game_workbench.js`
  - Register imported whitebox layers as walkable collision surfaces.
  - Add reusable helper functions for collision mesh collection, screen-surface hit tests, XY-to-surface snapping, and character grounding.
  - Use those helpers from drag/drop placement and play mode movement.
- Modify `tests/test_area_picker.py`
  - Add static guard tests matching the existing frontend test style.
  - Verify the new JavaScript contracts without requiring browser automation.

No new runtime dependency or frontend module is needed.

---

### Task 1: Whitebox Collision Metadata And Drag/Drop Surface Placement

**Files:**
- Modify: `tests/test_area_picker.py`
- Modify: `Scripts/app/area_picker/frontend/game_workbench.js`

**Interfaces:**
- Consumes: Existing globals in `game_workbench.js`: `whiteboxLayers`, `raycaster`, `sceneHost`, `camera`, `mouse`, `groundPlane`, `hitPoint`, `safeThree()`, `screenToGround()`, `placeCharacterAt(point)`, `registerWhiteboxLayers(root)`.
- Produces:
  - `function getWhiteboxCollisionMeshes(): Array<THREE.Mesh>`
  - `function screenToWhiteboxSurface(clientX: number, clientY: number): THREE.Vector3 | null`
  - `function snapPointToWhiteboxSurface(point: THREE.Vector3): THREE.Vector3 | null`

- [ ] **Step 1: Write the failing test**

Add this method near the other game workbench tests in `tests/test_area_picker.py`, after `test_game_workspace_mounts_three_scene`:

```python
    def test_game_whitebox_layers_register_walkable_collision_surfaces(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        register_start = game_js.index("function registerWhiteboxLayers(root)")
        register_end = game_js.index("function fitSunShadow(root)", register_start)
        register_body = game_js[register_start:register_end]

        self.assertIn("node.userData.collisionEnabled = true;", register_body)
        self.assertIn("node.userData.collisionRole = 'walkable';", register_body)
        self.assertIn("mesh.userData.collisionRoot = node;", register_body)
        self.assertIn("function getWhiteboxCollisionMeshes()", game_js)
        self.assertIn("function screenToWhiteboxSurface(clientX, clientY)", game_js)
        self.assertIn("function snapPointToWhiteboxSurface(point)", game_js)

    def test_game_character_drop_prefers_whitebox_surface_over_ground_plane(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        drag_start = game_js.index("function endAssetDrag(event)")
        drag_end = game_js.index("function handleGameShortcut(event)", drag_start)
        drag_body = game_js[drag_start:drag_end]

        self.assertIn("var point = screenToWhiteboxSurface(event.clientX, event.clientY);", drag_body)
        self.assertIn("if (!point) point = screenToGround(event.clientX, event.clientY);", drag_body)
        self.assertIn("if (point) placeCharacterAt(point);", drag_body)
        self.assertNotIn("character.position.set(point.x, point.y, 0);", game_js)
        self.assertIn("character.position.set(point.x, point.y, point.z || 0);", game_js)
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```powershell
pytest tests/test_area_picker.py::TestPickerHtml::test_game_whitebox_layers_register_walkable_collision_surfaces tests/test_area_picker.py::TestPickerHtml::test_game_character_drop_prefers_whitebox_surface_over_ground_plane -v
```

Expected: both tests fail because the collision metadata and helper names do not exist yet, and `placeCharacterAt()` still forces `z=0`.

- [ ] **Step 3: Implement whitebox collision registration and placement helpers**

In `Scripts/app/area_picker/frontend/game_workbench.js`, add these helper variables near the existing top-level editor state, after `var editorGrid = null;`:

```javascript
  var surfaceRayOrigin = null;
  var surfaceRayDirection = null;
```

In `initGameWorkbench()`, after `hitPoint = new THREE.Vector3();`, initialize them:

```javascript
    surfaceRayOrigin = new THREE.Vector3();
    surfaceRayDirection = new THREE.Vector3(0, 0, -1);
```

Add these helpers after `screenToGround(clientX, clientY)` and before `placeCharacterAt(point)`:

```javascript
  function getWhiteboxCollisionMeshes() {
    var meshes = [];
    whiteboxLayers.forEach(function(layer) {
      if (!layer.userData || !layer.userData.collisionEnabled) return;
      layer.traverse(function(node) {
        if (!node.isMesh || !node.geometry) return;
        meshes.push(node);
      });
    });
    return meshes;
  }

  function screenToWhiteboxSurface(clientX, clientY) {
    var rect = sceneHost.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    var meshes = getWhiteboxCollisionMeshes();
    if (!meshes.length) return null;
    mouse.x = ((clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -(((clientY - rect.top) / rect.height) * 2 - 1);
    raycaster.setFromCamera(mouse, camera);
    var hits = raycaster.intersectObjects(meshes, true);
    return hits.length ? hits[0].point.clone() : null;
  }

  function snapPointToWhiteboxSurface(point) {
    var THREE = safeThree();
    var meshes = getWhiteboxCollisionMeshes();
    if (!point || !THREE) return null;
    if (!meshes.length || !surfaceRayOrigin || !surfaceRayDirection) {
      return new THREE.Vector3(point.x, point.y, 0);
    }
    surfaceRayOrigin.set(point.x, point.y, Math.max(point.z || 0, 0) + 1000);
    raycaster.set(surfaceRayOrigin, surfaceRayDirection);
    var hits = raycaster.intersectObjects(meshes, true);
    if (!hits.length) return new THREE.Vector3(point.x, point.y, 0);
    return hits[0].point.clone();
  }
```

Change `placeCharacterAt(point)` from:

```javascript
    character.position.set(point.x, point.y, 0);
```

to:

```javascript
    character.position.set(point.x, point.y, point.z || 0);
```

In `registerWhiteboxLayers(root)`, after `node.userData.assetLabel = LAYER_LABELS[key];`, add:

```javascript
      node.userData.collisionEnabled = true;
      node.userData.collisionRole = 'walkable';
```

In the child mesh traversal inside `registerWhiteboxLayers(root)`, after `mesh.userData.assetRoot = node;`, add:

```javascript
        mesh.userData.collisionRoot = node;
```

In `endAssetDrag(event)`, replace:

```javascript
    var point = screenToGround(event.clientX, event.clientY);
    if (point) placeCharacterAt(point);
```

with:

```javascript
    var point = screenToWhiteboxSurface(event.clientX, event.clientY);
    if (!point) point = screenToGround(event.clientX, event.clientY);
    if (point) placeCharacterAt(point);
```

- [ ] **Step 4: Run the focused tests to verify they pass**

Run:

```powershell
pytest tests/test_area_picker.py::TestPickerHtml::test_game_whitebox_layers_register_walkable_collision_surfaces tests/test_area_picker.py::TestPickerHtml::test_game_character_drop_prefers_whitebox_surface_over_ground_plane -v
```

Expected: both tests pass.

- [ ] **Step 5: Run the existing nearby game workbench tests**

Run:

```powershell
pytest tests/test_area_picker.py::TestPickerHtml::test_game_workspace_mounts_three_scene tests/test_area_picker.py::TestPickerHtml::test_game_workspace_uses_transform_controls tests/test_area_picker.py::TestPickerHtml::test_game_viewport_orbits_selected_character_first -v
```

Expected: all tests pass. If `test_game_workspace_uses_transform_controls` fails because it expects `transformControls.attach(selectedCharacter)`, update that test only if the current source already intentionally uses `selectedObject`; do not change the runtime code for this collision task.

- [ ] **Step 6: Commit Task 1**

```powershell
git add tests/test_area_picker.py Scripts/app/area_picker/frontend/game_workbench.js
git commit -m "feat(editor): add whitebox collision placement"
```

---

### Task 2: Runtime Character Grounding On Whitebox Surface

**Files:**
- Modify: `tests/test_area_picker.py`
- Modify: `Scripts/app/area_picker/frontend/game_workbench.js`

**Interfaces:**
- Consumes:
  - `snapPointToWhiteboxSurface(point: THREE.Vector3): THREE.Vector3 | null` from Task 1
  - existing `createPlayModeController(options)` and `playMode.update(deltaTime)`
- Produces:
  - `function groundCharacterOnWhitebox(character): boolean`
  - `groundCharacter(player)` callback support inside play mode

- [ ] **Step 1: Write the failing test**

Add this method near the other game workbench tests in `tests/test_area_picker.py`, after the Task 1 tests:

```python
    def test_game_runtime_movement_grounds_character_on_whitebox_surface(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        controller_start = game_js.index("function createPlayModeController(options)")
        controller_end = game_js.index("function createGameCameraController()", controller_start)
        controller_body = game_js[controller_start:controller_end]
        update_start = controller_body.index("function update(deltaTime)")
        update_end = controller_body.index("return true;", update_start)
        update_body = controller_body[update_start:update_end]
        init_start = game_js.index("playMode = createPlayModeController({")
        init_end = game_js.index("});", init_start)
        init_body = game_js[init_start:init_end]

        self.assertIn("function groundCharacterOnWhitebox(character)", game_js)
        self.assertIn("groundCharacter(player);", update_body)
        self.assertLess(
            update_body.index("player.position.addScaledVector(moveDirection, config.moveSpeed * deltaTime);"),
            update_body.index("groundCharacter(player);"),
        )
        self.assertIn("groundCharacter: groundCharacterOnWhitebox", init_body)
        self.assertIn("snapPointToWhiteboxSurface(character.position)", game_js)
```

- [ ] **Step 2: Run the new test to verify it fails**

Run:

```powershell
pytest tests/test_area_picker.py::TestPickerHtml::test_game_runtime_movement_grounds_character_on_whitebox_surface -v
```

Expected: fail because `groundCharacterOnWhitebox()` and the play mode callback do not exist yet.

- [ ] **Step 3: Implement runtime grounding**

In `Scripts/app/area_picker/frontend/game_workbench.js`, add this helper after `snapPointToWhiteboxSurface(point)` and before `placeCharacterAt(point)`:

```javascript
  function groundCharacterOnWhitebox(character) {
    if (!character || !character.position) return false;
    var point = snapPointToWhiteboxSurface(character.position);
    if (!point) return false;
    character.position.z = point.z || 0;
    return true;
  }
```

Inside `createPlayModeController(options)`, change the default config block from:

```javascript
    var config = Object.assign({
      cameraDistance: 6,
      cameraHeight: 1.8,
      cameraTargetHeight: 1.2,
      lookSensitivity: 0.0025,
      maxPitch: 1.47,
      minPitch: -1.4,
      moveSpeed: 4.5,
      shoulderOffset: 0.45,
      lookDamping: 18
    }, options.options || {});
```

to:

```javascript
    var config = Object.assign({
      cameraDistance: 6,
      cameraHeight: 1.8,
      cameraTargetHeight: 1.2,
      lookSensitivity: 0.0025,
      maxPitch: 1.47,
      minPitch: -1.4,
      moveSpeed: 4.5,
      shoulderOffset: 0.45,
      lookDamping: 18
    }, options.options || {});
    var groundCharacter = typeof options.groundCharacter === 'function'
      ? options.groundCharacter
      : function() { return false; };
```

Inside `createPlayModeController(options)` `update(deltaTime)`, after the movement block and before `updateCharacterMotion(player, moveDirection, deltaTime);`, add:

```javascript
      groundCharacter(player);
```

When creating play mode in `initGameWorkbench()`, change:

```javascript
    playMode = createPlayModeController({
      camera: camera,
      renderer: renderer,
      onChange: syncRunState
    });
```

to:

```javascript
    playMode = createPlayModeController({
      camera: camera,
      renderer: renderer,
      groundCharacter: groundCharacterOnWhitebox,
      onChange: syncRunState
    });
```

- [ ] **Step 4: Run the focused runtime grounding test**

Run:

```powershell
pytest tests/test_area_picker.py::TestPickerHtml::test_game_runtime_movement_grounds_character_on_whitebox_surface -v
```

Expected: pass.

- [ ] **Step 5: Run all game workbench static guard tests**

Run:

```powershell
pytest tests/test_area_picker.py -k "game_" -v
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 2**

```powershell
git add tests/test_area_picker.py Scripts/app/area_picker/frontend/game_workbench.js
git commit -m "feat(editor): ground characters on whitebox surfaces"
```

---

### Task 3: End-To-End Verification

**Files:**
- Test only unless verification exposes a defect.

**Interfaces:**
- Consumes: Task 1 and Task 2 committed changes.
- Produces: Verified local implementation with no unrelated dirty files.

- [ ] **Step 1: Run focused frontend contract tests**

Run:

```powershell
pytest tests/test_area_picker.py -k "game_ or whitebox" -v
```

Expected: all selected tests pass.

- [ ] **Step 2: Run broader area picker tests**

Run:

```powershell
pytest tests/test_area_picker.py -v
```

Expected: pass. If unrelated failures appear, capture the exact failing test names and error messages before changing code.

- [ ] **Step 3: Check worktree state**

Run:

```powershell
git status --short
```

Expected: no output after Task 1 and Task 2 commits.

- [ ] **Step 4: Optional browser smoke test if a server is already running**

If a local WorldBuilder server is already running, open the game editor and verify manually:

- Import Houdini whitebox into the editor.
- Drag the character over terrain, road, and building roof.
- Confirm the character foot point lands on the visible surface.
- Click run and move with WASD over the imported whitebox.
- Confirm the character root stays visually grounded.

Do not start or stop long-running local services solely for this optional check unless the user asks for visible browser verification.
