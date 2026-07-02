# UEPerson Character Swap Design

## Context

The game workbench currently creates editor/play characters through
`Scripts/app/area_picker/frontend/gw_character.js`. That module loads the local
`RobotExpressive.glb` asset, adapts its animations through `AnimationMixer`, and
exposes the existing `GW.createCharacter`, `GW.resetCharacterMotion`, and
`GW.updateCharacterMotion` hooks used by `game_workbench.js` and `gw_play.js`.

The requested replacement character is `example/public/glb/UEPerson.glb` from
`https://github.com/hh-hang/three-player-controller`.

## Selected Approach

Use a direct asset swap while preserving the local game workbench interface.
The target repository's full player controller will not be imported.

This keeps the change scoped to the current editor/player character pipeline:

- Add `UEPerson.glb` under `Scripts/app/area_picker/frontend/assets/characters/`.
- Point `gw_character.js` at the new asset.
- Update source comments and `character.userData.avatarSource`.
- Adapt animation names from the target repository's `PLAYER_MODELS.person4`
  config: `idle`, `walk`, `run`, and `jumpStart`.
- Keep the existing loading proxy, `AnimationMixer`, character marking,
  selection outline behavior, Z-up placement logic, and play-mode motion hooks.

## Data Flow

1. User places a character in the editor.
2. `GW.createCharacter()` returns a `THREE.Group` with the existing loading
   proxy.
3. `GLTFLoader` loads `/area-picker/assets/characters/UEPerson.glb`.
4. The loaded model is marked as a character child, attached to the character
   root, scaled to the local target height, and grounded at local `z = 0`.
5. `AnimationMixer` registers available clips by name.
6. Idle is played after load; play mode switches between idle and locomotion
   through `GW.updateCharacterMotion()`.

## Tests And Verification

Update the existing area picker test that asserts the bundled character asset.
The test should verify:

- `UEPerson.glb` exists and is non-trivial in size.
- `gw_character.js` references `UEPerson.glb`.
- Source comments point to `hh-hang/three-player-controller`.
- `GLTFLoader` and `AnimationMixer` are still used.
- The expected UEPerson animation names are present.
- `gw_play.js` still calls the shared motion hooks.

After implementation, run the focused `pytest` area picker test first. If a
browser/server flow is already available and cheap to run, verify that placing a
character still creates a selectable player object and play mode still updates
animation state.

## Risks

The target repository does not include a separate asset license note for
`UEPerson.glb`; document the exact upstream path as the source. The asset uses
different animation names than RobotExpressive, so the adapter must avoid
hard-coded `Idle`, `Walking`, `Running`, and `Jump` lookups. Orientation and
height should continue to be normalized by the existing fit routine.
