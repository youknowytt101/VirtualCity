"""Offline tests for area_picker state and progress helpers."""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))

import area_picker
from app.area_picker import software_paths
import houdini_build.status as houdini_status_writer
import manual_review
import pipeline_status

FRONTEND_ROOT = Path(area_picker.FRONTEND_ROOT)
_PICKER_INDEX_HTML = area_picker._HTML
_PICKER_STYLES = (FRONTEND_ROOT / "styles.css").read_text(encoding="utf-8")
_PICKER_SCRIPT_NAMES = (
    "vc_glb.js",
    "render_profile.js",
    "viewport_grid.js",
    "gw_core.js",
    "gw_history.js",
    "gw_scene_state.js",
    "gw_scene_persistence.js",
    "gw_commands.js",
    "gw_character.js",
    "gw_play.js",
    "gw_camera.js",
    "gw_assets.js",
    "gw_outliner.js",
    "gw_inspector.js",
    "game_workbench.js",
    "houdini_preview.js",
    "scene_project.js",
    "scene_assets.js",
    "cloud_assets.js",
    "workspace.js",
    "selection_search.js",
    "pipeline_status.js",
    "dcc_bridge.js",
    "app.js",
)
_PICKER_APP_JS = "\n".join(
    (FRONTEND_ROOT / name).read_text(encoding="utf-8")
    for name in _PICKER_SCRIPT_NAMES
)
_PICKER_FRONTEND = "\n".join([_PICKER_INDEX_HTML, _PICKER_STYLES, _PICKER_APP_JS])


class TestProgressView(unittest.TestCase):
    """进度来自真相源投影，不再解析 stdout 日志。"""

    def test_houdini_stage_maps_into_high_band(self):
        run = {"phase": "houdini_recook", "status": "running",
               "progress": {"step": 4, "total": 7, "label": "[Houdini 4/7] 全链路验证"}}
        pv = pipeline_status.progress_view(run)
        self.assertGreater(pv["pct"], 85)
        self.assertLessEqual(pv["pct"], 99)
        self.assertEqual(pv["label"], "[Houdini 4/7] 全链路验证")

    def test_completed_run_reaches_full(self):
        run = {"phase": "pipeline_completed", "status": "completed",
               "progress": {"step": 7, "total": 7, "label": "done"}}
        self.assertEqual(pipeline_status.progress_view(run)["pct"], 100)

    def test_acquire_phase_uses_anchor_and_label(self):
        run = {"phase": "acquire_dem", "status": "running", "progress": {}}
        pv = pipeline_status.progress_view(run)
        self.assertEqual(pv["pct"], 38)
        self.assertEqual(pv["label"], "获取地形数据")


class TestRollingLogOffset(unittest.TestCase):
    """日志窗口滚动后，全局序号必须单调增长，前端据此消费不丢行。"""

    def _isolated_state(self):
        previous = dict(area_picker._state)
        with area_picker._state_lock:
            area_picker._reset_log("log_lines", "log_offset")
        return previous

    def test_offset_tracks_dropped_lines(self):
        previous = self._isolated_state()
        try:
            total = area_picker._MAX_LOG_LINES + 25
            with area_picker._state_lock:
                for i in range(total):
                    area_picker._append_log("log_lines", "log_offset", f"line-{i}")
            self.assertEqual(len(area_picker._state["log_lines"]), area_picker._MAX_LOG_LINES)
            self.assertEqual(area_picker._state["log_offset"], 25)
            self.assertEqual(area_picker._state["log_lines"][0], "line-25")
        finally:
            with area_picker._state_lock:
                area_picker._state.update(previous)

    def test_frontend_consumption_loses_no_line_across_rollover(self):
        previous = self._isolated_state()
        try:
            total = area_picker._MAX_LOG_LINES + 40
            consumed = []
            next_seq = 0
            with area_picker._state_lock:
                for i in range(total):
                    area_picker._append_log("log_lines", "log_offset", f"line-{i}")
                    base = area_picker._state["log_offset"]
                    window = list(area_picker._state["log_lines"])
                    global_end = base + len(window)
                    if global_end > next_seq:
                        start = max(next_seq, base) - base
                        consumed.extend(window[start:])
                        next_seq = global_end
            self.assertEqual(consumed, [f"line-{i}" for i in range(total)])
        finally:
            with area_picker._state_lock:
                area_picker._state.update(previous)


class TestPickerHtml(unittest.TestCase):
    def test_picker_frontend_is_split_into_static_assets(self):
        self.assertTrue((FRONTEND_ROOT / "index.html").exists())
        self.assertTrue((FRONTEND_ROOT / "styles.css").exists())
        self.assertTrue((FRONTEND_ROOT / "app.js").exists())
        for name in _PICKER_SCRIPT_NAMES:
            self.assertTrue((FRONTEND_ROOT / name).exists())
            self.assertIn(f"/area-picker/{name}?v=__VERSION__", _PICKER_INDEX_HTML)
        self.assertIn('/area-picker/styles.css?v=__VERSION__', _PICKER_INDEX_HTML)
        self.assertNotIn('/area-picker/asset_dir.js', _PICKER_INDEX_HTML)
        self.assertIn("window.VC_CONFIG", _PICKER_INDEX_HTML)
        self.assertNotIn("<style>", _PICKER_INDEX_HTML)
        self.assertIn("def _frontend_static", Path(area_picker.__file__).read_text(encoding="utf-8"))

    def test_ai_frontend_handoff_maps_user_symptoms_to_code(self):
        handoff_path = FRONTEND_ROOT / "AI_FRONTEND_HANDOFF.md"
        self.assertTrue(handoff_path.exists())
        handoff = handoff_path.read_text(encoding="utf-8")
        expected_markers = (
            "AI_FRONTEND_HANDOFF.md",
            "API_CONTRACT.md",
            "白盒预览不显示",
            "houdini_preview.js",
            "VC_HOUDINI_PREVIEW.update",
            "/whitebox.glb",
            "test_houdini_panel_preview_uses_explicit_whitebox_contract",
            "Houdini 按钮不可用",
            "pipeline_status.js",
            "applySharedStatus",
            "/health",
            "地图框选异常",
            "selection_search.js",
            "setSelection",
            "/tiles",
            "DCC 路径保存失败",
            "dcc_bridge.js",
            "saveSoftwarePath",
            "/software-paths",
            "底部工程资产目录不显示",
            "scene_assets.js",
            "loadSceneAssets",
            "/scene-assets",
            "/scene-asset-file",
            "_scene_asset_file_path",
            "/sync-whitebox-to-scene-assets",
            "syncHoudiniWhiteboxToAssets",
            "_sync_houdini_whitebox_to_scene_assets",
            "地点搜索异常",
            "bindLocationSearch",
            "/geocode",
            "区域导航不显示",
            "loadRegionNav",
            "/area-picker/regions.json",
            "底图或世界轮廓不显示",
            "WORLD_GEOJSON_URL",
            "/area-picker/world_countries.json",
        )
        for marker in expected_markers:
            self.assertIn(marker, handoff)
        self.assertNotIn("asset_dir.js", handoff)
        self.assertNotIn("/asset-dir", handoff)
        readme = (FRONTEND_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("AI_FRONTEND_HANDOFF.md", readme)
        self.assertIn("API_CONTRACT.md", readme)
        self.assertNotIn("/asset-dir", readme)

    def test_ai_frontend_handoff_guard_tests_exist(self):
        handoff = (FRONTEND_ROOT / "AI_FRONTEND_HANDOFF.md").read_text(encoding="utf-8")
        source = Path(__file__).read_text(encoding="utf-8")
        guard_tests = sorted(set(re.findall(r"`(test_[A-Za-z0-9_]+)`", handoff)))
        self.assertTrue(guard_tests)
        for test_name in guard_tests:
            with self.subTest(test_name=test_name):
                self.assertIn(f"def {test_name}", source)

    def test_api_contract_documents_frontend_routes_and_backend_handlers(self):
        contract_path = FRONTEND_ROOT / "API_CONTRACT.md"
        self.assertTrue(contract_path.exists())
        contract = contract_path.read_text(encoding="utf-8")
        expected_markers = (
            "/health",
            "refreshServiceState",
            "_service_payload",
            "/status",
            "pollStatus",
            "_build_status_payload",
            "/events",
            "startStatusStream",
            "_sse_events",
            "/jobs",
            "submitSelectedArea",
            "do_POST",
            "/whitebox.glb",
            "VC_HOUDINI_PREVIEW.update",
            "_serve_whitebox_glb",
            "/selection",
            "restoreRememberedSelection",
            "_post_selection",
            "/software-paths",
            "saveSoftwarePath",
            "_post_software_paths",
            "/scene-assets",
            "loadSceneAssets",
            "_scene_assets_status",
            "/scene-asset-file",
            "_scene_asset_file_path",
            "/sync-whitebox-to-scene-assets",
            "syncHoudiniWhiteboxToAssets",
            "_sync_houdini_whitebox_to_scene_assets",
            "/area-picker/regions.json",
            "loadRegionNav",
            "/area-picker/basemap-style.json",
            "VECTOR_STYLE_URL",
            "/area-picker/world_countries.json",
            "WORLD_GEOJSON_URL",
            "_frontend_static",
            "/static/",
            "_static",
        )
        for marker in expected_markers:
            self.assertIn(marker, contract)
        self.assertNotIn("## GET and POST /asset-dir", contract)
        self.assertNotIn("asset_dir.js", contract)

    def test_frontend_scripts_have_ai_handoff_headers(self):
        for name in _PICKER_SCRIPT_NAMES:
            with self.subTest(script=name):
                header = "\n".join((FRONTEND_ROOT / name).read_text(encoding="utf-8").splitlines()[:6])
                self.assertIn("// Domain:", header)
                self.assertIn("// Owns:", header)
                self.assertIn("// AI handoff:", header)

    def test_houdini_status_updates_use_shared_frontend_projection(self):
        self.assertIn("function applySharedStatus(d)", _PICKER_FRONTEND)
        self.assertGreaterEqual(_PICKER_FRONTEND.count("applySharedStatus(d);"), 2)

    def test_houdini_preview_honors_preview_ready_gate(self):
        self.assertIn("var previewReady = !!asset.preview_ready;", _PICKER_FRONTEND)
        self.assertIn("if (!previewReady || !whitebox.available)", _PICKER_FRONTEND)

    def test_houdini_preview_uses_terrain_mesh_for_preview_pivot(self):
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        self.assertIn("function findLayerObject(root, layerKey)", preview_js)
        self.assertIn("function computeTerrainPreviewPivot(model)", preview_js)
        self.assertIn("var terrainObject = findLayerObject(model, 'terrain');", preview_js)
        self.assertIn("var buildingsObject = findLayerObject(model, 'buildings');", preview_js)
        self.assertIn("var roadsObject = findLayerObject(model, 'roads');", preview_js)
        self.assertIn("var frameObject = buildingsObject || roadsObject || terrainObject || model;", preview_js)
        self.assertIn("function fitModelToPreview(model, pivot)", preview_js)
        self.assertIn("model.scale.setScalar(scale);", preview_js)
        self.assertIn("model.position.set(-centerX * scale, -centerY * scale, -groundZ * scale);", preview_js)
        self.assertNotIn("model.position.sub(center);", preview_js)

    def test_shared_render_profile_module_contract(self):
        profile_path = FRONTEND_ROOT / "render_profile.js"
        self.assertTrue(profile_path.exists())
        profile_js = profile_path.read_text(encoding="utf-8")
        self.assertIn("window.VC_RENDER_PROFILE", profile_js)
        self.assertIn("function createRenderer(THREE, options)", profile_js)
        self.assertIn("function configureColorManagement(THREE)", profile_js)
        self.assertIn("function createDefaultLighting(THREE, scene, options)", profile_js)
        self.assertIn("scene.add(sun, sun.target);", profile_js)
        self.assertIn("function applyEnvironment(THREE, renderer, scene, options)", profile_js)
        self.assertIn("new THREE.PMREMGenerator(renderer)", profile_js)
        self.assertIn("generator.fromScene(environmentScene", profile_js)
        self.assertIn("scene.environment = target.texture;", profile_js)

    def test_shared_render_profile_defines_shadow_quality_tiers(self):
        profile_js = (FRONTEND_ROOT / "render_profile.js").read_text(encoding="utf-8")
        self.assertIn("var SHADOW_QUALITY = {", profile_js)
        self.assertIn("low: { mapSize: 1024", profile_js)
        self.assertIn("medium: { mapSize: 2048", profile_js)
        self.assertIn("high: { mapSize: 4096", profile_js)
        self.assertIn("cinematic: { mapSize: 4096", profile_js)
        self.assertIn("function applyShadowQuality(THREE, light, qualityName)", profile_js)

    def test_houdini_preview_uses_shared_render_profile(self):
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        self.assertIn("window.VC_RENDER_PROFILE.configureColorManagement(THREE);", preview_js)
        self.assertIn("renderer = window.VC_RENDER_PROFILE.createRenderer(THREE, {", preview_js)
        self.assertIn("shadowQuality: 'medium'", preview_js)
        self.assertIn("var lighting = window.VC_RENDER_PROFILE.createDefaultLighting(THREE, scene, {", preview_js)
        self.assertIn("includeAmbient: false", preview_js)
        self.assertIn("previewEnvironment = window.VC_RENDER_PROFILE.applyEnvironment(THREE, renderer, scene, {", preview_js)
        self.assertIn("scene.background = new THREE.Color(0x666a6c);", preview_js)
        self.assertIn("previewSun = lighting.sun;", preview_js)
        self.assertIn("previewEnvironment.dispose();", preview_js)
        self.assertNotIn("renderer.shadowMap.type = THREE.PCFSoftShadowMap;", preview_js)
        self.assertNotIn("renderer.toneMapping = THREE.ACESFilmicToneMapping;", preview_js)
        self.assertNotIn("sun.shadow.mapSize.set(4096, 4096);", preview_js)
        self.assertNotIn("sun.position.set(8, 14, 10);", preview_js)
        self.assertNotIn("sun.shadow.camera.far = 400;", preview_js)
        self.assertNotIn("sun.shadow.camera.left = -60;", preview_js)
        self.assertNotIn("sun.shadow.camera.right = 60;", preview_js)
        self.assertNotIn("sun.shadow.camera.top = 60;", preview_js)
        self.assertNotIn("sun.shadow.camera.bottom = -60;", preview_js)

        self.assertNotIn("AmbientLight", preview_js)

    def test_houdini_preview_replaces_imported_materials_with_toon_whitebox_material(self):
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        self.assertIn("function applyPreviewWhiteboxMaterial(object)", preview_js)
        self.assertIn("new THREE.MeshToonMaterial({", preview_js)
        self.assertIn("color: WHITEBOX_PREVIEW_COLOR", preview_js)
        self.assertIn("gradientMap: window.VC_GW && window.VC_GW.getToonGradientMap", preview_js)
        self.assertIn("emissive: 0x000000", preview_js)
        self.assertNotIn("function previewWhiteboxColor(", preview_js)
        self.assertIn("disposeMaterial(object.material);", preview_js)
        self.assertIn("object.material = applyPreviewWhiteboxMaterial(object);", preview_js)

    def test_houdini_preview_adds_character_style_black_outline_to_whitebox(self):
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        self.assertIn("var WHITEBOX_PREVIEW_OUTLINE_THICKNESS", preview_js)
        self.assertIn("function attachPreviewWhiteboxOutline(object)", preview_js)
        self.assertIn("window.VC_GW.createOutlineMesh(object.geometry, WHITEBOX_PREVIEW_OUTLINE_THICKNESS)", preview_js)
        self.assertIn("outline.userData.previewWhiteboxOutline = true;", preview_js)
        self.assertIn("object.add(outline);", preview_js)
        self.assertIn("if (object.userData && object.userData.outline) return;", preview_js)
        self.assertIn("attachPreviewWhiteboxOutline(object);", preview_js)

    def test_glb_loader_does_not_force_double_side_for_every_model(self):
        glb_js = (FRONTEND_ROOT / "vc_glb.js").read_text(encoding="utf-8")
        self.assertNotIn("var DoubleSide = window.THREE && window.THREE.DoubleSide;", glb_js)
        self.assertNotIn("m.side = DoubleSide;", glb_js)

    def test_whitebox_import_keeps_double_side_scoped_to_whitebox_layers(self):
        assets_js = (FRONTEND_ROOT / "gw_assets.js").read_text(encoding="utf-8")
        self.assertIn("function createWhiteboxToonMaterial(sourceMaterial, layerKey)", assets_js)
        self.assertIn("new THREE.MeshToonMaterial({", assets_js)
        self.assertIn("gradientMap: GW.getToonGradientMap ? GW.getToonGradientMap() : null", assets_js)
        self.assertIn("side: THREE.DoubleSide", assets_js)
        self.assertIn("mesh.material = createWhiteboxToonMaterial(mesh.material, key);", assets_js)

    def test_whitebox_import_adds_character_style_black_outline(self):
        assets_js = (FRONTEND_ROOT / "gw_assets.js").read_text(encoding="utf-8")
        self.assertIn("var WHITEBOX_OUTLINE_THICKNESS", assets_js)
        self.assertIn("function attachWhiteboxToonOutline(mesh, layerKey)", assets_js)
        self.assertIn("GW.createOutlineMesh(mesh.geometry, WHITEBOX_OUTLINE_THICKNESS", assets_js)
        self.assertIn("outline.userData.whiteboxOutline = true;", assets_js)
        self.assertIn("mesh.add(outline);", assets_js)
        self.assertIn("if (mesh.userData && mesh.userData.outline) return;", assets_js)
        self.assertIn("attachWhiteboxToonOutline(mesh, key);", assets_js)

    def test_houdini_preview_uses_shared_shader_viewport_grid(self):
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        self.assertIn("function createPreviewGround()", preview_js)
        self.assertIn("new THREE.ShadowMaterial", preview_js)
        self.assertNotIn("PREVIEW_GRID_HALF_EXTENT", preview_js)
        self.assertNotIn("new THREE.GridHelper", preview_js)
        self.assertIn("var previewGrid = null;", preview_js)
        self.assertNotIn("var previewAxes = null;", preview_js)
        self.assertIn("window.VC_VIEWPORT_GRID.create(scene, camera", preview_js)
        self.assertIn("window.VC_VIEWPORT_GRID.update(previewGrid, camera);", preview_js)
        self.assertIn("window.VC_VIEWPORT_GRID.dispose(previewGrid);", preview_js)
        self.assertIn("minorColor: 0xc8cdd1", preview_js)
        self.assertIn("majorColor: 0xc8cdd1", preview_js)
        self.assertIn("minorAlpha: 0.24", preview_js)
        self.assertIn("majorAlpha: 0.24", preview_js)
        self.assertIn("axisXColor: 0xffffff", preview_js)
        self.assertIn("axisYColor: 0xffffff", preview_js)
        self.assertIn("axisInnerPx: 0.25", preview_js)
        self.assertIn("axisOuterPx: 0.85", preview_js)
        self.assertNotIn("function createPreviewAxes()", preview_js)
        self.assertNotIn("function updatePreviewGridLod()", preview_js)
        self.assertNotIn("function niceGridStep(rawStep)", preview_js)
        self.assertIn("function updatePreviewCameraOrbit()", preview_js)
        self.assertIn("if (model && phase === 'shown' && !previewDrag) previewYaw += 0.005;", preview_js)
        self.assertIn("updatePreviewCameraOrbit();", preview_js)
        self.assertNotIn("previewYaw += model ? 0.005 : 0.02;", preview_js)
        self.assertNotIn("previewRoot.rotation.z += model ? 0.005 : 0.02;", preview_js)
        self.assertIn("camera.position.set(", preview_js)

    def test_houdini_preview_grid_stays_visible_on_preview_origin_plane(self):
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        self.assertIn("var PREVIEW_GRID_Z = 0.02;", preview_js)
        self.assertIn("planeZ: PREVIEW_GRID_Z", preview_js)
        self.assertIn("showZAxis: false", preview_js)
        self.assertIn("axisLength: PREVIEW_AXIS_LENGTH", preview_js)
        self.assertNotIn("new THREE.LineSegments(new THREE.BufferGeometry(), gridMaterial)", preview_js)
        self.assertNotIn("positions.push(-snappedExtent, point, PREVIEW_GRID_Z, snappedExtent, point, PREVIEW_GRID_Z);", preview_js)
        self.assertNotIn("positions.push(point, -snappedExtent, PREVIEW_GRID_Z, point, snappedExtent, PREVIEW_GRID_Z);", preview_js)
        self.assertNotIn("grid.material.depthTest = false;", preview_js)
        self.assertNotIn("originMaterial.depthTest = false;", preview_js)
        self.assertNotIn("grid.renderOrder = 2;", preview_js)
        self.assertNotIn("renderOrder = 3;", preview_js)

    def test_shared_viewport_grid_module_contract(self):
        grid_path = FRONTEND_ROOT / "viewport_grid.js"
        self.assertTrue(grid_path.exists())
        grid_js = grid_path.read_text(encoding="utf-8")
        self.assertIn("window.VC_VIEWPORT_GRID", grid_js)
        self.assertIn("create: createViewportGrid", grid_js)
        self.assertIn("update: updateViewportGrid", grid_js)
        self.assertIn("dispose: disposeViewportGrid", grid_js)
        self.assertIn("new THREE.ShaderMaterial", grid_js)
        self.assertIn("fwidth(coord)", grid_js)
        self.assertIn("uViewProjectionInverse", grid_js)
        self.assertIn("uPlaneZ", grid_js)
        self.assertIn("uAxisInnerPx", grid_js)
        self.assertIn("uAxisOuterPx", grid_js)
        self.assertIn("showZAxis", grid_js)
        self.assertIn("fullscreen-triangle", grid_js)
        self.assertIn("rayDirection", grid_js)
        self.assertIn("grazingFade", grid_js)
        self.assertIn("float xAxisPx = abs(world.y) / max(fwidth(world.y), 0.000001);", grid_js)
        self.assertIn("float yAxisPx = abs(world.x) / max(fwidth(world.x), 0.000001);", grid_js)
        self.assertIn("float xAxis = 1.0 - smoothstep(uAxisInnerPx, uAxisOuterPx, xAxisPx);", grid_js)
        self.assertIn("float yAxis = 1.0 - smoothstep(uAxisInnerPx, uAxisOuterPx, yAxisPx);", grid_js)
        self.assertNotIn("axisHalfWidth", grid_js)
        self.assertNotIn("EDITOR_GRID_SIZE", grid_js)
        self.assertNotIn("updatePreviewGridLod", grid_js)

    def test_shared_viewport_grid_has_infinite_shader_fade_not_cpu_lod_rebuild(self):
        grid_path = FRONTEND_ROOT / "viewport_grid.js"
        self.assertTrue(grid_path.exists())
        grid_js = grid_path.read_text(encoding="utf-8")
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        self.assertIn("log10(worldPerPixel)", grid_js)
        self.assertIn("uLodPixels", grid_js)
        self.assertIn("uFadeStart", grid_js)
        self.assertIn("uFadeEnd", grid_js)
        self.assertNotIn("edgeFade", grid_js)
        self.assertNotIn("previewGridKey", grid_js)
        self.assertNotIn("geometry.dispose();\n    previewGrid.geometry = new THREE.BufferGeometry();", grid_js)
        self.assertNotIn("PREVIEW_GRID_DISTANCE_EXTENT_SCALE", preview_js)
        self.assertNotIn("function gridPlaneViewportExtent()", preview_js)
        self.assertNotIn("raycaster.setFromCamera(corners[i], camera);", preview_js)
        self.assertNotIn("host.offsetParent === null", preview_js)

    def test_houdini_preview_pauses_raf_when_not_visible_and_disposes_renderer(self):
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        self.assertIn("var previewVisible = false;", preview_js)
        self.assertIn("function scheduleTick()", preview_js)
        self.assertIn("function stopTick()", preview_js)
        self.assertIn("new IntersectionObserver(function(entries)", preview_js)
        self.assertIn("document.addEventListener('visibilitychange', updatePreviewVisibility);", preview_js)
        self.assertIn("window.addEventListener('pagehide', disposePreview);", preview_js)
        self.assertIn("renderer.dispose();", preview_js)
        self.assertIn("if (renderer.forceContextLoss) renderer.forceContextLoss();", preview_js)
        self.assertNotIn("rafId = requestAnimationFrame(tick);\n    if (!renderer || !host) return;", preview_js)

    def test_houdini_preview_supports_drag_orbit_and_wheel_zoom(self):
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        self.assertIn("var previewDrag = null;", preview_js)
        self.assertIn("host.addEventListener('pointerdown', beginPreviewDrag);", preview_js)
        self.assertIn("host.addEventListener('wheel', zoomPreview);", preview_js)
        self.assertIn("previewYaw -= dx * 0.01;", preview_js)
        self.assertIn("previewOrbitRadius = Math.max(1.2, Math.min(12, previewOrbitRadius * Math.exp(event.deltaY * 0.001)));", preview_js)

    def test_houdini_preview_surfaces_whitebox_diagnostics_and_identity(self):
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        self.assertIn("function modelStatsLabel(root, whitebox)", preview_js)
        self.assertIn(r"path.split(/[\\/]/).pop()", preview_js)
        self.assertIn("box.size_label", preview_js)
        self.assertIn("setMsg(modelStatsLabel(model, whitebox));", preview_js)
        self.assertIn("var message = whitebox.message || (err && err.message) || '预览加载失败';", preview_js)
        self.assertIn("setMsg('预览加载失败：' + message + '（点击重试）');", preview_js)
        self.assertIn("setMsg(whitebox.message || '');", preview_js)

    def test_houdini_preview_keeps_grid_camera_and_lights_fixed_between_generated_models(self):
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        self.assertIn("var previewSun = null;", preview_js)
        self.assertNotIn("previewShadowGround", preview_js)
        self.assertIn("var PREVIEW_SUN_DIRECTION = { x: 0.426, y: 0.721, z: 0.557 };", preview_js)
        self.assertIn("var PREVIEW_CAMERA_ORBIT_RADIUS = 4;", preview_js)
        self.assertIn("var PREVIEW_CAMERA_TARGET_Z = 1.2;", preview_js)
        self.assertIn("var PREVIEW_MODEL_TARGET_RADIUS = 2.8;", preview_js)
        self.assertIn("var PREVIEW_SUN_DISTANCE = 20;", preview_js)
        self.assertIn("var PREVIEW_SHADOW_EXTENT = 10;", preview_js)
        self.assertIn("function configurePreviewShadowRig()", preview_js)
        self.assertIn("function resetPreviewView()", preview_js)
        self.assertIn("fitModelToPreview(model, pivot);", preview_js)
        self.assertNotIn("function fitPreviewShadowRig(radius)", preview_js)
        self.assertNotIn("function frameView(radius, targetZ)", preview_js)
        self.assertNotIn("function frameRadius(radius)", preview_js)
        self.assertNotIn("frameView(pivot.radius, pivot.targetZ);", preview_js)
        self.assertNotIn("frameRadius(1.2);", preview_js)
        self.assertNotIn("fitPreviewShadowRig(previewOrbitRadius);", preview_js)
        self.assertNotIn("new THREE.PlaneGeometry(groundSize, groundSize)", preview_js)
        self.assertNotIn("var sunDistance = Math.max(20, safeRadius * 1.55);", preview_js)
        self.assertNotIn("var halfExtent = Math.max(60, safeRadius * 1.35);", preview_js)
        self.assertIn("shadowCamera.left = -PREVIEW_SHADOW_EXTENT;", preview_js)
        self.assertIn("shadowCamera.right = PREVIEW_SHADOW_EXTENT;", preview_js)
        self.assertIn("shadowCamera.updateProjectionMatrix();", preview_js)
        self.assertIn("previewSun.shadow.needsUpdate = true;", preview_js)

    def test_houdini_preview_keeps_terrain_roads_and_buildings_visible_with_layered_shadows(self):
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        self.assertNotIn("var castsShadow = !isTerrainObject(object) && !isRoadObject(object);", preview_js)
        self.assertNotIn("object.castShadow = castsShadow;", preview_js)
        self.assertNotIn("function isTerrainObject(object)", preview_js)
        self.assertNotIn("function isRoadObject(object)", preview_js)
        self.assertIn("object.castShadow = true;", preview_js)
        self.assertIn("object.receiveShadow = true;", preview_js)
        self.assertNotIn("object.visible = false", preview_js)

    def test_status_payloads_share_common_service_projection(self):
        source = Path(area_picker.__file__).read_text(encoding="utf-8")
        self.assertIn("def _attach_service_status_fields", source)
        self.assertGreaterEqual(source.count("_attach_service_status_fields("), 3)

    def test_picker_uses_draw_rectangle_for_fixed_grid_blocks(self):
        self.assertIn("固定网格框选器", _PICKER_FRONTEND)
        self.assertIn("new maplibregl.Map(", _PICKER_FRONTEND)
        self.assertIn("selectTilesByBounds", _PICKER_FRONTEND)
        self.assertIn("function tileDisplayBbox(tile)", _PICKER_FRONTEND)
        self.assertIn("function assignDisplayGridBounds(tiles)", _PICKER_FRONTEND)
        self.assertIn("tile.display_bbox =", _PICKER_FRONTEND)
        self.assertIn("bboxIntersects(bounds, tileDisplayBbox(tile))", _PICKER_FRONTEND)
        self.assertIn("id: 'grid-fill',", _PICKER_FRONTEND)
        self.assertIn("id: 'grid-line',", _PICKER_FRONTEND)
        self.assertIn("map.addSource('grid'", _PICKER_FRONTEND)
        self.assertIn("tile_ids", _PICKER_FRONTEND)
        self.assertIn("downloadData", _PICKER_FRONTEND)
        self.assertIn('id="selection-tools"', _PICKER_FRONTEND)
        self.assertIn("map-tool-control", _PICKER_FRONTEND)
        self.assertIn("activateRectangleTool", _PICKER_FRONTEND)
        self.assertIn("selectTileByLatLng", _PICKER_FRONTEND)
        self.assertIn("clearSelectionFromMapTool", _PICKER_FRONTEND)
        self.assertIn("bindSelectionTools", _PICKER_FRONTEND)
        self.assertIn("function setGridVisible(visible)", _PICKER_FRONTEND)
        self.assertIn("function toggleGridVisible()", _PICKER_FRONTEND)
        self.assertNotIn("leaflet.draw", _PICKER_FRONTEND)
        self.assertNotIn("L.Control.Draw", _PICKER_FRONTEND)
        self.assertNotIn("L.rectangle(", _PICKER_FRONTEND)
        self.assertNotIn("leaflet-draw-edit-remove", _PICKER_FRONTEND)
        self.assertNotIn(".leaflet-control-zoom", _PICKER_FRONTEND)
        self.assertNotIn('id="clear-btn"', _PICKER_FRONTEND)
        self.assertNotIn('id="legend"', _PICKER_FRONTEND)
        self.assertNotIn("未缓存：整体压暗", _PICKER_FRONTEND)
        self.assertNotIn("swatch-dim", _PICKER_FRONTEND)
        self.assertNotIn("cached-only", _PICKER_FRONTEND)
        self.assertNotIn("只显示已有缓存", _PICKER_FRONTEND)

    def test_houdini_action_panel_toggle_lives_in_top_toolbar(self):
        toolbar_start = _PICKER_INDEX_HTML.index('<div id="toolbar">')
        workspace_start = _PICKER_INDEX_HTML.index('<main id="workspace"')
        toolbar_html = _PICKER_INDEX_HTML[toolbar_start:workspace_start]
        action_panel_start = _PICKER_INDEX_HTML.index('<aside id="action-panel"')
        action_panel_html = _PICKER_INDEX_HTML[action_panel_start:]

        self.assertIn('class="toolbar-cluster"', toolbar_html)
        self.assertIn('id="action-panel-toggle"', toolbar_html)
        self.assertNotIn('id="action-panel-toggle"', action_panel_html)
        self.assertIn('data-action-panel-collapsed="false"', _PICKER_FRONTEND)
        self.assertIn('#workspace[data-action-panel-collapsed="true"]', _PICKER_STYLES)
        self.assertIn('function setActionPanelCollapsed(collapsed)', _PICKER_APP_JS)
        self.assertIn('function bindActionPanelToggle()', _PICKER_APP_JS)
        action_panel_collapse_body = _PICKER_APP_JS.split(
            "function setActionPanelCollapsed(collapsed)", 1
        )[1].split("function bindActionPanelToggle()", 1)[0]
        self.assertIn("if (map && map.resize) map.resize();", action_panel_collapse_body)
        self.assertIn("if (activeWorkspaceId === 'game' && window.VC_GAME_WORKBENCH) {", action_panel_collapse_body)
        self.assertIn("window.VC_GAME_WORKBENCH.resize();", action_panel_collapse_body)

    def test_picker_version_uses_public_date_semver_format(self):
        self.assertRegex(area_picker.APP_VERSION, r"^\d{2}-\d{2}-\d{2}_v\d+\.\d+$")

    def test_version_text_and_test_buttons_are_split(self):
        self.assertIn('id="app-version-label" class="version-text">__APP_VERSION__</span>', _PICKER_INDEX_HTML)
        self.assertIn('id="backend-restart-button"', _PICKER_INDEX_HTML)
        self.assertIn('id="frontend-refresh-button"', _PICKER_INDEX_HTML)
        self.assertIn('class="test-chip"', _PICKER_INDEX_HTML)
        self.assertIn('aria-label="测试期间重启后端服务"', _PICKER_INDEX_HTML)
        self.assertIn('aria-label="测试期间刷新前端资源"', _PICKER_INDEX_HTML)
        self.assertNotIn('id="frontend-refresh-button" class="version-chip"', _PICKER_INDEX_HTML)
        self.assertIn("frontendRefreshWorkspaceKey = 'vc.areaPicker.refreshWorkspace.v1'", _PICKER_APP_JS)
        self.assertIn("function bindFrontendRefresh()", _PICKER_APP_JS)
        self.assertIn("var restartButton = document.getElementById('backend-restart-button');", _PICKER_APP_JS)
        self.assertIn("var refreshButton = document.getElementById('frontend-refresh-button');", _PICKER_APP_JS)
        self.assertIn("function rememberWorkspace()", _PICKER_APP_JS)
        self.assertIn("clearDccPathCache();", _PICKER_APP_JS)
        self.assertIn("fetch('/restart'", _PICKER_APP_JS)
        self.assertIn("reloadWithCacheBust();", _PICKER_APP_JS)
        self.assertIn("url.searchParams.set('refresh', String(Date.now()))", _PICKER_APP_JS)
        self.assertIn("window.location.replace(url.toString())", _PICKER_APP_JS)
        self.assertTrue(hasattr(area_picker, "_schedule_desktop_restart"))
        server_source = Path(area_picker.__file__).read_text(encoding="utf-8")
        self.assertIn("parsed.path == '/restart'", server_source)
        self.assertIn("VC_AREA_PICKER_FORCE_RESTART", server_source)
        self.assertIn("def _clear_dcc_path_cache", server_source)
        self.assertIn("function initialWorkspaceId()", _PICKER_APP_JS)
        self.assertIn("bindFrontendRefresh();", _PICKER_APP_JS)
        self.assertIn("setWorkspace(initialWorkspaceId());", _PICKER_APP_JS)

    def test_picker_uses_local_web_assets_and_online_basemap(self):
        self.assertIn('/static/maplibre/maplibre-gl.css', _PICKER_FRONTEND)
        self.assertIn('/static/maplibre/maplibre-gl.js', _PICKER_FRONTEND)
        self.assertIn('/static/deckgl/deck.gl.min.js', _PICKER_FRONTEND)
        self.assertNotIn('/static/leaflet/leaflet.js', _PICKER_FRONTEND)
        self.assertNotIn('/static/leaflet-draw/leaflet.draw.js', _PICKER_FRONTEND)
        self.assertNotIn('unpkg.com/leaflet', _PICKER_FRONTEND)
        self.assertNotIn('cdnjs.cloudflare.com/ajax/libs/leaflet.draw', _PICKER_FRONTEND)
        self.assertIn('tile.openstreetmap.org', _PICKER_FRONTEND)
        self.assertIn('/area-picker/basemap-style.json', _PICKER_FRONTEND)
        self.assertNotIn('run-mode', _PICKER_FRONTEND)
        self.assertNotIn('local-basemap-enabled', _PICKER_FRONTEND)
        self.assertNotIn('loadLocalBasemap', _PICKER_FRONTEND)
        self.assertIn('type="button" class="badge badge-warn" onclick="openOrProbeHoudini()"', _PICKER_FRONTEND)
        self.assertIn('function openOrProbeHoudini()', _PICKER_FRONTEND)
        self.assertNotIn('setInterval(refreshServiceState', _PICKER_FRONTEND)
        self.assertIn("new EventSource('/events')", _PICKER_FRONTEND)
        self.assertIn('function startStatusStream()', _PICKER_FRONTEND)
        self.assertIn('var shutdownWithPage = window.VC_CONFIG.shutdownWithPage;', _PICKER_FRONTEND)
        self.assertIn("navigator.sendBeacon('/session/closed'", _PICKER_FRONTEND)
        self.assertIn("fetch('/session'", _PICKER_FRONTEND)
        self.assertTrue(hasattr(area_picker, "_schedule_page_close_shutdown"))
        self.assertIn('exportFbx', _PICKER_FRONTEND)
        self.assertIn('id="download-btn" disabled onclick="downloadData()"', _PICKER_FRONTEND)
        self.assertIn('class="source-action-btn"', _PICKER_FRONTEND)
        self.assertIn("submitSelectedArea('download'", _PICKER_FRONTEND)
        self.assertIn("id: 'grid-fill',", _PICKER_FRONTEND)
        self.assertIn("id: 'grid-line',", _PICKER_FRONTEND)
        self.assertNotIn("invert(1)", _PICKER_FRONTEND)
        self.assertNotIn("visualRoad", _PICKER_FRONTEND)
        self.assertNotIn("/visual-roads", _PICKER_FRONTEND)

    def test_lane_preview_button_is_not_exposed(self):
        removed_endpoint = "lane" + "-upgrade"
        self.assertNotIn(removed_endpoint, _PICKER_FRONTEND)
        self.assertNotIn("updateLaneUpgradeButton", _PICKER_FRONTEND)
        self.assertNotIn("handleLaneUpgrade", _PICKER_FRONTEND)

    def test_selection_survives_page_reload(self):
        self.assertIn("selectionStorageKey = 'vc.areaPicker.selection.v1'", _PICKER_FRONTEND)
        self.assertIn("function selectionPayloadFromSelection", _PICKER_FRONTEND)
        self.assertIn("function persistSelection()", _PICKER_FRONTEND)
        self.assertIn("function restoreSelectionFromPayload", _PICKER_FRONTEND)
        self.assertIn("function restoreRememberedSelection", _PICKER_FRONTEND)
        self.assertIn("function restorePendingSelection", _PICKER_FRONTEND)
        self.assertIn("fetch('/selection'", _PICKER_FRONTEND)
        self.assertIn("fetch('/selection/clear'", _PICKER_FRONTEND)
        self.assertIn("restoreRememberedSelection();", _PICKER_FRONTEND)
        self.assertIn("persistSelection();", _PICKER_FRONTEND)
        self.assertIn("syncDrawnSelectionLayer();", _PICKER_FRONTEND)
        self.assertIn("setRunStatus('warn', '待命', 0, '已选择区域，等待执行');", _PICKER_FRONTEND)
        self.assertIn("已恢复上次框选", _PICKER_FRONTEND)

    def test_viewport_data_summary_is_not_exposed(self):
        self.assertNotIn("视口数据", _PICKER_FRONTEND)
        self.assertNotIn("完整数据区域", _PICKER_FRONTEND)
        self.assertNotIn('id="grid-status"', _PICKER_FRONTEND)
        self.assertNotIn('id="downloaded-area-count"', _PICKER_FRONTEND)
        self.assertNotIn('id="selection-bbox"', _PICKER_FRONTEND)
        self.assertNotIn("function updateDownloadedAreaCount", _PICKER_FRONTEND)
        self.assertNotIn("data-overview", _PICKER_FRONTEND)
        self.assertNotIn("metric-grid", _PICKER_FRONTEND)
        self.assertNotIn("已下载区域数量", _PICKER_FRONTEND)
        self.assertNotIn("网格数量", _PICKER_FRONTEND)
        self.assertNotIn("区域尺寸", _PICKER_FRONTEND)
        self.assertNotIn("缓存覆盖", _PICKER_FRONTEND)
        self.assertNotIn("网格矩阵", _PICKER_FRONTEND)
        self.assertNotIn('id="selection-count"', _PICKER_FRONTEND)
        self.assertNotIn('id="selection-size"', _PICKER_FRONTEND)
        self.assertNotIn('id="selection-cache"', _PICKER_FRONTEND)
        self.assertNotIn('id="selection-matrix"', _PICKER_FRONTEND)

    def test_picker_exposes_current_data_sources(self):
        self.assertIn('id="source-list"', _PICKER_FRONTEND)
        self.assertIn("function refreshDataSources()", _PICKER_FRONTEND)
        self.assertIn("fetch('/data-sources'", _PICKER_FRONTEND)
        self.assertIn("选取区域预先下载地图数据加快Houdini自动管线构建速度", _PICKER_FRONTEND)
        self.assertNotIn("读取当前区域数据源...", _PICKER_FRONTEND)
        self.assertNotIn("当前区域数据源", _PICKER_FRONTEND)
        self.assertIn("数据源：OpenStreetMap", _PICKER_FRONTEND)
        self.assertIn("数据源：Overture Maps + Google Open Buildings", _PICKER_FRONTEND)
        self.assertIn("策略：本地缓存优先", _PICKER_FRONTEND)
        self.assertIn("item.strategy_label", _PICKER_FRONTEND)
        self.assertNotIn("source-state", _PICKER_FRONTEND)
        self.assertNotIn("已就绪", _PICKER_FRONTEND)

    def test_action_panel_groups_workflow_modules(self):
        self.assertIn('id="action-panel"', _PICKER_FRONTEND)
        self.assertIn("待命/运行监控", _PICKER_FRONTEND)
        self.assertIn("数据源", _PICKER_FRONTEND)
        self.assertIn("预览", _PICKER_FRONTEND)
        self.assertIn("构建", _PICKER_FRONTEND)
        self.assertIn("运行监控", _PICKER_FRONTEND)
        self.assertIn("建筑", _PICKER_FRONTEND)
        self.assertIn("地形", _PICKER_FRONTEND)
        self.assertIn("自然", _PICKER_FRONTEND)
        self.assertIn("道路", _PICKER_FRONTEND)
        self.assertIn("自然数据处理入口待接入", _PICKER_FRONTEND)
        self.assertIn("道路数据处理入口待接入", _PICKER_FRONTEND)
        self.assertNotIn("植被数据清洗入口待接入", _PICKER_FRONTEND)
        self.assertNotIn("车道数据处理入口待接入", _PICKER_FRONTEND)
        self.assertIn("placeholder-btn", _PICKER_FRONTEND)
        self.assertIn('id="run-status-panel"', _PICKER_FRONTEND)
        self.assertIn('id="run-status-bar"', _PICKER_FRONTEND)
        self.assertIn("function updateRunStatusFromHealth", _PICKER_FRONTEND)
        self.assertIn('id="failure-summary"', _PICKER_FRONTEND)
        self.assertIn("function setFailureSummary", _PICKER_FRONTEND)
        self.assertIn("function logFailureSummary", _PICKER_FRONTEND)
        self.assertIn("上次失败", _PICKER_FRONTEND)
        self.assertNotIn("打开输出", _PICKER_FRONTEND)

    def test_workspace_uses_gapless_three_column_layout(self):
        self.assertIn('grid-template-areas: "controls map actions";', _PICKER_FRONTEND)
        self.assertIn("gap: 0;", _PICKER_FRONTEND)
        self.assertIn("grid-area: controls;", _PICKER_FRONTEND)
        self.assertIn("grid-area: map;", _PICKER_FRONTEND)
        self.assertIn("grid-area: actions;", _PICKER_FRONTEND)
        self.assertIn("border-radius: 0;", _PICKER_FRONTEND)
        self.assertNotIn("left: 18px;", _PICKER_FRONTEND)
        self.assertNotIn("right: 18px;", _PICKER_FRONTEND)
        self.assertNotIn("top: 18px;", _PICKER_FRONTEND)
        self.assertNotIn("max-height: calc(100% - 36px);", _PICKER_FRONTEND)

    def test_workspace_switcher_has_mode_hooks(self):
        self.assertIn('data-workspace-target="city-preview"', _PICKER_FRONTEND)
        self.assertIn('data-workspace-target="news"', _PICKER_FRONTEND)
        self.assertNotIn('data-workspace-target="neighborhood"', _PICKER_FRONTEND)
        self.assertIn('data-workspace-target="game"', _PICKER_FRONTEND)
        self.assertIn('data-workspace-target="houdini"', _PICKER_FRONTEND)
        self.assertIn('id="game-workbench"', _PICKER_FRONTEND)
        self.assertIn('data-workspace-kind', _PICKER_FRONTEND)
        self.assertIn('#workspace[data-workspace-kind="earth"] #map-shell', _PICKER_FRONTEND)
        self.assertIn('grid-column: 2 / 3;', _PICKER_FRONTEND)
        self.assertIn('#action-panel[hidden]', _PICKER_FRONTEND)
        self.assertIn('var WORKSPACE_KINDS = {', _PICKER_FRONTEND)
        self.assertIn('function setWorkspace(id)', _PICKER_FRONTEND)
        self.assertIn('function bindWorkspaceSwitching()', _PICKER_FRONTEND)
        self.assertIn("map.resize();", _PICKER_FRONTEND)

    def test_earth_workspaces_have_independent_map_contexts(self):
        self.assertIn('id="map-news" class="map-view active" data-map-workspace="news"', _PICKER_INDEX_HTML)
        self.assertIn('id="map-zone" class="map-view" data-map-workspace="city-preview"', _PICKER_INDEX_HTML)
        self.assertIn('id="map-houdini" class="map-view" data-map-workspace="houdini"', _PICKER_INDEX_HTML)
        self.assertIn('var mapContexts = {};', _PICKER_APP_JS)
        self.assertIn('function activateMapContext(workspaceId)', _PICKER_APP_JS)
        self.assertIn('activateMapContext(nextWorkspace);', _PICKER_APP_JS)
        self.assertIn('#map-shell .map-tool-control', _PICKER_STYLES)

    def test_workspace_action_panel_has_tabbed_panels_for_unimplemented_modules(self):
        self.assertIn('data-action-panel-content="houdini"', _PICKER_INDEX_HTML)
        for workspace in ("news", "city-preview", "neighborhood", "game"):
            self.assertIn(f'data-action-panel-content="{workspace}"', _PICKER_INDEX_HTML)
        self.assertIn(".action-tabs", _PICKER_STYLES)
        self.assertIn("function syncActionPanelContent(workspaceId)", _PICKER_APP_JS)
        self.assertIn("querySelectorAll('[data-action-panel-content]')", _PICKER_APP_JS)

    def test_city_workspace_defaults_to_singapore_central_3d_preview(self):
        self.assertIn("function showDefaultCityPreview()", _PICKER_APP_JS)
        self.assertIn("findRegionById(regionData, 'sg')", _PICKER_APP_JS)
        self.assertIn("findRegionById(country.cities || [], 'central')", _PICKER_APP_JS)
        self.assertIn("loadBoundary(city.osmId);", _PICKER_APP_JS)
        self.assertIn("var lastCityView = null;", _PICKER_APP_JS)
        self.assertIn("lastCityView = { bbox: city.bbox, maxZoom: 12 };", _PICKER_APP_JS)
        self.assertIn("flyToBbox(lastCityView.bbox, lastCityView.maxZoom);", _PICKER_APP_JS)
        self.assertIn("function syncHoudiniCameraToCity()", _PICKER_APP_JS)
        self.assertIn("if (city && city.bbox) view = { bbox: city.bbox, maxZoom: 12 };", _PICKER_APP_JS)
        self.assertIn("flyToBbox(view.bbox, view.maxZoom);", _PICKER_APP_JS)
        self.assertIn("flyTo3DCity(target[0], target[1], city.landmark_zoom || 15);", _PICKER_APP_JS)
        self.assertIn("syncHoudiniCameraToCity();", _PICKER_APP_JS)
        self.assertIn("if (nextWorkspace === 'city-preview') showDefaultCityPreview();", _PICKER_APP_JS)
        self.assertIn("else if (cityPreviewActive && nextWorkspace !== 'city-preview' && nextWorkspace !== 'houdini' && showsMap) {", _PICKER_APP_JS)
        self.assertIn("cityPreviewActive = false;", _PICKER_APP_JS)
        self.assertIn("if (activeWorkspaceId === 'city-preview') showDefaultCityPreview();", _PICKER_APP_JS)
        self.assertIn("else if (activeWorkspaceId === 'houdini') syncHoudiniCameraToCity();", _PICKER_APP_JS)

    def test_country_click_toggles_city_list(self):
        self.assertIn("var sameCountryOpen = activeCountryId === country.id && citiesHost && !citiesHost.hidden;", _PICKER_APP_JS)
        self.assertIn("activeCountryId = null;", _PICKER_APP_JS)
        self.assertIn("citiesHost.hidden = true;", _PICKER_APP_JS)

    def test_eol_workspace_defaults_to_global_overview(self):
        self.assertIn("function flyToWorld()", _PICKER_APP_JS)
        self.assertIn("center: [window.VC_CONFIG.lon, 20]", _PICKER_APP_JS)
        self.assertIn("zoom: 2.5", _PICKER_APP_JS)
        self.assertIn("pitch: 0", _PICKER_APP_JS)
        self.assertIn("flyToWorld: flyToWorld", _PICKER_APP_JS)
        self.assertIn("function showGlobalOverview()", _PICKER_APP_JS)
        self.assertIn("cameraController.flyToWorld();", _PICKER_APP_JS)
        self.assertIn("if (nextWorkspace === 'news') showGlobalOverview();", _PICKER_APP_JS)

    def test_game_action_panel_uses_grid_column_like_map_viewports(self):
        game_workspace_style = _PICKER_STYLES.split(
            '#workspace[data-workspace-kind="game"] {',
            1,
        )[1].split("}", 1)[0]
        collapsed_game_style = _PICKER_STYLES.split(
            '#workspace[data-workspace-kind="game"][data-action-panel-collapsed="true"] {',
            1,
        )[1].split("}", 1)[0]
        self.assertIn("grid-template-columns: 300px minmax(0, 1fr) minmax(300px, 326px);", game_workspace_style)
        self.assertIn("grid-template-columns: 300px minmax(0, 1fr) 0;", collapsed_game_style)
        self.assertNotIn('#workspace[data-workspace-kind="game"] #action-panel:not([hidden])', _PICKER_STYLES)

    def test_game_workspace_shows_editor_left_action_buttons(self):
        control_panel_html = _PICKER_INDEX_HTML.split('<aside id="control-panel"', 1)[1].split('</aside>', 1)[0]
        self.assertIn('id="editor-left-actions"', control_panel_html)
        self.assertIn('class="panel-section editor-left-actions-section"', control_panel_html)
        self.assertIn('class="editor-left-action-list flat-panel flat-panel--col"', control_panel_html)
        self.assertLess(control_panel_html.index('id="tool-placeholder-section"'), control_panel_html.index('id="editor-left-actions"'))
        self.assertLess(control_panel_html.index('id="editor-left-actions"'), control_panel_html.index('id="panel-footer"'))
        for label in ("新建", "打开", "保存", "打开目录", "设置"):
            self.assertIn(f'<span class="editor-left-action-label">{label}</span>', control_panel_html)
        for action in ("new", "open", "save", "open-root", "settings"):
            self.assertIn(f'data-editor-action="{action}"', control_panel_html)
        self.assertLess(
            control_panel_html.index('data-editor-action="new"'),
            control_panel_html.index('data-editor-action="open"')
        )
        self.assertLess(
            control_panel_html.index('data-editor-action="open"'),
            control_panel_html.index('data-editor-action="save"')
        )
        self.assertNotIn("另存为", control_panel_html)
        self.assertNotIn('data-editor-action="save-as"', control_panel_html)
        self.assertIn(".editor-left-actions-section {\n  display: none;", _PICKER_STYLES)
        self.assertIn('#workspace[data-workspace-kind="game"] .editor-left-actions-section {\n  display: block;', _PICKER_STYLES)
        self.assertIn(".editor-left-action-btn", _PICKER_STYLES)
        self.assertIn(".editor-left-action-icon", _PICKER_STYLES)

    def test_editor_scene_actions_have_scene_root_dialog(self):
        scene_js_path = FRONTEND_ROOT / "scene_project.js"
        self.assertTrue(scene_js_path.exists())
        scene_js = scene_js_path.read_text(encoding="utf-8")
        self.assertIn('/area-picker/scene_project.js?v=__VERSION__', _PICKER_INDEX_HTML)
        self.assertLess(_PICKER_INDEX_HTML.index('scene_project.js'), _PICKER_INDEX_HTML.index('workspace.js'))
        self.assertIn('id="scene-root-dialog"', _PICKER_INDEX_HTML)
        self.assertIn('id="scene-root-form"', _PICKER_INDEX_HTML)
        self.assertIn('id="scene-root-input"', _PICKER_INDEX_HTML)
        self.assertIn('id="scene-root-status"', _PICKER_INDEX_HTML)
        self.assertIn("fetch('/scene-root')", scene_js)
        self.assertIn("fetch('/scene-root',", scene_js)
        self.assertIn("fetch('/open-scene-root'", scene_js)
        self.assertIn("announceSceneRootChanged(d);", scene_js)
        self.assertIn("button.dataset.editorAction", scene_js)
        self.assertIn("openDialog('新建工程', 'new')", scene_js)
        self.assertIn("openDialog('打开工程', 'open')", scene_js)
        self.assertIn("action === 'save'", scene_js)
        self.assertNotIn("action === 'save-as'", scene_js)
        self.assertIn("action === 'open-root'", scene_js)
        self.assertIn("action === 'open'", scene_js)
        self.assertIn("action === 'settings'", scene_js)
        self.assertIn("pendingDialogAction === 'new'", scene_js)
        self.assertIn("createNewProject();", scene_js)
        self.assertIn("请先选择工程的初始创建根目录", scene_js)
        self.assertIn('id="scene-root-hint"', _PICKER_INDEX_HTML)
        self.assertIn('id="scene-root-label"', _PICKER_INDEX_HTML)
        self.assertIn('id="scene-root-submit"', _PICKER_INDEX_HTML)
        self.assertIn("工程初始创建根目录", scene_js)
        self.assertIn("选择工程的初始创建根目录，并为工程命名。", scene_js)
        self.assertIn(".scene-root-dialog", _PICKER_STYLES)
        self.assertIn(".scene-root-backdrop", _PICKER_STYLES)
        server_source = Path(area_picker.__file__).read_text(encoding="utf-8")
        self.assertIn("parsed.path == '/scene-root'", server_source)
        self.assertIn("parsed.path == '/open-scene-root'", server_source)
        self.assertIn("def _post_scene_root", server_source)
        self.assertIn("def _post_open_scene_root", server_source)

    def test_editor_open_project_button_has_recent_project_picker(self):
        scene_js = (FRONTEND_ROOT / "scene_project.js").read_text(encoding="utf-8")
        self.assertIn('data-editor-action="open"', _PICKER_INDEX_HTML)
        self.assertIn('<span class="editor-left-action-label">打开</span>', _PICKER_INDEX_HTML)
        self.assertIn('id="scene-root-project-list"', _PICKER_INDEX_HTML)
        self.assertIn("function loadProjectRegistry()", scene_js)
        self.assertIn("function upsertProject(root, name)", scene_js)
        self.assertIn("function renderProjectList()", scene_js)
        self.assertIn("vc_scene_projects_v1", scene_js)
        self.assertIn("item.addEventListener('click', function() {", scene_js)
        self.assertIn("saveSceneRoot();", scene_js)
        self.assertIn(".scene-root-project-list", _PICKER_STYLES)
        self.assertIn(".scene-root-project-item", _PICKER_STYLES)

    def test_editor_new_project_dialog_has_name_field(self):
        scene_js = (FRONTEND_ROOT / "scene_project.js").read_text(encoding="utf-8")
        self.assertIn('id="scene-root-name-label"', _PICKER_INDEX_HTML)
        self.assertIn('id="scene-root-name-input"', _PICKER_INDEX_HTML)
        self.assertIn("工程名称", _PICKER_INDEX_HTML)
        self.assertIn("nameLabel.hidden = !isNew;", scene_js)
        self.assertIn("nameInput.hidden = !isNew;", scene_js)
        self.assertIn("var name = isNew && nameInput ? nameInput.value.trim() : '';", scene_js)
        self.assertIn("upsertProject(d.scene_root.scene_root, name);", scene_js)

    def test_scene_project_assets_status_lists_current_root_assets(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "Models").mkdir()
            (root / "Textures").mkdir()
            (root / "Docs").mkdir()
            (root / ".git").mkdir()
            (root / "Models" / "car.glb").write_bytes(b"glb-data")
            (root / "Textures" / "road.png").write_bytes(b"png-data")
            (root / "Docs" / "readme.txt").write_text("notes", encoding="utf-8")
            (root / ".git" / "config").write_text("hidden", encoding="utf-8")

            with patch.object(area_picker, "_scene_root_status", return_value={
                "scene_root": str(root),
                "scene_root_exists": True,
            }):
                payload = area_picker._scene_assets_status()

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["available"])
        self.assertEqual(payload["scene_root"], str(root))
        self.assertEqual(payload["limit"], 200)
        by_path = {item["relative_path"]: item for item in payload["assets"]}
        self.assertEqual(by_path["Models/car.glb"]["category"], "model")
        self.assertEqual(by_path["Textures/road.png"]["category"], "texture")
        self.assertEqual(by_path["Docs/readme.txt"]["category"], "other")
        self.assertNotIn(".git/config", by_path)

    def test_houdini_whitebox_sync_moves_asset_into_scene_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            scene_root = root / "Project"
            export_dir = root / "Houdini" / "Export"
            scene_root.mkdir()
            export_dir.mkdir(parents=True)
            whitebox = export_dir / "whitebox_v001.glb"
            whitebox.write_bytes(b"glb-data")

            with patch.object(area_picker, "_scene_root_status", return_value={
                "scene_root": str(scene_root),
                "scene_root_exists": True,
            }), patch.object(area_picker, "_whitebox_path_from_status", return_value=whitebox):
                payload = area_picker._sync_houdini_whitebox_to_scene_assets()
                asset_payload = area_picker._scene_assets_status()
                synced = scene_root / "Houdini_Whitebox.glb"
                self.assertTrue(payload["ok"])
                self.assertFalse(whitebox.exists())
                self.assertTrue(synced.exists())
                self.assertEqual(payload["asset"]["relative_path"], "Houdini_Whitebox.glb")
                self.assertEqual(payload["asset"]["category"], "model")
                self.assertEqual(payload["asset"]["display_name"], "Houdini 白盒")
                by_path = {item["relative_path"]: item for item in asset_payload["assets"]}
                self.assertEqual(by_path["Houdini_Whitebox.glb"]["display_name"], "Houdini 白盒")

    def test_account_footer_uses_codex_style_menu(self):
        self.assertIn('<details class="account-menu">', _PICKER_INDEX_HTML)
        self.assertIn('class="account-trigger"', _PICKER_INDEX_HTML)
        self.assertIn('class="account-popover"', _PICKER_INDEX_HTML)
        self.assertIn('role="menu"', _PICKER_INDEX_HTML)
        self.assertIn('<span class="account-name">Settings</span>', _PICKER_INDEX_HTML)
        self.assertIn('<span class="account-plan">Account</span>', _PICKER_INDEX_HTML)
        self.assertIn("border-top: 1px solid var(--line);", _PICKER_STYLES)
        self.assertIn(".account-menu[open] .account-popover", _PICKER_STYLES)
        self.assertNotIn(".account-menu:hover .account-popover", _PICKER_STYLES)
        self.assertIn("function bindAccountMenu()", _PICKER_APP_JS)
        self.assertIn("if (!menu.contains(event.target)) menu.open = false;", _PICKER_APP_JS)
        self.assertNotIn("account-card", _PICKER_FRONTEND)

    def test_game_workspace_mounts_three_scene(self):
        game_js_path = FRONTEND_ROOT / "game_workbench.js"
        self.assertTrue(game_js_path.exists())
        game_js = game_js_path.read_text(encoding="utf-8")
        core_js = (FRONTEND_ROOT / "gw_core.js").read_text(encoding="utf-8")
        character_js = (FRONTEND_ROOT / "gw_character.js").read_text(encoding="utf-8")
        play_js = (FRONTEND_ROOT / "gw_play.js").read_text(encoding="utf-8")
        self.assertIn('/static/three/three.min.js', _PICKER_INDEX_HTML)
        self.assertIn('/area-picker/viewport_grid.js?v=__VERSION__', _PICKER_INDEX_HTML)
        self.assertIn('/area-picker/gw_core.js?v=__VERSION__', _PICKER_INDEX_HTML)
        self.assertIn('/area-picker/gw_character.js?v=__VERSION__', _PICKER_INDEX_HTML)
        self.assertIn('/area-picker/gw_play.js?v=__VERSION__', _PICKER_INDEX_HTML)
        self.assertIn('/area-picker/game_workbench.js?v=__VERSION__', _PICKER_INDEX_HTML)
        self.assertIn('id="game-scene-host"', _PICKER_INDEX_HTML)
        self.assertIn('game-asset-button', _PICKER_INDEX_HTML)
        self.assertIn('data-game-asset="character"', _PICKER_INDEX_HTML)
        self.assertIn('id="game-run-button"', _PICKER_INDEX_HTML)
        self.assertIn('initGameWorkbench', game_js)
        self.assertIn('createToonGrayMaterial', character_js)
        self.assertIn('createPlayModeController', play_js)
        self.assertIn('placeCharacterAt', game_js)
        self.assertIn('handleGameShortcut', game_js)
        self.assertIn('window.VC_GAME_WORKBENCH', game_js)
        self.assertIn('window.VC_GAME_WORKBENCH.init()', _PICKER_APP_JS)
        self.assertIn('window.VC_GAME_WORKBENCH.setActive(', _PICKER_APP_JS)
        # Split modules share state through the window.VC_GW namespace and must load
        # before the host (game_workbench.js) that aliases their exports.
        self.assertIn('window.VC_GW', core_js)
        self.assertIn('GW.state', core_js)
        self.assertIn('GW.createCharacter = createCharacter;', character_js)
        self.assertIn('GW.createPlayModeController = createPlayModeController;', play_js)
        self.assertIn('var GW = window.VC_GW;', game_js)
        self.assertLess(_PICKER_INDEX_HTML.index('gw_core.js'), _PICKER_INDEX_HTML.index('gw_character.js'))
        self.assertLess(_PICKER_INDEX_HTML.index('gw_character.js'), _PICKER_INDEX_HTML.index('gw_play.js'))
        self.assertLess(_PICKER_INDEX_HTML.index('gw_play.js'), _PICKER_INDEX_HTML.index('game_workbench.js'))

    def test_game_scene_outline_shows_label_and_type_columns(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        asset_js = (FRONTEND_ROOT / "gw_assets.js").read_text(encoding="utf-8")
        outliner_js = (FRONTEND_ROOT / "gw_outliner.js").read_text(encoding="utf-8")

        self.assertIn('/area-picker/gw_outliner.js?v=__VERSION__', _PICKER_INDEX_HTML)
        self.assertLess(_PICKER_INDEX_HTML.index('gw_assets.js'), _PICKER_INDEX_HTML.index('gw_outliner.js'))
        self.assertLess(_PICKER_INDEX_HTML.index('gw_outliner.js'), _PICKER_INDEX_HTML.index('game_workbench.js'))
        self.assertIn("function createSceneOutliner(options)", outliner_js)
        self.assertIn("table.className = 'scene-outline-table';", outliner_js)
        self.assertIn("headerLabel.textContent = '项目标签';", outliner_js)
        self.assertIn("headerType.textContent = '类型';", outliner_js)
        self.assertIn("splitter.className = 'scene-outline-column-splitter';", outliner_js)
        self.assertIn("function beginColumnResize(table, splitter, event)", outliner_js)
        self.assertIn("table.style.setProperty('--scene-outline-label-width'", outliner_js)
        self.assertIn("setOutlineLabelWidth(columnResizeState.table, labelWidthFromPointer(columnResizeState.table, event));", outliner_js)
        self.assertIn("setOutlineLabelWidth(table, currentOutlineLabelWidth(table) + delta);", outliner_js)
        self.assertIn("labelCell.className = 'scene-outline-cell scene-outline-label';", outliner_js)
        self.assertIn("typeCell.className = 'scene-outline-cell scene-outline-type';", outliner_js)
        self.assertIn("typeCell.textContent = sceneOutlineTypeLabel(obj);", outliner_js)
        self.assertIn("model: '模型'", outliner_js)
        self.assertIn("GW.createSceneOutliner = createSceneOutliner;", outliner_js)
        self.assertIn("sceneOutliner = GW.createSceneOutliner", game_js)
        self.assertNotIn("function sceneOutlineTypeLabel(obj)", game_js)
        self.assertIn("root.userData.assetType = root.userData.assetType || 'model';", asset_js)
        self.assertIn(".scene-outline-table {", _PICKER_STYLES)
        scene_outline_body_style = _PICKER_STYLES.split("#game-scene-outline .action-outline-body", 1)[1].split("}", 1)[0]
        self.assertIn("scrollbar-gutter: auto;", scene_outline_body_style)
        self.assertNotIn("scrollbar-gutter: stable;", scene_outline_body_style)
        self.assertIn("--scene-outline-label-width: 1fr;", _PICKER_STYLES)
        self.assertIn("grid-template-columns: minmax(88px, var(--scene-outline-label-width, 1fr)) 7px minmax(54px, 78px);", _PICKER_STYLES)
        self.assertIn(".scene-outline-head,", _PICKER_STYLES)
        self.assertIn(".scene-outline-label", _PICKER_STYLES)
        self.assertIn(".scene-outline-type", _PICKER_STYLES)
        self.assertIn(".scene-outline-column-splitter", _PICKER_STYLES)
        self.assertIn(".scene-outline-row:not(:last-child)", _PICKER_STYLES)
        self.assertIn(".scene-outline-row .scene-outline-label", _PICKER_STYLES)
        self.assertIn("border-bottom: 1px solid color-mix(in srgb, var(--line) 46%, transparent);", _PICKER_STYLES)
        self.assertIn("border-right: 1px solid color-mix(in srgb, var(--line) 46%, transparent);", _PICKER_STYLES)
        self.assertIn(".scene-outline-swatch", _PICKER_STYLES)

    def test_game_workbench_splits_persistence_and_commands(self):
        persistence_path = FRONTEND_ROOT / "gw_scene_persistence.js"
        commands_path = FRONTEND_ROOT / "gw_commands.js"
        self.assertTrue(persistence_path.exists())
        self.assertTrue(commands_path.exists())
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        persistence_js = persistence_path.read_text(encoding="utf-8")
        commands_js = commands_path.read_text(encoding="utf-8")

        self.assertIn('/area-picker/gw_scene_persistence.js?v=__VERSION__', _PICKER_INDEX_HTML)
        self.assertIn('/area-picker/gw_commands.js?v=__VERSION__', _PICKER_INDEX_HTML)
        self.assertLess(_PICKER_INDEX_HTML.index('gw_scene_state.js'), _PICKER_INDEX_HTML.index('gw_scene_persistence.js'))
        self.assertLess(_PICKER_INDEX_HTML.index('gw_scene_persistence.js'), _PICKER_INDEX_HTML.index('gw_commands.js'))
        self.assertLess(_PICKER_INDEX_HTML.index('gw_commands.js'), _PICKER_INDEX_HTML.index('game_workbench.js'))

        self.assertIn("GW.createScenePersistence", persistence_js)
        self.assertIn("function sceneStorageKey()", persistence_js)
        self.assertIn("function restoreScene()", persistence_js)
        self.assertIn("window.localStorage.setItem(sceneStorageKey()", persistence_js)
        self.assertIn("window.localStorage.getItem(sceneStorageKey())", persistence_js)
        self.assertIn("GW.createSceneCommands", commands_js)
        self.assertIn("function makeDeleteModelCommand(model, index)", commands_js)
        self.assertIn("function makeTransformCommand(object, before, after)", commands_js)
        self.assertIn("GW.createScenePersistence", game_js)
        self.assertIn("GW.createSceneCommands", game_js)
        self.assertNotIn("window.localStorage.setItem(sceneStorageKey()", game_js)
        self.assertNotIn("window.localStorage.getItem(sceneStorageKey())", game_js)
        self.assertNotIn("function makeDeleteCommand(character, index)", game_js)
        self.assertNotIn("function makeTransformCommand(object, before, after)", game_js)

    def test_game_workbench_uses_generic_selected_object_commands(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        commands_path = FRONTEND_ROOT / "gw_commands.js"
        self.assertTrue(commands_path.exists())
        commands_js = commands_path.read_text(encoding="utf-8")

        self.assertIn("function deleteSelectedObject()", game_js)
        self.assertIn("function duplicateSelectedObject()", game_js)
        self.assertIn("sceneState.findModelFor(selectedObject)", game_js)
        self.assertIn("makeDeleteModelCommand(model, index)", commands_js)
        self.assertIn("makeCreateModelCommand(model)", commands_js)
        self.assertIn("makeDeleteCharacterCommand(character, index)", commands_js)
        self.assertNotIn("function deleteSelectedCharacter()", game_js)
        self.assertNotIn("duplicateSelectedCharacter();", game_js)

    def test_game_editor_grid_uses_shared_shader_viewport_grid(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        grid_start = game_js.index("function createGrid()")
        grid_end = game_js.index("function createGround()", grid_start)
        grid_body = game_js[grid_start:grid_end]

        self.assertIn("function updateEditorGrid()", game_js)
        self.assertIn("window.VC_VIEWPORT_GRID.create(scene, camera", grid_body)
        self.assertIn("window.VC_VIEWPORT_GRID.update(editorGrid, camera);", game_js)
        self.assertIn("minorColor: 0xc8cdd1", grid_body)
        self.assertIn("majorColor: 0xc8cdd1", grid_body)
        self.assertIn("minorAlpha: 0.24", grid_body)
        self.assertIn("majorAlpha: 0.24", grid_body)
        self.assertIn("axisXColor: 0xffffff", grid_body)
        self.assertIn("axisYColor: 0xffffff", grid_body)
        self.assertIn("axisInnerPx: 0.25", grid_body)
        self.assertIn("axisOuterPx: 0.85", grid_body)
        self.assertNotIn("function createEditorGridMaterial()", game_js)
        self.assertNotIn("new THREE.PlaneGeometry(1, 1)", grid_body)
        self.assertNotIn("EDITOR_GRID_SIZE", game_js)
        self.assertNotIn("new THREE.GridHelper", game_js)
        self.assertNotIn("new THREE.LineBasicMaterial", grid_body)

    def test_viewport_grid_script_loads_before_consumers(self):
        grid_script = '/area-picker/viewport_grid.js?v=__VERSION__'
        game_script = '/area-picker/game_workbench.js?v=__VERSION__'
        houdini_script = '/area-picker/houdini_preview.js?v=__VERSION__'
        self.assertIn(grid_script, _PICKER_INDEX_HTML)
        self.assertLess(_PICKER_INDEX_HTML.index(grid_script), _PICKER_INDEX_HTML.index(game_script))
        self.assertLess(_PICKER_INDEX_HTML.index(grid_script), _PICKER_INDEX_HTML.index(houdini_script))

    def test_game_workspace_details_tab_has_transform_inspector(self):
        self.assertIn('class="outline-side-tabs"', _PICKER_INDEX_HTML)
        game_panel = _PICKER_INDEX_HTML.split('class="action-panel-content game-side-panel"', 1)[1]
        game_workspace_style = _PICKER_STYLES.split(
            '#workspace[data-workspace-kind="game"] {',
            1,
        )[1].split("}", 1)[0]
        self.assertIn("grid-template-columns: 300px minmax(0, 1fr) minmax(300px, 326px);", game_workspace_style)
        self.assertNotIn("382px", game_workspace_style)
        self.assertNotIn('class="asset-side-tabs"', game_panel)
        self.assertNotIn('name="asset-side-tabs"', game_panel)
        self.assertLess(game_panel.index('id="game-side-resizer"'), game_panel.index('id="game-side-tabs"'))
        self.assertIn(".game-side-panel .outline-side-tabs", _PICKER_STYLES)
        self.assertIn(".game-side-panel > .outline-side-tabs", _PICKER_STYLES)
        self.assertIn(".game-side-panel > .outline-side-tabs {\n  display: none;", _PICKER_STYLES)
        self.assertIn(".game-side-panel > #game-scene-outline {\n  grid-column: 1 / -1;", _PICKER_STYLES)
        self.assertIn("--game-side-tab-strip-height: 26px;", _PICKER_STYLES)
        self.assertIn("min-height: var(--game-side-tab-strip-height, 26px);", _PICKER_STYLES)
        self.assertIn(".game-side-panel > #game-side-resizer {\n  grid-column: 1 / -1;", _PICKER_STYLES)
        self.assertIn(".game-side-panel > #game-side-tabs {\n  grid-column: 1 / -1;", _PICKER_STYLES)
        self.assertNotIn(".game-side-panel .asset-side-tabs", _PICKER_STYLES)
        self.assertNotIn(".game-side-panel > .asset-side-tabs", _PICKER_STYLES)
        self.assertIn(
            ".game-side-panel > .outline-side-tabs,\n"
            ".game-side-panel > #game-scene-outline,\n"
            ".game-side-panel > #game-side-tabs {\n"
            "  border-color: transparent;",
            _PICKER_STYLES,
        )
        self.assertLess(
            _PICKER_STYLES.index(".game-side-panel .outline-side-tabs"),
            _PICKER_STYLES.index(".game-side-panel > .outline-side-tabs,\n.game-side-panel > #game-scene-outline"),
        )
        self.assertIn("grid-template-columns: 48px minmax(0, 1fr);", _PICKER_STYLES)
        self.assertIn("column-gap: 0;", _PICKER_STYLES)
        self.assertIn("border-radius: 8px 0 0 8px;", _PICKER_STYLES)
        self.assertNotIn(".game-side-panel > #game-side-tabs {\n  border-top-left-radius: 0;\n  border-bottom-left-radius: 0;", _PICKER_STYLES)
        self.assertIn("border-radius: 6px 0 0 6px;", _PICKER_STYLES)
        side_label_checked_style = _PICKER_STYLES.split(".side-rail-input:checked + .side-rail-label", 1)[1].split("}", 1)[0]
        self.assertIn("border-color: transparent;", side_label_checked_style)
        self.assertIn("box-shadow: inset 2px 0 0 color-mix(in srgb, var(--accent) 62%, transparent);", _PICKER_STYLES)
        self.assertIn(".outline-side-tabs .side-rail-input:checked + .side-rail-label", _PICKER_STYLES)
        outline_side_label_style = _PICKER_STYLES.split(".outline-side-tabs .side-rail-input:checked + .side-rail-label", 1)[1].split("}", 1)[0]
        self.assertIn("box-shadow: none;", outline_side_label_style)
        self.assertNotIn(".asset-side-tabs .side-rail-input:checked + .side-rail-label", _PICKER_STYLES)
        self.assertIn('id="game-side-tabs" class="action-tabs" aria-label="我的游戏右栏标签页" style="--action-tab-count: 4;"', game_panel)
        self.assertIn('<label class="action-tab-label" for="game-side-tab-1">细节</label>', game_panel)
        self.assertIn('<label class="action-tab-label" for="game-side-tab-2">云端资产</label>', game_panel)
        self.assertIn('class="action-tab-panel cloud-assets-panel" aria-label="云端资产"', game_panel)
        self.assertIn('<label class="action-tab-label" for="game-side-tab-3">AI修改</label>', game_panel)
        self.assertIn('<label class="action-tab-label" for="game-side-tab-4">发布</label>', game_panel)
        self.assertLess(game_panel.index('for="game-side-tab-1">细节'), game_panel.index('for="game-side-tab-2">云端资产'))
        self.assertLess(game_panel.index('for="game-side-tab-2">云端资产'), game_panel.index('for="game-side-tab-3">AI修改'))
        self.assertLess(game_panel.index('for="game-side-tab-3">AI修改'), game_panel.index('for="game-side-tab-4">发布'))
        self.assertIn('class="action-tab-panel inspector-panel" aria-label="细节"', game_panel)
        self.assertIn('id="inspector-name"', game_panel)
        self.assertIn('id="inspector-pos-x"', game_panel)
        self.assertIn('id="inspector-rot-x"', game_panel)
        self.assertIn('id="inspector-scale-x"', game_panel)
        self.assertIn('<div class="inspector-group-title">旋转</div>', game_panel)
        self.assertNotIn('旋转（度）', game_panel)
        self.assertIn('class="inspector-subcontainers" aria-label="细节子容器"', game_panel)
        self.assertIn('class="inspector-subcontainer" data-inspector-container="model" aria-label="模型"', game_panel)
        self.assertIn('class="inspector-subcontainer" data-inspector-container="material" aria-label="材质"', game_panel)
        self.assertIn('class="inspector-subcontainer" data-inspector-container="logic" aria-label="功能逻辑"', game_panel)
        self.assertIn('<div class="inspector-subcontainer-title">模型</div>', game_panel)
        self.assertIn('<div class="inspector-subcontainer-title">材质</div>', game_panel)
        self.assertIn('<div class="inspector-subcontainer-title">功能逻辑</div>', game_panel)
        inspector_panel_style = _PICKER_STYLES.split(
            ".action-tab-input:checked + .action-tab-label + .inspector-panel",
            1,
        )[1].split("}", 1)[0]
        inspector_base_style = _PICKER_STYLES.split(".inspector-panel", 1)[1].split("}", 1)[0]
        inspector_body_style = _PICKER_STYLES.split(".inspector-body", 1)[1].split("}", 1)[0]
        inspector_name_style = _PICKER_STYLES.split(".inspector-name-input", 1)[1].split("}", 1)[0]
        inspector_name_row_style = _PICKER_STYLES.split(".inspector-name-row", 1)[1].split("}", 1)[0]
        inspector_group_style = _PICKER_STYLES.split(".inspector-group", 1)[1].split("}", 1)[0]
        inspector_group_title_style = _PICKER_STYLES.split(".inspector-group-title", 1)[1].split("}", 1)[0]
        inspector_row_style = _PICKER_STYLES.split(".inspector-row", 1)[1].split("}", 1)[0]
        inspector_number_style = _PICKER_STYLES.split(".inspector-number", 1)[1].split("}", 1)[0]
        inspector_subcontainers_style = _PICKER_STYLES.split(".inspector-subcontainers", 1)[1].split("}", 1)[0]
        inspector_subcontainer_style = _PICKER_STYLES.split(".inspector-subcontainer {", 1)[1].split("}", 1)[0]
        inspector_subcontainer_title_style = _PICKER_STYLES.split(".inspector-subcontainer-title", 1)[1].split("}", 1)[0]
        self.assertIn("display: none;", inspector_base_style)
        self.assertIn("gap: 6px;", inspector_panel_style)
        self.assertIn("display: flex;", inspector_panel_style)
        self.assertIn("padding: 6px;", inspector_panel_style)
        self.assertIn("gap: 6px;", inspector_body_style)
        self.assertIn("display: grid;", inspector_name_row_style)
        self.assertIn("grid-template-columns: 44px minmax(0, 1fr);", inspector_name_row_style)
        self.assertIn("align-items: center;", inspector_name_row_style)
        self.assertIn("display: grid;", inspector_group_style)
        self.assertIn("grid-template-columns: 44px minmax(0, 1fr);", inspector_group_style)
        self.assertIn("align-items: center;", inspector_group_style)
        self.assertIn("grid-column: 1;", inspector_group_title_style)
        self.assertIn("grid-column: 2;", inspector_row_style)
        self.assertIn("min-height: 22px;", inspector_name_style)
        self.assertIn("border-radius: 4px;", inspector_name_style)
        self.assertIn("gap: 4px;", inspector_row_style)
        self.assertIn("min-height: 22px;", inspector_number_style)
        self.assertIn("border-radius: 4px;", inspector_number_style)
        self.assertIn("display: flex;", inspector_subcontainers_style)
        self.assertIn("flex-direction: column;", inspector_subcontainers_style)
        self.assertIn("gap: 10px;", inspector_subcontainers_style)
        self.assertIn("min-height: 64px;", inspector_subcontainer_style)
        self.assertIn("border: 1px solid var(--line-soft);", inspector_subcontainer_style)
        self.assertIn("border-radius: 6px;", inspector_subcontainer_style)
        self.assertIn("font-size: 11px;", inspector_subcontainer_title_style)
        self.assertIn("color: var(--subtle);", inspector_subcontainer_title_style)
        self.assertNotIn('<label class="action-tab-label" for="game-side-tab-1">资产</label>', game_panel)
        self.assertNotIn('<div class="action-tab-panel" aria-label="资产">', game_panel)
        self.assertNotIn('id="asset-dir-form"', game_panel)
        self.assertNotIn('id="asset-dir-input"', game_panel)
        self.assertNotIn('id="asset-dir-tree"', game_panel)
        self.assertNotIn('class="asset-actions"', game_panel)
        self.assertNotIn('asset-cat-character', game_panel)
        self.assertNotIn('asset-cat-scene-whitebox', game_panel)
        self.assertNotIn('asset-cat-scene-component', game_panel)
        self.assertNotIn('asset-cat-logic', game_panel)
        self.assertNotIn('本地资产目录', game_panel)
        self.assertNotIn('人物角色', game_panel)
        self.assertNotIn('场景白盒', game_panel)
        self.assertNotIn('场景组件', game_panel)
        self.assertNotIn('id="import-houdini-whitebox-btn"', game_panel)
        self.assertNotIn("导入 Houdini 白盒", game_panel)
        self.assertNotIn('/area-picker/asset_dir.js', _PICKER_INDEX_HTML)
        self.assertNotIn(".asset-dir", _PICKER_STYLES)

    def test_game_workspace_has_bottom_ui_container(self):
        asset_js_path = FRONTEND_ROOT / "scene_assets.js"
        self.assertTrue(asset_js_path.exists())
        asset_js = asset_js_path.read_text(encoding="utf-8")
        host_html = _PICKER_INDEX_HTML.split(
            '<div id="composition-workbench-host"',
            1,
        )[1].split('</section>', 1)[0]
        self.assertIn('id="game-bottom-ui"', host_html)
        self.assertIn('class="game-bottom-ui"', host_html)
        self.assertIn('aria-label="编辑器底部面板"', host_html)
        self.assertIn('id="scene-asset-browser"', host_html)
        self.assertIn('class="scene-asset-browser"', host_html)
        self.assertIn('工程资产目录', host_html)
        self.assertIn('id="scene-asset-status"', host_html)
        self.assertIn('id="game-status"', host_html)
        self.assertIn('class="game-status"', host_html)
        self.assertIn('id="scene-asset-refresh"', host_html)
        self.assertIn('id="scene-asset-grid"', host_html)
        self.assertNotIn('拖入角色后点击运行</div>', host_html)
        self.assertIn(".game-status", _PICKER_STYLES)
        self.assertLess(host_html.index('id="game-scene-host"'), host_html.index('id="game-bottom-ui"'))
        self.assertLess(host_html.index('id="game-bottom-ui"'), host_html.index('id="game-drag-preview"'))
        self.assertIn('/area-picker/scene_assets.js?v=__VERSION__', _PICKER_INDEX_HTML)
        self.assertLess(_PICKER_INDEX_HTML.index('scene_project.js'), _PICKER_INDEX_HTML.index('scene_assets.js'))
        self.assertLess(_PICKER_INDEX_HTML.index('scene_assets.js'), _PICKER_INDEX_HTML.index('workspace.js'))
        self.assertIn("fetch('/scene-assets')", asset_js)
        self.assertIn("window.addEventListener('scene-root-changed'", asset_js)
        self.assertIn("function renderAssets", asset_js)
        self.assertIn("asset.display_name || asset.name", asset_js)
        self.assertIn("scene-asset-thumbnail", asset_js)
        self.assertIn("item.dataset.sceneAssetPath", asset_js)
        self.assertIn("item.dataset.sceneAssetUrl", asset_js)
        self.assertIn("'/scene-asset-file?path=' + encodeURIComponent", asset_js)
        self.assertIn("{ id: 'all', label: '全部' }", asset_js)
        self.assertIn("{ id: 'model', label: '模型' }", asset_js)
        self.assertIn("{ id: 'other', label: '其他' }", asset_js)
        self.assertNotIn("label: '贴图'", asset_js)
        self.assertNotIn("label: '材质'", asset_js)
        self.assertNotIn("label: '场景'", asset_js)
        self.assertIn("return asset.category !== 'model';", asset_js)
        bottom_ui_style = _PICKER_STYLES.split(".game-bottom-ui {", 1)[1].split("}", 1)[0]
        self.assertIn("position: absolute;", bottom_ui_style)
        self.assertIn("left: 0;", bottom_ui_style)
        self.assertIn("right: 0;", bottom_ui_style)
        self.assertNotIn("right: 326px;", bottom_ui_style)
        self.assertIn("bottom: 0;", bottom_ui_style)
        self.assertIn("height: clamp(140px, 20%, 200px);", bottom_ui_style)
        self.assertIn("z-index: 12;", bottom_ui_style)
        self.assertIn(".scene-asset-browser", _PICKER_STYLES)
        self.assertIn(".scene-asset-grid", _PICKER_STYLES)
        self.assertIn(".scene-asset-item", _PICKER_STYLES)
        server_source = Path(area_picker.__file__).read_text(encoding="utf-8")
        self.assertIn("parsed.path == '/scene-assets'", server_source)
        self.assertIn("parsed.path == '/scene-asset-file'", server_source)
        self.assertIn("def _scene_assets_status", server_source)
        self.assertIn("def _scene_asset_file_path", server_source)
        self.assertIn("#game-workbench.is-playing .game-bottom-ui", _PICKER_STYLES)

    def test_game_workspace_cloud_assets_tab_shows_server_material_library(self):
        cloud_js_path = FRONTEND_ROOT / "cloud_assets.js"
        self.assertTrue(cloud_js_path.exists())
        cloud_js = cloud_js_path.read_text(encoding="utf-8")
        game_panel = _PICKER_INDEX_HTML.split('class="action-panel-content game-side-panel"', 1)[1]
        server_source = Path(area_picker.__file__).read_text(encoding="utf-8")

        self.assertIn('id="cloud-asset-browser"', game_panel)
        self.assertIn('id="cloud-asset-status"', game_panel)
        self.assertIn('id="cloud-asset-refresh"', game_panel)
        self.assertIn('id="cloud-asset-categories"', game_panel)
        self.assertIn('id="cloud-asset-grid"', game_panel)
        self.assertIn('/area-picker/cloud_assets.js?v=__VERSION__', _PICKER_INDEX_HTML)
        self.assertIn("fetch('/cloud-assets')", cloud_js)
        self.assertIn("function renderCloudAssets", cloud_js)
        self.assertIn("window.VC_CLOUD_ASSETS", cloud_js)
        self.assertIn("runtimeType", cloud_js)
        self.assertIn(".cloud-asset-browser", _PICKER_STYLES)
        self.assertIn(".cloud-asset-card", _PICKER_STYLES)
        self.assertIn("def _cloud_assets_status", server_source)
        self.assertIn("parsed.path == '/cloud-assets'", server_source)
        self.assertIn("'ueperson-body-material'", server_source)
        self.assertIn("'toon-render-material'", server_source)

        self.assertTrue(hasattr(area_picker, "_cloud_assets_status"))
        payload = area_picker._cloud_assets_status()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["available"])
        self.assertEqual(payload["counts"]["material"], 2)
        self.assertEqual(
            [asset["runtimeType"] for asset in payload["assets"]],
            ["MeshPhysicalMaterial", "MeshToonMaterial"],
        )
        self.assertEqual(
            [asset["name"] for asset in payload["assets"]],
            ["MeshPhysicalMaterial 材质球", "卡通渲染材质球"],
        )

    def test_game_scene_storage_is_scoped_to_current_scene_root(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        persistence_js = (FRONTEND_ROOT / "gw_scene_persistence.js").read_text(encoding="utf-8")
        self.assertIn("function sceneStorageKey()", persistence_js)
        self.assertIn("currentSceneRoot", persistence_js)
        self.assertIn("encodeURIComponent(currentSceneRoot)", persistence_js)
        self.assertIn("window.localStorage.setItem(sceneStorageKey()", persistence_js)
        self.assertIn("window.localStorage.getItem(sceneStorageKey())", persistence_js)
        self.assertIn("function applySceneRootStatus(d)", persistence_js)
        self.assertIn("fetch('/scene-root')", persistence_js)
        self.assertIn("window.addEventListener('scene-root-changed'", game_js)
        self.assertIn("scenePersistence.applySceneRootStatus(event.detail || {})", game_js)
        self.assertIn("scenePersistence.restoreScene()", game_js)
        self.assertNotIn("window.localStorage.setItem(SCENE_STORAGE_KEY", game_js)
        self.assertNotIn("window.localStorage.getItem(SCENE_STORAGE_KEY", game_js)
        self.assertNotIn("window.localStorage.setItem(sceneStorageKey()", game_js)
        self.assertNotIn("window.localStorage.getItem(sceneStorageKey())", game_js)

    def test_scene_model_assets_are_persisted_as_scene_objects(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        asset_js = (FRONTEND_ROOT / "gw_assets.js").read_text(encoding="utf-8")
        scene_state_js = (FRONTEND_ROOT / "gw_scene_state.js").read_text(encoding="utf-8")

        # Array storage + serialize() live in gw_scene_state.js; game_workbench.js
        # only orchestrates restore/add/remove around it.
        self.assertIn("var sceneModels = [];", scene_state_js)
        self.assertIn("models: sceneModels.map(function(model)", scene_state_js)
        self.assertIn("url: model.url", scene_state_js)
        self.assertIn("label: model.label", scene_state_js)
        self.assertIn("function restoreSceneModel(item)", game_js)
        self.assertIn("data.models || []", game_js)
        self.assertIn("assetLoader.loadSceneAsset(item.url, null, item.label", game_js)
        self.assertIn("function addSceneModel(model, options)", game_js)
        self.assertIn("function removeSceneModel(model, options)", game_js)
        self.assertIn("ctx.addSceneModel({", asset_js)
        self.assertIn("url: url", asset_js)
        self.assertIn("label: label || root.userData.assetLabel || '模型资产'", asset_js)
        self.assertNotIn("var prev = ctx.getLoadedModel();", asset_js)
        self.assertNotIn("ctx.setLoadedModel(root);", asset_js)
        self.assertNotIn("ctx.setLoadedWhiteboxUrl(url);", asset_js)

    def test_scene_models_are_pickable_from_viewport(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        scene_state_js = (FRONTEND_ROOT / "gw_scene_state.js").read_text(encoding="utf-8")

        self.assertIn("function getPickableSceneObjects()", game_js)
        self.assertIn("sceneModels.forEach(function(model)", scene_state_js)
        self.assertIn("flat.push(model.root);", scene_state_js)
        self.assertIn("raycaster.intersectObjects(getPickableSceneObjects(), true)", game_js)

    def test_game_workbench_uses_scene_object_selection_naming(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        asset_js = (FRONTEND_ROOT / "gw_assets.js").read_text(encoding="utf-8")
        self.assertIn("function selectSceneObject(object)", game_js)
        self.assertIn("selectSceneObject: selectSceneObject", game_js)
        self.assertIn("selectSceneObject(picked);", game_js)
        self.assertNotIn("function selectCharacter(object)", game_js)
        self.assertNotIn("selectCharacter: selectCharacter", game_js)

    def test_scene_asset_file_path_is_limited_to_scene_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            scene_root = root / "Project"
            scene_root.mkdir()
            asset = scene_root / "Houdini_Whitebox.glb"
            outside = root / "outside.glb"
            asset.write_bytes(b"glb")
            outside.write_bytes(b"outside")
            with patch.object(area_picker, "_scene_root_status", return_value={
                "scene_root": str(scene_root),
                "scene_root_exists": True,
            }):
                resolved = area_picker._scene_asset_file_path("Houdini_Whitebox.glb")
                escaped = area_picker._scene_asset_file_path("../outside.glb")

        self.assertEqual(resolved, asset.resolve())
        self.assertIsNone(escaped)

    def test_houdini_sync_button_moves_whitebox_to_editor_asset_browser(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        self.assertIn("fetch('/sync-whitebox-to-scene-assets'", game_js)
        self.assertIn("window.VC_SCENE_ASSETS.refresh()", game_js)
        self.assertIn("同步至当前编辑器资产目录", _PICKER_INDEX_HTML)
        server_source = Path(area_picker.__file__).read_text(encoding="utf-8")
        self.assertIn("parsed.path == '/sync-whitebox-to-scene-assets'", server_source)
        self.assertIn("def _sync_houdini_whitebox_to_scene_assets", server_source)

    def test_bottom_scene_assets_drag_into_game_scene(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        self.assertIn("var sceneAssetGrid = document.getElementById('scene-asset-grid');", game_js)
        self.assertIn("sceneAssetGrid.addEventListener('pointerdown', beginAssetDrag);", game_js)
        self.assertIn("closest('.scene-asset-item[data-scene-asset-path]')", game_js)
        self.assertIn("kind: 'scene-asset'", game_js)
        self.assertIn("assetLoader.loadSceneAsset(dragState.asset.url, point, dragState.asset.name);", game_js)
        self.assertIn("function loadSceneAsset(url, point, label, options)", (FRONTEND_ROOT / "gw_assets.js").read_text(encoding="utf-8"))

    def test_game_play_mode_hides_editor_overlays_and_start_ui(self):
        # enter/exit moved into gw_play.js; selection-highlight + overlay sync stay
        # in the host. Pointer lock must not auto-engage on play entry.
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        play_js = (FRONTEND_ROOT / "gw_play.js").read_text(encoding="utf-8")
        enter_start = play_js.index("function enter(character)")
        enter_end = play_js.index("function exit()", enter_start)
        enter_body = play_js[enter_start:enter_end]

        self.assertNotIn("BoxHelper", game_js)
        self.assertNotIn("BoxHelper", play_js)
        self.assertIn("function syncSelectionHighlight()", game_js)
        self.assertIn("syncEditOverlays();", game_js)
        self.assertNotIn("requestPointerLock();", enter_body)
        self.assertIn("#game-workbench.is-playing .game-toolbar", _PICKER_STYLES)
        self.assertIn("#game-workbench.is-playing .game-bottom-ui", _PICKER_STYLES)

    def test_game_play_mode_has_gravity_jump_and_grounded_walk(self):
        # Play mode applies gravity, jumps on Space only when grounded, and gates
        # walking on grounded (UE-style). The host samples ground height from the
        # whitebox layers / z=0 plane and injects it into the controller.
        play_js = (FRONTEND_ROOT / "gw_play.js").read_text(encoding="utf-8")
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        self.assertIn("function applyGravity(deltaTime)", play_js)
        self.assertIn("gravity: -32", play_js)
        self.assertIn("jumpSpeed: 17.9", play_js)
        self.assertIn("verticalVelocity += config.gravity * deltaTime;", play_js)
        self.assertIn("if (code === 'space')", play_js)
        self.assertIn("verticalVelocity = config.jumpSpeed;", play_js)
        self.assertIn("if (grounded) {", play_js)
        self.assertIn("function sampleGroundHeight(x, y)", game_js)
        self.assertIn("raycaster.intersectObjects(whiteboxLayers, true)", game_js)
        self.assertIn("sampleGroundHeight: sampleGroundHeight", game_js)

    def test_game_workbench_static_version_changes_with_script(self):
        game_js_path = FRONTEND_ROOT / "game_workbench.js"
        stat = game_js_path.stat()
        fingerprint = f"{int(stat.st_mtime)}-{stat.st_size}"
        self.assertIn(fingerprint, area_picker._frontend_asset_version())

    def test_houdini_panel_preview_uses_explicit_whitebox_contract(self):
        preview_js = (FRONTEND_ROOT / "houdini_preview.js").read_text(encoding="utf-8")
        pipeline_js = (FRONTEND_ROOT / "pipeline_status.js").read_text(encoding="utf-8")

        self.assertIn("function resetPreviewView()", preview_js)
        self.assertIn("function fitModelToPreview(model, pivot)", preview_js)
        self.assertIn("asset.whitebox", preview_js)
        self.assertIn("whitebox.url", preview_js)
        self.assertIn("window.VC_HOUDINI_PREVIEW.update(d);", pipeline_js)
        self.assertNotIn("model_ready && !d.running", preview_js)

    def test_game_character_uses_ueperson_avatar_from_three_player_controller(self):
        # Avatar loading/animation lives in gw_character.js; the run-mode
        # controller (gw_play.js) drives the motion adapter during play.
        character_js = (FRONTEND_ROOT / "gw_character.js").read_text(encoding="utf-8")
        play_js = (FRONTEND_ROOT / "gw_play.js").read_text(encoding="utf-8")
        robot_glb = FRONTEND_ROOT / "assets" / "characters" / "UEPerson.glb"
        self.assertTrue(robot_glb.is_file())
        self.assertGreater(robot_glb.stat().st_size, 5_000_000)
        self.assertIn("UEPerson.glb", character_js)
        self.assertIn("Model source: hh-hang/three-player-controller example/public/glb/UEPerson.glb", character_js)
        self.assertIn('import("/static/three/GLTFLoader.js")', character_js)
        self.assertIn('new THREE.AnimationMixer', character_js)
        self.assertIn("idle: 'idle'", character_js)
        self.assertIn("walk: 'walk'", character_js)
        self.assertIn("run: 'run'", character_js)
        self.assertIn("jump: 'jumpStart'", character_js)
        self.assertIn("actions[ROBOT_ANIMATIONS.idle]", character_js)
        self.assertIn("actions[ROBOT_ANIMATIONS.run]", character_js)
        self.assertIn("actions[ROBOT_ANIMATIONS.walk]", character_js)
        self.assertIn("actions[ROBOT_ANIMATIONS.jump]", character_js)
        self.assertIn('character.userData.robotAvatar', character_js)
        self.assertIn('character.userData.animationMixer', character_js)
        self.assertIn('createCharacterMaterial', character_js)
        self.assertIn('updateCharacterMotion(player, moveDirection, deltaTime)', play_js)
        self.assertIn('resetCharacterMotion(player)', play_js)

    def test_game_play_starts_third_person_from_character_facing(self):
        character_js = (FRONTEND_ROOT / "gw_character.js").read_text(encoding="utf-8")
        play_js = (FRONTEND_ROOT / "gw_play.js").read_text(encoding="utf-8")
        self.assertIn("model.rotation.y = Math.PI;", character_js)
        self.assertIn("function syncYawFromCharacter(character)", play_js)
        self.assertIn("yaw = character.rotation.z + Math.PI / 2;", play_js)
        self.assertIn("syncYawFromCharacter(character);", play_js)
        self.assertNotIn("syncYawFromCamera();", play_js)

    def test_game_character_preserves_ueperson_horizontal_origin(self):
        character_js = (FRONTEND_ROOT / "gw_character.js").read_text(encoding="utf-8")
        self.assertNotIn("model.position.x -= center.x;", character_js)
        self.assertNotIn("model.position.y -= center.y;", character_js)
        self.assertIn("model.position.z -= box.min.z;", character_js)

    def test_game_character_uses_capsule_origin_and_model_offset(self):
        # character.position is the feet/ground-contact point (standard
        # character-controller convention) -- fitRobotAvatar anchors the
        # model's feet at the group's own local origin, so groundOffset is 0.
        character_js = (FRONTEND_ROOT / "gw_character.js").read_text(encoding="utf-8")
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        play_js = (FRONTEND_ROOT / "gw_play.js").read_text(encoding="utf-8")
        self.assertIn("character.userData.groundOffset = 0;", character_js)
        self.assertIn("model.position.z -= box.min.z;", character_js)
        self.assertNotIn("model.position.z -= ROBOT_ORIGIN_HEIGHT;", character_js)
        self.assertIn("function getCharacterGroundOffset(character)", game_js)
        self.assertIn("point.z + getCharacterGroundOffset(character)", game_js)
        self.assertIn("function getPlayerGroundOffset()", play_js)
        self.assertIn("groundZ + groundOffset", play_js)
        self.assertIn("config.cameraTargetHeight - groundOffset", play_js)

    def test_game_camera_clip_uses_scene_bounds_not_world_origin(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        self.assertNotIn("camera.position.length()", game_js)
        self.assertIn("function getCameraClipDistance()", game_js)
        self.assertIn("sceneClipSphere.center", game_js)
        self.assertIn("sceneClipSphere.radius", game_js)
        self.assertIn("camera.position.distanceTo(sceneClipSphere.center)", game_js)
        self.assertIn("var near = Math.max(0.1, far / 5000);", game_js)

    def test_game_workspace_has_composition_viewport_controls(self):
        # Editor camera (alt-orbit/track/dolly + flight speed) lives in gw_camera.js;
        # run-button label sync stays in the host.
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        camera_js = (FRONTEND_ROOT / "gw_camera.js").read_text(encoding="utf-8")
        self.assertIn('id="game-speed-control"', _PICKER_INDEX_HTML)
        self.assertIn('id="game-speed-input"', _PICKER_INDEX_HTML)
        self.assertIn('class="game-tool-button game-asset-button"', _PICKER_INDEX_HTML)
        self.assertIn('class="game-tool-button game-run-button"', _PICKER_INDEX_HTML)
        self.assertIn('id="game-run-label"', _PICKER_INDEX_HTML)
        self.assertIn('.game-toolbar-shell', _PICKER_STYLES)
        self.assertIn('.game-speed-control', _PICKER_STYLES)
        self.assertIn('.game-run-label', _PICKER_STYLES)
        self.assertIn('-webkit-appearance: none;', _PICKER_STYLES)
        self.assertIn('appearance: textfield;', _PICKER_STYLES)
        self.assertIn('handleAltViewportDrag', camera_js)
        self.assertIn('setMoveSpeed', camera_js)
        self.assertIn('runLabel.textContent', game_js)
        self.assertNotIn('runButton.textContent', game_js)
        self.assertIn('event.altKey', camera_js)
        self.assertIn("beginViewportDrag('orbit'", camera_js)
        self.assertIn("beginViewportDrag('track'", camera_js)
        self.assertIn("beginViewportDrag('dolly'", camera_js)

    def test_game_viewport_shows_runtime_render_stats_overlay(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        self.assertIn('id="game-runtime-stats"', _PICKER_INDEX_HTML)
        self.assertIn('data-runtime-stat="frame-ms"', _PICKER_INDEX_HTML)
        self.assertIn('data-runtime-stat="draw-calls"', _PICKER_INDEX_HTML)
        self.assertIn('data-runtime-stat="triangles"', _PICKER_INDEX_HTML)
        self.assertIn('data-runtime-stat="objects"', _PICKER_INDEX_HTML)
        self.assertIn('data-runtime-stat="meshes"', _PICKER_INDEX_HTML)
        self.assertIn('.game-runtime-stats', _PICKER_STYLES)
        runtime_stats_style = _PICKER_STYLES.split(".game-runtime-stats", 1)[1].split("}", 1)[0]
        runtime_stat_style = _PICKER_STYLES.split(".game-runtime-stat {", 1)[1].split("}", 1)[0]
        self.assertIn("position: absolute;", runtime_stats_style)
        self.assertIn("right: 10px;", runtime_stats_style)
        self.assertIn("top: 10px;", runtime_stats_style)
        self.assertIn("display: flex;", runtime_stats_style)
        self.assertIn("flex-direction: column;", runtime_stats_style)
        self.assertNotIn("grid-template-columns: repeat(5, auto);", runtime_stats_style)
        self.assertIn("grid-template-columns: auto auto;", runtime_stat_style)
        self.assertNotIn("border:", runtime_stat_style)
        self.assertNotIn("background:", runtime_stat_style)
        self.assertNotIn("box-shadow:", runtime_stat_style)
        self.assertNotIn("backdrop-filter:", runtime_stat_style)
        self.assertIn("function bindRuntimeStatsHud()", game_js)
        self.assertIn("function updateRuntimeStats(frameTimeMs, now)", game_js)
        self.assertIn("runtimeStatsFields.frameMs", game_js)
        self.assertIn("var renderInfo = renderer.info && renderer.info.render", game_js)
        self.assertIn("renderInfo.calls", game_js)
        self.assertIn("renderInfo.triangles", game_js)
        self.assertIn("scene.traverse(function(object)", game_js)
        self.assertIn("if (object.isMesh) counts.meshes += 1;", game_js)
        self.assertIn("render(frameTimeMs, now);", game_js)

    def test_game_transform_controls_have_explicit_modes(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        self.assertIn('data-transform-mode="translate"', _PICKER_INDEX_HTML)
        self.assertIn('data-transform-mode="rotate"', _PICKER_INDEX_HTML)
        self.assertIn('data-transform-mode="scale"', _PICKER_INDEX_HTML)
        self.assertIn("function setTransformMode(mode)", game_js)
        self.assertIn("transformControls.setMode(transformMode);", game_js)
        self.assertIn("transformControls.setSize(1);", game_js)
        self.assertIn("function bindTransformModeButtons()", game_js)

    def test_game_transform_controls_own_pointer_interaction(self):
        # Camera controller (gw_camera.js) defers to the gizmo before picking; the
        # isTransformControlActive predicate is injected from the host.
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        camera_js = (FRONTEND_ROOT / "gw_camera.js").read_text(encoding="utf-8")
        controls_start = camera_js.index("function createGameCameraController(ctx)")
        down_start = camera_js.index("function handlePointerDown(event)", controls_start)
        down_end = camera_js.index("function handlePointerMove(event)", down_start)
        down_body = camera_js[down_start:down_end]

        self.assertIn("function isTransformControlActive()", game_js)
        self.assertIn("transformControls.dragging || transformControls.axis", game_js)
        self.assertIn("if (isTransformControlActive()) return true;", down_body)
        self.assertLess(
            down_body.index("if (isTransformControlActive()) return true;"),
            down_body.index("pickCharacter(event);"),
        )

    def test_game_middle_mouse_tracks_viewport_without_alt(self):
        camera_js = (FRONTEND_ROOT / "gw_camera.js").read_text(encoding="utf-8")
        controls_start = camera_js.index("function createGameCameraController(ctx)")
        down_start = camera_js.index("function handlePointerDown(event)", controls_start)
        down_end = camera_js.index("function handlePointerMove(event)", down_start)
        down_body = camera_js[down_start:down_end]

        self.assertIn("if (event.button === 1) {", down_body)
        self.assertIn("beginViewportDrag('track', event, getViewportPivot(event));", down_body)

    def test_game_right_mouse_wheel_adjusts_flight_speed(self):
        # Wheel handler stays in host bindInput; speed math lives in gw_camera.js.
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        camera_js = (FRONTEND_ROOT / "gw_camera.js").read_text(encoding="utf-8")
        wheel_start = game_js.index("sceneHost.addEventListener('wheel'")
        wheel_end = game_js.index("}, { passive: false });", wheel_start)
        wheel_body = game_js[wheel_start:wheel_end]

        self.assertIn("function adjustMoveSpeed(event)", camera_js)
        self.assertIn("var speedStep = Math.max(5, moveSpeed * 0.12);", camera_js)
        self.assertIn("return setMoveSpeed(moveSpeed + (event.deltaY < 0 ? speedStep : -speedStep));", camera_js)
        self.assertIn("if (cameraControls.isLooking()) {", wheel_body)
        self.assertIn("cameraControls.adjustMoveSpeed(event);", wheel_body)
        self.assertLess(
            wheel_body.index("cameraControls.adjustMoveSpeed(event);"),
            wheel_body.index("cameraControls.zoomView(event);"),
        )

    def test_game_editor_shortcuts_match_unreal_viewport(self):
        # Transform-mode shortcuts stay in host; the dolly math moved to gw_camera.js.
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        camera_js = (FRONTEND_ROOT / "gw_camera.js").read_text(encoding="utf-8")
        self.assertIn("setTransformMode('translate');", game_js)
        self.assertIn("setTransformMode('rotate');", game_js)
        self.assertIn("setTransformMode('scale');", game_js)
        self.assertNotIn("code === 'keyr' || code === 'space'", game_js)
        self.assertIn("code === 'space'", game_js)
        self.assertIn("state.distance - dy * state.distance * 0.01", camera_js)

    def test_game_renderer_matches_composition_lighting_baseline(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        self.assertIn('var DEFAULT_EDITOR_SKY_COLOR = 0x8fb7d9;', game_js)
        self.assertIn("window.VC_RENDER_PROFILE.configureColorManagement(THREE);", game_js)
        self.assertIn("renderer = window.VC_RENDER_PROFILE.createRenderer(THREE, {", game_js)
        self.assertIn("shadowQuality: 'high'", game_js)
        self.assertIn("window.VC_RENDER_PROFILE.createCascadedShadowLighting(THREE, scene, camera, {", game_js)
        self.assertIn("includeAmbient: true", game_js)
        self.assertIn("editorEnvironment = window.VC_RENDER_PROFILE.applyEnvironment(THREE, renderer, scene, {", game_js)
        self.assertIn('scene.background = new THREE.Color(DEFAULT_EDITOR_SKY_COLOR);', game_js)
        self.assertNotIn('scene.background = new THREE.Color(0x666a6c);', game_js)
        self.assertIn('opacity: 0.4', game_js)
        self.assertIn('ambientLight = lighting.ambient;', game_js)
        self.assertIn('csm = lighting.csm;', game_js)
        self.assertNotIn('renderer.shadowMap.type = THREE.PCFSoftShadowMap;', game_js)
        self.assertNotIn('sun.shadow.mapSize.set(4096, 4096);', game_js)

    def test_game_workspace_uses_transform_controls(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        self.assertIn('type="importmap"', _PICKER_INDEX_HTML)
        self.assertIn('/static/three/three.module.js', _PICKER_INDEX_HTML)
        self.assertIn('/static/three/TransformControls.js', game_js)
        self.assertIn('transformControls.attach(selectedObject)', game_js)
        self.assertIn('transformControls.addEventListener("dragging-changed"', game_js)

    def test_render_profile_script_loads_before_three_viewports(self):
        profile_script = '/area-picker/render_profile.js?v=__VERSION__'
        grid_script = '/area-picker/viewport_grid.js?v=__VERSION__'
        game_script = '/area-picker/game_workbench.js?v=__VERSION__'
        houdini_script = '/area-picker/houdini_preview.js?v=__VERSION__'
        self.assertIn(profile_script, _PICKER_INDEX_HTML)
        self.assertLess(_PICKER_INDEX_HTML.index(profile_script), _PICKER_INDEX_HTML.index(grid_script))
        self.assertLess(_PICKER_INDEX_HTML.index(profile_script), _PICKER_INDEX_HTML.index(game_script))
        self.assertLess(_PICKER_INDEX_HTML.index(profile_script), _PICKER_INDEX_HTML.index(houdini_script))

    def test_game_viewport_orbit_pivot_stays_on_view_ray(self):
        # The pivot must always lie on the camera's current forward ray so the
        # first lookAt(target) on drag-start is a no-op -- otherwise the view
        # snaps toward a selection/ground hit that sits off to one side, which is
        # the "轴心不正常/摄像机跳变" jump this test guards against. Only the
        # *distance* to the pivot is selection/ground-aware; the direction never is.
        camera_js = (FRONTEND_ROOT / "gw_camera.js").read_text(encoding="utf-8")
        pivot_body = camera_js[
            camera_js.index("function getViewportPivot(event)"):
            camera_js.index("function beginViewportDrag")
        ]
        self.assertIn("camera.getWorldDirection(forward);", pivot_body)
        self.assertIn("var selectedFrame = getSelectedObjectFrame();", pivot_body)
        self.assertLess(
            pivot_body.index("var selectedFrame = getSelectedObjectFrame();"),
            pivot_body.index("screenToGround(event.clientX, event.clientY)")
        )
        self.assertIn("distance = camera.position.distanceTo(selectedFrame.center);", pivot_body)
        self.assertIn("if (point) distance = camera.position.distanceTo(point);", pivot_body)
        self.assertIn("THREE.MathUtils.clamp(distance, 1, 2000)", pivot_body)
        self.assertIn("return camera.position.clone().addScaledVector(forward, distance);", pivot_body)
        self.assertNotIn("if (selectedFrame) return selectedFrame.center;", pivot_body)
        self.assertNotIn("if (point) return point;", pivot_body)

    def test_game_frame_selected_uses_any_selected_scene_object(self):
        game_js = (FRONTEND_ROOT / "game_workbench.js").read_text(encoding="utf-8")
        self.assertIn("function getSelectedObjectFrame()", game_js)
        self.assertIn("function focusSelectedObject", game_js)
        frame_body = game_js[
            game_js.index("function getSelectedObjectFrame()"):
            game_js.index("function focusSelectedObject")
        ]
        focus_body = game_js[
            game_js.index("function focusSelectedObject()"):
            game_js.index("function getPlayableCharacter")
        ]
        shortcut_start = game_js.index("function handleGameShortcut(event)")
        shortcut_body = game_js[
            shortcut_start:
            game_js.index("function handleKeyUp", shortcut_start)
        ]
        self.assertIn("if (!selectedObject) return null;", frame_body)
        self.assertIn("new THREE.Box3().setFromObject(selectedObject)", frame_body)
        self.assertIn("var radius = 0.5 * size.length();", frame_body)
        self.assertIn("camera.fov", frame_body)
        self.assertIn("var frame = getSelectedObjectFrame();", focus_body)
        self.assertIn("camera.position.copy(frame.center).addScaledVector(frame.direction, frame.distance);", focus_body)
        self.assertIn("code === 'keyf' && focusSelectedObject()", shortcut_body)
        self.assertNotIn("focusSelectedCharacter", game_js)

    def test_map_controls_are_repositioned(self):
        self.assertIn('#map-shell #selection-tools {', _PICKER_FRONTEND)
        basemap_style = _PICKER_STYLES.split("#map-shell #basemap-control", 1)[1].split("}", 1)[0]
        view_toggle_style = _PICKER_STYLES.split("#map-shell #view-toggle", 1)[1].split("}", 1)[0]

        self.assertIn("left: auto;", basemap_style)
        self.assertIn("right: 14px;", basemap_style)
        self.assertIn("top: auto;", basemap_style)
        self.assertIn("bottom: 58px;", basemap_style)
        self.assertIn("right: 14px;", view_toggle_style)
        self.assertIn("bottom: 14px;", view_toggle_style)

    def test_basemap_and_view_controls_are_single_click_toggles(self):
        selection_js = (FRONTEND_ROOT / "selection_search.js").read_text(encoding="utf-8")
        self.assertIn('id="basemap-toggle"', _PICKER_INDEX_HTML)
        self.assertNotIn('id="basemap-segment"', _PICKER_INDEX_HTML)
        self.assertIn("function toggleBasemapStyle()", selection_js)
        self.assertIn("setBasemapStyle(next.id);", selection_js)
        self.assertNotIn("seg.querySelectorAll('.segmented-option')", _PICKER_APP_JS)
        self.assertNotIn("var thumb = document.createElement('span');", selection_js)

        self.assertIn('id="view-toggle-button"', _PICKER_INDEX_HTML)
        self.assertNotIn('class="map-tool-button flat-item view-toggle-2d active"', _PICKER_INDEX_HTML)
        self.assertNotIn('class="map-tool-button flat-item view-toggle-3d"', _PICKER_INDEX_HTML)
        self.assertIn("var toggle = document.querySelector('#view-toggle .view-toggle-button');", _PICKER_APP_JS)
        self.assertIn("if (cameraController.isFlatView()) cameraController.enter3DInPlace();", _PICKER_APP_JS)
        self.assertIn("else cameraController.exitTo2D();", _PICKER_APP_JS)

    def test_grid_tools_are_houdini_only(self):
        self.assertIn('#workspace:not([data-workspace-kind="houdini"]) #selection-tools', _PICKER_FRONTEND)
        self.assertIn("if (activeWorkspaceId !== 'houdini') return;", _PICKER_APP_JS)
        self.assertIn('setGridVisible(true);', _PICKER_APP_JS)
        self.assertIn('setGridVisible(false);', _PICKER_APP_JS)
        self.assertIn('setPointSelectActive(false);', _PICKER_APP_JS)

    def test_workspace_menu_order_and_default_page(self):
        menu_section = _PICKER_INDEX_HTML.split('id="tool-placeholder-section"', 1)[1].split('</section>', 1)[0]
        self.assertIn('class="tool-placeholder-stack"', menu_section)
        self.assertIn('class="tool-placeholder-list tool-placeholder-list--world flat-panel flat-panel--col"', menu_section)
        self.assertIn('class="tool-placeholder-list tool-placeholder-list--workbench flat-panel flat-panel--col"', menu_section)
        world_group = menu_section.split('tool-placeholder-list--world', 1)[1].split('</div>', 1)[0]
        workbench_group = menu_section.split('tool-placeholder-list--workbench', 1)[1]
        self.assertIn('title="切换到 EOL">EOL', world_group)
        self.assertIn('title="切换到 ZONE">ZONE', world_group)
        self.assertNotIn('title="切换到编辑器">编辑器', world_group)
        self.assertIn('title="切换到编辑器">编辑器', workbench_group)
        self.assertIn('title="切换到 Houdini 工作台">Houdini', workbench_group)
        self.assertIn('DCCbridge', workbench_group)
        self.assertLess(menu_section.index('tool-placeholder-list--world'), menu_section.index('tool-placeholder-list--workbench'))
        self.assertIn(".tool-placeholder-stack {\n  display: flex;", _PICKER_STYLES)
        self.assertIn("gap: 10px;", _PICKER_STYLES.split(".tool-placeholder-stack", 1)[1].split("}", 1)[0])

        menu_labels = [
            'data-workspace-target="news" aria-pressed="true" title="切换到 EOL">EOL',
            'data-workspace-target="city-preview" aria-pressed="false" title="切换到 ZONE">ZONE',
            'data-workspace-target="game" aria-pressed="false" title="切换到编辑器">编辑器',
            'data-workspace-target="houdini" aria-pressed="false" title="切换到 Houdini 工作台">Houdini',
            "DCCbridge",
        ]
        positions = [_PICKER_INDEX_HTML.index(label) for label in menu_labels]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('id="workspace" data-workspace-kind="earth" data-action-panel-collapsed="false"', _PICKER_INDEX_HTML)
        self.assertIn('data-workspace-target="news" aria-pressed="true"', _PICKER_INDEX_HTML)
        self.assertIn('id="action-panel" aria-label="执行操作面板"', _PICKER_INDEX_HTML)
        self.assertNotIn('id="action-panel" aria-label="执行操作面板" hidden', _PICKER_INDEX_HTML)
        self.assertIn('var activeWorkspaceId = \'news\';', _PICKER_APP_JS)
        self.assertIn('var actionPanelCollapsed = false;', _PICKER_APP_JS)

    def test_dccbridge_controls_are_clickable(self):
        self.assertIn('class="dcc-toggle" aria-pressed="false" aria-label="打开 Houdini"', _PICKER_INDEX_HTML)
        self.assertIn('class="dcc-install-btn" aria-pressed="false">安装</button>', _PICKER_INDEX_HTML)
        self.assertNotIn('class="dcc-install-btn" disabled', _PICKER_INDEX_HTML)
        self.assertIn("function bindDccBridgeControls", _PICKER_APP_JS)
        self.assertIn("install.textContent = installed ? '已安装' : '安装';", _PICKER_APP_JS)
        self.assertIn(".dcc-bridge-panel.flat-item:hover", _PICKER_FRONTEND)
        self.assertIn(".dcc-bridge-summary.active", _PICKER_FRONTEND)
        self.assertIn("updateWorkspaceButtons('');", _PICKER_APP_JS)
        self.assertIn("summary.classList.add('active');", _PICKER_APP_JS)
        self.assertIn("bridge.open && !bridge.contains(event.target)", _PICKER_APP_JS)
        self.assertIn("min-width: 36px;", _PICKER_FRONTEND)
        self.assertIn(".dcc-option-row.is-enabled .dcc-name", _PICKER_FRONTEND)
        self.assertIn("function openDccSoftware", _PICKER_APP_JS)
        self.assertIn("fetch('/open-software'", _PICKER_APP_JS)
        self.assertIn("function closeDccSoftware", _PICKER_APP_JS)
        self.assertIn("fetch('/close-software'", _PICKER_APP_JS)
        self.assertIn("if (toggle.classList.contains('is-on')) closeDccSoftware(row, toggle);", _PICKER_APP_JS)
        self.assertIn("function setDccSoftwareSwitch", _PICKER_APP_JS)
        self.assertIn("if (available) setDccSoftwareSwitch('houdini', true);", _PICKER_APP_JS)
        self.assertIn("setDccSoftwareSwitch(softwareId, ok);", _PICKER_APP_JS)
        self.assertIn("function saveDccSoftwarePath", _PICKER_APP_JS)
        self.assertIn("function updateDccSoftwarePaths", _PICKER_APP_JS)
        for label in ("Houdini", "Blender", "Unity", "Unreal", "Godot"):
            self.assertIn(label, _PICKER_INDEX_HTML)
        for removed in ("3ds Max", "Maya", "Cocos", "ZBrush"):
            self.assertNotIn(removed, _PICKER_INDEX_HTML)
        self.assertIn('data-dcc-id="houdini"', _PICKER_INDEX_HTML)
        self.assertIn('class="dcc-path-btn" aria-expanded="false" title="设置 Houdini 本地路径"', _PICKER_INDEX_HTML)
        self.assertIn('class="dcc-path-icon"', _PICKER_INDEX_HTML)
        self.assertIn('/area-picker/icons/lucide-folder.svg', _PICKER_STYLES)
        self.assertIn('/area-picker/icons/bootstrap-folder-fill.svg', _PICKER_STYLES)
        self.assertIn("clip-path: inset(0 100% 0 0);", _PICKER_STYLES)
        self.assertIn(".dcc-option-row.has-path .dcc-path-icon::after", _PICKER_STYLES)
        self.assertTrue((FRONTEND_ROOT / "icons" / "lucide-folder.svg").exists())
        self.assertTrue((FRONTEND_ROOT / "icons" / "bootstrap-folder-fill.svg").exists())
        self.assertTrue((FRONTEND_ROOT / "icons" / "LUCIDE_LICENSE.txt").exists())
        self.assertTrue((FRONTEND_ROOT / "icons" / "BOOTSTRAP_ICONS_LICENSE.txt").exists())
        self.assertIn('class="dcc-path-input" type="text"', _PICKER_INDEX_HTML)
        self.assertIn("<title>WorldBuilder", _PICKER_INDEX_HTML)
        self.assertIn("dccPathCachePrefix = 'worldbuilder.dcc.path.'", _PICKER_APP_JS)
        self.assertIn("legacyDccPathCachePrefix = 'virtualcity.dcc.path.'", _PICKER_APP_JS)
        self.assertIn("function dccPathStorageKey", _PICKER_APP_JS)
        self.assertIn("function clearDccPathCache", _PICKER_APP_JS)
        self.assertIn("localStorage.setItem(dccPathStorageKey(row), value);", _PICKER_APP_JS)
        self.assertIn("localStorage.removeItem(key);", _PICKER_APP_JS)
        self.assertIn("paths[key] || getCachedDccPath(row)", _PICKER_APP_JS)
        self.assertIn("function saveAndCloseDccPathEditor", _PICKER_APP_JS)
        self.assertIn("event.key !== 'Enter'", _PICKER_APP_JS)
        self.assertIn("document.addEventListener('pointerdown'", _PICKER_APP_JS)
        self.assertIn("row.classList.toggle('has-path', !!value);", _PICKER_APP_JS)
        self.assertIn("panel.addEventListener('input'", _PICKER_APP_JS)
        self.assertIn("row.classList.toggle('has-path', !!input.value.trim());", _PICKER_APP_JS)
        self.assertIn("if (d.ok) row.classList.toggle('has-path', !!input.value.trim());", _PICKER_APP_JS)
        server_source = Path(area_picker.__file__).read_text(encoding="utf-8")
        self.assertIn("def _post_open_software", server_source)
        self.assertIn("parsed.path == '/open-software'", server_source)
        self.assertIn("def _post_close_software", server_source)
        self.assertIn("parsed.path == '/close-software'", server_source)

    def test_dccbridge_software_directory_resolves_to_exe(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blender = root / "blender.exe"
            blender.write_text("", encoding="utf-8")
            self.assertEqual(area_picker._resolve_software_launch_path("blender", str(root)), blender)

    def test_dccbridge_close_software_uses_process_name(self):
        fake_run = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch.object(area_picker.os, "name", "nt"), \
                patch.object(area_picker, "_software_path_status", return_value={"blender_exe": "C:/missing/blender.exe"}), \
                patch.object(area_picker.subprocess, "run", return_value=fake_run) as run:
            payload = area_picker._close_software_from_config("blender")
        self.assertTrue(payload["ok"])
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[:3], ["powershell", "-NoProfile", "-Command"])
        self.assertIn("Get-Process -Name 'blender'", cmd[3])

    def test_scene_root_path_is_persisted_with_software_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config_path = root / "software_paths.json"
            scene_root = root / "Scenes"
            with patch.object(software_paths, "SOFTWARE_PATHS_FILE", config_path):
                status = software_paths.write_scene_root(str(scene_root))
                saved = json.loads(config_path.read_text(encoding="utf-8"))
                created = scene_root.is_dir()
        self.assertEqual(status["scene_root"], str(scene_root))
        self.assertTrue(status["scene_root_exists"])
        self.assertTrue(created)
        self.assertEqual(saved["scene_root"], str(scene_root))

    def test_open_scene_root_from_config_requires_existing_root(self):
        with patch.object(area_picker, "_scene_root_status", return_value={"scene_root": "", "scene_root_exists": False}):
            missing_payload = area_picker._open_scene_root_from_config()
        self.assertFalse(missing_payload["ok"])
        self.assertIn("请先设置场景工程根目录", missing_payload["message"])

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch.object(area_picker, "_scene_root_status", return_value={"scene_root": str(root), "scene_root_exists": True}), \
                    patch.object(area_picker, "_open_local_directory") as open_dir:
                payload = area_picker._open_scene_root_from_config()
        self.assertTrue(payload["ok"])
        open_dir.assert_called_once_with(root)

    def test_restart_clears_dcc_path_cache(self):
        data = {
            "houdini_exe": "C:/Houdini/houdini.exe",
            "blender_exe": "C:/Blender/blender.exe",
            "unity_exe": "C:/Unity/Unity.exe",
            "unreal_exe": "C:/Unreal/UnrealEditor.exe",
            "godot_exe": "C:/Godot/Godot.exe",
            "unrelated": "keep",
        }
        with patch.object(area_picker, "_read_software_paths", return_value=dict(data)), \
                patch.object(area_picker, "_write_software_paths") as write_paths:
            area_picker._clear_dcc_path_cache()
        write_paths.assert_called_once_with({"unrelated": "keep"})

    def test_houdini_status_lives_in_action_panel(self):
        self.assertIn('id="houdini-badge"', _PICKER_FRONTEND)
        self.assertIn('id="houdini-connection-value"', _PICKER_FRONTEND)
        self.assertIn('id="houdini-asset-value"', _PICKER_FRONTEND)
        self.assertIn('id="houdini-export-value"', _PICKER_FRONTEND)
        self.assertIn("function updateHoudiniStatusPanel", _PICKER_FRONTEND)


class TestDataSourcesStatus(unittest.TestCase):
    def test_downloaded_area_status_counts_complete_directory_areas(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "RawData"
            (raw / "_downloads" / "area_snapshot").mkdir(parents=True)
            (raw / "_downloads" / "area_snapshot" / "roads.osm").write_text("<osm/>", encoding="utf-8")
            (raw / "_downloads" / "area_snapshot" / "buildings.geojson").write_text("{}", encoding="utf-8")
            (raw / "_downloads" / "area_snapshot" / "dem.csv").write_text("x,y,z\n", encoding="utf-8")
            (raw / "_downloads" / "area_incomplete").mkdir()
            (raw / "_downloads" / "area_incomplete" / "roads.osm").write_text("<osm/>", encoding="utf-8")

            (raw / "OSM").mkdir()
            (raw / "Overture").mkdir()
            (raw / "DEM").mkdir()
            (raw / "OSM" / "area_raw_osm_v001.osm").write_text("<osm/>", encoding="utf-8")
            (raw / "Overture" / "area_raw_buildings_overture_v001.geojson").write_text("{}", encoding="utf-8")
            (raw / "DEM" / "area_raw_dem_v001.csv").write_text("x,y,z\n", encoding="utf-8")
            (raw / "OSM" / "area_snapshot_osm_v001.osm").write_text("<osm/>", encoding="utf-8")
            (raw / "Overture" / "area_snapshot_buildings_overture_v001.geojson").write_text("{}", encoding="utf-8")
            (raw / "DEM" / "area_snapshot_dem_v001.csv").write_text("x,y,z\n", encoding="utf-8")

            with patch.object(area_picker, "ROOT", root):
                payload = area_picker._downloaded_area_status()

        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["area_ids"], ["area_raw", "area_snapshot"])
        # 无 macro-tile 下载时，quick_jumps 仅含 9 个预置城市书签，tile 数均为 0。
        self.assertEqual(len(payload["quick_jumps"]), len(area_picker.PRESET_CITY_JUMPS))
        self.assertTrue(all(j["source"] == "preset_city" for j in payload["quick_jumps"]))
        self.assertTrue(all(j["tile_count"] == 0 for j in payload["quick_jumps"]))
        self.assertTrue(all(j["jumpable"] and len(j["bbox"]) == 4 for j in payload["quick_jumps"]))

    def test_downloaded_area_status_builds_macro_tile_quick_jumps(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tiles = root / "RawData" / "_tiles"
            tiles.mkdir(parents=True)
            (tiles / "pattaya_dem.tif").write_bytes(b"tif")
            (tiles / "pattaya_osm.osm").write_text("<osm/>", encoding="utf-8")
            (tiles / "pattaya_bld.geojson").write_text("{}", encoding="utf-8")
            (tiles / "_index.json").write_text(json.dumps({
                "pattaya": {
                    "bbox": [100.84, 12.89, 100.92, 12.97],
                    "dem_tif": "F:\\VirtualCity\\RawData\\_tiles\\pattaya_dem.tif",
                    "osm_xml": "F:\\VirtualCity\\RawData\\_tiles\\pattaya_osm.osm",
                    "bld_geojson": "F:\\VirtualCity\\RawData\\_tiles\\pattaya_bld.geojson",
                }
            }), encoding="utf-8")

            with patch.object(area_picker, "ROOT", root):
                payload = area_picker._downloaded_area_status()

        self.assertEqual(payload["count"], 0)
        # pattaya 中心不属于任何预置城市，作为孤儿排在 9 个预置城市之前。
        self.assertEqual(len(payload["quick_jumps"]), 1 + len(area_picker.PRESET_CITY_JUMPS))
        jump = payload["quick_jumps"][0]
        self.assertEqual(jump["id"], "pattaya")
        self.assertEqual(jump["label"], "Pattaya")
        # 无真实清单时，按 bbox 反推得到 10x10=100 个格子，聚合成一片。
        self.assertEqual(jump["tile_count"], 100)
        self.assertTrue(jump["jumpable"])
        self.assertEqual(jump["source"], "downloaded_area")

    def test_macro_tile_prefers_manifest_tile_count_over_bbox_reverse_calc(self):
        # 真实下载清单存在时，tile_count 取一手记录，不再用粗 bbox 反推（121 不再塌成 100）。
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tiles = root / "RawData" / "_tiles"
            tiles.mkdir(parents=True)
            (tiles / "pattaya_dem.tif").write_bytes(b"tif")
            (tiles / "pattaya_osm.osm").write_text("<osm/>", encoding="utf-8")
            (tiles / "pattaya_bld.geojson").write_text("{}", encoding="utf-8")
            (tiles / "_index.json").write_text(json.dumps({
                "pattaya": {
                    "bbox": [100.84, 12.89, 100.92, 12.97],
                    "dem_tif": str(tiles / "pattaya_dem.tif"),
                    "osm_xml": str(tiles / "pattaya_osm.osm"),
                    "bld_geojson": str(tiles / "pattaya_bld.geojson"),
                }
            }), encoding="utf-8")
            areas = root / "RawData" / "_areas"
            areas.mkdir(parents=True)
            (areas / "pattaya.json").write_text(json.dumps({
                "area_id": "pattaya",
                "tile_count": 121,
                "tile_ids": [f"z47n_e{700000 + i * 1000}_n1429000_s1000" for i in range(121)],
                "bbox": [100.84, 12.89, 100.92, 12.97],
            }), encoding="utf-8")

            with patch.object(area_picker, "ROOT", root):
                payload = area_picker._downloaded_area_status()

        jump = payload["quick_jumps"][0]
        self.assertEqual(jump["id"], "pattaya")
        self.assertEqual(jump["tile_count"], 121)
        self.assertEqual(jump["source"], "downloaded_area")

    def test_downloaded_area_manifest_without_index_entry_appears_as_jump(self):
        # 真实下载（selection_id 命名）未进 _index.json 时，仍凭清单出现在跳转列表。
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            areas = root / "RawData" / "_areas"
            areas.mkdir(parents=True)
            sel_id = "z47n_e700000_n1429000_w11000_h11000_s1000"
            (areas / f"{sel_id}.json").write_text(json.dumps({
                "area_id": sel_id,
                "tile_count": 121,
                "tile_ids": [f"z47n_e{700000 + i * 1000}_n1429000_s1000" for i in range(121)],
                "bbox": [100.84, 12.89, 100.92, 12.97],
            }), encoding="utf-8")

            with patch.object(area_picker, "ROOT", root):
                payload = area_picker._downloaded_area_status()

        orphans = [j for j in payload["quick_jumps"] if j["source"] == "downloaded_area"]
        self.assertEqual(len(orphans), 1)
        self.assertEqual(orphans[0]["id"], sel_id)
        self.assertEqual(orphans[0]["tile_count"], 121)
        # bbox 现在是真实格子的几何外包，而非清单里的粗 bbox。
        self.assertEqual(len(orphans[0]["bbox"]), 4)
        west, south, east, north = orphans[0]["bbox"]
        self.assertLess(west, east)
        self.assertLess(south, north)

    def test_downloaded_area_inside_preset_city_folds_into_bookmark(self):
        # 已下载区域中心落在 Tokyo bbox 内：不另列孤儿，tile 数折叠进 Tokyo 书签。
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tiles = root / "RawData" / "_tiles"
            tiles.mkdir(parents=True)
            (tiles / "tk_dem.tif").write_bytes(b"tif")
            (tiles / "tk_osm.osm").write_text("<osm/>", encoding="utf-8")
            (tiles / "tk_bld.geojson").write_text("{}", encoding="utf-8")
            (tiles / "_index.json").write_text(json.dumps({
                "tokyo_shinjuku": {
                    "bbox": [139.69, 35.68, 139.71, 35.70],
                    "dem_tif": str(tiles / "tk_dem.tif"),
                    "osm_xml": str(tiles / "tk_osm.osm"),
                    "bld_geojson": str(tiles / "tk_bld.geojson"),
                }
            }), encoding="utf-8")

            with patch.object(area_picker, "ROOT", root):
                payload = area_picker._downloaded_area_status()

        jumps = payload["quick_jumps"]
        self.assertEqual(len(jumps), len(area_picker.PRESET_CITY_JUMPS))
        self.assertTrue(all(j["source"] == "preset_city" for j in jumps))
        tokyo = next(j for j in jumps if j["id"] == "tokyo")
        self.assertGreater(tokyo["tile_count"], 0)


        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg_dir = root / "Config"
            cfg_dir.mkdir()
            (root / "RawData" / "OSM").mkdir(parents=True)
            (root / "RawData" / "Overture").mkdir(parents=True)
            (root / "RawData" / "DEM").mkdir(parents=True)
            (root / "RawData" / "OSM" / "area_osm.osm").write_text("<osm></osm>", encoding="utf-8")
            (root / "RawData" / "Overture" / "area_buildings.geojson").write_text(
                '{"type":"FeatureCollection","features":[]}', encoding="utf-8")
            (root / "RawData" / "DEM" / "area_dem.csv").write_text("x,y,z\n0,0,0\n", encoding="utf-8")
            (cfg_dir / "active_area.json").write_text(json.dumps({
                "area_id": "area_test",
                "osm_file": "RawData/OSM/area_osm.osm",
                "buildings_file": "RawData/Overture/area_buildings.geojson",
                "dem_csv": "RawData/DEM/area_dem.csv",
                "dem_source": "fabdem",
                "sources": {
                    "roads": "tile_cache_osm_else_overpass_v1",
                    "buildings": "tile_cache_overture_else_overture_api_v1",
                    "dem": "fabdem_else_tile_cache_else_nasadem_v1",
                },
                "cache": {
                    "clip": {"status": "hit", "key": "bbox_test"}
                },
            }), encoding="utf-8")

            with patch.object(area_picker, "ROOT", root):
                payload = area_picker._data_sources_status()

        self.assertTrue(payload["available"])
        self.assertEqual(payload["area_id"], "area_test")
        self.assertEqual([item["key"] for item in payload["items"]], ["roads", "buildings", "terrain"])
        self.assertTrue(all(item["file"]["exists"] for item in payload["items"]))
        self.assertIn("OpenStreetMap", payload["items"][0]["provider"])
        self.assertIn("Overture", payload["items"][1]["provider"])
        self.assertIn("FABDEM", payload["items"][2]["provider"])
        self.assertIn("clip cache hit", payload["items"][0]["current"])
        self.assertIn("Overpass API", payload["items"][0]["strategy_label"])
        self.assertIn("Google 高度补全", payload["items"][1]["strategy_label"])
        self.assertIn("NASADEM 兜底", payload["items"][2]["strategy_label"])

class TestSelectionMemory(unittest.TestCase):
    def tearDown(self):
        area_picker._clear_remembered_selection()

    def test_selection_memory_round_trips_tile_ids(self):
        payload = area_picker._remember_selection([
            "z47n_e704000_n1429000_s1000",
            "z47n_e705000_n1429000_s1000",
        ])
        self.assertTrue(payload["available"])
        self.assertEqual(payload["selection_id"], "z47n_e704000_n1429000_w2000_h1000_s1000")
        self.assertEqual(payload["tile_count"], 2)

        status = area_picker._remembered_selection_status()
        self.assertTrue(status["available"])
        self.assertEqual(status["tile_ids"], payload["tile_ids"])
        self.assertGreater(status["updated_at"], 0)

        area_picker._clear_remembered_selection()
        self.assertFalse(area_picker._remembered_selection_status()["available"])


class TestRootLauncher(unittest.TestCase):
    def test_root_launcher_starts_native_desktop_window(self):
        launcher = ROOT / "启动WorldBuilder.cmd"
        self.assertTrue(launcher.exists())
        source = launcher.read_text(encoding="utf-8")
        self.assertIn("launch_worldbuilder_console.ps1", source)

        launch_script = ROOT / "Scripts" / "launch_worldbuilder_console.ps1"
        self.assertTrue(launch_script.exists())
        launch_source = launch_script.read_text(encoding="utf-8")
        # 桌面外壳模型：启动器跑 desktop.py（pywebview 原生窗口 + 同进程内嵌服务），
        # 不再开浏览器，也不再依赖网页心跳自杀（SHUTDOWN_WITH_PAGE）。
        self.assertIn("desktop.py", launch_source)
        self.assertNotIn("VC_AREA_PICKER_SHUTDOWN_WITH_PAGE", launch_source)
        self.assertNotIn("url.dll,FileProtocolHandler", launch_source)
        self.assertIn("Test-AreaPickerReady", launch_source)

        desktop = ROOT / "Scripts" / "desktop.py"
        self.assertTrue(desktop.exists())
        desktop_source = desktop.read_text(encoding="utf-8")
        self.assertIn("import webview", desktop_source)
        self.assertIn("VC_AREA_PICKER_NO_BROWSER", desktop_source)

    def test_root_reset_shortcut_uses_reset_script(self):
        shortcut = ROOT / "重置WorldBuilder服务.cmd"
        self.assertTrue(shortcut.exists())
        source = shortcut.read_text(encoding="utf-8")
        self.assertIn("reset_worldbuilder_servers.ps1", source)
        self.assertNotIn("-StopUnknownPortOwners", source)


class TestFrontendAssetVersion(unittest.TestCase):
    def test_version_changes_when_asset_content_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            static_root = root / "_static"
            static_root.mkdir(parents=True)
            for name in (
                "app.js",
                "workspace.js",
                "selection_search.js",
                "pipeline_status.js",
                "dcc_bridge.js",
                "gw_outliner.js",
                "game_workbench.js",
                "vc_glb.js",
                "render_profile.js",
                "viewport_grid.js",
                "houdini_preview.js",
                "scene_project.js",
                "scene_assets.js",
                "cloud_assets.js",
                "styles.css",
                "index.html",
            ):
                (root / name).write_text("v1", encoding="utf-8")
            with patch.object(area_picker, "FRONTEND_ROOT", root), patch.object(area_picker, "STATIC_ROOT", static_root):
                first = area_picker._frontend_asset_version()
                # 改动 app.js 内容（size 变化），版本串必须随之变化。
                (root / "app.js").write_text("v2-longer-content", encoding="utf-8")
                second = area_picker._frontend_asset_version()
                (root / "styles.css").write_text("v3-longer-styles-content", encoding="utf-8")
                third = area_picker._frontend_asset_version()
                (root / "houdini_preview.js").write_text("v4-preview-content", encoding="utf-8")
                fourth = area_picker._frontend_asset_version()
                (root / "viewport_grid.js").write_text("v5-grid-content", encoding="utf-8")
                fifth = area_picker._frontend_asset_version()
                (root / "render_profile.js").write_text("v6-render-profile-content", encoding="utf-8")
                sixth = area_picker._frontend_asset_version()
        self.assertNotEqual(first, second)
        self.assertNotEqual(second, third)
        self.assertNotEqual(third, fourth)
        self.assertNotEqual(fourth, fifth)
        self.assertNotEqual(fifth, sixth)

    def test_version_is_stable_without_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            static_root = root / "_static"
            static_root.mkdir(parents=True)
            for name in (
                "app.js",
                "workspace.js",
                "selection_search.js",
                "pipeline_status.js",
                "dcc_bridge.js",
                "gw_outliner.js",
                "game_workbench.js",
                "vc_glb.js",
                "render_profile.js",
                "viewport_grid.js",
                "houdini_preview.js",
                "scene_project.js",
                "scene_assets.js",
                "cloud_assets.js",
                "styles.css",
                "index.html",
            ):
                (root / name).write_text("same", encoding="utf-8")
            with patch.object(area_picker, "FRONTEND_ROOT", root), patch.object(area_picker, "STATIC_ROOT", static_root):
                self.assertEqual(
                    area_picker._frontend_asset_version(),
                    area_picker._frontend_asset_version(),
                )

    def test_version_does_not_raise_on_missing_assets(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(area_picker, "FRONTEND_ROOT", Path(td)), patch.object(area_picker, "STATIC_ROOT", Path(td) / "_static"):
                self.assertIsInstance(area_picker._frontend_asset_version(), str)


class TestHoudiniStatus(unittest.TestCase):
    def test_build_status_records_whitebox_artifact_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            whitebox = root / "Houdini" / "Export" / "whitebox_v001.glb"
            whitebox.parent.mkdir(parents=True)
            whitebox.write_bytes(b"glb-data")
            with patch.object(houdini_status_writer, "ROOT", root):
                houdini_status_writer.write_build_status(
                    "area_test",
                    "completed",
                    root / "Houdini" / "Hip" / "area.hip",
                    "done",
                    "pass",
                    "Reports/model_qa/area_test.json",
                    "run_test",
                    whitebox_path=whitebox,
                )

            payload = json.loads((root / "Config" / "houdini_build_status.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["whitebox_path"], "Houdini/Export/whitebox_v001.glb")

    def test_run_terminal_confirms_completed_for_matching_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = root / "Reports" / "pipeline_runs"
            run_dir.mkdir(parents=True)
            (run_dir / "run_new.json").write_text(json.dumps({
                "run_id": "run_new",
                "area_id": "area_test",
                "status": "completed",
                "phase": "pipeline_completed",
                "events": [{"status": "completed", "phase": "pipeline_completed", "message": "done"}],
            }), encoding="utf-8")
            with patch.object(area_picker, "ROOT", root):
                done, ok, status, message = area_picker._read_run_terminal("run_new")
                self.assertTrue(done)
                self.assertTrue(ok)
                self.assertEqual(status, "completed")
                self.assertEqual(message, "done")

    def test_run_terminal_reports_failed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = root / "Reports" / "pipeline_runs"
            run_dir.mkdir(parents=True)
            (run_dir / "run_new.json").write_text(json.dumps({
                "run_id": "run_new",
                "area_id": "area_test",
                "status": "failed",
                "phase": "houdini_recook",
                "events": [{"status": "failed", "phase": "houdini_recook", "message": "QA failed"}],
            }), encoding="utf-8")
            with patch.object(area_picker, "ROOT", root):
                done, ok, status, message = area_picker._read_run_terminal("run_new")
                self.assertTrue(done)
                self.assertFalse(ok)
                self.assertEqual(status, "failed")

    def test_run_terminal_not_done_while_running(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = root / "Reports" / "pipeline_runs"
            run_dir.mkdir(parents=True)
            (run_dir / "run_new.json").write_text(json.dumps({
                "run_id": "run_new",
                "area_id": "area_test",
                "status": "running",
                "phase": "houdini_recook",
                "events": [],
            }), encoding="utf-8")
            with patch.object(area_picker, "ROOT", root):
                done, ok, _status, _message = area_picker._read_run_terminal("run_new")
                self.assertFalse(done)
                self.assertFalse(ok)

    def test_run_terminal_missing_record_is_not_done(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "Reports" / "pipeline_runs").mkdir(parents=True)
            with patch.object(area_picker, "ROOT", root):
                done, ok, _status, _message = area_picker._read_run_terminal("run_absent")
                self.assertFalse(done)
                self.assertFalse(ok)

    def test_failure_summary_extracts_model_qa_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "Config"
            qa_dir = root / "Reports" / "model_qa"
            run_dir = root / "Reports" / "pipeline_runs"
            cfg.mkdir(parents=True)
            qa_dir.mkdir(parents=True)
            run_dir.mkdir(parents=True)
            report = qa_dir / "area_test_quick.json"
            report.write_text(json.dumps({
                "status": "fail",
                "summary": {"pass": 1, "warn": 1, "fail": 1},
                "checks": [
                    {"name": "required_nodes", "status": "pass", "message": "ok"},
                    {
                        "name": "road_clipped_faces",
                        "status": "fail",
                        "message": "road_clipped geometry has invalid faces",
                        "details": {
                            "self_intersection_count": 954,
                            "self_intersecting_prim_count": 475,
                            "max_vertices": 210,
                        },
                    },
                    {
                        "name": "road_terrain_fit",
                        "status": "warn",
                        "message": "road_clipped has many terrain ray misses",
                        "details": {"misses": 1200, "sampled_points": 2934},
                    },
                ],
            }), encoding="utf-8")
            (cfg / "active_area.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
            }), encoding="utf-8")
            (cfg / "houdini_build_status.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "failed",
                "message": "model QA failed (see Reports/model_qa/area_test_quick.json)",
                "qa_status": "fail",
                "qa_report": "Reports/model_qa/area_test_quick.json",
            }), encoding="utf-8")
            (run_dir / "run_test.json").write_text(json.dumps({
                "run_id": "run_test",
                "area_id": "area_test",
                "status": "failed",
                "phase": "houdini_recook",
                "events": [
                    {"status": "failed", "phase": "houdini_recook", "message": "model QA failed"}
                ],
            }), encoding="utf-8")

            with patch.object(area_picker, "ROOT", root):
                summary = area_picker._failure_summary({
                    "done": True,
                    "ok": False,
                    "name": "area_test",
                    "run_id": "run_test",
                    "returncode": 1,
                })

        self.assertTrue(summary["available"])
        self.assertEqual(summary["stage"], "Houdini 7/7 Model QA")
        self.assertEqual(summary["check"], "road_clipped_faces")
        self.assertIn("invalid faces", summary["reason"])
        self.assertEqual(summary["report"], "Reports/model_qa/area_test_quick.json")
        self.assertIn("self intersections=954", summary["metrics_line"])
        self.assertEqual(summary["warnings"][0]["name"], "road_terrain_fit")

    def test_failure_summary_hides_while_pipeline_is_running(self):
        self.assertFalse(area_picker._failure_summary({"running": True})["available"])


class TestExportAvailability(unittest.TestCase):
    class _Geo:
        def __init__(self, points=10, prims=5):
            self._values = {"pointcount": points, "primitivecount": prims}

        def intrinsicValue(self, name):
            return self._values[name]

    class _Node:
        def __init__(self, *, visible=True, points=10, prims=5):
            self._visible = visible
            self._geo = TestExportAvailability._Geo(points, prims)

        def isDisplayFlagSet(self):
            return self._visible

        def geometry(self):
            return self._geo

    class _Conn:
        def __init__(self, node):
            self._config = {}
            self.modules = SimpleNamespace(hou=SimpleNamespace(node=lambda path: node))
            self.closed = False

        def close(self):
            self.closed = True

    def _probe_model(self, node):
        conn = self._Conn(node)
        fake_rpyc = SimpleNamespace(classic=SimpleNamespace(connect=lambda *args, **kwargs: conn))
        with patch.object(area_picker, "_probe_houdini", return_value=True), \
                patch.dict(sys.modules, {"rpyc": fake_rpyc}):
            result = area_picker._houdini_model_available({})
        self.assertTrue(conn.closed)
        return result

    def test_live_houdini_model_requires_visible_non_empty_out_city(self):
        self.assertTrue(self._probe_model(self._Node()))
        self.assertFalse(self._probe_model(self._Node(visible=False)))
        self.assertFalse(self._probe_model(self._Node(points=0)))
        self.assertFalse(self._probe_model(self._Node(prims=0)))
        self.assertFalse(self._probe_model(None))

    def test_houdini_asset_status_reports_export_readiness(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "Config"
            qa = root / "Reports" / "model_qa"
            cfg.mkdir()
            qa.mkdir(parents=True)
            (cfg / "active_area.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
            }), encoding="utf-8")
            (cfg / "houdini_build_status.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "completed",
                "qa_status": "pass",
                "qa_report": "Reports/model_qa/area_test_quick.json",
                "whitebox_path": "Houdini/Export/whitebox_v001.glb",
            }), encoding="utf-8")
            whitebox = root / "Houdini" / "Export" / "whitebox_v001.glb"
            whitebox.parent.mkdir(parents=True)
            whitebox.write_bytes(b"glb-data")
            (qa / "area_test_quick.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "pass",
            }), encoding="utf-8")
            with patch.object(area_picker, "ROOT", root), \
                    patch.object(area_picker, "_houdini_model_available", return_value=True):
                payload = area_picker._houdini_asset_status(True)
        self.assertTrue(payload["qa_ok"])
        self.assertTrue(payload["model_ready"])
        self.assertTrue(payload["export_ready"])
        self.assertTrue(payload["whitebox"]["available"])
        self.assertEqual(payload["whitebox"]["run_id"], "run_test")
        self.assertEqual(payload["whitebox"]["path"], "Houdini/Export/whitebox_v001.glb")
        self.assertIn("/whitebox.glb?", payload["whitebox"]["url"])

    def test_houdini_asset_status_reports_missing_whitebox_without_blocking_export(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "Config"
            qa = root / "Reports" / "model_qa"
            cfg.mkdir()
            qa.mkdir(parents=True)
            (cfg / "active_area.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
            }), encoding="utf-8")
            (cfg / "houdini_build_status.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "completed",
                "qa_status": "pass",
                "qa_report": "Reports/model_qa/area_test_quick.json",
                "whitebox_path": "Houdini/Export/missing.glb",
            }), encoding="utf-8")
            (qa / "area_test_quick.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "pass",
            }), encoding="utf-8")
            with patch.object(area_picker, "ROOT", root), \
                    patch.object(area_picker, "_houdini_model_available", return_value=True):
                payload = area_picker._houdini_asset_status(True)
        self.assertTrue(payload["export_ready"])
        self.assertFalse(payload["whitebox"]["available"])
        self.assertEqual(payload["whitebox"]["run_id"], "run_test")

    def test_export_requires_both_completed_qa_and_live_model(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "Config"
            qa = root / "Reports" / "model_qa"
            cfg.mkdir()
            qa.mkdir(parents=True)
            (cfg / "active_area.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
            }), encoding="utf-8")
            (cfg / "houdini_build_status.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "completed",
                "qa_status": "pass",
                "qa_report": "Reports/model_qa/area_test_quick.json",
            }), encoding="utf-8")
            (qa / "area_test_quick.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "pass",
            }), encoding="utf-8")
            with patch.object(area_picker, "ROOT", root), \
                    patch.object(area_picker, "_houdini_model_available", return_value=False):
                self.assertFalse(area_picker._export_available())
            (cfg / "houdini_build_status.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "failed",
                "qa_status": "fail",
                "qa_report": "Reports/model_qa/area_test_quick.json",
            }), encoding="utf-8")
            with patch.object(area_picker, "ROOT", root), \
                    patch.object(area_picker, "_houdini_model_available", return_value=True):
                self.assertFalse(area_picker._export_available())
            (cfg / "houdini_build_status.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "completed",
                "qa_status": "pass",
                "qa_report": "Reports/model_qa/area_test_quick.json",
            }), encoding="utf-8")
            with patch.object(area_picker, "ROOT", root), \
                    patch.object(area_picker, "_houdini_model_available", return_value=True):
                self.assertTrue(area_picker._export_available())

    def test_export_gate_blocks_stale_houdini_status(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "Config"
            cfg.mkdir()
            (cfg / "active_area.json").write_text(json.dumps({
                "area_id": "area_new",
                "run_id": "run_new",
            }), encoding="utf-8")
            (cfg / "houdini_build_status.json").write_text(json.dumps({
                "area_id": "area_old",
                "run_id": "run_old",
                "status": "completed",
            }), encoding="utf-8")
            gate = pipeline_status.export_gate(root, live_model_ready=True)
        self.assertFalse(gate["allowed"])
        self.assertIn("stale houdini status", gate["primary_reason"])

    def test_manual_review_required_gate_needs_same_run_approval(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "Config"
            qa = root / "Reports" / "model_qa"
            cfg.mkdir()
            qa.mkdir(parents=True)
            active = {
                "area_id": "area_test",
                "run_id": "run_test",
            }
            (cfg / "active_area.json").write_text(json.dumps(active), encoding="utf-8")
            (cfg / "houdini_build_status.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "completed",
                "qa_status": "warn",
                "qa_report": "Reports/model_qa/area_test_quick.json",
            }), encoding="utf-8")
            (qa / "area_test_quick.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "warn",
            }), encoding="utf-8")

            blocked = pipeline_status.export_gate(root, active, live_model_ready=True)
            manual_review.write_review("area_test", "run_old", root=root)
            still_blocked = pipeline_status.export_gate(root, active, live_model_ready=True)
            manual_review.write_review("area_test", "run_test", root=root)
            allowed = pipeline_status.export_gate(root, active, live_model_ready=True)

        self.assertFalse(blocked["allowed"])
        self.assertFalse(still_blocked["allowed"])
        self.assertTrue(allowed["allowed"])

    def test_export_gate_qa_fail_requires_review_not_hard_block(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "Config"
            qa = root / "Reports" / "model_qa"
            cfg.mkdir()
            qa.mkdir(parents=True)
            active = {
                "area_id": "area_test",
                "run_id": "run_test",
            }
            (cfg / "active_area.json").write_text(json.dumps(active), encoding="utf-8")
            (cfg / "houdini_build_status.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "completed",
                "qa_status": "fail",
                "qa_report": "Reports/model_qa/area_test_quick.json",
            }), encoding="utf-8")
            (qa / "area_test_quick.json").write_text(json.dumps({
                "area_id": "area_test",
                "run_id": "run_test",
                "status": "fail",
            }), encoding="utf-8")

            blocked = pipeline_status.export_gate(root, active, live_model_ready=True)
            manual_review.write_review("area_test", "run_test", root=root)
            allowed = pipeline_status.export_gate(root, active, live_model_ready=True)

        self.assertFalse(blocked["allowed"])
        self.assertTrue(blocked["requires_manual_review"])
        self.assertTrue(allowed["allowed"])
        previous = dict(area_picker._state)
        try:
            with area_picker._state_lock:
                area_picker._state["running"] = True
                area_picker._state["export_running"] = False
            with patch.object(area_picker, "_probe_houdini", return_value=True), \
                    patch.object(area_picker, "_export_available", side_effect=AssertionError("must not probe")):
                payload = area_picker._service_payload()
            self.assertFalse(payload["export_available"])
        finally:
            with area_picker._state_lock:
                area_picker._state.update(previous)


class TestSetAreaDataOnly(unittest.TestCase):
    def test_set_area_exposes_data_only_mode(self):
        source = (ROOT / "Scripts" / "acquisition" / "set_area.py").read_text(encoding="utf-8")
        self.assertIn("--data-only", source)
        self.assertIn("--acquire-only", source)
        self.assertIn("data_download_completed", source)
        self.assertIn("跳过 refine_data 与 Houdini 重算", source)

    def test_legacy_set_area_wrapper_points_to_acquisition_layer(self):
        source = (ROOT / "Scripts" / "set_area.py").read_text(encoding="utf-8")
        self.assertIn('SCRIPTS / "acquisition" / "set_area.py"', source)
        self.assertIn("runpy.run_path", source)

    def test_data_only_does_not_emit_houdini_completion_warning(self):
        source = (ROOT / "Scripts" / "app" / "area_picker" / "server.py").read_text(encoding="utf-8")
        self.assertIn("if ok and not houdini_done and not data_only:", source)

    def test_full_pipeline_uses_explicit_orchestrator(self):
        source = (ROOT / "Scripts" / "app" / "area_picker" / "server.py").read_text(encoding="utf-8")
        self.assertIn("orchestration/run_pipeline.py", source)
        self.assertIn("--tile-ids", source)
        self.assertIn("'acquisition/set_area.py', '--data-only'", source)

    def test_pipeline_command_builder_keeps_layered_entrypoints(self):
        selection = {
            "selection_id": "z47n_e704000_n1429000_w1000_h1000_s1000",
            "tile_ids": ["z47n_e704000_n1429000_s1000"],
            "bbox": [100.8802921, 12.9195947, 100.8895736, 12.9286991],
        }

        data_cmd = area_picker._pipeline_command_for_selection(selection, data_only=True)
        self.assertEqual(data_cmd[:6], ["uv", "run", "python", "-u", "acquisition/set_area.py", "--data-only"])
        self.assertNotIn("orchestration/run_pipeline.py", data_cmd)

        run_cmd = area_picker._pipeline_command_for_selection(selection, data_only=False)
        self.assertIn("orchestration/run_pipeline.py", run_cmd)
        self.assertIn("--tile-ids", run_cmd)
        self.assertIn("z47n_e704000_n1429000_s1000", run_cmd)

    def test_run_pipeline_orchestrator_exists(self):
        source = (ROOT / "Scripts" / "orchestration" / "run_pipeline.py").read_text(encoding="utf-8")
        self.assertIn("acquisition/set_area.py", source)
        self.assertIn("--acquire-only", source)
        self.assertIn("VC_PIPELINE_TILE_IDS", source)
        self.assertIn("cleaning/refine_data.py", source)
        self.assertIn("houdini_build/recook_new_area.py", source)


class TestServerStartup(unittest.TestCase):
    def test_current_server_is_reused(self):
        existing = {
            "server_version": area_picker.APP_VERSION,
            "pid": 123,
            "running": False,
            "run_id": "",
        }
        with patch.object(area_picker, "_probe_existing_server", return_value=existing), \
                patch.object(area_picker, "_open_browser") as open_browser:
            self.assertEqual(area_picker.main(), 0)
            open_browser.assert_called_once_with(f"http://{area_picker.PICKER_HOST}:{area_picker.PORT}")

    def test_legacy_server_is_rejected(self):
        existing = {
            "server_version": "",
            "legacy_server": True,
            "running": False,
            "run_id": "",
        }
        with patch.object(area_picker, "_probe_existing_server", return_value=existing), \
                patch.object(area_picker.urllib.request, "urlopen", side_effect=OSError("mocked shutdown request")), \
                patch.object(area_picker, "_open_browser") as open_browser:
            self.assertEqual(area_picker.main(), 2)
            open_browser.assert_not_called()


class TestPageShutdown(unittest.TestCase):
    def setUp(self):
        self._page_state = dict(area_picker._page_state)
        self._state = dict(area_picker._state)

    def tearDown(self):
        with area_picker._page_lock:
            area_picker._page_state.update(self._page_state)
        with area_picker._state_lock:
            area_picker._state.update(self._state)

    def test_page_shutdown_waits_for_close_grace(self):
        with area_picker._page_lock:
            area_picker._page_state.update({
                "seen": True,
                "last_seen": 10.0,
                "close_requested": True,
                "closed_at": 10.5,
            })
        with area_picker._state_lock:
            area_picker._state["running"] = False
            area_picker._state["export_running"] = False

        self.assertFalse(area_picker._page_shutdown_due(12.0, enabled=True))
        self.assertTrue(area_picker._page_shutdown_due(15.0, enabled=True))

    def test_page_shutdown_does_not_interrupt_running_pipeline(self):
        with area_picker._page_lock:
            area_picker._page_state.update({
                "seen": True,
                "last_seen": 10.0,
                "close_requested": True,
                "closed_at": 10.0,
            })
        with area_picker._state_lock:
            area_picker._state["running"] = True
            area_picker._state["export_running"] = False

        self.assertFalse(area_picker._page_shutdown_due(20.0, enabled=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
