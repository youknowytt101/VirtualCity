# Orbit Preview Three Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the orbit overlay with a Three.js-backed 3D atmosphere/orbit renderer while keeping the existing MapLibre globe, satellite icons, and frontend pipeline intact.

**Architecture:** Keep MapLibre in charge of map state and interactions. Add a vendored Three.js runtime under `/static`, then refactor `orbit-preview.js` so a Three.js scene renders the atmosphere sphere and orbit polylines while the existing 2D label canvas keeps the hex satellite glyphs and text. Reuse current TLE sampling and time-scale logic.

**Tech Stack:** MapLibre GL JS, Three.js, existing `satellite.js`, 2D canvas, existing Python static file server.

---

### Task 1: Add Three.js runtime and hook it into the page

**Files:**
- Create: `Scripts/web_assets/three/three.min.js`
- Modify: `Scripts/app/area_picker/frontend/index.html:253-256`
- Modify: `Scripts/app/area_picker/server.py:1314-1320`
- Modify: `tests/test_area_picker.py:143-148,530-545`

- [ ] **Step 1: Add the vendored runtime**

```text
Download the browser UMD build of Three.js into `Scripts/web_assets/three/three.min.js` so it is served from `/static/three/three.min.js`.
```

- [ ] **Step 2: Load Three.js before `orbit-preview.js`**

```html
<script src="/static/three/three.min.js"></script>
<script src="/area-picker/orbit-preview.js?v=__VERSION__"></script>
```

- [ ] **Step 3: Include the new asset in the frontend version hash**

```python
for name in ("app.js", "orbit-preview.js", "styles.css", "index.html", "three/three.min.js"):
    ...
```

- [ ] **Step 4: Extend the frontend tests to assert the new script tag and version hashing**

```python
self.assertIn('/static/three/three.min.js', _PICKER_FRONTEND)
self.assertIn("three/three.min.js", source)
```

### Task 2: Replace the orbit renderer with a Three.js overlay

**Files:**
- Modify: `Scripts/app/area_picker/frontend/orbit-preview.js`
- Modify: `Scripts/app/area_picker/frontend/styles.css:119-130`

- [ ] **Step 1: Write a failing sanity check for the new overlay entry points**

```python
self.assertIn("THREE", _PICKER_ORBIT_JS)
self.assertIn("drawAtmosphere", _PICKER_ORBIT_JS)
self.assertIn("drawOrbitLines", _PICKER_ORBIT_JS)
```

- [ ] **Step 2: Replace the WebGL point/shader path with a Three.js scene manager**

```javascript
var threeRenderer = new THREE.WebGLRenderer({ canvas: threeCanvas, alpha: true, antialias: true, preserveDrawingBuffer: true });
var threeScene = new THREE.Scene();
var threeCamera = new THREE.PerspectiveCamera(...);
var atmosphereMesh = new THREE.Mesh(new THREE.SphereGeometry(1.03, 64, 64), new THREE.MeshBasicMaterial({ color: 0x7faeff, transparent: true, opacity: 0.18, blending: THREE.AdditiveBlending, depthWrite: false }));
```

- [ ] **Step 3: Build orbit line geometry from the existing sampled satellite positions**

```javascript
var geometry = new THREE.BufferGeometry();
geometry.setAttribute('position', new THREE.Float32BufferAttribute(points, 3));
var line = new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.3 }));
```

- [ ] **Step 4: Keep the 2D label canvas for the existing hex spacecraft glyphs**

```javascript
drawSpacecraftGlyph(body, geom, nowDate, alpha);
drawLabel(body, projected, alpha);
```

- [ ] **Step 5: Keep the overlay canvas stack and make the Three canvas sit underneath labels**

```css
.space-three-canvas { position: absolute; inset: 0; z-index: 430; pointer-events: none; }
.space-label-canvas { z-index: 431; }
```

### Task 3: Verify rendering and regressions

**Files:**
- Modify: `tests/test_area_picker.py`
- Verify: `Scripts/app/area_picker/frontend/orbit-preview.js`

- [ ] **Step 1: Run the focused test file**

```bash
python -m pytest tests/test_area_picker.py -q
```

- [ ] **Step 2: Confirm the new asset and script references are present**

```text
Expected: tests pass and the new Three.js script tag is present in the frontend HTML snapshot.
```

- [ ] **Step 3: Confirm the overlay still mounts once and still keeps the existing satellite icon path**

```text
Expected: the page still uses `window.VirtualCityOrbitPreview.mount(...)`, and the 2D hex glyph path stays intact.
```
