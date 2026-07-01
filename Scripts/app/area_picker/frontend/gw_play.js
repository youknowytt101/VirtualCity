// Domain: game-workbench / play-mode
// Owns: the third-person play controller (pointer-lock look, WASD movement,
//       follow camera). Factory returning a controller bound to a render target.
// AI handoff: For play camera/movement, start here; editor camera lives in
//             gw_camera.js, scene wiring in game_workbench.js.
(function() {
  'use strict';

  var GW = window.VC_GW || (window.VC_GW = {});
  var safeThree = GW.safeThree;
  var resetCharacterMotion = GW.resetCharacterMotion;
  var updateCharacterMotion = GW.updateCharacterMotion;

  function createPlayModeController(options) {
    var THREE = safeThree();
    var config = Object.assign({
      cameraDistance: 6,
      cameraHeight: 1.8,
      cameraTargetHeight: 1.2,
      lookSensitivity: 0.0025,
      maxPitch: 1.47,
      minPitch: -1.4,
      moveSpeed: 4.5,
      shoulderOffset: 0.45,
      lookDamping: 18,
      gravity: -32,
      jumpSpeed: 17.9  // √(2·32·5) → ~5m apex
    }, options.options || {});
    var movementKeys = { keyw: true, keya: true, keys: true, keyd: true };
    var keys = {};
    var forward = new THREE.Vector3();
    var moveDirection = new THREE.Vector3();
    var right = new THREE.Vector3();
    var cameraPosition = new THREE.Vector3();
    var focusPoint = new THREE.Vector3();
    var player = null;
    var playing = false;
    var verticalVelocity = 0;
    var grounded = false;
    var yaw = 0;
    var pitch = 0.18;
    var targetYaw = 0;
    var targetPitch = 0.18;
    var canvas = options.renderer.domElement;

    // Ground height under (x, y): host casts a downward ray against the whitebox
    // layers and falls back to the z=0 plane. Defaults to 0 if not injected.
    function groundHeightAt(x, y) {
      return options.sampleGroundHeight ? options.sampleGroundHeight(x, y) : 0;
    }

    // Per-frame gravity integration with landing clamp. Walking onto higher
    // terrain snaps up; walking off an edge falls until the next surface.
    function applyGravity(deltaTime) {
      var groundZ = groundHeightAt(player.position.x, player.position.y);
      verticalVelocity += config.gravity * deltaTime;
      player.position.z += verticalVelocity * deltaTime;
      if (player.position.z <= groundZ) {
        player.position.z = groundZ;
        verticalVelocity = 0;
        grounded = true;
      } else {
        grounded = false;
      }
    }

    function isPointerLocked() {
      return document.pointerLockElement === canvas;
    }

    function requestPointerLock() {
      if (!isPointerLocked() && canvas.requestPointerLock) {
        var result = canvas.requestPointerLock();
        if (result && typeof result.catch === 'function') result.catch(function() {});
      }
    }

    function exitPointerLock() {
      if (isPointerLocked() && document.exitPointerLock) document.exitPointerLock();
    }

    function syncYawFromCamera() {
      options.camera.getWorldDirection(forward);
      yaw = forward.lengthSq() ? Math.atan2(forward.y, forward.x) : 0;
      targetYaw = yaw;
    }

    function getGroundForward() {
      return forward.set(Math.cos(yaw), Math.sin(yaw), 0).normalize();
    }

    function getGroundRight() {
      return right.set(Math.sin(yaw), -Math.cos(yaw), 0).normalize();
    }

    function updateCamera() {
      if (!player) return;
      var groundForward = getGroundForward();
      var groundRight = getGroundRight();
      var horizontalDistance = config.cameraDistance * Math.cos(pitch);
      var verticalOffset = config.cameraHeight + config.cameraDistance * Math.sin(pitch);

      focusPoint.copy(player.position);
      focusPoint.z += config.cameraTargetHeight;
      cameraPosition
        .copy(focusPoint)
        .addScaledVector(groundForward, -horizontalDistance)
        .addScaledVector(groundRight, config.shoulderOffset);
      cameraPosition.z += verticalOffset;
      options.camera.position.copy(cameraPosition);
      options.camera.lookAt(focusPoint);
    }

    document.addEventListener('pointerlockchange', function() {
      if (playing && !isPointerLocked()) keys = {};
    });

    function enter(character) {
      if (!character || character.userData.assetType !== 'character') return false;
      player = character;
      playing = true;
      keys = {};
      syncYawFromCamera();
      pitch = 0.18;
      targetYaw = yaw;
      targetPitch = pitch;
      verticalVelocity = 0;
      grounded = false;
      canvas.focus();
      updateCamera();
      options.onChange(true);
      return true;
    }

    function exit() {
      if (!playing) return false;
      resetCharacterMotion(player);
      playing = false;
      player = null;
      keys = {};
      exitPointerLock();
      options.onChange(false);
      return true;
    }

    function handleKeyDown(event) {
      if (!playing) return false;
      var code = event.code.toLowerCase();
      event.preventDefault();
      if (code === 'escape') {
        exit();
        return true;
      }
      if (code === 'space') {
        if (grounded) {
          verticalVelocity = config.jumpSpeed;
          grounded = false;
        }
        return true;
      }
      if (movementKeys[code]) keys[code] = true;
      return true;
    }

    function handleKeyUp(event) {
      if (!playing) return false;
      var code = event.code.toLowerCase();
      event.preventDefault();
      if (movementKeys[code]) delete keys[code];
      return true;
    }

    function handlePointerDown(event) {
      if (!playing) return false;
      event.preventDefault();
      canvas.focus();
      requestPointerLock();
      return true;
    }

    function handlePointerMove(event) {
      if (!playing) return false;
      if (!isPointerLocked()) return true;
      event.preventDefault();
      var maxDelta = 200;
      var dx = event.movementX || 0;
      var dy = event.movementY || 0;
      if (Math.abs(dx) > maxDelta || Math.abs(dy) > maxDelta) return true;
      if (!dx && !dy) return true;
      targetYaw -= dx * config.lookSensitivity;
      targetPitch = THREE.MathUtils.clamp(
        targetPitch + dy * config.lookSensitivity,
        config.minPitch,
        config.maxPitch
      );
      return true;
    }

    function update(deltaTime) {
      if (!playing || !player) return false;
      var t = 1 - Math.exp(-config.lookDamping * deltaTime);
      yaw += (targetYaw - yaw) * t;
      pitch += (targetPitch - pitch) * t;
      // Gravity first so grounded reflects this frame. Walking is only allowed
      // once grounded — airborne (jumping/falling) ignores WASD, UE-style.
      applyGravity(deltaTime);
      moveDirection.set(0, 0, 0);
      if (grounded) {
        if (keys.keyw) moveDirection.add(getGroundForward());
        if (keys.keys) moveDirection.addScaledVector(getGroundForward(), -1);
        if (keys.keyd) moveDirection.add(getGroundRight());
        if (keys.keya) moveDirection.addScaledVector(getGroundRight(), -1);
        if (moveDirection.lengthSq() > 0) {
          moveDirection.normalize();
          player.position.addScaledVector(moveDirection, config.moveSpeed * deltaTime);
          player.rotation.z = Math.atan2(moveDirection.y, moveDirection.x) - Math.PI / 2;
        }
      }
      updateCharacterMotion(player, moveDirection, deltaTime);
      updateCamera();
      return true;
    }

    return {
      clearInput: function() { keys = {}; },
      enter: enter,
      exit: exit,
      handleKeyDown: handleKeyDown,
      handleKeyUp: handleKeyUp,
      handlePointerDown: handlePointerDown,
      handlePointerMove: handlePointerMove,
      isPlaying: function() { return playing; },
      update: update
    };
  }

  GW.createPlayModeController = createPlayModeController;
})();
