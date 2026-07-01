// Domain: viewport-grid
// Owns: Shared shader-based Z-up reference grid for Three.js viewport surfaces.
// AI handoff: For editor/Houdini grid rendering issues, inspect VC_VIEWPORT_GRID consumers first.
(function() {
  'use strict';

  var DEFAULTS = {
    name: 'viewport-grid',
    planeZ: 0,
    fadeStart: 700,
    fadeEnd: 1850,
    lodPixels: 64,
    minorColor: 0xb8c0c8,
    majorColor: 0xe3e8ee,
    axisXColor: 0xff5a54,
    axisYColor: 0x56c77a,
    axisZColor: 0x5f8cff,
    minorAlpha: 0.28,
    majorAlpha: 0.62,
    axisAlpha: 0.9,
    axisInnerPx: 1.0,
    axisOuterPx: 2.6,
    renderOrder: -10,
    depthTest: true,
    showZAxis: false,
    axisLength: 4,
    zAxisOpacity: 0.75
  };

  function copyOptions(opts) {
    var result = {};
    Object.keys(DEFAULTS).forEach(function(key) {
      result[key] = DEFAULTS[key];
    });
    opts = opts || {};
    Object.keys(opts).forEach(function(key) {
      if (opts[key] !== undefined) result[key] = opts[key];
    });
    return result;
  }

  function createFullscreenTriangle(THREE) {
    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute([
      -1, -1, 0,
      3, -1, 0,
      -1, 3, 0
    ], 3));
    return geometry;
  }

  function createGridMaterial(THREE, options) {
    return new THREE.ShaderMaterial({
      uniforms: {
        uViewProjection: { value: new THREE.Matrix4() },
        uViewProjectionInverse: { value: new THREE.Matrix4() },
        uCameraPosition: { value: new THREE.Vector3() },
        uPlaneZ: { value: options.planeZ },
        uMinorColor: { value: new THREE.Color(options.minorColor) },
        uMajorColor: { value: new THREE.Color(options.majorColor) },
        uAxisXColor: { value: new THREE.Color(options.axisXColor) },
        uAxisYColor: { value: new THREE.Color(options.axisYColor) },
        uAxisZColor: { value: new THREE.Color(options.axisZColor) },
        uFadeStart: { value: options.fadeStart },
        uFadeEnd: { value: options.fadeEnd },
        uLodPixels: { value: options.lodPixels },
        uMinorAlpha: { value: options.minorAlpha },
        uMajorAlpha: { value: options.majorAlpha },
        uAxisAlpha: { value: options.axisAlpha },
        uAxisInnerPx: { value: options.axisInnerPx },
        uAxisOuterPx: { value: options.axisOuterPx }
      },
      transparent: true,
      depthWrite: false,
      depthTest: !!options.depthTest,
      extensions: {
        derivatives: true,
        fragDepth: true
      },
      vertexShader: [
        'varying vec2 vClipPosition;',
        'void main() {',
        '  vClipPosition = position.xy;',
        '  gl_Position = vec4(position.xy, 0.0, 1.0);',
        '}'
      ].join('\n'),
      fragmentShader: [
        'uniform mat4 uViewProjection;',
        'uniform mat4 uViewProjectionInverse;',
        'uniform vec3 uCameraPosition;',
        'uniform float uPlaneZ;',
        'uniform vec3 uMinorColor;',
        'uniform vec3 uMajorColor;',
        'uniform vec3 uAxisXColor;',
        'uniform vec3 uAxisYColor;',
        'uniform vec3 uAxisZColor;',
        'uniform float uFadeStart;',
        'uniform float uFadeEnd;',
        'uniform float uLodPixels;',
        'uniform float uMinorAlpha;',
        'uniform float uMajorAlpha;',
        'uniform float uAxisAlpha;',
        'uniform float uAxisInnerPx;',
        'uniform float uAxisOuterPx;',
        'varying vec2 vClipPosition;',
        'float log10(float value) {',
        '  return log(value) / 2.302585093;',
        '}',
        'vec3 unprojectPoint(float z) {',
        '  vec4 world = uViewProjectionInverse * vec4(vClipPosition, z, 1.0);',
        '  return world.xyz / max(world.w, 0.000001);',
        '}',
        'float gridLine(vec2 worldPosition, float cellSize, float widthPx) {',
        '  vec2 coord = worldPosition / cellSize;',
        '  vec2 g = abs(fract(coord - 0.5) - 0.5) / max(fwidth(coord) * widthPx, vec2(0.000001));',
        '  return 1.0 - min(min(g.x, g.y), 1.0);',
        '}',
        'void main() {',
        '  vec3 nearPoint = unprojectPoint(-1.0);',
        '  vec3 farPoint = unprojectPoint(1.0);',
        '  vec3 rayDirection = farPoint - nearPoint;',
        '  if (abs(rayDirection.z) < 0.000001) discard;',
        '  float rayT = (uPlaneZ - nearPoint.z) / rayDirection.z;',
        '  if (rayT < 0.0) discard;',
        '  vec3 worldPosition = nearPoint + rayDirection * rayT;',
        '  vec2 world = worldPosition.xy;',
        '  float worldPerPixel = max(max(fwidth(world.x), fwidth(world.y)), 0.000001);',
        '  float lod = log10(worldPerPixel) + log10(uLodPixels);',
        '  float lodLevel = floor(lod);',
        '  float lodBlend = smoothstep(0.15, 0.95, fract(lod));',
        '  float fineCell = pow(10.0, lodLevel);',
        '  float majorCell = fineCell * 10.0;',
        '  float nextMajorCell = majorCell * 10.0;',
        '  float minorLine = gridLine(world, fineCell, 1.0) * (1.0 - lodBlend);',
        '  float majorLine = gridLine(world, majorCell, 1.35);',
        '  float nextMajorLine = gridLine(world, nextMajorCell, 1.5) * lodBlend;',
        '  float minorAlpha = minorLine * uMinorAlpha;',
        '  float majorAlpha = max(majorLine * mix(uMajorAlpha, uMinorAlpha, lodBlend), nextMajorLine * uMajorAlpha);',
        '  float alpha = max(minorAlpha, majorAlpha);',
        '  vec3 color = mix(uMinorColor, uMajorColor, step(minorAlpha, majorAlpha));',
        '  float xAxisPx = abs(world.y) / max(fwidth(world.y), 0.000001);',
        '  float yAxisPx = abs(world.x) / max(fwidth(world.x), 0.000001);',
        '  float xAxis = 1.0 - smoothstep(uAxisInnerPx, uAxisOuterPx, xAxisPx);',
        '  float yAxis = 1.0 - smoothstep(uAxisInnerPx, uAxisOuterPx, yAxisPx);',
        '  float zOrigin = min(xAxis, yAxis);',
        '  float axisWeight = max(xAxis, yAxis);',
        '  vec3 axisColor = (uAxisXColor * xAxis + uAxisYColor * yAxis) / max(xAxis + yAxis, 0.000001);',
        '  axisColor = mix(axisColor, uAxisZColor, zOrigin);',
        '  color = mix(color, axisColor, clamp(axisWeight + zOrigin, 0.0, 1.0));',
        '  alpha = max(alpha, axisWeight * uAxisAlpha);',
        '  float cameraDistance = distance(uCameraPosition, worldPosition);',
        '  float distanceFade = 1.0 - smoothstep(uFadeStart, uFadeEnd, cameraDistance);',
        '  vec3 viewDir = normalize(uCameraPosition - worldPosition);',
        '  float grazingFade = smoothstep(0.035, 0.22, abs(dot(viewDir, vec3(0.0, 0.0, 1.0))));',
        '  alpha *= distanceFade * grazingFade;',
        '  if (alpha <= 0.002) discard;',
        '  vec4 clipPosition = uViewProjection * vec4(worldPosition, 1.0);',
        '  gl_FragDepthEXT = (clipPosition.z / clipPosition.w) * 0.5 + 0.5;',
        '  gl_FragColor = vec4(color, alpha);',
        '}'
      ].join('\n')
    });
  }

  function setColor(uniform, value) {
    if (value === undefined || value === null) return;
    uniform.value.set(value);
  }

  function setUniform(uniform, value) {
    if (value === undefined || value === null) return;
    uniform.value = value;
  }

  function updateMatrixUniforms(handle, camera) {
    camera.updateMatrixWorld(true);
    handle.viewProjection.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    handle.viewProjectionInverse.copy(handle.viewProjection);
    if (handle.viewProjectionInverse.invert) handle.viewProjectionInverse.invert();
    else handle.viewProjectionInverse.getInverse(handle.viewProjection);
    handle.material.uniforms.uViewProjection.value.copy(handle.viewProjection);
    handle.material.uniforms.uViewProjectionInverse.value.copy(handle.viewProjectionInverse);
    handle.material.uniforms.uCameraPosition.value.copy(camera.position);
    // Grow the distance-fade window with viewing distance so the grid never fully
    // discards when zoomed out; configured fadeStart/fadeEnd act as the floor.
    // Full 3D distance to the plane origin, not just height above it -- height
    // alone collapses toward zero when orbiting down to a horizontal view even
    // though the camera's actual distance from the grid content is unchanged.
    var baseEnd = handle.options.fadeEnd;
    var baseStart = handle.options.fadeStart;
    var dx = camera.position.x;
    var dy = camera.position.y;
    var dz = camera.position.z - handle.options.planeZ;
    var planeDist = Math.sqrt(dx * dx + dy * dy + dz * dz);
    var fadeEnd = Math.max(baseEnd, planeDist * 3.5);
    handle.material.uniforms.uFadeEnd.value = fadeEnd;
    handle.material.uniforms.uFadeStart.value = fadeEnd * (baseStart / Math.max(baseEnd, 0.000001));
  }

  function createZAxis(handle) {
    var THREE = window.THREE;
    var positions = new Float32Array(6);
    var colors = new Float32Array([
      0.36, 0.52, 0.82,
      0.36, 0.52, 0.82
    ]);
    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    var material = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: handle.options.zAxisOpacity,
      depthWrite: false,
      depthTest: true
    });
    var axis = new THREE.LineSegments(geometry, material);
    axis.name = handle.options.name + '-z-axis';
    axis.frustumCulled = false;
    axis.renderOrder = handle.options.renderOrder + 1;
    axis.userData.pickable = false;
    handle.scene.add(axis);
    handle.zAxis = axis;
    handle.zAxisPositions = positions;
  }

  function updateZAxis(handle) {
    if (!handle.options.showZAxis) {
      if (handle.zAxis) {
        handle.scene.remove(handle.zAxis);
        handle.zAxis.geometry.dispose();
        handle.zAxis.material.dispose();
        handle.zAxis = null;
        handle.zAxisPositions = null;
      }
      return;
    }
    if (!handle.zAxis) createZAxis(handle);
    var z = handle.options.planeZ;
    var length = Math.max(0.001, handle.options.axisLength);
    var positions = handle.zAxisPositions;
    positions[0] = 0;
    positions[1] = 0;
    positions[2] = z;
    positions[3] = 0;
    positions[4] = 0;
    positions[5] = z + length;
    handle.zAxis.geometry.attributes.position.needsUpdate = true;
    handle.zAxis.geometry.computeBoundingSphere();
    handle.zAxis.material.opacity = handle.options.zAxisOpacity;
    handle.zAxis.renderOrder = handle.options.renderOrder + 1;
  }

  function applyOptions(handle, opts) {
    var options = handle.options;
    opts = opts || {};
    Object.keys(opts).forEach(function(key) {
      if (opts[key] !== undefined) options[key] = opts[key];
    });
    var uniforms = handle.material.uniforms;
    setUniform(uniforms.uPlaneZ, options.planeZ);
    setUniform(uniforms.uFadeStart, options.fadeStart);
    setUniform(uniforms.uFadeEnd, options.fadeEnd);
    setUniform(uniforms.uLodPixels, options.lodPixels);
    setUniform(uniforms.uMinorAlpha, options.minorAlpha);
    setUniform(uniforms.uMajorAlpha, options.majorAlpha);
    setUniform(uniforms.uAxisAlpha, options.axisAlpha);
    setUniform(uniforms.uAxisInnerPx, options.axisInnerPx);
    setUniform(uniforms.uAxisOuterPx, options.axisOuterPx);
    setColor(uniforms.uMinorColor, options.minorColor);
    setColor(uniforms.uMajorColor, options.majorColor);
    setColor(uniforms.uAxisXColor, options.axisXColor);
    setColor(uniforms.uAxisYColor, options.axisYColor);
    setColor(uniforms.uAxisZColor, options.axisZColor);
    handle.mesh.renderOrder = options.renderOrder;
    handle.material.depthTest = !!options.depthTest;
    updateZAxis(handle);
  }

  function createViewportGrid(scene, camera, opts) {
    var THREE = window.THREE;
    if (!THREE || !scene || !camera) return null;
    var options = copyOptions(opts);
    var material = createGridMaterial(THREE, options);
    var mesh = new THREE.Mesh(createFullscreenTriangle(THREE), material);
    mesh.name = options.name + '-fullscreen-triangle';
    mesh.frustumCulled = false;
    mesh.renderOrder = options.renderOrder;
    mesh.userData.pickable = false;
    scene.add(mesh);
    var handle = {
      scene: scene,
      mesh: mesh,
      material: material,
      options: options,
      viewProjection: new THREE.Matrix4(),
      viewProjectionInverse: new THREE.Matrix4(),
      zAxis: null,
      zAxisPositions: null
    };
    applyOptions(handle, options);
    updateViewportGrid(handle, camera);
    return handle;
  }

  function updateViewportGrid(handle, camera) {
    if (!handle || !handle.mesh || !camera) return;
    updateMatrixUniforms(handle, camera);
  }

  function setViewportGridOptions(handle, opts) {
    if (!handle || !handle.material) return;
    applyOptions(handle, opts || {});
  }

  function disposeViewportGrid(handle) {
    if (!handle) return;
    if (handle.scene && handle.mesh) handle.scene.remove(handle.mesh);
    if (handle.mesh) {
      handle.mesh.geometry.dispose();
      handle.mesh.material.dispose();
    }
    if (handle.zAxis) {
      if (handle.scene) handle.scene.remove(handle.zAxis);
      handle.zAxis.geometry.dispose();
      handle.zAxis.material.dispose();
    }
    handle.mesh = null;
    handle.material = null;
    handle.zAxis = null;
    handle.zAxisPositions = null;
  }

  window.VC_VIEWPORT_GRID = {
    create: createViewportGrid,
    update: updateViewportGrid,
    setOptions: setViewportGridOptions,
    dispose: disposeViewportGrid
  };
})();
