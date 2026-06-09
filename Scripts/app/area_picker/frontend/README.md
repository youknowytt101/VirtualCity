# Area Picker Frontend

This folder contains the homepage UI for the VirtualCity area picker.

- `index.html`: page structure and `window.VC_CONFIG` bootstrap values injected by the Python server.
- `styles.css`: visual design, layout, responsive rules, and animation polish.
- `app.js`: browser interaction logic, Leaflet map setup, tile selection, and API calls.

Keep the automation pipeline boundary stable while iterating on visuals:

- Do not rename the API endpoints used by `app.js`: `/tiles`, `/run`, `/download-data`, `/status`, `/health`, `/data-sources`, `/selection`, `/selection/clear`, `/software-paths`, `/open-houdini`, and `/export`.
- Do not change the meaning of submitted `tile_ids`; Houdini and data acquisition rely on them.
- Visual changes should generally start in `styles.css`.
- Interaction and motion changes should generally stay in `app.js`.
- Backend serving and config injection live in `server.py`.
