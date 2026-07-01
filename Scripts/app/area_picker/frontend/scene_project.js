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
  var nameLabel = document.getElementById('scene-root-name-label');
  var nameInput = document.getElementById('scene-root-name-input');
  var projectList = document.getElementById('scene-root-project-list');
  var pendingDialogAction = '';
  if (!actions) return;

  // Client-side project registry (name + last-opened, keyed by scene root path).
  // Purely a display/recency convenience for the "打开工程" picker -- the server
  // only ever knows about the raw scene_root path, never a project name.
  var PROJECT_REGISTRY_KEY = 'vc_scene_projects_v1';

  function loadProjectRegistry() {
    try {
      var raw = window.localStorage.getItem(PROJECT_REGISTRY_KEY);
      var list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list : [];
    } catch (e) {
      return [];
    }
  }

  function saveProjectRegistry(list) {
    try {
      window.localStorage.setItem(PROJECT_REGISTRY_KEY, JSON.stringify(list));
    } catch (e) {}
  }

  function projectNameFromPath(root) {
    var parts = String(root || '').split(/[\\/]/).filter(Boolean);
    return parts.length ? parts[parts.length - 1] : root;
  }

  function upsertProject(root, name) {
    root = String(root || '').trim();
    if (!root) return;
    var list = loadProjectRegistry();
    var entry = null;
    for (var i = 0; i < list.length; i++) {
      if (list[i].root === root) { entry = list[i]; break; }
    }
    if (!entry) {
      entry = { root: root, name: name || projectNameFromPath(root) };
      list.push(entry);
    } else if (name) {
      entry.name = name;
    }
    entry.updatedAt = Date.now();
    list.sort(function(a, b) { return (b.updatedAt || 0) - (a.updatedAt || 0); });
    saveProjectRegistry(list);
  }

  function renderProjectList() {
    if (!projectList) return;
    var list = loadProjectRegistry();
    projectList.innerHTML = '';
    if (!list.length) {
      var empty = document.createElement('div');
      empty.className = 'scene-root-project-empty';
      empty.textContent = '还没有已保存的工程，可在下方手动输入根目录打开。';
      projectList.appendChild(empty);
      return;
    }
    list.forEach(function(entry) {
      var item = document.createElement('button');
      item.type = 'button';
      item.className = 'scene-root-project-item';
      var name = document.createElement('span');
      name.className = 'scene-root-project-name';
      name.textContent = entry.name || projectNameFromPath(entry.root);
      var path = document.createElement('span');
      path.className = 'scene-root-project-path';
      path.textContent = entry.root;
      item.appendChild(name);
      item.appendChild(path);
      item.addEventListener('click', function() {
        if (input) input.value = entry.root;
        saveSceneRoot();
      });
      projectList.appendChild(item);
    });
  }

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
    var isNew = pendingDialogAction === 'new';
    var isOpen = pendingDialogAction === 'open';
    if (title && label) title.textContent = label;
    if (hint) {
      hint.textContent = isNew
        ? '选择工程的初始创建根目录，并为工程命名。'
        : isOpen
          ? '从最近的工程中选择，或手动输入要打开的场景工程根目录。'
          : '设置或新增一个场景工程根目录。';
    }
    if (rootLabel) rootLabel.textContent = isNew ? '工程初始创建根目录' : '场景工程根目录';
    if (submitBtn) submitBtn.textContent = isNew ? '创建' : isOpen ? '打开' : '保存';
    if (nameLabel) nameLabel.hidden = !isNew;
    if (nameInput) {
      nameInput.hidden = !isNew;
      if (isNew) nameInput.value = '';
    }
    if (projectList) {
      projectList.hidden = !isOpen;
      if (isOpen) renderProjectList();
    }
    showStatus('');
    dialog.hidden = false;
    if (backdrop) backdrop.hidden = false;
    if (dialog.showModal && !dialog.open) {
      dialog.showModal();
    } else {
      dialog.hidden = false;
      dialog.setAttribute('open', '');
    }
    if (isNew && nameInput) {
      nameInput.focus();
    } else if (input) {
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
    var isNew = pendingDialogAction === 'new';
    var isOpen = pendingDialogAction === 'open';
    if ((isNew || isOpen) && !input.value.trim()) {
      showStatus(isOpen ? '请从最近工程中选择，或输入要打开的场景工程根目录' : '请先选择工程的初始创建根目录');
      return;
    }
    showStatus(isOpen ? '打开中...' : '保存中...');
    var name = isNew && nameInput ? nameInput.value.trim() : '';
    fetch('/scene-root', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: input.value.trim() })
    })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        showStatus(d && d.message ? d.message : (isOpen ? '已打开' : '已保存'));
        if (d && d.scene_root) {
          applyStatus(d.scene_root);
          announceSceneRootChanged(d.scene_root);
        }
        if (d && d.ok && d.scene_root && d.scene_root.scene_root) {
          upsertProject(d.scene_root.scene_root, name);
        }
        if (d && d.ok && isNew) {
          createNewProject();
          closeDialog();
        } else if (d && d.ok && isOpen) {
          closeDialog();
        }
      })
      .catch(function() { showStatus(isOpen ? '打开失败' : '保存失败'); });
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
      if (d && d.scene_root) upsertProject(d.scene_root);
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
    if (action === 'open') {
      openDialog('打开工程', 'open');
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
