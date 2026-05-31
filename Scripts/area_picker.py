"""
VirtualCity — 交互式区域选择器
================================
运行后自动打开浏览器，在地图上框选固定 1km UTM 网格块，点击"开始生成"即可触发完整管线。
不需要截图、不需要复制 URL、不需要手动估算坐标；下游仍使用 bbox 入口。

用法:
    uv run python Scripts/area_picker.py

浏览器打开后:
    1. 放大到目标区域
    2. 点击左侧矩形工具，拖拽覆盖 1 个或多个 1km x 1km 网格
    3. 点击"开始生成"
    4. 在网页或终端窗口查看管线进度
"""

import sys, json, subprocess, threading, webbrowser, time, os, re, urllib.error, urllib.request, urllib.parse
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

import vc_grid

APP_VERSION = "2026-06-01-grid-box-select-v2"
STARTED_AT = time.strftime("%Y-%m-%d %H:%M:%S")
AUTO_SHUTDOWN_ON_SUCCESS = os.environ.get("VC_AREA_PICKER_AUTO_SHUTDOWN") == "1"
NO_BROWSER = os.environ.get("VC_AREA_PICKER_NO_BROWSER") == "1"

# Global pipeline state
_state = {'running': False, 'done': False, 'ok': False, 'returncode': None, 'name': '', 'start': 0.0,
          'run_id': '',
          'houdini_done': False, 'houdini_status': '', 'houdini_message': '',
          'step': 0, 'total_steps': 6, 'step_label': '', 'log_lines': [], 'pct': 0}
_state_lock = threading.Lock()
_server_ref = [None]  # mutable ref so _run thread can call shutdown()
_MAX_LOG_LINES = 80


def _safe_print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(str(msg).encode('ascii', errors='backslashreplace').decode('ascii'))

SCRIPTS = Path(__file__).resolve().parent
ROOT    = SCRIPTS.parent
PORT    = 8765

_STEP_RE = re.compile(r'^\[(\d+)/(\d+)\]')
_RUN_RE = re.compile(r'^\[RUN\] run_id=(\S+)$')
_HOUDINI_RE = re.compile(r'^\[Houdini\s+(\d+)/(\d+)\]\s*(.*)')


def _line_progress_update(line: str, current_pct: int) -> dict:
    """Map pipeline log lines to UI progress updates."""
    m = _STEP_RE.match(line)
    if m:
        step_n, step_total = int(m.group(1)), int(m.group(2))
        if step_n >= step_total:
            pct = max(current_pct, 75)
        else:
            pct = max(current_pct, min(74, int(step_n / step_total * 75)))
        return {
            'step': step_n,
            'total_steps': step_total,
            'step_label': f'[{step_n}/{step_total}] {line.split("]", 1)[-1].strip()}',
            'pct': pct,
        }

    h = _HOUDINI_RE.match(line)
    if h:
        stage_n, stage_total = int(h.group(1)), int(h.group(2))
        pct = max(current_pct, min(99, 75 + int(stage_n / stage_total * 23)))
        return {
            'step_label': line,
            'pct': pct,
        }

    if '[OK] 全部通过' in line or 'Houdini build completed' in line:
        return {'step_label': 'Houdini 完成，等待状态确认...', 'pct': max(current_pct, 99)}

    if '[OK]' in line and current_pct < 75:
        return {'pct': min(74, current_pct + 3)}

    return {}


def _service_payload() -> dict:
    with _state_lock:
        running = _state.get('running', False)
        done = _state.get('done', False)
        run_id = _state.get('run_id', '')
        name = _state.get('name', '')
    return {
        'app': 'VirtualCity area_picker',
        'server_version': APP_VERSION,
        'pid': os.getpid(),
        'started_at': STARTED_AT,
        'root': str(ROOT),
        'running': running,
        'done': done,
        'name': name,
        'run_id': run_id,
        'auto_shutdown_on_success': AUTO_SHUTDOWN_ON_SUCCESS,
        'no_browser': NO_BROWSER,
    }


def _probe_existing_server() -> dict | None:
    url = f'http://localhost:{PORT}'
    try:
        with urllib.request.urlopen(url + '/health', timeout=1.5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if isinstance(data, dict):
                return data
    except Exception:
        pass

    try:
        with urllib.request.urlopen(url + '/status', timeout=1.5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if isinstance(data, dict):
                data.setdefault('server_version', '')
                data['legacy_server'] = not bool(data.get('server_version'))
                return data
    except Exception:
        return None
    return None


def _open_browser(url: str) -> None:
    if not NO_BROWSER:
        webbrowser.open(url)


def _read_houdini_status(expected_area: str, expected_run_id: str = ''):
    status_file = ROOT / 'Config' / 'houdini_build_status.json'
    if not status_file.exists():
        return False, '', 'status file missing'
    try:
        data = json.loads(status_file.read_text(encoding='utf-8'))
    except Exception as exc:
        return False, '', f'status file unreadable: {exc}'
    area_id = data.get('area_id', '')
    run_id = data.get('run_id', '')
    status = data.get('status', '')
    message = data.get('message', '')
    if area_id != expected_area:
        return False, status, f'area mismatch: {area_id} != {expected_area}'
    if expected_run_id and run_id != expected_run_id:
        return False, status, f'run mismatch: {run_id} != {expected_run_id}'
    return status == 'completed', status, message

def _get_initial_center():
    try:
        cfg = json.loads((ROOT / 'Config' / 'active_area.json').read_text(encoding='utf-8'))
        return cfg.get('origin_lat', 12.94), cfg.get('origin_lon', 100.88)
    except Exception:
        return 12.94, 100.88

_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>VirtualCity — 固定网格框选器</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.css"/>
<style>
* { box-sizing: border-box; }
body { margin:0; font-family: 'Segoe UI', Arial, sans-serif; display:flex; flex-direction:column; height:100vh; background:#0d0d1a; }
#toolbar {
  padding: 10px 16px; background:#12122a; color:#eee;
  display:flex; align-items:center; gap:14px; flex-wrap:wrap;
  border-bottom: 2px solid #1e1e3a;
}
#toolbar h2 { margin:0; font-size:15px; color:#4fc3f7; white-space:nowrap; }
#tile-display {
  font-family: monospace; font-size:12px; color:#a5d6a7;
  background:#1a1a2e; padding:5px 10px; border-radius:4px;
  min-width:390px; border:1px solid #2a2a4a; white-space:pre;
}
.label { color:#9aa7b2; font-size:12px; white-space:nowrap; }
.filter {
  color:#ddd; font-size:13px; display:flex; gap:6px; align-items:center;
  background:#1a1a2e; border:1px solid #2a2a4a; border-radius:4px;
  padding:5px 9px; white-space:nowrap;
}
#run-btn {
  padding:8px 22px; background:#4fc3f7; color:#000;
  border:none; border-radius:5px; font-size:14px;
  font-weight:bold; cursor:pointer; white-space:nowrap;
  transition: background 0.15s;
}
#run-btn:disabled { background:#3a3a5a; color:#666; cursor:not-allowed; }
#run-btn:hover:not(:disabled) { background:#81d4fa; }
#clear-btn {
  padding:8px 12px; background:#1e1e38; color:#ddd;
  border:1px solid #3a3a5a; border-radius:5px; font-size:13px;
  cursor:pointer; white-space:nowrap;
}
#clear-btn:hover { background:#2a2a4a; }
#map { flex:1; }
#legend {
  position:absolute; z-index:450; right:16px; top:74px;
  background:rgba(13,13,26,0.9); color:#ddd; border:1px solid #2a2a4a;
  border-radius:6px; padding:8px 10px; font-size:12px; line-height:1.7;
}
.swatch { display:inline-block; width:18px; height:12px; margin-right:6px; vertical-align:-1px; border:1px solid #778; }
.swatch-empty { background:transparent; }
.swatch-cache { background:rgba(25,118,210,0.35); border-color:#1976d2; }
#progress-container {
  display:none; padding:8px 16px; background:#0f0f22;
  border-top:1px solid #1e1e3a;
}
#progress-bar-wrap {
  background:#1a1a2e; border-radius:6px; height:22px; overflow:hidden;
  border:1px solid #2a2a4a; position:relative;
}
#progress-bar {
  height:100%; background: linear-gradient(90deg, #1565c0, #4fc3f7);
  border-radius:6px; transition: width 0.4s ease;
  box-shadow: 0 0 8px rgba(79,195,247,0.4);
}
#progress-text {
  position:absolute; top:0; left:0; right:0; bottom:0;
  display:flex; align-items:center; justify-content:center;
  font-size:12px; font-weight:bold; color:#fff; text-shadow:0 1px 2px rgba(0,0,0,0.5);
}
#step-label { color:#4fc3f7; font-size:12px; margin-top:5px; }
#log-panel {
  height:160px; background:#080812; color:#80cbc4;
  font-family: monospace; font-size:11.5px;
  padding:8px 14px; overflow-y:auto;
  border-top:2px solid #1e1e3a; white-space:pre-wrap;
}
.ok  { color:#a5d6a7; }
.err { color:#ef9a9a; }
.dim { color:#6f8792; }
.step { color:#4fc3f7; font-weight:bold; }
</style>
</head>
<body>
<div id="toolbar">
  <h2>VirtualCity 固定网格框选器</h2>
  <span class="label">__VERSION__</span>
  <span class="label">用矩形工具框选 1km 基础格；结果会吸附成连续矩形网格块</span>
  <label class="filter"><input id="cached-only" type="checkbox"> 只显示已有缓存</label>
  <span id="grid-status" class="label">加载网格中...</span>
  <div id="tile-display">尚未框选网格</div>
  <button id="clear-btn" onclick="clearSelection()">清除框选</button>
  <button id="run-btn" disabled onclick="runPipeline()">开始生成</button>
</div>
<div id="map">
  <div id="legend">
    <div><span class="swatch swatch-empty"></span>未缓存：无填充</div>
    <div><span class="swatch swatch-cache"></span>已缓存：半透明蓝色</div>
  </div>
</div>
<div id="progress-container">
  <div id="progress-bar-wrap">
    <div id="progress-bar" style="width:0%"></div>
    <div id="progress-text">0%</div>
  </div>
  <div id="step-label">准备中...</div>
</div>
<div id="log-panel">等待选择网格...</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.js"></script>
<script>
var selection = null;
var selectedTileIds = {};
var lastGridData = null;
var gridLayer = null;
var drawnItems = null;
var gridRequestId = 0;
var gridTimer = null;
var maxSelectionTiles = __MAX_SELECTION_TILES__;

var map = L.map('map').setView([__LAT__, __LON__], 14);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap contributors', maxZoom: 19
}).addTo(map);
gridLayer = L.layerGroup().addTo(map);
drawnItems = new L.FeatureGroup();
map.addLayer(drawnItems);

var drawControl = new L.Control.Draw({
  draw: {
    rectangle: { shapeOptions: { color: '#ffeb3b', weight: 2, fillOpacity: 0.02 } },
    polygon: false, polyline: false, circle: false,
    marker: false, circlemarker: false
  },
  edit: { featureGroup: drawnItems, edit: false, remove: true }
});
map.addControl(drawControl);

map.on(L.Draw.Event.CREATED, function(e) {
  drawnItems.clearLayers();
  e.layer.setStyle({ opacity: 0, fillOpacity: 0 });
  drawnItems.addLayer(e.layer);
  selectTilesByBounds(e.layer.getBounds());
});

map.on(L.Draw.Event.DELETED, function() {
  clearSelection();
});

document.getElementById('cached-only').addEventListener('change', function() {
  renderGrid(lastGridData);
});

function tileStyle(tile) {
  var isSelected = !!selectedTileIds[tile.tile_id];
  return {
    color: isSelected ? '#ffeb3b' : (tile.cached ? '#1976d2' : '#7f8a99'),
    weight: isSelected ? 3 : 1,
    opacity: isSelected ? 1.0 : 0.72,
    fillColor: '#1976d2',
    fillOpacity: tile.cached ? 0.34 : 0.0,
    dashArray: tile.cached ? null : '4 4'
  };
}

function kmSize(tile) {
  return (tile.size_m / 1000).toFixed(0) + 'km x ' + (tile.size_m / 1000).toFixed(0) + 'km';
}

function selectionId(sel) {
  var hemi = sel.northern ? 'n' : 's';
  return 'z' + sel.zone + hemi + '_e' + sel.easting + '_n' + sel.northing +
    '_w' + sel.width_m + '_h' + sel.height_m + '_s' + sel.size_m;
}

function updateTileDisplay() {
  var el = document.getElementById('tile-display');
  if (!selection) {
    el.textContent = '尚未框选网格';
    document.getElementById('run-btn').disabled = true;
    return;
  }
  var b = selection.bbox;
  var total = selection.tiles.length;
  var cached = selection.tiles.filter(function(tile) { return tile.cached; }).length;
  var cacheText = cached === total ? '全部已有本地缓存' : ('已缓存 ' + cached + '/' + total + '，其余运行时下载');
  el.textContent =
    selection.selection_id + ' | ' + selection.cols + ' x ' + selection.rows + ' 格 | ' +
    (selection.width_m / 1000) + 'km x ' + (selection.height_m / 1000) + 'km | ' + cacheText + '\n' +
    'W:' + b[0].toFixed(6) + '  S:' + b[1].toFixed(6) + '  E:' + b[2].toFixed(6) + '  N:' + b[3].toFixed(6);
  document.getElementById('run-btn').disabled = false;
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

function setSelection(seedTiles) {
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
  refreshTileStyles();
  var cached = rectTiles.filter(function(tile) { return tile.cached; }).length;
  log('已框选: ' + selection.selection_id + '  ' + rectTiles.length + ' 格，已缓存 ' + cached + '/' + rectTiles.length, 'ok');
}

function selectTilesByBounds(bounds) {
  if (!lastGridData || !lastGridData.tiles || !lastGridData.tiles.length) {
    log('网格尚未加载完成，请稍等。', 'err');
    return;
  }
  var hits = lastGridData.tiles.filter(function(tile) {
    return bboxIntersects(bounds, tile.bbox);
  });
  setSelection(hits);
}

function clearSelection() {
  selection = null;
  selectedTileIds = {};
  drawnItems.clearLayers();
  updateTileDisplay();
  refreshTileStyles();
}

function renderGrid(data) {
  gridLayer.clearLayers();
  if (!data) return;
  lastGridData = data;
  if (data.truncated) {
    document.getElementById('grid-status').textContent = data.message || '视口太大，请放大';
    return;
  }
  var cachedOnly = document.getElementById('cached-only').checked;
  var shown = 0;
  var cached = 0;
  data.tiles.forEach(function(tile) {
    if (tile.cached) cached += 1;
    if (cachedOnly && !tile.cached) return;
    var options = tileStyle(tile);
    options.interactive = false;
    var poly = L.polygon(tile.corners, options);
    poly.vcTile = tile;
    poly.addTo(gridLayer);
    shown += 1;
  });
  document.getElementById('grid-status').textContent =
    '显示 ' + shown + ' / ' + data.tiles.length + ' 格；已缓存 ' + cached + ' 格';
  refreshTileStyles();
}

function loadGrid() {
  var b = map.getBounds();
  var req = ++gridRequestId;
  var url = '/tiles?west=' + encodeURIComponent(b.getWest()) +
    '&south=' + encodeURIComponent(b.getSouth()) +
    '&east=' + encodeURIComponent(b.getEast()) +
    '&north=' + encodeURIComponent(b.getNorth());
  document.getElementById('grid-status').textContent = '加载网格中...';
  fetch(url)
  .then(function(r) { return r.json(); })
  .then(function(data) {
    if (req !== gridRequestId) return;
    renderGrid(data);
  })
  .catch(function(e) {
    document.getElementById('grid-status').textContent = '网格加载失败';
    log('[错误] 网格加载失败: ' + e, 'err');
  });
}

function scheduleGridLoad() {
  clearTimeout(gridTimer);
  gridTimer = setTimeout(loadGrid, 120);
}

map.on('moveend zoomend', scheduleGridLoad);
scheduleGridLoad();

function log(msg, cls) {
  var el = document.getElementById('log-panel');
  var line = document.createElement('span');
  if (cls) line.className = cls;
  line.textContent = msg + '\n';
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

var _pollTimer = null;
var _lastLogLen = 0;

function pollStatus() {
  fetch('/status')
  .then(r => r.json())
  .then(d => {
    var pct = d.pct || 0;
    document.getElementById('progress-bar').style.width = pct + '%';
    document.getElementById('progress-text').textContent = pct + '%';
    document.getElementById('step-label').textContent = d.step_label || '运行中...';

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

    if (d.done) {
      clearInterval(_pollTimer);
      _pollTimer = null;
      document.getElementById('progress-bar').style.width = '100%';
      document.getElementById('progress-text').textContent = '100%';
      if (d.ok) {
        document.getElementById('progress-bar').style.background = 'linear-gradient(90deg, #2e7d32, #a5d6a7)';
        document.getElementById('step-label').textContent = '[OK] 生成完成';
        log('[OK] 生成完成！区域: ' + d.name, 'ok');
        if (d.run_id) log('run_id: ' + d.run_id, 'dim');
        if (d.auto_shutdown_on_success) {
          log('3 秒后自动关闭页面，5 秒后停止本地服务...', 'dim');
          setTimeout(function() {
            window.open('', '_self');
            window.close();
            document.body.innerHTML = '<div style="font-family:Segoe UI,Arial,sans-serif;background:#0d0d1a;color:#a5d6a7;height:100vh;display:flex;align-items:center;justify-content:center;flex-direction:column;"><h2>[OK] VirtualCity 生成完成</h2><p>本地服务已自动停止，可以关闭此页面。</p></div>';
          }, 3000);
        } else {
          log('状态服务保持运行，可继续查看 /status 或继续选择网格测试。', 'dim');
          document.getElementById('run-btn').disabled = false;
          scheduleGridLoad();
        }
      } else {
        document.getElementById('progress-bar').style.background = 'linear-gradient(90deg, #c62828, #ef9a9a)';
        document.getElementById('step-label').textContent = '[FAIL] 管线出错';
        log('[FAIL] 管线出错 (exit=' + d.returncode + ')', 'err');
        document.getElementById('run-btn').disabled = false;
      }
    }
  })
  .catch(function() { /* server may be restarting */ });
}

function runPipeline() {
  if (!selection) return;
  var name = selection.selection_id;
  var b = selection.bbox;
  document.getElementById('run-btn').disabled = true;
  document.getElementById('log-panel').innerHTML = '';
  _lastLogLen = 0;
  document.getElementById('progress-container').style.display = 'block';
  document.getElementById('progress-bar').style.width = '0%';
  document.getElementById('progress-bar').style.background = 'linear-gradient(90deg, #1565c0, #4fc3f7)';
  document.getElementById('progress-text').textContent = '0%';
  document.getElementById('step-label').textContent = '准备中...';
  log('[' + new Date().toLocaleTimeString() + '] 提交网格块: ' + name, 'ok');
  log('bbox = [' + b[0]+', '+b[1]+', '+b[2]+', '+b[3]+']', 'dim');

  fetch('/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tile_ids: selection.tiles.map(function(tile) { return tile.tile_id; }) })
  })
  .then(r => r.json())
  .then(d => {
    if (d.ok) {
      log('管线已启动...', 'dim');
      _pollTimer = setInterval(pollStatus, 1000);
    } else {
      log('[错误] ' + d.message, 'err');
      document.getElementById('run-btn').disabled = false;
    }
  })
  .catch(e => {
    log('[网络错误] ' + e, 'err');
    document.getElementById('run-btn').disabled = false;
  });
}
</script>
</body>
</html>"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # Suppress default access logs

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/health':
            self._json(_service_payload())
            return
        if parsed.path == '/status':
            with _state_lock:
                elapsed = int(time.time() - _state['start']) if _state['running'] or _state['done'] else 0
                resp = {
                    'done':       _state['done'],
                    'ok':         _state['ok'],
                    'returncode': _state['returncode'],
                    'name':       _state['name'],
                    'run_id':     _state['run_id'],
                    'elapsed':    elapsed,
                    'step':       _state['step'],
                    'total_steps': _state['total_steps'],
                    'step_label': _state['step_label'],
                    'pct':        _state['pct'],
                    'log_lines':  list(_state['log_lines']),
                    'houdini_done':    _state['houdini_done'],
                    'houdini_status':  _state['houdini_status'],
                    'houdini_message': _state['houdini_message'],
                    'server_version':  APP_VERSION,
                    'pid':             os.getpid(),
                    'started_at':      STARTED_AT,
                    'auto_shutdown_on_success': AUTO_SHUTDOWN_ON_SUCCESS,
                    'no_browser':      NO_BROWSER,
                }
            self._json(resp)
            return
        if parsed.path == '/tiles':
            try:
                params = urllib.parse.parse_qs(parsed.query)

                def param(name: str) -> float:
                    value = params.get(name, [None])[0]
                    if value is None:
                        raise ValueError(f'missing {name}')
                    return float(value)

                bbox = [param('west'), param('south'), param('east'), param('north')]
                if not (bbox[0] < bbox[2] and bbox[1] < bbox[3]):
                    raise ValueError('invalid viewport bbox')
                self._json(vc_grid.tiles_for_bbox(bbox))
            except Exception as exc:
                self._json({'tiles': [], 'truncated': True, 'message': f'网格参数错误: {exc}'})
            return
        lat, lon = _get_initial_center()
        html = (_HTML
                .replace('__LAT__', str(lat))
                .replace('__LON__', str(lon))
                .replace('__VERSION__', APP_VERSION)
                .replace('__MAX_SELECTION_TILES__', str(vc_grid.MAX_SELECTION_TILES)))
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != '/run':
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get('Content-Length', 0))
        try:
            body = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._json({'ok': False, 'message': '请求 JSON 无法解析'})
            return

        tile_ids = body.get('tile_ids')
        if tile_ids is None and body.get('tile_id'):
            tile_ids = [body.get('tile_id')]
        if not isinstance(tile_ids, list) or not tile_ids:
            self._json({'ok': False, 'message': '请先框选一个或多个固定网格'})
            return
        try:
            selection = vc_grid.selection_from_tile_ids(tile_ids)
        except ValueError as exc:
            self._json({'ok': False, 'message': f'网格框选无效: {exc}'})
            return
        west, south, east, north = selection['bbox']
        bbox = {'west': west, 'south': south, 'east': east, 'north': north}
        name = selection['selection_id']

        with _state_lock:
            if _state.get('running'):
                self._json({'ok': False, 'message': '已有管线正在运行，请等待当前流程结束'})
                return
            _state.update({'running': True, 'done': False, 'ok': False,
                           'returncode': None, 'name': name, 'start': time.time(),
                           'run_id': '',
                           'step': 0, 'total_steps': 6, 'step_label': '启动中...', 'pct': 0,
                           'log_lines': [],
                           'houdini_done': False, 'houdini_status': '', 'houdini_message': ''})

        cmd = [
            'uv', 'run', 'python', '-u', 'set_area.py',
            str(bbox['west']), str(bbox['south']),
            str(bbox['east']), str(bbox['north']),
            name,
        ]
        _safe_print(f"\n[area_picker] 启动管线: {' '.join(cmd)}")

        def _run():
            proc = None
            try:
                env = os.environ.copy()
                env['PYTHONIOENCODING'] = 'utf-8'
                proc = subprocess.Popen(
                    cmd, cwd=str(SCRIPTS),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', errors='replace',
                    bufsize=1,
                    env=env,
                )
                for raw_line in proc.stdout:
                    line = raw_line.rstrip('\n\r')
                    if not line:
                        continue
                    _safe_print(line)  # echo to terminal
                    with _state_lock:
                        _state['log_lines'].append(line)
                        if len(_state['log_lines']) > _MAX_LOG_LINES:
                            _state['log_lines'] = _state['log_lines'][-_MAX_LOG_LINES:]
                        progress = _line_progress_update(line, int(_state.get('pct', 0)))
                        if progress:
                            _state.update(progress)
                        run_match = _RUN_RE.match(line)
                        if run_match:
                            _state['run_id'] = run_match.group(1)

                proc.wait()
                returncode = proc.returncode
                with _state_lock:
                    run_id = _state.get('run_id', '')
                houdini_done, houdini_status, houdini_message = _read_houdini_status(name, run_id)
                ok = returncode == 0 and houdini_done
            except Exception as exc:
                returncode = proc.returncode if proc is not None else -1
                houdini_done, houdini_status, houdini_message = False, 'exception', str(exc)
                ok = False
                try:
                    _safe_print(f'[area_picker] 管线线程异常: {exc}')
                except Exception:
                    _safe_print('[area_picker] pipeline thread exception')

            with _state_lock:
                if ok and not houdini_done:
                    _state['log_lines'].append(f'[WARN] Houdini 状态文件未确认，但 set_area.py 已成功退出: {houdini_message}')
                _state.update({'running': False, 'done': True,
                               'ok': ok,
                               'returncode': returncode,
                               'pct': 100 if ok else _state['pct'],
                               'step_label': '[OK] 完成' if ok else '[FAIL] 失败',
                               'houdini_done': houdini_done,
                               'houdini_status': houdini_status,
                               'houdini_message': houdini_message})
            status = 'OK' if ok else f'FAIL(exit={returncode}, houdini={houdini_status})'
            _safe_print(f'[area_picker] 管线结束: {status}')
            if houdini_done:
                _safe_print('[area_picker] Houdini 构建完成已确认')
            else:
                _safe_print(f'[area_picker] Houdini 构建完成未确认: {houdini_message}')
            if ok:
                if AUTO_SHUTDOWN_ON_SUCCESS:
                    _safe_print('[area_picker] 5 秒后自动退出服务器...')
                    time.sleep(5)
                    _server_ref[0].shutdown()
                else:
                    _safe_print('[area_picker] 状态服务保持运行，按 Ctrl+C 退出')

        threading.Thread(target=_run, daemon=True).start()
        self._json({'ok': True, 'message': f'管线已启动: {name}'})

    def _json(self, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    lat, lon = _get_initial_center()
    url = f'http://localhost:{PORT}'
    existing = _probe_existing_server()
    if existing:
        version = existing.get('server_version', '')
        if version == APP_VERSION:
            print(f"[area_picker] 已有当前版本服务在运行: {url}")
            print(f"  pid={existing.get('pid')} running={existing.get('running')} run_id={existing.get('run_id', '')}")
            _open_browser(url)
            return 0
        print(f"[FAIL] 端口 {PORT} 已被旧版或未知 area_picker 服务占用。")
        print("       请关闭旧的 area_picker 终端/进程后重新运行，避免误用旧代码。")
        print(f"       当前探测状态: version={version!r} running={existing.get('running')} run_id={existing.get('run_id', '')}")
        return 2

    print(f"\n{'='*52}")
    print(f"  VirtualCity 区域选择器")
    print(f"  当前区域中心: ({lat:.4f}, {lon:.4f})")
    print(f"  浏览器地址:   {url}")
    print(f"{'='*52}")
    print(f"  操作步骤:")
    print(f"    1. 放大到目标区域")
    print(f"    2. 点击左侧矩形工具，框选 1 个或多个 1km x 1km 网格")
    print(f"    3. 点击 [开始生成] 按钮")
    print(f"{'='*52}\n")
    print(f"  按 Ctrl+C 退出\n")

    try:
        server = HTTPServer(('localhost', PORT), _Handler)
    except OSError as exc:
        print(f"[FAIL] 无法启动 area_picker 服务: {exc}")
        print(f"       端口 {PORT} 可能仍被其他进程占用。")
        return 2
    _server_ref[0] = server
    if not NO_BROWSER:
        threading.Timer(1.0, lambda: _open_browser(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    print('[area_picker] 已退出')
    return 0


if __name__ == '__main__':
    sys.exit(main())
