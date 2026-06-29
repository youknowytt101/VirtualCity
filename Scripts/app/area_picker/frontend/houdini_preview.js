// Domain: houdini-preview
// Owns: Small Three.js whitebox preview driven by the houdini_asset.whitebox status contract.
// AI handoff: For blank preview or stale GLB issues, trace VC_HOUDINI_PREVIEW.update from pipeline_status.js.
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
  var previewVisible = false;
  var previewInView = true;
  var previewObserver = null;
  var previewVisibilityBound = false;
  var previewDrag = null;
  var previewDragged = false;
  var phase = 'idle';       // idle | running | loading | shown | error
  var sessionGenerated = false;  // 本会话点过"生成"才允许显示白盒，重启后归零=待机
  var currentWhitebox = null;
  var shownCacheKey = '';
  var loadSeq = 0;
  var PREVIEW_CAMERA_ORBIT_RADIUS = 4;
  var PREVIEW_CAMERA_TARGET_Z = 1.2;
  var PREVIEW_CAMERA_PAN_Z = -0.8;
  var PREVIEW_MODEL_TARGET_RADIUS = 2.8;
  var PREVIEW_SUN_DISTANCE = 20;
  var PREVIEW_SHADOW_EXTENT = 10;
  var PREVIEW_SHADOW_FAR = 40;
  var previewYaw = Math.atan2(-1.6, 1.2);
  var previewOrbitRadius = PREVIEW_CAMERA_ORBIT_RADIUS;
  var previewTargetZ = PREVIEW_CAMERA_TARGET_Z;
  var WHITEBOX_PREVIEW_COLOR = 0xb8b8b8;
  var PREVIEW_SUN_DIRECTION = { x: 0.426, y: 0.721, z: 0.557 };
  var PREVIEW_GRID_Z = 0.02;
  var PREVIEW_AXIS_LENGTH = 3;
  var previewGrid = null;

  function setMsg(text) {
    if (msgEl) msgEl.textContent = text || '';
  }

  function modelStatsLabel(root, whitebox) {
    var verts = 0, tris = 0;
    root.traverse(function(object) {
      if (!object.isMesh || !object.geometry) return;
      var geometry = object.geometry;
      var position = geometry.attributes && geometry.attributes.position;
      if (position) verts += position.count;
      tris += (geometry.index ? geometry.index.count : (position ? position.count : 0)) / 3;
    });
    var box = whitebox || {};
    var path = box.path || '';
    var name = path ? path.split(/[\\/]/).pop() : '';
    var lines = ['顶点 ' + verts.toLocaleString() + ' · 面 ' + Math.round(tris).toLocaleString()];
    if (name) lines.push(name + (box.size_label && box.size_label !== '--' ? ' · ' + box.size_label : ''));
    if (path) lines.push(path);
    return lines.join('\n');
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
      if (previewDragged) {
        previewDragged = false;
        return;
      }
      if (currentWhitebox && currentWhitebox.available) {
        loadWhitebox(currentWhitebox, true);
      }
    });
    host.addEventListener('pointerdown', beginPreviewDrag);
    host.addEventListener('pointermove', dragPreview);
    host.addEventListener('pointerup', endPreviewDrag);
    host.addEventListener('pointercancel', endPreviewDrag);
    host.addEventListener('wheel', zoomPreview);

    if (THREE.ColorManagement && 'legacyMode' in THREE.ColorManagement) {
      THREE.ColorManagement.legacyMode = false;
    }
    THREE.Object3D.DEFAULT_UP.set(0, 0, 1);
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x666a6c);
    camera = new THREE.PerspectiveCamera(45, 1, 0.05, 100000);
    camera.up.set(0, 0, 1);
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    if ('outputColorSpace' in renderer) renderer.outputColorSpace = THREE.SRGBColorSpace;
    else renderer.outputEncoding = THREE.sRGBEncoding;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    host.appendChild(renderer.domElement);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x8a9bb0, 0.9));
    previewSun = new THREE.DirectionalLight(0xffffff, 2.0);
    var sun = previewSun;
    sun.castShadow = true;
    sun.shadow.mapSize.set(4096, 4096);
    sun.shadow.camera.near = 0.5;
    sun.shadow.bias = -0.00015;
    sun.shadow.normalBias = 0.03;
    sun.shadow.radius = 1.2;
    scene.add(sun, sun.target);

    createPreviewGrid();
    createPreviewGround();
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

    resetPreviewView();
    installPreviewVisibility();
    updatePreviewVisibility();
    return true;
  }

  function installPreviewVisibility() {
    if (previewVisibilityBound) return;
    previewVisibilityBound = true;
    if ('IntersectionObserver' in window) {
      previewObserver = new IntersectionObserver(function(entries) {
        previewInView = !!(entries[0] && entries[0].isIntersecting);
        updatePreviewVisibility();
      });
      previewObserver.observe(host);
    }
    document.addEventListener('visibilitychange', updatePreviewVisibility);
    window.addEventListener('pagehide', disposePreview);
    window.addEventListener('beforeunload', disposePreview);
  }

  function updatePreviewVisibility() {
    previewVisible = !!host && previewInView && !document.hidden && host.clientWidth > 0 && host.clientHeight > 0;
    if (previewVisible) scheduleTick();
    else stopTick();
  }

  function scheduleTick() {
    if (rafId || !previewVisible || !renderer) return;
    rafId = requestAnimationFrame(tick);
  }

  function stopTick() {
    if (!rafId) return;
    cancelAnimationFrame(rafId);
    rafId = null;
  }

  function createPreviewGrid() {
    if (!window.VC_VIEWPORT_GRID) {
      setMsg('Viewport grid module 未加载');
      return;
    }
    previewGrid = window.VC_VIEWPORT_GRID.create(scene, camera, {
      name: 'houdini-preview-grid',
      planeZ: PREVIEW_GRID_Z,
      fadeStart: 6,
      fadeEnd: 18,
      lodPixels: 42,
      minorColor: 0xc8cdd1,
      majorColor: 0xc8cdd1,
      axisXColor: 0xffffff,
      axisYColor: 0xffffff,
      axisZColor: 0x5c85d1,
      minorAlpha: 0.24,
      majorAlpha: 0.24,
      axisAlpha: 0.82,
      axisInnerPx: 0.25,
      axisOuterPx: 0.85,
      showZAxis: false,
      axisLength: PREVIEW_AXIS_LENGTH
    });
  }

  function createPreviewGround() {
    var THREE = window.THREE;
    var shadow = new THREE.Mesh(
      new THREE.PlaneGeometry(PREVIEW_SHADOW_EXTENT * 2, PREVIEW_SHADOW_EXTENT * 2),
      new THREE.ShadowMaterial({ color: 0x000000, opacity: 0.4, transparent: true })
    );
    shadow.position.z = PREVIEW_GRID_Z - 0.01;
    shadow.receiveShadow = true;
    shadow.renderOrder = -9;
    shadow.userData.pickable = false;
    scene.add(shadow);
  }

  function configurePreviewShadowRig() {
    if (!previewSun) return;
    previewSun.position.set(
      PREVIEW_SUN_DIRECTION.x * PREVIEW_SUN_DISTANCE,
      PREVIEW_SUN_DIRECTION.y * PREVIEW_SUN_DISTANCE,
      PREVIEW_CAMERA_TARGET_Z + PREVIEW_SUN_DIRECTION.z * PREVIEW_SUN_DISTANCE
    );
    previewSun.target.position.set(0, 0, PREVIEW_CAMERA_TARGET_Z);
    previewSun.target.updateMatrixWorld();

    var shadowCamera = previewSun.shadow.camera;
    shadowCamera.left = -PREVIEW_SHADOW_EXTENT;
    shadowCamera.right = PREVIEW_SHADOW_EXTENT;
    shadowCamera.top = PREVIEW_SHADOW_EXTENT;
    shadowCamera.bottom = -PREVIEW_SHADOW_EXTENT;
    shadowCamera.near = 0.5;
    shadowCamera.far = PREVIEW_SHADOW_FAR;
    shadowCamera.updateProjectionMatrix();
    previewSun.shadow.needsUpdate = true;
  }

  function resetPreviewView() {
    previewOrbitRadius = PREVIEW_CAMERA_ORBIT_RADIUS;
    previewTargetZ = PREVIEW_CAMERA_TARGET_Z;
    configurePreviewShadowRig();
    updatePreviewCameraOrbit();
  }

  function updatePreviewCameraOrbit() {
    if (!camera) return;
    var d = Math.max(0.5, previewOrbitRadius);
    var horizontal = d * 2.0;
    camera.position.set(
      Math.cos(previewYaw) * horizontal,
      Math.sin(previewYaw) * horizontal,
      d * 1.0 + previewTargetZ + PREVIEW_CAMERA_PAN_Z
    );
    camera.lookAt(0, 0, previewTargetZ + PREVIEW_CAMERA_PAN_Z);
    if (previewGrid) window.VC_VIEWPORT_GRID.update(previewGrid, camera);
  }

  function beginPreviewDrag(event) {
    if (!renderer) return;
    previewDrag = { x: event.clientX, y: event.clientY };
    previewDragged = false;
    if (host.setPointerCapture) host.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  function dragPreview(event) {
    if (!previewDrag || !camera) return;
    var dx = event.clientX - previewDrag.x;
    var dy = event.clientY - previewDrag.y;
    previewDragged = previewDragged || Math.abs(dx) + Math.abs(dy) > 2;
    previewYaw -= dx * 0.01;
    previewDrag.x = event.clientX;
    previewDrag.y = event.clientY;
    updatePreviewCameraOrbit();
    scheduleTick();
    event.preventDefault();
  }

  function endPreviewDrag(event) {
    previewDrag = null;
    if (host.releasePointerCapture) host.releasePointerCapture(event.pointerId);
  }

  function zoomPreview(event) {
    if (!renderer || !camera) return;
    event.preventDefault();
    previewOrbitRadius = Math.max(1.2, Math.min(12, previewOrbitRadius * Math.exp(event.deltaY * 0.001)));
    updatePreviewCameraOrbit();
    scheduleTick();
  }

  function disposeMaterial(material) {
    if (!material) return;
    var materials = Array.isArray(material) ? material : [material];
    materials.forEach(function(item) {
      if (item && item.dispose) item.dispose();
    });
  }

  function applyPreviewWhiteboxMaterial(object) {
    var THREE = window.THREE;
    return new THREE.MeshStandardMaterial({
      color: WHITEBOX_PREVIEW_COLOR,
      metalness: 0,
      roughness: 0.68,
      side: THREE.DoubleSide
    });
  }

  function disposePreviewObject(object) {
    if (!object) return;
    object.traverse(function(object) {
      if (object.geometry) object.geometry.dispose();
      disposeMaterial(object.material);
    });
  }

  function clearModel() {
    if (!model) return;
    previewRoot.remove(model);
    disposePreviewObject(model);
    model = null;
  }

  function disposePreview() {
    stopTick();
    clearModel();
    disposePreviewObject(placeholder);
    if (previewGrid && window.VC_VIEWPORT_GRID) window.VC_VIEWPORT_GRID.dispose(previewGrid);
    if (previewObserver) previewObserver.disconnect();
    if (renderer) {
      renderer.dispose();
      if (renderer.forceContextLoss) renderer.forceContextLoss();
      if (renderer.domElement && renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
    }
    document.removeEventListener('visibilitychange', updatePreviewVisibility);
    window.removeEventListener('pagehide', disposePreview);
    window.removeEventListener('beforeunload', disposePreview);
    renderer = scene = camera = previewRoot = previewSun = placeholder = previewGrid = null;
    model = null;
    previewObserver = null;
    previewVisibilityBound = false;
    previewVisible = false;
  }

  function enterPlaceholder() {
    if (!ensureInit()) return;
    clearModel();
    placeholder.visible = true;
    resetPreviewView();
    setMsg('生成中…');
    phase = 'running';
    scheduleTick();
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

  function fitModelToPreview(model, pivot) {
    if (!model) return;
    var center = (pivot && pivot.center) || {};
    var centerX = isFinite(center.x) ? center.x : 0;
    var centerY = isFinite(center.y) ? center.y : 0;
    var groundZ = pivot && isFinite(pivot.groundZ) ? pivot.groundZ : 0;
    var radius = pivot && isFinite(pivot.radius) && pivot.radius > 0 ? pivot.radius : PREVIEW_MODEL_TARGET_RADIUS;
    var scale = PREVIEW_MODEL_TARGET_RADIUS / Math.max(0.001, radius);
    model.scale.setScalar(scale);
    model.position.set(-centerX * scale, -centerY * scale, -groundZ * scale);
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
    scheduleTick();
    window.VC_GLB.load(whitebox.url).then(function(root) {
      if (seq !== loadSeq) return;
      clearModel();
      model = root;
      model.traverse(function(object) {
        if (!object.isMesh) return;
        preparePreviewMesh(object);
      });
      var pivot = computeTerrainPreviewPivot(model);
      fitModelToPreview(model, pivot);
      resetPreviewView();
      previewRoot.add(model);
      placeholder.visible = false;
      shownCacheKey = key;
      setMsg(modelStatsLabel(model, whitebox));
      phase = 'shown';
      scheduleTick();
    }).catch(function(err) {
      if (seq !== loadSeq) return;
      phase = 'error';
      var message = whitebox.message || (err && err.message) || '预览加载失败';
      setMsg('预览加载失败：' + message + '（点击重试）');
      scheduleTick();
    });
  }

  function tick() {
    rafId = null;
    if (!renderer || !host) return;
    var w = host.clientWidth;
    var h = host.clientHeight;
    if (w === 0 || h === 0) {
      updatePreviewVisibility();
      return;
    }
    var pr = renderer.getPixelRatio();
    if (renderer.domElement.width !== Math.floor(w * pr) || renderer.domElement.height !== Math.floor(h * pr)) {
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    }
    if (placeholder.visible || model) {
      if (model && phase === 'shown' && !previewDrag) previewYaw += 0.005;
      updatePreviewCameraOrbit();
    } else {
      if (previewGrid) window.VC_VIEWPORT_GRID.update(previewGrid, camera);
    }
    renderer.render(scene, camera);
    if (model && phase === 'shown') scheduleTick();
  }

  function update(payload) {
    if (!payload) return;
    var asset = payload.houdini_asset || {};
    var whitebox = asset.whitebox || {};
    var previewReady = !!asset.preview_ready;
    if (payload.running && payload.operation !== 'download') {
      sessionGenerated = true;
      currentWhitebox = whitebox.available ? whitebox : currentWhitebox;
      if (phase !== 'running') enterPlaceholder();
      return;
    }
    if (!previewReady || !whitebox.available) {
      currentWhitebox = null;
      if (phase === 'loading') return;
      if (phase !== 'shown') setMsg(whitebox.message || '');
      return;
    }
    if (!sessionGenerated) {
      // 待机：磁盘上的旧白盒不自动显示，等本会话点击生成后才加载
      currentWhitebox = null;
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
