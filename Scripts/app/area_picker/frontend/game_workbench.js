(function() {
  'use strict';

  var sceneHost = null;
  var dragPreview = null;
  var runButton = null;
  var runLabel = null;
  var speedInput = null;
  var statusText = null;
  var renderer = null;
  var scene = null;
  var camera = null;
  var clock = null;
  var raycaster = null;
  var mouse = null;
  var groundPlane = null;
  var hitPoint = null;
  var selectionBox = null;
  var playMode = null;
  var cameraControls = null;
  var rafId = null;
  var initialized = false;
  var active = false;
  var dragState = null;
  var characters = [];
  var selectedCharacter = null;
  var transformControls = null;
  var transformControlsLoading = null;
  var undoStack = [];
  var sharedToonGradientMap = null;

  function setStatus(message) {
    if (statusText) statusText.textContent = message;
  }

  function safeThree() {
    if (!window.THREE) {
      setStatus('Three.js 未加载');
      return null;
    }
    return window.THREE;
  }

  function getToonGradientMap() {
    var THREE = safeThree();
    if (!THREE) return null;
    if (sharedToonGradientMap) return sharedToonGradientMap;

    var stops = new Uint8Array([70, 160, 240]);
    var map = new THREE.DataTexture(stops, stops.length, 1, THREE.RedFormat);
    map.minFilter = THREE.NearestFilter;
    map.magFilter = THREE.NearestFilter;
    map.generateMipmaps = false;
    map.needsUpdate = true;
    sharedToonGradientMap = map;
    return map;
  }

  function createToonGrayMaterial(color) {
    return createCharacterMaterial(color || 0x9a9a9a);
  }

  function createCharacterMaterial(color) {
    var THREE = safeThree();
    return new THREE.MeshToonMaterial({
      color: color,
      gradientMap: getToonGradientMap()
    });
  }

  function createOutlineMaterial(thickness) {
    var THREE = safeThree();
    return new THREE.ShaderMaterial({
      side: THREE.BackSide,
      uniforms: {
        outlineColor: { value: new THREE.Color(0x141414) },
        outlineThickness: { value: thickness || 0.012 }
      },
      vertexShader: [
        'uniform float outlineThickness;',
        'void main() {',
        '  vec3 pushed = position + normalize(normal) * outlineThickness;',
        '  gl_Position = projectionMatrix * modelViewMatrix * vec4(pushed, 1.0);',
        '}'
      ].join('\n'),
      fragmentShader: [
        'uniform vec3 outlineColor;',
        'void main() {',
        '  gl_FragColor = vec4(outlineColor, 1.0);',
        '}'
      ].join('\n')
    });
  }

  function createOutlineMesh(geometry, thickness) {
    var THREE = safeThree();
    var outline = new THREE.Mesh(geometry, createOutlineMaterial(thickness));
    outline.userData.pickable = false;
    outline.userData.outline = true;
    return outline;
  }

  function createCharacterPart(options) {
    var THREE = safeThree();
    var mesh = new THREE.Mesh(options.geometry, options.material);
    mesh.name = options.name;
    if (options.position) mesh.position.set(options.position[0], options.position[1], options.position[2]);
    if (options.rotation) mesh.rotation.set(options.rotation[0], options.rotation[1], options.rotation[2]);
    if (options.scale) mesh.scale.set(options.scale[0], options.scale[1], options.scale[2]);
    if (options.outline !== false) mesh.add(createOutlineMesh(options.geometry, options.outline || 0.012));
    mesh.userData.restPosition = mesh.position.clone();
    mesh.userData.restRotation = mesh.rotation.clone();
    return mesh;
  }

  function createCharacter() {
    var THREE = safeThree();
    var character = new THREE.Group();
    var Capsule = THREE.CapsuleGeometry || THREE.CylinderGeometry;
    var bodyGeometry = THREE.CapsuleGeometry
      ? new Capsule(0.27, 0.72, 6, 14)
      : new Capsule(0.27, 0.27, 1.08, 14);
    var limbGeometry = THREE.CapsuleGeometry
      ? new Capsule(0.075, 0.42, 5, 10)
      : new Capsule(0.075, 0.075, 0.58, 10);
    var legGeometry = THREE.CapsuleGeometry
      ? new Capsule(0.09, 0.42, 5, 10)
      : new Capsule(0.09, 0.09, 0.6, 10);
    var materials = {
      suit: createCharacterMaterial(0x4f8fd8),
      accent: createCharacterMaterial(0xf2c94c),
      dark: createCharacterMaterial(0x242a31),
      cloth: createCharacterMaterial(0x6f7680),
      skin: createCharacterMaterial(0xd8c4a8)
    };
    var body = createCharacterPart({
      name: 'player-body',
      geometry: bodyGeometry,
      material: materials.suit,
      position: [0, 0, 0.88],
      rotation: [Math.PI / 2, 0, 0],
      outline: 0.014
    });
    var chest = createCharacterPart({
      name: 'player-chest-marker',
      geometry: new THREE.BoxGeometry(0.32, 0.045, 0.2),
      material: materials.accent,
      position: [0, 0.265, 1.02],
      outline: 0.006
    });
    var head = createCharacterPart({
      name: 'player-head',
      geometry: new THREE.SphereGeometry(0.24, 24, 16),
      material: materials.skin,
      position: [0, 0.02, 1.5],
      outline: 0.012
    });
    var helmet = createCharacterPart({
      name: 'player-helmet',
      geometry: new THREE.SphereGeometry(0.255, 24, 12),
      material: materials.dark,
      position: [0, 0.01, 1.58],
      scale: [1.04, 1.04, 0.72],
      outline: 0.01
    });
    var visor = createCharacterPart({
      name: 'player-visor',
      geometry: new THREE.BoxGeometry(0.3, 0.055, 0.085),
      material: materials.accent,
      position: [0, 0.235, 1.54],
      outline: 0.006
    });
    var brim = createCharacterPart({
      name: 'player-helmet-brim',
      geometry: new THREE.BoxGeometry(0.34, 0.18, 0.04),
      material: materials.dark,
      position: [0, 0.18, 1.7],
      outline: 0.006
    });
    var backpack = createCharacterPart({
      name: 'player-backpack',
      geometry: new THREE.BoxGeometry(0.38, 0.16, 0.52),
      material: materials.dark,
      position: [0, -0.245, 0.91],
      outline: 0.01
    });
    var leftArm = createCharacterPart({
      name: 'player-left-arm',
      geometry: limbGeometry,
      material: materials.cloth,
      position: [-0.37, 0.01, 0.88],
      rotation: [Math.PI / 2, 0, 0.16],
      outline: 0.01
    });
    var rightArm = createCharacterPart({
      name: 'player-right-arm',
      geometry: limbGeometry,
      material: materials.cloth,
      position: [0.37, 0.01, 0.88],
      rotation: [Math.PI / 2, 0, -0.16],
      outline: 0.01
    });
    var leftLeg = createCharacterPart({
      name: 'player-left-leg',
      geometry: legGeometry,
      material: materials.dark,
      position: [-0.15, 0, 0.36],
      rotation: [Math.PI / 2, 0, 0.04],
      outline: 0.01
    });
    var rightLeg = createCharacterPart({
      name: 'player-right-leg',
      geometry: legGeometry,
      material: materials.dark,
      position: [0.15, 0, 0.36],
      rotation: [Math.PI / 2, 0, -0.04],
      outline: 0.01
    });
    var leftFoot = createCharacterPart({
      name: 'player-left-foot',
      geometry: new THREE.BoxGeometry(0.22, 0.38, 0.11),
      material: materials.dark,
      position: [-0.15, 0.1, 0.06],
      outline: 0.008
    });
    var rightFoot = createCharacterPart({
      name: 'player-right-foot',
      geometry: new THREE.BoxGeometry(0.22, 0.38, 0.11),
      material: materials.dark,
      position: [0.15, 0.1, 0.06],
      outline: 0.008
    });

    character.userData.motionParts = {
      upper: [body, chest, head, helmet, visor, brim, backpack],
      leftArm: leftArm,
      rightArm: rightArm,
      leftLeg: leftLeg,
      rightLeg: rightLeg,
      leftFoot: leftFoot,
      rightFoot: rightFoot
    };
    character.add(
      backpack,
      body,
      chest,
      leftArm,
      rightArm,
      leftLeg,
      rightLeg,
      leftFoot,
      rightFoot,
      head,
      helmet,
      visor,
      brim
    );
    resetCharacterMotion(character);
    return character;
  }

  function resetPartMotion(part) {
    if (!part || !part.userData.restPosition || !part.userData.restRotation) return;
    part.position.copy(part.userData.restPosition);
    part.rotation.copy(part.userData.restRotation);
  }

  function resetCharacterMotion(character) {
    var parts = character && character.userData.motionParts;
    if (!parts) return;
    parts.upper.forEach(resetPartMotion);
    resetPartMotion(parts.leftArm);
    resetPartMotion(parts.rightArm);
    resetPartMotion(parts.leftLeg);
    resetPartMotion(parts.rightLeg);
    resetPartMotion(parts.leftFoot);
    resetPartMotion(parts.rightFoot);
  }

  function updateCharacterMotion(character, moveDirection, deltaTime) {
    var parts = character && character.userData.motionParts;
    if (!parts) return;
    var moving = moveDirection && moveDirection.lengthSq() > 0.0001;
    character.userData.motionTime = (character.userData.motionTime || 0) + deltaTime * (moving ? 10 : 3);
    resetCharacterMotion(character);
    if (!moving) {
      var idle = Math.sin(character.userData.motionTime) * 0.012;
      parts.upper.forEach(function(part) {
        part.position.z += idle;
      });
      return;
    }

    var stride = Math.sin(character.userData.motionTime);
    var counterStride = Math.sin(character.userData.motionTime + Math.PI);
    var bob = Math.abs(Math.sin(character.userData.motionTime * 2)) * 0.045;
    parts.upper.forEach(function(part) {
      part.position.z += bob;
    });
    parts.leftArm.rotation.x += counterStride * 0.42;
    parts.rightArm.rotation.x += stride * 0.42;
    parts.leftLeg.rotation.x += stride * 0.32;
    parts.rightLeg.rotation.x += counterStride * 0.32;
    parts.leftFoot.position.y += Math.max(0, stride) * 0.08;
    parts.rightFoot.position.y += Math.max(0, counterStride) * 0.08;
  }

  function markCharacter(character) {
    var id = 'character-' + String(characters.length + 1).padStart(2, '0');
    character.name = id;
    character.userData.assetRoot = character;
    character.userData.assetType = 'character';
    character.traverse(function(child) {
      child.castShadow = true;
      child.receiveShadow = true;
      child.userData.assetRoot = character;
      child.userData.assetType = 'character';
    });
    characters.push(character);
    return character;
  }

  function createGrid() {
    var THREE = safeThree();
    var grid = new THREE.GridHelper(80, 80, 0x7f8790, 0xc4c9cf);
    grid.rotation.x = Math.PI / 2;
    grid.material.transparent = true;
    grid.material.opacity = 0.5;
    grid.material.depthWrite = false;
    scene.add(grid);

    var originMaterial = new THREE.LineBasicMaterial({
      color: 0x5f6872,
      transparent: true,
      opacity: 0.8
    });
    var xLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(-40, 0, 0.004),
        new THREE.Vector3(40, 0, 0.004)
      ]),
      originMaterial
    );
    var yLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(0, -40, 0.004),
        new THREE.Vector3(0, 40, 0.004)
      ]),
      originMaterial
    );
    scene.add(xLine, yLine);
  }

  function createGround() {
    var THREE = safeThree();
    var shadow = new THREE.Mesh(
      new THREE.PlaneGeometry(80, 80),
      new THREE.ShadowMaterial({
        color: 0x000000,
        opacity: 0.4,
        transparent: true
      })
    );
    shadow.position.z = -0.01;
    shadow.receiveShadow = true;
    shadow.userData.pickable = false;
    scene.add(shadow);
  }

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
      lookDamping: 18
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
    var yaw = 0;
    var pitch = 0.18;
    var targetYaw = 0;
    var targetPitch = 0.18;
    var canvas = options.renderer.domElement;

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
      canvas.focus();
      requestPointerLock();
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
      moveDirection.set(0, 0, 0);
      if (keys.keyw) moveDirection.add(getGroundForward());
      if (keys.keys) moveDirection.addScaledVector(getGroundForward(), -1);
      if (keys.keyd) moveDirection.add(getGroundRight());
      if (keys.keya) moveDirection.addScaledVector(getGroundRight(), -1);
      if (moveDirection.lengthSq() > 0) {
        moveDirection.normalize();
        player.position.addScaledVector(moveDirection, config.moveSpeed * deltaTime);
        player.rotation.z = Math.atan2(moveDirection.y, moveDirection.x) - Math.PI / 2;
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

  function createGameCameraController() {
    var THREE = safeThree();
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
    var moveSpeed = 7;

    function setMoveSpeed(value) {
      var numericSpeed = Number(value);
      if (!Number.isFinite(numericSpeed)) return moveSpeed;
      moveSpeed = THREE.MathUtils.clamp(numericSpeed, 1, 80);
      if (speedInput) speedInput.value = String(Math.round(moveSpeed));
      return moveSpeed;
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

    function getViewportPivot(event) {
      if (selectedCharacter) {
        var box = new THREE.Box3().setFromObject(selectedCharacter);
        if (!box.isEmpty()) return box.getCenter(new THREE.Vector3());
      }
      var point = screenToGround(event.clientX, event.clientY);
      if (point) return point;
      camera.getWorldDirection(forward);
      return camera.position.clone().addScaledVector(forward, 10);
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
      sceneHost.setPointerCapture(event.pointerId);
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
        state.distance = Math.max(0.35, state.distance + dy * state.distance * 0.01);
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
      if (event.button === 0 && !dragState) {
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
      pressKey: function(code) { keys[code] = true; },
      releaseKey: function(event) { delete keys[event.code.toLowerCase()]; },
      setMoveSpeed: setMoveSpeed,
      syncRotationFromCamera: syncRotationFromCamera,
      update: update,
      zoomView: function(event) {
        event.preventDefault();
        camera.getWorldDirection(forward);
        camera.position.addScaledVector(forward, -event.deltaY * 0.02);
      }
    };
  }

  function screenToGround(clientX, clientY) {
    var rect = sceneHost.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    mouse.x = ((clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -(((clientY - rect.top) / rect.height) * 2 - 1);
    raycaster.setFromCamera(mouse, camera);
    return raycaster.ray.intersectPlane(groundPlane, hitPoint) ? hitPoint.clone() : null;
  }

  function placeCharacterAt(point) {
    var character = markCharacter(createCharacter());
    character.position.set(point.x, point.y, 0);
    scene.add(character);
    selectCharacter(character);
    undoStack.push({ type: 'create', character: character });
    setStatus('角色已放置，按 R 或点击运行');
    return character;
  }

  function selectCharacter(character) {
    selectedCharacter = character || null;
    if (selectionBox) {
      selectionBox.object = selectedCharacter || new (safeThree()).Object3D();
      selectionBox.visible = Boolean(selectedCharacter);
    }
    if (transformControls) {
      if (selectedCharacter) transformControls.attach(selectedCharacter);
      else transformControls.detach();
    } else if (selectedCharacter) {
      ensureTransformControls();
    }
  }

  function ensureTransformControls() {
    if (transformControls || transformControlsLoading || !scene || !camera || !renderer) return;
    transformControlsLoading = import('/static/three/TransformControls.js').then(function(module) {
      transformControls = new module.TransformControls(camera, renderer.domElement);
      transformControls.addEventListener("dragging-changed", function(event) {
        if (event.value && cameraControls) cameraControls.clearState();
      });
      transformControls.addEventListener('change', render);
      scene.add(transformControls);
      if (selectedCharacter) transformControls.attach(selectedCharacter);
    }).catch(function() {
      setStatus('TransformControls 未加载');
    });
  }

  function pickCharacter(event) {
    var rect = sceneHost.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -(((event.clientY - rect.top) / rect.height) * 2 - 1);
    raycaster.setFromCamera(mouse, camera);
    var hits = raycaster.intersectObjects(characters, true);
    var character = null;
    for (var i = 0; i < hits.length; i++) {
      var root = hits[i].object.userData.assetRoot;
      if (root && root.userData.assetType === 'character') {
        character = root;
        break;
      }
    }
    selectCharacter(character);
  }

  function deleteSelectedCharacter() {
    if (!selectedCharacter || playMode.isPlaying()) return false;
    var character = selectedCharacter;
    var index = characters.indexOf(character);
    if (index >= 0) characters.splice(index, 1);
    scene.remove(character);
    selectCharacter(null);
    undoStack.push({ type: 'delete', character: character, index: index });
    setStatus('角色已删除');
    return true;
  }

  function undoLastAction() {
    if (playMode.isPlaying()) return false;
    var action = undoStack.pop();
    if (!action) return false;
    if (action.type === 'create') {
      scene.remove(action.character);
      characters = characters.filter(function(item) { return item !== action.character; });
      if (selectedCharacter === action.character) selectCharacter(null);
      return true;
    }
    if (action.type === 'delete') {
      characters.splice(Math.max(0, action.index), 0, action.character);
      scene.add(action.character);
      selectCharacter(action.character);
      return true;
    }
    return false;
  }

  function duplicateSelectedCharacter() {
    if (!selectedCharacter || playMode.isPlaying()) return false;
    var character = placeCharacterAt(selectedCharacter.position.clone().add({ x: 1, y: 1, z: 0 }));
    character.rotation.copy(selectedCharacter.rotation);
    return true;
  }

  function focusSelectedCharacter() {
    var THREE = safeThree();
    if (!selectedCharacter) return false;
    var box = new THREE.Box3().setFromObject(selectedCharacter);
    if (box.isEmpty()) return false;
    var center = box.getCenter(new THREE.Vector3());
    camera.position.copy(center).add(new THREE.Vector3(4, -7, 4));
    camera.lookAt(center);
    cameraControls.syncRotationFromCamera();
    return true;
  }

  function getPlayableCharacter() {
    return selectedCharacter || characters[0] || null;
  }

  function toggleRun() {
    if (!playMode) return;
    if (playMode.isPlaying()) {
      playMode.exit();
      return;
    }
    if (!playMode.enter(getPlayableCharacter())) {
      setStatus('先拖入一个角色');
    }
  }

  function syncRunState() {
    var playing = playMode && playMode.isPlaying();
    if (runButton) {
      runButton.classList.toggle('is-active', playing);
      runButton.setAttribute('aria-pressed', playing ? 'true' : 'false');
      if (runLabel) runLabel.textContent = playing ? '停止' : '运行';
    }
    setStatus(playing ? 'WASD 移动，鼠标控制方向，Esc 停止' : '拖入角色后点击运行');
  }

  function updateDragPreview(clientX, clientY) {
    if (!dragPreview) return;
    dragPreview.style.left = clientX + 'px';
    dragPreview.style.top = clientY + 'px';
  }

  function beginAssetDrag(event) {
    var button = event.target.closest('[data-game-asset="character"]');
    if (!button || event.button !== 0 || playMode.isPlaying()) return;
    event.preventDefault();
    dragState = {
      pointerId: event.pointerId,
      source: button
    };
    try {
      button.setPointerCapture(event.pointerId);
    } catch (e) {}
    dragPreview.hidden = false;
    updateDragPreview(event.clientX, event.clientY);
  }

  function moveAssetDrag(event) {
    if (!dragState) return false;
    event.preventDefault();
    updateDragPreview(event.clientX, event.clientY);
    return true;
  }

  function endAssetDrag(event) {
    if (!dragState) return;
    event.preventDefault();
    try {
      if (dragState.source.hasPointerCapture(dragState.pointerId)) {
        dragState.source.releasePointerCapture(dragState.pointerId);
      }
    } catch (e) {}
    var point = screenToGround(event.clientX, event.clientY);
    if (point) placeCharacterAt(point);
    dragPreview.hidden = true;
    dragState = null;
  }

  function handleGameShortcut(event) {
    if (!active || !initialized) return;
    if (event.target && /^(input|textarea|select)$/i.test(event.target.tagName)) return;
    if (playMode.handleKeyDown(event)) return;

    var code = event.code.toLowerCase();
    if (code === 'keyr' || code === 'space') {
      event.preventDefault();
      toggleRun();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && code === 'keyz') {
      event.preventDefault();
      undoLastAction();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && code === 'keyd') {
      event.preventDefault();
      duplicateSelectedCharacter();
      return;
    }
    if ((code === 'delete' || code === 'backspace') && deleteSelectedCharacter()) {
      event.preventDefault();
      return;
    }
    if (code === 'keyf' && focusSelectedCharacter()) {
      event.preventDefault();
      return;
    }
    cameraControls.pressKey(code);
  }

  function handleKeyUp(event) {
    if (!active || !initialized) return;
    if (playMode.handleKeyUp(event)) return;
    cameraControls.releaseKey(event);
  }

  function render() {
    if (!renderer) return;
    if (selectionBox && selectedCharacter) selectionBox.update();
    renderer.render(scene, camera);
  }

  function tick() {
    if (!active) return;
    var deltaTime = Math.min(clock.getDelta(), 0.05);
    playMode.update(deltaTime);
    cameraControls.update(deltaTime);
    render();
    rafId = requestAnimationFrame(tick);
  }

  function resize() {
    if (!initialized || !renderer || !sceneHost) return;
    var rect = sceneHost.getBoundingClientRect();
    var width = Math.max(1, Math.floor(rect.width));
    var height = Math.max(1, Math.floor(rect.height));
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    render();
  }

  function bindInput() {
    var toolbar = document.getElementById('game-toolbar');
    if (toolbar) toolbar.addEventListener('pointerdown', beginAssetDrag);
    window.addEventListener('pointermove', function(event) {
      if (playMode.handlePointerMove(event)) return;
      if (moveAssetDrag(event)) return;
      cameraControls.handlePointerMove(event);
    });
    window.addEventListener('pointerup', function(event) {
      endAssetDrag(event);
      cameraControls.handlePointerUp(event);
    });
    window.addEventListener('pointercancel', endAssetDrag);
    window.addEventListener('keydown', handleGameShortcut);
    window.addEventListener('keyup', handleKeyUp);
    window.addEventListener('blur', function() {
      if (playMode) playMode.clearInput();
      if (cameraControls) cameraControls.clearState();
    });
    window.addEventListener('resize', resize);
    sceneHost.addEventListener('pointerdown', function(event) {
      if (playMode.handlePointerDown(event)) return;
      cameraControls.handlePointerDown(event);
    });
    sceneHost.addEventListener('wheel', function(event) {
      if (!playMode.isPlaying()) cameraControls.zoomView(event);
    }, { passive: false });
    sceneHost.addEventListener('contextmenu', function(event) {
      event.preventDefault();
    });
    if (runButton) runButton.addEventListener('click', toggleRun);
    if (speedInput) {
      speedInput.addEventListener('input', function() {
        cameraControls.setMoveSpeed(speedInput.value);
      });
      speedInput.addEventListener('change', function() {
        cameraControls.setMoveSpeed(speedInput.value);
      });
    }
  }

  function initGameWorkbench() {
    var THREE = safeThree();
    if (initialized || !THREE) return;
    sceneHost = document.getElementById('game-scene-host');
    dragPreview = document.getElementById('game-drag-preview');
    runButton = document.getElementById('game-run-button');
    runLabel = document.getElementById('game-run-label');
    speedInput = document.getElementById('game-speed-input');
    statusText = document.getElementById('game-status');
    if (!sceneHost) return;

    if (THREE.ColorManagement && 'legacyMode' in THREE.ColorManagement) {
      THREE.ColorManagement.legacyMode = false;
    }
    THREE.Object3D.DEFAULT_UP.set(0, 0, 1);
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0xffffff);
    camera = new THREE.PerspectiveCamera(50, 1, 0.1, 2000);
    camera.up.set(0, 0, 1);
    camera.position.set(10, -16, 8);
    camera.lookAt(0, 0, 0);
    renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.BasicShadowMap;
    if ('outputColorSpace' in renderer) renderer.outputColorSpace = THREE.SRGBColorSpace;
    else renderer.outputEncoding = THREE.sRGBEncoding;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    renderer.domElement.tabIndex = 0;
    sceneHost.appendChild(renderer.domElement);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x8a9bb0, 0.9));
    var sun = new THREE.DirectionalLight(0xffffff, 2.0);
    sun.position.set(8, 14, 10);
    sun.castShadow = true;
    sun.shadow.mapSize.set(4096, 4096);
    sun.shadow.camera.near = 0.5;
    sun.shadow.camera.far = 400;
    sun.shadow.camera.left = -60;
    sun.shadow.camera.right = 60;
    sun.shadow.camera.top = 60;
    sun.shadow.camera.bottom = -60;
    sun.shadow.bias = -0.00015;
    sun.shadow.normalBias = 0.03;
    sun.shadow.radius = 0;
    scene.add(sun, sun.target);
    createGround();
    createGrid();

    raycaster = new THREE.Raycaster();
    mouse = new THREE.Vector2();
    groundPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
    hitPoint = new THREE.Vector3();
    selectionBox = new THREE.BoxHelper(new THREE.Object3D(), 0xffc400);
    selectionBox.visible = false;
    selectionBox.material.depthTest = false;
    scene.add(selectionBox);
    clock = new THREE.Clock();
    playMode = createPlayModeController({
      camera: camera,
      renderer: renderer,
      onChange: syncRunState
    });
    cameraControls = createGameCameraController();
    if (speedInput) cameraControls.setMoveSpeed(speedInput.value);
    cameraControls.syncRotationFromCamera();
    bindInput();
    initialized = true;
    resize();
    setStatus('拖入角色后点击运行');
  }

  function setActive(nextActive) {
    active = Boolean(nextActive);
    if (!active) {
      if (playMode) playMode.exit();
      if (rafId) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
      return;
    }
    initGameWorkbench();
    resize();
    if (!rafId) {
      clock.getDelta();
      rafId = requestAnimationFrame(tick);
    }
  }

  window.VC_GAME_WORKBENCH = {
    init: initGameWorkbench,
    resize: resize,
    setActive: setActive
  };
})();
