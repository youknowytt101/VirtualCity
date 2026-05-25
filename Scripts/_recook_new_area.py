"""
Houdini 换区重算脚本
====================
每次 set_area.py 换区后自动执行：
  1. 修复 dem_import / dem_terrain Python SOP（防止硬编码/sqrt 格网 bug）
  2. 强制 recook 数据源
  3. 验证全链路节点（几何非空 + 高度范围合理）
  4. 重建裁剪节点（基于新 DEM 边界）
  5. 重连 merge_all + 保存 hip
"""
import sys, rpyc, subprocess
from pathlib import Path
from vc_paths import ROOT, ACTIVE_AREA, HIP as MASTER_HIP, HOUDINI, load_active_area

PASS = '[OK]'
FAIL = '[FAIL]'
errors = []

# ── 前置：原始数据清洗（GeoJSON 几何/高度 + OSM 道路）──────────────
print('[数据清洗]')
_clean_result = subprocess.run(
    [sys.executable, str(ROOT / 'Scripts' / 'clean_raw_data.py'), '--report'],
    capture_output=True, text=True, encoding='utf-8', errors='replace'
)
for _line in _clean_result.stdout.splitlines():
    sys.stdout.buffer.write(('  ' + _line + '\n').encode('utf-8', errors='replace'))
if _clean_result.returncode != 0:
    print('  [WARN] clean_raw_data 退出码非 0，继续执行...')
    print(_clean_result.stderr[:400])

# ── 前置：OSM building:levels 高度补全 ─────────────────────────────
print('[heights] OSM building:levels enrichment...')
try:
    sys.path.insert(0, str(ROOT / 'Scripts'))
    from enrich_building_levels import enrich_levels as _enrich_levels
    _lvl_cfg = load_active_area()
    _lvl_stats = _enrich_levels(_lvl_cfg, verbose=False)
    print(f'  [heights] OSM levels matched: {_lvl_stats["updated"]} buildings updated')
except Exception as _e:
    print(f'  [WARN] enrich_building_levels failed: {_e}')

# ── 前置：DEM DSM -> DTM 修正（建筑掩码插值）────────────────────────
print('[dem] DTM correction (building mask)...')
try:
    from correct_dem_dtm import correct_dtm as _correct_dtm
    _dtm_cfg = load_active_area()
    _dtm_ok = _correct_dtm(_dtm_cfg, verbose=False)
    if _dtm_ok:
        print('  [dem] DTM correction applied')
    else:
        print('  [dem] DTM correction skipped (no cells masked)')
except Exception as _e:
    print(f'  [WARN] correct_dem_dtm failed: {_e}')

# ══════════════════════════════════════════
# 颜色配置 — 修改这里即可独立控制三类颜色
COLORS = {
    'roads':     (1.00, 1.00, 1.00),  # 道路：纯白
    'buildings': (0.55, 0.55, 0.55),  # 建筑：中灰
    'terrain':   (0.25, 0.25, 0.25),  # 地形：深灰
}
# ══════════════════════════════════════════

conn = rpyc.classic.connect('localhost', 18811)
hou  = conn.modules.hou
ROOT_STR = ROOT.as_posix()
CFG_FILE = ACTIVE_AREA.as_posix()

# ── 0. 确保 hip 已加载 ───────────────────────────────
HIP = MASTER_HIP.as_posix()
if 'untitled' in hou.hipFile.path():
    hou.hipFile.load(HIP, suppress_save_prompt=True)
    print('  hip 已加载: ' + HIP)
else:
    print('  hip: ' + hou.hipFile.path().split('/')[-1])

net = hou.node('/obj/pattaya_osm')

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
osm = hou.node('/obj/pattaya_osm/osm_import')
if osm and osm.parm('python'):
    osm.parm('python').set(_OSM_IMPORT_CODE)
    print('  SOP 修复: osm_import (canonical: single resolver + OSM bld fallback)')

# ── 1. 修复 dem_import Python SOP（H-006：硬编码路径）────
DEM_IMPORT_CODE = """
import hou, csv, json as _json
ROOT_DIR = r'__ROOT__'
CFG_FILE = r'__CFG__'
def _resolve_project_path(value):
    raw = str(value).replace(chr(92), '/')
    low = raw.lower()
    marker = '/virtualcity/'
    idx = low.find(marker)
    if idx >= 0:
        return ROOT_DIR + '/' + raw[idx + len(marker):]
    if low.endswith('/virtualcity'):
        return ROOT_DIR
    if ':' in raw[:3] or raw.startswith('/'):
        return raw
    return ROOT_DIR + '/' + raw
with open(CFG_FILE, encoding='utf-8') as _f:
    CSV_FILE = _resolve_project_path(_json.load(_f)['dem_csv'])
geo = hou.pwd().geometry()
with open(CSV_FILE, newline='') as f:
    for row in csv.DictReader(f):
        p = geo.createPoint()
        p.setPosition(hou.Vector3(float(row['x']), float(row['y']), float(row['z'])))
""".replace('__ROOT__', ROOT_STR).replace('__CFG__', CFG_FILE)

DEM_TERRAIN_CODE = """
import hou, csv, json as _json
ROOT_DIR = r'__ROOT__'
CFG_FILE = r'__CFG__'
def _resolve_project_path(value):
    raw = str(value).replace(chr(92), '/')
    low = raw.lower()
    marker = '/virtualcity/'
    idx = low.find(marker)
    if idx >= 0:
        return ROOT_DIR + '/' + raw[idx + len(marker):]
    if low.endswith('/virtualcity'):
        return ROOT_DIR
    if ':' in raw[:3] or raw.startswith('/'):
        return raw
    return ROOT_DIR + '/' + raw
with open(CFG_FILE, encoding='utf-8') as _f:
    CSV_FILE = _resolve_project_path(_json.load(_f)['dem_csv'])
geo = hou.pwd().geometry()
rows = []
with open(CSV_FILE, newline='') as f:
    for row in csv.DictReader(f):
        rows.append((float(row['x']), float(row['y']), float(row['z'])))
# H-005: 从坐标推断格网尺寸（不用 sqrt，支持非正方形）
xs    = sorted(set(round(r[0], 1) for r in rows))
zs    = sorted(set(round(r[2], 1) for r in rows))
ncols = len(xs)
nrows = len(zs)
pts   = []
for x, y, z in rows:
    p = geo.createPoint()
    p.setPosition(hou.Vector3(x, y, z))
    pts.append(p)
for ri in range(nrows - 1):
    for ci in range(ncols - 1):
        i0, i1 = ri * ncols + ci, ri * ncols + ci + 1
        i2, i3 = (ri + 1) * ncols + ci + 1, (ri + 1) * ncols + ci
        if max(i0, i1, i2, i3) < len(pts):
            poly = geo.createPolygon()
            for idx in [i0, i1, i2, i3]:
                poly.addVertex(pts[idx])
"""
DEM_TERRAIN_CODE = DEM_TERRAIN_CODE.replace('__ROOT__', ROOT_STR).replace('__CFG__', CFG_FILE)

for node_path, code in [
    ('/obj/pattaya_osm/dem_import',   DEM_IMPORT_CODE),
    ('/obj/pattaya_osm/dem_terrain',  DEM_TERRAIN_CODE),
]:
    n = hou.node(node_path)
    if n:
        n.parm('python').set(code)
        print('  SOP 修复: ' + node_path.split('/')[-1])

# ── 1a. 修复 divide_bld（Q-001：convex+numsides=3 强制三角化建筑 footprint）──
_div_bld = hou.node('/obj/pattaya_osm/divide_bld')
if _div_bld:
    _div_bld.parm('convex').set(0)
    _div_bld.parm('usemaxsides').set(0)
    print('  SOP 修复: divide_bld (Q-001: 关闭 convex+numsides → 保留 n-gon footprint)')

# ── 1b. 修复道路地形吸附（H-007：Ray SOP direction=0，改用 xyzdist）──
ROAD_SNAP_VEX = """
// 点级别：每个道路点独立吸附到最近地形
int hit_prim;
vector uvw;
xyzdist(1, @P, hit_prim, uvw);
vector terrain_pos = primuv(1, "P", hit_prim, uvw);
@P.y = terrain_pos.y;
"""
snap_old = hou.node('/obj/pattaya_osm/snap_roads_to_terrain1')
if snap_old and snap_old.type().name() == 'ray':
    road_w = hou.node('/obj/pattaya_osm/road_width')
    resample = hou.node('/obj/pattaya_osm/resample_roads')
    dem_t    = hou.node('/obj/pattaya_osm/dem_terrain')
    snap_old.destroy()
    snap_new = net.createNode('attribwrangle', 'snap_roads_to_terrain1')
    snap_new.setInput(0, resample)
    snap_new.setInput(1, dem_t)
    snap_new.parm('class').set(2)  # 2 = Point
    snap_new.parm('snippet').set(ROAD_SNAP_VEX)
    if road_w:
        road_w.setInput(0, snap_new)
    print('  SOP 修复: snap_roads_to_terrain1 (Ray→xyzdist attribwrangle)')
elif snap_old:
    snap_old.parm('class').set(2)
    snap_old.parm('snippet').set(ROAD_SNAP_VEX)
    print('  snap_roads_to_terrain1 class=2 + VEX 已校验更新')

# ── 1b2. 道路分级宽度（road_width attribwrangle）──────────────────────────
ROAD_WIDTH_VEX = """
string hw = s@highway;
float hw_val;
if      (hw == "motorway")                                    hw_val = 5.0;
else if (hw == "motorway_link")                               hw_val = 3.5;
else if (hw == "trunk")                                       hw_val = 4.5;
else if (hw == "trunk_link")                                  hw_val = 3.0;
else if (hw == "primary")                                     hw_val = 4.0;
else if (hw == "primary_link")                                hw_val = 2.5;
else if (hw == "secondary")                                   hw_val = 3.5;
else if (hw == "secondary_link")                              hw_val = 2.0;
else if (hw == "tertiary")                                    hw_val = 2.5;
else if (hw == "tertiary_link")                               hw_val = 1.5;
else if (hw == "residential" || hw == "living_street")        hw_val = 2.0;
else if (hw == "unclassified")                                hw_val = 2.0;
else if (hw == "service")                                     hw_val = 1.5;
else if (hw == "track")                                       hw_val = 1.5;
else if (hw == "pedestrian")                                  hw_val = 2.5;
else if (hw == "footway" || hw == "path" || hw == "bridleway") hw_val = 0.75;
else if (hw == "cycleway")                                    hw_val = 0.75;
else if (hw == "steps")                                       hw_val = 0.6;
else                                                          hw_val = 1.5;
f@half_width = hw_val;
"""
_rw = hou.node('/obj/pattaya_osm/road_width')
if _rw:
    _rw.parm('snippet').set(ROAD_WIDTH_VEX)
    _rw.parm('class').set(1)  # Primitive
    print('  road_width VEX 已更新（14 级分级宽度）')

# ── 1d. road_strips v2: 路段修剪 + 路口凸包填充 ──────────────────────
import pathlib as _pl
_rs_v2_path = ROOT / 'Scripts' / '_road_strips_v2.py'
_rs_v2_code = _rs_v2_path.read_text(encoding='utf-8')
_rs_node = hou.node('/obj/pattaya_osm/road_strips')
_rwf_node = hou.node('/obj/pattaya_osm/road_width_flat')
if _rs_node and _rwf_node:
    _rs_node.parm('python').set(_rs_v2_code)
    _rs_node.setInput(0, _rwf_node, 0)
    print('  road_strips v2 已更新（路口凸包填充）')
elif _rs_node:
    # road_width_flat 不存在时自动创建
    _rwf_node = hou.node('/obj/pattaya_osm').createNode('attribwrangle', 'road_width_flat')
    _rwf_node.setInput(0, hou.node('/obj/pattaya_osm/resample_roads'), 0)
    _rwf_node.parm('class').set(1)
    _rwf_node.parm('snippet').set(hou.node('/obj/pattaya_osm/road_width').parm('snippet').eval())
    _rs_node.parm('python').set(_rs_v2_code)
    _rs_node.setInput(0, _rwf_node, 0)
    print('  road_width_flat 已创建 + road_strips v2 已更新')

# ── 1c. 修复建筑地形吸附（H-011：坡面建筑底面埋入地形）──────────────
BLD_SNAP_VEX = """
// snap_bld_to_terrain v4: 逐角点查询 + 取最低值
// 对每个角点分别查询地形高度，取 MIN 作为底面 Y
// 斜坡建筑：低侧贴地，高侧嵌入地形（符合真实建筑行为，无悬空）
int verts[] = primvertices(0, @primnum);
int n = len(verts);
if (n == 0) return;

float min_terrain_y = 1e10;

foreach(int v; verts) {
    int pt = vertexpoint(0, v);
    vector p = point(0, "P", pt);

    // Step 1: query from Y=0 (finds terrain directly below for flat/coastal)
    int hp; vector uvw;
    xyzdist(1, set(p.x, 0.0, p.z), hp, uvw);
    vector tp = primuv(1, "P", hp, uvw);

    // Step 2: refine from Step1 Y (removes slope residual)
    xyzdist(1, set(p.x, tp.y, p.z), hp, uvw);
    tp = primuv(1, "P", hp, uvw);

    min_terrain_y = min(min_terrain_y, tp.y);
}

float base_y = min_terrain_y - 0.2;  // sink 0.2m to hide base gap

foreach(int v; verts) {
    int pt = vertexpoint(0, v);
    vector p = point(0, "P", pt);
    p.y = base_y;
    setpointattrib(0, "P", pt, p, "set");
}
"""
snap_bld = hou.node('/obj/pattaya_osm/snap_bld_to_terrain')
if snap_bld:
    snap_bld.parm('class').set(1)   # Primitive
    snap_bld.parm('snippet').set(BLD_SNAP_VEX)
    print('  SOP 修复: snap_bld_to_terrain (逐顶点 MAX 高度)')

# ── P0: procedural_height VEX —— 同时处理 height_m<=0 和 ~10m 两种缺失情况 ──
PROC_HEIGHT_VEX = r"""// P0: 推算高度的触发条件:
//   1. height_m ~= 10.0  -> OSM/Overture 默认值，没有真实数据
//   2. height_m <= 0      -> 明确缺失或数据错误
// 触发条件: ~10.0 (OSM default), ~8.0 (Overture DEFAULT_HEIGHT), <=0 (missing)
int needs_estimate = (abs(f@height_m - 10.0) < 0.1)
                  || (abs(f@height_m -  8.0) < 0.1)
                  || (f@height_m <= 0);
if (!needs_estimate) return;

int pts[] = primpoints(0, @primnum);
int n = len(pts);
float area = 0;
for (int i = 0; i < n; i++) {
    vector p0 = point(0, "P", pts[i]);
    vector p1 = point(0, "P", pts[(i+1)%n]);
    area += p0.x * p1.z - p1.x * p0.z;
}
area = abs(area) * 0.5;

float base_floors;
if      (area < 60)   base_floors = 1;
else if (area < 150)  base_floors = 2;
else if (area < 400)  base_floors = 3;
else if (area < 1000) base_floors = 4;
else if (area < 3000) base_floors = 6;
else                  base_floors = 8;

vector ctr = {0,0,0};
for (int i = 0; i < n; i++) ctr += point(0,"P",pts[i]);
ctr /= n;
float noise_val = fit(noise(ctr * 0.003), 0, 1, -1.5, 1.5);
float floors = clamp(base_floors + noise_val, 1, 15);
f@height_m = floors * 3.5;
"""
_ph = hou.node('/obj/pattaya_osm/procedural_height')
if _ph:
    _ph.parm('snippet').set(PROC_HEIGHT_VEX)
    print('  SOP 修复: procedural_height (P0: height_m<=0 fallback)')

# ── 2. 强制 recook 数据源 ────────────────────────────
print('\n[recook 数据源]')
for path in ['/obj/pattaya_osm/osm_import', '/obj/pattaya_osm/dem_import',
             '/obj/pattaya_osm/dem_terrain']:
    n = hou.node(path)
    if not n:
        continue
    n.cook(force=True)
    geo  = n.geometry()
    pts  = geo.intrinsicValue('pointcount')
    prm  = geo.intrinsicValue('primitivecount')
    print('  {:<20s} pts={:6d}  prims={:6d}'.format(n.name(), pts, prm))
    if pts == 0:
        errors.append(n.name() + ' geometry empty after recook')

# ── 2b. 地形加密（Subdivide Bilinear × 2）───────────────────────────
old_subdiv = hou.node('/obj/pattaya_osm/dem_subdivide')
if old_subdiv:
    old_subdiv.destroy()
dem_subdiv = net.createNode('subdivide', 'dem_subdivide')
dem_subdiv.setInput(0, hou.node('/obj/pattaya_osm/dem_terrain'))
dem_subdiv.parm('algorithm').set(4)   # 4 = OpenSubdiv Bilinear（线性插值，不改变已有高程）
dem_subdiv.parm('iterations').set(2)  # 2轮细分 = ×16 面片密度（30m→~7.5m等效）
dem_subdiv.cook(force=True)
_sd_geo  = dem_subdiv.geometry()
_sd_pts  = _sd_geo.intrinsicValue('pointcount')
_sd_prms = _sd_geo.intrinsicValue('primitivecount')
print('  dem_subdivide: pts={} prims={} (原 {} 面片 → 加密 ×16)'.format(
    _sd_pts, _sd_prms, _sd_prms // 16))

# 更新吸附节点 input1 → dem_subdivide（更密地形 = 更精确贴合）
for _sn_name in ['snap_bld_to_terrain', 'snap_roads_to_terrain1']:
    _sn = hou.node('/obj/pattaya_osm/' + _sn_name)
    if _sn:
        _sn.setInput(1, dem_subdiv)

# ── 3. 验证全链路节点 ────────────────────────────────
print('\n[全链路验证]')
CHECKS = [
    ('extract_buildings',    50,   None,  'buildings extracted from OSM'),
    ('snap_bld_to_terrain',  50,   None,  'buildings snapped to terrain'),
    ('extrude_buildings',    50,   None,  'buildings extruded'),
    ('post_normals',         50,   None,  'normals computed'),
    ('road_strips',          100,  None,  'roads generated'),
]
for name, min_pts, max_y, desc in CHECKS:
    n = hou.node('/obj/pattaya_osm/' + name)
    if not n:
        print('  SKIP  {:<22s} (node not found)'.format(name))
        continue
    n.cook(force=False)
    geo  = n.geometry()
    pts  = geo.intrinsicValue('pointcount')
    bb   = geo.boundingBox()
    mn_y = bb.minvec()[1]
    mx_y = bb.maxvec()[1]
    ok   = pts >= min_pts
    tag  = PASS if ok else FAIL
    print('  {}  {:<22s} pts={:6d}  Y[{:.1f}~{:.1f}]  {}'.format(
        tag, name, pts, mn_y, mx_y, desc))
    if not ok:
        errors.append('{} pts={} < {}'.format(name, pts, min_pts))

# ── 4. 重建裁剪节点 ──────────────────────────────────
print('\n[裁剪节点重建]')
dem = hou.node('/obj/pattaya_osm/dem_terrain')
dem.cook(force=False)
bb  = dem.geometry().boundingBox()
mn, mx = bb.minvec(), bb.maxvec()
MARGIN = 50
XMIN = mn[0] - MARGIN
XMAX = mx[0] + MARGIN
ZMIN = mn[2] - MARGIN
ZMAX = mx[2] + MARGIN
print('  DEM 边界: X[{:.0f}~{:.0f}] Z[{:.0f}~{:.0f}]'.format(XMIN, XMAX, ZMIN, ZMAX))

VEX = (  # noqa: E741
    'int ps[] = primpoints(0, @primnum);\n'
    'int n = len(ps);\n'
    'if (n == 0) { i@del = 1; return; }\n'
    'vector sum = {0,0,0};\n'
    'for(int i=0; i<n; i++) sum += point(0,"P",ps[i]);\n'
    'vector c = sum / n;\n'
    'i@del = (c.x < XMIN || c.x > XMAX || c.z < ZMIN || c.z > ZMAX) ? 1 : 0;\n'
).replace('XMIN', str(XMIN)).replace('XMAX', str(XMAX)) \
 .replace('ZMIN', str(ZMIN)).replace('ZMAX', str(ZMAX))


def remake_clip(src_name, mark_name, out_name):
    for nm in [out_name, mark_name]:
        old = hou.node('/obj/pattaya_osm/' + nm)
        if old:
            old.destroy()
    src = hou.node('/obj/pattaya_osm/' + src_name)
    if not src:
        errors.append('source node not found: ' + src_name)
        return None
    w = net.createNode('attribwrangle', mark_name)
    w.setInput(0, src)
    w.parm('class').set(1)
    w.parm('snippet').set(VEX)
    b = net.createNode('blast', out_name)
    b.setInput(0, w)
    b.parm('group').set('@del==1')
    b.parm('grouptype').set(4)
    b.parm('negate').set(0)
    b.cook(force=True)
    geo  = b.geometry()
    pts  = geo.intrinsicValue('pointcount')
    bb2  = geo.boundingBox()
    tag  = PASS if pts > 0 else FAIL
    print('  {}  {:<20s} pts={:6d}  Y[{:.1f}~{:.1f}]'.format(
        tag, out_name, pts, bb2.minvec()[1], bb2.maxvec()[1]))
    if pts == 0:
        errors.append(out_name + ' empty after clip')
    return b


# ── 4b. road_strips 二次地形吸附（修复侧边点埋入地形）────────────────
ROAD_DRAPE_VEX = """
// 对每个道路条带顶点重新吸附到地形，防止宽度扩展后侧边点埋入坡面
int hit_prim;
vector uvw;
xyzdist(1, @P, hit_prim, uvw);
vector tp = primuv(1, "P", hit_prim, uvw);
@P.y = max(tp.y, 0.0) + 0.15;  // 浮起 0.15m，且不低于海平面(Y=0)
"""
old_drape = hou.node('/obj/pattaya_osm/snap_road_strips')
if old_drape:
    old_drape.destroy()
road_strips_node = hou.node('/obj/pattaya_osm/road_strips')
snap_road_strips = net.createNode('attribwrangle', 'snap_road_strips')
snap_road_strips.setInput(0, road_strips_node)
snap_road_strips.setInput(1, dem_subdiv)
snap_road_strips.parm('class').set(2)   # Point
snap_road_strips.parm('snippet').set(ROAD_DRAPE_VEX)
snap_road_strips.cook(force=True)
_rs_geo  = snap_road_strips.geometry()
_rs_pts  = _rs_geo.intrinsicValue('pointcount')
_rs_bb   = _rs_geo.boundingBox()
_rs_ymin = _rs_bb.minvec()[1]
print('  snap_road_strips: pts={} Y_min={:.2f}m'.format(_rs_pts, _rs_ymin))

bld_clip  = remake_clip('post_normals',    'bld_clip_mark',  'bld_clipped')
road_clip = remake_clip('snap_road_strips','road_clip_mark', 'road_clipped')

# ── 4c. 颜色节点（三类独立，来自 COLORS 配置）────────────────────────
def make_color_node(name, src_node, rgb):
    old = hou.node('/obj/pattaya_osm/' + name)
    if old: old.destroy()
    w = net.createNode('attribwrangle', name)
    w.setInput(0, src_node)
    w.parm('class').set(2)  # Point
    w.parm('snippet').set('@Cd = set({:.4f}, {:.4f}, {:.4f});'.format(*rgb))
    w.cook(force=True)
    return w

_dem_sd = hou.node('/obj/pattaya_osm/dem_subdivide') or hou.node('/obj/pattaya_osm/dem_terrain')
road_colored    = make_color_node('road_color',    road_clip, COLORS['roads'])
bld_colored     = make_color_node('bld_color',     bld_clip,  COLORS['buildings'])
terrain_colored = make_color_node('terrain_color', _dem_sd,   COLORS['terrain'])

# ── 4d. 道路挤出（road_extrude：0.18m 侧面 + 顶面）────────────────────
old_ext = hou.node('/obj/pattaya_osm/road_extrude')
if old_ext:
    old_ext.destroy()
road_extrude = net.createNode('polyextrude::2.0', 'road_extrude')
road_extrude.setInput(0, road_colored)
road_extrude.parm('dist').set(0.18)
road_extrude.parm('outputback').set(0)
road_extrude.parm('outputfront').set(1)
road_extrude.parm('outputside').set(1)
road_extrude.parm('xformspace').set(0)  # Local (along prim normal)
road_extrude.cook(force=True)
print('  road_extrude: pts={} prims={}'.format(
    road_extrude.geometry().intrinsicValue('pointcount'),
    road_extrude.geometry().intrinsicValue('primitivecount')))

# ── 5. 重连 merge_all + 保存 ────────────────────────
merge = hou.node('/obj/pattaya_osm/merge_all')
if merge and bld_clip and road_clip:
    merge.setInput(0, bld_colored)
    merge.setInput(1, road_extrude)
    merge.setInput(2, terrain_colored)

net.layoutChildren()
hou.hipFile.save()

# ── 5b. Hip 按区域存档 ────────────────────────────────
import shutil as _shutil, json as _json_arc
_area_id = load_active_area(absolute=False)['area_id']
ARCHIVE_HIP = (HOUDINI / 'Hip' / 'VC_{}_citygen_v001.hip'.format(_area_id)).as_posix()
if ARCHIVE_HIP != HIP:
    _shutil.copy2(HIP, ARCHIVE_HIP)
    print('  hip 存档: VC_{}_citygen_v001.hip'.format(_area_id))

# ── 6. 强制刷新整条输出链（视口同步）────────────────────
FULL_CHAIN = [
    'osm_import', 'dem_terrain',
    'extract_buildings', 'snap_bld_to_terrain', 'extrude_buildings', 'post_normals',
    'snap_roads_to_terrain1', 'road_width', 'road_strips',
    'bld_clipped', 'road_clipped', 'road_color', 'road_extrude', 'bld_color', 'terrain_color', 'merge_all', 'OUT_city',
]
for _cn in FULL_CHAIN:
    _n = hou.node('/obj/pattaya_osm/' + _cn)
    if _n:
        _n.cook(force=True)
_out = hou.node('/obj/pattaya_osm/OUT_city')
if _out:
    _out.setDisplayFlag(True)
    _out.setRenderFlag(True)
print('  [OK] 视口链已强制刷新')

# ── 结果汇报 ─────────────────────────────────────────
print()
if errors:
    print('[FAIL] 发现 {} 个错误:'.format(len(errors)))
    for e in errors:
        print('  - ' + e)
    sys.exit(1)
else:
    print('[OK] 全部通过，hip 已保存')
    print('     请在 Houdini 视口选中 OUT_city 按 D 确认效果')

conn.close()
