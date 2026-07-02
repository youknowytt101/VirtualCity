// Domain: game-workbench / scene-persistence
// Owns: scene-root scoped localStorage persistence, debounced saves, and restore
//       orchestration. The host supplies scene-specific serialization/restore.
// AI handoff: For save/load bugs, start here; object creation during restore
//             remains in game_workbench.js because it needs scene factories.
(function() {
  'use strict';

  var GW = window.VC_GW || (window.VC_GW = {});
  var SCENE_STORAGE_KEY = 'vc_game_scene_v1';

  GW.createScenePersistence = function(ctx) {
    var currentSceneRoot = '';
    var sceneRootReady = false;
    var saveTimer = null;
    var restoringScene = false;

    function normalizeSceneRootStatus(d) {
      if (!d) return '';
      var root = d.scene_root;
      if (root && typeof root === 'object') root = root.scene_root;
      return root ? String(root).trim() : '';
    }

    function sceneStorageKey() {
      return SCENE_STORAGE_KEY + '::' + (currentSceneRoot ? encodeURIComponent(currentSceneRoot) : 'default');
    }

    function saveScene() {
      saveTimer = null;
      if (restoringScene) return;
      try {
        window.localStorage.setItem(sceneStorageKey(), JSON.stringify(ctx.serializeScene()));
      } catch (e) {
        console.warn('[game-workbench] 场景保存失败', e);
        ctx.setStatus('场景保存失败，本地存储可能已满或被禁用');
      }
    }

    function clearPendingSave() {
      if (!saveTimer) return;
      clearTimeout(saveTimer);
      saveTimer = null;
    }

    function scheduleSave() {
      if (restoringScene || saveTimer) return;
      saveTimer = setTimeout(saveScene, 400);
    }

    function restoreScene() {
      var raw = null;
      try { raw = window.localStorage.getItem(sceneStorageKey()); } catch (e) {
        console.warn('[game-workbench] 读取本地场景存档失败', e);
        ctx.setStatus('本地存档读取失败，已加载空场景');
        ctx.rebuildSceneOutline();
        return;
      }
      if (!raw) {
        ctx.rebuildSceneOutline();
        return;
      }
      var data = null;
      try { data = JSON.parse(raw); } catch (e) {
        console.warn('[game-workbench] 本地场景存档已损坏', e);
        ctx.setStatus('本地存档已损坏，已重置为空场景');
        ctx.rebuildSceneOutline();
        return;
      }
      if (!data || data.v !== 1) {
        console.warn('[game-workbench] 本地场景存档版本不受支持', data);
        ctx.setStatus('本地存档版本不受支持，已加载空场景');
        ctx.rebuildSceneOutline();
        return;
      }
      restoringScene = true;
      try {
        ctx.restoreSceneSnapshot(data);
      } catch (e) {
        console.warn('[game-workbench] 场景恢复失败，部分对象可能未恢复', e);
        ctx.setStatus('本地存档解析出错，部分对象可能未恢复');
        ctx.rebuildSceneOutline();
      } finally {
        restoringScene = false;
      }
    }

    function reloadSceneForCurrentRoot() {
      if (!ctx.isInitialized()) return;
      clearPendingSave();
      ctx.clearSceneObjects();
      restoreScene();
      ctx.render();
    }

    function applySceneRootStatus(d) {
      var nextRoot = normalizeSceneRootStatus(d);
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
      ctx.ensureInit();
      clearPendingSave();
      saveScene();
      ctx.setStatus('场景已保存');
    }

    function newScene() {
      ctx.ensureInit();
      clearPendingSave();
      ctx.clearSceneObjects();
      saveScene();
      ctx.render();
      ctx.setStatus('已新建场景');
    }

    return {
      applySceneRootStatus: applySceneRootStatus,
      clearPendingSave: clearPendingSave,
      isRestoring: function() { return restoringScene; },
      isSceneRootReady: function() { return sceneRootReady; },
      loadSceneRootForWorkbench: loadSceneRootForWorkbench,
      newScene: newScene,
      restoreScene: restoreScene,
      saveSceneNow: saveSceneNow,
      scheduleSave: scheduleSave
    };
  };
})();
