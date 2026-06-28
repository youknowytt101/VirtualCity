// DCC software path and bridge controls.

// Domain: dcc-bridge
// Owns: DCC software paths, Houdini launch/probe state, and DCCbridge open/close controls.
// AI handoff: For Houdini badge or software path issues, start with saveSoftwarePath, setHoudiniBadge, and updateDccSoftwarePaths.
function setStatusRow(rowId, valueId, state, text, title) {
  var row = document.getElementById(rowId);
  var value = document.getElementById(valueId);
  if (!row || !value) return;
  row.className = 'status-row status-' + state;
  value.textContent = text;
  row.title = title || text;
}

function updateSoftwarePath(paths) {
  var input = document.getElementById('houdini-path-input');
  var note = document.getElementById('houdini-path-note');
  if (!input || !note || !paths) return;
  var value = paths.houdini_exe || '';
  if (document.activeElement !== input) {
    input.value = value;
  }
  if (!value) {
    note.textContent = '未设置软件路径';
    note.style.color = '';
  } else if (paths.houdini_exe_exists) {
    note.textContent = '已设置: ' + value;
    note.style.color = 'var(--accent)';
  } else {
    note.textContent = '文件不存在: ' + value;
    note.style.color = 'var(--accent)';
  }
}

function saveSoftwarePath(refreshAfter) {
  var input = document.getElementById('houdini-path-input');
  var note = document.getElementById('houdini-path-note');
  if (!input) return Promise.resolve({ ok: false });
  return fetch('/software-paths', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ houdini_exe: input.value || '' })
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.software_paths) {
      updateSoftwarePath(d.software_paths);
      updateDccSoftwarePaths(d.software_paths);
    }
    if (!d.ok && note) {
      note.textContent = d.message || '保存失败';
      note.style.color = 'var(--accent)';
    }
    if (refreshAfter) refreshServiceState();
    return d;
  })
  .catch(function(e) {
    if (note) {
      note.textContent = '保存失败: ' + e;
      note.style.color = 'var(--accent)';
    }
    return { ok: false, message: String(e) };
  });
}

function updateHoudiniStatusPanel(available, asset) {
  setStatusRow(
    'houdini-connection-row',
    'houdini-connection-value',
    available ? 'ok' : 'off',
    available ? '在线' : '离线',
    available ? 'Houdini RPYC 已连接' : '需要先打开 Houdini 并启用 RPYC 18811'
  );

  var whitebox = asset && asset.whitebox ? asset.whitebox : null;
  var qaOk = !!(asset && asset.qa_ok);
  var modelReady = !!(asset && asset.model_ready);
  var previewReady = !!(asset && asset.preview_ready);
  var exportReady = !!(asset && asset.export_ready);
  var message = asset && asset.message ? asset.message : '';
  var assetText = '等待生成';
  var assetState = 'warn';
  var assetTitle = message || 'Houdini 生成完成后会写入白盒预览产物';

  if (!available && !previewReady) {
    assetText = '等待 Houdini';
    assetState = 'off';
    assetTitle = message || '需要先打开 Houdini 并生成当前区域';
  } else if (previewReady && modelReady) {
    assetText = '白盒可预览 / 现场可用';
    assetState = 'ok';
    assetTitle = whitebox && whitebox.path ? whitebox.path : assetTitle;
  } else if (previewReady) {
    assetText = '白盒可预览';
    assetState = 'ok';
    assetTitle = whitebox && whitebox.path ? whitebox.path : assetTitle;
  } else if (qaOk && modelReady) {
    assetText = 'QA 通过 / 等待白盒';
    assetState = 'warn';
  } else if (qaOk) {
    assetText = 'QA 通过 / 现场缺失';
    assetState = 'warn';
  } else if (asset && asset.status === 'completed') {
    assetText = '构建完成 / 待预览';
    assetState = 'warn';
  } else if (asset && asset.status) {
    assetText = 'Houdini ' + asset.status;
    assetState = 'warn';
  }

  if (whitebox && !whitebox.available && whitebox.message) {
    assetTitle = whitebox.message;
  }

  setStatusRow(
    'houdini-asset-row',
    'houdini-asset-value',
    assetState,
    assetText,
    assetTitle
  );
  setStatusRow(
    'houdini-export-row',
    'houdini-export-value',
    exportReady ? 'ok' : 'warn',
    exportReady ? '可导出' : '等待资产',
    exportReady ? '当前 Houdini 模型可导出 FBX' : '需要 Houdini 在线、Model QA 通过，并且 OUT_city 现场几何可用'
  );
}

function setHoudiniBadge(available, asset) {
  var el = document.getElementById('houdini-badge');
  el.disabled = false;
  if (available) {
    el.className = 'badge badge-ok';
    el.textContent = 'Houdini 已连接';
    el.title = 'Houdini 已打开并可连接；点击刷新状态';
  } else {
    el.className = 'badge badge-warn';
    el.textContent = '打开 Houdini';
    el.title = '启动输入路径里的 Houdini';
  }
  updateHoudiniStatusPanel(available, asset || null);
  if (available) setDccSoftwareSwitch('houdini', true);
}

function setHoudiniChecking(text) {
  var el = document.getElementById('houdini-badge');
  el.className = 'badge badge-warn';
  el.textContent = text || '处理中...';
  el.disabled = true;
  setStatusRow('houdini-connection-row', 'houdini-connection-value', 'warn', '处理中', '正在处理 Houdini 连接');
}

function openOrProbeHoudini() {
  var badge = document.getElementById('houdini-badge');
  var connected = badge && badge.classList.contains('badge-ok');
  if (connected) {
    setHoudiniChecking('刷新中...');
    refreshServiceState();
    return;
  }
  setHoudiniChecking('启动中...');
  saveSoftwarePath(false).then(function() {
    var input = document.getElementById('houdini-path-input');
    return fetch('/open-houdini', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ houdini_exe: input ? input.value : '' })
    });
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.software_paths) {
      updateSoftwarePath(d.software_paths);
      updateDccSoftwarePaths(d.software_paths);
    }
    if (!d.ok) {
      var note = document.getElementById('houdini-path-note');
      if (note) {
        note.textContent = d.message || '启动失败';
        note.style.color = 'var(--accent)';
      }
      refreshServiceState();
      return;
    }
    setDccSoftwareSwitch('houdini', true);
    pollHoudiniAfterOpen(8);
  })
  .catch(function(e) {
    var note = document.getElementById('houdini-path-note');
    if (note) {
      note.textContent = '启动失败: ' + e;
      note.style.color = 'var(--accent)';
    }
    refreshServiceState();
  });
}

function dccSoftwareId(row) {
  return row ? (row.getAttribute('data-dcc-id') || '').trim() : '';
}

function dccSoftwarePathKey(row) {
  var softwareId = dccSoftwareId(row);
  return softwareId ? softwareId + '_exe' : '';
}

function dccPathStorageKey(row) {
  return dccPathCachePrefix + dccSoftwareId(row);
}

function legacyDccPathStorageKey(row) {
  return legacyDccPathCachePrefix + dccSoftwareId(row);
}

function getCachedDccPath(row) {
  try {
    return localStorage.getItem(dccPathStorageKey(row)) || localStorage.getItem(legacyDccPathStorageKey(row)) || '';
  } catch (e) {
    return '';
  }
}

function setCachedDccPath(row, value) {
  try {
    if (value) localStorage.setItem(dccPathStorageKey(row), value);
    else localStorage.removeItem(dccPathStorageKey(row));
    localStorage.removeItem(legacyDccPathStorageKey(row));
  } catch (e) {}
}

function clearDccPathCache() {
  try {
    var keys = [];
    for (var i = 0; i < localStorage.length; i++) {
      var key = localStorage.key(i);
      if (key && (key.indexOf(dccPathCachePrefix) === 0 || key.indexOf(legacyDccPathCachePrefix) === 0)) keys.push(key);
    }
    keys.forEach(function(key) {
      localStorage.removeItem(key);
    });
  } catch (e) {}
  document.querySelectorAll('.dcc-option-row').forEach(function(row) {
    var input = row.querySelector('.dcc-path-input');
    if (input) input.value = '';
    row.classList.remove('has-path');
    closeDccPathEditor(row);
  });
}

function updateDccSoftwarePaths(paths) {
  if (!paths) return;
  document.querySelectorAll('.dcc-option-row').forEach(function(row) {
    var input = row.querySelector('.dcc-path-input');
    var key = dccSoftwarePathKey(row);
    if (!input || !key) return;
    var value = paths[key] || getCachedDccPath(row);
    if (document.activeElement !== input) input.value = value;
    row.classList.toggle('has-path', !!value);
  });
}

function setDccSoftwareSwitch(softwareId, enabled) {
  var row = document.querySelector('.dcc-option-row[data-dcc-id="' + softwareId + '"]');
  var toggle = row ? row.querySelector('.dcc-toggle') : null;
  if (!row || !toggle) return;
  toggle.classList.toggle('is-on', enabled);
  toggle.setAttribute('aria-pressed', enabled ? 'true' : 'false');
  row.classList.toggle('is-enabled', enabled);
}

function saveDccSoftwarePath(row) {
  var input = row ? row.querySelector('.dcc-path-input') : null;
  var softwareId = dccSoftwareId(row);
  if (!input || !softwareId) return Promise.resolve({ ok: false });
  var value = input.value.trim();
  setCachedDccPath(row, value);
  row.classList.toggle('has-path', !!value);
  return fetch('/software-paths', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ software_id: softwareId, path: value })
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.software_paths) {
      updateSoftwarePath(d.software_paths);
      updateDccSoftwarePaths(d.software_paths);
    }
    if (d.ok) row.classList.toggle('has-path', !!input.value.trim());
    return d;
  });
}

function closeDccPathEditor(row) {
  var pathBtn = row ? row.querySelector('.dcc-path-btn') : null;
  var editor = row ? row.querySelector('.dcc-path-editor') : null;
  if (pathBtn) {
    pathBtn.classList.remove('is-open');
    pathBtn.setAttribute('aria-expanded', 'false');
  }
  if (editor) editor.hidden = true;
}

function saveAndCloseDccPathEditor(row) {
  if (!row) return;
  saveDccSoftwarePath(row).then(function(d) {
    if (!d || d.ok) closeDccPathEditor(row);
  });
}

function openDccSoftware(row, toggle) {
  var input = row ? row.querySelector('.dcc-path-input') : null;
  var softwareId = dccSoftwareId(row);
  if (!row || !toggle || !softwareId) return;
  toggle.disabled = true;
  fetch('/open-software', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ software_id: softwareId, path: input ? input.value : '' })
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.software_paths) {
      updateSoftwarePath(d.software_paths);
      updateDccSoftwarePaths(d.software_paths);
    }
    var ok = !!d.ok;
    setDccSoftwareSwitch(softwareId, ok);
    if (!ok && input) {
      var pathBtn = row.querySelector('.dcc-path-btn');
      var editor = row.querySelector('.dcc-path-editor');
      input.title = d.message || '软件启动失败';
      if (pathBtn) {
        pathBtn.classList.add('is-open');
        pathBtn.setAttribute('aria-expanded', 'true');
      }
      if (editor) editor.hidden = false;
      input.focus();
    }
  })
  .catch(function(e) {
    toggle.classList.remove('is-on');
    toggle.setAttribute('aria-pressed', 'false');
    row.classList.remove('is-enabled');
    if (input) input.title = '软件启动失败: ' + e;
  })
  .finally(function() {
    toggle.disabled = false;
  });
}

function closeDccSoftware(row, toggle) {
  var softwareId = dccSoftwareId(row);
  if (!row || !toggle || !softwareId) return;
  toggle.disabled = true;
  fetch('/close-software', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ software_id: softwareId })
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.software_paths) {
      updateSoftwarePath(d.software_paths);
      updateDccSoftwarePaths(d.software_paths);
    }
    setDccSoftwareSwitch(softwareId, !d.ok);
    if (!d.ok) toggle.title = d.message || '软件关闭失败';
  })
  .catch(function(e) {
    setDccSoftwareSwitch(softwareId, true);
    toggle.title = '软件关闭失败: ' + e;
  })
  .finally(function() {
    toggle.disabled = false;
  });
}

function bindDccBridgeControls() {
  var panel = document.querySelector('.dcc-bridge-options');
  if (!panel) return;
  var bridge = panel.closest('.dcc-bridge-panel');
  var summary = bridge ? bridge.querySelector('.dcc-bridge-summary') : null;
  if (bridge && summary) {
    bridge.addEventListener('toggle', function() {
      if (bridge.open) {
        updateWorkspaceButtons('');
        summary.classList.add('active');
      } else {
        updateWorkspaceButtons(activeWorkspaceId);
      }
    });
  }
  document.addEventListener('pointerdown', function(event) {
    if (bridge && bridge.open && !bridge.contains(event.target)) bridge.open = false;
    var keepRow = event.target.closest('.dcc-option-row');
    panel.querySelectorAll('.dcc-option-row').forEach(function(row) {
      if (row !== keepRow && row.querySelector('.dcc-path-editor:not([hidden])')) {
        saveAndCloseDccPathEditor(row);
      }
    });
  });
  panel.addEventListener('click', function(event) {
    var toggle = event.target.closest('.dcc-toggle');
    if (toggle && panel.contains(toggle)) {
      var row = toggle.closest('.dcc-option-row');
      if (toggle.classList.contains('is-on')) closeDccSoftware(row, toggle);
      else openDccSoftware(row, toggle);
      return;
    }

    var pathBtn = event.target.closest('.dcc-path-btn');
    if (pathBtn && panel.contains(pathBtn)) {
      var pathRow = pathBtn.closest('.dcc-option-row');
      var editor = pathRow ? pathRow.querySelector('.dcc-path-editor') : null;
      var open = pathBtn.getAttribute('aria-expanded') !== 'true';
      pathBtn.classList.toggle('is-open', open);
      pathBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (editor) {
        editor.hidden = !open;
        var pathInput = editor.querySelector('.dcc-path-input');
        if (open && pathInput) pathInput.focus();
      }
      return;
    }

    var install = event.target.closest('.dcc-install-btn');
    if (!install || !panel.contains(install)) return;
    var installed = install.getAttribute('aria-pressed') !== 'true';
    var installRow = install.closest('.dcc-option-row');
    if (installRow) installRow.classList.toggle('is-installed', installed);
    install.classList.toggle('is-installed', installed);
    install.setAttribute('aria-pressed', installed ? 'true' : 'false');
    install.textContent = installed ? '已安装' : '安装';
  });
  panel.addEventListener('change', function(event) {
    var input = event.target.closest('.dcc-path-input');
    if (!input || !panel.contains(input)) return;
    var row = input.closest('.dcc-option-row');
    if (!row) return;
    saveDccSoftwarePath(row);
  });
  panel.addEventListener('input', function(event) {
    var input = event.target.closest('.dcc-path-input');
    if (!input || !panel.contains(input)) return;
    var row = input.closest('.dcc-option-row');
    if (row) row.classList.toggle('has-path', !!input.value.trim());
  });
  panel.addEventListener('keydown', function(event) {
    var input = event.target.closest('.dcc-path-input');
    if (!input || !panel.contains(input) || event.key !== 'Enter') return;
    event.preventDefault();
    saveAndCloseDccPathEditor(input.closest('.dcc-option-row'));
  });
}
