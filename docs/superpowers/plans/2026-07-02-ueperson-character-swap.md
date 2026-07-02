# UEPerson Character Swap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the game workbench's bundled RobotExpressive avatar with `UEPerson.glb` from `hh-hang/three-player-controller`.

**Architecture:** Keep the existing local character factory and play-mode hooks. Swap only the bundled GLB asset and the animation adapter constants so `game_workbench.js` and `gw_play.js` continue to call the same `GW.createCharacter`, `GW.resetCharacterMotion`, and `GW.updateCharacterMotion` APIs.

**Tech Stack:** Three.js, GLTFLoader, `AnimationMixer`, browser-served static assets, Python `pytest` tests.

---

## File Structure

- Modify `tests/test_area_picker.py`: update the existing character asset regression test from RobotExpressive expectations to UEPerson expectations.
- Modify `Scripts/app/area_picker/frontend/gw_character.js`: point to `UEPerson.glb`, update source metadata, and adapt animation names to `idle`, `walk`, `run`, and `jumpStart`.
- Modify `Scripts/app/area_picker/frontend/README.md`: describe the UEPerson avatar loader instead of RobotExpressive.
- Modify `Scripts/app/area_picker/frontend/assets/characters/README.md`: record the exact upstream repository path for `UEPerson.glb`.
- Add `Scripts/app/area_picker/frontend/assets/characters/UEPerson.glb`: downloaded from `https://raw.githubusercontent.com/hh-hang/three-player-controller/master/example/public/glb/UEPerson.glb`.
- Leave `RobotExpressive.glb` untouched unless a future cleanup request explicitly asks to remove it, because deleting binary assets in a dirty worktree is more invasive than the requested runtime swap.

### Task 1: Update The Character Regression Test

**Files:**
- Modify: `tests/test_area_picker.py:1454-1469`

- [ ] **Step 1: Change the existing test name and assertions**

Replace the `test_game_character_uses_threejs_robot_expressive_avatar` body with:

```python
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
        self.assertIn("new THREE.AnimationMixer", character_js)
        self.assertIn("idle: 'idle'", character_js)
        self.assertIn("walk: 'walk'", character_js)
        self.assertIn("run: 'run'", character_js)
        self.assertIn("jump: 'jumpStart'", character_js)
        self.assertIn("actions[ROBOT_ANIMATIONS.idle]", character_js)
        self.assertIn("actions[ROBOT_ANIMATIONS.run]", character_js)
        self.assertIn("actions[ROBOT_ANIMATIONS.walk]", character_js)
        self.assertIn("actions[ROBOT_ANIMATIONS.jump]", character_js)
        self.assertIn("character.userData.robotAvatar", character_js)
        self.assertIn("character.userData.animationMixer", character_js)
        self.assertIn("createCharacterMaterial", character_js)
        self.assertIn("updateCharacterMotion(player, moveDirection, deltaTime)", play_js)
        self.assertIn("resetCharacterMotion(player)", play_js)
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```powershell
python -m pytest tests/test_area_picker.py::TestPickerHtml::test_game_character_uses_ueperson_avatar_from_three_player_controller -q
```

Expected: FAIL because `UEPerson.glb` is not present and `gw_character.js` still references RobotExpressive.

### Task 2: Add UEPerson Asset And Update The Character Adapter

**Files:**
- Add: `Scripts/app/area_picker/frontend/assets/characters/UEPerson.glb`
- Modify: `Scripts/app/area_picker/frontend/gw_character.js:1-20`
- Modify: `Scripts/app/area_picker/frontend/gw_character.js:165-186`
- Modify: `Scripts/app/area_picker/frontend/gw_character.js:230-236`

- [ ] **Step 1: Download the UEPerson GLB**

Run:

```powershell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/hh-hang/three-player-controller/master/example/public/glb/UEPerson.glb" -OutFile "Scripts/app/area_picker/frontend/assets/characters/UEPerson.glb"
```

Expected: `Scripts/app/area_picker/frontend/assets/characters/UEPerson.glb` exists and is larger than 5 MB.

- [ ] **Step 2: Update the top-level source constants**

Change the source comments and constants in `gw_character.js` to:

```javascript
// Owns: the Three.js UEPerson avatar loader, animation adapter, and
//       shared toon/outline helpers used by the game workbench.
// AI handoff: For avatar look or run-cycle motion, start here; selection/outline
//             highlight wiring stays in game_workbench.js.
(function() {
  'use strict';

  var GW = window.VC_GW || (window.VC_GW = {});
  var safeThree = GW.safeThree;
  var sharedToonGradientMap = null;
  // Model source: hh-hang/three-player-controller example/public/glb/UEPerson.glb.
  var ROBOT_AVATAR_URL = '/area-picker/assets/characters/UEPerson.glb';
  var ROBOT_TARGET_HEIGHT = 1.72;
  var ROBOT_ANIMATIONS = {
    idle: 'idle',
    walk: 'walk',
    run: 'run',
    jump: 'jumpStart'
  };
```

- [ ] **Step 3: Update action lookup to use UEPerson clip names**

Replace the `createRobotActions` action selection block with:

```javascript
    var runningActionName = actions[ROBOT_ANIMATIONS.run] ? ROBOT_ANIMATIONS.run : ROBOT_ANIMATIONS.walk;
    var locomotionActionName = actions[ROBOT_ANIMATIONS.walk] ? ROBOT_ANIMATIONS.walk : runningActionName;
    var jumpAction = actions[ROBOT_ANIMATIONS.jump];
    if (jumpAction) {
      jumpAction.loop = THREE.LoopOnce;
      jumpAction.clampWhenFinished = true;
    }
```

Replace the idle start line with:

```javascript
    if (actions[ROBOT_ANIMATIONS.idle]) playRobotAction(character, ROBOT_ANIMATIONS.idle, 0);
```

- [ ] **Step 4: Update loaded model metadata**

Change the attached model name and avatar source to:

```javascript
    model.name = 'player-ueperson';
```

and:

```javascript
    character.userData.avatarSource = 'hh-hang/three-player-controller UEPerson';
```

- [ ] **Step 5: Run the focused test to verify it passes**

Run:

```powershell
python -m pytest tests/test_area_picker.py::TestPickerHtml::test_game_character_uses_ueperson_avatar_from_three_player_controller -q
```

Expected: PASS.

### Task 3: Update Asset Documentation

**Files:**
- Modify: `Scripts/app/area_picker/frontend/assets/characters/README.md`
- Modify: `Scripts/app/area_picker/frontend/README.md`

- [ ] **Step 1: Replace the character asset README content**

Use this content in `Scripts/app/area_picker/frontend/assets/characters/README.md`:

```markdown
# Character Assets

## UEPerson.glb

- Source: `hh-hang/three-player-controller`, `example/public/glb/UEPerson.glb`
- Upstream URL: `https://github.com/hh-hang/three-player-controller/blob/master/example/public/glb/UEPerson.glb`
- Local use: default editor/play character for the area picker game workbench.

The upstream repository does not include a separate asset license note for this
GLB. Keep the exact upstream path here so provenance is auditable.
```

- [ ] **Step 2: Update frontend module README wording**

In `Scripts/app/area_picker/frontend/README.md`, replace the `gw_character.js` bullet with:

```markdown
- `gw_character.js`: Three.js UEPerson GLB avatar loading, animation mixer wiring, and shared toon/outline helpers. Pure factories.
```

- [ ] **Step 3: Run the focused test again**

Run:

```powershell
python -m pytest tests/test_area_picker.py::TestPickerHtml::test_game_character_uses_ueperson_avatar_from_three_player_controller -q
```

Expected: PASS.

### Task 4: Final Verification And Review

**Files:**
- Verify: `Scripts/app/area_picker/frontend/gw_character.js`
- Verify: `Scripts/app/area_picker/frontend/assets/characters/UEPerson.glb`
- Verify: `Scripts/app/area_picker/frontend/assets/characters/README.md`
- Verify: `Scripts/app/area_picker/frontend/README.md`
- Verify: `tests/test_area_picker.py`

- [ ] **Step 1: Run the area picker test module**

Run:

```powershell
python -m pytest tests/test_area_picker.py -q
```

Expected: PASS, or a clear unrelated failure from pre-existing dirty worktree changes.

- [ ] **Step 2: Inspect the final diff**

Run:

```powershell
git diff -- Scripts/app/area_picker/frontend/gw_character.js Scripts/app/area_picker/frontend/assets/characters/README.md Scripts/app/area_picker/frontend/README.md tests/test_area_picker.py
git status --short -- Scripts/app/area_picker/frontend/assets/characters/UEPerson.glb
```

Expected: diff only contains the UEPerson swap, documentation updates, and test expectation updates; status shows the new `UEPerson.glb` asset.

- [ ] **Step 3: Report verification**

In the final response, list changed files, the test commands that were run, and any remaining risk about upstream asset licensing/provenance.
