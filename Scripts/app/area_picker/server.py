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
BOUNDARY_CACHE_DIR = SCRIPTS / 'app' / 'area_picker' / '.cache' / 'boundary'
BOUNDARY_PREBUILT_DIR = SCRIPTS / 'app' / 'area_picker' / 'frontend' / 'boundaries'

import pipeline_status
import vc_grid
import area_manifest
import area_aggregate
from acquisition import sources as acquisition_sources
import app.area_picker.template as area_picker_template
from app.area_picker.software_paths import (
    SOFTWARE_PATHS_FILE,
    read_software_paths as _read_software_paths,
    software_path_status as _software_path_status,
    write_software_paths as _write_software_paths,
)

_HTML = area_picker_template.HTML
FRONTEND_ROOT = area_picker_template.FRONTEND_ROOT
APP_VERSION = "10-06-26_v2.23"
STARTED_AT = time.strftime("%Y-%m-%d %H:%M:%S")
AUTO_SHUTDOWN_ON_SUCCESS = os.environ.get("VC_AREA_PICKER_AUTO_SHUTDOWN") == "1"


def _fetch_boundary(osm_type: str, osm_id: str) -> dict:
    key = f'{osm_type}{osm_id}'
    prebuilt_file = BOUNDARY_PREBUILT_DIR / f'{key}.json'
    if prebuilt_file.exists():
        try:
            prebuilt = json.loads(prebuilt_file.read_text(encoding='utf-8'))
            if isinstance(prebuilt, dict) and prebuilt.get('ok'):
                return prebuilt
        except Exception:
            pass
    cache_file = BOUNDARY_CACHE_DIR / f'{key}.json'
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding='utf-8'))
            if isinstance(cached, dict) and cached.get('ok'):
                return cached
        except Exception:
            pass
    url = 'https://nominatim.openstreetmap.org/lookup?' + urllib.parse.urlencode({
        'osm_ids': key,
        'format': 'jsonv2',
        'polygon_geojson': '1',
    })
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'VirtualCity/0.1 area-picker geocoder',
            'Accept': 'application/json',
        },
    )
    last_exc = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            item = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else None
            geojson = item.get('geojson') if item else None
            if not isinstance(geojson, dict) or geojson.get('type') not in ('Polygon', 'MultiPolygon'):
                return {'ok': False, 'message': 'no polygon boundary', 'geojson': None}
            result = {
                'ok': True,
                'geojson': geojson,
                'boundingbox': item.get('boundingbox') if isinstance(item.get('boundingbox'), list) else [],
            }
            try:
                BOUNDARY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(result), encoding='utf-8')
            except Exception:
                pass
            return result
        except Exception as exc:
            last_exc = exc
            time.sleep(0.6)
    return {'ok': False, 'message': f'boundary failed: {last_exc}', 'geojson': None}
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
          'log_offset': 0, 'export_log_offset': 0,
          'export_running': False, 'export_done': False, 'export_ok': False,
          'export_returncode': None, 'export_log_lines': []}
_state_lock = threading.Lock()
_selection_state = {'selection': None, 'updated_at': 0.0}
_selection_lock = threading.Lock()
_server_ref = [None]  # mutable ref so _run thread can call shutdown()
_MAX_LOG_LINES = 80


def _append_log(key, offset_key, line):
    """Append a line to a rolling log window and keep a monotonic global offset.

    log_offset 记录当前窗口首行在全局序列中的下标（即已被裁掉的行数）。
    前端据此用全局序号消费，避免窗口滚动后 len() 不再增长导致的增量失效。
    必须在持有 _state_lock 时调用。
    """
    lines = _state[key]
    lines.append(line)
    overflow = len(lines) - _MAX_LOG_LINES
    if overflow > 0:
        del lines[:overflow]
        _state[offset_key] += overflow


def _reset_log(key, offset_key, seed=None):
    """Reset a log window and its global offset. Hold _state_lock when calling."""
    _state[key] = list(seed) if seed else []
    _state[offset_key] = 0
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

_RUN_RE = re.compile(r'^\[RUN\] run_id=(\S+)$')
_REPORT_PATH_RE = re.compile(r'(Reports[/\\][^)\s]+\.json)', re.IGNORECASE)
_RAW_AREA_PATTERNS = {
    'roads': ('OSM', re.compile(r'(.+)_osm_v001\.osm$')),
    'buildings': ('Overture', re.compile(r'(.+)_buildings_overture_v001\.geojson$')),
    'dem_csv': ('DEM', re.compile(r'(.+)_dem_v001\.csv$')),
    'dem_tif': ('DEM', re.compile(r'(.+)_dem_v001\.tif$')),
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


def _quick_jump_label(area_id: str) -> str:
    parts = [part for part in re.split(r'[_\-\s]+', str(area_id or '').strip()) if part]
    if not parts:
        return '已下载区域'
    return ' '.join(part.upper() if part.isupper() else part.capitalize() for part in parts)


def _valid_bbox(value) -> list[float]:
    if not isinstance(value, list) or len(value) != 4:
        return []
    try:
        bbox = [float(v) for v in value]
    except (TypeError, ValueError):
        return []
    if not (bbox[0] < bbox[2] and bbox[1] < bbox[3]):
        return []
    return bbox


PRESET_CITY_JUMPS = [
    {'id': 'tokyo', 'label': 'Tokyo', 'bbox': [139.60, 35.55, 139.92, 35.82]},
    {'id': 'new_york', 'label': 'New York', 'bbox': [-74.05, 40.68, -73.90, 40.82]},
    {'id': 'london', 'label': 'London', 'bbox': [-0.25, 51.43, 0.02, 51.57]},
    {'id': 'paris', 'label': 'Paris', 'bbox': [2.25, 48.81, 2.42, 48.90]},
    {'id': 'shanghai', 'label': 'Shanghai', 'bbox': [121.40, 31.15, 121.58, 31.30]},
    {'id': 'singapore', 'label': 'Singapore', 'bbox': [103.78, 1.26, 103.90, 1.36]},
    {'id': 'bangkok', 'label': 'Bangkok', 'bbox': [100.46, 13.68, 100.62, 13.80]},
    {'id': 'sydney', 'label': 'Sydney', 'bbox': [151.16, -33.90, 151.28, -33.83]},
    {'id': 'los_angeles', 'label': 'Los Angeles', 'bbox': [-118.30, 34.00, -118.18, 34.10]},
]


def _bbox_center(bbox: list[float]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _center_in_bbox(center: tuple[float, float], bbox: list[float]) -> bool:
    lon, lat = center
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


def _preset_city_jumps(downloaded: list[dict]) -> list[dict]:
    """预置世界主要城市书签。已下载区域中心落在城市 bbox 内的，复用其真实 tile 数。"""
    jumps: list[dict] = []
    for city in PRESET_CITY_JUMPS:
        tile_count = 0
        for area in downloaded:
            area_bbox = area.get('bbox')
            if isinstance(area_bbox, list) and len(area_bbox) == 4 and \
                    _center_in_bbox(_bbox_center(area_bbox), city['bbox']):
                tile_count += int(area.get('tile_count') or 0)
        jumps.append({
            'id': city['id'],
            'label': city['label'],
            'tile_count': tile_count,
            'bbox': list(city['bbox']),
            'jumpable': True,
            'source': 'preset_city',
        })
    return jumps


def _quick_jumps(root: Path | None = None) -> list[dict]:
    """孤儿（已下载但不属于任何预置城市）排在最前，其后是 9 个预置城市书签。"""
    downloaded = _macro_tile_quick_jumps(root)
    preset = _preset_city_jumps(downloaded)
    preset_boxes = [city['bbox'] for city in PRESET_CITY_JUMPS]
    orphans = [
        area for area in downloaded
        if not any(
            isinstance(area.get('bbox'), list) and len(area['bbox']) == 4 and
            _center_in_bbox(_bbox_center(area['bbox']), box)
            for box in preset_boxes
        )
    ]
    return orphans + preset


def _downloaded_tile_sources(root: Path | None = None) -> list[dict]:
    """收集所有已下载来源的格子集合（带命名标志），供几何聚合使用。

    两类来源：_index.json 的宏块预缓存（有名），以及真实下载清单 _areas/*.json
    （匿名 selection）。同名区域优先用清单的真实 tile_ids，缺失才用 bbox 反推。
    """
    base = root or ROOT
    manifests = area_manifest.load_all(base)
    sources: list[dict] = []
    seen: set[str] = set()

    index_path = base / 'RawData' / '_tiles' / '_index.json'
    index: dict = {}
    if index_path.exists():
        try:
            loaded = json.loads(index_path.read_text(encoding='utf-8'))
            if isinstance(loaded, dict):
                index = loaded
        except Exception:
            index = {}

    for area_id, entry in sorted(index.items()):
        if not isinstance(entry, dict):
            continue
        bbox = _valid_bbox(entry.get('bbox'))
        if not bbox:
            continue
        required = ('dem_tif', 'osm_xml', 'bld_geojson')
        if not all(entry.get(key) and _resolve_project_path(entry.get(key), root=base).exists() for key in required):
            continue
        manifest = manifests.get(str(area_id))
        if manifest and manifest.get('tile_ids'):
            tile_ids = list(manifest['tile_ids'])
        else:
            grid = vc_grid.tiles_for_bbox(bbox, max_tiles=10000)
            tile_ids = [t['tile_id'] for t in (grid.get('tiles') or [])]
        if not tile_ids:
            continue
        seen.add(str(area_id))
        sources.append({
            'id': str(area_id),
            'label': _quick_jump_label(str(area_id)),
            'named': True,
            'tile_ids': tile_ids,
        })

    for area_id, manifest in sorted(manifests.items()):
        if str(area_id) in seen:
            continue
        tile_ids = list(manifest.get('tile_ids') or [])
        if not tile_ids:
            continue
        sources.append({
            'id': str(area_id),
            'label': manifest.get('label') or _quick_jump_label(str(area_id)),
            'named': bool(manifest.get('label')),
            'tile_ids': tile_ids,
        })
    return sources


def _macro_tile_quick_jumps(root: Path | None = None) -> list[dict]:
    """已下载格子按网格 4-邻接聚合成片，每片统一计数/命名/包络。"""
    sources = _downloaded_tile_sources(root)
    areas = area_aggregate.aggregate(sources)
    jumps: list[dict] = []
    for area in areas:
        jumps.append({
            'id': area['id'],
            'label': area['label'],
            'tile_count': area['tile_count'],
            'bbox': area['bbox'],
            'jumpable': True,
            'source': 'downloaded_area',
        })
    return jumps


def _downloaded_area_status(root: Path | None = None) -> dict:
    area_ids = sorted(_complete_downloaded_area_ids(root))
    return {
        'count': len(area_ids),
        'area_ids': area_ids,
        'quick_jumps': _quick_jumps(root),
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

    # 静态字段（provider/method/strategy_label/默认 profile/title）来自单一真相源
    # acquisition.sources 注册表，避免与缓存指纹、set_area 回退逻辑三处漂移。
    # 运行时字段（实际命中策略、current 状态、file 状态、dem_source 覆盖）在此叠加。
    specs = acquisition_sources.SOURCES

    # 注册表用 'dem'，但前端契约与 _source_mode 第三组用 'terrain'：仅运行时侧用 terrain，
    # cfg['sources'] 的回退 key 仍读注册表 key（dem）。
    runtime = {
        'roads': {
            'group': 'roads',
            'cfg_key': 'roads',
            'file': _file_status(cfg.get('osm_file')),
        },
        'buildings': {
            'group': 'buildings',
            'cfg_key': 'buildings',
            'file': _file_status(cfg.get('buildings_file')),
        },
        'dem': {
            'group': 'terrain',
            'cfg_key': 'dem',
            'file': _file_status(cfg.get('dem_csv')),
            'provider_override': dem_source.upper() if dem_source != 'unknown' else 'DEM',
            'current_suffix': f' · source={dem_source}',
        },
    }

    items = []
    for reg_key, spec in specs.items():
        rt = runtime.get(reg_key, {'group': reg_key, 'cfg_key': reg_key, 'file': None})
        group = rt['group']
        current = _source_mode(cfg, group) + rt.get('current_suffix', '')
        items.append({
            'key': group,
            'title': spec.title,
            'provider': rt.get('provider_override', spec.provider),
            'method': spec.method,
            'strategy': sources.get(rt['cfg_key']) or spec.profile,
            'strategy_label': spec.strategy_label,
            'current': current,
            'file': rt['file'],
        })
    return {
        'available': True,
        'area_id': str(cfg.get('area_id') or ''),
        'run_id': str(cfg.get('run_id') or ''),
        'items': items,
    }


def _resolve_project_path(value: str | Path, *, root: Path | None = None) -> Path:
    base = root or ROOT
    raw = str(value).replace('\\', '/')
    lowered = raw.lower()
    marker = '/virtualcity/'
    idx = lowered.find(marker)
    if idx >= 0:
        return base / raw[idx + len(marker):]
    if lowered.endswith('/virtualcity'):
        return base
    path = Path(raw)
    if path.is_absolute():
        return path
    return base / path


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


def _read_run_terminal(expected_run_id: str = ''):
    """从真相源 pipeline_runs/{run_id}.json 读本次 run 的终态。

    run_pipeline.py 在三模块边界把 status 写成 completed/failed，这里只采信
    身份匹配（run_id 相同）的记录，避免读到上一轮 run 的残留终态。
    返回 (done, ok, status, message)：done 表示已到终态，ok 表示成功完成。
    """
    if not expected_run_id:
        return False, False, '', 'run_id unknown'
    try:
        payload = pipeline_status.load_run(ROOT, expected_run_id)
    except Exception:
        payload = {}
    if not payload or str(payload.get('run_id') or '') != expected_run_id:
        return False, False, '', 'run record missing'
    status = str(payload.get('status') or '').lower()
    last = payload.get('events') or []
    message = str(last[-1].get('message') if last else payload.get('phase') or '')
    if status == 'completed':
        return True, True, 'completed', message
    if status == 'failed':
        return True, False, 'failed', message
    return False, False, status, message


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
    # report 优先采信真相源 run.qa（阶段1已把 QA 结论并入 run 文件），
    # 再回退 houdini_build_status.json 的 qa_report，最后从日志消息里捞路径。
    run_qa = run_payload.get('qa') if isinstance(run_payload.get('qa'), dict) else {}
    report = str(run_qa.get('report') or build_status.get('qa_report') or _report_path_from_message(message))
    if not report:
        report = _report_path_from_message(str(failed_event.get('message') or ''))
    qa = _qa_report_summary(report)
    primary = qa.get('primary_check') if isinstance(qa.get('primary_check'), dict) else {}
    check_name = str(primary.get('name') or '')
    check_message = str(primary.get('message') or '')

    if not phase and (build_failed or qa):
        phase = 'houdini_recook'
    phase_label = pipeline_status.PHASE_LABELS.get(phase, phase or '管线执行')
    stage = phase_label
    run_qa_status = str(run_qa.get('status') or '').lower()
    if report or run_qa_status == 'fail' or str(build_status.get('qa_status') or '').lower() == 'fail':
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


def _frontend_asset_version() -> str:
    """前端静态资源的内容指纹，用于 ?v= 缓存击穿。

    APP_VERSION 是手写的 server 代码版本（也用于进程版本比对），不随前端文件变化，
    所以不能拿它做缓存击穿——改了 app.js/styles.css 而忘记 +1 时，URL 不变、浏览器
    吃旧缓存，热更新失效。这里改用前端文件的 mtime+size 派生指纹：文件一改版本串自动
    变，URL 随之变，浏览器强制重取，无需任何手动维护。"""
    parts: list[str] = []
    for name in ("app.js", "styles.css", "index.html"):
        try:
            st = (FRONTEND_ROOT / name).stat()
            parts.append(f"{int(st.st_mtime)}-{st.st_size}")
        except OSError:
            parts.append("0")
    return "-".join(parts)


def _build_status_payload() -> dict:
    """构建 /status 与 /events 共用的状态投影。

    进度与终态只认真相源 pipeline_runs（内存 _state 仅作缓存）；server 重启丢失
    内存态后，靠 active_area.json 的 run_id 从磁盘恢复进度与 done/ok。两个端点
    共用同一份构建逻辑，避免轮询与 SSE 两套投影漂移。
    """
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
            'phase':      '',
            'phase_label': '',
            'pct':        _state['pct'],
            'log_lines':  list(_state['log_lines']),
            'log_offset': _state['log_offset'],
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
            'export_log_offset': _state['export_log_offset'],
        }
        snapshot = dict(resp)
    resp['houdini_available'] = _probe_houdini()
    run_id = snapshot.get('run_id') or ''
    if not run_id:
        try:
            run_id = str(pipeline_status.load_active(ROOT).get('run_id') or '')
            if run_id:
                resp['run_id'] = run_id
        except Exception:
            run_id = ''
    if run_id:
        try:
            run_payload = pipeline_status.load_run(ROOT, run_id)
            if run_payload:
                pv = pipeline_status.progress_view(run_payload)
                resp['step'] = pv['step']
                resp['total_steps'] = pv['total'] or resp['total_steps']
                resp['step_label'] = pv['label']
                resp['phase'] = pv['phase']
                resp['phase_label'] = pv['phase_label']
                resp['pct'] = pv['pct']
                if not resp.get('running') and not resp.get('done'):
                    run_status = str(run_payload.get('status') or '').lower()
                    if run_status in ('completed', 'failed'):
                        resp['done'] = True
                        resp['ok'] = run_status == 'completed'
        except Exception:
            pass
    resp['houdini_asset'] = _houdini_asset_status(resp['houdini_available'])
    resp['software_paths'] = _software_path_status()
    if not resp.get('running') and not resp.get('export_running'):
        resp['export_available'] = bool(resp['houdini_asset'].get('export_ready'))
    resp['selection'] = _remembered_selection_status()
    resp['downloaded_areas'] = _downloaded_area_status()
    resp['failure_summary'] = _failure_summary(snapshot)
    return resp


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
        if parsed.path == '/boundary':
            params = urllib.parse.parse_qs(parsed.query)
            osm_type = str(params.get('osm_type', ['R'])[0]).strip().upper() or 'R'
            osm_id = str(params.get('osm_id', [''])[0]).strip()
            if osm_type not in ('R', 'W', 'N') or not osm_id.isdigit():
                self._json({'ok': False, 'message': 'invalid osm_type/osm_id', 'geojson': None})
                return
            self._json(_fetch_boundary(osm_type, osm_id))
            return
        if parsed.path in ('/svg_live_viewer.html', '/reports/visualizations/svg_live_viewer.html'):
            self.send_response(302)
            self.send_header('Location', '/')
            self.end_headers()
            return
        if parsed.path == '/status':
            self._json(_build_status_payload())
            return
        if parsed.path == '/events':
            self._sse_events()
            return
        if parsed.path.startswith('/static/'):
            self._static(parsed.path)
            return
        if parsed.path.startswith('/area-picker/'):
            self._frontend_static(parsed.path)
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
                .replace('__VERSION__', _frontend_asset_version())
                .replace('__APP_VERSION__', APP_VERSION)
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
        if parsed.path not in ('/run', '/download-data', '/jobs'):
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get('Content-Length', 0))
        try:
            body = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._json({'ok': False, 'message': '请求 JSON 无法解析'})
            return

        # 统一作业入口 /jobs 用 body.mode 区分生成/下载；旧的 /run、/download-data
        # 仍按 path 决定，作为兼容入口保留。
        if parsed.path == '/jobs':
            mode = str(body.get('mode') or 'generate').lower()
            data_only = mode == 'download'
        else:
            data_only = parsed.path == '/download-data'

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
                           'log_offset': 0, 'export_log_offset': 0,
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
                if data_only:
                    env['VC_PIPELINE_TILE_IDS'] = ','.join(tile_ids or [])
                proc = subprocess.Popen(
                    cmd, cwd=str(SCRIPTS),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', errors='replace',
                    bufsize=1,
                    env=env,
                )

                def _drain_stdout():
                    for raw_line in proc.stdout:
                        line = raw_line.rstrip('\n\r')
                        if not line:
                            continue
                        _safe_print(line)  # echo to terminal
                        with _state_lock:
                            _append_log('log_lines', 'log_offset', line)
                            run_match = _RUN_RE.match(line)
                            if run_match:
                                _state['run_id'] = run_match.group(1)

                # Read stdout on a side thread purely for echo + rolling log;
                # completion is decided by the durable run file, not by the pipe
                # reaching EOF or by parsing log lines.
                reader = threading.Thread(target=_drain_stdout, daemon=True)
                reader.start()

                proc.wait()
                returncode = proc.returncode
                reader.join(timeout=2.0)
                if data_only:
                    houdini_done, houdini_status, houdini_message = False, 'skipped', 'data download only'
                    ok = returncode == 0
                else:
                    with _state_lock:
                        run_id = _state.get('run_id', '')
                    done, run_ok, run_status, run_message = _read_run_terminal(run_id)
                    houdini_done = run_ok
                    houdini_status = run_status or ('completed' if run_ok else 'unknown')
                    houdini_message = run_message
                    ok = returncode == 0 and run_ok
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
                    _append_log('log_lines', 'log_offset', f'[WARN] 真相源未确认完成，但 run_pipeline.py 已成功退出: {houdini_message}')
                _state.update({'running': False, 'done': True,
                               'ok': ok,
                               'returncode': returncode,
                               'pct': 100 if ok else _state['pct'],
                               'step_label': '[OK] 完成' if ok else '[FAIL] 失败',
                               'houdini_done': houdini_done,
                               'houdini_status': houdini_status,
                               'houdini_message': houdini_message})
            status = 'OK' if ok else f'FAIL(exit={returncode}, run={houdini_status})'
            _safe_print(f'[area_picker] 管线结束: {status}')
            if data_only:
                _safe_print('[area_picker] 数据下载完成，Houdini 重算已跳过')
            elif houdini_done:
                _safe_print('[area_picker] 真相源已确认管线完成')
            else:
                _safe_print(f'[area_picker] 管线完成未确认: {houdini_message}')
            if ok:
                if AUTO_SHUTDOWN_ON_SUCCESS:
                    _safe_print('[area_picker] 5 秒后自动退出服务器...')
                    time.sleep(5)
                    _server_ref[0].shutdown()
                else:
                    _safe_print('[area_picker] 状态服务保持运行，按 Ctrl+C 退出')

        def _status_watchdog():
            # Fallback completion path. The _run thread surfaces done only after
            # its stdout reader and proc.wait() return; if that thread ever
            # wedges, the durable run file still flips to completed/failed.
            # Watch THIS run_id in the single source of truth and surface done so
            # the UI can leave the progress screen regardless of the reader's fate.
            if data_only:
                return
            while True:
                time.sleep(2.0)
                with _state_lock:
                    if _state.get('done') or not _state.get('running'):
                        return
                    run_id = _state.get('run_id', '')
                # Require a known run_id so we never read a previous run's
                # leftover completed/failed record.
                if not run_id:
                    continue
                done, run_ok, run_status, run_message = _read_run_terminal(run_id)
                if not done:
                    continue
                with _state_lock:
                    if _state.get('done') or not _state.get('running'):
                        return
                    _state.update({'running': False, 'done': True,
                                   'ok': run_ok,
                                   'pct': 100 if run_ok else _state['pct'],
                                   'step_label': '[OK] 完成' if run_ok else '[FAIL] 失败',
                                   'houdini_done': run_ok,
                                   'houdini_status': run_status,
                                   'houdini_message': run_message})
                _safe_print(f'[area_picker] 真相源哨兵确认管线结束: {run_status}')
                return

        threading.Thread(target=_run, daemon=True).start()
        threading.Thread(target=_status_watchdog, daemon=True).start()
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
                'export_log_offset': 0,
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
                        _append_log('export_log_lines', 'export_log_offset', line)
                proc.wait()
                returncode = proc.returncode
                ok = returncode == 0
            except Exception as exc:
                returncode = proc.returncode if proc is not None else -1
                ok = False
                with _state_lock:
                    _append_log('export_log_lines', 'export_log_offset', f'[FAIL] 导出线程异常: {exc}')

            with _state_lock:
                _state.update({
                    'export_running': False,
                    'export_done': True,
                    'export_ok': ok,
                    'export_returncode': returncode,
                })
                _append_log('export_log_lines', 'export_log_offset', '[OK] FBX 导出完成' if ok else f'[FAIL] FBX 导出失败 exit={returncode}')
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
        ctype = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        self._serve_file_with_range(target, ctype, cache_control='public, max-age=86400')

    def _serve_file_with_range(self, target: Path, ctype: str, *, cache_control: str):
        # pmtiles 等大文件依赖 HTTP Range 只取所需字节区间，避免整文件下载/全量入内存。
        file_size = target.stat().st_size
        range_header = self.headers.get('Range')
        byte_range = self._parse_range_header(range_header, file_size)

        if byte_range is None:
            if range_header:
                # 语法可解析但区间非法（越界等）-> 416 并回报当前总长。
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{file_size}')
                self.send_header('Accept-Ranges', 'bytes')
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(file_size))
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Cache-Control', cache_control)
            self.end_headers()
            self._stream_file_range(target, 0, file_size)
            return

        start, end = byte_range
        length = end - start + 1
        self.send_response(206)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(length))
        self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', cache_control)
        self.end_headers()
        self._stream_file_range(target, start, length)

    @staticmethod
    def _parse_range_header(range_header: str | None, file_size: int):
        # 仅支持单区间 'bytes=start-end' / 'bytes=start-' / 'bytes=-suffix'。
        # 返回闭区间 (start, end)，非法或越界返回 None。
        if not range_header or file_size <= 0:
            return None
        if not range_header.startswith('bytes='):
            return None
        spec = range_header[len('bytes='):].strip()
        if ',' in spec:
            spec = spec.split(',', 1)[0].strip()
        if '-' not in spec:
            return None
        start_str, end_str = spec.split('-', 1)
        start_str, end_str = start_str.strip(), end_str.strip()
        try:
            if start_str == '':
                if end_str == '':
                    return None
                suffix = int(end_str)
                if suffix <= 0:
                    return None
                start = max(0, file_size - suffix)
                end = file_size - 1
            else:
                start = int(start_str)
                end = int(end_str) if end_str else file_size - 1
        except ValueError:
            return None
        if start < 0 or start >= file_size or end < start:
            return None
        end = min(end, file_size - 1)
        return start, end

    def _stream_file_range(self, target: Path, start: int, length: int):
        if self.command == 'HEAD':
            return
        chunk_size = 64 * 1024
        remaining = length
        try:
            with target.open('rb') as fh:
                fh.seek(start)
                while remaining > 0:
                    chunk = fh.read(min(chunk_size, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _frontend_static(self, request_path: str):
        rel = urllib.parse.unquote(request_path[len('/area-picker/'):]).replace('\\', '/').lstrip('/')
        target = (FRONTEND_ROOT / rel).resolve()
        try:
            target.relative_to(FRONTEND_ROOT.resolve())
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
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _sse_events(self):
        """Server-Sent Events 流：周期推送与 /status 同构的状态投影。

        真相源归一后，状态已是磁盘上的事实，这里只是把同一份 _build_status_payload
        定时推给前端。客户端断开（写异常）即结束循环；轮询端点 /status 仍保留作为
        不支持 EventSource 时的降级路径。
        """
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache, no-store')
            self.send_header('Connection', 'keep-alive')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()
        except Exception:
            return
        idle_after_done = 0
        while True:
            try:
                payload = _build_status_payload()
                frame = 'data: ' + json.dumps(payload, ensure_ascii=False) + '\n\n'
                self.wfile.write(frame.encode('utf-8'))
                self.wfile.flush()
            except Exception:
                return  # client disconnected or write failed
            # 终态后再多推几帧确保前端收到收尾，然后结束这条长连接。
            if payload.get('done') and not payload.get('running') and not payload.get('export_running'):
                idle_after_done += 1
                if idle_after_done >= 3:
                    return
            else:
                idle_after_done = 0
            time.sleep(1.0)


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
