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
from houdini_build.context import BuildContext
from houdini_build.domains import domain_summary
from houdini_build.domains import buildings as buildings_domain
from houdini_build.domains import roads as roads_domain
from houdini_build.domains import terrain as terrain_domain
from houdini_build.network_layout import apply_domain_network_layout
from houdini_build.preflight import check_houdini_ready, houdini_ready_failure_message
from houdini_build.status import write_build_status
from orchestration import pipeline_state
from shared.vc_paths import ROOT, HIP as MASTER_HIP, load_active_area, project_relative

PASS = '[OK]'
FAIL = '[FAIL]'
errors = []


def _write_build_status(area_id, status, hip_path=None, message='', qa_status='', qa_report='',
                        run_id=''):
    write_build_status(area_id, status, hip_path, message, qa_status, qa_report, run_id)

_cfg = load_active_area()
_ctx = BuildContext.from_config(_cfg)
_area_id = _ctx.area_id
_run_id = _ctx.run_id
_roads_cut_fill_enabled = _ctx.roads_cut_fill_enabled
_dev_quick_roads = _ctx.dev_quick_roads
_road_output_mode = _ctx.road_output_mode
_apply_road_profiles = _ctx.apply_road_profiles
_apply_curb_variation = _ctx.apply_curb_variation
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
if not check_houdini_ready(_area_id, _run_id):
    _RECOOK_FINALIZED = True
    _message = houdini_ready_failure_message(_area_id)
    print('  [FAIL] ' + _message)
    print('         Run cleaning/refine_data.py first, or use orchestration/run_pipeline.py for the full pipeline.')
    _write_build_status(_area_id, 'failed', message=_message, run_id=_run_id)
    if _run_id:
        pipeline_state.fail_run(_run_id, phase='houdini_preflight', message=_message)
    sys.exit(1)
else:
    print('[Houdini preflight] _houdini_ready 已就绪，run_id 匹配')

print('[Houdini 1/7] 数据就绪，连接 Houdini...', flush=True)
print('  构建域: ' + domain_summary())

# ══════════════════════════════════════════
# 颜色配置 — 修改这里即可独立控制三类颜色
COLORS = _ctx.colors
# ══════════════════════════════════════════

conn = rpyc.classic.connect('localhost', 18811)
conn._config['sync_request_timeout'] = 600
hou  = conn.modules.hou
ROOT_STR = _ctx.root_str
CFG_FILE = _ctx.cfg_file

# OBJ 网络名：从 active_area.json 读取，可在换城市时修改
OBJ_NET = _ctx.obj_net
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

# 构建期间挂起 OUT_city 的 display/render flag：display 节点常开时，每 force
# 一个上游节点都会触发视口把整条 dirty 链拉去重绘一次。实测同一条强制刷新链
# display 开=159.74s / 关=28.32s，~82% 墙钟耗在视口重绘而非建模。flag 在第 6 段
# 结尾会被重新设回 True，几何输出不受影响。
_out_city = hou.node(OBJ_PATH + '/OUT_city')
if _out_city:
    _out_city.setDisplayFlag(False)
    _out_city.setRenderFlag(False)
    print('  OUT_city display/render 已临时挂起（构建结束自动恢复）')


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

# ── 1. 地形域：修复 dem_import / dem_terrain Python SOP ────
terrain_domain.inject_dem_sops(hou, OBJ_PATH, ROOT_STR, CFG_FILE)

# ── 1a. 建筑域：修复建筑 footprint SOP ─────────────────
buildings_domain.patch_footprint_divide_sop(hou, OBJ_PATH)

# ── 1b. 道路域：raw API line、共享拓扑、统一中心线点距 ──
road_source_chain = roads_domain.build_source_chain(
    hou,
    net,
    OBJ_PATH,
    osm,
    params=_ctx.road_build_params,
)
_road_mesh_input = road_source_chain.mesh_input
buildings_domain.patch_snap_and_height_sops(hou, OBJ_PATH)

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

# ── 2b. 地形域：snap target = dem_subdivide ──────────────────────────────
snap_target = terrain_domain.build_snap_target(
    hou,
    net,
    OBJ_PATH,
    None,
    _roads_cut_fill_enabled,
    road_pipe.ROAD_CUT_FILL_VEX,
)
terrain_domain.retarget_snap_consumers(hou, OBJ_PATH, snap_target)

# ── 2c. 建筑域：footprint chamfer ─────────────────────
bld_footprint_bevel = buildings_domain.build_footprint_bevel(hou, net, OBJ_PATH)

# ── 3. 验证全链路节点 ────────────────────────────────
print('\n[Houdini 4/7] 全链路验证')
CHECKS = [
    ('extract_buildings',    50,   None,  'buildings extracted from OSM'),
    ('snap_bld_to_terrain',  50,   None,  'buildings snapped to terrain'),
    ('bld_footprint_bevel',  50,   None,  'building footprints chamfered'),
    ('extrude_buildings',    50,   None,  'buildings extruded'),
    ('post_normals',         50,   None,  'normals computed'),
    ('road_api_raw_lines', 100, None, 'raw map API road lines generated'),
    ('road_api_shared_topology', 100, None, 'raw API road shared topology generated'),
    ('road_centerline_resample', 100, None, 'road centerline spacing normalized'),
    ('road_turn_curve_smooth', 100, None, 'road hard turns curve-smoothed'),
    ('road_vertex_cleanup', 100, None, 'road vertices cleaned and evenly spaced'),
    ('road_junction_curve_smooth', 100, None, 'road junctions curve-smoothed'),
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


bld_clip = buildings_domain.clip_buildings(remake_asset_filter)
road_clip = roads_domain.build_clipped_lines(
    hou,
    net,
    OBJ_PATH,
    _road_mesh_input,
    snap_target,
    road_pipe.ROAD_DRAPE_VEX,
    _road_output_mode,
    asset_filter_code,
    remake_asset_filter,
)
road_profile_src = roads_domain.apply_profiles(
    hou,
    net,
    OBJ_PATH,
    ROOT_STR,
    road_clip,
    _apply_road_profiles,
)
road_capsule_surface = roads_domain.build_capsule_surface_preview(
    hou,
    net,
    OBJ_PATH,
    road_profile_src,
    True,
)
road_curb_src = roads_domain.apply_curb_variation(
    hou,
    net,
    OBJ_PATH,
    ROOT_STR,
    road_profile_src,
    _apply_curb_variation,
)

foundation_clip = buildings_domain.build_foundation(
    hou,
    net,
    OBJ_PATH,
    bld_clip,
    snap_target,
    remake_asset_filter,
)

# ── 4c. 颜色节点（三类独立，来自 COLORS 配置）────────────────────────
road_colored = roads_domain.color_roads(hou, net, OBJ_PATH, road_curb_src, COLORS['roads'])
road_surface_colored = roads_domain.color_road_surface(hou, net, OBJ_PATH, road_capsule_surface, COLORS['roads'])
terrain_colored = terrain_domain.color_terrain(hou, net, OBJ_PATH, snap_target, COLORS['terrain'])
bld_final = buildings_domain.color_and_finalize_buildings(
    hou,
    net,
    OBJ_PATH,
    bld_clip,
    foundation_clip,
    COLORS['buildings'],
)

# ── 4d. 道路双轨输出────────────────────────────
# road_color 保留干净中心线 debug；最终 OUT_city 使用 capsule 道路面。
road_surface = roads_domain.finalize_surface(hou, OBJ_PATH, road_surface_colored or road_colored)

# ── 4e. promote_height / restore_height: method=First 防跨建筑高度污染 ─
# fuse_bld 焊接邻近建筑角点后，Average 模式会让相邻建筑高度互相稀释。
# 改用 First（method=1）保留任一原值，量级误差 1~3m → 0m。
buildings_domain.set_height_promote_restore_first(hou, OBJ_PATH)

# ── 4f. 死节点清理 ─────────────────────────────────────
_dead_nodes = [
    'bld_height_vary',       # 早期实验残留
    'dem_triangulate',       # 已被 dem_terrain 替代
    'dem_import',            # 仅喂 dem_triangulate（须在其后删）
    'dem_hf_import1',        # 孤立空节点
    '__tmp_subdivide',       # 临时残留
    'snap_roads_to_terrain', # 旧 Ray 实现，已被 _terrain1 替代
    'road_width',
    'road_width_flat',
    'road_vertical_smoother',
    'snap_roads_to_terrain1',
    'resample_roads',
    'road_shared_topology',
    'extract_roads',
    'road_centerline_filter',
    'laneforge_lane_surfaces',     # 旧 LaneForge 车道面实验残留
    'UnrealEngine_lane_surfaces',  # 旧 UE lane surface 实验残留
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
if merge and bld_clip and road_surface:
    merge.setInput(0, bld_final)
    merge.setInput(1, road_surface)
    merge.setInput(2, terrain_colored)

print('\n[Houdini 6/7] 刷新输出链并保存 HIP')
try:
    apply_domain_network_layout(hou, net, OBJ_PATH)
except Exception as _layout_exc:
    print('  [WARN] Houdini 网络分组失败: {}'.format(_layout_exc))
hou.hipFile.save()

# ── 5b. Hip 按区域存档 ────────────────────────────────
import shutil as _shutil, json as _json_arc
ARCHIVE_HIP = _ctx.archive_hip_path
if ARCHIVE_HIP != HIP:
    _shutil.copy2(HIP, ARCHIVE_HIP)
    print('  hip 存档: VC_{}_citygen_v001.hip'.format(_area_id))

# ── 6. 强制刷新整条输出链（视口同步）────────────────────
FULL_CHAIN = _ctx.output_refresh_chain()
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
