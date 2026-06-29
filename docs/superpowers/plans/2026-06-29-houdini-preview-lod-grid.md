# Houdini Preview LOD Grid Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed Houdini preview grid with a stable DCC-style display space: fixed origin, XYZ axes, camera orbit, and a screen-density LOD grid plane.

**Architecture:** Keep the change inside `Scripts/app/area_picker/frontend/houdini_preview.js`. The model is positioned into a stable Z-up preview space; axes and grid belong to that space; the camera orbits the origin instead of rotating the model. The grid is rebuilt as lightweight `LineSegments` when the camera/viewport implies a new nice-number spacing.

**Tech Stack:** Plain browser JavaScript, Three.js already loaded by the area picker, Python unittest guard tests in `tests/test_area_picker.py`.

---

### Task 1: Update Guard Tests First

**Files:**
- Modify: `tests/test_area_picker.py`

- [x] **Step 1: Replace the old fixed-grid/model-turntable assertions**

Change `test_houdini_preview_uses_fixed_camera_light_and_model_turntable` so it expects:

```python
    def test_houdini_preview_uses_stable_display_space_camera_orbit_and_lod_grid(self):
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        self.assertNotIn("function createPreviewGround()", preview_js)
        self.assertNotIn("new THREE.ShadowMaterial", preview_js)
        self.assertNotIn("PREVIEW_GRID_HALF_EXTENT", preview_js)
        self.assertNotIn("new THREE.GridHelper", preview_js)
        self.assertIn("var previewGrid = null;", preview_js)
        self.assertIn("var previewAxes = null;", preview_js)
        self.assertIn("function createPreviewAxes()", preview_js)
        self.assertIn("function updatePreviewGridLod()", preview_js)
        self.assertIn("function niceGridStep(rawStep)", preview_js)
        self.assertIn("function updatePreviewCameraOrbit()", preview_js)
        self.assertIn("previewYaw += model ? 0.005 : 0.02;", preview_js)
        self.assertIn("updatePreviewCameraOrbit();", preview_js)
        self.assertNotIn("previewRoot.rotation.z += model ? 0.005 : 0.02;", preview_js)
        self.assertIn("camera.position.set(", preview_js)
```

- [x] **Step 2: Update the ground-plane guard**

Change `test_houdini_preview_grid_stays_below_model` so it expects custom grid geometry:

```python
    def test_houdini_preview_grid_stays_below_model(self):
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        self.assertIn("var PREVIEW_GRID_Z = -0.02;", preview_js)
        self.assertIn("new THREE.LineSegments(new THREE.BufferGeometry(), gridMaterial)", preview_js)
        self.assertIn("gridMaterial.depthWrite = false;", preview_js)
        self.assertIn("positions.push(-snappedExtent, point, PREVIEW_GRID_Z, snappedExtent, point, PREVIEW_GRID_Z);", preview_js)
        self.assertIn("positions.push(point, -snappedExtent, PREVIEW_GRID_Z, point, snappedExtent, PREVIEW_GRID_Z);", preview_js)
        self.assertIn("0, 0, PREVIEW_GRID_Z,", preview_js)
        self.assertNotIn("grid.material.depthTest = false;", preview_js)
        self.assertNotIn("originMaterial.depthTest = false;", preview_js)
        self.assertNotIn("grid.renderOrder = 2;", preview_js)
        self.assertNotIn("renderOrder = 3;", preview_js)
```

- [x] **Step 3: Run the targeted tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_area_picker.py::TestPickerHtml::test_houdini_preview_uses_stable_display_space_camera_orbit_and_lod_grid tests/test_area_picker.py::TestPickerHtml::test_houdini_preview_grid_stays_below_model -q
```

Expected: fails because `previewGrid`, `createPreviewAxes`, `updatePreviewGridLod`, and camera-orbit animation do not exist yet.

### Task 2: Implement Stable Preview Space and LOD Grid

**Files:**
- Modify: `Scripts/app/area_picker/frontend/houdini_preview.js`

- [x] **Step 1: Replace fixed grid constants with display-space constants**

Use:

```javascript
  var PREVIEW_GRID_Z = -0.02;
  var PREVIEW_GRID_TARGET_PIXELS = 22;
  var PREVIEW_GRID_MIN_EXTENT = 4;
  var PREVIEW_AXIS_MIN_LENGTH = 3;
  var previewGrid = null;
  var previewAxes = null;
  var previewGridKey = '';
```

- [x] **Step 2: Replace `createPreviewGrid()`**

Create a `LineSegments` grid and call `createPreviewAxes()`:

```javascript
  function createPreviewGrid() {
    var THREE = window.THREE;
    var gridMaterial = new THREE.LineBasicMaterial({
      color: 0xb7bec6,
      transparent: true,
      opacity: 0.32
    });
    gridMaterial.depthWrite = false;
    previewGrid = new THREE.LineSegments(new THREE.BufferGeometry(), gridMaterial);
    scene.add(previewGrid);
    createPreviewAxes();
  }
```

- [x] **Step 3: Add `createPreviewAxes()`**

Create X/Y/Z axis lines rooted at origin:

```javascript
  function createPreviewAxes() {
    var THREE = window.THREE;
    var axisMaterial = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.72
    });
    axisMaterial.depthWrite = false;
    previewAxes = new THREE.LineSegments(new THREE.BufferGeometry(), axisMaterial);
    scene.add(previewAxes);
  }
```

- [x] **Step 4: Add LOD helper functions**

Use nice-number spacing and current camera projection:

```javascript
  function niceGridStep(rawStep) {
    if (!isFinite(rawStep) || rawStep <= 0) return 1;
    var power = Math.pow(10, Math.floor(Math.log(rawStep) / Math.LN10));
    var normalized = rawStep / power;
    if (normalized <= 1) return power;
    if (normalized <= 2) return 2 * power;
    if (normalized <= 5) return 5 * power;
    return 10 * power;
  }

  function gridWorldPerPixel() {
    if (!host || !camera) return 1;
    var h = Math.max(1, host.clientHeight || 1);
    var target = new window.THREE.Vector3(0, 0, previewTargetZ);
    var distance = Math.max(0.001, camera.position.distanceTo(target));
    var visibleHeight = 2 * distance * Math.tan(camera.fov * Math.PI / 360);
    return visibleHeight / h;
  }
```

- [x] **Step 5: Add `updatePreviewGridLod()`**

Rebuild line geometry only when spacing/extent changes:

```javascript
  function updatePreviewGridLod() {
    if (!previewGrid || !previewAxes) return;
    var THREE = window.THREE;
    var spacing = niceGridStep(gridWorldPerPixel() * PREVIEW_GRID_TARGET_PIXELS);
    var extent = Math.max(PREVIEW_GRID_MIN_EXTENT, previewOrbitRadius * 2.2, spacing * 12);
    var lineCount = Math.max(1, Math.ceil(extent / spacing));
    var snappedExtent = lineCount * spacing;
    var axisLength = Math.max(PREVIEW_AXIS_MIN_LENGTH, snappedExtent);
    var key = spacing + ':' + lineCount + ':' + axisLength;
    if (key === previewGridKey) return;
    previewGridKey = key;

    var positions = [];
    for (var i = -lineCount; i <= lineCount; i++) {
      var point = i * spacing;
      positions.push(-snappedExtent, point, PREVIEW_GRID_Z, snappedExtent, point, PREVIEW_GRID_Z);
      positions.push(point, -snappedExtent, PREVIEW_GRID_Z, point, snappedExtent, PREVIEW_GRID_Z);
    }
    previewGrid.geometry.dispose();
    previewGrid.geometry = new THREE.BufferGeometry();
    previewGrid.geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));

    updatePreviewAxes(axisLength);
  }
```

- [x] **Step 6: Add `updatePreviewAxes(axisLength)`**

Keep axes at origin:

```javascript
  function updatePreviewAxes(axisLength) {
    var THREE = window.THREE;
    var positions = [
      -axisLength, 0, PREVIEW_GRID_Z + 0.003, axisLength, 0, PREVIEW_GRID_Z + 0.003,
      0, -axisLength, PREVIEW_GRID_Z + 0.003, 0, axisLength, PREVIEW_GRID_Z + 0.003,
      0, 0, PREVIEW_GRID_Z, 0, 0, Math.max(PREVIEW_AXIS_MIN_LENGTH, axisLength * 0.16)
    ];
    var colors = [
      0.86, 0.34, 0.25, 0.86, 0.34, 0.25,
      0.35, 0.68, 0.55, 0.35, 0.68, 0.55,
      0.36, 0.52, 0.82, 0.36, 0.52, 0.82
    ];
    previewAxes.geometry.dispose();
    previewAxes.geometry = new THREE.BufferGeometry();
    previewAxes.geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    previewAxes.geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
  }
```

- [x] **Step 7: Update framing and tick**

Call `updatePreviewGridLod()` after camera placement. Replace model turntable with camera orbit:

```javascript
  function updatePreviewCameraOrbit() {
    var d = Math.max(0.5, previewOrbitRadius);
    var horizontal = d * 2.0;
    camera.position.set(
      Math.cos(previewYaw) * horizontal,
      Math.sin(previewYaw) * horizontal,
      d * 1.0 + previewTargetZ
    );
    camera.lookAt(0, 0, previewTargetZ);
    updatePreviewGridLod();
  }
```

In `tick()`:

```javascript
    if (placeholder.visible || model) {
      previewYaw += model ? 0.005 : 0.02;
      updatePreviewCameraOrbit();
    } else {
      updatePreviewGridLod();
    }
```

### Task 3: Verify

**Files:**
- Verify: `Scripts/app/area_picker/frontend/houdini_preview.js`
- Verify: `tests/test_area_picker.py`

- [x] **Step 1: Run targeted tests**

Run:

```powershell
python -m pytest tests/test_area_picker.py::TestPickerHtml::test_houdini_preview_uses_stable_display_space_camera_orbit_and_lod_grid tests/test_area_picker.py::TestPickerHtml::test_houdini_preview_grid_stays_below_model -q
```

Expected: `2 passed`.

- [x] **Step 2: Run JavaScript syntax check**

Run:

```powershell
node --check Scripts/app/area_picker/frontend/houdini_preview.js
```

Expected: exit code 0 and no syntax errors.

- [x] **Step 3: Run area picker tests**

Run:

```powershell
python -m pytest tests/test_area_picker.py -q
```

Expected: all tests pass.

- [x] **Step 4: Review diff**

Run:

```powershell
git diff -- Scripts/app/area_picker/frontend/houdini_preview.js tests/test_area_picker.py
```

Expected: only the Houdini preview grid/camera assertions and implementation changed.
