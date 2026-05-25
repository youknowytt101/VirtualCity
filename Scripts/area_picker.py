"""
VirtualCity — 交互式区域选择器
================================
运行后自动打开浏览器，在地图上用矩形框选目标区域，点击"开始生成"即可触发完整管线。
不需要截图、不需要复制 URL、不需要手动估算坐标。

用法:
    uv run python Scripts/area_picker.py

浏览器打开后:
    1. 点击左侧工具栏的矩形图标
    2. 在地图上拖拽框选目标区域
    3. 填写区域名称（英文，用于文件命名）
    4. 点击"▶ 开始生成"
    5. 在终端窗口查看管线进度
"""

import sys, json, subprocess, threading, webbrowser, time
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

# Global pipeline state
_state = {'running': False, 'done': False, 'ok': False, 'returncode': None, 'name': '', 'start': 0.0}
_server_ref = [None]  # mutable ref so _run thread can call shutdown()

SCRIPTS = Path(__file__).resolve().parent
ROOT    = SCRIPTS.parent
PORT    = 8765

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
<title>VirtualCity — 区域选择器</title>
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
#bbox-display {
  font-family: monospace; font-size:12px; color:#a5d6a7;
  background:#1a1a2e; padding:5px 10px; border-radius:4px;
  min-width:300px; border:1px solid #2a2a4a;
}
.label { color:#888; font-size:12px; white-space:nowrap; }
#area-name {
  padding:6px 10px; border-radius:4px;
  border:1px solid #444; background:#1e1e38; color:#eee;
  font-size:13px; width:180px;
}
#run-btn {
  padding:8px 22px; background:#4fc3f7; color:#000;
  border:none; border-radius:5px; font-size:14px;
  font-weight:bold; cursor:pointer; white-space:nowrap;
  transition: background 0.15s;
}
#run-btn:disabled { background:#3a3a5a; color:#666; cursor:not-allowed; }
#run-btn:hover:not(:disabled) { background:#81d4fa; }
#map { flex:1; }
#log-panel {
  height:140px; background:#080812; color:#80cbc4;
  font-family: monospace; font-size:12px;
  padding:8px 14px; overflow-y:auto;
  border-top:2px solid #1e1e3a; white-space:pre-wrap;
}
.ok  { color:#a5d6a7; }
.err { color:#ef9a9a; }
.dim { color:#546e7a; }
</style>
</head>
<body>
<div id="toolbar">
  <h2>🗺 VirtualCity 区域选择器</h2>
  <span class="label">① 点击左侧矩形工具 → 拖拽框选区域</span>
  <div id="bbox-display">尚未框选区域</div>
  <span class="label">② 区域名称:</span>
  <input id="area-name" type="text" placeholder="area_name（英文）" value=""/>
  <button id="run-btn" disabled onclick="runPipeline()">▶ 开始生成</button>
</div>
<div id="map"></div>
<div id="log-panel">等待框选区域...</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.js"></script>
<script>
var bbox = null;

var map = L.map('map').setView([__LAT__, __LON__], 14);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap contributors', maxZoom: 19
}).addTo(map);

var drawnItems = new L.FeatureGroup();
map.addLayer(drawnItems);

var drawControl = new L.Control.Draw({
  draw: {
    rectangle: { shapeOptions: { color: '#4fc3f7', weight: 2, fillOpacity: 0.08 } },
    polygon: false, polyline: false, circle: false,
    marker: false, circlemarker: false
  },
  edit: { featureGroup: drawnItems, remove: true }
});
map.addControl(drawControl);

map.on(L.Draw.Event.CREATED, function(e) {
  drawnItems.clearLayers();
  drawnItems.addLayer(e.layer);
  updateBbox(e.layer.getBounds());
});

map.on(L.Draw.Event.EDITED, function(e) {
  e.layers.eachLayer(function(l) { updateBbox(l.getBounds()); });
});

map.on(L.Draw.Event.DELETED, function() {
  bbox = null;
  document.getElementById('bbox-display').textContent = '已清除，请重新框选';
  document.getElementById('run-btn').disabled = true;
});

function updateBbox(b) {
  bbox = {
    west:  +b.getWest().toFixed(6),
    south: +b.getSouth().toFixed(6),
    east:  +b.getEast().toFixed(6),
    north: +b.getNorth().toFixed(6)
  };
  var lat_c = (bbox.south + bbox.north) / 2;
  var wKm = ((bbox.east - bbox.west) * Math.cos(lat_c * Math.PI/180) * 111.32).toFixed(2);
  var hKm = ((bbox.north - bbox.south) * 111.32).toFixed(2);
  document.getElementById('bbox-display').textContent =
    'W:' + bbox.west + '  S:' + bbox.south + '\n' +
    'E:' + bbox.east  + '  N:' + bbox.north + '\n' +
    '尺寸: ' + wKm + ' km × ' + hKm + ' km';

  // Auto-generate name if empty
  var nameEl = document.getElementById('area-name');
  if (!nameEl.value) {
    nameEl.value = 'area_' + lat_c.toFixed(3) + '_' + ((bbox.west+bbox.east)/2).toFixed(3);
  }
  document.getElementById('run-btn').disabled = false;
  log('已框选: [' + bbox.west+', '+bbox.south+', '+bbox.east+', '+bbox.north+']  ' + wKm+'×'+hKm+' km', 'ok');
}

function log(msg, cls) {
  var el = document.getElementById('log-panel');
  var line = document.createElement('span');
  if (cls) line.className = cls;
  line.textContent = msg + '\n';
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

var _pollTimer = null;

function pollStatus() {
  fetch('/status')
  .then(r => r.json())
  .then(d => {
    if (d.done) {
      clearInterval(_pollTimer);
      _pollTimer = null;
      if (d.ok) {
        log('[OK] 生成完成！区域: ' + d.name, 'ok');
        log('3 秒后自动关闭此页面...', 'dim');
        setTimeout(function() { window.close(); }, 3000);
      } else {
        log('[FAIL] 管线出错 (exit=' + d.returncode + ')，请查看终端', 'err');
        document.getElementById('run-btn').disabled = false;
      }
    } else {
      log('运行中... (' + d.elapsed + 's)', 'dim');
    }
  })
  .catch(function() { /* server may be restarting */ });
}

function runPipeline() {
  if (!bbox) return;
  var name = document.getElementById('area-name').value.trim().replace(/\s+/g, '_') || 'area_custom';
  document.getElementById('run-btn').disabled = true;
  document.getElementById('log-panel').innerHTML = '';
  log('[' + new Date().toLocaleTimeString() + '] 提交任务: ' + name, 'ok');
  log('bbox = [' + bbox.west+', '+bbox.south+', '+bbox.east+', '+bbox.north+']', 'dim');

  fetch('/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bbox: bbox, name: name })
  })
  .then(r => r.json())
  .then(d => {
    if (d.ok) {
      log('管线已启动，每 3 秒轮询状态...', 'dim');
      _pollTimer = setInterval(pollStatus, 3000);
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
        if self.path == '/status':
            elapsed = int(time.time() - _state['start']) if _state['running'] or _state['done'] else 0
            self._json({
                'done':       _state['done'],
                'ok':         _state['ok'],
                'returncode': _state['returncode'],
                'name':       _state['name'],
                'elapsed':    elapsed,
            })
            return
        lat, lon = _get_initial_center()
        html = (_HTML
                .replace('__LAT__', str(lat))
                .replace('__LON__', str(lon)))
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def do_POST(self):
        if self.path != '/run':
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get('Content-Length', 0))
        body   = json.loads(self.rfile.read(length))
        bbox   = body.get('bbox', {})
        name   = body.get('name', 'area_custom').strip() or 'area_custom'

        required = ('west', 'south', 'east', 'north')
        if not all(k in bbox for k in required):
            self._json({'ok': False, 'message': 'bbox 参数不完整'})
            return

        cmd = [
            'uv', 'run', 'python', 'set_area.py',
            str(bbox['west']), str(bbox['south']),
            str(bbox['east']), str(bbox['north']),
            name,
        ]
        print(f"\n[area_picker] 启动管线: {' '.join(cmd)}")
        _state.update({'running': True, 'done': False, 'ok': False,
                       'returncode': None, 'name': name, 'start': time.time()})

        def _run():
            result = subprocess.run(cmd, cwd=str(SCRIPTS))
            _state.update({'running': False, 'done': True,
                           'ok': result.returncode == 0,
                           'returncode': result.returncode})
            status = 'OK' if result.returncode == 0 else f'FAIL(exit={result.returncode})'
            print(f'[area_picker] 管线结束: {status}')
            if result.returncode == 0:
                print('[area_picker] 5 秒后自动退出服务器...')
                time.sleep(5)
                _server_ref[0].shutdown()

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
    print(f"\n{'='*52}")
    print(f"  VirtualCity 区域选择器")
    print(f"  当前区域中心: ({lat:.4f}, {lon:.4f})")
    print(f"  浏览器地址:   {url}")
    print(f"{'='*52}")
    print(f"  操作步骤:")
    print(f"    1. 在地图上点击左侧矩形工具")
    print(f"    2. 拖拽框选目标区域")
    print(f"    3. 填写区域名称（英文）")
    print(f"    4. 点击 [开始生成] 按钮")
    print(f"{'='*52}\n")
    print(f"  按 Ctrl+C 退出\n")

    server = HTTPServer(('localhost', PORT), _Handler)
    _server_ref[0] = server
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    print('[area_picker] 已退出')


if __name__ == '__main__':
    main()
