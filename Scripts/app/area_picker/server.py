"""
VirtualCity — 交互式区域选择器
================================
运行后自动打开浏览器，在地图上框选固定 1km UTM 网格块，点击"开始生成"即可触发完整管线。
不需要截图、不需要复制 URL、不需要手动估算坐标；下游仍使用 bbox 入口。

用法:
    uv run python Scripts/area_picker.py

浏览器打开后:
    1. 放大到目标区域
    2. 点击区域选择工具，框选或点选 1 个或多个 1km x 1km 网格
    3. 点击"开始生成"
    4. 在网页或终端窗口查看管线进度
"""

import sys, json, subprocess, threading, webbrowser, time, os, re, socket, mimetypes, urllib.error, urllib.request, urllib.parse, importlib
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
ROOT = SCRIPTS.parent
STATIC_ROOT = SCRIPTS / 'web_assets'

import pipeline_status
import vc_grid
import app.area_picker.template as area_picker_template
from app.area_picker.software_paths import (
    SOFTWARE_PATHS_FILE,
    read_software_paths as _read_software_paths,
    software_path_status as _software_path_status,
    write_software_paths as _write_software_paths,
)

_HTML = area_picker_template.HTML
APP_VERSION = "2026-06-08-panel-selection-tools-v27"
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
_selection_state = {'selection': None, 'updated_at': 0.0}
_selection_lock = threading.Lock()
_server_ref = [None]  # mutable ref so _run thread can call shutdown()
_MAX_LOG_LINES = 80
_page_lock = threading.Lock()
_page_state = {'seen': False, 'last_seen': 0.0, 'close_requested': False, 'closed_at': 0.0,
               'monitor_started': False, 'hold_until': 0.0}


def _safe_print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(str(msg).encode('ascii', errors='backslashreplace').decode('ascii'))

PICKER_HOST = '127.0.0.1'
PORT    = 8765

_STEP_RE = re.compile(r'^\[(\d+)/(\d+)\]')
_RUN_RE = re.compile(r'^\[RUN\] run_id=(\S+)$')
_HOUDINI_RE = re.compile(r'^\[Houdini\s+(\d+)/(\d+)\]\s*(.*)')
_REPORT_PATH_RE = re.compile(r'(Reports[/\\][^)\s]+\.json)', re.IGNORECASE)
_RAW_AREA_PATTERNS = {
    'roads': ('OSM', re.compile(r'(.+)_osm_v001\.osm$')),
    'buildings': ('Overture', re.compile(r'(.+)_buildings_overture_v001\.geojson$')),
    'dem_csv': ('DEM', re.compile(r'(.+)_dem_v001\.csv$')),
    'dem_tif': ('DEM', re.compile(r'(.+)_dem_v001\.tif$')),
}

_PHASE_LABELS = {
    'created': '创建运行记录',
    'download_area_prepared': '准备下载区域',
    'active_area_written': '写入 active_area',
    'acquire_osm': '获取道路数据',
    'acquire_dem': '获取地形数据',
    'acquire_buildings': '获取建筑数据',
    'refine_data': '数据清洗',
    'refine_data_completed': '数据清洗完成',
    'houdini_preflight': 'Houdini 输入预检',
    'houdini_recook': 'Houdini 重算',
    'houdini_completed': 'Houdini 完成',
    'pipeline_completed': '管线完成',
    'aborted': '流程中止',
}

_QA_METRIC_KEYS = (
    'self_intersection_count',
    'self_intersecting_prim_count',
    'too_many_vertices_count',
    'max_vertices',
    'ngon_count',
    'aspect_fail_count',
    'small_angle_fail_count',
    'max_aspect_ratio',
    'min_angle_deg',
    'large_area_warn_count',
    'misses',
    'sampled_points',
    'sliver_edge_count',
)

_QA_METRIC_LABELS = {
    'self_intersection_count': 'self intersections',
    'self_intersecting_prim_count': 'bad prims',
    'too_many_vertices_count': 'over-vertex prims',
    'max_vertices': 'max vertices',
    'ngon_count': 'ngons',
    'aspect_fail_count': 'aspect fails',
    'small_angle_fail_count': 'small-angle fails',
    'max_aspect_ratio': 'max aspect',
    'min_angle_deg': 'min angle',
    'large_area_warn_count': 'large-area warns',
    'misses': 'terrain misses',
    'sampled_points': 'samples',
    'sliver_edge_count': 'sliver edges',
}


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


def _complete_downloaded_area_ids(root: Path | None = None) -> set[str]:
    data_root = (root or ROOT) / 'RawData'
    area_ids: set[str] = set()

    downloads = data_root / '_downloads'
    if downloads.exists():
        for entry in downloads.iterdir():
            if not entry.is_dir():
                continue
            if (
                (entry / 'roads.osm').exists()
                and (entry / 'buildings.geojson').exists()
                and (entry / 'dem.csv').exists()
            ):
                area_ids.add(entry.name)

    raw_sets: dict[str, set[str]] = {}
    for key, (folder, pattern) in _RAW_AREA_PATTERNS.items():
        found: set[str] = set()
        directory = data_root / folder
        if directory.exists():
            for path in directory.iterdir():
                if not path.is_file():
                    continue
                match = pattern.fullmatch(path.name)
                if match:
                    found.add(match.group(1))
        raw_sets[key] = found
    raw_complete = (
        raw_sets.get('roads', set())
        & raw_sets.get('buildings', set())
        & (raw_sets.get('dem_csv', set()) | raw_sets.get('dem_tif', set()))
    )
    area_ids.update(raw_complete)
    return area_ids


def _downloaded_area_status() -> dict:
    area_ids = sorted(_complete_downloaded_area_ids())
    return {
        'count': len(area_ids),
        'area_ids': area_ids,
    }


def _service_payload() -> dict:
    with _state_lock:
        snapshot = dict(_state)
        running = snapshot.get('running', False)
        export_running = snapshot.get('export_running', False)
        done = snapshot.get('done', False)
        run_id = snapshot.get('run_id', '')
        name = snapshot.get('name', '')
        operation = snapshot.get('operation', '')
        ok = snapshot.get('ok', False)
        pct = snapshot.get('pct', 0)
        step_label = snapshot.get('step_label', '')
    houdini_available = _probe_houdini()
    houdini_asset = _houdini_asset_status(houdini_available)
    return {
        'app': 'VirtualCity area_picker',
        'server_version': APP_VERSION,
        'pid': os.getpid(),
        'started_at': STARTED_AT,
        'root': str(ROOT),
        'running': running,
        'export_running': export_running,
        'done': done,
        'ok': ok,
        'name': name,
        'operation': operation,
        'run_id': run_id,
        'pct': pct,
        'step_label': step_label,
        'auto_shutdown_on_success': AUTO_SHUTDOWN_ON_SUCCESS,
        'no_browser': NO_BROWSER,
        'shutdown_with_page': SHUTDOWN_WITH_PAGE,
        'houdini_available': houdini_available,
        'houdini_asset': houdini_asset,
        'software_paths': _software_path_status(),
        'export_available': False if running or export_running else bool(houdini_asset.get('export_ready')),
        'selection': _remembered_selection_status(),
        'downloaded_areas': _downloaded_area_status(),
        'failure_summary': _failure_summary(snapshot),
    }


def _file_status(value: str | Path | None) -> dict:
    if not value:
        return {'path': '', 'exists': False, 'size': 0, 'size_label': '--'}
    try:
        path = _resolve_project_path(value)
        exists = path.exists()
        size = path.stat().st_size if exists else 0
    except Exception:
        return {'path': str(value), 'exists': False, 'size': 0, 'size_label': '--'}
    if size >= 1024 * 1024:
        size_label = f'{size / (1024 * 1024):.1f} MB'
    elif size >= 1024:
        size_label = f'{size / 1024:.0f} KB'
    elif exists:
        size_label = f'{size} B'
    else:
        size_label = '--'
    return {
        'path': str(value),
        'abs_path': str(path),
        'exists': exists,
        'size': size,
        'size_label': size_label,
    }


def _source_mode(cfg: dict, group: str) -> str:
    cache = cfg.get('cache') if isinstance(cfg.get('cache'), dict) else {}
    clip = cache.get('clip') if isinstance(cache.get('clip'), dict) else {}
    clip_status = str(clip.get('status') or '')
    if clip_status:
        key = str(clip.get('key') or '')
        return f'clip cache {clip_status}' + (f' · {key}' if key else '')
    return {
        'roads': '按需从 Overpass / tile cache 获取',
        'buildings': '按需从 Overture / tile cache 获取',
        'terrain': '按需从 DEM 源 / tile cache 获取',
    }.get(group, '按需获取')


def _data_sources_status() -> dict:
    try:
        cfg = _load_active_area()
    except Exception as exc:
        return {'available': False, 'message': f'active_area.json 不可读: {exc}', 'items': []}

    sources = cfg.get('sources') if isinstance(cfg.get('sources'), dict) else {}
    dem_source = str(cfg.get('dem_source') or 'unknown')
    items = [
        {
            'key': 'roads',
            'title': '道路',
            'provider': 'OpenStreetMap',
            'method': 'OSM highway ways · Overpass API',
            'strategy': sources.get('roads') or 'tile_cache_osm_else_overpass_v1',
            'current': _source_mode(cfg, 'roads'),
            'file': _file_status(cfg.get('osm_file')),
        },
        {
            'key': 'buildings',
            'title': '建筑',
            'provider': 'Overture Maps + Google Open Buildings',
            'method': 'Overture 轮廓 · Google 高度补全',
            'strategy': sources.get('buildings') or 'tile_cache_overture_else_overture_api_v1',
            'current': _source_mode(cfg, 'buildings'),
            'file': _file_status(cfg.get('buildings_file')),
        },
        {
            'key': 'terrain',
            'title': '地形',
            'provider': dem_source.upper() if dem_source != 'unknown' else 'DEM',
            'method': 'FABDEM DTM 优先 · NASADEM 兜底',
            'strategy': sources.get('dem') or 'fabdem_else_tile_cache_else_nasadem_v1',
            'current': _source_mode(cfg, 'terrain') + f' · source={dem_source}',
            'file': _file_status(cfg.get('dem_csv')),
        },
    ]
    return {
        'available': True,
        'area_id': str(cfg.get('area_id') or ''),
        'run_id': str(cfg.get('run_id') or ''),
        'items': items,
    }


def _resolve_project_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return ROOT / path


def _load_active_area() -> dict:
    return json.loads((ROOT / 'Config' / 'active_area.json').read_text(encoding='utf-8'))


def _selection_payload_from_tile_ids(tile_ids) -> dict:
    selection = vc_grid.selection_from_tile_ids(tile_ids)
    return {
        'available': True,
        'selection_id': selection.get('selection_id', ''),
        'tile_ids': list(selection.get('tile_ids') or []),
        'bbox': selection.get('bbox') or [],
        'center': selection.get('center') or [],
        'cols': selection.get('cols', 0),
        'rows': selection.get('rows', 0),
        'tile_count': selection.get('tile_count', 0),
    }


def _remember_selection(tile_ids) -> dict:
    payload = _selection_payload_from_tile_ids(tile_ids)
    with _selection_lock:
        _selection_state['selection'] = payload
        _selection_state['updated_at'] = time.time()
    return payload


def _clear_remembered_selection() -> None:
    with _selection_lock:
        _selection_state['selection'] = None
        _selection_state['updated_at'] = 0.0


def _remembered_selection_status() -> dict:
    with _selection_lock:
        payload = dict(_selection_state.get('selection') or {})
        updated_at = float(_selection_state.get('updated_at') or 0.0)
    if not payload:
        return {'available': False}
    payload['available'] = True
    payload['updated_at'] = updated_at
    return payload


def _pipeline_command_for_selection(selection: dict, *, data_only: bool,
                                    submitted_tile_ids: list | None = None) -> list[str]:
    """Build the CLI command for a validated fixed-grid selection."""
    west, south, east, north = selection['bbox']
    name = selection['selection_id']
    if data_only:
        return [
            'uv', 'run', 'python', '-u', 'acquisition/set_area.py', '--data-only',
            str(west), str(south),
            str(east), str(north),
            name,
        ]
    tile_ids = selection.get('tile_ids') or submitted_tile_ids or []
    return [
        'uv', 'run', 'python', '-u', 'orchestration/run_pipeline.py',
        '--tile-ids', ','.join(tile_ids),
        str(west), str(south),
        str(east), str(north),
        name,
    ]


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
        hold_until = float(_page_state.get('hold_until') or 0.0)
        if hold_until > now:
            return False
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


def _schedule_page_close_shutdown() -> None:
    if not SHUTDOWN_WITH_PAGE:
        return

    def _delayed_shutdown() -> None:
        time.sleep(PAGE_CLOSE_GRACE_SECONDS + 0.5)
        server = _server_ref[0]
        if server is not None and _page_shutdown_due():
            _safe_print('[area_picker] 网页已关闭，自动停止本地服务...')
            server.shutdown()

    threading.Thread(target=_delayed_shutdown, daemon=True).start()


def _probe_houdini(timeout: float = 0.35) -> bool:
    """Return whether the local Houdini RPYC port accepts connections."""
    try:
        with socket.create_connection(('127.0.0.1', 18811), timeout=timeout):
            return True
    except OSError:
        return False


def _open_houdini_from_config() -> dict:
    status = _software_path_status()
    houdini_exe = status.get('houdini_exe') or ''
    if _probe_houdini():
        return {'ok': True, 'message': 'Houdini 已连接', 'already_connected': True, 'software_paths': status}
    if not houdini_exe:
        return {'ok': False, 'message': '请先输入 Houdini 软件路径', 'software_paths': status}
    if not status.get('houdini_exe_exists'):
        return {'ok': False, 'message': 'Houdini 软件路径不存在', 'software_paths': status}
    try:
        subprocess.Popen([houdini_exe], cwd=str(Path(houdini_exe).parent), close_fds=True)
    except Exception as exc:
        return {'ok': False, 'message': f'Houdini 启动失败: {exc}', 'software_paths': status}
    return {'ok': True, 'message': 'Houdini 已启动，等待连接', 'started': True, 'software_paths': status}


def _export_available() -> bool:
    """Return whether QA passed and the current Houdini session still has exportable geometry."""
    try:
        cfg = json.loads((ROOT / 'Config' / 'active_area.json').read_text(encoding='utf-8'))
    except Exception:
        return False
    model_ready = _houdini_model_available(cfg)
    gate = pipeline_status.export_gate(ROOT, cfg, live_model_ready=model_ready)
    return bool(gate.get('allowed'))


def _houdini_asset_status(houdini_available: bool | None = None) -> dict:
    """Summarize whether the current Houdini scene has QA-passed exportable geometry."""
    try:
        cfg = _load_active_area()
    except Exception as exc:
        return {
            'qa_ok': False,
            'model_ready': False,
            'export_ready': False,
            'status': '',
            'message': f'active_area.json 不可读: {exc}',
            'area_id': '',
            'run_id': '',
        }
    area_id = str(cfg.get('area_id') or '')
    run_id = str(cfg.get('run_id') or '')
    if houdini_available is None:
        houdini_available = _probe_houdini()
    model_ready = _houdini_model_available(cfg) if houdini_available else False
    gate = pipeline_status.export_gate(ROOT, cfg, live_model_ready=model_ready)
    h_status = gate.get('status', {}).get('houdini', {})
    qa_ok = bool(h_status.get('available') and str(h_status.get('status') or '').lower() == 'completed')
    status = str(h_status.get('status') or '')
    message = str(h_status.get('message') or gate.get('primary_reason') or '')
    return {
        'qa_ok': qa_ok,
        'model_ready': model_ready,
        'export_ready': bool(gate.get('allowed')),
        'status': status,
        'message': message,
        'export_block_reason': str(gate.get('primary_reason') or ''),
        'manual_review_required': bool(gate.get('requires_manual_review')),
        'manual_review_approved': bool(gate.get('manual_review_approved')),
        'area_id': area_id,
        'run_id': run_id,
    }


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
    url = f'http://{PICKER_HOST}:{PORT}'
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


def _read_json_silent(path: Path) -> dict:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _project_path_label(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace('\\', '/')
    except Exception:
        return str(path).replace('\\', '/')


def _metric_value_label(value) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if abs(value) >= 100:
            return f'{value:.1f}'
        if abs(value) >= 10:
            return f'{value:.2f}'
        return f'{value:.3f}'
    return str(value)


def _check_summary(check: dict) -> dict:
    details = check.get('details') if isinstance(check.get('details'), dict) else {}
    metrics = []
    for key in _QA_METRIC_KEYS:
        if key not in details:
            continue
        value = details.get(key)
        if value is None or value == '':
            continue
        metrics.append({
            'key': key,
            'label': _QA_METRIC_LABELS.get(key, key),
            'value': value,
            'value_label': _metric_value_label(value),
        })
    metrics_line = ', '.join(f"{item['label']}={item['value_label']}" for item in metrics[:6])
    return {
        'name': str(check.get('name') or ''),
        'status': str(check.get('status') or ''),
        'message': str(check.get('message') or ''),
        'metrics': metrics[:8],
        'metrics_line': metrics_line,
    }


def _qa_report_summary(report_value: str | Path | None) -> dict:
    if not report_value:
        return {}
    report_path = _resolve_project_path(report_value)
    payload = _read_json_silent(report_path)
    if not payload:
        return {
            'report': str(report_value).replace('\\', '/'),
            'report_abs_path': str(report_path),
            'report_exists': False,
        }

    checks = payload.get('checks') if isinstance(payload.get('checks'), list) else []
    failed = [_check_summary(c) for c in checks if isinstance(c, dict) and str(c.get('status') or '').lower() == 'fail']
    warnings = [_check_summary(c) for c in checks if isinstance(c, dict) and str(c.get('status') or '').lower() == 'warn']
    primary = failed[0] if failed else (warnings[0] if warnings else {})
    return {
        'report': _project_path_label(report_path),
        'report_abs_path': str(report_path),
        'report_exists': True,
        'qa_status': str(payload.get('status') or ''),
        'qa_summary': payload.get('summary') if isinstance(payload.get('summary'), dict) else {},
        'failed_checks': failed[:4],
        'warning_checks': warnings[:4],
        'primary_check': primary,
    }


def _report_path_from_message(message: str) -> str:
    match = _REPORT_PATH_RE.search(message or '')
    return match.group(1).replace('\\', '/') if match else ''


def _pipeline_run_payload(run_id: str) -> dict:
    if not run_id or not re.fullmatch(r'[A-Za-z0-9_.-]+', run_id):
        return {}
    return _read_json_silent(ROOT / 'Reports' / 'pipeline_runs' / f'{run_id}.json')


def _latest_failed_event(run_payload: dict) -> dict:
    events = run_payload.get('events') if isinstance(run_payload.get('events'), list) else []
    for event in reversed(events):
        if isinstance(event, dict) and str(event.get('status') or '').lower() == 'failed':
            return event
    return {}


def _failure_summary(snapshot: dict | None = None) -> dict:
    snapshot = snapshot or {}
    if snapshot.get('running') or snapshot.get('export_running'):
        return {'available': False}
    active_cfg = {}
    try:
        active_cfg = _load_active_area()
    except Exception:
        active_cfg = {}

    expected_area = str(snapshot.get('name') or snapshot.get('area_id') or active_cfg.get('area_id') or '')
    expected_run_id = str(snapshot.get('run_id') or active_cfg.get('run_id') or '')
    status_path = ROOT / 'Config' / 'houdini_build_status.json'
    build_status = _read_json_silent(status_path)

    if build_status:
        status_area = str(build_status.get('area_id') or '')
        status_run = str(build_status.get('run_id') or '')
        if expected_area and status_area and status_area != expected_area:
            build_status = {}
        elif expected_run_id and status_run and status_run != expected_run_id:
            build_status = {}
        else:
            expected_area = expected_area or status_area
            expected_run_id = expected_run_id or status_run

    run_payload = _pipeline_run_payload(expected_run_id)
    failed_event = _latest_failed_event(run_payload)

    snapshot_failed = bool(snapshot.get('done') and not snapshot.get('ok'))
    build_failed = str(build_status.get('status') or '').lower() == 'failed'
    run_failed = str(run_payload.get('status') or '').lower() == 'failed'
    if not (snapshot_failed or build_failed or run_failed):
        return {'available': False}

    phase = str(run_payload.get('phase') or failed_event.get('phase') or '')
    message = str(build_status.get('message') or failed_event.get('message') or snapshot.get('houdini_message') or '')
    report = str(build_status.get('qa_report') or _report_path_from_message(message))
    if not report:
        report = _report_path_from_message(str(failed_event.get('message') or ''))
    qa = _qa_report_summary(report)
    primary = qa.get('primary_check') if isinstance(qa.get('primary_check'), dict) else {}
    check_name = str(primary.get('name') or '')
    check_message = str(primary.get('message') or '')

    if not phase and (build_failed or qa):
        phase = 'houdini_recook'
    phase_label = _PHASE_LABELS.get(phase, phase or '管线执行')
    stage = phase_label
    if report or str(build_status.get('qa_status') or '').lower() == 'fail':
        stage = 'Houdini 7/7 Model QA'
    elif phase == 'houdini_recook':
        stage = 'Houdini 重算'

    reason = f'{check_name}: {check_message}' if check_name and check_message else (check_message or message or f'exit={snapshot.get("returncode")}')
    key = '|'.join([
        expected_run_id,
        phase,
        report,
        check_name,
        str(snapshot.get('returncode') or ''),
    ])
    return {
        'available': True,
        'area_id': expected_area,
        'run_id': expected_run_id,
        'status': 'failed',
        'phase': phase,
        'phase_label': phase_label,
        'stage': stage,
        'reason': reason,
        'message': message,
        'check': check_name,
        'check_message': check_message,
        'metrics': primary.get('metrics') or [],
        'metrics_line': primary.get('metrics_line') or '',
        'warnings': qa.get('warning_checks') or [],
        'failed_checks': qa.get('failed_checks') or [],
        'report': qa.get('report') or report,
        'report_exists': bool(qa.get('report_exists')),
        'run_report': _project_path_label(ROOT / 'Reports' / 'pipeline_runs' / f'{expected_run_id}.json') if expected_run_id else '',
        'key': key,
    }


def _get_initial_center():
    try:
        cfg = json.loads((ROOT / 'Config' / 'active_area.json').read_text(encoding='utf-8'))
        return cfg.get('origin_lat', 12.94), cfg.get('origin_lon', 100.88)
    except Exception:
        return 12.94, 100.88

def _template_html():
    if os.environ.get("VC_AREA_PICKER_TEMPLATE_RELOAD", "1") == "1":
        importlib.reload(area_picker_template)
    return area_picker_template.HTML


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # Suppress default access logs

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/health':
            self._json(_service_payload())
            return
        if parsed.path == '/data-sources':
            self._json(_data_sources_status())
            return
        if parsed.path == '/software-paths':
            self._json(_software_path_status())
            return
        if parsed.path == '/selection':
            self._json(_remembered_selection_status())
            return
        if parsed.path == '/geocode':
            params = urllib.parse.parse_qs(parsed.query)
            query = str(params.get('q', [''])[0]).strip()
            if not query:
                self._json({'ok': False, 'message': 'missing query', 'results': []})
                return
            try:
                url = 'https://nominatim.openstreetmap.org/search?' + urllib.parse.urlencode({
                    'q': query,
                    'format': 'jsonv2',
                    'addressdetails': '1',
                    'limit': '8',
                })
                req = urllib.request.Request(
                    url,
                    headers={
                        'User-Agent': 'VirtualCity/0.1 area-picker geocoder',
                        'Accept': 'application/json',
                    },
                )
                with urllib.request.urlopen(req, timeout=8.0) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                if not isinstance(data, list):
                    data = []
                results = []
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    results.append({
                        'display_name': str(item.get('display_name') or ''),
                        'name': str(item.get('name') or ''),
                        'lat': str(item.get('lat') or ''),
                        'lon': str(item.get('lon') or ''),
                        'boundingbox': item.get('boundingbox') if isinstance(item.get('boundingbox'), list) else [],
                        'class': str(item.get('category') or item.get('class') or ''),
                        'type': str(item.get('type') or ''),
                    })
                self._json({'ok': True, 'results': results})
            except Exception as exc:
                self._json({'ok': False, 'message': f'geocode failed: {exc}', 'results': []})
            return
        if parsed.path in ('/svg_live_viewer.html', '/reports/visualizations/svg_live_viewer.html'):
            self.send_response(302)
            self.send_header('Location', '/')
            self.end_headers()
            return
        if parsed.path == '/status':
            with _state_lock:
                elapsed = int(time.time() - _state['start']) if _state['running'] or _state['done'] else 0
                resp = {
                    'running':    _state['running'],
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
                    'houdini_available': False,
                    'export_available': False,
                    'export_running': _state['export_running'],
                    'export_done': _state['export_done'],
                    'export_ok': _state['export_ok'],
                    'export_returncode': _state['export_returncode'],
                    'export_log_lines': list(_state['export_log_lines']),
                }
                snapshot = dict(resp)
            resp['houdini_available'] = _probe_houdini()
            resp['houdini_asset'] = _houdini_asset_status(resp['houdini_available'])
            resp['software_paths'] = _software_path_status()
            if not resp.get('running') and not resp.get('export_running'):
                resp['export_available'] = bool(resp['houdini_asset'].get('export_ready'))
            resp['selection'] = _remembered_selection_status()
            resp['downloaded_areas'] = _downloaded_area_status()
            resp['failure_summary'] = _failure_summary(snapshot)
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
        html = (_template_html()
                .replace('__LAT__', str(lat))
                .replace('__LON__', str(lon))
                .replace('__VERSION__', APP_VERSION)
                .replace('__MAX_SELECTION_TILES__', str(vc_grid.MAX_SELECTION_TILES))
                .replace('__SHUTDOWN_WITH_PAGE__', 'true' if SHUTDOWN_WITH_PAGE else 'false'))
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
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
            _schedule_page_close_shutdown()
            self._json({'ok': True})
            return
        if parsed.path == '/selection':
            self._post_selection()
            return
        if parsed.path == '/selection/clear':
            _clear_remembered_selection()
            self._json({'ok': True})
            return
        if parsed.path == '/software-paths':
            self._post_software_paths()
            return
        if parsed.path == '/open-houdini':
            self._post_open_houdini()
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
        _remember_selection(tile_ids)
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
            operation = 'download' if data_only else 'generate'
            _state.update({'running': True, 'done': False, 'ok': False,
                           'returncode': None, 'name': name, 'start': time.time(),
                           'operation': operation,
                           'run_id': '',
                           'step': 0, 'total_steps': 6, 'step_label': '启动中...', 'pct': 0,
                           'log_lines': [],
                           'houdini_done': False, 'houdini_status': '', 'houdini_message': '',
                           'export_done': False, 'export_ok': False, 'export_returncode': None,
                           'export_log_lines': []})

        cmd = _pipeline_command_for_selection(
            selection,
            data_only=data_only,
            submitted_tile_ids=tile_ids,
        )
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
                    _state['log_lines'].append(f'[WARN] Houdini 状态文件未确认，但 run_pipeline.py 已成功退出: {houdini_message}')
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
        if data_only:
            message = f'数据下载已启动: {name}'
        else:
            message = f'Houdini 生成已启动: {name}'
        self._json({'ok': True, 'message': message})

    def _post_selection(self):
        length = int(self.headers.get('Content-Length', 0))
        try:
            body = json.loads(self.rfile.read(length) or b'{}')
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
            payload = _remember_selection(tile_ids)
        except ValueError as exc:
            self._json({'ok': False, 'message': f'网格框选无效: {exc}'})
            return
        self._json({'ok': True, 'selection': payload})

    def _post_software_paths(self):
        length = int(self.headers.get('Content-Length', 0))
        try:
            body = json.loads(self.rfile.read(length) or b'{}')
        except json.JSONDecodeError:
            self._json({'ok': False, 'message': '请求 JSON 无法解析'})
            return
        houdini_exe = str(body.get('houdini_exe') or '').strip().strip('"')
        data = _read_software_paths()
        data['houdini_exe'] = houdini_exe
        try:
            _write_software_paths(data)
        except Exception as exc:
            self._json({'ok': False, 'message': f'软件路径保存失败: {exc}'})
            return
        status = _software_path_status()
        message = '软件路径已保存'
        if houdini_exe and not status.get('houdini_exe_exists'):
            message = '软件路径已保存，但文件不存在'
        self._json({'ok': True, 'message': message, 'software_paths': status})
    def _post_open_houdini(self):
        if not _probe_houdini():
            length = int(self.headers.get('Content-Length', 0))
            try:
                body = json.loads(self.rfile.read(length) or b'{}')
            except json.JSONDecodeError:
                self._json({'ok': False, 'message': '请求 JSON 无法解析'})
                return
            houdini_exe = str(body.get('houdini_exe') or '').strip().strip('"')
            if houdini_exe:
                data = _read_software_paths()
                data['houdini_exe'] = houdini_exe
                try:
                    _write_software_paths(data)
                except Exception as exc:
                    self._json({'ok': False, 'message': f'软件路径保存失败: {exc}'})
                    return
        self._json(_open_houdini_from_config())
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
    url = f'http://{PICKER_HOST}:{PORT}'
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
    print(f"    2. 点击区域选择工具，框选或点选 1 个或多个 1km x 1km 网格")
    print(f"    3. 点击 [开始生成] 按钮")
    if SHUTDOWN_WITH_PAGE:
        print(f"    4. 关闭网页后，本地服务会自动退出")
    print(f"{'='*52}\n")
    print(f"  按 Ctrl+C 退出\n")

    try:
        server = ThreadingHTTPServer((PICKER_HOST, PORT), _Handler)
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
