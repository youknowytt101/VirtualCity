// Domain: scene-project
// Owns: Editor left action buttons and scene project root directory persistence.
// AI handoff: For editor left action buttons or scene root dialog issues, check /scene-root and /open-scene-root.
(function() {
  'use strict';

  var actions = document.getElementById('editor-left-actions');
  var dialog = document.getElementById('scene-root-dialog');
  var backdrop = document.getElementById('scene-root-backdrop');
  var form = document.getElementById('scene-root-form');
  var input = document.getElementById('scene-root-input');
  var status = document.getElementById('scene-root-status');
  var title = document.getElementById('scene-root-title');
  var hint = document.getElementById('scene-root-hint');
  var rootLabel = document.getElementById('scene-root-label');
  var submitBtn = document.getElementById('scene-root-submit');
  var closeBtn = document.getElementById('scene-root-close');
  var cancelBtn = document.getElementById('scene-root-cancel');
  var pendingDialogAction = '';
  if (!actions) return;

  function showStatus(text) {
    if (status) status.textContent = text || '';
  }

  function applyStatus(d) {
    if (!d) return;
    if (input && document.activeElement !== input) input.value = d.scene_root || '';
    if (d.scene_root && d.scene_root_exists === false) showStatus('目录不存在');
  }

  function announceSceneRootChanged(sceneRoot) {
    try {
      window.dispatchEvent(new CustomEvent('scene-root-changed', { detail: sceneRoot || {} }));
    } catch (e) {
      window.dispatchEvent(new Event('scene-root-changed'));
    }
  }

  function sceneApi() {
    return window.VC_GAME_WORKBENCH || {};
  }

  function saveCurrentScene() {
    var api = sceneApi();
    if (typeof api.saveSceneNow === 'function') api.saveSceneNow();
  }

  function createNewProject() {
    var api = sceneApi();
    if (typeof api.newScene === 'function') api.newScene();
  }

  function openDialog(label, action) {
    if (!dialog) return;
    pendingDialogAction = action || '';
    if (title && label) title.textContent = label;
    if (hint) {
      hint.textContent = pendingDialogAction === 'new'
        ? '选择工程的初始创建根目录。'
        : '设置或新增一个场景工程根目录。';
    }
    if (rootLabel) rootLabel.textContent = pendingDialogAction === 'new' ? '工程初始创建根目录' : '场景工程根目录';
    if (submitBtn) submitBtn.textContent = pendingDialogAction === 'new' ? '创建' : '保存';
    showStatus('');
    dialog.hidden = false;
    if (backdrop) backdrop.hidden = false;
    if (dialog.showModal && !dialog.open) {
      dialog.showModal();
    } else {
      dialog.hidden = false;
      dialog.setAttribute('open', '');
    }
    if (input) {
      input.focus();
      input.select();
    }
  }

  function closeDialog() {
    if (!dialog) return;
    if (dialog.open && dialog.close) dialog.close();
    dialog.removeAttribute('open');
    dialog.hidden = true;
    pendingDialogAction = '';
    if (backdrop) backdrop.hidden = true;
  }

  function saveSceneRoot() {
    if (!input) return;
    if (pendingDialogAction === 'new' && !input.value.trim()) {
      showStatus('请先选择工程的初始创建根目录');
      return;
    }
    showStatus('保存中...');
    fetch('/scene-root', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: input.value.trim() })
    })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        showStatus(d && d.message ? d.message : '已保存');
        if (d && d.scene_root) {
          applyStatus(d.scene_root);
          announceSceneRootChanged(d.scene_root);
        }
        if (d && d.ok && pendingDialogAction === 'new') {
          createNewProject();
          closeDialog();
        }
      })
      .catch(function() { showStatus('保存失败'); });
  }

  function openSceneRoot() {
    fetch('/open-scene-root', { method: 'POST' })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d && d.ok) return;
        openDialog('打开场景工程根目录');
        showStatus(d && d.message ? d.message : '打开失败');
      })
      .catch(function() {
        openDialog('打开场景工程根目录');
        showStatus('打开失败');
      });
  }

  fetch('/scene-root')
    .then(function(r) { return r.json(); })
    .then(function(d) {
      applyStatus(d);
      announceSceneRootChanged(d);
    })
    .catch(function() {});

  actions.addEventListener('click', function(event) {
    var button = event.target.closest('[data-editor-action]');
    if (!button) return;
    var action = button.dataset.editorAction;
    if (action === 'new') {
      openDialog('新建工程', 'new');
      return;
    }
    if (action === 'save') {
      saveCurrentScene();
      openDialog('保存场景');
      return;
    }
    if (action === 'open-root') {
      openSceneRoot();
      return;
    }
    if (action === 'settings') return;
  });

  if (form) {
    form.addEventListener('submit', function(event) {
      event.preventDefault();
      saveSceneRoot();
    });
  }
  if (closeBtn) closeBtn.addEventListener('click', closeDialog);
  if (cancelBtn) cancelBtn.addEventListener('click', closeDialog);
  if (backdrop) backdrop.addEventListener('click', closeDialog);
  if (dialog) {
    dialog.addEventListener('cancel', function() {
      dialog.hidden = true;
      if (backdrop) backdrop.hidden = true;
    });
    dialog.addEventListener('close', function() {
      dialog.hidden = true;
      if (backdrop) backdrop.hidden = true;
    });
  }
})();
