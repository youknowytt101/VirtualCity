# Cloud Assets Browser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first-pass cloud asset browser in the game editor right sidebar.

**Architecture:** Add a local manifest-backed `/cloud-assets` server endpoint and a focused `cloud_assets.js` frontend module that renders into the existing `云端资产` tab. The server payload keeps the same shape a future real cloud service can return.

**Tech Stack:** Python `http.server`-style app in `Scripts/app/area_picker/server.py`; plain browser JavaScript modules under `Scripts/app/area_picker/frontend`; existing CSS in `styles.css`; regression coverage in `tests/test_area_picker.py`.

## Global Constraints

- First version only displays the cloud asset library.
- Do not implement real upload.
- Do not apply materials to selected objects.
- Keep the bottom `工程资产目录` as the project-local asset browser.
- Include two built-in material assets: `UEPerson 主材质` as `MeshPhysicalMaterial`, and `卡通渲染材质` as `MeshToonMaterial`.

---

### Task 1: Server Cloud Asset Payload

**Files:**
- Modify: `Scripts/app/area_picker/server.py`
- Test: `tests/test_area_picker.py`

**Interfaces:**
- Produces: `_cloud_assets_status() -> dict`
- Produces HTTP: `GET /cloud-assets`

- [ ] **Step 1: Write the failing test**

Add assertions to `tests/test_area_picker.py` checking:

```python
server_source = SERVER_PATH.read_text(encoding="utf-8")
self.assertIn("def _cloud_assets_status", server_source)
self.assertIn("parsed.path == '/cloud-assets'", server_source)
self.assertIn("'ueperson-body-material'", server_source)
self.assertIn("'toon-render-material'", server_source)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_area_picker.py -k cloud_assets -v`

Expected: FAIL because `_cloud_assets_status` and `/cloud-assets` do not exist yet.

- [ ] **Step 3: Implement the server payload**

Add `_cloud_asset_records()` and `_cloud_assets_status()` near the scene asset helpers. Add a GET route for `/cloud-assets` that calls `_cloud_assets_status()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_area_picker.py -k cloud_assets -v`

Expected: PASS.

### Task 2: Right Sidebar Cloud Asset UI

**Files:**
- Modify: `Scripts/app/area_picker/frontend/index.html`
- Create: `Scripts/app/area_picker/frontend/cloud_assets.js`
- Modify: `Scripts/app/area_picker/frontend/styles.css`
- Modify: `Scripts/app/area_picker/server.py`
- Test: `tests/test_area_picker.py`

**Interfaces:**
- Consumes: `GET /cloud-assets`
- Produces browser global: `window.VC_CLOUD_ASSETS.refresh()`

- [ ] **Step 1: Write the failing test**

Add assertions to `tests/test_area_picker.py` checking:

```python
self.assertIn('id="cloud-asset-browser"', game_panel)
self.assertIn('/area-picker/cloud_assets.js?v=__VERSION__', _PICKER_INDEX_HTML)
self.assertIn("fetch('/cloud-assets')", cloud_js)
self.assertIn("function renderCloudAssets", cloud_js)
self.assertIn("window.VC_CLOUD_ASSETS", cloud_js)
self.assertIn(".cloud-asset-browser", _PICKER_STYLES)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_area_picker.py -k cloud_assets -v`

Expected: FAIL because the UI module and mount points do not exist yet.

- [ ] **Step 3: Implement HTML, JS, and CSS**

Add mount markup inside the existing `.cloud-assets-panel`; add `cloud_assets.js` to the HTML script list and `_frontend_asset_version()` asset list; render compact category buttons and material cards.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_area_picker.py -k cloud_assets -v`

Expected: PASS.

### Task 3: Full Relevant Verification

**Files:**
- Test only.

**Interfaces:**
- Confirms all area picker static tests still pass.

- [ ] **Step 1: Run focused tests**

Run: `python -m pytest tests/test_area_picker.py -k cloud_assets -v`

Expected: PASS.

- [ ] **Step 2: Run full relevant test file**

Run: `python -m pytest tests/test_area_picker.py`

Expected: PASS.
