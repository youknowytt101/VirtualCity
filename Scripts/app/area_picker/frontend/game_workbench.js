// Domain: game-workbench
// Owns: Three.js editor scene, asset drag/drop, transform controls, whitebox import,
//       undo/redo history, and localStorage scene persistence in the game workspace.
// AI handoff: For editor viewport, asset sync, or scene outline issues, start here before checking vc_glb.js.
(function() {
  'use strict';

  var GW = window.VC_GW;
  var sceneHost = null;
  var dragPreview = null;
  var runButton = null;
  var runLabel = null;
  var speedInput = null;
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
  var characters = [];
  var selectedCharacter = null;
  var selectedObject = null;
  var whiteboxLayers = [];
  var sun = null;
  var outlineBody = null;
  var transformControls = null;
  var transformControlsLoading = null;
  var transformMode = 'translate';
  var transformModeButtons = [];
  var sceneModels = [];
  var assetLoader = null;
  var undoStack = [];
  var redoStack = [];
  var transformDragSnapshot = null;
  var saveTimer = null;
  var restoringScene = false;
  var sideResizeState = null;
  var editorGrid = null;
  var sceneOutliner = null;

  var SCENE_STORAGE_KEY = 'vc_game_scene_v1';
  var currentSceneRoot = '';
  var sceneRootReady = false;

  // Aliases into the split modules (gw_core/gw_character/gw_play). These load
  // before game_workbench.js, so VC_GW.* is populated by the time this IIFE runs.
  var setStatus = GW.setStatus;
  var safeThree = GW.safeThree;
  var setOutlineSelected = GW.setOutlineSelected;
  var createCharacter = GW.createCharacter;
  var createPlayModeController = GW.createPlayModeController;

  function syncSelectionHighlight() {
    var playing = playMode && playMode.isPlaying();
    characters.forEach(function(character) {
      var selected = character === selectedObject && !playing;
      character.traverse(function(child) {
        if (child.userData && child.userData.outline) setOutlineSelected(child, selected);
      });
    });
    whiteboxLayers.forEach(function(layer) {
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

  // Height of the ground under (x, y): cast a ray straight down from high above
  // and return the first whitebox surface hit, falling back to the z=0 plane.
  // Injected into the play controller so gravity lands the character on terrain.
  function sampleGroundHeight(x, y) {
    var THREE = safeThree();
    if (!THREE || !raycaster) return 0;
    raycaster.set(new THREE.Vector3(x, y, 100000), new THREE.Vector3(0, 0, -1));
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

  function placeCharacterAt(point) {
    var character = markCharacter(createCharacter());
    character.position.set(point.x, point.y, 0);
    scene.add(character);
    selectSceneObject(character);
    rebuildSceneOutline();
    pushCommand(makeCreateCommand(character));
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

  // Selects any scene object (character or whitebox layer). selectedCharacter is
  // kept set only for characters so character-only ops (run/delete/duplicate) stay
  // no-ops on terrain/buildings/roads layers.
  function selectSceneObject(object) {
    selectedObject = object || null;
    selectedCharacter = (object && object.userData && object.userData.assetType === 'character') ? object : null;
    if (transformControls) {
      if (selectedObject) transformControls.attach(selectedObject);
      else transformControls.detach();
    } else if (selectedObject) {
      ensureTransformControls();
    }
    syncEditOverlays();
    refreshOutlineActive();
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
          var after = captureTransform(selectedObject);
          if (transformChanged(transformDragSnapshot, after)) {
            pushCommand(makeTransformCommand(selectedObject, transformDragSnapshot, after));
          }
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

  // Scene persistence. Characters are procedural, so we only need to store each
  // one's transform (rebuilt via createCharacter on restore) plus the last
  // whitebox URL. Saves are debounced; restore replays the snapshot and is
  // guarded by restoringScene so it never re-triggers a save mid-rebuild.
  function serializeScene() {
    return {
      v: 1,
      models: sceneModels.map(function(model) {
        return {
          url: model.url,
          label: model.label,
          p: model.root.position.toArray(),
          r: [model.root.rotation.x, model.root.rotation.y, model.root.rotation.z],
          s: model.root.scale.toArray()
        };
      }),
      characters: characters.map(function(character) {
        return {
          p: character.position.toArray(),
          r: [character.rotation.x, character.rotation.y, character.rotation.z],
          s: character.scale.toArray()
        };
      })
    };
  }

  function sceneStorageKey() {
    return SCENE_STORAGE_KEY + '::' + (currentSceneRoot ? encodeURIComponent(currentSceneRoot) : 'default');
  }

  function saveScene() {
    saveTimer = null;
    if (restoringScene) return;
    try {
      window.localStorage.setItem(sceneStorageKey(), JSON.stringify(serializeScene()));
    } catch (e) {}
  }

  function scheduleSave() {
    if (restoringScene || saveTimer) return;
    saveTimer = setTimeout(saveScene, 400);
  }

  function clearSceneObjects() {
    if (!scene) return;
    if (playMode) playMode.exit();
    characters.slice().forEach(function(character) {
      scene.remove(character);
    });
    characters = [];
    sceneModels.slice().forEach(function(model) {
      scene.remove(model.root);
    });
    sceneModels = [];
    whiteboxLayers = [];
    undoStack.length = 0;
    redoStack.length = 0;
    selectSceneObject(null);
    rebuildSceneOutline();
  }

  function reloadSceneForCurrentRoot() {
    if (!initialized) return;
    if (saveTimer) {
      clearTimeout(saveTimer);
      saveTimer = null;
    }
    clearSceneObjects();
    restoreScene();
    render();
  }

  function applySceneRootStatus(d) {
    var nextRoot = d && d.scene_root ? String(d.scene_root).trim() : '';
    var changed = !sceneRootReady || nextRoot !== currentSceneRoot;
    currentSceneRoot = nextRoot;
    sceneRootReady = true;
    if (changed) reloadSceneForCurrentRoot();
  }

  function loadSceneRootForWorkbench() {
    fetch('/scene-root')
      .then(function(r) { return r.json(); })
      .then(applySceneRootStatus)
      .catch(function() {
        sceneRootReady = true;
        reloadSceneForCurrentRoot();
      });
  }

  function saveSceneNow() {
    initGameWorkbench();
    if (saveTimer) {
      clearTimeout(saveTimer);
      saveTimer = null;
    }
    saveScene();
    setStatus('场景已保存');
  }

  function newScene() {
    initGameWorkbench();
    if (saveTimer) {
      clearTimeout(saveTimer);
      saveTimer = null;
    }
    clearSceneObjects();
    saveScene();
    render();
    setStatus('已新建场景');
  }

  function refreshWhiteboxLayers() {
    whiteboxLayers = [];
    sceneModels.forEach(function(model) {
      (model.layers || []).forEach(function(layer) {
        whiteboxLayers.push(layer);
      });
    });
  }

  function sceneObjectBelongsToModel(object, model) {
    if (!object || !model) return false;
    var root = object.userData && object.userData.assetRoot ? object.userData.assetRoot : object;
    return root === model.root || (model.layers || []).indexOf(root) >= 0;
  }

  function addSceneModel(model, options) {
    if (!model || !model.root) return null;
    var index = options && typeof options.index === 'number' ? options.index : -1;
    if (index >= 0) sceneModels.splice(index, 0, model);
    else if (sceneModels.indexOf(model) < 0) sceneModels.push(model);
    scene.add(model.root);
    refreshWhiteboxLayers();
    rebuildSceneOutline();
    if (!(options && options.skipHistory)) pushCommand(makeCreateModelCommand(model));
    return model;
  }

  function removeSceneModel(model, options) {
    if (!model || !model.root) return;
    var index = sceneModels.indexOf(model);
    if (index >= 0) sceneModels.splice(index, 1);
    scene.remove(model.root);
    if (sceneObjectBelongsToModel(selectedObject, model)) selectSceneObject(null);
    refreshWhiteboxLayers();
    rebuildSceneOutline();
    return index;
  }

  function makeCreateModelCommand(model) {
    return {
      undo: function() { removeSceneModel(model, { skipHistory: true }); },
      redo: function() { addSceneModel(model, { skipHistory: true }); }
    };
  }

  function restoreSceneModel(item) {
    if (!item || !item.url || !assetLoader) return;
    assetLoader.loadSceneAsset(item.url, null, item.label, {
      restoring: true,
      transform: item
    });
  }

  function restoreScene() {
    var raw = null;
    try { raw = window.localStorage.getItem(sceneStorageKey()); } catch (e) { return; }
    if (!raw) return;
    var data = null;
    try { data = JSON.parse(raw); } catch (e) { return; }
    if (!data || data.v !== 1) return;
    restoringScene = true;
    try {
      (data.characters || []).forEach(function(item) {
        var character = markCharacter(createCharacter());
        if (item.p) character.position.fromArray(item.p);
        if (item.r) character.rotation.set(item.r[0], item.r[1], item.r[2]);
        if (item.s) character.scale.fromArray(item.s);
        scene.add(character);
      });
      var savedModels = data.models || [];
      if (!savedModels.length && data.whitebox) {
        savedModels = [{ url: data.whitebox, label: '模型资产' }];
      }
      savedModels.forEach(restoreSceneModel);
      rebuildSceneOutline();
    } finally {
      restoringScene = false;
    }
  }

  // Thin host wrappers over the asset loader (gw_assets.js). assetLoader is built
  // in initGameWorkbench once scene/sun state exists; ensure init first so a sync
  // triggered from another workspace still mounts the scene before loading.
  function loadGLB(url) {
    initGameWorkbench();
    if (!assetLoader) { setStatus('场景未就绪'); return; }
    assetLoader.loadGLB(url);
  }

  function getSceneOutlineItems() {
    var items = [];
    sceneModels.forEach(function(model) {
      if (model.layers && model.layers.length) {
        model.layers.forEach(function(layer) { items.push(layer); });
      } else {
        items.push(model.root);
      }
    });
    return items.concat(characters);
  }

  function rebuildSceneOutline() {
    if (!sceneOutliner) return;
    sceneOutliner.rebuild(getSceneOutlineItems(), selectedObject);
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
    var pickables = characters.slice();
    sceneModels.forEach(function(model) {
      if (model.layers && model.layers.length) {
        model.layers.forEach(function(layer) { pickables.push(layer); });
      } else if (model.root) {
        pickables.push(model.root);
      }
    });
    return pickables;
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

  function deleteSelectedCharacter() {
    if (!selectedCharacter || playMode.isPlaying()) return false;
    var character = selectedCharacter;
    var index = characters.indexOf(character);
    removeCharacter(character);
    pushCommand(makeDeleteCommand(character, index));
    setStatus('角色已删除');
    return true;
  }

  // Command-pattern history: every reversible edit pushes a { undo, redo } pair.
  // pushCommand clears the redo branch (standard linear-history behavior) and
  // persists. undo/redo just replay the stored closures. scheduleSave keeps
  // localStorage in sync without thrashing on every gizmo frame.
  function pushCommand(command) {
    undoStack.push(command);
    redoStack.length = 0;
    scheduleSave();
  }

  function undoLastAction() {
    if (playMode.isPlaying()) return false;
    var command = undoStack.pop();
    if (!command) return false;
    command.undo();
    redoStack.push(command);
    render();
    scheduleSave();
    return true;
  }

  function redoLastAction() {
    if (playMode.isPlaying()) return false;
    var command = redoStack.pop();
    if (!command) return false;
    command.redo();
    undoStack.push(command);
    render();
    scheduleSave();
    return true;
  }

  function addCharacterToScene(character, index) {
    if (typeof index === 'number' && index >= 0) characters.splice(index, 0, character);
    else if (characters.indexOf(character) < 0) characters.push(character);
    scene.add(character);
  }

  function removeCharacter(character) {
    var index = characters.indexOf(character);
    if (index >= 0) characters.splice(index, 1);
    scene.remove(character);
    if (selectedObject === character) selectSceneObject(null);
    rebuildSceneOutline();
  }

  function makeCreateCommand(character) {
    return {
      undo: function() { removeCharacter(character); },
      redo: function() { addCharacterToScene(character); selectSceneObject(character); rebuildSceneOutline(); }
    };
  }

  function makeDeleteCommand(character, index) {
    return {
      undo: function() { addCharacterToScene(character, index); selectSceneObject(character); rebuildSceneOutline(); },
      redo: function() { removeCharacter(character); }
    };
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

  function makeTransformCommand(object, before, after) {
    return {
      undo: function() { applyTransform(object, before); refreshAfterTransform(object); },
      redo: function() { applyTransform(object, after); refreshAfterTransform(object); }
    };
  }

  function refreshAfterTransform(object) {
    if (selectedObject === object && transformControls) transformControls.attach(object);
    render();
  }

  function duplicateSelectedCharacter() {
    if (!selectedCharacter || playMode.isPlaying()) return false;
    var character = placeCharacterAt(selectedCharacter.position.clone().add({ x: 1, y: 1, z: 0 }));
    character.rotation.copy(selectedCharacter.rotation);
    return true;
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
      duplicateSelectedCharacter();
      return;
    }
    if ((code === 'delete' || code === 'backspace') && deleteSelectedCharacter()) {
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

  function adaptCameraClip() {
    if (!camera) return;
    // Grid plane is z=0. Grow far with viewing height so the (distance-scaled) grid
    // is never clipped, and keep the near/far ratio bounded so the grid shader's
    // inverse-projection reconstruction stays precise instead of buckling into moiré.
    var planeDist = Math.abs(camera.position.z);
    var far = Math.max(2000, planeDist * 5);
    var near = Math.max(0.1, far / 5000);
    if (camera.far !== far || camera.near !== near) {
      camera.far = far;
      camera.near = near;
      camera.updateProjectionMatrix();
    }
  }

  function render() {
    if (!renderer) return;
    adaptCameraClip();
    updateEditorGrid();
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
  }

  function initGameWorkbench() {
    var THREE = safeThree();
    if (initialized || !THREE) return;
    sceneHost = document.getElementById('game-scene-host');
    dragPreview = document.getElementById('game-drag-preview');
    runButton = document.getElementById('game-run-button');
    runLabel = document.getElementById('game-run-label');
    speedInput = document.getElementById('game-speed-input');
    GW.state.statusText = document.getElementById('game-status');
    gameWorkbench = document.getElementById('game-workbench');
    outlineBody = document.querySelector('#game-scene-outline .action-outline-body');
    if (!sceneHost) return;
    sceneOutliner = GW.createSceneOutliner({
      body: outlineBody,
      onSelect: selectSceneObject
    });

    if (THREE.ColorManagement && 'legacyMode' in THREE.ColorManagement) {
      THREE.ColorManagement.legacyMode = false;
    }
    THREE.Object3D.DEFAULT_UP.set(0, 0, 1);
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x666a6c);
    camera = new THREE.PerspectiveCamera(50, 1, 0.1, 2000);
    camera.up.set(0, 0, 1);
    camera.position.set(10, -16, 8);
    camera.lookAt(0, 0, 0);
    renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    if ('outputColorSpace' in renderer) renderer.outputColorSpace = THREE.SRGBColorSpace;
    else renderer.outputEncoding = THREE.sRGBEncoding;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    renderer.domElement.tabIndex = 0;
    sceneHost.appendChild(renderer.domElement);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x8a9bb0, 0.9));
    scene.add(new THREE.AmbientLight(0xb4b8bc, 0.5));  // 灰色环境光，抬升投影暗部
    sun = new THREE.DirectionalLight(0xffffff, 2.0);
    sun.position.set(8, 14, 10);
    sun.castShadow = true;
    sun.shadow.mapSize.set(4096, 4096);
    sun.shadow.camera.near = 0.5;
    sun.shadow.camera.far = 80;
    sun.shadow.camera.left = -40;
    sun.shadow.camera.right = 40;
    sun.shadow.camera.top = 40;
    sun.shadow.camera.bottom = -40;
    sun.shadow.bias = -0.00015;
    sun.shadow.normalBias = 0.03;
    sun.shadow.radius = 1.2;
    scene.add(sun, sun.target);
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
      sampleGroundHeight: sampleGroundHeight
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
      getSun: function() { return sun; },
      getSelectedObject: function() { return selectedObject; },
      selectSceneObject: selectSceneObject,
      addSceneModel: addSceneModel,
      rebuildSceneOutline: rebuildSceneOutline,
      render: render,
      scheduleSave: scheduleSave
    });
    initialized = true;
    resize();
    if (sceneRootReady) restoreScene();
    else loadSceneRootForWorkbench();
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
    applySceneRootStatus(event.detail || {});
  });
})();
