var selection = null;
var selectedTileIds = {};
var lastGridData = null;
var gridLayer = null;
var drawnItems = null;
var gridRequestId = 0;
var gridTimer = null;
var maxSelectionTiles = window.VC_CONFIG.maxSelectionTiles;
var shutdownWithPage = window.VC_CONFIG.shutdownWithPage;
var pageSessionTimer = null;
var selectionStorageKey = 'vc.areaPicker.selection.v1';
var pendingRestoreTileIds = null;
var pendingRestoreLogged = false;
var rectangleDrawTool = null;
var pointSelectActive = false;
var selectionToolButtons = {};
var gridRenderer = null;

var map = L.map('map', { zoomControl: false }).setView([window.VC_CONFIG.lat, window.VC_CONFIG.lon], 14);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap contributors', maxZoom: 19
}).addTo(map);
gridRenderer = L.canvas({ padding: 0.35 });
gridLayer = L.layerGroup().addTo(map);
drawnItems = new L.FeatureGroup();
map.addLayer(drawnItems);

rectangleDrawTool = new L.Draw.Rectangle(map, {
  shapeOptions: { color: 'var(--accent)', weight: 2, fillOpacity: 0.02 }
});

function rectangleToolActive() {
  return !!(rectangleDrawTool && rectangleDrawTool.enabled && rectangleDrawTool.enabled());
}

function updateMapToolButtons() {
  if (selectionToolButtons.rectangle) {
    selectionToolButtons.rectangle.classList.toggle('active', rectangleToolActive());
  }
  if (selectionToolButtons.point) {
    selectionToolButtons.point.classList.toggle('active', pointSelectActive);
  }
  if (selectionToolButtons.clear) {
    selectionToolButtons.clear.disabled = !selection;
  }
}

function setPointSelectActive(active) {
  pointSelectActive = !!active;
  if (pointSelectActive && rectangleToolActive()) rectangleDrawTool.disable();
  var method = pointSelectActive ? 'addClass' : 'removeClass';
  L.DomUtil[method](map.getContainer(), 'point-select-active');
  updateMapToolButtons();
}

function activateRectangleTool() {
  setPointSelectActive(false);
  if (rectangleDrawTool && !rectangleToolActive()) rectangleDrawTool.enable();
  updateMapToolButtons();
}

function clearSelectionFromMapTool() {
  setPointSelectActive(false);
  if (rectangleToolActive()) rectangleDrawTool.disable();
  clearSelection();
}

function bindSelectionTools() {
  selectionToolButtons = {
    rectangle: document.querySelector('.map-tool-rectangle'),
    point: document.querySelector('.map-tool-point'),
    clear: document.querySelector('.map-tool-clear')
  };
  if (selectionToolButtons.rectangle) {
    selectionToolButtons.rectangle.addEventListener('click', activateRectangleTool);
  }
  if (selectionToolButtons.point) {
    selectionToolButtons.point.addEventListener('click', function() {
      setPointSelectActive(!pointSelectActive);
    });
  }
  if (selectionToolButtons.clear) {
    selectionToolButtons.clear.addEventListener('click', clearSelectionFromMapTool);
  }
  updateMapToolButtons();
}
bindSelectionTools();

function shortSearchTitle(item) {
  var name = item.name || item.display_name || '';
  if (name) return name;
  var display = item.display_name || '';
  return display.split(',').slice(0, 2).join(', ') || '未知地点';
}

function searchResultMeta(item) {
  var parts = [];
  if (item.type) parts.push(item.type);
  if (item.class) parts.push(item.class);
  if (item.display_name) parts.push(item.display_name);
  return parts.join(' · ');
}

function focusSearchResult(item) {
  var lat = parseFloat(item.lat);
  var lon = parseFloat(item.lon);
  if (!isFinite(lat) || !isFinite(lon)) return;
  if (item.boundingbox && item.boundingbox.length === 4) {
    var south = parseFloat(item.boundingbox[0]);
    var north = parseFloat(item.boundingbox[1]);
    var west = parseFloat(item.boundingbox[2]);
    var east = parseFloat(item.boundingbox[3]);
    if (isFinite(south) && isFinite(north) && isFinite(west) && isFinite(east) && south < north && west < east) {
      map.fitBounds([[south, west], [north, east]], { padding: [40, 40], maxZoom: 15 });
    } else {
      map.setView([lat, lon], 13);
    }
  } else {
    map.setView([lat, lon], 13);
  }
  setText('location-search-status', '已定位：' + shortSearchTitle(item) + '。现在可以点选或框选网格。');
  scheduleGridLoad();
}

function bindLocationSearch() {
  var form = document.getElementById('location-search-form');
  var input = document.getElementById('location-search-input');
  var btn = document.getElementById('location-search-btn');
  if (!form || !input) return;
  form.addEventListener('submit', function(event) {
    event.preventDefault();
    var q = input.value.trim();
    if (!q) {
      setText('location-search-status', '请输入国家、地区、城市或地址。');
      return;
    }
    setText('location-search-status', '正在搜索：' + q);
    if (btn) btn.disabled = true;
    fetch('/geocode?q=' + encodeURIComponent(q))
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (!d.ok) {
        setText('location-search-status', d.message || '搜索失败');
        return;
      }
      var items = d.results || [];
      if (!items.length) {
        setText('location-search-status', '没有找到匹配地点。');
        return;
      }
      focusSearchResult(items[0]);
    })
    .catch(function(e) {
      setText('location-search-status', '搜索失败：' + e);
    })
    .finally(function() {
      if (btn) btn.disabled = false;
    });
  });
}

bindLocationSearch();

map.on(L.Draw.Event.CREATED, function(e) {
  drawnItems.clearLayers();
  e.layer.setStyle({ opacity: 0, fillOpacity: 0 });
  drawnItems.addLayer(e.layer);
  selectTilesByBounds(e.layer.getBounds());
});

map.on(L.Draw.Event.DRAWSTART, function() {
  setPointSelectActive(false);
  updateMapToolButtons();
});

map.on(L.Draw.Event.DRAWSTOP, function() {
  updateMapToolButtons();
});

map.on('click', function(e) {
  if (!pointSelectActive) return;
  selectTileByLatLng(e.latlng);
});
document.getElementById('houdini-path-input').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') {
    e.preventDefault();
    saveSoftwarePath(false);
  }
});
document.getElementById('houdini-path-input').addEventListener('blur', function() {
  saveSoftwarePath(false);
});

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
    if (d.software_paths) updateSoftwarePath(d.software_paths);
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
    if (d.software_paths) updateSoftwarePath(d.software_paths);
    if (!d.ok) {
      var note = document.getElementById('houdini-path-note');
      if (note) {
        note.textContent = d.message || '启动失败';
        note.style.color = 'var(--accent)';
      }
      refreshServiceState();
      return;
    }
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
function updateExportButton(available, running) {
  var btn = document.getElementById('export-btn');
  btn.disabled = !available || !!running;
}

function setRunStatus(state, title, pct, detail) {
  var panel = document.getElementById('run-status-panel');
  var chip = document.getElementById('run-status-chip');
  var titleEl = document.getElementById('run-status-title');
  var pctEl = document.getElementById('run-status-pct');
  var bar = document.getElementById('run-status-bar');
  var detailEl = document.getElementById('run-status-detail');
  if (!panel || !chip || !titleEl || !pctEl || !bar || !detailEl) return;
  var n = Math.max(0, Math.min(100, Number(pct) || 0));
  panel.className = 'run-status-panel status-' + state;
  chip.textContent = title;
  titleEl.textContent = title;
  pctEl.textContent = n + '%';
  bar.style.width = n + '%';
  if (state === 'ok') {
    bar.style.background = 'var(--accent)';
  } else if (state === 'off') {
    bar.style.background = 'var(--accent)';
  } else if (state === 'warn') {
    bar.style.background = 'var(--accent)';
  } else {
    bar.style.background = 'var(--accent)';
  }
  detailEl.textContent = detail || '等待任务';
}

function failureMetricsLine(summary) {
  if (!summary) return '';
  if (summary.metrics_line) return summary.metrics_line;
  var metrics = summary.metrics || [];
  return metrics.slice(0, 6).map(function(item) {
    return (item.label || item.key || 'metric') + '=' + (item.value_label || item.value);
  }).join(', ');
}

function setFailureSummary(summary) {
  var box = document.getElementById('failure-summary');
  if (!box) return;
  var reasonEl = document.getElementById('failure-reason');
  var reportEl = document.getElementById('failure-report');
  var metricsEl = document.getElementById('failure-metrics');
  if (!summary || !summary.available) {
    box.hidden = true;
    return;
  }
  var reason = summary.reason || summary.message || '未知失败原因';
  var report = summary.report || summary.run_report || '--';
  var metrics = failureMetricsLine(summary) || '--';
  reasonEl.textContent = reason;
  reasonEl.title = reason;
  reportEl.textContent = report;
  reportEl.title = report;
  metricsEl.textContent = metrics;
  metricsEl.title = metrics;
  box.hidden = false;
}

function failureStatusDetail(summary, fallback) {
  if (!summary || !summary.available) return fallback || '[FAIL] 管线出错';
  var stage = summary.stage || summary.phase_label || '管线失败';
  if (summary.check) return stage + ': ' + summary.check;
  if (summary.phase) return stage + ' · ' + summary.phase;
  return stage;
}

function logFailureSummary(summary, returncode) {
  if (!summary || !summary.available) {
    log('[FAIL] 管线出错 (exit=' + returncode + ')', 'err');
    return;
  }
  var key = summary.key || (summary.run_id + '|' + summary.reason + '|' + summary.report);
  if (_lastFailureKey === key) return;
  _lastFailureKey = key;
  var head = '[FAIL] ' + (summary.stage || summary.phase_label || '管线出错');
  if (summary.check) head += ': ' + summary.check;
  log(head, 'err');
  if (summary.reason) log('原因: ' + summary.reason, 'err');
  var metrics = failureMetricsLine(summary);
  if (metrics) log('指标: ' + metrics, 'err');
  if (summary.warnings && summary.warnings.length) {
    var names = summary.warnings.map(function(item) { return item.name; }).filter(Boolean).join(', ');
    if (names) log('警告: ' + names, 'dim');
  }
  if (summary.report) log('QA 报告: ' + summary.report, 'dim');
  if (summary.run_report) log('运行报告: ' + summary.run_report, 'dim');
}

function updateRunStatusFromHealth(d) {
  if (!d) {
    setRunStatus('warn', '待命', 0, '等待选择区域');
    setFailureSummary(null);
    return;
  }
  if (d.running) {
    setRunStatus('warn', '运行中', d.pct || 0, d.step_label || '任务执行中');
    setFailureSummary(null);
  } else if (d.export_running) {
    setRunStatus('warn', '导出中', 0, 'Houdini 正在导出 FBX');
    setFailureSummary(null);
  } else if (d.done) {
    if (d.ok) {
      setRunStatus('ok', '完成', 100, d.step_label || d.name || '任务结束');
      setFailureSummary(null);
    } else {
      setRunStatus('off', '失败', d.pct || 0, failureStatusDetail(d.failure_summary, d.step_label || d.name || '任务失败'));
      setFailureSummary(d.failure_summary);
    }
  } else if (d.failure_summary && d.failure_summary.available) {
    setRunStatus('off', '上次失败', d.pct || 0, failureStatusDetail(d.failure_summary, '上次管线失败'));
    setFailureSummary(d.failure_summary);
  } else {
    setRunStatus('warn', '待命', 0, selection ? '已选择区域，等待执行' : '等待选择区域');
    setFailureSummary(null);
  }
}

function updateHoudiniStatusPanel(available, asset) {
  setStatusRow(
    'houdini-connection-row',
    'houdini-connection-value',
    available ? 'ok' : 'off',
    available ? '在线' : '离线',
    available ? 'Houdini RPYC 已连接' : '需要先打开 Houdini 并启用 RPYC 18811'
  );
  var qaOk = !!(asset && asset.qa_ok);
  var modelReady = !!(asset && asset.model_ready);
  var exportReady = !!(asset && asset.export_ready);
  var message = asset && asset.message ? asset.message : '';
  var assetText = '等待生成';
  var assetState = 'warn';
  if (!available) {
    assetText = '等待 Houdini';
    assetState = 'off';
  } else if (qaOk && modelReady) {
    assetText = 'QA 通过 / 现场可用';
    assetState = 'ok';
  } else if (qaOk && !modelReady) {
    assetText = 'QA 通过 / 现场缺失';
    assetState = 'warn';
  } else if (message.indexOf('run mismatch') >= 0) {
    assetText = 'QA 记录不匹配';
    assetState = 'warn';
  } else if (message.indexOf('area mismatch') >= 0) {
    assetText = '区域不匹配';
    assetState = 'warn';
  } else if (asset && asset.status === 'completed') {
    assetText = 'QA 已完成 / 待确认';
    assetState = 'warn';
  } else if (asset && asset.status) {
    assetText = 'QA ' + asset.status;
    assetState = 'warn';
  }
  setStatusRow(
    'houdini-asset-row',
    'houdini-asset-value',
    assetState,
    assetText,
    message || 'Houdini 生成完成并通过 QA 后，模型资产会进入可导出状态'
  );
  setStatusRow(
    'houdini-export-row',
    'houdini-export-value',
    exportReady ? 'ok' : 'warn',
    exportReady ? '可导出' : '等待资产',
    exportReady ? '当前 Houdini 模型可导出 FBX' : '需要 Houdini 在线、Model QA 通过，并且 OUT_city 现场几何可用'
  );
}

function updateSelectionButtons(running) {
  var disabled = !selection || !!running;
  document.getElementById('run-btn').disabled = disabled;
  document.getElementById('download-btn').disabled = disabled;
}

function renderDataSources(payload) {
  var status = document.getElementById('source-status');
  var list = document.getElementById('source-list');
  if (!status || !list) return;
  status.textContent = '选取区域预先下载地图数据加快Houdini自动管线构建速度';
  if (!payload || !payload.available) {
    return;
  }
  list.innerHTML = '';
  (payload.items || []).forEach(function(item) {
    var card = document.createElement('div');
    card.className = 'source-card';

    var head = document.createElement('div');
    head.className = 'source-head';
    var title = document.createElement('span');
    title.className = 'source-title';
    title.textContent = item.title || item.key || '数据';
    var file = item.file || {};
    head.appendChild(title);

    var provider = document.createElement('div');
    provider.className = 'source-provider';
    provider.textContent = '数据源：' + (item.provider || '--');

    var detail = document.createElement('div');
    detail.className = 'source-detail';
    detail.textContent = '策略：' + (item.strategy_label || item.strategy || item.method || '--');
    detail.title = item.current || item.strategy || '';

    var fileLine = document.createElement('div');
    fileLine.className = 'source-file';
    fileLine.textContent = (file.exists ? '[OK] ' : '[缺失] ') + (file.path || '--') +
      (file.size_label ? ' · ' + file.size_label : '');
    fileLine.title = file.abs_path || file.path || '';

    card.appendChild(head);
    card.appendChild(provider);
    card.appendChild(detail);
    card.appendChild(fileLine);
    list.appendChild(card);
  });
}

function refreshDataSources() {
  fetch('/data-sources')
  .then(function(r) { return r.json(); })
  .then(renderDataSources)
  .catch(function(e) {
    renderDataSources({ available: false, message: '数据源读取失败: ' + e });
  });
}

function refreshServiceState() {
  fetch('/health')
  .then(function(r) { return r.json(); })
  .then(function(d) {
    setHoudiniBadge(!!d.houdini_available, d.houdini_asset);
    updateSoftwarePath(d.software_paths);
    updateExportButton(!!d.export_available, !!d.running);
    updateSelectionButtons(!!d.running);
    updateRunStatusFromHealth(d);
    refreshDataSources();
  })
  .catch(function() {
    setHoudiniBadge(false, null);
    setRunStatus('off', '离线', 0, '状态服务不可用');
  });
}

function probeHoudini() {
  openOrProbeHoudini();
}

function touchPageSession() {
  if (!shutdownWithPage) return;
  fetch('/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
    keepalive: true
  }).catch(function() {});
}

function notifyPageClosed() {
  if (!shutdownWithPage) return;
  if (pageSessionTimer) clearInterval(pageSessionTimer);
  var payload = new Blob(['{}'], { type: 'application/json' });
  if (navigator.sendBeacon) {
    navigator.sendBeacon('/session/closed', payload);
  } else {
    fetch('/session/closed', { method: 'POST', body: '{}', keepalive: true }).catch(function() {});
  }
}

function startPageSession() {
  if (!shutdownWithPage) return;
  touchPageSession();
  pageSessionTimer = setInterval(touchPageSession, 2000);
  window.addEventListener('pagehide', notifyPageClosed);
}

function tileStyle(tile) {
  var isSelected = !!selectedTileIds[tile.tile_id];
  var isCached = !!tile.cached;
  var selectedColor = '#35d4c4';
  var cachedColor = '#eef7f4';
  var gridLineColor = '#000000';
  return {
    color: gridLineColor,
    weight: isSelected ? 2 : 1,
    opacity: 1.0,
    fillColor: isCached ? cachedColor : selectedColor,
    fillOpacity: isSelected ? (isCached ? 0.28 : 0.2) : (isCached ? 0.22 : 0),
    dashArray: null
  };
}

function tileLatLngBounds(tile) {
  var b = tileDisplayBbox(tile);
  return [[b[1], b[0]], [b[3], b[2]]];
}

function tileDisplayBbox(tile) {
  return tile.display_bbox || tile.bbox;
}

function sortedUniqueNumbers(values) {
  var seen = {};
  values.forEach(function(value) {
    var number = Number(value);
    if (Number.isFinite(number)) seen[String(number)] = number;
  });
  return Object.keys(seen).map(function(key) { return seen[key]; }).sort(function(a, b) { return a - b; });
}

function assignDisplayGridBounds(tiles) {
  if (!tiles || !tiles.length) return;
  var eastings = sortedUniqueNumbers(tiles.map(function(tile) { return tile.easting; }));
  var northings = sortedUniqueNumbers(tiles.map(function(tile) { return tile.northing; }));
  if (!eastings.length || !northings.length) return;

  var colIndex = {};
  var rowIndex = {};
  eastings.forEach(function(value, index) { colIndex[String(value)] = index; });
  northings.forEach(function(value, index) { rowIndex[String(value)] = index; });

  var west = Math.min.apply(null, tiles.map(function(tile) { return tile.bbox[0]; }));
  var south = Math.min.apply(null, tiles.map(function(tile) { return tile.bbox[1]; }));
  var east = Math.max.apply(null, tiles.map(function(tile) { return tile.bbox[2]; }));
  var north = Math.max.apply(null, tiles.map(function(tile) { return tile.bbox[3]; }));
  var lonStep = (east - west) / eastings.length;
  var latStep = (north - south) / northings.length;
  if (!Number.isFinite(lonStep) || !Number.isFinite(latStep) || lonStep <= 0 || latStep <= 0) {
    tiles.forEach(function(tile) { tile.display_bbox = tile.bbox; });
    return;
  }

  tiles.forEach(function(tile) {
    var col = colIndex[String(Number(tile.easting))];
    var row = rowIndex[String(Number(tile.northing))];
    if (col === undefined || row === undefined) {
      tile.display_bbox = tile.bbox;
      return;
    }
    tile.display_bbox = [
      west + col * lonStep,
      south + row * latStep,
      west + (col + 1) * lonStep,
      south + (row + 1) * latStep
    ];
  });
}

function kmSize(tile) {
  return (tile.size_m / 1000).toFixed(0) + 'km x ' + (tile.size_m / 1000).toFixed(0) + 'km';
}

function selectionId(sel) {
  var hemi = sel.northern ? 'n' : 's';
  return 'z' + sel.zone + hemi + '_e' + sel.easting + '_n' + sel.northing +
    '_w' + sel.width_m + '_h' + sel.height_m + '_s' + sel.size_m;
}

function setText(id, value) {
  var el = document.getElementById(id);
  if (el) el.textContent = value;
}

function formatKm(meters) {
  return (meters / 1000).toFixed(0) + ' km';
}

function selectionTileIds(sel) {
  return sel && sel.tiles ? sel.tiles.map(function(tile) { return tile.tile_id; }) : [];
}

function selectionPayloadFromSelection(sel) {
  if (!sel) return null;
  return {
    selection_id: sel.selection_id,
    tile_ids: selectionTileIds(sel),
    bbox: sel.bbox,
    saved_at: Date.now()
  };
}

function persistSelection() {
  var payload = selectionPayloadFromSelection(selection);
  if (!payload || !payload.tile_ids.length) return;
  try {
    if (window.sessionStorage) {
      window.sessionStorage.setItem(selectionStorageKey, JSON.stringify(payload));
    }
  } catch (e) {}
  fetch('/selection', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tile_ids: payload.tile_ids }),
    keepalive: true
  }).catch(function() {});
}

function clearPersistedSelection() {
  pendingRestoreTileIds = null;
  pendingRestoreLogged = false;
  if (!window.sessionStorage) return;
  try {
    window.sessionStorage.removeItem(selectionStorageKey);
  } catch (e) {}
  fetch('/selection/clear', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
    keepalive: true
  }).catch(function() {});
}

function loadPersistedSelection() {
  if (!window.sessionStorage) return null;
  try {
    var raw = window.sessionStorage.getItem(selectionStorageKey);
    if (!raw) return null;
    var payload = JSON.parse(raw);
    if (!payload || !payload.tile_ids || !payload.tile_ids.length) return null;
    return payload;
  } catch (e) {
    return null;
  }
}

function restoreRememberedSelection() {
  var localPayload = loadPersistedSelection();
  if (restoreSelectionFromPayload(localPayload)) return;
  fetch('/selection')
  .then(function(r) { return r.json(); })
  .then(function(payload) {
    if (payload && payload.available) restoreSelectionFromPayload(payload);
  })
  .catch(function() {});
}

function restoreSelectionFromPayload(payload) {
  if (!payload || !payload.tile_ids || !payload.tile_ids.length) return false;
  if (payload.bbox && payload.bbox.length === 4) {
    map.fitBounds([[payload.bbox[1], payload.bbox[0]], [payload.bbox[3], payload.bbox[2]]], {
      padding: [60, 60],
      maxZoom: 16
    });
  }
  pendingRestoreTileIds = payload.tile_ids.slice();
  pendingRestoreLogged = false;
  if (lastGridData && lastGridData.tiles && lastGridData.tiles.length) {
    restorePendingSelection();
    return true;
  }
  scheduleGridLoad();
  return true;
}

function restorePendingSelection() {
  if (!pendingRestoreTileIds || !pendingRestoreTileIds.length || !lastGridData || !lastGridData.tiles) {
    return false;
  }
  var wanted = {};
  pendingRestoreTileIds.forEach(function(id) { wanted[id] = true; });
  var tiles = lastGridData.tiles.filter(function(tile) { return !!wanted[tile.tile_id]; });
  if (tiles.length !== pendingRestoreTileIds.length) {
    return false;
  }
  var previous = pendingRestoreTileIds;
  pendingRestoreTileIds = null;
  setSelection(tiles, { silent: true });
  if (!pendingRestoreLogged) {
    log('已恢复上次框选: ' + selection.selection_id + '  ' + previous.length + ' 格', 'ok');
    pendingRestoreLogged = true;
  }
  return true;
}

function updateTileDisplay() {
  var el = document.getElementById('tile-display');
  if (!selection) {
    if (el) el.textContent = '尚未框选网格';
    setText('area-id-chip', '未选择区域');
    updateSelectionButtons(false);
    updateMapToolButtons();
    return;
  }
  var b = selection.bbox;
  var total = selection.tiles.length;
  var cached = selection.tiles.filter(function(tile) { return tile.cached; }).length;
  var cacheText = cached === total ? '全部已有本地缓存' : ('已缓存 ' + cached + '/' + total + '，其余运行时下载');
  var bboxText = 'W ' + b[0].toFixed(6) + ' / S ' + b[1].toFixed(6) +
    ' / E ' + b[2].toFixed(6) + ' / N ' + b[3].toFixed(6);
  if (el) {
    el.textContent =
      selection.selection_id + '\n' +
      selection.cols + ' x ' + selection.rows + ' 格 · ' +
      formatKm(selection.width_m) + ' x ' + formatKm(selection.height_m) + ' · ' + cacheText + '\n' +
      bboxText;
  }
  setText('area-id-chip', selection.selection_id);
  updateSelectionButtons(false);
  updateMapToolButtons();
}

function syncDrawnSelectionLayer() {
  if (!drawnItems || !selection || !selection.bbox) return;
  drawnItems.clearLayers();
  var b = selection.bbox;
  L.rectangle([[b[1], b[0]], [b[3], b[2]]], {
    opacity: 0,
    fillOpacity: 0
  }).addTo(drawnItems);
}

function refreshTileStyles() {
  gridLayer.eachLayer(function(layer) {
    if (layer.vcTile) layer.setStyle(tileStyle(layer.vcTile));
  });
}

function bboxIntersects(bounds, bbox) {
  return !(bbox[2] < bounds.getWest() || bbox[0] > bounds.getEast() ||
           bbox[3] < bounds.getSouth() || bbox[1] > bounds.getNorth());
}

function setSelection(seedTiles, options) {
  options = options || {};
  if (!seedTiles || !seedTiles.length) {
    log('没有框到网格，请放大后重试。', 'err');
    return;
  }
  var zone = seedTiles[0].zone;
  var northern = seedTiles[0].northern;
  var size = seedTiles[0].size_m;
  var eastings = seedTiles.map(function(tile) { return tile.easting; });
  var northings = seedTiles.map(function(tile) { return tile.northing; });
  var minE = Math.min.apply(null, eastings);
  var maxE = Math.max.apply(null, eastings);
  var minN = Math.min.apply(null, northings);
  var maxN = Math.max.apply(null, northings);
  var rectTiles = (lastGridData.tiles || []).filter(function(tile) {
    return tile.zone === zone && tile.northern === northern && tile.size_m === size &&
      tile.easting >= minE && tile.easting <= maxE &&
      tile.northing >= minN && tile.northing <= maxN;
  });
  var cols = Math.round((maxE - minE) / size) + 1;
  var rows = Math.round((maxN - minN) / size) + 1;
  var expected = cols * rows;
  if (rectTiles.length !== expected) {
    clearSelection();
    log('[错误] 框选结果跨出了当前已加载网格，请稍微缩小框选或放大地图。', 'err');
    return;
  }
  if (expected > maxSelectionTiles) {
    clearSelection();
    log('[错误] 本次框选 ' + expected + ' 格，超过上限 ' + maxSelectionTiles + ' 格。', 'err');
    return;
  }
  rectTiles.sort(function(a, b) {
    if (a.northing !== b.northing) return a.northing - b.northing;
    return a.easting - b.easting;
  });
  var bbox = [
    Math.min.apply(null, rectTiles.map(function(tile) { return tile.bbox[0]; })),
    Math.min.apply(null, rectTiles.map(function(tile) { return tile.bbox[1]; })),
    Math.max.apply(null, rectTiles.map(function(tile) { return tile.bbox[2]; })),
    Math.max.apply(null, rectTiles.map(function(tile) { return tile.bbox[3]; }))
  ];
  selection = {
    zone: zone,
    northern: northern,
    easting: minE,
    northing: minN,
    cols: cols,
    rows: rows,
    size_m: size,
    width_m: cols * size,
    height_m: rows * size,
    bbox: bbox,
    tiles: rectTiles
  };
  selection.selection_id = selectionId(selection);
  selectedTileIds = {};
  rectTiles.forEach(function(tile) { selectedTileIds[tile.tile_id] = true; });
  updateTileDisplay();
  syncDrawnSelectionLayer();
  refreshTileStyles();
  persistSelection();
  setRunStatus('warn', '待命', 0, '已选择区域，等待执行');
  var cached = rectTiles.filter(function(tile) { return tile.cached; }).length;
  if (!options.silent) {
    log('已框选: ' + selection.selection_id + '  ' + rectTiles.length + ' 格，已缓存 ' + cached + '/' + rectTiles.length, 'ok');
  }
}

function selectTilesByBounds(bounds) {
  if (!lastGridData || !lastGridData.tiles || !lastGridData.tiles.length) {
    log('网格尚未加载完成，请稍等。', 'err');
    return;
  }
  var hits = lastGridData.tiles.filter(function(tile) {
    return bboxIntersects(bounds, tileDisplayBbox(tile));
  });
  setSelection(hits);
}

function selectTileByLatLng(latlng) {
  if (!lastGridData || !lastGridData.tiles || !lastGridData.tiles.length) {
    log('网格尚未加载完成，请稍等。', 'err');
    return;
  }
  var hit = null;
  for (var i = 0; i < lastGridData.tiles.length; i += 1) {
    var tile = lastGridData.tiles[i];
    var b = tileDisplayBbox(tile);
    if (latlng.lng >= b[0] && latlng.lng <= b[2] && latlng.lat >= b[1] && latlng.lat <= b[3]) {
      hit = tile;
      break;
    }
  }
  if (!hit) {
    log('未点中当前视口网格，请放大或等待网格加载。', 'err');
    return;
  }
  setSelection([hit]);
}

function clearSelection() {
  selection = null;
  selectedTileIds = {};
  drawnItems.clearLayers();
  clearPersistedSelection();
  updateTileDisplay();
  refreshTileStyles();
  setRunStatus('warn', '待命', 0, '等待选择区域');
}

function renderGrid(data) {
  gridLayer.clearLayers();
  if (!data) return;
  lastGridData = data;
  if (data.truncated) {
    return;
  }
  assignDisplayGridBounds(data.tiles);
  data.tiles.forEach(function(tile) {
    var options = tileStyle(tile);
    options.interactive = false;
    options.renderer = gridRenderer;
    var poly = L.rectangle(tileLatLngBounds(tile), options);
    poly.vcTile = tile;
    poly.addTo(gridLayer);
  });
  restorePendingSelection();
  refreshTileStyles();
}

function loadGrid() {
  map.invalidateSize();
  var size = map.getSize();
  if (!size || size.x <= 0 || size.y <= 0) {
    scheduleGridLoad();
    return;
  }
  var b = map.getBounds();
  if (!(b.getWest() < b.getEast() && b.getSouth() < b.getNorth())) {
    scheduleGridLoad();
    return;
  }
  var req = ++gridRequestId;
  var url = '/tiles?west=' + encodeURIComponent(b.getWest()) +
    '&south=' + encodeURIComponent(b.getSouth()) +
    '&east=' + encodeURIComponent(b.getEast()) +
    '&north=' + encodeURIComponent(b.getNorth());
  fetch(url)
  .then(function(r) { return r.json(); })
  .then(function(data) {
    if (req !== gridRequestId) return;
    renderGrid(data);
  })
  .catch(function(e) {
    log('[错误] 网格加载失败: ' + e, 'err');
  });
}

function scheduleGridLoad() {
  clearTimeout(gridTimer);
  gridTimer = setTimeout(loadGrid, 40);
}

map.on('moveend zoomend', scheduleGridLoad);
window.addEventListener('resize', function() {
  map.invalidateSize();
  scheduleGridLoad();
});
restoreRememberedSelection();
scheduleGridLoad();

function categorizeLine(line) {
  var l = line.toLowerCase();
  
  // Model QA check
  if (l.indexOf('[modelqa]') >= 0 || l.indexOf('model qa') >= 0 || l.indexOf('report: reports/') >= 0 || l.indexOf('checks={') >= 0) {
    return 'qa';
  }
  // Model QA specific indicator lines
  if (l.indexOf('[ok]') >= 0 && (
      l.indexOf('required_nodes') >= 0 || 
      l.indexOf('terrain_density') >= 0 || 
      l.indexOf('building_color') >= 0 || 
      l.indexOf('footprint_bevel') >= 0 || 
      l.indexOf('building_normals') >= 0 || 
      l.indexOf('foundation_tags') >= 0 || 
      l.indexOf('foundation_normals') >= 0 || 
      l.indexOf('foundation_alignment') >= 0 || 
      l.indexOf('building_terrain_fit') >= 0 || 
      l.indexOf('road_terrain_fit') >= 0
  )) {
    return 'qa';
  }
  if (l.indexOf('[warn] road_faces') >= 0 || l.indexOf('[warn] road_clipped_faces') >= 0) {
    return 'qa';
  }
  
  // Houdini Cooking & SOP pipeline
  if (l.indexOf('[houdini') >= 0 || 
      l.indexOf('cooking:') >= 0 || 
      l.indexOf('osm_import') >= 0 || 
      l.indexOf('dem_terrain') >= 0 || 
      l.indexOf('dem_subdivide') >= 0 ||
      l.indexOf('bld_footprint_bevel') >= 0 || 
      l.indexOf('extract_buildings') >= 0 || 
      l.indexOf('snap_bld_to_terrain') >= 0 || 
      l.indexOf('extrude_buildings') >= 0 || 
      l.indexOf('post_normals') >= 0 || 
      l.indexOf('road_strips') >= 0 || 
      l.indexOf('bld_clipped') >= 0 || 
      l.indexOf('road_clipped') >= 0 || 
      l.indexOf('bld_foundation') >= 0 || 
      l.indexOf('bld_with_foundation') >= 0 || 
      l.indexOf('road_extrude') >= 0 || 
      l.indexOf('viewport') >= 0 || 
      l.indexOf('save hip') >= 0) {
    return 'houdini';
  }
  
  // Refinement / Offline Cleaning
  if (l.indexOf('[数据精炼]') >= 0 || 
      l.indexOf('[dtm]') >= 0 || 
      l.indexOf('[tile cache]') >= 0 || 
      l.indexOf('download') >= 0 || 
      l.indexOf('[probe]') >= 0 || 
      l.indexOf('earth engine') >= 0 || 
      l.indexOf('fabdem') >= 0 || 
      l.indexOf('geotiff') >= 0 || 
      l.indexOf('csv') >= 0 || 
      l.indexOf('osm') >= 0) {
    return 'clean';
  }
  
  return null;
}

function writeToPanel(panelId, msg, cls) {
  var el = document.getElementById('log-panel-' + panelId);
  if (!el) return;
  
  if (el.textContent.indexOf('等待') === 0) {
    el.textContent = '';
  }
  
  var line = document.createElement('span');
  if (cls) line.className = cls;
  line.textContent = msg + '\n';
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

function log(msg, cls) {
  writeToPanel('all', msg, cls);
  
  var category = categorizeLine(msg);
  if (category) {
    writeToPanel(category, msg, cls);
  }
}

function switchTab(panelId) {
  var btns = document.querySelectorAll('.tab-btn');
  btns.forEach(function(btn) {
    btn.classList.remove('active');
  });
  
  var activeBtn = document.querySelector('button[onclick="switchTab(\'' + panelId + '\')"]');
  if (activeBtn) {
    activeBtn.classList.add('active');
  }
  
  var panels = document.querySelectorAll('.log-panel');
  panels.forEach(function(p) {
    if (p.id === 'log-panel-' + panelId) {
      p.style.display = 'block';
      p.scrollTop = p.scrollHeight;
    } else {
      p.style.display = 'none';
    }
  });
}

var _pollTimer = null;
var _lastLogLen = 0;
var _lastExportLogLen = 0;
var _lastFailureKey = '';
var _houdiniOpenPollTimer = null;

function pollHoudiniAfterOpen(remaining) {
  clearTimeout(_houdiniOpenPollTimer);
  refreshServiceState();
  if (remaining <= 0) return;
  _houdiniOpenPollTimer = setTimeout(function() {
    pollHoudiniAfterOpen(remaining - 1);
  }, 2000);
}

function pollStatus() {
  fetch('/status')
  .then(r => r.json())
  .then(d => {
    var pct = d.pct || 0;
    document.getElementById('progress-bar').style.width = pct + '%';
    document.getElementById('progress-text').textContent = pct + '%';
    document.getElementById('step-label').textContent = d.step_label || '运行中...';
    updateRunStatusFromHealth(d);
    updateSoftwarePath(d.software_paths);

    if (d.log_lines && d.log_lines.length > _lastLogLen) {
      var newLines = d.log_lines.slice(_lastLogLen);
      for (var i = 0; i < newLines.length; i++) {
        var line = newLines[i];
        var cls = 'dim';
        if (line.indexOf('[OK]') >= 0) cls = 'ok';
        else if (line.indexOf('[ERR]') >= 0 || line.indexOf('[FAIL]') >= 0) cls = 'err';
        else if (line.match(/^\[\d+\/\d+\]/)) cls = 'step';
        log(line, cls);
      }
      _lastLogLen = d.log_lines.length;
    }

    if (d.export_log_lines && d.export_log_lines.length > _lastExportLogLen) {
      var exportLines = d.export_log_lines.slice(_lastExportLogLen);
      for (var j = 0; j < exportLines.length; j++) {
        var exLine = exportLines[j];
        var exCls = 'dim';
        if (exLine.indexOf('[OK]') >= 0 || exLine.indexOf(' OK:') >= 0) exCls = 'ok';
        else if (exLine.indexOf('[ERR]') >= 0 || exLine.indexOf('[FAIL]') >= 0 || exLine.indexOf('[WARN]') >= 0) exCls = 'err';
        log(exLine, exCls);
      }
      _lastExportLogLen = d.export_log_lines.length;
    }
    updateExportButton(!!d.export_available, !!d.export_running || !!d.running);
    setHoudiniBadge(!!d.houdini_available, d.houdini_asset);
    updateSelectionButtons(!!d.running);

    if (d.export_done && !d.export_running) {
      clearInterval(_pollTimer);
      _pollTimer = null;
      refreshServiceState();
      return;
    }

    if (d.done && !d.export_running) {
      clearInterval(_pollTimer);
      _pollTimer = null;
      document.getElementById('progress-bar').style.width = '100%';
      document.getElementById('progress-text').textContent = '100%';
      if (d.ok) {
        document.getElementById('progress-bar').style.background = 'var(--accent)';
        var doneLabel = d.operation === 'download' ? '[OK] 数据下载完成' : '[OK] 生成完成';
        var doneLog = d.operation === 'download' ? '[OK] 数据下载完成！区域: ' : '[OK] 生成完成！区域: ';
        document.getElementById('step-label').textContent = doneLabel;
        setRunStatus('ok', '完成', 100, doneLabel);
        log(doneLog + d.name, 'ok');
        if (d.run_id) log('run_id: ' + d.run_id, 'dim');
        if (d.auto_shutdown_on_success) {
          log('3 秒后自动关闭页面，5 秒后停止本地服务...', 'dim');
          setTimeout(function() {
            window.open('', '_self');
            window.close();
            document.body.innerHTML = '<div style="font-family:Noto Sans SC,Microsoft YaHei,PingFang SC,Segoe UI,Arial,sans-serif;background:var(--base);color:var(--accent);height:100vh;display:flex;align-items:center;justify-content:center;flex-direction:column;"><h2>[OK] VirtualCity 生成完成</h2><p>本地服务已自动停止，可以关闭此页面。</p></div>';
          }, 3000);
        } else {
          log('状态服务保持运行，可继续查看 /status 或继续选择网格测试。', 'dim');
          updateSelectionButtons(false);
          scheduleGridLoad();
          refreshServiceState();
        }
      } else {
        document.getElementById('progress-bar').style.background = 'var(--accent)';
        var failDetail = failureStatusDetail(d.failure_summary, '[FAIL] 管线出错');
        document.getElementById('step-label').textContent = failDetail;
        setRunStatus('off', '失败', d.pct || 0, failDetail);
        setFailureSummary(d.failure_summary);
        logFailureSummary(d.failure_summary, d.returncode);
        updateSelectionButtons(false);
        refreshServiceState();
      }
    }
  })
  .catch(function() { /* server may be restarting */ });
}

function submitSelectedArea(endpoint, actionLabel) {
  if (!selection) return;
  var name = selection.selection_id;
  var b = selection.bbox;
  updateSelectionButtons(true);
  document.getElementById('log-panel-all').innerHTML = '';
  document.getElementById('log-panel-clean').innerHTML = '等待数据下载或精炼...';
  document.getElementById('log-panel-houdini').innerHTML = '等待 Houdini RPYC 执行...';
  document.getElementById('log-panel-qa').innerHTML = '等待 Model QA 诊断报告...';
  _lastLogLen = 0;
  _lastExportLogLen = 0;
  _lastFailureKey = '';
  setFailureSummary(null);
  document.getElementById('progress-container').style.display = 'block';
  document.getElementById('progress-bar').style.width = '0%';
  document.getElementById('progress-bar').style.background = 'var(--accent)';
  document.getElementById('progress-text').textContent = '0%';
  document.getElementById('step-label').textContent = '准备中...';
  setRunStatus('warn', '启动中', 0, actionLabel + ': ' + name);
  log('[' + new Date().toLocaleTimeString() + '] ' + actionLabel + ': ' + name, 'ok');
  log('bbox = [' + b[0]+', '+b[1]+', '+b[2]+', '+b[3]+']', 'dim');
  updateExportButton(false, true);

  fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      tile_ids: selection.tiles.map(function(tile) { return tile.tile_id; })
    })
  })
  .then(r => r.json())
  .then(d => {
    if (d.ok) {
      log(d.message || '任务已启动...', 'dim');
      _pollTimer = setInterval(pollStatus, 1000);
    } else {
      log('[错误] ' + d.message, 'err');
      updateSelectionButtons(false);
      refreshServiceState();
    }
  })
  .catch(e => {
    log('[网络错误] ' + e, 'err');
    updateSelectionButtons(false);
    refreshServiceState();
  });
}

function runPipeline() {
  submitSelectedArea('/run', '提交 Houdini 生成');
}

function downloadData() {
  submitSelectedArea('/download-data', '提交数据下载');
}

function ensurePolling() {
  if (!_pollTimer) _pollTimer = setInterval(pollStatus, 1000);
}

function exportFbx() {
  document.getElementById('export-btn').disabled = true;
  _lastExportLogLen = 0;
  setRunStatus('warn', '导出中', 0, 'Houdini 正在导出 FBX');
  log('[' + new Date().toLocaleTimeString() + '] 开始导出 FBX（不触发 UE5 导入）...', 'ok');
  fetch('/export', { method: 'POST' })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.ok) {
      ensurePolling();
    } else {
      log('[错误] ' + d.message, 'err');
      refreshServiceState();
    }
  })
  .catch(function(e) {
    log('[网络错误] ' + e, 'err');
    refreshServiceState();
  });
}

refreshServiceState();
refreshDataSources();
startPageSession();
