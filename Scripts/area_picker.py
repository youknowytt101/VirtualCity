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

import sys, json, subprocess, threading, webbrowser, time, os, re, socket, mimetypes, urllib.error, urllib.request, urllib.parse
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

import vc_grid

APP_VERSION = "2026-06-01-online-only-console-v14"
STARTED_AT = time.strftime("%Y-%m-%d %H:%M:%S")
AUTO_SHUTDOWN_ON_SUCCESS = os.environ.get("VC_AREA_PICKER_AUTO_SHUTDOWN") == "1"
NO_BROWSER = os.environ.get("VC_AREA_PICKER_NO_BROWSER") == "1"
SHUTDOWN_WITH_PAGE = os.environ.get("VC_AREA_PICKER_SHUTDOWN_WITH_PAGE") == "1"
PAGE_SESSION_GRACE_SECONDS = 30.0
PAGE_CLOSE_GRACE_SECONDS = 4.0

# Global pipeline state
_state = {'running': False, 'done': False, 'ok': False, 'returncode': None, 'name': '', 'start': 0.0,
          'operation': '',
          'run_id': '',
          'houdini_done': False, 'houdini_status': '', 'houdini_message': '',
          'step': 0, 'total_steps': 6, 'step_label': '', 'log_lines': [], 'pct': 0,
          'export_running': False, 'export_done': False, 'export_ok': False,
          'export_returncode': None, 'export_log_lines': []}
_state_lock = threading.Lock()
_server_ref = [None]  # mutable ref so _run thread can call shutdown()
_MAX_LOG_LINES = 80
_page_lock = threading.Lock()
_page_state = {'seen': False, 'last_seen': 0.0, 'close_requested': False, 'closed_at': 0.0,
               'monitor_started': False}


def _safe_print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(str(msg).encode('ascii', errors='backslashreplace').decode('ascii'))

SCRIPTS = Path(__file__).resolve().parent
ROOT    = SCRIPTS.parent
STATIC_ROOT = SCRIPTS / 'web_assets'
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
        export_running = _state.get('export_running', False)
        done = _state.get('done', False)
        run_id = _state.get('run_id', '')
        name = _state.get('name', '')
        operation = _state.get('operation', '')
    return {
        'app': 'VirtualCity area_picker',
        'server_version': APP_VERSION,
        'pid': os.getpid(),
        'started_at': STARTED_AT,
        'root': str(ROOT),
        'running': running,
        'done': done,
        'name': name,
        'operation': operation,
        'run_id': run_id,
        'auto_shutdown_on_success': AUTO_SHUTDOWN_ON_SUCCESS,
        'no_browser': NO_BROWSER,
        'shutdown_with_page': SHUTDOWN_WITH_PAGE,
        'houdini_available': _probe_houdini(),
        'export_available': False if running or export_running else _export_available(),
    }


def _mark_page_seen(now: float | None = None) -> None:
    now = time.time() if now is None else now
    with _page_lock:
        _page_state.update({'seen': True, 'last_seen': now, 'close_requested': False, 'closed_at': 0.0})


def _mark_page_closed(now: float | None = None) -> None:
    now = time.time() if now is None else now
    with _page_lock:
        _page_state.update({'seen': True, 'close_requested': True, 'closed_at': now})


def _page_shutdown_due(now: float | None = None, *, enabled: bool | None = None) -> bool:
    enabled = SHUTDOWN_WITH_PAGE if enabled is None else enabled
    if not enabled:
        return False
    with _state_lock:
        if _state.get('running') or _state.get('export_running'):
            return False
    now = time.time() if now is None else now
    with _page_lock:
        if not _page_state.get('seen'):
            return False
        last_seen = float(_page_state.get('last_seen') or 0.0)
        close_requested = bool(_page_state.get('close_requested'))
        closed_at = float(_page_state.get('closed_at') or 0.0)
    if close_requested:
        return (now - closed_at) >= PAGE_CLOSE_GRACE_SECONDS and (now - last_seen) >= PAGE_CLOSE_GRACE_SECONDS
    return (now - last_seen) >= PAGE_SESSION_GRACE_SECONDS


def _start_page_monitor() -> None:
    if not SHUTDOWN_WITH_PAGE:
        return
    with _page_lock:
        if _page_state.get('monitor_started'):
            return
        _page_state['monitor_started'] = True

    def _monitor() -> None:
        while True:
            time.sleep(1.0)
            server = _server_ref[0]
            if server is None:
                continue
            if _page_shutdown_due():
                _safe_print('[area_picker] 网页已关闭，自动停止本地服务...')
                server.shutdown()
                return

    threading.Thread(target=_monitor, daemon=True).start()


def _probe_houdini(timeout: float = 0.35) -> bool:
    """Return whether the local Houdini RPYC port accepts connections."""
    try:
        with socket.create_connection(('127.0.0.1', 18811), timeout=timeout):
            return True
    except OSError:
        return False


def _export_available() -> bool:
    """Return whether QA passed and the current Houdini session still has exportable geometry."""
    try:
        cfg = json.loads((ROOT / 'Config' / 'active_area.json').read_text(encoding='utf-8'))
    except Exception:
        return False
    ok, _, _ = _read_houdini_status(cfg.get('area_id', ''), cfg.get('run_id', ''))
    return ok and _houdini_model_available(cfg)


def _houdini_model_available(cfg: dict | None = None, timeout: float = 1.5) -> bool:
    """Probe live OUT_city geometry without loading a HIP or forcing a recook."""
    if not _probe_houdini():
        return False
    conn = None
    try:
        import rpyc
        conn = rpyc.classic.connect('localhost', 18811)
        conn._config['sync_request_timeout'] = timeout
        hou = conn.modules.hou
        obj_net = (cfg or {}).get('obj_network', 'city_gen')
        out_city = hou.node(f'/obj/{obj_net}/OUT_city')
        if out_city is None and obj_net == 'city_gen':
            out_city = hou.node('/obj/pattaya_osm/OUT_city')
        if out_city is None:
            return False
        if not out_city.isDisplayFlagSet():
            return False
        geo = out_city.geometry()
        if geo is None:
            return False
        points = int(geo.intrinsicValue('pointcount'))
        prims = int(geo.intrinsicValue('primitivecount'))
        return points > 0 and prims > 0
    except Exception:
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


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
<link rel="stylesheet" href="/static/leaflet/leaflet.css"/>
<link rel="stylesheet" href="/static/leaflet-draw/leaflet.draw.css"/>
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
#run-btn, #export-btn, #download-btn {
  padding:8px 22px; background:#4fc3f7; color:#000;
  border:none; border-radius:5px; font-size:14px;
  font-weight:bold; cursor:pointer; white-space:nowrap;
  transition: background 0.15s;
}
#export-btn { background:#a5d6a7; }
#download-btn { background:#ffcc80; }
#run-btn:disabled, #export-btn:disabled, #download-btn:disabled { background:#3a3a5a; color:#666; cursor:not-allowed; }
#run-btn:hover:not(:disabled) { background:#81d4fa; }
#export-btn:hover:not(:disabled) { background:#c8e6c9; }
#download-btn:hover:not(:disabled) { background:#ffe0b2; }
#clear-btn {
  padding:8px 12px; background:#1e1e38; color:#ddd;
  border:1px solid #3a3a5a; border-radius:5px; font-size:13px;
  cursor:pointer; white-space:nowrap;
}
#clear-btn:hover { background:#2a2a4a; }
.badge {
  padding:4px 10px; border-radius:10px; font-size:12px; white-space:nowrap;
  border:none; cursor:pointer; font-family:inherit;
}
.badge-ok { background:#1b5e20; color:#c8e6c9; }
.badge-warn { background:#6d4c00; color:#fff3cd; }
.badge:hover:not(:disabled) { filter:brightness(1.14); }
.badge:disabled { opacity:0.75; cursor:wait; }
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
#log-tabs {
  background: #0c0c1b;
  border-top: 1px solid #1e1e3a;
  display: flex;
  padding: 4px 10px 0 10px;
}
.tab-btn {
  background: transparent;
  border: none;
  color: #6f8792;
  font-family: inherit;
  font-size: 11px;
  font-weight: bold;
  padding: 6px 14px;
  cursor: pointer;
  border-radius: 4px 4px 0 0;
  border-bottom: 2px solid transparent;
  transition: all 0.2s ease;
  margin-right: 4px;
}
.tab-btn:hover {
  color: #80cbc4;
  background: rgba(128, 203, 196, 0.05);
}
.tab-btn.active {
  color: #4fc3f7;
  border-bottom: 2px solid #4fc3f7;
  background: rgba(79, 195, 247, 0.08);
}
.log-panel {
  height: 160px; background:#080812; color:#80cbc4;
  font-family: monospace; font-size:11.5px;
  padding:8px 14px; overflow-y:auto;
  white-space:pre-wrap;
  border-top: 1px solid #1e1e3a;
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
  <button id="houdini-badge" type="button" class="badge badge-warn" onclick="probeHoudini()" title="点击探测 Houdini RPYC 连接">检查 Houdini</button>
  <span id="grid-status" class="label">加载网格中...</span>
  <div id="tile-display">尚未框选网格</div>
  <button id="clear-btn" onclick="clearSelection()">清除框选</button>
  <button id="run-btn" disabled onclick="runPipeline()">Houdini 生成</button>
  <button id="export-btn" disabled onclick="exportFbx()">导出 FBX</button>
  <button id="download-btn" disabled onclick="downloadData()">下载数据</button>
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
<div id="log-tabs">
  <button class="tab-btn active" onclick="switchTab('all')">📊 完整控制台</button>
  <button class="tab-btn" onclick="switchTab('clean')">🧹 离线精炼</button>
  <button class="tab-btn" onclick="switchTab('houdini')">🏗️ Houdini 算子</button>
  <button class="tab-btn" onclick="switchTab('qa')">✅ QA 质量审查</button>
</div>
<div id="log-panels-container">
  <div id="log-panel-all" class="log-panel">等待选择网格...</div>
  <div id="log-panel-clean" class="log-panel" style="display:none">等待数据下载或精炼...</div>
  <div id="log-panel-houdini" class="log-panel" style="display:none">等待 Houdini RPYC 执行...</div>
  <div id="log-panel-qa" class="log-panel" style="display:none">等待 Model QA 诊断报告...</div>
</div>

<script src="/static/leaflet/leaflet.js"></script>
<script src="/static/leaflet-draw/leaflet.draw.js"></script>
<script>
var selection = null;
var selectedTileIds = {};
var lastGridData = null;
var gridLayer = null;
var drawnItems = null;
var gridRequestId = 0;
var gridTimer = null;
var maxSelectionTiles = __MAX_SELECTION_TILES__;
var shutdownWithPage = __SHUTDOWN_WITH_PAGE__;
var pageSessionTimer = null;

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

function setHoudiniBadge(available) {
  var el = document.getElementById('houdini-badge');
  el.disabled = false;
  if (available) {
    el.className = 'badge badge-ok';
    el.textContent = 'Houdini 已连接';
  } else {
    el.className = 'badge badge-warn';
    el.textContent = 'Houdini 未连接';
  }
}

function setHoudiniChecking() {
  var el = document.getElementById('houdini-badge');
  el.className = 'badge badge-warn';
  el.textContent = '探测中...';
  el.disabled = true;
}

function updateExportButton(available, running) {
  var btn = document.getElementById('export-btn');
  btn.disabled = !available || !!running;
}

function updateSelectionButtons(running) {
  var disabled = !selection || !!running;
  document.getElementById('run-btn').disabled = disabled;
  document.getElementById('download-btn').disabled = disabled;
}

function refreshServiceState() {
  fetch('/health')
  .then(function(r) { return r.json(); })
  .then(function(d) {
    setHoudiniBadge(!!d.houdini_available);
    updateExportButton(!!d.export_available, !!d.running);
    updateSelectionButtons(!!d.running);
  })
  .catch(function() {
    setHoudiniBadge(false);
  });
}

function probeHoudini() {
  setHoudiniChecking();
  refreshServiceState();
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
    updateSelectionButtons(false);
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
  updateSelectionButtons(false);
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
        document.getElementById('progress-bar').style.background = 'linear-gradient(90deg, #2e7d32, #a5d6a7)';
        var doneLabel = d.operation === 'download' ? '[OK] 数据下载完成' : '[OK] 生成完成';
        var doneLog = d.operation === 'download' ? '[OK] 数据下载完成！区域: ' : '[OK] 生成完成！区域: ';
        document.getElementById('step-label').textContent = doneLabel;
        log(doneLog + d.name, 'ok');
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
          updateSelectionButtons(false);
          scheduleGridLoad();
          refreshServiceState();
        }
      } else {
        document.getElementById('progress-bar').style.background = 'linear-gradient(90deg, #c62828, #ef9a9a)';
        document.getElementById('step-label').textContent = '[FAIL] 管线出错';
        log('[FAIL] 管线出错 (exit=' + d.returncode + ')', 'err');
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
  document.getElementById('progress-container').style.display = 'block';
  document.getElementById('progress-bar').style.width = '0%';
  document.getElementById('progress-bar').style.background = 'linear-gradient(90deg, #1565c0, #4fc3f7)';
  document.getElementById('progress-text').textContent = '0%';
  document.getElementById('step-label').textContent = '准备中...';
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
startPageSession();
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
                    'operation':  _state.get('operation', ''),
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
                    'shutdown_with_page': SHUTDOWN_WITH_PAGE,
                    'houdini_available': _probe_houdini(),
                    'export_available': False if _state['running'] or _state['export_running'] else _export_available(),
                    'export_running': _state['export_running'],
                    'export_done': _state['export_done'],
                    'export_ok': _state['export_ok'],
                    'export_returncode': _state['export_returncode'],
                    'export_log_lines': list(_state['export_log_lines']),
                }
            self._json(resp)
            return
        if parsed.path.startswith('/static/'):
            self._static(parsed.path)
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
        if parsed.path not in ('/', ''):
            self.send_response(404)
            self.end_headers()
            return
        lat, lon = _get_initial_center()
        html = (_HTML
                .replace('__LAT__', str(lat))
                .replace('__LON__', str(lon))
                .replace('__VERSION__', APP_VERSION)
                .replace('__MAX_SELECTION_TILES__', str(vc_grid.MAX_SELECTION_TILES))
                .replace('__SHUTDOWN_WITH_PAGE__', 'true' if SHUTDOWN_WITH_PAGE else 'false'))
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/shutdown':
            _safe_print('[area_picker] 收到来自新实例的停机指令，正在释放资源准备退出...')
            self._json({'ok': True, 'message': 'shutting down'})
            threading.Thread(target=lambda: _server_ref[0].shutdown()).start()
            return
        if parsed.path == '/session':
            _mark_page_seen()
            _start_page_monitor()
            self._json({'ok': True})
            return
        if parsed.path == '/session/closed':
            _mark_page_closed()
            _start_page_monitor()
            self._json({'ok': True})
            return
        if parsed.path == '/export':
            self._post_export()
            return
        if parsed.path not in ('/run', '/download-data'):
            self.send_response(404)
            self.end_headers()
            return
        data_only = parsed.path == '/download-data'

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
        if not data_only and not _probe_houdini():
            self._json({'ok': False, 'message': 'Houdini 未连接。请先打开 Houdini，并确认 RPYC 端口 18811 可用。'})
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
                           'operation': 'download' if data_only else 'generate',
                           'run_id': '',
                           'step': 0, 'total_steps': 6, 'step_label': '启动中...', 'pct': 0,
                           'log_lines': [],
                           'houdini_done': False, 'houdini_status': '', 'houdini_message': '',
                           'export_done': False, 'export_ok': False, 'export_returncode': None,
                           'export_log_lines': []})

        cmd = [
            'uv', 'run', 'python', '-u', 'set_area.py',
            str(bbox['west']), str(bbox['south']),
            str(bbox['east']), str(bbox['north']),
            name,
        ]
        if data_only:
            cmd.insert(5, '--data-only')
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
                if data_only:
                    houdini_done, houdini_status, houdini_message = False, 'skipped', 'data download only'
                    ok = returncode == 0
                else:
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
                if ok and not houdini_done and not data_only:
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
            if data_only:
                _safe_print('[area_picker] 数据下载完成，Houdini 重算已跳过')
            elif houdini_done:
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
        message = f'数据下载已启动: {name}' if data_only else f'Houdini 生成已启动: {name}'
        self._json({'ok': True, 'message': message})

    def _post_export(self):
        if not _export_available():
            self._json({'ok': False, 'message': '当前区域还没有通过 Houdini Model QA，不能导出 FBX。'})
            return
        if not _probe_houdini():
            self._json({'ok': False, 'message': 'Houdini 未连接，无法导出 FBX。'})
            return
        with _state_lock:
            if _state.get('running'):
                self._json({'ok': False, 'message': '生成管线正在运行，完成后再导出 FBX。'})
                return
            if _state.get('export_running'):
                self._json({'ok': False, 'message': 'FBX 导出正在运行。'})
                return
            _state.update({
                'export_running': True,
                'export_done': False,
                'export_ok': False,
                'export_returncode': None,
                'export_log_lines': ['[导出] Houdini FBX 导出开始（不触发 UE5 导入）'],
            })

        def _run_export():
            proc = None
            try:
                env = os.environ.copy()
                env['PYTHONIOENCODING'] = 'utf-8'
                proc = subprocess.Popen(
                    ['uv', 'run', 'python', '-u', 'export_and_import.py', '--fbx-only'],
                    cwd=str(SCRIPTS),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', errors='replace',
                    bufsize=1,
                    env=env,
                )
                for raw_line in proc.stdout:
                    line = raw_line.rstrip('\n\r')
                    if not line:
                        continue
                    _safe_print(line)
                    with _state_lock:
                        _state['export_log_lines'].append(line)
                        if len(_state['export_log_lines']) > _MAX_LOG_LINES:
                            _state['export_log_lines'] = _state['export_log_lines'][-_MAX_LOG_LINES:]
                proc.wait()
                returncode = proc.returncode
                ok = returncode == 0
            except Exception as exc:
                returncode = proc.returncode if proc is not None else -1
                ok = False
                with _state_lock:
                    _state['export_log_lines'].append(f'[FAIL] 导出线程异常: {exc}')

            with _state_lock:
                _state.update({
                    'export_running': False,
                    'export_done': True,
                    'export_ok': ok,
                    'export_returncode': returncode,
                })
                _state['export_log_lines'].append('[OK] FBX 导出完成' if ok else f'[FAIL] FBX 导出失败 exit={returncode}')
            _safe_print('[area_picker] FBX 导出完成' if ok else f'[area_picker] FBX 导出失败 exit={returncode}')

        threading.Thread(target=_run_export, daemon=True).start()
        self._json({'ok': True, 'message': 'FBX 导出已启动'})

    def _static(self, request_path: str):
        rel = urllib.parse.unquote(request_path[len('/static/'):]).replace('\\', '/').lstrip('/')
        target = (STATIC_ROOT / rel).resolve()
        try:
            target.relative_to(STATIC_ROOT.resolve())
        except ValueError:
            self.send_response(403)
            self.end_headers()
            return
        if not target.exists() or not target.is_file():
            self.send_response(404)
            self.end_headers()
            return
        body = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'public, max-age=86400')
        self.end_headers()
        self.wfile.write(body)

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
            existing_shutdown = bool(existing.get('shutdown_with_page', False))
            if existing_shutdown == SHUTDOWN_WITH_PAGE:
                print(f"[area_picker] 已有当前版本服务在运行: {url}")
                print(f"  pid={existing.get('pid')} running={existing.get('running')} run_id={existing.get('run_id', '')}")
                _open_browser(url)
                return 0

        # Try to shut down the existing server gracefully
        print(f"[area_picker] 发现端口 {PORT} 被旧服务 (pid={existing.get('pid', 'unknown')}) 占用，正在发送停机指令...")
        try:
            req = urllib.request.Request(f"{url}/shutdown", data=b'{}', headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                print("[area_picker] 停机指令发送成功，正在等待旧服务优雅释放端口...")
                time.sleep(2.5) # Give the old process some buffer time to release port
        except Exception as e:
            print(f"[WARN] 无法优雅关闭旧服务: {e}")

        # Re-probe to check if the old server actually went offline
        still_running = _probe_existing_server()
        if still_running:
            print(f"[FAIL] 端口 {PORT} 的旧服务拒绝停机或仍未释放端口。")
            print("       请手动关闭占用该端口的终端或进程后再重试。")
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
    if SHUTDOWN_WITH_PAGE:
        print(f"    4. 关闭网页后，本地服务会自动退出")
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
