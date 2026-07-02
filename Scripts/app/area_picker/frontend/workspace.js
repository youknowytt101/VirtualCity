// Workspace switching and shell layout controls.

// Domain: workspace-shell
// Owns: Workspace switching, action panel visibility, shell resizing, refresh/restart controls, and account menu behavior.
// AI handoff: For right panel, workspace tab, or refresh-state issues, start with setWorkspace and syncActionPanelContent.
function updateWorkspaceButtons(workspaceId) {
  var buttons = document.querySelectorAll('[data-workspace-target]');
  Array.prototype.forEach.call(buttons, function(button) {
    var active = button.dataset.workspaceTarget === workspaceId;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
  var dccSummary = document.querySelector('.dcc-bridge-summary');
  if (dccSummary) dccSummary.classList.remove('active');
}

function syncActionPanelContent(workspaceId) {
  var panels = document.querySelectorAll('[data-action-panel-content]');
  Array.prototype.forEach.call(panels, function(panel) {
    panel.hidden = panel.dataset.actionPanelContent !== workspaceId;
  });
}
function syncActionPanelToggle() {
  var workspace = document.getElementById('workspace');
  var actionPanel = document.getElementById('action-panel');
  var toggle = document.getElementById('action-panel-toggle');
  var collapsed = !!actionPanelCollapsed;
  if (workspace) workspace.dataset.actionPanelCollapsed = collapsed ? 'true' : 'false';
  if (actionPanel) actionPanel.hidden = collapsed;
  if (!toggle) return;
  toggle.hidden = false;
  toggle.classList.toggle('is-collapsed', collapsed);
  toggle.setAttribute('aria-pressed', collapsed ? 'true' : 'false');
  toggle.setAttribute('aria-label', collapsed ? '展开右栏' : '收起右栏');
  toggle.title = collapsed ? '展开右栏' : '收起右栏';
}

function setActionPanelCollapsed(collapsed) {
  actionPanelCollapsed = !!collapsed;
  syncActionPanelToggle();
  requestAnimationFrame(function() {
    if (map && map.resize) map.resize();
    if (activeWorkspaceId === 'game' && window.VC_GAME_WORKBENCH) {
      window.VC_GAME_WORKBENCH.resize();
    }
    if (activeWorkspaceId === 'houdini') scheduleGridLoad();
    if (typeof scheduleDeckRefresh === 'function') scheduleDeckRefresh(true);
  });
}

function bindActionPanelToggle() {
  var toggle = document.getElementById('action-panel-toggle');
  if (!toggle) return;
  toggle.addEventListener('click', function() {
    setActionPanelCollapsed(!actionPanelCollapsed);
  });
  syncActionPanelToggle();
}

function setHoudiniOutlineHeight(height) {
  var panel = document.querySelector('[data-action-panel-content="houdini"]');
  var resizer = document.getElementById('houdini-side-resizer');
  if (!panel || !resizer) return;
  var rect = panel.getBoundingClientRect();
  if (rect.height <= 0) return;
  var resizerHeight = resizer.getBoundingClientRect().height || 6;
  var minHeight = 150;
  var maxHeight = Math.max(minHeight, rect.height - resizerHeight - 200);
  var nextHeight = Math.max(minHeight, Math.min(maxHeight, height));
  panel.style.setProperty('--houdini-outline-height', Math.round(nextHeight) + 'px');
  resizer.setAttribute('aria-valuemin', String(minHeight));
  resizer.setAttribute('aria-valuemax', String(Math.round(maxHeight)));
  resizer.setAttribute('aria-valuenow', String(Math.round(nextHeight)));
}

function setHoudiniOutlineHeightFromPointer(event) {
  var panel = document.querySelector('[data-action-panel-content="houdini"]');
  var resizer = document.getElementById('houdini-side-resizer');
  if (!panel || !resizer) return;
  var rect = panel.getBoundingClientRect();
  var resizerHeight = resizer.getBoundingClientRect().height || 6;
  setHoudiniOutlineHeight(rect.bottom - event.clientY - resizerHeight / 2);
}

function finishHoudiniSideResize(event) {
  if (!houdiniSideResizeState) return;
  var resizer = document.getElementById('houdini-side-resizer');
  if (resizer && resizer.releasePointerCapture && event && event.pointerId === houdiniSideResizeState.pointerId) {
    try { resizer.releasePointerCapture(event.pointerId); } catch (e) {}
  }
  houdiniSideResizeState = null;
  document.body.classList.remove('is-resizing-game-side');
}

function bindHoudiniSideResize() {
  var resizer = document.getElementById('houdini-side-resizer');
  var outline = document.getElementById('houdini-run-outline');
  if (!resizer || !outline) return;
  resizer.addEventListener('pointerdown', function(event) {
    if (event.button !== 0) return;
    event.preventDefault();
    houdiniSideResizeState = { pointerId: event.pointerId };
    document.body.classList.add('is-resizing-game-side');
    if (resizer.setPointerCapture) resizer.setPointerCapture(event.pointerId);
    setHoudiniOutlineHeightFromPointer(event);
  });
  window.addEventListener('pointermove', function(event) {
    if (!houdiniSideResizeState) return;
    event.preventDefault();
    setHoudiniOutlineHeightFromPointer(event);
  });
  window.addEventListener('pointerup', finishHoudiniSideResize);
  window.addEventListener('pointercancel', finishHoudiniSideResize);
  resizer.addEventListener('keydown', function(event) {
    var step = 20;
    var current = outline.getBoundingClientRect().height;
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setHoudiniOutlineHeight(current + step);
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      setHoudiniOutlineHeight(current - step);
    } else if (event.key === 'Home') {
      event.preventDefault();
      setHoudiniOutlineHeight(0);
    } else if (event.key === 'End') {
      event.preventDefault();
      setHoudiniOutlineHeight(Number.MAX_SAFE_INTEGER);
    }
  });
}

function refreshAccountMenuUser() {
  var nameEl = document.querySelector('.account-menu .account-name');
  var statusEl = document.getElementById('account-status-text');
  fetch('/auth/me').then(function(response) {
    return response.json();
  }).then(function(res) {
    var user = res && res.user;
    if (nameEl) nameEl.textContent = user ? user.email : 'Settings';
    if (statusEl) statusEl.textContent = user ? '已登录' : '未登录';
  }).catch(function() {});
}

function bindAccountLogout() {
  var logoutButton = document.getElementById('account-logout-btn');
  if (!logoutButton) return;
  logoutButton.addEventListener('click', function() {
    fetch('/auth/logout', { method: 'POST' }).catch(function() {}).finally(function() {
      window.location.href = '/login';
    });
  });
}

function bindAccountMenu() {
  var menu = document.querySelector('.account-menu');
  if (!menu) return;
  document.addEventListener('click', function(event) {
    if (!menu.contains(event.target)) menu.open = false;
  });
  document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') menu.open = false;
  });
  bindAccountLogout();
  refreshAccountMenuUser();
}

function initialWorkspaceId() {
  if (!window.sessionStorage) return activeWorkspaceId;
  try {
    var storedWorkspace = window.sessionStorage.getItem(frontendRefreshWorkspaceKey);
    window.sessionStorage.removeItem(frontendRefreshWorkspaceKey);
    if (storedWorkspace && WORKSPACE_KINDS[storedWorkspace]) return storedWorkspace;
  } catch (e) {}
  return activeWorkspaceId;
}

function bindFrontendRefresh() {
  var refreshButton = document.getElementById('frontend-refresh-button');
  var restartButton = document.getElementById('backend-restart-button');
  if (!refreshButton && !restartButton) return;
  function reloadWithCacheBust() {
    var url = new URL(window.location.href);
    url.searchParams.set('refresh', String(Date.now()));
    window.location.replace(url.toString());
  }
  function rememberWorkspace() {
    try {
      sessionStorage.setItem(frontendRefreshWorkspaceKey, activeWorkspaceId);
    } catch (e) {}
  }
  if (refreshButton) {
    refreshButton.addEventListener('click', function() {
      rememberWorkspace();
      reloadWithCacheBust();
    });
  }
  if (restartButton) {
    restartButton.addEventListener('click', function() {
      rememberWorkspace();
      clearDccPathCache();
      restartButton.classList.add('is-refreshing');
      restartButton.disabled = true;
      fetch('/restart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}'
      })
      .catch(function() {})
      .finally(function() {
        setTimeout(function() {
          restartButton.classList.remove('is-refreshing');
          restartButton.disabled = false;
        }, 2500);
      });
    });
  }
}

function setWorkspace(id) {
  var nextWorkspace = WORKSPACE_KINDS[id] ? id : 'houdini';
  var workspaceKind = WORKSPACE_KINDS[nextWorkspace];
  var previousWorkspace = activeWorkspaceId;
  var workspace = document.getElementById('workspace');
  var mapShell = document.getElementById('map-shell');
  var gameWorkbench = document.getElementById('game-workbench');
  var isHoudini = workspaceKind === 'houdini';
  var showsMap = workspaceKind !== 'game';
  if (workspace) workspace.dataset.workspaceKind = workspaceKind;
  if (mapShell) mapShell.hidden = !showsMap;
  syncActionPanelContent(nextWorkspace);
  syncActionPanelToggle();
  if (gameWorkbench) gameWorkbench.hidden = workspaceKind !== 'game';
  if (window.VC_GAME_WORKBENCH) {
    if (workspaceKind === 'game') {
      window.VC_GAME_WORKBENCH.init();
    }
    window.VC_GAME_WORKBENCH.setActive(workspaceKind === 'game');
  }
  if (WORKSPACE_KINDS[previousWorkspace] === 'houdini' && !isHoudini) {
    setGridVisible(false);
    setPointSelectActive(false);
    if (rectangleToolActive()) disarmRectangleTool();
  }
  activeWorkspaceId = nextWorkspace;
  if (showsMap) activateMapContext(nextWorkspace);
  updateWorkspaceButtons(nextWorkspace);
  if (showsMap) {
    requestAnimationFrame(function() {
      if (map && map.resize) map.resize();
      if (isHoudini) {
        setGridVisible(true);
        syncHoudiniCameraToCity();
        scheduleGridLoad();
      }
      if (typeof scheduleDeckRefresh === 'function') scheduleDeckRefresh(true);
      if (nextWorkspace === 'city-preview') showDefaultCityPreview();
      if (nextWorkspace === 'news') showGlobalOverview();
      else if (cityPreviewActive && nextWorkspace !== 'city-preview' && nextWorkspace !== 'houdini' && showsMap) {
        cityPreviewActive = false;
        exit3DTo2D();
      }
    });
  }
}

function bindWorkspaceSwitching() {
  var buttons = document.querySelectorAll('[data-workspace-target]');
  Array.prototype.forEach.call(buttons, function(button) {
    button.addEventListener('click', function() {
      setWorkspace(button.dataset.workspaceTarget);
    });
  });
}
