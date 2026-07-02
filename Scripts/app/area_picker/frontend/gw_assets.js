// Domain: game-workbench / assets
// Owns: whitebox GLB import — layer tagging/material isolation, and the load
//       orchestrator. registerWhiteboxLayers is pure; the loader takes a ctx
//       of host getters/setters since it mutates scene state.
// AI handoff: For whitebox import or layer tagging, start here; the shared GLB
//             loader is vc_glb.js, scene/selection wiring is game_workbench.js.
//             Shadows are cascaded (CSM) via game_workbench.js/render_profile.js.
(function() {
  'use strict';

  var GW = window.VC_GW || (window.VC_GW = {});
  var safeThree = GW.safeThree;
  var setStatus = GW.setStatus;

  var LAYER_LABELS = { terrain: '地形', buildings: '建筑', roads: '道路' };
  var LAYER_PREFIX = 'VC_whitebox_';
  var WHITEBOX_TOON_COLORS = {
    terrain: 0xaab5ad,
    buildings: 0xb8b8b8,
    roads: 0x747a80
  };
  var WHITEBOX_OUTLINE_THICKNESS = {
    terrain: 0.008,
    buildings: 0.016,
    roads: 0.01
  };

  function createWhiteboxToonMaterial(sourceMaterial, layerKey) {
    var THREE = safeThree();
    if (!THREE) return sourceMaterial;
    var material = new THREE.MeshToonMaterial({
      color: WHITEBOX_TOON_COLORS[layerKey] || 0xb8b8b8,
      gradientMap: GW.getToonGradientMap ? GW.getToonGradientMap() : null,
      emissive: 0x000000,
      side: THREE.DoubleSide
    });
    material.name = 'VC_whitebox_' + (layerKey || 'default') + '_toon';
    if (GW.state.csm) GW.state.csm.setupMaterial(material);
    return material;
  }

  function attachWhiteboxToonOutline(mesh, layerKey) {
    if (!mesh || !mesh.geometry || !GW.createOutlineMesh) return null;
    if (mesh.children && mesh.children.some(function(child) {
      return child.userData && child.userData.whiteboxOutline;
    })) return null;
    var outline = GW.createOutlineMesh(mesh.geometry, WHITEBOX_OUTLINE_THICKNESS[layerKey] || 0.012);
    outline.name = (mesh.name || 'whitebox') + '_toon_outline';
    outline.castShadow = false;
    outline.receiveShadow = false;
    outline.renderOrder = (mesh.renderOrder || 0) - 1;
    outline.userData.whiteboxOutline = true;
    outline.userData.assetType = layerKey || 'whitebox';
    outline.userData.assetRoot = mesh.userData && mesh.userData.assetRoot;
    mesh.add(outline);
    return outline;
  }

  // The GLB nests the layer nodes under a "Root" node (gltf.scene > Root >
  // VC_whitebox_{terrain,buildings,roads}), so we must traverse — not just scan
  // root.children. Tag each layer node pickable, clone its material so per-layer
  // highlight stays isolated, and enable shadows (only buildings cast — terrain/
  // roads stay receive-only to avoid self-shadow acne on the large flat surfaces).
  // Pure: returns the tagged layer-node array for the host to own.
  function registerWhiteboxLayers(root) {
    var layers = [];
    root.traverse(function(node) {
      var name = node.name || '';
      if (name.indexOf(LAYER_PREFIX) !== 0) return;
      var key = name.slice(LAYER_PREFIX.length);
      if (!LAYER_LABELS[key]) return;
      node.userData.assetType = key;
      node.userData.assetRoot = node;
      node.userData.assetLabel = LAYER_LABELS[key];
      var casts = key === 'buildings';
      node.traverse(function(mesh) {
        if (!mesh.isMesh) return;
        if (mesh.userData && mesh.userData.outline) return;
        mesh.material = createWhiteboxToonMaterial(mesh.material, key);
        mesh.castShadow = casts;
        mesh.receiveShadow = true;
        mesh.userData.assetRoot = node;
        attachWhiteboxToonOutline(mesh, key);
      });
      layers.push(node);
    });
    return layers;
  }

  // Load orchestrator. ctx supplies host state access + UI refresh callbacks so the
  // loader can swap the previous model, hand the new layer array back to the host,
  // and trigger outline/render/save — without owning that state itself.
  function applySavedTransform(root, transform) {
    if (!root || !transform) return;
    if (transform.p) root.position.fromArray(transform.p);
    if (transform.r) root.rotation.set(transform.r[0], transform.r[1], transform.r[2]);
    if (transform.s) root.scale.fromArray(transform.s);
  }

  function markModelRoot(root, label) {
    root.userData.assetType = root.userData.assetType || 'model';
    root.userData.assetRoot = root;
    root.userData.assetLabel = label || root.userData.assetLabel || '模型资产';
    root.traverse(function(node) {
      if (!node.userData) node.userData = {};
      if (!node.userData.assetRoot) node.userData.assetRoot = root;
      if (!node.userData.assetType) node.userData.assetType = root.userData.assetType;
    });
  }

  function createAssetLoader(ctx) {
    function loadGLB(url, point, label, options) {
      ctx.ensureInit();
      var scene = ctx.getScene();
      if (!scene) { setStatus('场景未就绪'); return; }
      if (!window.VC_GLB) { setStatus('加载器未就绪'); return; }
      setStatus(label ? ('导入 ' + label + ' 中…') : '导入白盒中…');
      window.VC_GLB.load(url).then(function(root) {
        if (point && root.position && root.position.copy) root.position.copy(point);
        applySavedTransform(root, options && options.transform);
        markModelRoot(root, label);
        var layers = registerWhiteboxLayers(root);
        ctx.addSceneModel({
          root: root,
          url: url,
          label: label || root.userData.assetLabel || '模型资产',
          layers: layers
        }, { skipHistory: options && options.restoring });
        ctx.rebuildSceneOutline();
        ctx.render();
        if (!(options && options.restoring)) ctx.scheduleSave();
        setStatus(label ? (label + ' 已导入') : '白盒已导入');
      }).catch(function(error) {
        setStatus(label ? (label + ' 导入失败') : '白盒导入失败');
        if (window.console) console.error('GLB load failed:', error);
      });
    }

    function loadSceneAsset(url, point, label, options) {
      loadGLB(url, point, label, options);
    }

    // Load the latest pipeline-produced whitebox (no export — the generation
    // pipeline writes the GLB; cache-bust to dodge stale caches).
    function syncFromHoudini() {
      var whitebox = window.VC_HOUDINI_PREVIEW && window.VC_HOUDINI_PREVIEW.getWhitebox
        ? window.VC_HOUDINI_PREVIEW.getWhitebox()
        : null;
      loadGLB((whitebox && whitebox.url) || ('/whitebox.glb?t=' + Date.now()));
    }

    return { loadGLB: loadGLB, syncFromHoudini: syncFromHoudini, loadSceneAsset: loadSceneAsset };
  }

  GW.registerWhiteboxLayers = registerWhiteboxLayers;
  GW.createWhiteboxToonMaterial = createWhiteboxToonMaterial;
  GW.createAssetLoader = createAssetLoader;
})();
