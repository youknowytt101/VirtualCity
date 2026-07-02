// Domain: game-workbench
// Owns: Three.js editor scene bootstrap, render loop, input routing, transform
//       controls, and whitebox import wiring. Scene storage/history/commands/
//       inspector live in gw_scene_state.js/gw_history.js/gw_commands.js/
//       gw_scene_persistence.js/gw_inspector.js -- this file orchestrates them.
// AI handoff: For editor viewport, asset sync, or scene outline issues, start here before checking vc_glb.js.
(function() {
  'use strict';

  var GW = window.VC_GW;
  var sceneHost = null;
  var dragPreview = null;
  var runButton = null;
  var runLabel = null;
  var speedInput = null;
  var lightInput = null;
  var ambientLight = null;
  var gameWorkbench = null;
  var renderer = null;
  var scene = null;
  var camera = null;
  var clock = null;
  var raycaster = null;
  var mouse = null;
  var groundPlane = null;
  var hitPoint = null;
  var playMode = null;
  var cameraControls = null;
  var rafId = null;
  var initialized = false;
  var active = false;
  var dragState = null;
  var sceneState = null;
  var selectedObject = null;
  var csm = null;
  var editorEnvironment = null;
  var outlineBody = null;
  var transformControls = null;
  var transformControlsLoading = null;
  var transformMode = 'translate';
  var transformModeButtons = [];
  var assetLoader = null;
  var history = null;
  var sceneCommands = null;
  var scenePersistence = null;
  var transformDragSnapshot = null;
  var pendingSceneRootStatus = null;
  var sideResizeState = null;
  var editorGrid = null;
  var sceneOutliner = null;
  var inspector = null;
  var runtimeStatsEl = null;
  var runtimeStatsFields = {};
  var runtimeStatsLastFrameTime = null;
  var runtimeStatsLastUpdate = 0;
  var playCollider = null;
  var DEFAULT_EDITOR_SKY_COLOR = 0x8fb7d9;

  // Aliases into the split modules (gw_core/gw_character/gw_play). These load
  // before game_workbench.js, so VC_GW.* is populated by the time this IIFE runs.
  var setStatus = GW.setStatus;
  var safeThree = GW.safeThree;
  var setOutlineSelected = GW.setOutlineSelected;
  var createCharacter = GW.createCharacter;
  var createPlayModeController = GW.createPlayModeController;

  function syncSelectionHighlight() {
    var playing = playMode && playMode.isPlaying();
    sceneState.getCharacters().forEach(function(character) {
      var selected = character === selectedObject && !playing;
      character.traverse(function(child) {
        if (child.userData && child.userData.outline) setOutlineSelected(child, selected);
      });
    });
    sceneState.getWhiteboxLayers().forEach(function(layer) {
      setLayerHighlight(layer, layer === selectedObject && !playing);
    });
  }

  // Whitebox layers have no baked outline meshes; tint their material emissive
  // instead. Materials are cloned per layer on import so this stays isolated.
  function setLayerHighlight(layer, on) {
    layer.traverse(function(mesh) {
      if (!mesh.isMesh || !mesh.material) return;
      var mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      mats.forEach(function(m) {
        if (!m || !m.emissive) return;
        if (m.userData.__baseEmissive === undefined) m.userData.__baseEmissive = m.emissive.getHex();
        m.emissive.setHex(on ? 0x1f6f8b : m.userData.__baseEmissive);
      });
    });
  }

  function markCharacter(character) {
    var id = 'character-' + String(sceneState.getCharacters().length + 1).padStart(2, '0');
    character.name = id;
    character.userData.assetRoot = character;
    character.userData.assetType = 'character';
    character.traverse(function(child) {
      child.castShadow = true;
      child.receiveShadow = true;
      child.userData.assetRoot = character;
      child.userData.assetType = 'character';
    });
    return character;
  }

  function createGrid() {
    var THREE = safeThree();
    if (!THREE) return;
    if (!window.VC_VIEWPORT_GRID) {
      setStatus('Viewport grid module 未加载');
      return;
    }
    editorGrid = window.VC_VIEWPORT_GRID.create(scene, camera, {
      name: 'editor-procedural-grid',
      planeZ: 0,
      fadeStart: 700,
      fadeEnd: 1850,
      lodPixels: 64,
      minorColor: 0xc8cdd1,
      majorColor: 0xc8cdd1,
      axisXColor: 0xffffff,
      axisYColor: 0xffffff,
      axisZColor: 0x5f8cff,
      minorAlpha: 0.24,
      majorAlpha: 0.24,
      axisAlpha: 0.9,
      axisInnerPx: 0.25,
      axisOuterPx: 0.85,
      showZAxis: false
    });
    updateEditorGrid();
  }

  function updateEditorGrid() {
    if (!editorGrid || !camera) return;
    window.VC_VIEWPORT_GRID.update(editorGrid, camera);
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

  function screenToGround(clientX, clientY) {
    var rect = sceneHost.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    mouse.x = ((clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -(((clientY - rect.top) / rect.height) * 2 - 1);
    raycaster.setFromCamera(mouse, camera);
    return raycaster.ray.intersectPlane(groundPlane, hitPoint) ? hitPoint.clone() : null;
  }

  // Rebuilds the merged BVH play-mode collider (gw_collision.js) from the
  // scene's current whitebox layers + models, so entering Run always reflects
  // whatever's been imported/placed since the last run. Async; every consumer
  // below (ground/obstacle sampling, gw_play.js's capsule collision) tolerates
  // playCollider being null -- mid-build, load failure, or nothing collidable
  // -- by falling back to the simpler per-object raycasts that always worked.
  function buildOrRefreshPlayCollider() {
    if (!GW.buildPlayCollider) return;
    GW.buildPlayCollider(sceneState.getCollidables()).then(function(collider) {
      playCollider = collider;
    }).catch(function(error) {
      playCollider = null;
      var message = error && error.message ? error.message : String(error || '未知错误');
      if (GW.setStatus) GW.setStatus('碰撞体构建失败，已回退到简单避障: ' + message);
    });
  }

  // Height of the ground under (x, y): prefer a single raycast against the
  // BVH play collider once it's built; otherwise fall back to a direct
  // raycast against the whitebox layers, then the z=0 plane. Injected into
  // the play controller so gravity lands the character on terrain.
  function sampleGroundHeight(x, y) {
    var THREE = safeThree();
    if (!THREE || !raycaster) return 0;
    raycaster.set(new THREE.Vector3(x, y, 100000), new THREE.Vector3(0, 0, -1));
    if (playCollider) {
      var colliderHits = raycaster.intersectObject(playCollider, false);
      if (colliderHits.length) return colliderHits[0].point.z;
    }
    var whiteboxLayers = sceneState.getWhiteboxLayers();
    if (whiteboxLayers.length) {
      var hits = raycaster.intersectObjects(whiteboxLayers, true);
      for (var i = 0; i < hits.length; i++) {
        var obj = hits[i].object;
        if (obj && obj.userData && obj.userData.pickable === false) continue;
        return hits[i].point.z;
      }
    }
    return 0;
  }

  // Casts from the play camera's focus point (the player's chest) toward its
  // desired chase-cam position and returns the first solid hit in between, so
  // gw_play.js can pull the camera in front of walls/terrain instead of
  // letting it clip through them. Prefers the BVH play collider (one fast
  // raycast against all scene geometry); falls back to a per-object raycast
  // against scene pickables when the collider isn't built yet. Excludes the
  // player's own avatar either way so the camera isn't blocked by the
  // character it's following.
  function sampleCameraObstacle(origin, target, ignoreCharacter) {
    var THREE = safeThree();
    if (!THREE || !raycaster) return null;
    var offset = target.clone().sub(origin);
    var distance = offset.length();
    if (distance < 0.0001) return null;
    raycaster.set(origin, offset.normalize());
    if (playCollider) {
      var colliderHits = raycaster.intersectObject(playCollider, false);
      return (colliderHits.length && colliderHits[0].distance <= distance) ? colliderHits[0].point : null;
    }
    var candidates = sceneState.getPickables().filter(function(obj) {
      return obj !== ignoreCharacter && obj.userData.assetRoot !== ignoreCharacter;
    });
    var hits = raycaster.intersectObjects(candidates, true);
    for (var i = 0; i < hits.length; i++) {
      if (hits[i].distance > distance) break;
      var obj = hits[i].object;
      if (obj.userData.pickable === false || obj.userData.assetRoot === ignoreCharacter) continue;
      return hits[i].point;
    }
    return null;
  }

  function getCharacterGroundOffset(character) {
    return Number(character && character.userData && character.userData.groundOffset) || 0;
  }

  function setCharacterGroundPosition(character, point) {
    if (!character || !point) return;
    character.position.set(point.x, point.y, point.z + getCharacterGroundOffset(character));
  }

  function placeCharacterAt(point) {
    var character = markCharacter(createCharacter());
    setCharacterGroundPosition(character, point);
    sceneState.addCharacter(character);
    selectSceneObject(character);
    rebuildSceneOutline();
    pushCommand(sceneCommands.makeCreateCharacterCommand(character));
    setStatus('角色已放置，按 Space 或点击运行');
    return character;
  }

  function updateTransformModeButtons() {
    transformModeButtons.forEach(function(button) {
      var activeMode = button.dataset.transformMode === transformMode;
      button.classList.toggle('is-active', activeMode);
      button.setAttribute('aria-pressed', activeMode ? 'true' : 'false');
    });
  }

  function setTransformMode(mode) {
    if (mode !== 'translate' && mode !== 'rotate' && mode !== 'scale') return;
    transformMode = mode;
    if (transformControls) transformControls.setMode(transformMode);
    updateTransformModeButtons();
    render();
  }

  function bindTransformModeButtons() {
    transformModeButtons = Array.prototype.slice.call(document.querySelectorAll('[data-transform-mode]'));
    transformModeButtons.forEach(function(button) {
      button.addEventListener('click', function() {
        setTransformMode(button.dataset.transformMode);
      });
    });
    updateTransformModeButtons();
  }

  function isTransformControlActive() {
    return Boolean(
      transformControls &&
      transformControls.visible &&
      transformControls.enabled &&
      (transformControls.dragging || transformControls.axis)
    );
  }

  // Character-specific play/run paths need just the character; models and
  // whitebox layers can't run. Derived on demand from selectedObject so there's
  // a single source of truth for "what's selected".
  function getSelectedCharacter() {
    return (selectedObject && selectedObject.userData && selectedObject.userData.assetType === 'character') ? selectedObject : null;
  }

  // Selects any scene object (character or whitebox layer). Generic edit
  // commands use selectedObject so models and whitebox layers can participate.
  function selectSceneObject(object) {
    selectedObject = object || null;
    if (transformControls) {
      if (selectedObject) transformControls.attach(selectedObject);
      else transformControls.detach();
    } else if (selectedObject) {
      ensureTransformControls();
    }
    syncEditOverlays();
    refreshOutlineActive();
    if (inspector) inspector.refresh();
  }

  // Rename writes to userData.assetLabel (what the outliner displays for both
  // characters and models) and, for model roots/layers, to the model wrapper's
  // .label so the name survives serialize()/restore.
  function renameSelectedObject(object, name) {
    if (!object) return;
    object.userData.assetLabel = name;
    var model = sceneState.findModelFor(object);
    if (model) model.label = name;
    rebuildSceneOutline();
    scheduleSave();
  }

  function commitTransformChange(object, before) {
    var after = captureTransform(object);
    if (transformChanged(before, after)) pushCommand(sceneCommands.makeTransformCommand(object, before, after));
    render();
  }

  function syncEditOverlays() {
    var editing = Boolean(selectedObject) && !(playMode && playMode.isPlaying());
    if (transformControls) {
      transformControls.visible = editing;
      transformControls.enabled = editing;
      transformControls.setMode(transformMode);
    }
    syncSelectionHighlight();
  }

  function ensureTransformControls() {
    if (transformControls || transformControlsLoading || !scene || !camera || !renderer) return;
    transformControlsLoading = import('/static/three/TransformControls.js').then(function(module) {
      transformControls = new module.TransformControls(camera, renderer.domElement);
      transformControls.setMode(transformMode);
      transformControls.setSize(1);
      transformControls.addEventListener("dragging-changed", function(event) {
        if (event.value) {
          if (cameraControls) cameraControls.clearState();
          transformDragSnapshot = selectedObject ? captureTransform(selectedObject) : null;
        } else if (transformDragSnapshot && selectedObject) {
          commitTransformChange(selectedObject, transformDragSnapshot);
          transformDragSnapshot = null;
        }
      });
      transformControls.addEventListener('change', render);
      scene.add(transformControls);
      if (selectedObject) transformControls.attach(selectedObject);
      syncEditOverlays();
    }).catch(function() {
      setStatus('TransformControls 未加载');
    });
  }

  function scheduleSave() {
    if (scenePersistence) scenePersistence.scheduleSave();
  }

  function clearSceneObjects() {
    if (!scene) return;
    if (playMode) playMode.exit();
    sceneState.clear();
    history.clear();
    selectSceneObject(null);
    rebuildSceneOutline();
  }

  function saveSceneNow() {
    if (!scenePersistence) initGameWorkbench();
    if (scenePersistence) scenePersistence.saveSceneNow();
  }

  function newScene() {
    if (!scenePersistence) initGameWorkbench();
    if (scenePersistence) scenePersistence.newScene();
  }

  function addSceneModel(model, options) {
    if (!model || !model.root) return null;
    var index = options && typeof options.index === 'number' ? options.index : -1;
    sceneState.addModel(model, index >= 0 ? index : undefined);
    rebuildSceneOutline();
    if (!(options && options.skipHistory)) pushCommand(sceneCommands.makeCreateModelCommand(model));
    return model;
  }

  function removeSceneModel(model, options) {
    if (!model || !model.root) return;
    var index = sceneState.removeModel(model);
    if (sceneState.belongsToModel(selectedObject, model)) selectSceneObject(null);
    rebuildSceneOutline();
    return index;
  }

  function getModelSelectionTarget(model) {
    if (!model) return null;
    return (model.layers && model.layers[0]) || model.root || null;
  }

  function restoreSceneModel(item) {
    if (!item || !item.url || !assetLoader) return;
    assetLoader.loadSceneAsset(item.url, null, item.label, {
      restoring: true,
      transform: item
    });
  }

  // Persistence owns storage mechanics; the host owns object construction because
  // it has the character factory and asset loader.
  function restoreSceneSnapshot(data) {
    (data.characters || []).forEach(function(item) {
      var character = markCharacter(createCharacter());
      if (item.p) character.position.fromArray(item.p);
      if (item.p && character.position.z <= getCharacterGroundOffset(character) * 0.25) {
        character.position.z += getCharacterGroundOffset(character);
      }
      if (item.r) character.rotation.set(item.r[0], item.r[1], item.r[2]);
      if (item.s) character.scale.fromArray(item.s);
      if (item.label) character.userData.assetLabel = item.label;
      sceneState.addCharacter(character);
    });
    var savedModels = data.models || [];
    if (!savedModels.length && data.whitebox) {
      savedModels = [{ url: data.whitebox, label: '模型资产' }];
    }
    savedModels.forEach(restoreSceneModel);
    rebuildSceneOutline();
  }

  // Thin host wrappers over the asset loader (gw_assets.js). assetLoader is built
  // in initGameWorkbench once scene/sun state exists; ensure init first so a sync
  // triggered from another workspace still mounts the scene before loading.
  function loadGLB(url) {
    initGameWorkbench();
    if (!assetLoader) { setStatus('场景未就绪'); return; }
    assetLoader.loadGLB(url);
  }

  function rebuildSceneOutline() {
    if (!sceneOutliner) return;
    sceneOutliner.rebuild(sceneState.getOutlineItems(), selectedObject);
  }

  function refreshOutlineActive() {
    if (sceneOutliner) sceneOutliner.refreshActive(selectedObject);
  }

  // Load the latest pipeline-produced whitebox into the editor (no export — the
  // generation pipeline writes the GLB; cache-bust to dodge stale caches).
  function syncFromHoudini() {
    initGameWorkbench();
    if (assetLoader) assetLoader.syncFromHoudini();
  }

  function refreshSceneAssetsBrowser() {
    if (window.VC_SCENE_ASSETS && typeof window.VC_SCENE_ASSETS.refresh === 'function') {
      window.VC_SCENE_ASSETS.refresh();
      return;
    }
    window.dispatchEvent(new Event('scene-root-changed'));
  }

  function syncHoudiniWhiteboxToAssets(button) {
    var label = button ? button.querySelector('.btn-main') : null;
    var previousLabel = label ? label.textContent : '';
    if (button) button.disabled = true;
    if (label) label.textContent = '同步中...';
    fetch('/sync-whitebox-to-scene-assets', { method: 'POST' })
      .then(function(r) { return r.json(); })
      .then(function(res) {
        if (!res || !res.ok) {
          setStatus(res && res.message ? res.message : '同步失败');
          return;
        }
        var navBtn = document.querySelector('[data-workspace-target="game"]');
        if (navBtn) navBtn.click();
        refreshSceneAssetsBrowser();
        setStatus(res.message || 'Houdini 白盒已同步至资产目录');
      })
      .catch(function() { setStatus('同步失败'); })
      .finally(function() {
        if (label) label.textContent = previousLabel || '同步至当前编辑器资产目录';
        if (button) button.disabled = false;
      });
  }

  function bindSyncButtons() {
    var importBtn = document.getElementById('import-houdini-whitebox-btn');  // 编辑器 资产 tab
    if (importBtn) importBtn.addEventListener('click', syncFromHoudini);

    var syncBtn = document.getElementById('sync-to-editor-btn');  // Houdini 构建面板
    if (syncBtn) syncBtn.addEventListener('click', function() {
      syncHoudiniWhiteboxToAssets(syncBtn);
    });

    var openDirBtn = document.getElementById('open-export-dir-btn');  // 打开白盒导出目录
    if (openDirBtn) openDirBtn.addEventListener('click', function() {
      fetch('/open-export-dir', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(res) { if (!res.ok) setStatus(res.message || '打开目录失败'); })
        .catch(function() { setStatus('打开目录失败'); });
    });
  }

  function getPickableSceneObjects() {
    return sceneState.getPickables();
  }

  function pickCharacter(event) {
    var rect = sceneHost.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -(((event.clientY - rect.top) / rect.height) * 2 - 1);
    raycaster.setFromCamera(mouse, camera);
    var hits = raycaster.intersectObjects(getPickableSceneObjects(), true);
    var picked = null;
    for (var i = 0; i < hits.length; i++) {
      var root = hits[i].object.userData.assetRoot;
      if (root) {
        picked = root;
        break;
      }
    }
    selectSceneObject(picked);
  }

  function deleteSelectedObject() {
    if (!selectedObject || playMode.isPlaying()) return false;
    var model = sceneState.findModelFor(selectedObject);
    if (model) {
      var modelIndex = removeSceneModel(model);
      pushCommand(sceneCommands.makeDeleteModelCommand(model, modelIndex));
      setStatus('对象已删除');
      return true;
    }
    var selectedCharacter = getSelectedCharacter();
    if (selectedCharacter) {
      var character = selectedCharacter;
      var index = sceneState.getCharacters().indexOf(character);
      removeCharacter(character);
      pushCommand(sceneCommands.makeDeleteCharacterCommand(character, index));
      setStatus('角色已删除');
      return true;
    }
    return false;
  }

  // Command-pattern history: every reversible edit pushes a { undo, redo } pair
  // into gw_history.js's stack. scheduleSave keeps localStorage in sync without
  // thrashing on every gizmo frame.
  function pushCommand(command) {
    history.push(command);
    scheduleSave();
  }

  function undoLastAction() {
    if (playMode.isPlaying() || !history.undo()) return false;
    render();
    scheduleSave();
    return true;
  }

  function redoLastAction() {
    if (playMode.isPlaying() || !history.redo()) return false;
    render();
    scheduleSave();
    return true;
  }

  function removeCharacter(character) {
    sceneState.removeCharacter(character);
    if (selectedObject === character) selectSceneObject(null);
    rebuildSceneOutline();
  }

  function captureTransform(object) {
    return {
      position: object.position.clone(),
      quaternion: object.quaternion.clone(),
      scale: object.scale.clone()
    };
  }

  function applyTransform(object, snapshot) {
    object.position.copy(snapshot.position);
    object.quaternion.copy(snapshot.quaternion);
    object.scale.copy(snapshot.scale);
    object.updateMatrixWorld(true);
  }

  function transformChanged(a, b) {
    return !a.position.equals(b.position) ||
      !a.quaternion.equals(b.quaternion) ||
      !a.scale.equals(b.scale);
  }

  function refreshAfterTransform(object) {
    if (selectedObject === object && transformControls) transformControls.attach(object);
    render();
  }

  function duplicateCharacter(character) {
    var offsetPosition = character.position.clone();
    offsetPosition.x += 1;
    offsetPosition.y += 1;
    offsetPosition.z -= getCharacterGroundOffset(character);
    var duplicate = placeCharacterAt(offsetPosition);
    duplicate.rotation.copy(character.rotation);
    return true;
  }

  function markDuplicatedModelRoot(root, label) {
    root.userData.assetType = root.userData.assetType || 'model';
    root.userData.assetRoot = root;
    root.userData.assetLabel = label;
    root.traverse(function(node) {
      if (!node.userData) node.userData = {};
      if (!node.userData.assetRoot) node.userData.assetRoot = root;
      if (!node.userData.assetType) node.userData.assetType = root.userData.assetType;
    });
  }

  function duplicateSceneModel(model) {
    if (!model || !model.root) return false;
    var root = model.root.clone(true);
    var label = (model.label || model.root.userData.assetLabel || '模型资产') + ' 副本';
    root.position.x += 1;
    root.position.y += 1;
    markDuplicatedModelRoot(root, label);
    var layers = GW.registerWhiteboxLayers ? GW.registerWhiteboxLayers(root) : [];
    var duplicated = addSceneModel({
      root: root,
      url: model.url,
      label: label,
      layers: layers
    });
    selectSceneObject(getModelSelectionTarget(duplicated));
    setStatus('对象已复制');
    render();
    return true;
  }

  function duplicateSelectedObject() {
    if (!selectedObject || playMode.isPlaying()) return false;
    var model = sceneState.findModelFor(selectedObject);
    if (model) return duplicateSceneModel(model);
    var selectedCharacter = getSelectedCharacter();
    if (selectedCharacter) return duplicateCharacter(selectedCharacter);
    return false;
  }

  function getSelectedObjectFrame() {
    var THREE = safeThree();
    if (!THREE) return null;
    if (!selectedObject) return null;
    var box = new THREE.Box3().setFromObject(selectedObject);
    if (box.isEmpty()) return null;
    var center = box.getCenter(new THREE.Vector3());
    var size = box.getSize(new THREE.Vector3());
    var radius = 0.5 * size.length();
    var fov = THREE.MathUtils.degToRad(camera.fov || 50);
    var distance = Math.max(9, (radius / Math.tan(fov / 2)) * 1.25);
    if (!Number.isFinite(distance)) distance = 9;
    var direction = camera.position.clone().sub(center);
    if (direction.lengthSq() < 0.0001) direction.set(4, -7, 4);
    direction.normalize();
    return { center: center, direction: direction, distance: distance };
  }

  function focusSelectedObject() {
    var frame = getSelectedObjectFrame();
    if (!frame) return false;
    camera.position.copy(frame.center).addScaledVector(frame.direction, frame.distance);
    camera.lookAt(frame.center);
    cameraControls.syncRotationFromCamera();
    return true;
  }

  function getPlayableCharacter() {
    return getSelectedCharacter() || sceneState.getCharacters()[0] || null;
  }

  function toggleRun() {
    if (!playMode) return;
    if (playMode.isPlaying()) {
      playMode.exit();
      return;
    }
    buildOrRefreshPlayCollider();
    if (!playMode.enter(getPlayableCharacter())) {
      setStatus('先拖入一个角色');
    }
  }

  function syncRunState() {
    var playing = playMode && playMode.isPlaying();
    if (gameWorkbench) gameWorkbench.classList.toggle('is-playing', playing);
    if (runButton) {
      runButton.classList.toggle('is-active', playing);
      runButton.setAttribute('aria-pressed', playing ? 'true' : 'false');
      if (runLabel) runLabel.textContent = playing ? '停止' : '运行';
    }
    syncEditOverlays();
    setStatus(playing ? 'WASD 移动，空格跳跃，鼠标控制方向，Esc 停止' : '');
  }

  function updateDragPreview(clientX, clientY) {
    if (!dragPreview) return;
    dragPreview.style.left = clientX + 'px';
    dragPreview.style.top = clientY + 'px';
  }

  function beginAssetDrag(event) {
    var sceneAsset = event.target.closest('.scene-asset-item[data-scene-asset-path]');
    var button = event.target.closest('[data-game-asset="character"]');
    if ((!button && !sceneAsset) || event.button !== 0 || playMode.isPlaying()) return;
    if (sceneAsset && sceneAsset.dataset.sceneAssetCategory !== 'model') return;
    event.preventDefault();
    if (sceneAsset) {
      dragState = {
        kind: 'scene-asset',
        pointerId: event.pointerId,
        source: sceneAsset,
        asset: {
          name: sceneAsset.dataset.sceneAssetName || '模型资产',
          url: sceneAsset.dataset.sceneAssetUrl || '',
          path: sceneAsset.dataset.sceneAssetPath || ''
        }
      };
    } else {
      dragState = {
        kind: 'character',
        pointerId: event.pointerId,
        source: button
      };
    }
    try {
      dragState.source.setPointerCapture(event.pointerId);
    } catch (e) {}
    if (dragPreview) {
      dragPreview.textContent = dragState.kind === 'scene-asset' ? dragState.asset.name : '角色';
      dragPreview.hidden = false;
    }
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
    if (point) {
      if (dragState.kind === 'scene-asset') {
        if (assetLoader && dragState.asset.url) assetLoader.loadSceneAsset(dragState.asset.url, point, dragState.asset.name);
      } else {
        placeCharacterAt(point);
      }
    }
    if (dragPreview) dragPreview.hidden = true;
    dragState = null;
  }

  function handleGameShortcut(event) {
    if (!active || !initialized) return;
    if (event.target && /^(input|textarea|select)$/i.test(event.target.tagName)) return;
    if (playMode.handleKeyDown(event)) return;

    var code = event.code.toLowerCase();
    if (cameraControls.isLooking()) {
      cameraControls.pressKey(code);
      return;
    }
    if (code === 'keyw') {
      event.preventDefault();
      setTransformMode('translate');
      return;
    }
    if (code === 'keye') {
      event.preventDefault();
      setTransformMode('rotate');
      return;
    }
    if (code === 'keyr') {
      event.preventDefault();
      setTransformMode('scale');
      return;
    }
    if (code === 'space') {
      event.preventDefault();
      toggleRun();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && code === 'keyz') {
      event.preventDefault();
      if (event.shiftKey) redoLastAction();
      else undoLastAction();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && code === 'keyy') {
      event.preventDefault();
      redoLastAction();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && code === 'keyd') {
      event.preventDefault();
      duplicateSelectedObject();
      return;
    }
    if ((code === 'delete' || code === 'backspace') && deleteSelectedObject()) {
      event.preventDefault();
      return;
    }
    if (code === 'keyf' && focusSelectedObject()) {
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

  // Imported models are centered near the world origin, so distance-from-origin
  // (not height alone) is the right proxy for "how far might there be something
  // to render." Height-only broke down during alt-orbit: decreasing elevation to
  // level the view toward horizontal shrinks the camera's height toward the
  // pivot's height even while its actual distance from the scene stays the same
  // (it's just trading height for horizontal distance on the orbit sphere), so
  // far kept shrinking and clipped the city out from under the model. Keep the
  // near/far ratio bounded (5000:1) for the grid shader's inverse-projection
  // reconstruction precision (see viewport_grid.js).
  // csm.updateFrustums() resizes each cascade's shadow-camera frustum, which
  // changes its texel size -- the bias/normalBias tuned for that size
  // (tuneCSMShadowBias, render_profile.js) needs recomputing every time this
  // runs, or a cascade that just got bigger/smaller keeps a stale, wrong bias.
  function refitCSM() {
    if (!csm) return;
    csm.updateFrustums();
    if (window.VC_RENDER_PROFILE) window.VC_RENDER_PROFILE.tuneCSMShadowBias(csm);
  }

  function adaptCameraClip() {
    if (!camera) return;
    var originDist = camera.position.length();
    var far = Math.max(2000, originDist * 5);
    var near = Math.max(0.1, far / 5000);
    if (camera.far !== far || camera.near !== near) {
      camera.far = far;
      camera.near = near;
      camera.updateProjectionMatrix();
      refitCSM();
    }
  }

  function bindRuntimeStatsHud() {
    runtimeStatsEl = document.getElementById('game-runtime-stats');
    runtimeStatsFields = {
      frameMs: runtimeStatsEl && runtimeStatsEl.querySelector('[data-runtime-stat="frame-ms"]'),
      drawCalls: runtimeStatsEl && runtimeStatsEl.querySelector('[data-runtime-stat="draw-calls"]'),
      triangles: runtimeStatsEl && runtimeStatsEl.querySelector('[data-runtime-stat="triangles"]'),
      objects: runtimeStatsEl && runtimeStatsEl.querySelector('[data-runtime-stat="objects"]'),
      meshes: runtimeStatsEl && runtimeStatsEl.querySelector('[data-runtime-stat="meshes"]')
    };
  }

  function formatRuntimeCount(value) {
    return Math.round(value || 0).toLocaleString();
  }

  function countRuntimeSceneObjects() {
    var counts = { objects: 0, meshes: 0 };
    if (!scene) return counts;
    scene.traverse(function(object) {
      counts.objects += 1;
      if (object.isMesh) counts.meshes += 1;
    });
    return counts;
  }

  function updateRuntimeStats(frameTimeMs, now) {
    if (!runtimeStatsEl || !runtimeStatsFields.frameMs || typeof frameTimeMs !== 'number') return;
    var timestamp = typeof now === 'number' ? now : performance.now();
    if (timestamp - runtimeStatsLastUpdate < 250) return;
    runtimeStatsLastUpdate = timestamp;
    var renderInfo = renderer.info && renderer.info.render;
    var counts = countRuntimeSceneObjects();
    runtimeStatsFields.frameMs.textContent = frameTimeMs.toFixed(1) + ' ms';
    runtimeStatsFields.drawCalls.textContent = formatRuntimeCount(renderInfo && renderInfo.calls);
    runtimeStatsFields.triangles.textContent = formatRuntimeCount(renderInfo && renderInfo.triangles);
    runtimeStatsFields.objects.textContent = formatRuntimeCount(counts.objects);
    runtimeStatsFields.meshes.textContent = formatRuntimeCount(counts.meshes);
  }

  function render(frameTimeMs, now) {
    if (!renderer) return;
    adaptCameraClip();
    updateEditorGrid();
    renderer.render(scene, camera);
    updateRuntimeStats(frameTimeMs, now);
    if (inspector) inspector.sync();
  }

  function tick(now) {
    if (!active) return;
    var deltaTime = Math.min(clock.getDelta(), 0.05);
    var frameTimeMs = runtimeStatsLastFrameTime === null || typeof now !== 'number'
      ? deltaTime * 1000
      : now - runtimeStatsLastFrameTime;
    runtimeStatsLastFrameTime = typeof now === 'number' ? now : runtimeStatsLastFrameTime;
    playMode.update(deltaTime);
    if (csm) csm.update();
    cameraControls.update(deltaTime);
    render(frameTimeMs, now);
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
    refitCSM();
    render();
  }

  function setGameOutlineHeight(height) {
    var panel = document.querySelector('[data-action-panel-content="game"]');
    var resizer = document.getElementById('game-side-resizer');
    if (!panel || !resizer) return;
    var rect = panel.getBoundingClientRect();
    if (rect.height <= 0) return;
    var resizerHeight = resizer.getBoundingClientRect().height || 6;
    var minHeight = 96;
    var maxHeight = Math.max(minHeight, rect.height - resizerHeight - 160);
    var nextHeight = Math.max(minHeight, Math.min(maxHeight, height));
    panel.style.setProperty('--game-outline-height', Math.round(nextHeight) + 'px');
    resizer.setAttribute('aria-valuemin', String(minHeight));
    resizer.setAttribute('aria-valuemax', String(Math.round(maxHeight)));
    resizer.setAttribute('aria-valuenow', String(Math.round(nextHeight)));
  }

  function setGameOutlineHeightFromPointer(event) {
    var panel = document.querySelector('[data-action-panel-content="game"]');
    var resizer = document.getElementById('game-side-resizer');
    if (!panel || !resizer) return;
    var rect = panel.getBoundingClientRect();
    var resizerHeight = resizer.getBoundingClientRect().height || 6;
    setGameOutlineHeight(event.clientY - rect.top - resizerHeight / 2);
  }

  function finishSidePanelResize(event) {
    if (!sideResizeState) return;
    var resizer = document.getElementById('game-side-resizer');
    if (resizer && resizer.releasePointerCapture && event && event.pointerId === sideResizeState.pointerId) {
      try { resizer.releasePointerCapture(event.pointerId); } catch (e) {}
    }
    sideResizeState = null;
    document.body.classList.remove('is-resizing-game-side');
  }

  function bindSidePanelResize() {
    var resizer = document.getElementById('game-side-resizer');
    var outline = document.getElementById('game-scene-outline');
    if (!resizer || !outline) return;
    resizer.addEventListener('pointerdown', function(event) {
      if (event.button !== 0) return;
      event.preventDefault();
      sideResizeState = { pointerId: event.pointerId };
      document.body.classList.add('is-resizing-game-side');
      if (resizer.setPointerCapture) resizer.setPointerCapture(event.pointerId);
      setGameOutlineHeightFromPointer(event);
    });
    window.addEventListener('pointermove', function(event) {
      if (!sideResizeState) return;
      event.preventDefault();
      setGameOutlineHeightFromPointer(event);
    });
    window.addEventListener('pointerup', finishSidePanelResize);
    window.addEventListener('pointercancel', finishSidePanelResize);
    resizer.addEventListener('keydown', function(event) {
      var step = 20;
      var current = outline.getBoundingClientRect().height;
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        setGameOutlineHeight(current - step);
      } else if (event.key === 'ArrowDown') {
        event.preventDefault();
        setGameOutlineHeight(current + step);
      } else if (event.key === 'Home') {
        event.preventDefault();
        setGameOutlineHeight(0);
      } else if (event.key === 'End') {
        event.preventDefault();
        setGameOutlineHeight(Number.MAX_SAFE_INTEGER);
      }
    });
    setGameOutlineHeight(outline.getBoundingClientRect().height);
  }

  function bindInput() {
    var toolbar = document.getElementById('game-toolbar');
    var sceneAssetGrid = document.getElementById('scene-asset-grid');
    if (toolbar) toolbar.addEventListener('pointerdown', beginAssetDrag);
    if (sceneAssetGrid) sceneAssetGrid.addEventListener('pointerdown', beginAssetDrag);
    window.addEventListener('pointermove', function(event) {
      if (sideResizeState) return;
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
      if (playMode.isPlaying()) return;
      if (cameraControls.isLooking()) {
        cameraControls.adjustMoveSpeed(event);
        return;
      }
      cameraControls.zoomView(event);
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
    if (lightInput) {
      lightInput.addEventListener('input', function() {
        if (ambientLight) ambientLight.intensity = parseFloat(lightInput.value) || 0;
        render();
      });
    }
  }

  // createCharacterMaterial/createWhiteboxToonMaterial only call
  // csm.setupMaterial() at creation time, guarded by whether CSM has
  // finished loading yet -- but a scene auto-restored on page load
  // (scenePersistence.restoreScene(), below) can finish creating all its
  // whitebox/character materials before the CSM addon's dynamic import
  // resolves, since both are async and there's no ordering guarantee
  // between them. Those materials would otherwise be stuck rendering with
  // plain (non-cascaded) lighting forever. Run once, right when CSM becomes
  // ready, to catch up on whatever already exists; needsUpdate is required
  // because setupMaterial() alone doesn't force an already-compiled
  // material's shader program to recompile.
  function applyCSMToExistingMaterials() {
    if (!csm || !sceneState) return;
    function setupMesh(node) {
      if (!node.isMesh || !node.material) return;
      var materials = Array.isArray(node.material) ? node.material : [node.material];
      materials.forEach(function(material) {
        if (!material.isMeshToonMaterial) return;
        csm.setupMaterial(material);
        material.needsUpdate = true;
      });
    }
    sceneState.getCharacters().forEach(function(root) { root.traverse(setupMesh); });
    sceneState.getCollidables().forEach(function(root) { root.traverse(setupMesh); });
  }

  function initGameWorkbench() {
    var THREE = safeThree();
    if (initialized || !THREE) return;
    sceneHost = document.getElementById('game-scene-host');
    dragPreview = document.getElementById('game-drag-preview');
    runButton = document.getElementById('game-run-button');
    runLabel = document.getElementById('game-run-label');
    speedInput = document.getElementById('game-speed-input');
    lightInput = document.getElementById('game-light-input');
    bindRuntimeStatsHud();
    GW.state.statusText = document.getElementById('game-status');
    gameWorkbench = document.getElementById('game-workbench');
    outlineBody = document.querySelector('#game-scene-outline .action-outline-body');
    if (!sceneHost) return;
    sceneOutliner = GW.createSceneOutliner({
      body: outlineBody,
      onSelect: selectSceneObject
    });
    sceneState = GW.createSceneState({ getScene: function() { return scene; } });
    history = GW.createHistory();
    inspector = GW.createInspector({
      getSelectedObject: function() { return selectedObject; },
      captureTransform: captureTransform,
      commitTransform: commitTransformChange,
      renameObject: renameSelectedObject
    });
    sceneCommands = GW.createSceneCommands({
      addCharacter: function(character, index) { sceneState.addCharacter(character, index); },
      addSceneModel: addSceneModel,
      applyTransform: applyTransform,
      getModelSelectionTarget: getModelSelectionTarget,
      rebuildSceneOutline: rebuildSceneOutline,
      refreshAfterTransform: refreshAfterTransform,
      removeCharacter: removeCharacter,
      removeSceneModel: removeSceneModel,
      selectSceneObject: selectSceneObject
    });
    scenePersistence = GW.createScenePersistence({
      clearSceneObjects: clearSceneObjects,
      ensureInit: initGameWorkbench,
      isInitialized: function() { return initialized; },
      rebuildSceneOutline: rebuildSceneOutline,
      render: render,
      restoreSceneSnapshot: restoreSceneSnapshot,
      serializeScene: function() { return sceneState.serialize(); },
      setStatus: setStatus
    });

    if (!window.VC_RENDER_PROFILE) {
      setStatus('Render profile module 未加载');
      return;
    }
    window.VC_RENDER_PROFILE.configureColorManagement(THREE);
    THREE.Object3D.DEFAULT_UP.set(0, 0, 1);
    scene = new THREE.Scene();
    scene.background = new THREE.Color(DEFAULT_EDITOR_SKY_COLOR);
    camera = new THREE.PerspectiveCamera(50, 1, 0.1, 2000);
    camera.up.set(0, 0, 1);
    camera.position.set(10, -16, 8);
    camera.lookAt(0, 0, 0);
    renderer = window.VC_RENDER_PROFILE.createRenderer(THREE, {
      antialias: true,
      preserveDrawingBuffer: false,
      shadowQuality: 'high'
    });
    renderer.domElement.tabIndex = 0;
    sceneHost.appendChild(renderer.domElement);

    // Cascaded shadow maps instead of a single sun: the scene renders
    // immediately with hemisphere/ambient light only, and shadows fade in a
    // moment later once the CSM addon's dynamic import resolves (same
    // fire-and-forget pattern gw_character.js uses for the avatar GLTF).
    window.VC_RENDER_PROFILE.createCascadedShadowLighting(THREE, scene, camera, {
      includeAmbient: true,
      ambientIntensity: lightInput ? parseFloat(lightInput.value) : 0.5,
      shadowQuality: 'high'
    }).then(function(lighting) {
      ambientLight = lighting.ambient;
      csm = lighting.csm;
      GW.state.csm = csm;
      applyCSMToExistingMaterials();
    }).catch(function(error) {
      var message = error && error.message ? error.message : String(error || '未知错误');
      setStatus('阴影系统加载失败: ' + message);
    });
    editorEnvironment = window.VC_RENDER_PROFILE.applyEnvironment(THREE, renderer, scene, {
      shadowQuality: 'high'
    });
    createGround();
    createGrid();

    raycaster = new THREE.Raycaster();
    mouse = new THREE.Vector2();
    groundPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
    hitPoint = new THREE.Vector3();
    clock = new THREE.Clock();
    playMode = createPlayModeController({
      camera: camera,
      renderer: renderer,
      onChange: syncRunState,
      sampleGroundHeight: sampleGroundHeight,
      sampleCameraObstacle: sampleCameraObstacle,
      getCollider: function() { return playCollider; }
    });
    cameraControls = GW.createGameCameraController({
      camera: camera,
      sceneHost: sceneHost,
      speedInput: speedInput,
      playMode: playMode,
      getDragState: function() { return dragState; },
      getSelectedObjectFrame: getSelectedObjectFrame,
      screenToGround: screenToGround,
      pickCharacter: pickCharacter,
      isTransformControlActive: isTransformControlActive
    });
    if (speedInput) cameraControls.setMoveSpeed(speedInput.value);
    cameraControls.syncRotationFromCamera();
    bindTransformModeButtons();
    bindSidePanelResize();
    bindInput();
    assetLoader = GW.createAssetLoader({
      ensureInit: initGameWorkbench,
      getScene: function() { return scene; },
      getSelectedObject: function() { return selectedObject; },
      selectSceneObject: selectSceneObject,
      addSceneModel: addSceneModel,
      rebuildSceneOutline: rebuildSceneOutline,
      render: render,
      scheduleSave: scheduleSave
    });
    if (pendingSceneRootStatus) {
      scenePersistence.applySceneRootStatus(pendingSceneRootStatus);
      pendingSceneRootStatus = null;
    }
    initialized = true;
    resize();
    if (scenePersistence.isSceneRootReady()) scenePersistence.restoreScene();
    else scenePersistence.loadSceneRootForWorkbench();
    setStatus('');
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
      runtimeStatsLastFrameTime = null;
      runtimeStatsLastUpdate = 0;
      rafId = requestAnimationFrame(tick);
    }
  }

  window.VC_GAME_WORKBENCH = {
    init: initGameWorkbench,
    resize: resize,
    setActive: setActive,
    loadGLB: loadGLB,
    syncFromHoudini: syncFromHoudini,
    newScene: newScene,
    saveSceneNow: saveSceneNow
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindSyncButtons);
  } else {
    bindSyncButtons();
  }
  window.addEventListener('scene-root-changed', function(event) {
    if (scenePersistence) scenePersistence.applySceneRootStatus(event.detail || {});
    else pendingSceneRootStatus = event.detail || {};
  });
})();
