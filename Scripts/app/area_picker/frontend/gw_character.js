// Domain: game-workbench / character
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
  var gltfLoaderPromise = null;

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
    var material = new THREE.MeshToonMaterial({
      color: color,
      gradientMap: getToonGradientMap()
    });
    if (GW.state.csm) GW.state.csm.setupMaterial(material);
    return material;
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
    var material = createOutlineMaterial(thickness);
    var outline = new THREE.Mesh(geometry, material);
    outline.userData.pickable = false;
    outline.userData.outline = true;
    outline.userData.outlineBaseColor = material.uniforms.outlineColor.value.clone();
    outline.userData.outlineBaseThickness = material.uniforms.outlineThickness.value;
    return outline;
  }

  function setOutlineSelected(outline, selected) {
    var uniforms = outline.material && outline.material.uniforms;
    if (!uniforms || !uniforms.outlineColor || !uniforms.outlineThickness) return;
    uniforms.outlineColor.value.set(selected ? 0xffc400 : outline.userData.outlineBaseColor);
    uniforms.outlineThickness.value = selected ? 0.026 : outline.userData.outlineBaseThickness;
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

  function loadGLTF(url) {
    if (!gltfLoaderPromise) {
      gltfLoaderPromise = import("/static/three/GLTFLoader.js").then(function(mod) {
        return new mod.GLTFLoader();
      });
    }
    return gltfLoaderPromise.then(function(loader) {
      return new Promise(function(resolve, reject) {
        loader.load(url, resolve, undefined, reject);
      });
    });
  }

  function markCharacterChild(character, node) {
    if (!node.userData) node.userData = {};
    node.userData.assetRoot = character;
    node.userData.assetType = 'character';
    if (node.isMesh || node.isSkinnedMesh) {
      node.castShadow = true;
      node.receiveShadow = true;
    }
  }

  // Fits the model to ROBOT_TARGET_HEIGHT and anchors its feet at the
  // character group's own local origin (0,0,0) -- so character.position (the
  // editor gizmo, ground snapping, camera math) always means "where the feet
  // touch the ground", the standard convention for a character controller.
  function fitRobotAvatar(model) {
    var THREE = safeThree();
    if (!THREE || !model) return;
    var box = new THREE.Box3();
    model.updateMatrixWorld(true);
    box.setFromObject(model);
    var height = box.max.z - box.min.z;
    if (height > 0.001) {
      model.scale.multiplyScalar(ROBOT_TARGET_HEIGHT / height);
      model.updateMatrixWorld(true);
      box.setFromObject(model);
    }
    model.position.z -= box.min.z;
    model.updateMatrixWorld(true);
  }

  function createLoadingProxy() {
    var THREE = safeThree();
    var geometry = THREE.CapsuleGeometry
      ? new THREE.CapsuleGeometry(0.22, 0.78, 5, 12)
      : new THREE.CylinderGeometry(0.22, 0.22, 1.22, 12);
    // Capsule total height is 0.78 + 2*0.22 = 1.22; positioning its center at
    // half that height puts its bottom at the group's local origin (feet),
    // matching fitRobotAvatar's convention for the real avatar.
    var proxy = createCharacterPart({
      name: 'player-robot-loading-proxy',
      geometry: geometry,
      material: createCharacterMaterial(0x76879a),
      position: [0, 0, 0.61],
      rotation: [Math.PI / 2, 0, 0],
      outline: 0.01
    });
    proxy.userData.loadingProxy = true;
    return proxy;
  }

  function createRobotActions(character, model, animations) {
    var THREE = safeThree();
    var mixer = new THREE.AnimationMixer(model);
    var actions = {};
    (animations || []).forEach(function(clip) {
      actions[clip.name] = mixer.clipAction(clip);
    });
    var runningActionName = actions[ROBOT_ANIMATIONS.run] ? ROBOT_ANIMATIONS.run : ROBOT_ANIMATIONS.walk;
    var locomotionActionName = actions[ROBOT_ANIMATIONS.walk] ? ROBOT_ANIMATIONS.walk : runningActionName;
    var jumpAction = actions[ROBOT_ANIMATIONS.jump];
    if (jumpAction) {
      jumpAction.loop = THREE.LoopOnce;
      jumpAction.clampWhenFinished = true;
    }
    character.userData.animationMixer = mixer;
    character.userData.robotAvatar = {
      model: model,
      actions: actions,
      activeAction: null,
      locomotionActionName: locomotionActionName,
      loaded: true
    };
    if (actions[ROBOT_ANIMATIONS.idle]) playRobotAction(character, ROBOT_ANIMATIONS.idle, 0);
    return actions;
  }

  function playRobotAction(character, actionName, fadeDuration) {
    var robot = character && character.userData.robotAvatar;
    if (!robot || !robot.actions) return;
    var next = robot.actions[actionName];
    if (!next || robot.activeAction === next) return;
    var previous = robot.activeAction;
    robot.activeAction = next;
    if (previous) previous.fadeOut(fadeDuration);
    next
      .reset()
      .setEffectiveTimeScale(1)
      .setEffectiveWeight(1)
      .fadeIn(fadeDuration)
      .play();
  }

  function attachRobotAvatar(character, gltf) {
    var model = gltf.scene;
    var placeholder = character.userData.loadingProxy;
    model.name = 'player-ueperson';
    model.rotation.x = Math.PI / 2;
    model.rotation.y = Math.PI;
    model.traverse(function(node) {
      markCharacterChild(character, node);
    });
    // Fit before parenting: fitRobotAvatar reads a world-space bounding box,
    // and while unparented that's the same as model-local space. Fitting
    // after character.add(model) would bake the character's own (possibly
    // large, e.g. real terrain elevation) position into the box, corrupting
    // model.position.z and detaching the visual mesh from the group's origin.
    fitRobotAvatar(model);
    character.add(model);
    if (placeholder) {
      character.remove(placeholder);
      character.userData.loadingProxy = null;
    }
    createRobotActions(character, model, gltf.animations);
  }

  function handleRobotLoadError(error) {
    var message = error && (error.message || error.statusText) ? (error.message || error.statusText) : String(error || '未知错误');
    if (GW.setStatus) GW.setStatus('角色模型加载失败: ' + message);
  }

  function createCharacter() {
    var THREE = safeThree();
    var character = new THREE.Group();
    var placeholder = createLoadingProxy();
    character.userData.avatarSource = 'hh-hang/three-player-controller UEPerson';
    // 0: character.position is the feet/ground-contact point (see
    // fitRobotAvatar). Kept as an explicit field, not just an implied 0,
    // because ground snapping/camera math (game_workbench.js, gw_play.js)
    // read it uniformly regardless of which avatar's origin convention.
    character.userData.groundOffset = 0;
    character.userData.loadingProxy = placeholder;
    character.add(placeholder);
    loadGLTF(ROBOT_AVATAR_URL)
      .then(function(gltf) { attachRobotAvatar(character, gltf); })
      .catch(handleRobotLoadError);
    resetCharacterMotion(character);
    return character;
  }

  function resetPartMotion(part) {
    if (!part || !part.userData.restPosition || !part.userData.restRotation) return;
    part.position.copy(part.userData.restPosition);
    part.rotation.copy(part.userData.restRotation);
  }

  function resetCharacterMotion(character) {
    if (character && character.userData && character.userData.robotAvatar) {
      playRobotAction(character, ROBOT_ANIMATIONS.idle, 0.12);
      return;
    }
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
    if (character && character.userData && character.userData.animationMixer) {
      var movingRobot = moveDirection && moveDirection.lengthSq() > 0.0001;
      var robot = character.userData.robotAvatar || {};
      playRobotAction(character, movingRobot ? robot.locomotionActionName : ROBOT_ANIMATIONS.idle, 0.16);
      character.userData.animationMixer.update(deltaTime);
      return;
    }
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

  GW.getToonGradientMap = getToonGradientMap;
  GW.createToonGrayMaterial = createToonGrayMaterial;
  GW.createCharacterMaterial = createCharacterMaterial;
  GW.createOutlineMaterial = createOutlineMaterial;
  GW.createOutlineMesh = createOutlineMesh;
  GW.setOutlineSelected = setOutlineSelected;
  GW.createCharacterPart = createCharacterPart;
  GW.createCharacter = createCharacter;
  GW.resetPartMotion = resetPartMotion;
  GW.resetCharacterMotion = resetCharacterMotion;
  GW.updateCharacterMotion = updateCharacterMotion;
})();
