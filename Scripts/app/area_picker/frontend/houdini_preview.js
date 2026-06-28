// Small Three.js preview in the Houdini build panel.
// The preview is driven by the explicit houdini_asset.whitebox contract from
// /health, /status, and /events. It never probes Houdini and never triggers an
// export; it only visualizes the latest GLB artifact reported by the server.
(function() {
  'use strict';

  var host = null, msgEl = null;
  var renderer = null, scene = null, camera = null, previewRoot = null;
  var previewSun = null;
  var placeholder = null, model = null, rafId = null;
  var phase = 'idle';       // idle | running | loading | shown | error
  var currentWhitebox = null;
  var shownCacheKey = '';
  var loadSeq = 0;
  var previewYaw = Math.atan2(-1.6, 1.2);
  var previewOrbitRadius = 1.2;
  var previewTargetZ = 0;
  var WHITEBOX_PREVIEW_COLOR = 0xb8b8b8;
  var PREVIEW_SUN_DIRECTION = { x: 0.426, y: 0.721, z: 0.557 };

  function setMsg(text) {
    if (msgEl) msgEl.textContent = text || '';
  }

  function ensureInit() {
    if (renderer) return true;
    var THREE = window.THREE;
    host = document.getElementById('houdini-preview-host');
    if (!THREE || !host) return false;

    msgEl = document.createElement('div');
    msgEl.className = 'houdini-preview-msg';
    host.appendChild(msgEl);
    host.addEventListener('click', function() {
      if (currentWhitebox && currentWhitebox.available) {
        loadWhitebox(currentWhitebox, true);
      }
    });

    if (THREE.ColorManagement && 'legacyMode' in THREE.ColorManagement) {
      THREE.ColorManagement.legacyMode = false;
    }
    THREE.Object3D.DEFAULT_UP.set(0, 0, 1);
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x8f8f8f);
    camera = new THREE.PerspectiveCamera(45, 1, 0.05, 100000);
    camera.up.set(0, 0, 1);
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.BasicShadowMap;
    if ('outputColorSpace' in renderer) renderer.outputColorSpace = THREE.SRGBColorSpace;
    else renderer.outputEncoding = THREE.sRGBEncoding;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    host.appendChild(renderer.domElement);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x8a9bb0, 0.9));
    previewSun = new THREE.DirectionalLight(0xffffff, 2.0);
    var sun = previewSun;
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

    createPreviewGrid();
    previewRoot = new THREE.Group();
    scene.add(previewRoot);

    placeholder = new THREE.Mesh(
      new THREE.BoxGeometry(1, 1, 1),
      new THREE.MeshStandardMaterial({ color: 0xcdd2d6, roughness: 0.6 })
    );
    placeholder.position.z = 0.5;
    placeholder.castShadow = true;
    placeholder.receiveShadow = true;
    placeholder.visible = false;
    previewRoot.add(placeholder);

    frameRadius(1.2);
    if (!rafId) rafId = requestAnimationFrame(tick);
    return true;
  }

  function createPreviewGrid() {
    var THREE = window.THREE;
    var grid = new THREE.GridHelper(80, 80, 0x7f8790, 0xc4c9cf);
    grid.rotation.x = Math.PI / 2;
    grid.material.transparent = true;
    grid.material.opacity = 0.5;
    grid.material.depthWrite = false;
    grid.material.depthTest = false;
    grid.renderOrder = 2;
    scene.add(grid);

    var originMaterial = new THREE.LineBasicMaterial({
      color: 0x5f6872,
      transparent: true,
      opacity: 0.8
    });
    originMaterial.depthTest = false;
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
    xLine.renderOrder = 3;
    yLine.renderOrder = 3;
    scene.add(xLine, yLine);
  }

  function frameRadius(radius) {
    frameView(radius, 0);
  }

  function frameView(radius, targetZ) {
    previewOrbitRadius = Math.max(0.5, radius);
    previewTargetZ = targetZ || 0;
    fitPreviewShadowRig(previewOrbitRadius);
    updatePreviewCameraOrbit();
  }

  function fitPreviewShadowRig(radius) {
    if (!previewSun) return;
    var safeRadius = Math.max(1.2, isFinite(radius) ? radius : 1.2);
    var sunDistance = Math.max(20, safeRadius * 1.55);

    previewSun.position.set(
      PREVIEW_SUN_DIRECTION.x * sunDistance,
      PREVIEW_SUN_DIRECTION.y * sunDistance,
      previewTargetZ + PREVIEW_SUN_DIRECTION.z * sunDistance
    );
    previewSun.target.position.set(0, 0, previewTargetZ);
    previewSun.target.updateMatrixWorld();

    var shadowCamera = previewSun.shadow.camera;
    var halfExtent = Math.max(60, safeRadius * 1.35);
    shadowCamera.left = -halfExtent;
    shadowCamera.right = halfExtent;
    shadowCamera.top = halfExtent;
    shadowCamera.bottom = -halfExtent;
    shadowCamera.near = 0.5;
    shadowCamera.far = Math.max(400, safeRadius * 4.0);
    shadowCamera.updateProjectionMatrix();
    previewSun.shadow.needsUpdate = true;
  }

  function updatePreviewCameraOrbit() {
    var d = Math.max(0.5, previewOrbitRadius);
    var horizontal = d * 2.0;
    camera.position.set(
      Math.cos(previewYaw) * horizontal,
      Math.sin(previewYaw) * horizontal,
      d * 1.0 + previewTargetZ
    );
    camera.lookAt(0, 0, previewTargetZ);
  }

  function disposeMaterial(material) {
    if (!material) return;
    var materials = Array.isArray(material) ? material : [material];
    materials.forEach(function(item) {
      if (item && item.dispose) item.dispose();
    });
  }

  function previewWhiteboxColor(object) {
    return WHITEBOX_PREVIEW_COLOR;
  }

  function applyPreviewWhiteboxMaterial(object) {
    var THREE = window.THREE;
    return new THREE.MeshStandardMaterial({
      color: previewWhiteboxColor(object),
      metalness: 0,
      roughness: 0.68,
      side: THREE.DoubleSide
    });
  }

  function clearModel() {
    if (!model) return;
    previewRoot.remove(model);
    model.traverse(function(object) {
      if (object.geometry) object.geometry.dispose();
      disposeMaterial(object.material);
    });
    model = null;
  }

  function enterPlaceholder() {
    if (!ensureInit()) return;
    clearModel();
    placeholder.visible = true;
    frameRadius(1.2);
    setMsg('生成中…');
    phase = 'running';
  }

  function cacheKeyFor(whitebox) {
    return whitebox.cache_key || whitebox.run_id || whitebox.url || '';
  }

  function sortedQuantile(values, q) {
    if (!values.length) return 0;
    values.sort(function(a, b) { return a - b; });
    var idx = Math.round((values.length - 1) * q);
    idx = Math.max(0, Math.min(values.length - 1, idx));
    return values[idx];
  }

  function objectLayerName(object) {
    return String(
      (object && object.name) ||
      (object && object.userData && (object.userData.name || object.userData.layer)) ||
      ''
    ).toLowerCase();
  }

  function layerNameMatches(name, layerKey) {
    var key = String(layerKey || '').toLowerCase();
    return name === key || name === 'whitebox_' + key || name.indexOf(key + '_') === 0 || name.indexOf('_' + key) >= 0;
  }

  function findLayerObject(root, layerKey) {
    var match = null;
    var key = String(layerKey || '').toLowerCase();
    root.traverse(function(object) {
      if (match) return;
      var name = objectLayerName(object);
      if (name === key || name === 'whitebox_' + key || name.indexOf(key + '_') === 0 || name.indexOf('_' + key) >= 0) {
        match = object;
      }
    });
    return match;
  }

  function expandBoxWithObject(box, object) {
    if (!object) return false;
    var next = new window.THREE.Box3().setFromObject(object);
    if (next.isEmpty()) return false;
    box.union(next);
    return true;
  }

  function computeTerrainPreviewPivot(model) {
    var THREE = window.THREE;
    var terrainObject = findLayerObject(model, 'terrain');
    var buildingsObject = findLayerObject(model, 'buildings');
    var roadsObject = findLayerObject(model, 'roads');
    if (!roadsObject) roadsObject = findLayerObject(model, 'road');
    var frameObject = buildingsObject || roadsObject || terrainObject || model;
    var pivotObject = terrainObject || model;
    var pivotBox = new THREE.Box3().setFromObject(pivotObject);
    var fullCenter = pivotBox.getCenter(new THREE.Vector3());
    var frameBox = new THREE.Box3();
    if (!expandBoxWithObject(frameBox, terrainObject)) expandBoxWithObject(frameBox, frameObject);
    expandBoxWithObject(frameBox, roadsObject);
    expandBoxWithObject(frameBox, buildingsObject);
    if (frameBox.isEmpty()) frameBox.copy(pivotBox);
    var frameSize = frameBox.getSize(new THREE.Vector3());
    var totalPositions = 0;
    model.updateMatrixWorld(true);

    pivotObject.traverse(function(object) {
      var attrs = object.geometry && object.geometry.attributes;
      var position = attrs && attrs.position;
      if (object.isMesh && position) totalPositions += position.count;
    });

    var maxSamples = 60000;
    var sampleEvery = Math.max(1, Math.ceil(totalPositions / maxSamples));
    var seen = 0;
    var point = new THREE.Vector3();
    var xs = [], ys = [], zs = [];

    pivotObject.traverse(function(object) {
      var attrs = object.geometry && object.geometry.attributes;
      var position = attrs && attrs.position;
      if (!object.isMesh || !position) return;
      object.updateWorldMatrix(true, false);
      for (var i = 0; i < position.count; i++) {
        if ((seen++ % sampleEvery) !== 0) continue;
        point.fromBufferAttribute(position, i).applyMatrix4(object.matrixWorld);
        if (!isFinite(point.x) || !isFinite(point.y) || !isFinite(point.z)) continue;
        xs.push(point.x);
        ys.push(point.y);
        zs.push(point.z);
      }
    });

    if (!xs.length || pivotBox.isEmpty()) {
      return { center: fullCenter, groundZ: fullCenter.z, targetZ: 0, radius: 1.2 };
    }

    var center = new THREE.Vector3(
      (sortedQuantile(xs, 0.05) + sortedQuantile(xs, 0.95)) * 0.5,
      (sortedQuantile(ys, 0.05) + sortedQuantile(ys, 0.95)) * 0.5,
      0
    );
    var groundZ = sortedQuantile(zs, 0.02);
    var medianZ = sortedQuantile(zs, 0.5);
    var verticalSpan = Math.max(0, frameBox.max.z - groundZ);
    var radius = Math.max(frameSize.x, frameSize.y) * 0.6;
    radius = Math.max(1.2, radius, verticalSpan * 0.7);
    return {
      center: center,
      groundZ: groundZ,
      targetZ: Math.max(0, medianZ - groundZ),
      radius: radius
    };
  }

  function preparePreviewMesh(object) {
    disposeMaterial(object.material);
    object.material = applyPreviewWhiteboxMaterial(object);
    object.castShadow = true;
    object.receiveShadow = true;
  }

  function loadWhitebox(whitebox, force) {
    if (!ensureInit() || !window.VC_GLB || !whitebox || !whitebox.url) return;
    var key = cacheKeyFor(whitebox);
    if (!force && key && key === shownCacheKey && phase === 'shown') return;
    var seq = ++loadSeq;
    currentWhitebox = whitebox;
    placeholder.visible = true;
    phase = 'loading';
    setMsg('加载预览…');
    window.VC_GLB.load(whitebox.url).then(function(root) {
      if (seq !== loadSeq) return;
      clearModel();
      model = root;
      model.traverse(function(object) {
        if (!object.isMesh) return;
        preparePreviewMesh(object);
      });
      var pivot = computeTerrainPreviewPivot(model);
      if (isFinite(pivot.radius) && pivot.radius > 0) {
        model.position.set(-pivot.center.x, -pivot.center.y, -pivot.groundZ);
        frameView(pivot.radius, pivot.targetZ);
      } else {
        frameRadius(1.2);
      }
      previewRoot.add(model);
      placeholder.visible = false;
      shownCacheKey = key;
      setMsg('');
      phase = 'shown';
    }).catch(function() {
      if (seq !== loadSeq) return;
      phase = 'error';
      setMsg('预览加载失败（点击重试）');
    });
  }

  function tick() {
    rafId = requestAnimationFrame(tick);
    if (!renderer || !host) return;
    var w = host.clientWidth;
    var h = host.clientHeight;
    if (w === 0 || h === 0 || host.offsetParent === null) return;
    var pr = renderer.getPixelRatio();
    if (renderer.domElement.width !== Math.floor(w * pr) || renderer.domElement.height !== Math.floor(h * pr)) {
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    }
    if (placeholder.visible || model) {
      previewRoot.rotation.z += model ? 0.005 : 0.02;
    }
    renderer.render(scene, camera);
  }

  function update(payload) {
    if (!payload) return;
    var asset = payload.houdini_asset || {};
    var whitebox = asset.whitebox || {};
    var previewReady = !!asset.preview_ready;
    if (payload.running && payload.operation !== 'download') {
      currentWhitebox = whitebox.available ? whitebox : currentWhitebox;
      if (phase !== 'running') enterPlaceholder();
      return;
    }
    if (!previewReady || !whitebox.available) {
      currentWhitebox = null;
      if (phase === 'loading') return;
      if (phase !== 'shown') setMsg('');
      return;
    }
    currentWhitebox = whitebox;
    loadWhitebox(whitebox, false);
  }

  function getWhitebox() {
    return currentWhitebox;
  }

  window.VC_HOUDINI_PREVIEW = { update: update, getWhitebox: getWhitebox };
})();
