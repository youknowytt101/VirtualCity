// Domain: game-workbench / editor-camera
// Owns: the editor viewport camera controller — Maya/Houdini-style alt-orbit/track/
//       dolly, right-drag look + WASDQE fly, wheel zoom, and flight-speed control.
// AI handoff: Factory takes a ctx of stable host references (camera, sceneHost,
//             speedInput, playMode) plus callbacks (getDragState, getSelectedObjectFrame,
//             screenToGround, pickCharacter, isTransformControlActive). Play-mode
//             camera is separate (gw_play.js).
(function() {
  'use strict';

  var GW = window.VC_GW || (window.VC_GW = {});
  var safeThree = GW.safeThree;

  function createGameCameraController(ctx) {
    var THREE = safeThree();
    // Stable host references (assigned once during init, never reassigned) can be
    // aliased directly. dragState is reassigned by the host, so it comes via getter.
    var camera = ctx.camera;
    var sceneHost = ctx.sceneHost;
    var speedInput = ctx.speedInput;
    var playMode = ctx.playMode;
    var getSelectedObjectFrame = ctx.getSelectedObjectFrame;
    var screenToGround = ctx.screenToGround;
    var pickCharacter = ctx.pickCharacter;
    var isTransformControlActive = ctx.isTransformControlActive;

    var keys = {};
    var rightDown = false;
    var cameraDragState = null;
    var forward = new THREE.Vector3();
    var right = new THREE.Vector3();
    var viewUp = new THREE.Vector3();
    var orbitOffset = new THREE.Vector3();
    var panDelta = new THREE.Vector3();
    var up = new THREE.Vector3(0, 0, 1);
    var yaw = 0;
    var pitch = 0;
    var moveSpeed = 35;

    function setMoveSpeed(value) {
      var numericSpeed = Number(value);
      if (!Number.isFinite(numericSpeed)) return moveSpeed;
      moveSpeed = THREE.MathUtils.clamp(numericSpeed, 1, 150);
      if (speedInput) speedInput.value = String(Math.round(moveSpeed));
      return moveSpeed;
    }

    function adjustMoveSpeed(event) {
      event.preventDefault();
      var speedStep = Math.max(5, moveSpeed * 0.12);
      return setMoveSpeed(moveSpeed + (event.deltaY < 0 ? speedStep : -speedStep));
    }

    function syncRotationFromCamera() {
      camera.getWorldDirection(forward);
      yaw = Math.atan2(forward.y, forward.x);
      pitch = Math.asin(THREE.MathUtils.clamp(forward.z, -1, 1));
    }

    function updateCameraRotation() {
      forward.set(
        Math.cos(pitch) * Math.cos(yaw),
        Math.cos(pitch) * Math.sin(yaw),
        Math.sin(pitch)
      );
      camera.lookAt(camera.position.clone().add(forward));
    }

    function updateAxes() {
      camera.getWorldDirection(forward).normalize();
      right.crossVectors(forward, up);
      if (right.lengthSq() === 0) right.set(1, 0, 0);
      else right.normalize();
      viewUp.crossVectors(right, forward).normalize();
    }

    // The orbit pivot must lie exactly on the camera's current forward ray. If it
    // didn't (e.g. the selected object's center, or a ground raycast under the
    // cursor, sitting off to one side), the very first drag-move frame's
    // camera.lookAt(target) would snap the view toward it before any orbiting
    // happened -- a visible jump, and not how UE's alt-orbit behaves. So only the
    // *distance* is "smart" (further out when a selection/ground hit is far away);
    // the pivot itself always sits straight ahead, making the initial lookAt a
    // no-op and the drag start seamless.
    function getViewportPivot(event) {
      camera.getWorldDirection(forward);
      var distance = 10;
      var selectedFrame = getSelectedObjectFrame();
      if (selectedFrame) {
        distance = camera.position.distanceTo(selectedFrame.center);
      } else {
        var point = screenToGround(event.clientX, event.clientY);
        if (point) distance = camera.position.distanceTo(point);
      }
      distance = THREE.MathUtils.clamp(distance, 1, 2000);
      return camera.position.clone().addScaledVector(forward, distance);
    }

    function beginViewportDrag(mode, event, target) {
      var state = {
        mode: mode,
        pointerId: event.pointerId,
        lastX: event.clientX,
        lastY: event.clientY,
        target: target || null
      };
      if (target && (mode === 'orbit' || mode === 'dolly' || mode === 'track')) {
        orbitOffset.copy(camera.position).sub(target);
        state.distance = Math.max(orbitOffset.length(), 0.001);
        state.yaw = Math.atan2(orbitOffset.y, orbitOffset.x);
        state.elevation = Math.asin(THREE.MathUtils.clamp(orbitOffset.z / state.distance, -1, 1));
      }
      cameraDragState = state;
      try {
        sceneHost.setPointerCapture(event.pointerId);
      } catch (e) {}
      sceneHost.focus();
    }

    function handleAltViewportDrag(event) {
      var state = cameraDragState;
      if (!state || event.pointerId !== state.pointerId) return false;
      var dx = event.clientX - state.lastX;
      var dy = event.clientY - state.lastY;
      state.lastX = event.clientX;
      state.lastY = event.clientY;

      if (state.mode === 'look') {
        yaw -= dx * 0.003;
        pitch -= dy * 0.003;
        pitch = THREE.MathUtils.clamp(pitch, -Math.PI / 2 + 0.02, Math.PI / 2 - 0.02);
        updateCameraRotation();
        return true;
      }

      if (!state.target) return true;

      if (state.mode === 'orbit') {
        state.yaw -= dx * 0.005;
        state.elevation += dy * 0.005;
        state.elevation = THREE.MathUtils.clamp(state.elevation, -Math.PI / 2 + 0.05, Math.PI / 2 - 0.05);
        var radiusOnGround = Math.cos(state.elevation) * state.distance;
        orbitOffset.set(
          Math.cos(state.yaw) * radiusOnGround,
          Math.sin(state.yaw) * radiusOnGround,
          Math.sin(state.elevation) * state.distance
        );
        camera.position.copy(state.target).add(orbitOffset);
        camera.lookAt(state.target);
        syncRotationFromCamera();
        return true;
      }

      if (state.mode === 'track') {
        updateAxes();
        var scale = Math.max(state.distance * 0.002, 0.006);
        panDelta.set(0, 0, 0);
        panDelta.addScaledVector(right, dx * scale);
        panDelta.addScaledVector(viewUp, -dy * scale);
        camera.position.add(panDelta);
        state.target.add(panDelta);
        return true;
      }

      if (state.mode === 'dolly') {
        state.distance = Math.max(0.35, state.distance - dy * state.distance * 0.01);
        orbitOffset.copy(camera.position).sub(state.target).normalize().multiplyScalar(state.distance);
        camera.position.copy(state.target).add(orbitOffset);
        camera.lookAt(state.target);
        syncRotationFromCamera();
        return true;
      }

      return true;
    }

    function handlePointerDown(event) {
      if (playMode && playMode.isPlaying()) return false;
      if (event.altKey && event.button >= 0 && event.button <= 2) {
        event.preventDefault();
        var target = getViewportPivot(event);
        if (event.button === 0) beginViewportDrag('orbit', event, target);
        else if (event.button === 1) beginViewportDrag('track', event, target);
        else if (event.button === 2) beginViewportDrag('dolly', event, target);
        return true;
      }
      if (event.button === 2) {
        event.preventDefault();
        rightDown = true;
        syncRotationFromCamera();
        beginViewportDrag('look', event, null);
        return true;
      }
      if (event.button === 1) {
        event.preventDefault();
        beginViewportDrag('track', event, getViewportPivot(event));
        return true;
      }
      if (event.button === 0 && !ctx.getDragState()) {
        if (isTransformControlActive()) return true;
        pickCharacter(event);
        return true;
      }
      return false;
    }

    function handlePointerMove(event) {
      if (!cameraDragState) return false;
      event.preventDefault();
      handleAltViewportDrag(event);
      return true;
    }

    function handlePointerUp(event) {
      if (!cameraDragState) return false;
      event.preventDefault();
      if (cameraDragState.mode === 'look') rightDown = false;
      var pointerId = cameraDragState.pointerId;
      cameraDragState = null;
      try {
        sceneHost.releasePointerCapture(pointerId);
      } catch (e) {}
      return true;
    }

    function update(deltaTime) {
      if (!rightDown) return false;
      var moved = false;
      var speed = keys.shiftleft || keys.shiftright ? moveSpeed * 2.5 : moveSpeed;
      var distance = speed * deltaTime;
      updateAxes();
      if (keys.keyw) {
        camera.position.addScaledVector(forward, distance);
        moved = true;
      }
      if (keys.keys) {
        camera.position.addScaledVector(forward, -distance);
        moved = true;
      }
      if (keys.keyd) {
        camera.position.addScaledVector(right, distance);
        moved = true;
      }
      if (keys.keya) {
        camera.position.addScaledVector(right, -distance);
        moved = true;
      }
      if (keys.keye) {
        camera.position.z += distance;
        moved = true;
      }
      if (keys.keyq) {
        camera.position.z -= distance;
        moved = true;
      }
      return moved;
    }

    return {
      clearState: function() {
        keys = {};
        rightDown = false;
        cameraDragState = null;
      },
      handlePointerDown: handlePointerDown,
      handlePointerMove: handlePointerMove,
      handlePointerUp: handlePointerUp,
      isLooking: function() { return rightDown; },
      pressKey: function(code) { keys[code] = true; },
      releaseKey: function(event) { delete keys[event.code.toLowerCase()]; },
      setMoveSpeed: setMoveSpeed,
      adjustMoveSpeed: adjustMoveSpeed,
      syncRotationFromCamera: syncRotationFromCamera,
      update: update,
      zoomView: function(event) {
        event.preventDefault();
        camera.getWorldDirection(forward);
        camera.position.addScaledVector(forward, -event.deltaY * 0.02);
      }
    };
  }

  GW.createGameCameraController = createGameCameraController;
})();
