// Map selection, grid loading, and location search controls.

// Domain: map-selection
// Owns: Grid loading, fixed-tile selection, persisted selection restore, basemap menu, and location search.
// AI handoff: For map selection or tile restore issues, start with setSelection, loadGrid, and restoreRememberedSelection.
function setDrawData(fc) {
  var src = map.getSource('draw');
  if (src) src.setData(fc || emptyFeatureCollection());
}

function buildGridFeatureCollection() {
  var tiles = (lastGridData && lastGridData.tiles) ? lastGridData.tiles : [];
  return {
    type: 'FeatureCollection',
    features: tiles.map(function(tile) {
      var b = tileDisplayBbox(tile);
      return {
        type: 'Feature',
        properties: {
          tile_id: tile.tile_id,
          selected: !!selectedTileIds[tile.tile_id],
          cached: !!tile.cached
        },
        geometry: {
          type: 'Polygon',
          coordinates: [[[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]], [b[0], b[1]]]]
        }
      };
    })
  };
}

function setGridData() {
  var src = map.getSource('grid');
  if (src) src.setData(buildGridFeatureCollection());
}

function rectFeatureCollection(a, b) {
  var w = Math.min(a.lng, b.lng), e = Math.max(a.lng, b.lng);
  var s = Math.min(a.lat, b.lat), n = Math.max(a.lat, b.lat);
  return {
    type: 'FeatureCollection',
    features: [{
      type: 'Feature',
      properties: {},
      geometry: { type: 'LineString', coordinates: [[w, s], [e, s], [e, n], [w, n], [w, s]] }
    }]
  };
}

function makeBounds(a, b) {
  var w = Math.min(a.lng, b.lng), e = Math.max(a.lng, b.lng);
  var s = Math.min(a.lat, b.lat), n = Math.max(a.lat, b.lat);
  return {
    getWest: function() { return w; },
    getEast: function() { return e; },
    getSouth: function() { return s; },
    getNorth: function() { return n; }
  };
}

function armRectangleTool() {
  rectToolArmed = true;
  rectDragging = false;
  rectStart = null;
  if (map.dragPan) map.dragPan.disable();
  map.getCanvas().style.cursor = 'crosshair';
}

function disarmRectangleTool() {
  rectToolArmed = false;
  rectDragging = false;
  rectStart = null;
  if (map.dragPan) map.dragPan.enable();
  map.getCanvas().style.cursor = '';
  setDrawData(emptyFeatureCollection());
  updateMapToolButtons();
}

function bindRectangleDrag() {
  map.on('mousedown', function(e) {
    if (!rectToolArmed) return;
    rectDragging = true;
    rectStart = e.lngLat;
    setDrawData(rectFeatureCollection(rectStart, e.lngLat));
  });
  map.on('mousemove', function(e) {
    if (!rectDragging || !rectStart) return;
    setDrawData(rectFeatureCollection(rectStart, e.lngLat));
  });
  map.on('mouseup', function(e) {
    if (!rectDragging || !rectStart) return;
    var start = rectStart;
    var end = e.lngLat;
    rectDragging = false;
    rectStart = null;
    disarmRectangleTool();
    if (start.lng === end.lng && start.lat === end.lat) return;
    selectTilesByBounds(makeBounds(start, end));
  });
}

function rectangleToolActive() {
  return rectToolArmed;
}

function updateMapToolButtons() {
  if (selectionToolButtons.grid) {
    selectionToolButtons.grid.classList.toggle('active', gridVisible);
    selectionToolButtons.grid.setAttribute('aria-pressed', gridVisible ? 'true' : 'false');
  }
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

function setGridVisible(visible) {
  gridVisible = !!visible;
  var value = gridVisible ? 'visible' : 'none';
  ['grid-fill', 'grid-line'].forEach(function(layerId) {
    if (map.getLayer(layerId)) map.setLayoutProperty(layerId, 'visibility', value);
  });
  var toolbar = document.getElementById('selection-tools');
  if (toolbar) toolbar.classList.toggle('drawer-open', gridVisible);
  var drawer = toolbar && toolbar.querySelector('.map-tool-drawer');
  if (drawer) drawer.setAttribute('aria-hidden', gridVisible ? 'false' : 'true');
  updateMapToolButtons();
}

function toggleGridVisible() {
  setGridVisible(!gridVisible);
}

function setPointSelectActive(active) {
  pointSelectActive = !!active;
  if (pointSelectActive && rectangleToolActive()) disarmRectangleTool();
  var container = map.getContainer();
  if (pointSelectActive) {
    container.classList.add('point-select-active');
  } else {
    container.classList.remove('point-select-active');
  }
  updateMapToolButtons();
}

function activateRectangleTool() {
  setPointSelectActive(false);
  if (!rectangleToolActive()) armRectangleTool();
  updateMapToolButtons();
}

function clearSelectionFromMapTool() {
  setPointSelectActive(false);
  if (rectangleToolActive()) disarmRectangleTool();
  clearSelection();
}

function bindSelectionTools() {
  selectionToolButtons = {
    grid: document.querySelector('.map-tool-grid'),
    rectangle: document.querySelector('.map-tool-rectangle'),
    point: document.querySelector('.map-tool-point'),
    clear: document.querySelector('.map-tool-clear')
  };
  if (selectionToolButtons.grid) {
    selectionToolButtons.grid.addEventListener('click', toggleGridVisible);
  }
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
  buildBasemapMenu();
  updateMapToolButtons();
  updateBasemapMenu();
}

function buildBasemapMenu() {
  var toggle = document.getElementById('basemap-toggle');
  if (!toggle) return;
  toggle.addEventListener('click', function(e) {
    e.stopPropagation();
    toggleBasemapStyle();
  });
}

function toggleBasemapStyle() {
  var next = getNextBasemapStyle(currentBasemap);
  setBasemapStyle(next.id);
}

function shortSearchTitle(item) {
  var name = item.name || item.display_name || '';
  if (name) return name;
  var display = item.display_name || '';
  return display.split(',').slice(0, 2).join(', ') || '未知地点';
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
      map.fitBounds([[west, south], [east, north]], { padding: 40, maxZoom: 15 });
    } else {
      map.jumpTo({ center: [lon, lat], zoom: 13 });
    }
  } else {
    map.jumpTo({ center: [lon, lat], zoom: 13 });
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
  setDrawData(emptyFeatureCollection());
}

function refreshTileStyles() {
  setGridData();
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
  setDrawData(emptyFeatureCollection());
  clearPersistedSelection();
  updateTileDisplay();
  refreshTileStyles();
  setRunStatus('warn', '待命', 0, '等待选择区域');
}

function renderGrid(data) {
  if (!data) {
    lastGridData = null;
    setGridData();
    return;
  }
  lastGridData = data;
  if (data.truncated) {
    setGridData();
    return;
  }
  assignDisplayGridBounds(data.tiles);
  setGridData();
  restorePendingSelection();
}

function loadGrid() {
  if (!mapReady) {
    scheduleGridLoad();
    return;
  }
  var canvas = map.getCanvas();
  if (!canvas || canvas.width <= 0 || canvas.height <= 0) {
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
  if (activeWorkspaceId !== 'houdini') return;
  clearTimeout(gridTimer);
  gridTimer = setTimeout(loadGrid, 40);
}
