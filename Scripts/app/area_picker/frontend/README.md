# Area Picker Frontend

This folder contains the homepage UI for the VirtualCity area picker.

- `index.html`: page structure and `window.VC_CONFIG` bootstrap values injected by the Python server.
- `styles.css`: visual design, layout, responsive rules, and animation polish.
- `app.js`: browser interaction logic, map setup, tile selection, and API calls.

Keep the automation pipeline boundary stable while iterating on visuals:

- `app.js` submits jobs through the unified `/jobs` endpoint (`body.mode` is `generate` or `download`); do not rename it. The legacy `/run` and `/download-data` routes still exist in `server.py` for backward compatibility but are no longer called by the frontend.
- Other endpoints `app.js` relies on: `/tiles`, `/boundary`, `/geocode`, `/status`, `/events` (SSE, with `/status` polling as fallback), `/health`, `/data-sources`, `/selection`, `/selection/clear`, `/software-paths`, `/open-houdini`, `/export`, `/session`, and `/session/closed`. Static config is served at `/area-picker/regions.json` and `/area-picker/basemap-style.json`.
- Do not change the meaning of submitted `tile_ids`; Houdini and data acquisition rely on them.
- Visual changes should generally start in `styles.css`.
- Interaction and motion changes should generally stay in `app.js`.
- Backend serving and config injection live in `server.py`.
