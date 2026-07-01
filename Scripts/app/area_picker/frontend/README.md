# Area Picker Frontend

This folder contains the homepage UI for the WorldBuilder area picker.

- `index.html`: page structure and `window.VC_CONFIG` bootstrap values injected by the Python server.
- `styles.css`: visual design, layout, responsive rules, and animation polish.
- `app.js`: map setup, region navigation, and startup wiring.
- `workspace.js`: workspace switching, shell panel layout, refresh/restart controls, and account menu behavior.
- `selection_search.js`: grid loading, fixed-tile selection, persisted selection restore, and location search.
- `pipeline_status.js`: run/export buttons, status stream handling, progress UI, logs, and data-source rendering.
- `dcc_bridge.js`: DCC software paths, Houdini launch/probe state, and DCCbridge controls.
- `scene_project.js`: editor left action buttons (新建/打开/保存/打开目录/设置), scene root dialog, scene project root create/open/save wiring, and a client-side localStorage project registry (name + recency) that backs the "打开工程" recent-projects picker.
- `scene_assets.js`: editor bottom project asset browser backed by the current scene root.
- `gw_core.js`: `window.VC_GW` namespace, shared editor-state container (`VC_GW.state`), and base helpers (`safeThree`, `setStatus`). Loads before the other `gw_*` modules.
- `gw_history.js`: generic undo/redo command stack (`createHistory`). game_workbench.js builds the `{ undo, redo }` closures per edit and pushes them here.
- `gw_scene_state.js`: owns the characters/sceneModels/whiteboxLayers arrays (`createSceneState`) — scene.add/remove wiring, pickable + outline list derivation, and localStorage-shaped serialization.
- `gw_scene_persistence.js`: scene-root scoped localStorage persistence, debounced saves, and restore orchestration. It reads/writes snapshots; game_workbench.js still constructs objects during restore.
- `gw_commands.js`: reversible scene edit command factories for create/delete/transform. `gw_history.js` owns the stack; this file owns command semantics.
- `gw_character.js`: procedural stylized avatar (geometry, toon material, outline shader) and its walk/idle motion rig. Pure factories.
- `gw_play.js`: third-person play controller (pointer-lock look, WASD movement, follow camera).
- `gw_camera.js`: editor viewport camera controller (alt-orbit/track/dolly, right-drag look + WASDQE fly, wheel zoom, flight speed). Factory takes a ctx of host references/callbacks.
- `gw_assets.js`: whitebox GLB import — pure `registerWhiteboxLayers`/`fitSunShadow` plus a ctx-injected load orchestrator (`createAssetLoader`).
- `gw_outliner.js`: scene outline row/table rendering and active selection row synchronization.
- `gw_inspector.js`: the "细节" tab's numeric position/rotation/scale panel and rename field (`createInspector`). Reads/writes the selected object directly; commits through the same command history as the gizmo.
- `game_workbench.js`: Three.js virtual asset workbench host — scene/renderer bootstrap, grid/ground, selection + transform, scene outline, input routing, and the render loop. Orchestrates `gw_scene_state.js`/`gw_history.js`/`gw_commands.js`/`gw_scene_persistence.js`/`gw_inspector.js`; builds the camera controller and asset loader via injected ctx; loads last and aliases the `gw_*` exports.
- `AI_FRONTEND_HANDOFF.md`: symptom-to-code map for fast AI handoff and debugging.
- `API_CONTRACT.md`: frontend route contract linking scripts, backend handlers, and required fields.

Keep the automation pipeline boundary stable while iterating on visuals:

- `pipeline_status.js` submits jobs through the unified `/jobs` endpoint (`body.mode` is `generate` or `download`); do not rename it. The legacy `/run` and `/download-data` routes still exist in `server.py` for backward compatibility but are no longer called by the frontend.
- Frontend scripts rely on: `/tiles`, `/boundary`, `/geocode`, `/status`, `/events` (SSE, with `/status` polling as fallback), `/health`, `/data-sources`, `/selection`, `/selection/clear`, `/software-paths`, `/open-houdini`, `/open-software`, `/close-software`, `/scene-root`, `/scene-assets`, `/scene-asset-file`, `/sync-whitebox-to-scene-assets`, `/open-scene-root`, `/export`, `/restart`, `/session`, and `/session/closed`. Static config is served at `/area-picker/regions.json`, `/area-picker/basemap-style.json`, and `/area-picker/world_countries.json`.
- Do not change the meaning of submitted `tile_ids`; Houdini and data acquisition rely on them.
- Visual changes should generally start in `styles.css`.
- Interaction and motion changes should stay in the smallest matching script above.
- Backend serving and config injection live in `server.py`.

## Testing

`tests/test_area_picker.py` guards frontend source text/structure (fast, no browser). `tests/test_game_workbench_e2e.py` drives the game workbench's place/undo/redo/delete and inspector-edit paths through a real, isolated Chromium instance via Playwright (`pytest.mark.e2e`) — it starts its own `server.py` subprocess on a free port (`VC_AREA_PICKER_PORT`) so it never touches a developer's already-running WorldBuilder session. First-time setup: `pip install playwright && playwright install chromium`. Skip the slower browser tests during fast iteration with `pytest tests/ -m "not e2e"`.
