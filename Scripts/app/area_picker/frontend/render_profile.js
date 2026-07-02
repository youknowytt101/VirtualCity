// Domain: render-profile
// Owns: Shared Three.js renderer, lighting, shadow quality, and PMREM environment setup.
// AI handoff: For editor/preview lighting drift, update this module before touching consumers.
(function() {
  'use strict';

  var SHADOW_QUALITY = {
    low: { mapSize: 1024, radius: 0.8 },
    medium: { mapSize: 2048, radius: 1.0 },
    high: { mapSize: 4096, radius: 1.2 },
    cinematic: { mapSize: 4096, radius: 1.8 }
  };

  var DEFAULTS = {
    pixelRatioCap: 2,
    toneMappingExposure: 1.0,
    shadowQuality: 'high',
    includeAmbient: true,
    ambientColor: 0xb4b8bc,
    ambientIntensity: 0.5,
    hemisphereSkyColor: 0xffffff,
    hemisphereGroundColor: 0x8a9bb0,
    hemisphereIntensity: 0.9,
    sunColor: 0xffffff,
    sunIntensity: 2.0,
    sunPosition: [8, 14, 10],
    environmentIntensity: 1.0,
    environmentBlur: 0.04
  };

  function copyOptions(options) {
    var result = {};
    Object.keys(DEFAULTS).forEach(function(key) {
      result[key] = DEFAULTS[key];
    });
    options = options || {};
    Object.keys(options).forEach(function(key) {
      if (options[key] !== undefined) result[key] = options[key];
    });
    return result;
  }

  function shadowQuality(name) {
    return SHADOW_QUALITY[name] || SHADOW_QUALITY.high;
  }

  function configureColorManagement(THREE) {
    if (THREE && THREE.ColorManagement && 'legacyMode' in THREE.ColorManagement) {
      THREE.ColorManagement.legacyMode = false;
    }
  }

  function createRenderer(THREE, options) {
    options = copyOptions(options);
    var renderer = new THREE.WebGLRenderer({
      antialias: options.antialias !== false,
      preserveDrawingBuffer: !!options.preserveDrawingBuffer
    });
    applyRendererProfile(THREE, renderer, options);
    return renderer;
  }

  function applyRendererProfile(THREE, renderer, options) {
    options = copyOptions(options);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, options.pixelRatioCap));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    if ('outputColorSpace' in renderer) renderer.outputColorSpace = THREE.SRGBColorSpace;
    else renderer.outputEncoding = THREE.sRGBEncoding;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = options.toneMappingExposure;
  }

  // three.js's WebGLShadowMap only creates a light's shadow.map render target
  // once, lazily, on first render (see its `if (shadow.map === null)` check)
  // -- it never notices a later shadow.mapSize change and never recreates
  // the target. So changing mapSize at runtime needs the stale map disposed
  // here too, or the resolution change silently has no effect.
  function setShadowMapSize(light, size) {
    if (!light || !light.shadow) return;
    if (light.shadow.mapSize.width === size && light.shadow.mapSize.height === size && light.shadow.map) return;
    light.shadow.mapSize.set(size, size);
    if (light.shadow.map) {
      light.shadow.map.dispose();
      light.shadow.map = null;
    }
  }

  function applyShadowQuality(THREE, light, qualityName) {
    if (!light || !light.shadow) return;
    var quality = shadowQuality(qualityName);
    light.castShadow = true;
    setShadowMapSize(light, quality.mapSize);
    light.shadow.camera.near = 0.5;
    light.shadow.camera.far = 80;
    light.shadow.camera.left = -40;
    light.shadow.camera.right = 40;
    light.shadow.camera.top = 40;
    light.shadow.camera.bottom = -40;
    light.shadow.bias = -0.00015;
    light.shadow.normalBias = 0.03;
    light.shadow.radius = quality.radius;
    light.shadow.camera.updateProjectionMatrix();
  }

  function createAmbientLighting(THREE, scene, profile) {
    var hemi = new THREE.HemisphereLight(
      profile.hemisphereSkyColor,
      profile.hemisphereGroundColor,
      profile.hemisphereIntensity
    );
    scene.add(hemi);

    var ambient = null;
    if (profile.includeAmbient) {
      ambient = new THREE.AmbientLight(profile.ambientColor, profile.ambientIntensity);
      scene.add(ambient);
    }
    return { hemisphere: hemi, ambient: ambient };
  }

  function createDefaultLighting(THREE, scene, options) {
    var profile = copyOptions(options);
    var lighting = createAmbientLighting(THREE, scene, profile);

    var sun = new THREE.DirectionalLight(profile.sunColor, profile.sunIntensity);
    sun.position.fromArray(profile.sunPosition);
    applyShadowQuality(THREE, sun, profile.shadowQuality);
    scene.add(sun, sun.target);
    return { hemisphere: lighting.hemisphere, ambient: lighting.ambient, sun: sun };
  }

  // Single directional "sun" + one shadow map can't be both sharp near the
  // camera and cover the whole scene -- its frustum has to pick one scale.
  // Cascaded shadow maps (CSM) split the camera's view frustum into a few
  // depth slices and give each its own shadow map, so nearby geometry stays
  // crisp while far geometry still gets (coarser) shadows, automatically
  // following whatever the camera is looking at. Uses three.js's own CSM
  // addon (vendored unmodified at Scripts/web_assets/three/csm/, matching
  // this project's r149 three.js revision) rather than this module's plain
  // single-sun path -- game_workbench.js's play/editor camera moves
  // continuously and can drive CSM's per-frame update(); houdini_preview.js
  // has no such loop, so it stays on createDefaultLighting unchanged.
  //
  // lightDirection is expressed as "the direction light travels" (CSM's own
  // convention), matching this app's established sun angle (mostly downward,
  // slightly toward +X/+Y) but pointing the opposite way from sunPosition's
  // "direction toward the light" convention above.
  function createCascadedShadowLighting(THREE, scene, camera, options) {
    var profile = copyOptions(options);
    var lighting = createAmbientLighting(THREE, scene, profile);

    return import("/static/three/csm/CSM.js").then(function(mod) {
      var csm = new mod.CSM({
        camera: camera,
        parent: scene,
        cascades: 3,
        mode: 'practical',
        shadowMapSize: 2048,
        maxFar: 2000,
        lightDirection: new THREE.Vector3(-0.45, -0.35, -1).normalize(),
        lightIntensity: profile.sunIntensity
      });
      // CSM's constructor hardcodes `this.fade = false` and never actually
      // reads a `fade` constructor option (checked directly in the vendored
      // source) -- without this, cascades have a hard edge where one shadow
      // map's coverage stops and the next begins, most visible when rotating
      // the camera. Has to happen before any setupMaterial() calls (which
      // read `this.fade` to decide whether to set the CSM_FADE shader
      // define), so materials created after this always pick it up correctly.
      csm.fade = true;
      tuneCSMShadowBias(csm);
      return { hemisphere: lighting.hemisphere, ambient: lighting.ambient, csm: csm };
    });
  }

  // CSM.js hardcodes one tiny shadow.bias (0.000001) across every cascade
  // and never sets normalBias at all (checked directly in the vendored
  // source's createLights()) -- fine for a single, fixed-scale shadow
  // camera, but this app's cascades span wildly different physical sizes (a
  // near cascade tens of meters wide vs. a far one approaching maxFar). A
  // shared bias is either too small for the coarse far cascades (self-
  // shadowing acne -- most visible on a large flat surface like a building
  // facade facing the camera head-on, where nearly the whole face samples
  // the same depth) or too large for the fine near cascade (shadows
  // detaching from geometry). Scale both to each cascade's own texel size
  // instead, using the same bias/normalBias-to-texel-size ratio this app's
  // old single-sun setup used (applyShadowQuality's -0.00015 / 0.03 at an
  // 80m-wide, 4096-texel frustum), just reapplied per cascade. Call again
  // after any csm.updateFrustums() -- frustum bounds (and so texel size)
  // change with them.
  function tuneCSMShadowBias(csm) {
    if (!csm || !csm.lights) return;
    csm.lights.forEach(function(light) {
      var cam = light.shadow.camera;
      var texelSize = (cam.right - cam.left) / csm.shadowMapSize;
      light.shadow.bias = -texelSize * 0.00768;
      light.shadow.normalBias = texelSize * 1.536;
    });
  }

  function createEnvironmentScene(THREE, options) {
    var profile = copyOptions(options);
    var scene = new THREE.Scene();
    var geometry = new THREE.SphereGeometry(50, 32, 16);
    var material = new THREE.ShaderMaterial({
      side: THREE.BackSide,
      depthWrite: false,
      uniforms: {
        skyColor: { value: new THREE.Color(0xdcecff).multiplyScalar(profile.environmentIntensity) },
        horizonColor: { value: new THREE.Color(0xf4f1e8).multiplyScalar(profile.environmentIntensity) },
        groundColor: { value: new THREE.Color(0x6f7880).multiplyScalar(profile.environmentIntensity) },
        sunColor: { value: new THREE.Color(0xfff1d2).multiplyScalar(profile.environmentIntensity) }
      },
      vertexShader: [
        'varying vec3 vDir;',
        'void main() {',
        '  vDir = normalize(position);',
        '  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);',
        '}'
      ].join('\n'),
      fragmentShader: [
        'varying vec3 vDir;',
        'uniform vec3 skyColor;',
        'uniform vec3 horizonColor;',
        'uniform vec3 groundColor;',
        'uniform vec3 sunColor;',
        'void main() {',
        '  float h = clamp(vDir.z * 0.5 + 0.5, 0.0, 1.0);',
        '  vec3 base = mix(groundColor, skyColor, smoothstep(0.18, 1.0, h));',
        '  base = mix(base, horizonColor, 1.0 - abs(h - 0.52) * 2.0);',
        '  vec3 sunDir = normalize(vec3(0.35, 0.55, 0.76));',
        '  float sun = pow(max(dot(normalize(vDir), sunDir), 0.0), 96.0);',
        '  gl_FragColor = vec4(base + sunColor * sun * 2.0, 1.0);',
        '}'
      ].join('\n')
    });
    scene.add(new THREE.Mesh(geometry, material));
    return {
      scene: scene,
      dispose: function() {
        geometry.dispose();
        material.dispose();
      }
    };
  }

  function applyEnvironment(THREE, renderer, scene, options) {
    if (!THREE || !THREE.PMREMGenerator || !renderer || !scene) return null;
    var profile = copyOptions(options);
    var generator = new THREE.PMREMGenerator(renderer);
    var environmentScene = createEnvironmentScene(THREE, profile);
    var target = generator.fromScene(environmentScene.scene, profile.environmentBlur, 0.1, 100);
    scene.environment = target.texture;
    environmentScene.dispose();
    generator.dispose();
    return {
      texture: target.texture,
      target: target,
      dispose: function() {
        if (scene.environment === target.texture) scene.environment = null;
        target.dispose();
      }
    };
  }

  window.VC_RENDER_PROFILE = {
    createRenderer: createRenderer,
    applyRendererProfile: applyRendererProfile,
    configureColorManagement: configureColorManagement,
    createDefaultLighting: createDefaultLighting,
    createCascadedShadowLighting: createCascadedShadowLighting,
    tuneCSMShadowBias: tuneCSMShadowBias,
    applyEnvironment: applyEnvironment,
    applyShadowQuality: applyShadowQuality,
    setShadowMapSize: setShadowMapSize,
    shadowQuality: shadowQuality
  };
})();
