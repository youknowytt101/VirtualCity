# Cloud Assets Browser Design

## Goal

Add a first-pass cloud asset library to the game editor. The library represents assets that will later live on a server and be available to all users. In this version it is backed by local server data, not a real remote object store.

## Scope

This version only displays the cloud asset library in the existing right-side `云端资产` tab.

Included:
- A server API that returns a cloud asset manifest.
- A right-side cloud asset browser UI inside the existing `cloud-assets-panel`.
- Two built-in material assets:
  - `UEPerson 主材质`, representing the current character body material `M_UE4Man_Body`, runtime type `MeshPhysicalMaterial`.
  - `卡通渲染材质`, representing the existing toon material factory, runtime type `MeshToonMaterial`.
- Refresh, loading, empty, and error states.
- Category counts and material-focused asset cards.

Not included in this version:
- Real file upload.
- Applying a cloud material to a selected object.
- Remote authentication, CDN, database storage, review, moderation, or asset permissions.
- Replacing the bottom `工程资产目录`; that panel remains the current project-local asset browser.

## Architecture

Use a local manifest-backed API as the cloud boundary.

Server:
- Add `/cloud-assets`.
- Return a stable JSON payload with `ok`, `available`, `assets`, `counts`, `message`, and optional `updated_at`.
- Keep records structured so a future remote implementation can return the same shape.

Frontend:
- Add a focused `cloud_assets.js` module loaded after the current game/editor scripts.
- Bind to the existing `.cloud-assets-panel`.
- Fetch `/cloud-assets` on load and on refresh.
- Render category buttons and asset cards using the existing compact asset-browser visual language.

Data model:

```json
{
  "id": "ueperson-body-material",
  "name": "UEPerson 主材质",
  "category": "material",
  "materialKind": "physical",
  "runtimeType": "MeshPhysicalMaterial",
  "source": "built-in",
  "description": "角色白色盔甲主体材质 M_UE4Man_Body",
  "tags": ["character", "armor", "pbr"]
}
```

## UI Behavior

The right-side `云端资产` tab shows:
- A compact header with title, status, and refresh button.
- Category filters: `全部`, `材质`.
- Asset cards with a material swatch, name, runtime material type, source, and short description.

For the first version, cards are informational only. Clicking a card selects it visually or no-ops; it must not imply that the material has been applied to the selected model.

## Error Handling

- If `/cloud-assets` fails, show a concise error state in the tab.
- If the manifest is empty, show an empty state.
- If a record has missing optional fields, render safe fallbacks instead of failing the whole panel.

## Testing

Add focused tests to `tests/test_area_picker.py`:
- HTML contains the cloud asset browser mount points in the existing `云端资产` tab.
- `cloud_assets.js` is loaded by `index.html`.
- `cloud_assets.js` fetches `/cloud-assets` and renders assets.
- Server source exposes `/cloud-assets`.
- Server payload includes the two built-in material assets and category counts.

## Future Extensions

Later phases can add:
- Upload to local simulated cloud storage, then real server storage.
- Applying a material asset to the selected object.
- Thumbnail generation and previews.
- Asset ownership, permissions, moderation, and publishing workflow.
