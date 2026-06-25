# Orbit Preview Three Overlay Design

## Goal

Upgrade the current `orbit-preview` frontend overlay so that:

- Earth atmosphere is rendered as a real translucent 3D sphere
- Satellite orbit paths are rendered as real 3D lines
- Existing hex satellite icon styling remains visually unchanged

The existing MapLibre globe map remains the system of record for map state, user interaction, and the rest of the frontend workflow.

## Scope

In scope:

- Replace the current custom `orbit-preview` render path with a Three.js-backed overlay
- Keep current satellite position / trajectory sampling logic as the data source
- Keep current label-canvas based satellite icon rendering
- Preserve current mount behavior from `app.js`

Out of scope:

- Replacing MapLibre itself
- Reworking selection, deck.gl buildings, grid, region, or search flows
- Upgrading the optional sun / planet preview path in this pass
- Redesigning the visual language of satellite icons or labels

## Current System

Today the map is owned by MapLibre in globe projection. `orbit-preview.js` adds two extra canvases over the map container:

- a WebGL canvas used for point/depth-style orbital rendering
- a 2D canvas used for tails, labels, and icon-like glyphs

Satellite positions are already computed in 3D from TLE data via `satellite.js`, then projected into the current map view.

## Proposed Architecture

Keep the overlay split into two layers:

- Three.js layer:
  - owns the transparent 3D scene
  - renders the atmosphere sphere
  - renders 3D orbit polylines in Earth-centered coordinates
- 2D label layer:
  - keeps the existing hex spacecraft icon look
  - keeps existing text label rendering
  - projects satellite world positions to screen space each frame

`app.js` remains responsible only for mounting the overlay against the existing MapLibre instance.

## Coordinate Strategy

Use the existing Earth-centered normalized coordinate system from `orbit-preview.js` as the shared model space:

- Earth radius stays normalized to `1`
- sampled satellite positions remain vectors around that unit sphere
- Three.js orbit lines and atmosphere sphere use the same world coordinates

The overlay camera will be synchronized each frame from MapLibre view state so the Three scene visually stays locked to the globe.

## Rendering Design

### Atmosphere

Replace the current unused gradient-ring approach with a real sphere mesh:

- sphere slightly larger than Earth radius
- transparent material
- additive or soft alpha blending tuned for a restrained glow
- rendered behind orbit lines and icons where depth requires it

This is meant to read as a thin atmospheric shell, not a fog volume.

### Orbit Lines

Render orbit paths as Three.js line geometry built from sampled satellite trajectory points:

- reuse existing trajectory cache / sampling logic where possible
- build per-satellite line vertex buffers in Earth-centered coordinates
- update cached geometry only when the current logic would already rebuild tails

The visual target is the current orbit path feel, but now as real 3D geometry instead of screen-space 2D stroke segments.

### Satellite Icons

Do not change the icon style. Keep the current 2D hex outline glyph rendering on the label canvas.

The only change is where the projected satellite position comes from:

- use the same satellite world position
- project it through the synchronized overlay/map camera path
- draw the same icon and label treatment at the resulting screen coordinate

## Data Flow

1. Fetch and parse TLE data as today
2. Sample / cache satellite positions and trajectory points as today
3. Feed sampled 3D positions into:
   - Three.js orbit line geometry
   - per-frame icon projection for the label canvas
4. On each animation frame:
   - sync overlay size and camera with MapLibre
   - render the Three.js scene
   - clear and redraw label canvas icons / labels

## Error Handling

- If Three.js is unavailable, fail closed and preserve current app behavior without crashing the map
- If a satellite sample is invalid, skip that satellite for the affected frame / geometry rebuild
- If overlay sync fails during a frame, skip rendering that frame rather than mutating unrelated map state

## Verification

Primary checks:

- map interactions still work: pan, zoom, 2D/3D toggle, city fly/orbit
- atmosphere remains visually attached to the globe
- orbit lines stay spatially correct as the camera rotates
- satellite hex icons still match the current look
- no duplicate overlay mounts after style reload or repeated setup calls

## Risks

- Camera sync between MapLibre globe and Three.js may require calibration
- Depth ordering between atmosphere, Earth, and orbit lines may need tuning
- Current code has mixed comments about atmosphere ownership; implementation should leave one clear path

## Recommended Implementation Shape

- Keep most sampling/math helpers in `orbit-preview.js`
- Replace the current WebGL point/depth rendering section with a Three.js scene manager
- Keep the label canvas path for icons and labels with minimal change
- Make only small glue changes in `app.js` if mount options need to expand

## Open Decision

Assumption for this spec:

- We will add or use an already-available Three.js runtime only for the overlay layer, not for the rest of the frontend

If the repo does not already ship Three.js, the next planning step should decide whether to vendor a local build or use an existing bundled path, rather than pulling in a larger new frontend stack.
