# Area Picker Frontend

This folder contains the homepage UI for the WorldBuilder area picker.

- `index.html`: page structure and `window.VC_CONFIG` bootstrap values injected by the Python server.
- `styles.css`: visual design, layout, responsive rules, and animation polish.
- `app.js`: map setup, region navigation, and startup wiring.
- `workspace.js`: workspace switching, shell panel layout, refresh/restart controls, and account menu behavior.
- `selection_search.js`: grid loading, fixed-tile selection, persisted selection restore, and location search.
- `pipeline_status.js`: run/export buttons, status stream handling, progress UI, logs, and data-source rendering.
- `dcc_bridge.js`: DCC software paths, Houdini launch/probe state, and DCCbridge controls.
- `game_workbench.js`: Three.js virtual asset workbench.
- `AI_FRONTEND_HANDOFF.md`: symptom-to-code map for fast AI handoff and debugging.
- `API_CONTRACT.md`: frontend route contract linking scripts, backend handlers, and required fields.

Keep the automation pipeline boundary stable while iterating on visuals:

- `pipeline_status.js` submits jobs through the unified `/jobs` endpoint (`body.mode` is `generate` or `download`); do not rename it. The legacy `/run` and `/download-data` routes still exist in `server.py` for backward compatibility but are no longer called by the frontend.
- Frontend scripts rely on: `/tiles`, `/boundary`, `/geocode`, `/status`, `/events` (SSE, with `/status` polling as fallback), `/health`, `/data-sources`, `/selection`, `/selection/clear`, `/software-paths`, `/open-houdini`, `/open-software`, `/close-software`, `/asset-dir`, `/export`, `/restart`, `/session`, and `/session/closed`. Static config is served at `/area-picker/regions.json`, `/area-picker/basemap-style.json`, and `/area-picker/world_countries.json`.
- Do not change the meaning of submitted `tile_ids`; Houdini and data acquisition rely on them.
- Visual changes should generally start in `styles.css`.
- Interaction and motion changes should stay in the smallest matching script above.
- Backend serving and config injection live in `server.py`.
