"""
Houdini 换区重算脚本
====================
由 orchestration/run_pipeline.py 在数据清洗发布 Houdini-ready 后执行：
  1. 修复 dem_import / dem_terrain Python SOP（防止硬编码/sqrt 格网 bug）
  2. 强制 recook 数据源
  3. 验证全链路节点（几何非空 + 高度范围合理）
  4. 重建裁剪节点（基于新 DEM 边界）
  5. 重连 merge_all + 保存 hip
"""
import sys, rpyc, subprocess, json, time, atexit
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import houdini_road_pipeline as road_pipe
import houdini_sops
import data_cleaning_cache as dcc
import pipeline_state
from vc_paths import ROOT, ACTIVE_AREA, HIP as MASTER_HIP, HOUDINI, load_active_area, project_relative

PASS = '[OK]'
FAIL = '[FAIL]'
errors = []


def _write_build_status(area_id, status, hip_path=None, message='', qa_status='', qa_report='',
                        run_id=''):
    status_file = ROOT / 'Config' / 'houdini_build_status.json'
    payload = {
        'area_id': area_id,
        'run_id': run_id,
        'status': status,
        'hip_path': project_relative(hip_path) if hip_path else '',
        'message': message,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    if qa_status:
        payload['qa_status'] = qa_status
    if qa_report:
        payload['qa_report'] = qa_report
    status_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = status_file.with_name('.{}.{}.tmp'.format(status_file.name, time.time_ns()))
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write('\n')
    tmp.replace(status_file)

_cfg = load_active_area()
_area_id = _cfg.get('area_id', '')
_run_id = _cfg.get('run_id', '')
_roads_cut_fill_enabled = bool(_cfg.get('roads_cut_fill_enabled', False))
_dev_quick_roads = bool(_cfg.get('dev_quick_roads', False))
_roads_topology_preferred = str(_cfg.get('roads_topology_preferred', 'strips')).lower().strip()
_road_source_mode = str(_cfg.get('road_source_mode', _roads_topology_preferred)).lower().strip()
if _road_source_mode not in ('auto', 'legacy_debug', 'strips', 'builder', 'topology', 'rtb'):
    _road_source_mode = 'auto'
_qa_autorevert_topology_builder = bool(_cfg.get('qa_autorevert_topology_builder', True))
_junction_min_angle_deg = float(_cfg.get('junction_min_angle_deg', 2.0))
_sliver_edge_min_m = float(_cfg.get('sliver_edge_min_m', 0.01))
_roads_topology_max_prim_ratio = float(_cfg.get('roads_topology_max_prim_ratio', 5.0))
_roads_topology_qa_sample_prims = int(_cfg.get('roads_topology_qa_sample_prims', 500))
_apply_road_profiles = bool(_cfg.get('apply_road_profiles', True))
_apply_curb_variation = bool(_cfg.get('apply_curb_variation', True))
_RECOOK_FINALIZED = False


def _mark_unhandled_exit():
    if _RECOOK_FINALIZED:
        return
    _message = 'Houdini recook exited before completion'
    try:
        _write_build_status(_area_id, 'failed', message=_message, run_id=_run_id)
        if _run_id:
            pipeline_state.fail_run(_run_id, phase='houdini_recook', message=_message)
    except Exception:
        pass


atexit.register(_mark_unhandled_exit)

if _run_id:
    pipeline_state.update_run(_run_id, status='running', phase='houdini_preflight',
                              message='checking Houdini-ready inputs')
_write_build_status(_area_id, 'running', message='Houdini recook started', run_id=_run_id)

# ── 前置：只做 Houdini-ready preflight，不再兜底清洗 ────────────────
_hr_dir = ROOT / 'RawData' / '_houdini_ready' / _area_id
if not dcc.ready_outputs_exist(_hr_dir, expected_area_id=_area_id,
                               expected_run_id=_run_id or None):
    _RECOOK_FINALIZED = True
    _message = (
        'Houdini-ready preflight failed: RawData/_houdini_ready/{area_id} '
        'is missing, incomplete, or does not match current run_id'
    ).format(area_id=_area_id)
    print('  [FAIL] ' + _message)
    print('         Run cleaning/refine_data.py first, or use orchestration/run_pipeline.py for the full pipeline.')
    _write_build_status(_area_id, 'failed', message=_message, run_id=_run_id)
    if _run_id:
        pipeline_state.fail_run(_run_id, phase='houdini_preflight', message=_message)
    sys.exit(1)
else:
    print('[Houdini preflight] _houdini_ready 已就绪，run_id 匹配')

print('[Houdini 1/7] 数据就绪，连接 Houdini...', flush=True)

# ══════════════════════════════════════════
# 颜色配置 — 修改这里即可独立控制三类颜色
COLORS = {
    'roads':     (1.00, 1.00, 1.00),  # 道路：纯白
    'buildings': (0.55, 0.55, 0.55),  # 建筑：中灰
    'terrain':   (0.25, 0.25, 0.25),  # 地形：深灰
}
# ══════════════════════════════════════════

conn = rpyc.classic.connect('localhost', 18811)
conn._config['sync_request_timeout'] = 600
hou  = conn.modules.hou
ROOT_STR = ROOT.as_posix()
CFG_FILE = ACTIVE_AREA.as_posix()

# OBJ 网络名：从 active_area.json 读取，可在换城市时修改
OBJ_NET = _cfg.get('obj_network', 'city_gen')
OBJ_PATH = f'/obj/{OBJ_NET}'

# ── 0. 确保 hip 已加载 ───────────────────────────────
HIP = MASTER_HIP.as_posix()
if 'untitled' in hou.hipFile.path():
    hou.hipFile.load(HIP, suppress_save_prompt=True)
    print('  hip 已加载: ' + HIP)
else:
    print('  hip: ' + hou.hipFile.path().split('/')[-1])

net = hou.node(OBJ_PATH)
if net is None and OBJ_NET == 'city_gen':
    legacy_net = hou.node('/obj/pattaya_osm')
    if legacy_net is not None:
        net = legacy_net
        OBJ_NET = 'pattaya_osm'
        OBJ_PATH = f'/obj/{OBJ_NET}'

print('[Houdini 2/7] 修复 SOP 和参数...', flush=True)


def cooked_geometry(node_path, force=False, retries=3):
    """Fetch geometry after cook, retrying stale Houdini node proxies."""
    last_exc = None
    for attempt in range(retries):
        try:
            node = hou.node(node_path)
            if node is None:
                return None
            node.cook(force=force)
            node = hou.node(node_path)
            if node is None:
                return None
            return node.geometry()
        except Exception as exc:
            last_exc = exc
            text = '{} {}'.format(type(exc), exc)
            if 'ObjectWasDeleted' not in text and 'no longer exists' not in text:
                raise
            time.sleep(0.15 * (attempt + 1))
    raise last_exc


for _node in net.allSubChildren():
    if _node.type().name() != 'python':
        continue
    _parm = _node.parm('python')
    if not _parm:
        continue
    _code = _parm.eval()
    _new_code = (_code
                 .replace('F:/VirtualCity', ROOT_STR)
                 .replace('D:/VirtualCity', ROOT_STR)
                 .replace('d:/VirtualCity', ROOT_STR)
                 .replace('/原始数据/', '/RawData/')
                 .replace('/自动化插件/', '/Scripts/')
                 .replace('/配置/', '/Config/'))
    if _new_code != _code:
        _parm.set(_new_code)
        print('  Python SOP 路径已适配: ' + _node.name())

# ── osm_import: canonical code (Fix 2+5: single resolver, OSM bld fallback) ──
_OSM_IMPORT_CODE = open(
    str(Path(ROOT_STR) / 'Scripts' / '_osm_import_canonical.py'),
    encoding='utf-8'
).read().replace('__ROOT__', ROOT_STR).replace('__CFG__', CFG_FILE)
osm = hou.node(OBJ_PATH + '/osm_import')
if osm and osm.parm('python'):
    osm.parm('python').set(_OSM_IMPORT_CODE)
    print('  SOP 修复: osm_import (canonical: single resolver + OSM bld fallback)')

# ── 1. 修复 dem_import Python SOP（H-006：硬编码路径）────
DEM_IMPORT_CODE = houdini_sops.load('dem_import.py', ROOT=ROOT_STR, CFG=CFG_FILE)
DEM_TERRAIN_CODE = houdini_sops.load('dem_terrain.py', ROOT=ROOT_STR, CFG=CFG_FILE)

for node_path, code in [
    (OBJ_PATH + '/dem_import',   DEM_IMPORT_CODE),
    (OBJ_PATH + '/dem_terrain',  DEM_TERRAIN_CODE),
]:
    n = hou.node(node_path)
    if n:
        n.parm('python').set(code)
        print('  SOP 修复: ' + node_path.split('/')[-1])

# ── 1a. 修复 divide_bld（Q-001：convex+numsides=3 强制三角化建筑 footprint）──
_div_bld = hou.node(OBJ_PATH + '/divide_bld')
if _div_bld:
    _div_bld.parm('convex').set(0)
    _div_bld.parm('usemaxsides').set(0)
    print('  SOP 修复: divide_bld (Q-001: 关闭 convex+numsides → 保留 n-gon footprint)')

# ── 1b. 修复道路地形吸附（H-007：Ray SOP direction=0，改用 XZ 垂直投射）──
ROAD_SNAP_VEX = road_pipe.ROAD_SNAP_VEX
snap_old = hou.node(OBJ_PATH + '/snap_roads_to_terrain1')
dem_t    = hou.node(OBJ_PATH + '/dem_terrain')
if snap_old and snap_old.type().name() == 'ray':
    road_w = hou.node(OBJ_PATH + '/road_width')
    resample = hou.node(OBJ_PATH + '/resample_roads')
    snap_old.destroy()
    snap_new = net.createNode('attribwrangle', 'snap_roads_to_terrain1')
    snap_new.setInput(0, resample)
    snap_new.setInput(1, dem_t)
    snap_new.parm('class').set(2)  # 2 = Point
    snap_new.parm('snippet').set(ROAD_SNAP_VEX)
    snap_old = snap_new
    print('  SOP 修复: snap_roads_to_terrain1 (Ray→xyzdist attribwrangle)')
elif snap_old:
    snap_old.parm('class').set(2)
    snap_old.parm('snippet').set(ROAD_SNAP_VEX)
    if dem_t:
        snap_old.setInput(1, dem_t)
    print('  snap_roads_to_terrain1 class=2 + VEX 已校验更新')

# ── 1b1.5. 道路 1D 纵向高程平滑（Milestone 2 - Stage 2.5） ─────────────────────
_smoother_code = houdini_sops.load('road_vertical_smoother.py')
_smoother_node = hou.node(OBJ_PATH + '/road_vertical_smoother')
if _smoother_node is None:
    _smoother_node = net.createNode('python', 'road_vertical_smoother')
_smoother_node.setInput(0, snap_old)
_smoother_node.parm('python').set(_smoother_code)
_smoother_node.cook(force=True)
print('  road_vertical_smoother SOP 已注入并执行（Laplacian 平滑与坡度夹紧）')

# ── 1b2. 道路分级宽度（road_width attribwrangle）──────────────────────────
ROAD_WIDTH_VEX = road_pipe.ROAD_WIDTH_VEX
_rwf_node = hou.node(OBJ_PATH + '/road_width_flat')
_road_width_input = _smoother_node
if _rwf_node is None:
    _rwf_node = net.createNode('attribwrangle', 'road_width_flat')
if _road_width_input:
    _rwf_node.setInput(0, _road_width_input, 0)
_rwf_node.parm('class').set(1)  # Primitive
_rwf_node.parm('snippet').set(ROAD_WIDTH_VEX)
print('  road_width_flat VEX + 输入已更新（road_vertical_smoother → road_width_flat）')

# ── 1b3. road_graph 过滤：把离线折叠掉的短冲突边同步回 Houdini ─────────────
ROAD_GRAPH_FILTER_CODE = houdini_sops.load('road_graph_filter.py', ROOT=ROOT_STR, CFG=CFG_FILE)
_rgf_node = hou.node(OBJ_PATH + '/road_graph_filter')
if _rgf_node is None:
    _rgf_node = net.createNode('python', 'road_graph_filter')
_rgf_node.setInput(0, _rwf_node, 0)
_rgf_node.parm('python').set(ROAD_GRAPH_FILTER_CODE)
_road_mesh_input = _rgf_node
print('  road_graph_filter 已接入（road_width_flat → road_graph_filter → road surface builders）')


# ── 1d. road_strips v2: 路段修剪 + 路口凸包填充 ──────────────────────
_rs_v2_code = road_pipe.load_road_strips_code(ROOT)
_rs_node = hou.node(OBJ_PATH + '/road_strips')
if _rs_node is None:
    _rs_node = net.createNode('python', 'road_strips')
_rs_node.parm('python').set(_rs_v2_code)
_rs_node.setInput(0, _road_mesh_input, 0)
print('  road_strips v5 已更新（复杂路口降级 + 调试属性 + 自交保护）')

# ── 1d2. Road Topology Builder（A/B 可选）────────────────────────────
# 说明：该节点在 'road_width_flat' 之后按拓扑半径截断 + 扇面缝合生成道路面片，
# 通过 'road_source' Switch 在现有 road_strips 与新生成之间切换，默认仍选用 road_strips。
try:
    RTB_CODE = houdini_sops.load('road_topology_builder.py')
    rtb_node = hou.node(OBJ_PATH + '/road_topology_builder')
    if rtb_node is None:
        rtb_node = net.createNode('python', 'road_topology_builder')
    rtb_node.setInput(0, _road_mesh_input, 0)
    rtb_node.parm('python').set(RTB_CODE)
    # 路径选择器：0=road_strips（默认），1=road_topology_builder
    source_switch = hou.node(OBJ_PATH + '/road_source')
    if source_switch is None:
        source_switch = net.createNode('switch', 'road_source')
    # 确保两路输入就绪
    rs_node_ref = hou.node(OBJ_PATH + '/road_strips')
    if rs_node_ref:
        source_switch.setInput(0, rs_node_ref, 0)
    source_switch.setInput(1, rtb_node, 0)
    # 默认策略：auto。builder 通过轻量 QA 就使用；失败则回退 legacy road_strips。
    _pref_mode = _road_source_mode or _roads_topology_preferred
    _pref = 1 if _pref_mode in ('builder', 'topology', 'rtb') else 0

    def _xz_min_angle(pts):
        if len(pts) < 3:
            return None
        import math as _m
        mn = None
        for i, cur in enumerate(pts):
            prev = pts[(i-1) % len(pts)]
            nxt = pts[(i+1) % len(pts)]
            ax, az = prev[0]-cur[0], prev[2]-cur[2]
            bx, bz = nxt[0]-cur[0], nxt[2]-cur[2]
            al = (_m.hypot(ax, az))
            bl = (_m.hypot(bx, bz))
            if al < 1e-9 or bl < 1e-9:
                continue
            dt = max(-1.0, min(1.0, (ax*bx + az*bz) / (al*bl)))
            ang = _m.degrees(_m.acos(dt))
            mn = ang if mn is None else min(mn, ang)
        return mn

    def _xz_min_edge(pts):
        import math as _m
        if len(pts) < 2:
            return 0.0
        mn = 1e9
        for i, p in enumerate(pts):
            q = pts[(i+1) % len(pts)]
            mn = min(mn, _m.hypot(q[0]-p[0], q[2]-p[2]))
        return 0.0 if mn == 1e9 else mn

    _builder_bad = 0
    _builder_checked = 0
    _builder_prims = 0
    _strips_prims = 0
    _builder_ratio = 0.0
    _builder_qa_ok = False
    if _pref_mode in ('auto', 'builder', 'topology', 'rtb'):
        try:
            rtb_node.cook(force=True)
            geo_b = rtb_node.geometry()
            _builder_prims = int(geo_b.intrinsicValue('primitivecount'))
            if rs_node_ref:
                try:
                    _strips_prims = int(rs_node_ref.geometry().intrinsicValue('primitivecount'))
                except Exception:
                    _strips_prims = 0
            _builder_ratio = (_builder_prims / float(_strips_prims)) if _strips_prims else 0.0
            _builder_sample_limit = max(50, min(_roads_topology_qa_sample_prims, _builder_prims))
            for prim in geo_b.prims():
                pts = [v.point().position() for v in prim.vertices()]
                if len(pts) < 3:
                    continue
                ang = _xz_min_angle(pts)
                edge = _xz_min_edge(pts)
                if (ang is not None and ang < _junction_min_angle_deg) or (edge < _sliver_edge_min_m):
                    _builder_bad += 1
                _builder_checked += 1
                if _builder_checked >= _builder_sample_limit:
                    break
            _builder_qa_ok = (
                _builder_bad == 0
                and _builder_prims > 0
                and (_builder_ratio <= _roads_topology_max_prim_ratio or _strips_prims <= 0)
            )
        except Exception as _qe:
            _builder_qa_ok = False
            print(f"  [road_source] builder QA 评估失败: {_qe}")

    if _pref_mode == 'auto':
        _pref = 1 if _builder_qa_ok else 0
    elif _pref_mode in ('legacy_debug', 'strips'):
        _pref = 0
    elif _pref in (1,) and _qa_autorevert_topology_builder and not _builder_qa_ok:
        _pref = 0
        print("  [auto-revert] road_topology_builder QA 未通过，已回退为 road_strips")
    source_switch.parm('input').set(_pref)
    _chosen = 'road_topology_builder' if _pref == 1 else 'road_strips'
    print("  road_source: mode={} selected={} builder_prims={} strips_prims={} ratio={:.2f} bad={}/{}".format(
        _road_source_mode or _pref_mode, _chosen, _builder_prims, _strips_prims, _builder_ratio, _builder_bad, _builder_checked))
except Exception as _e:
    print(f"  [WARN] Road Topology Builder 注入失败，保持使用 road_strips: {_e}")

# ── 1c. 修复建筑地形吸附（H-011：坡面建筑底面埋入地形）──────────────
BLD_SNAP_VEX = houdini_sops.load('bld_snap.vex')
snap_bld = hou.node(OBJ_PATH + '/snap_bld_to_terrain')
if snap_bld:
    snap_bld.parm('class').set(1)   # Primitive
    snap_bld.parm('snippet').set(BLD_SNAP_VEX)
    print('  SOP 修复: snap_bld_to_terrain (逐顶点 MAX 高度)')

# ── P0: procedural_height VEX —— 同时处理 height_m<=0 和 ~10m 两种缺失情况 ──
PROC_HEIGHT_VEX = houdini_sops.load('procedural_height.vex')
_ph = hou.node(OBJ_PATH + '/procedural_height')
if _ph:
    _ph.parm('snippet').set(PROC_HEIGHT_VEX)
    print('  SOP 修复: procedural_height (P0: height_m<=0 fallback)')

# ── 2. 强制 recook 数据源 ────────────────────────────
print('\n[Houdini 3/7] recook 数据源')
if _dev_quick_roads:
    print('  [dev_quick_roads] 跳过数据源重算 (osm/dem)')
else:
    for path in [OBJ_PATH + '/osm_import', OBJ_PATH + '/dem_import',
                 OBJ_PATH + '/dem_terrain']:
        n = hou.node(path)
        if not n:
            continue
        print(f'  Cooking: {path}')
        try:
            n.cook(force=True)
        except Exception as e:
            print(f'  [ERROR] Cook failed for {path}!')
            try:
                print(f'  Node errors:\n{n.errors()}')
                print(f'  Node warnings:\n{n.warnings()}')
            except Exception as e2:
                print(f'  Could not retrieve node errors: {e2}')
            raise e
        geo  = n.geometry()
        pts  = geo.intrinsicValue('pointcount')
        prm  = geo.intrinsicValue('primitivecount')
        print('  {:<20s} pts={:6d}  prims={:6d}'.format(n.name(), pts, prm))
        if pts == 0:
            errors.append(n.name() + ' geometry empty after recook')

# ── 2b. 地形 snap target = dem_subdivide ──────────────────────────────
# DEM 原始约 30m 网格，在山地俯视角布线过稀。Bilinear×2 只做线性插值，
# 不增加真实高程精度，但能把显示和道路贴地目标提升到约 7.5m 网格。
dem_terrain = hou.node(OBJ_PATH + '/dem_terrain')

# ── 2b2. 阶段2.5（可选）：Cut&Fill；默认关闭，按 active_area.json 的 roads_cut_fill_enabled 控制 ──
snap_target = hou.node(OBJ_PATH + '/dem_subdivide')
if snap_target is None:
    snap_target = net.createNode('subdivide', 'dem_subdivide')

if _roads_cut_fill_enabled:
    cut_fill_target = hou.node(OBJ_PATH + '/dem_cut_and_fill')
    if cut_fill_target is None:
        cut_fill_target = net.createNode('attribwrangle', 'dem_cut_and_fill')
    cut_fill_target.setInput(0, dem_terrain)
    cut_fill_target.setInput(1, _rwf_node)
    cut_fill_target.parm('class').set(2)  # Point level
    cut_fill_target.parm('snippet').set(road_pipe.ROAD_CUT_FILL_VEX)
    cut_fill_target.cook(force=True)
    print('  dem_cut_and_fill VEX 削坡平整完成: pts={}'.format(
        cut_fill_target.geometry().intrinsicValue('pointcount')))
    snap_target.setInput(0, cut_fill_target)
else:
    # 阶段1+2：不启用 Cut&Fill，直接用 dem_terrain 进入 subdivide
    snap_target.setInput(0, dem_terrain)
snap_target.parm('algorithm').set(4)   # OpenSubdiv Bilinear
snap_target.parm('iterations').set(2)  # 30m -> ~7.5m
snap_target.cook(force=True)
print('  dem_subdivide: pts={} prims={} (Bilinear iterations=2)'.format(
    snap_target.geometry().intrinsicValue('pointcount'),
    snap_target.geometry().intrinsicValue('primitivecount')))

for _sn_name in ['snap_bld_to_terrain', 'snap_roads_to_terrain1']:
    _sn = hou.node(OBJ_PATH + '/' + _sn_name)
    if _sn:
        _sn.setInput(1, snap_target)

# -- 2c. Building footprint chamfer: convex vertical corners only ----------
BLD_FOOTPRINT_BEVEL_CODE = houdini_sops.load('bld_footprint_bevel.py')

for _ph_name in ['promote_height', 'restore_height']:
    _ph = hou.node(OBJ_PATH + '/' + _ph_name)
    if _ph and _ph.parm('method'):
        _ph.parm('method').set(1)  # 1 = First

old_bld_footprint_bevel = hou.node(OBJ_PATH + '/bld_footprint_bevel')
if old_bld_footprint_bevel:
    old_bld_footprint_bevel.destroy()
bld_footprint_bevel = net.createNode('python', 'bld_footprint_bevel')
restore_height = hou.node(OBJ_PATH + '/restore_height')
bld_footprint_bevel.setInput(0, restore_height)
bld_footprint_bevel.parm('python').set(BLD_FOOTPRINT_BEVEL_CODE)
bld_footprint_bevel.cook(force=True)
extrude_buildings = hou.node(OBJ_PATH + '/extrude_buildings')
if extrude_buildings:
    extrude_buildings.setInput(0, bld_footprint_bevel)
print('  bld_footprint_bevel: pts={} prims={}'.format(
    bld_footprint_bevel.geometry().intrinsicValue('pointcount'),
    bld_footprint_bevel.geometry().intrinsicValue('primitivecount')))

# ── 3. 验证全链路节点 ────────────────────────────────
print('\n[Houdini 4/7] 全链路验证')
CHECKS = [
    ('extract_buildings',    50,   None,  'buildings extracted from OSM'),
    ('snap_bld_to_terrain',  50,   None,  'buildings snapped to terrain'),
    ('bld_footprint_bevel',  50,   None,  'building footprints chamfered'),
    ('extrude_buildings',    50,   None,  'buildings extruded'),
    ('post_normals',         50,   None,  'normals computed'),
    ('road_strips',          100,  None,  'roads generated'),
]
for name, min_pts, max_y, desc in CHECKS:
    node_path = OBJ_PATH + '/' + name
    n = hou.node(node_path)
    if not n:
        print('  SKIP  {:<22s} (node not found)'.format(name))
        continue
    try:
        geo = cooked_geometry(node_path, force=False)
        if geo is None:
            raise RuntimeError('node disappeared during cook')
        pts  = geo.intrinsicValue('pointcount')
        bb   = geo.boundingBox()
        mn_y = bb.minvec()[1]
        mx_y = bb.maxvec()[1]
        ok   = pts >= min_pts
        tag  = PASS if ok else FAIL
        print('  {}  {:<22s} pts={:6d}  Y[{:.1f}~{:.1f}]  {}'.format(
            tag, name, pts, mn_y, mx_y, desc))
    except Exception as exc:
        ok = False
        print('  {}  {:<22s} geometry unavailable: {}'.format(FAIL, name, exc))
        errors.append('{} geometry unavailable: {}'.format(name, exc))
        continue
    if not ok:
        errors.append('{} pts={} < {}'.format(name, pts, min_pts))

# ── 4. 重建裁剪节点 ──────────────────────────────────
print('\n[Houdini 5/7] 完整资产边界过滤节点重建')
dem = snap_target
dem.cook(force=False)
bb  = dem.geometry().boundingBox()
mn, mx = bb.minvec(), bb.maxvec()
MARGIN = 100  # 增加外扩距离以减少边界处的道路裁剪
XMIN = mn[0] - MARGIN
XMAX = mx[0] + MARGIN
ZMIN = mn[2] - MARGIN
ZMAX = mx[2] + MARGIN
print('  DEM 边界: X[{:.0f}~{:.0f}] Z[{:.0f}~{:.0f}]'.format(XMIN, XMAX, ZMIN, ZMAX))

def asset_filter_code(mode):
    return houdini_sops.load(
        'asset_bounds_filter.py',
        XMIN=XMIN, XMAX=XMAX, ZMIN=ZMIN, ZMAX=ZMAX,
        MODE=mode,
    )


def remake_asset_filter(src_name, mark_name, out_name, mode):
    for nm in [out_name, mark_name]:
        old = hou.node(OBJ_PATH + '/' + nm)
        if old:
            old.destroy()
    src = hou.node(OBJ_PATH + '/' + src_name)
    if not src:
        errors.append('source node not found: ' + src_name)
        return None
    b = net.createNode('python', out_name)
    b.setInput(0, src)
    b.parm('python').set(asset_filter_code(mode))
    b.cook(force=True)
    geo  = b.geometry()
    pts  = geo.intrinsicValue('pointcount')
    prims = geo.intrinsicValue('primitivecount')
    bb2  = geo.boundingBox()
    tag  = PASS if pts > 0 else FAIL
    try:
        kept = geo.attribValue('asset_bounds_kept_units')
        removed = geo.attribValue('asset_bounds_removed_units')
        units = ' kept_units={} removed_units={}'.format(kept, removed)
    except Exception:
        units = ''
    print('  {}  {:<20s} mode={:<9s} pts={:6d} prims={:6d}  Y[{:.1f}~{:.1f}]{}'.format(
        tag, out_name, mode, pts, prims, bb2.minvec()[1], bb2.maxvec()[1], units))
    if pts == 0:
        errors.append(out_name + ' empty after asset bounds filter')
    return b


# ── 4b. road_strips 二次地形吸附（修复侧边点埋入地形）────────────────
ROAD_DRAPE_VEX = road_pipe.ROAD_DRAPE_VEX
old_drape = hou.node(OBJ_PATH + '/snap_road_strips')
if old_drape:
    old_drape.destroy()
road_strips_node = hou.node(OBJ_PATH + '/road_strips')
road_source_switch = hou.node(OBJ_PATH + '/road_source')
road_mesh_src = road_source_switch if road_source_switch is not None else road_strips_node
snap_road_strips = net.createNode('attribwrangle', 'snap_road_strips')
snap_road_strips.setInput(0, road_mesh_src)
snap_road_strips.setInput(1, snap_target)
snap_road_strips.parm('class').set(2)   # Point
snap_road_strips.parm('snippet').set(ROAD_DRAPE_VEX)
snap_road_strips.cook(force=True)
_rs_geo  = snap_road_strips.geometry()
_rs_pts  = _rs_geo.intrinsicValue('pointcount')
_rs_bb   = _rs_geo.boundingBox()
_rs_ymin = _rs_bb.minvec()[1]
print('  snap_road_strips: pts={} Y_min={:.2f}m'.format(_rs_pts, _rs_ymin))

# ── 4b2. 道路完整面片边界过滤（不再几何切割边界面）──────────────
old_bbox_clip = hou.node(OBJ_PATH + '/road_bbox_clip')
if old_bbox_clip:
    old_bbox_clip.destroy()
road_bbox_clip = net.createNode('python', 'road_bbox_clip')
road_bbox_clip.setInput(0, snap_road_strips)
road_bbox_clip.parm('python').set(asset_filter_code('primitive'))
road_bbox_clip.cook(force=True)
print('  road_bbox_clip: pts={} prims={} preserved_prims={}'.format(
    road_bbox_clip.geometry().intrinsicValue('pointcount'),
    road_bbox_clip.geometry().intrinsicValue('primitivecount'),
    road_bbox_clip.geometry().attribValue('road_bbox_preserved_ngon_count')))

old_final_drape = hou.node(OBJ_PATH + '/snap_road_clipped')
if old_final_drape:
    old_final_drape.destroy()
snap_road_clipped = net.createNode('attribwrangle', 'snap_road_clipped')
snap_road_clipped.setInput(0, road_bbox_clip)
snap_road_clipped.setInput(1, snap_target)
snap_road_clipped.parm('class').set(2)   # Point
snap_road_clipped.parm('snippet').set(ROAD_DRAPE_VEX)
snap_road_clipped.cook(force=True)
print('  snap_road_clipped: pts={} Y_min={:.2f}m'.format(
    snap_road_clipped.geometry().intrinsicValue('pointcount'),
    snap_road_clipped.geometry().boundingBox().minvec()[1]))

bld_clip  = remake_asset_filter('post_normals',     'bld_clip_mark',  'bld_clipped',  'component')
road_clip = remake_asset_filter('snap_road_clipped', 'road_clip_mark', 'road_clipped', 'primitive')

# ── 4b2.4 道路碎片清理：移除扇形三角化产生的微小三角形 ──────────────────
ROAD_FRAGMENT_CLEANUP_CODE = houdini_sops.load('road_fragment_cleanup.py')
old_frag_cleanup = hou.node(OBJ_PATH + '/road_fragment_cleanup')
if old_frag_cleanup:
    old_frag_cleanup.destroy()
road_frag_cleanup = net.createNode('python', 'road_fragment_cleanup')
road_frag_cleanup.setInput(0, road_clip)
road_frag_cleanup.parm('python').set(ROAD_FRAGMENT_CLEANUP_CODE)
road_frag_cleanup.cook(force=True)
_frag_tiny = road_frag_cleanup.geometry().attribValue('rfc_removed_tiny_triangles') if road_frag_cleanup.geometry().findGlobalAttrib('rfc_removed_tiny_triangles') else 0
_frag_sliver = road_frag_cleanup.geometry().attribValue('rfc_removed_sliver_triangles') if road_frag_cleanup.geometry().findGlobalAttrib('rfc_removed_sliver_triangles') else 0
_frag_sharp = road_frag_cleanup.geometry().attribValue('rfc_removed_sharp_triangles') if road_frag_cleanup.geometry().findGlobalAttrib('rfc_removed_sharp_triangles') else 0
print('  road_fragment_cleanup: 移除微小={} 细长={} 尖锐={}'.format(_frag_tiny, _frag_sliver, _frag_sharp))
road_clip = road_frag_cleanup

# ── 4b2.5 可选：属性驱动截面配置注入（不改变几何，仅写入属性）──────
road_profile_src = road_clip
try:
    old_prof = hou.node(OBJ_PATH + '/road_profile_apply')
    if _apply_road_profiles and road_clip is not None:
        if old_prof:
            old_prof.destroy()
        ROAD_PROFILE_APPLY_CODE = houdini_sops.load('road_profile_apply.py', ROOT=ROOT_STR)
        road_prof = net.createNode('python', 'road_profile_apply')
        road_prof.setInput(0, road_clip)
        road_prof.parm('python').set(ROAD_PROFILE_APPLY_CODE)
        road_prof.cook(force=True)
        road_profile_src = road_prof
        _prof_geo = road_prof.geometry()
        try:
            _applied = _prof_geo.attribValue('road_profile_applied_prims')
            _fallback = _prof_geo.attribValue('road_profile_fallback_prims')
        except Exception:
            _applied = _prof_geo.intrinsicValue('primitivecount')
            _fallback = 0
        print('  road_profile_apply: 已注入 applied={} fallback={}（从 Config/road_profiles.json 读取截面参数）'.format(
            _applied, _fallback))
    elif old_prof:
        old_prof.destroy()
        print('  road_profile_apply: 已关闭并移除旧节点')
except Exception as _e:
    print(f'  [WARN] road_profile_apply 注入失败: {_e}')

# ── 4b2.6 可选：路缘石随机起伏（Milestone 3 微细节）──────────────
road_curb_src = road_profile_src
try:
    old_curb = hou.node(OBJ_PATH + '/road_curb_variation')
    if _apply_curb_variation and road_profile_src is not None:
        if old_curb:
            old_curb.destroy()
        ROAD_CURB_VARIATION_CODE = houdini_sops.load('road_curb_variation.py', ROOT=ROOT_STR)
        road_curb = net.createNode('python', 'road_curb_variation')
        road_curb.setInput(0, road_profile_src)
        road_curb.parm('python').set(ROAD_CURB_VARIATION_CODE)
        road_curb.cook(force=True)
        road_curb_src = road_curb
        try:
            _curb_applied = road_curb.geometry().attribValue('road_curb_variation_applied_prims')
        except Exception:
            _curb_applied = road_curb.geometry().intrinsicValue('primitivecount')
        print('  road_curb_variation: 已注入 applied={} (±2cm 随机起伏)'.format(_curb_applied))
    elif old_curb:
        old_curb.destroy()
        print('  road_curb_variation: 已关闭并移除旧节点')
except Exception as _e:
    print(f'  [WARN] road_curb_variation 注入失败: {_e}')

# ── 4b3. 建筑地基 / 裙边（坡地建筑下坡侧补空）──────────────────────
BUILDING_FOUNDATION_CODE = houdini_sops.load('bld_foundation.py')

old_foundation = hou.node(OBJ_PATH + '/bld_foundation')
if old_foundation:
    old_foundation.destroy()
bld_foundation = net.createNode('python', 'bld_foundation')
bld_foundation.setInput(0, bld_clip)
bld_foundation.setInput(1, snap_target)
bld_foundation.parm('python').set(BUILDING_FOUNDATION_CODE)
bld_foundation.cook(force=True)
print('  bld_foundation: pts={} prims={}'.format(
    bld_foundation.geometry().intrinsicValue('pointcount'),
    bld_foundation.geometry().intrinsicValue('primitivecount')))

foundation_clip = remake_asset_filter('bld_foundation', 'bld_foundation_clip_mark', 'bld_foundation_clipped', 'component')

# ── 4c. 颜色节点（三类独立，来自 COLORS 配置）────────────────────────
def make_color_node(name, src_node, rgb):
    old = hou.node(OBJ_PATH + '/' + name)
    if old: old.destroy()
    w = net.createNode('attribwrangle', name)
    w.setInput(0, src_node)
    w.parm('class').set(2)  # Point
    w.parm('snippet').set('@Cd = set({:.4f}, {:.4f}, {:.4f});'.format(*rgb))
    w.cook(force=True)
    return w

road_colored    = make_color_node('road_color',    road_curb_src,   COLORS['roads'])
bld_colored     = make_color_node('bld_color',     bld_clip,    COLORS['buildings'])
foundation_colored = None
if foundation_clip:
    foundation_colored = make_color_node('bld_foundation_color', foundation_clip, COLORS['buildings'])
terrain_colored = make_color_node('terrain_color', snap_target, COLORS['terrain'])

old_bld_final = hou.node(OBJ_PATH + '/bld_with_foundation')
if old_bld_final:
    old_bld_final.destroy()
old_bld_merge = hou.node(OBJ_PATH + '/bld_with_foundation_merge')
if old_bld_merge:
    old_bld_merge.destroy()
bld_merge = net.createNode('merge', 'bld_with_foundation_merge')
bld_merge.setInput(0, bld_colored)
if foundation_colored:
    bld_merge.setInput(1, foundation_colored)
bld_merge.cook(force=True)

bld_final = net.createNode('normal', 'bld_with_foundation')
bld_final.setInput(0, bld_merge)
if bld_final.parm('type'):
    bld_final.parm('type').set(1)  # Vertex normals
if bld_final.parm('cuspangle'):
    bld_final.parm('cuspangle').set(0.0)  # hard building edges, no wall smoothing
if bld_final.parm('normalize'):
    bld_final.parm('normalize').set(1)
bld_final.cook(force=True)
print('  bld_with_foundation: pts={} prims={}'.format(
    bld_final.geometry().intrinsicValue('pointcount'),
    bld_final.geometry().intrinsicValue('primitivecount')))

# ── 4d. 道路面片输出（无挤出）────────────────────────────
# 当前道路阶段先保持为平面面片，避免 PolyExtrude 在分段道路上生成细碎侧面。
for _old_road_node in ('road_pre_extrude_dissolve', 'road_pre_extrude_fuse', 'road_extrude'):
    _old = hou.node(OBJ_PATH + '/' + _old_road_node)
    if _old:
        _old.destroy()
        print('  道路挤出节点移除: ' + _old_road_node)
road_surface = road_colored
print('  road_surface: 使用平面道路面片（无挤出） pts={} prims={}'.format(
    road_surface.geometry().intrinsicValue('pointcount'),
    road_surface.geometry().intrinsicValue('primitivecount')))

# ── 4e. promote_height / restore_height: method=First 防跨建筑高度污染 ─
# fuse_bld 焊接邻近建筑角点后，Average 模式会让相邻建筑高度互相稀释。
# 改用 First（method=1）保留任一原值，量级误差 1~3m → 0m。
for _ph_name in ['promote_height', 'restore_height']:
    _ph = hou.node(OBJ_PATH + '/' + _ph_name)
    if _ph and _ph.parm('method'):
        _ph.parm('method').set(1)  # 1 = First

# ── 4f. 死节点清理 ─────────────────────────────────────
_dead_nodes = [
    'bld_height_vary',       # 早期实验残留
    'dem_triangulate',       # 已被 dem_terrain 替代
    'dem_import',            # 仅喂 dem_triangulate（须在其后删）
    'dem_hf_import1',        # 孤立空节点
    '__tmp_subdivide',       # 临时残留
    'snap_roads_to_terrain', # 旧 Ray 实现，已被 _terrain1 替代
    'road_width',            # 已被 road_width_flat 替代
]
# 两遍清理，避免下游先于上游的依赖残留阻塞
for _ in range(2):
    for _dn in _dead_nodes:
        _n = hou.node(OBJ_PATH + '/' + _dn)
        if _n and len(_n.outputs()) == 0:
            _n.destroy()
            print('  死节点清理: ' + _dn)

# ── 5. 重连 merge_all + 保存 ────────────────────────
merge = hou.node(OBJ_PATH + '/merge_all')
if merge and bld_clip and road_clip:
    merge.setInput(0, bld_final)
    merge.setInput(1, road_surface)
    merge.setInput(2, terrain_colored)

print('\n[Houdini 6/7] 刷新输出链并保存 HIP')
net.layoutChildren()
hou.hipFile.save()

# ── 5b. Hip 按区域存档 ────────────────────────────────
import shutil as _shutil, json as _json_arc
ARCHIVE_HIP = (HOUDINI / 'Hip' / 'VC_{}_citygen_v001.hip'.format(_area_id)).as_posix()
if ARCHIVE_HIP != HIP:
    _shutil.copy2(HIP, ARCHIVE_HIP)
    print('  hip 存档: VC_{}_citygen_v001.hip'.format(_area_id))

# ── 6. 强制刷新整条输出链（视口同步）────────────────────
if _dev_quick_roads:
    FULL_CHAIN = [
        'snap_roads_to_terrain1', 'road_vertical_smoother', 'road_width_flat',
        'road_graph_filter',
        'road_strips', 'road_topology_builder', 'road_source',
        'snap_road_strips', 'road_bbox_clip', 'snap_road_clipped',
        'road_clipped', 'road_fragment_cleanup', 'road_profile_apply', 'road_curb_variation', 'road_color', 'OUT_city',
    ]
else:
    FULL_CHAIN = [
        'osm_import', 'dem_terrain', 'dem_cut_and_fill', 'dem_subdivide',
        'extract_buildings', 'snap_bld_to_terrain', 'bld_footprint_bevel', 'extrude_buildings', 'post_normals',
        'snap_roads_to_terrain1', 'road_vertical_smoother', 'road_width_flat',
        'road_graph_filter',
        'road_strips', 'road_topology_builder', 'road_source',
        'snap_road_strips', 'road_bbox_clip', 'snap_road_clipped',
        'bld_clipped', 'bld_foundation', 'bld_foundation_clipped',
        'road_clipped', 'road_fragment_cleanup', 'road_profile_apply', 'road_curb_variation', 'road_color',
        'bld_color', 'bld_foundation_color', 'bld_with_foundation_merge', 'bld_with_foundation',
        'terrain_color', 'merge_all', 'OUT_city',
    ]
for _cn in FULL_CHAIN:
    _n = hou.node(OBJ_PATH + '/' + _cn)
    if _n:
        _n.cook(force=True)
_out = hou.node(OBJ_PATH + '/OUT_city')
if _out:
    _out.setDisplayFlag(True)
    _out.setRenderFlag(True)
print('  [OK] 视口链已强制刷新')

# Release the recook RPYC connection before the standalone QA subprocess opens
# its own connection. Houdini's lightweight RPYC server can drop one stream when
# two long-lived clients inspect geometry at the same time.
try:
    conn.close()
except Exception:
    pass
conn = None

# -- 6b. Quick model QA (fast regression gate) ---------------------------
qa_status = ''
qa_report = ''
if not errors:
    print('\n[Houdini 7/7] Model QA')
    _qa_cmd = [sys.executable, str(ROOT / 'Scripts' / 'houdini_model_qa.py'), '--mode', 'quick']
    _qa_result = subprocess.run(_qa_cmd, cwd=str(ROOT), capture_output=False)
    _qa_latest = ROOT / 'Reports' / 'model_qa' / '{}_latest.json'.format(_area_id)
    if not _qa_latest.exists():
        _qa_latest = ROOT / 'Reports' / 'model_qa' / 'latest.json'
    if _qa_latest.exists():
        try:
            with open(_qa_latest, encoding='utf-8') as _f:
                _qa_payload = json.load(_f)
                qa_status = _qa_payload.get('status', '')
                qa_report = _qa_payload.get('report_path', project_relative(_qa_latest))
        except Exception as _exc:
            qa_status = 'unreadable'
            qa_report = project_relative(_qa_latest)
            print('  [WARN] Model QA report unreadable: {}'.format(_exc))
    if _qa_result.returncode != 0:
        errors.append('model QA failed (see {})'.format(qa_report or 'Reports/model_qa/latest.json'))

# ── 结果汇报 ─────────────────────────────────────────
print()
if errors:
    _RECOOK_FINALIZED = True
    print('[FAIL] 发现 {} 个错误:'.format(len(errors)))
    for e in errors:
        print('  - ' + e)
    _write_build_status(_area_id, 'failed', ARCHIVE_HIP, '; '.join(errors), qa_status, qa_report, _run_id)
    if _run_id:
        pipeline_state.fail_run(_run_id, phase='houdini_recook', message='; '.join(errors))
    sys.exit(1)
else:
    _RECOOK_FINALIZED = True
    _msg = 'Houdini build completed'
    if qa_status:
        _msg += '; model QA quick {}'.format(qa_status)
    _write_build_status(_area_id, 'completed', ARCHIVE_HIP, _msg, qa_status, qa_report, _run_id)
    if _run_id:
        pipeline_state.update_run(_run_id, status='completed', phase='houdini_completed',
                                  message=_msg, fields={'hip_path': project_relative(ARCHIVE_HIP),
                                                        'qa_status': qa_status,
                                                        'qa_report': qa_report})
    print('[OK] 全部通过，hip 已保存')
    print('     Houdini 构建完成标记: Config/houdini_build_status.json')
    print('     请在 Houdini 视口选中 OUT_city 按 D 确认效果')

if conn:
    conn.close()
