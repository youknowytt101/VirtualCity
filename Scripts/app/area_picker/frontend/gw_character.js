// Domain: game-workbench / character
// Owns: the procedural stylized avatar (geometry, toon material, outline shader)
//       and its walk/idle motion rig. Pure factories — no shared scene state.
// AI handoff: For avatar look or run-cycle motion, start here; selection/outline
//             highlight wiring stays in game_workbench.js.
(function() {
  'use strict';

  var GW = window.VC_GW || (window.VC_GW = {});
  var safeThree = GW.safeThree;
  var sharedToonGradientMap = null;

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
