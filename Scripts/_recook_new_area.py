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
import sys, rpyc, subprocess, json, time
from pathlib import Path
import houdini_road_pipeline as road_pipe
from vc_paths import ROOT, ACTIVE_AREA, HIP as MASTER_HIP, HOUDINI, load_active_area, project_relative

PASS = '[OK]'
FAIL = '[FAIL]'
errors = []


def _write_build_status(area_id, status, hip_path=None, message='', qa_status='', qa_report=''):
    status_file = ROOT / 'Config' / 'houdini_build_status.json'
    payload = {
        'area_id': area_id,
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
    with open(status_file, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write('\n')

# ── 前置：数据精炼（由 refine_data.py 统一处理）──────────────────────
# 如果从 set_area.py 调用，refine_data.py 已提前运行完毕。
# 如果直接调用本脚本，检查 _houdini_ready 是否已有数据：
_hr_dir = ROOT / 'RawData' / '_houdini_ready' / load_active_area(absolute=False).get('area_id', '')
if not _hr_dir.exists() or not any(_hr_dir.iterdir()):
    print('[数据精炼] _houdini_ready 为空，运行 refine_data.py...')
    _refine_result = subprocess.run(
        [sys.executable, str(ROOT / 'Scripts' / 'refine_data.py'), '--skip-probe'],
        capture_output=False, cwd=str(ROOT / 'Scripts')
    )
    if _refine_result.returncode != 0:
        print('  [WARN] refine_data.py 退出码非 0，继续执行...')
else:
    print('[数据精炼] _houdini_ready 已就绪，跳过')

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
_cfg = load_active_area()
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
DEM_IMPORT_CODE = """
import hou, csv, json as _json, os
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
    _cfg = _json.load(_f)
    _ready = ROOT_DIR + '/RawData/_houdini_ready/' + _cfg.get('area_id', '') + '/dem.csv'
    CSV_FILE = _ready if os.path.exists(_ready) else _resolve_project_path(_cfg['dem_csv'])
geo = hou.pwd().geometry()
with open(CSV_FILE, newline='') as f:
    for row in csv.DictReader(f):
        p = geo.createPoint()
        p.setPosition(hou.Vector3(float(row['x']), float(row['y']), float(row['z'])))
""".replace('__ROOT__', ROOT_STR).replace('__CFG__', CFG_FILE)

DEM_TERRAIN_CODE = """
import hou, csv, json as _json, os
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
    _cfg = _json.load(_f)
    _ready = ROOT_DIR + '/RawData/_houdini_ready/' + _cfg.get('area_id', '') + '/dem.csv'
    CSV_FILE = _ready if os.path.exists(_ready) else _resolve_project_path(_cfg['dem_csv'])
geo = hou.pwd().geometry()
rows = []
with open(CSV_FILE, newline='') as f:
    for row in csv.DictReader(f):
        rows.append((float(row['x']), float(row['y']), float(row['z']),
                     int(row.get('row', 0)), int(row.get('col', 0))))
# H-005: 用 CSV 的 row/col 列直接构建网格（兼容 UTM 投影坐标）
grid = {}
for row in rows:
    x, y, z = row[0], row[1], row[2]
    ri, ci  = int(row[3]), int(row[4])
    p = geo.createPoint()
    p.setPosition(hou.Vector3(x, y, z))
    grid[(ri, ci)] = p
all_ri = sorted(set(k[0] for k in grid))
all_ci = sorted(set(k[1] for k in grid))
for i in range(len(all_ri) - 1):
    for j in range(len(all_ci) - 1):
        r0, r1 = all_ri[i], all_ri[i+1]
        c0, c1 = all_ci[j], all_ci[j+1]
        corners = [grid.get((r0,c0)), grid.get((r0,c1)),
                   grid.get((r1,c1)), grid.get((r1,c0))]
        if all(corners):
            poly = geo.createPolygon()
            for pt in corners:
                poly.addVertex(pt)
"""
DEM_TERRAIN_CODE = DEM_TERRAIN_CODE.replace('__ROOT__', ROOT_STR).replace('__CFG__', CFG_FILE)

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
if snap_old and snap_old.type().name() == 'ray':
    road_w = hou.node(OBJ_PATH + '/road_width')
    resample = hou.node(OBJ_PATH + '/resample_roads')
    dem_t    = hou.node(OBJ_PATH + '/dem_terrain')
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
ROAD_WIDTH_VEX = road_pipe.ROAD_WIDTH_VEX
# road_width_flat 是真正喂入 road_strips 的节点，直接写 ROAD_WIDTH_VEX
# （旧版 road_width 节点已 deprecated，统一在 cleanup 段删除）
_rwf_node = hou.node(OBJ_PATH + '/road_width_flat')
_road_width_input = hou.node(OBJ_PATH + '/snap_roads_to_terrain1') or hou.node(OBJ_PATH + '/resample_roads')
if _rwf_node is None:
    _rwf_node = net.createNode('attribwrangle', 'road_width_flat')
if _road_width_input:
    # Always repair the input. Existing HIPs may preserve a stale/miswired input,
    # and this node must consume terrain-snapped centerlines, not raw resample_roads.
    _rwf_node.setInput(0, _road_width_input, 0)
_rwf_node.parm('class').set(1)  # Primitive
_rwf_node.parm('snippet').set(ROAD_WIDTH_VEX)
print('  road_width_flat VEX + 输入已更新（snap_roads_to_terrain1 → road_width_flat）')

# ── 1d. road_strips v2: 路段修剪 + 路口凸包填充 ──────────────────────
_rs_v2_code = road_pipe.load_road_strips_code(ROOT)
_rs_node = hou.node(OBJ_PATH + '/road_strips')
if _rs_node:
    _rs_node.parm('python').set(_rs_v2_code)
    _rs_node.setInput(0, _rwf_node, 0)
    print('  road_strips v4 已更新（调试属性 + 自交保护 + 凸包填充）')

# ── 1c. 修复建筑地形吸附（H-011：坡面建筑底面埋入地形）──────────────
BLD_SNAP_VEX = """
// snap_bld_to_terrain v6: XZ 垂直采样地形 + 逐角点取最高值
// 3D 最近点在山地会吸到旁边低坡，导致建筑局部埋地；必须垂直射线取高。
// 坡面建筑：底面保持水平，略高于最高地形点；下坡侧由 bld_foundation 补裙边。
int verts[] = primvertices(0, @primnum);
int n = len(verts);
if (n == 0) return;

float max_terrain_y = -1e10;

foreach(int v; verts) {
    int pt = vertexpoint(0, v);
    vector p = point(0, "P", pt);

    vector hitp;
    vector uvw;
    int hp = intersect(1, set(p.x, 10000.0, p.z), set(0.0, -20000.0, 0.0), hitp, uvw);
    if (hp >= 0) {
        max_terrain_y = max(max_terrain_y, hitp.y);
    } else {
        int near_prim;
        vector near_uvw;
        xyzdist(1, set(p.x, p.y, p.z), near_prim, near_uvw);
        vector tp = primuv(1, "P", near_prim, near_uvw);
        max_terrain_y = max(max_terrain_y, tp.y);
    }
}

float base_y = max_terrain_y + 0.05;  // keep the flat base above terrain; skirt hides downhill gap

foreach(int v; verts) {
    int pt = vertexpoint(0, v);
    vector p = point(0, "P", pt);
    p.y = base_y;
    setpointattrib(0, "P", pt, p, "set");
}
"""
snap_bld = hou.node(OBJ_PATH + '/snap_bld_to_terrain')
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

// 精度审核 #5：按建筑类型差异化层高（泰国实测参考值）
// Overture subtype/class 实际取值远多于 3 类，按家族归并：
string cls = s@bld_class;
float floor_h;
// — 住宅类（泰国实测 2.8~3.0m/层）—
if      (cls == "residential")   floor_h = 2.9;
else if (cls == "apartments")    floor_h = 2.9;
else if (cls == "house")         floor_h = 2.9;
else if (cls == "terrace")       floor_h = 2.9;
else if (cls == "dormitory")     floor_h = 2.9;
// — 商业 / 服务类（3.3~3.8m/层）—
else if (cls == "commercial")    floor_h = 3.5;
else if (cls == "retail")        floor_h = 3.5;
else if (cls == "office")        floor_h = 3.5;
else if (cls == "hotel")         floor_h = 3.4;
else if (cls == "hospital")      floor_h = 3.6;
else if (cls == "school" ||
         cls == "education")     floor_h = 3.5;
else if (cls == "civic" ||
         cls == "government" ||
         cls == "public")        floor_h = 3.6;
// — 工业 / 仓储（4.0~5.0m/层）—
else if (cls == "industrial")    floor_h = 4.5;
else if (cls == "warehouse")     floor_h = 4.5;
// — 低矮辅助结构（车棚 / 屋顶部件，强制 1 层）—
else if (cls == "carport" ||
         cls == "garage" ||
         cls == "shed" ||
         cls == "roof")          { floor_h = 2.5; floors = 1; }
// — 未识别（"building" 兜底或异类）按面积启发 —
else {
    if      (area > 2000) floor_h = 4.5;   // 工业级 footprint
    else if (area > 500)  floor_h = 3.5;   // 商业级
    else                  floor_h = 2.9;   // 住宅级（Pattaya 主流）
}

f@height_m = floors * floor_h;
"""
_ph = hou.node(OBJ_PATH + '/procedural_height')
if _ph:
    _ph.parm('snippet').set(PROC_HEIGHT_VEX)
    print('  SOP 修复: procedural_height (P0: height_m<=0 fallback)')

# ── 2. 强制 recook 数据源 ────────────────────────────
print('\n[recook 数据源]')
for path in [OBJ_PATH + '/osm_import', OBJ_PATH + '/dem_import',
             OBJ_PATH + '/dem_terrain']:
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

# ── 2b. 地形 snap target = dem_subdivide ──────────────────────────────
# DEM 原始约 30m 网格，在山地俯视角布线过稀。Bilinear×2 只做线性插值，
# 不增加真实高程精度，但能把显示和道路贴地目标提升到约 7.5m 网格。
dem_terrain = hou.node(OBJ_PATH + '/dem_terrain')
snap_target = hou.node(OBJ_PATH + '/dem_subdivide')
if snap_target is None:
    snap_target = net.createNode('subdivide', 'dem_subdivide')
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
BLD_FOOTPRINT_BEVEL_CODE = r"""
import hou, math

BEVEL_DIST = 0.60
MAX_ANGLE_DEG = 100.0
ANGLE_EPS_DEG = 2.0
MAX_EDGE_FRACTION = 0.25
MIN_CUT = 0.08
MIN_EDGE_LEN = 0.35

src_geo = hou.pwd().inputs()[0].geometry()
geo = hou.pwd().geometry()
geo.clear()

prim_attribs = []
for attrib in src_geo.primAttribs():
    if attrib.name() == "P":
        continue
    try:
        new_attrib = geo.addAttrib(hou.attribType.Prim, attrib.name(), attrib.defaultValue())
        prim_attribs.append((attrib, new_attrib))
    except Exception:
        pass

bevel_a = geo.addAttrib(hou.attribType.Prim, "footprint_bevel_count", 0)

def v2(p):
    return (float(p.x()), float(p.z()))

def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])

def add(a, b):
    return (a[0] + b[0], a[1] + b[1])

def mul(a, s):
    return (a[0] * s, a[1] * s)

def length(a):
    return math.sqrt(a[0] * a[0] + a[1] * a[1])

def norm(a):
    l = length(a)
    if l <= 1e-9:
        return (0.0, 0.0)
    return (a[0] / l, a[1] / l)

def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]

def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]

def signed_area(points):
    acc = 0.0
    n = len(points)
    for i, p in enumerate(points):
        q = points[(i + 1) % n]
        acc += p[0] * q[1] - q[0] * p[1]
    return acc * 0.5

def angle_deg(prev_p, curr_p, next_p):
    a = norm(sub(prev_p, curr_p))
    b = norm(sub(next_p, curr_p))
    d = max(-1.0, min(1.0, dot(a, b)))
    return math.degrees(math.acos(d))

def make_point(xz, y):
    pt = geo.createPoint()
    pt.setPosition(hou.Vector3(xz[0], y, xz[1]))
    return pt

for prim in src_geo.prims():
    try:
        if not prim.isClosed():
            continue
    except Exception:
        pass

    verts = list(prim.vertices())
    if len(verts) < 3:
        continue

    src_positions = [v.point().position() for v in verts]
    points = [v2(p) for p in src_positions]
    base_y = sum(p.y() for p in src_positions) / len(src_positions)
    area = signed_area(points)
    if abs(area) <= 1e-6:
        continue
    orient = 1.0 if area > 0.0 else -1.0

    new_points = []
    bevel_count = 0
    n = len(points)
    for i, curr in enumerate(points):
        prev_p = points[(i - 1) % n]
        next_p = points[(i + 1) % n]
        prev_edge = sub(curr, prev_p)
        next_edge = sub(next_p, curr)
        prev_len = length(prev_edge)
        next_len = length(next_edge)
        turn = cross(prev_edge, next_edge)
        convex = turn * orient > 1e-8
        ang = angle_deg(prev_p, curr, next_p)

        can_bevel = (
            convex
            and ang <= MAX_ANGLE_DEG + ANGLE_EPS_DEG
            and prev_len >= MIN_EDGE_LEN
            and next_len >= MIN_EDGE_LEN
        )

        if not can_bevel:
            new_points.append(curr)
            continue

        cut = min(
            BEVEL_DIST,
            prev_len * MAX_EDGE_FRACTION,
            next_len * MAX_EDGE_FRACTION,
        )
        if cut < MIN_CUT:
            new_points.append(curr)
            continue

        into_prev = norm(sub(prev_p, curr))
        into_next = norm(sub(next_p, curr))
        new_points.append(add(curr, mul(into_prev, cut)))
        new_points.append(add(curr, mul(into_next, cut)))
        bevel_count += 1

    if len(new_points) < 3:
        continue

    new_prim = geo.createPolygon()
    for p in new_points:
        new_prim.addVertex(make_point(p, base_y))
    for src_attr, dst_attr in prim_attribs:
        try:
            new_prim.setAttribValue(dst_attr, prim.attribValue(src_attr))
        except Exception:
            pass
    new_prim.setAttribValue(bevel_a, bevel_count)
"""

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
print('\n[全链路验证]')
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
print('\n[裁剪节点重建]')
dem = snap_target
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
        old = hou.node(OBJ_PATH + '/' + nm)
        if old:
            old.destroy()
    src = hou.node(OBJ_PATH + '/' + src_name)
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
ROAD_DRAPE_VEX = road_pipe.ROAD_DRAPE_VEX
old_drape = hou.node(OBJ_PATH + '/snap_road_strips')
if old_drape:
    old_drape.destroy()
road_strips_node = hou.node(OBJ_PATH + '/road_strips')
snap_road_strips = net.createNode('attribwrangle', 'snap_road_strips')
snap_road_strips.setInput(0, road_strips_node)
snap_road_strips.setInput(1, snap_target)
snap_road_strips.parm('class').set(2)   # Point
snap_road_strips.parm('snippet').set(ROAD_DRAPE_VEX)
snap_road_strips.cook(force=True)
_rs_geo  = snap_road_strips.geometry()
_rs_pts  = _rs_geo.intrinsicValue('pointcount')
_rs_bb   = _rs_geo.boundingBox()
_rs_ymin = _rs_bb.minvec()[1]
print('  snap_road_strips: pts={} Y_min={:.2f}m'.format(_rs_pts, _rs_ymin))

# ── 4b2. 道路几何级 bbox 裁剪（不再只按 primitive 中心点删除）──────────────
ROAD_BBOX_CLIP_CODE = road_pipe.road_bbox_clip_code(XMIN, XMAX, ZMIN, ZMAX)

old_bbox_clip = hou.node(OBJ_PATH + '/road_bbox_clip')
if old_bbox_clip:
    old_bbox_clip.destroy()
road_bbox_clip = net.createNode('python', 'road_bbox_clip')
road_bbox_clip.setInput(0, snap_road_strips)
road_bbox_clip.parm('python').set(ROAD_BBOX_CLIP_CODE)
road_bbox_clip.cook(force=True)
print('  road_bbox_clip: pts={} prims={}'.format(
    road_bbox_clip.geometry().intrinsicValue('pointcount'),
    road_bbox_clip.geometry().intrinsicValue('primitivecount')))

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

bld_clip  = remake_clip('post_normals',    'bld_clip_mark',  'bld_clipped')
road_clip = remake_clip('snap_road_clipped','road_clip_mark', 'road_clipped')

# ── 4b3. 建筑地基 / 裙边（坡地建筑下坡侧补空）──────────────────────
BUILDING_FOUNDATION_CODE = r"""
import hou

MIN_DEPTH = 0.12
MAX_DEPTH = 25.0
TERRAIN_EPS = 0.03
SIDE_NORMAL_Y = 0.20
BOTTOM_Y_TOL = 0.01

# Input 0 must be the final building body, not an earlier footprint.
# The skirt top edge is copied from each actual wall bottom edge, so it cannot
# drift after fuse/divide/clip changes upstream.
body_geo = hou.pwd().inputs()[0].geometry()
terrain_geo = hou.pwd().inputs()[1].geometry()
geo = hou.pwd().geometry()
geo.clear()

is_foundation_a = geo.addAttrib(hou.attribType.Prim, "is_foundation", 0)

def terrain_y_at(x, z):
    pos = hou.Vector3()
    normal = hou.Vector3()
    uvw = hou.Vector3()
    hit = terrain_geo.intersect(
        hou.Vector3(x, 10000.0, z),
        hou.Vector3(0.0, -1.0, 0.0),
        pos,
        normal,
        uvw,
        min_hit=0.01,
        max_hit=20000.0,
        tolerance=0.01,
    )
    if hit >= 0:
        return pos.y()
    return None

def add_quad(a, b, c, d):
    pts = []
    for p in (a, b, c, d):
        pt = geo.createPoint()
        pt.setPosition(p)
        pts.append(pt)

    def make(order):
        prim = geo.createPolygon()
        for idx in order:
            prim.addVertex(pts[idx])
        prim.setAttribValue(is_foundation_a, 1)
        return prim

    prim = make([0, 1, 2, 3])
    return prim

def add_oriented_quad(top_a, top_b, bot_b, bot_a, ref_normal):
    prim = add_quad(top_a, top_b, bot_b, bot_a)
    if prim.normal().dot(ref_normal) >= 0:
        return prim
    pts = [v.point() for v in prim.vertices()]
    geo.deletePrims([prim], True)
    flipped = geo.createPolygon()
    for idx in (3, 2, 1, 0):
        flipped.addVertex(pts[idx])
    flipped.setAttribValue(is_foundation_a, 1)
    return flipped

def bottom_y_for(p):
    ty = terrain_y_at(p.x(), p.z())
    if ty is None:
        return p.y()
    bottom_y = min(ty + TERRAIN_EPS, p.y())
    if p.y() - bottom_y > MAX_DEPTH:
        bottom_y = p.y() - MAX_DEPTH
    return bottom_y

for prim in body_geo.prims():
    verts = list(prim.vertices())
    if len(verts) < 3:
        continue
    n = prim.normal()
    if abs(n.y()) > SIDE_NORMAL_Y:
        continue

    positions = [v.point().position() for v in verts]
    min_y = min(p.y() for p in positions)
    bottom_indices = [i for i, p in enumerate(positions) if abs(p.y() - min_y) <= BOTTOM_Y_TOL]
    if len(bottom_indices) < 2:
        continue

    bottom_positions = [positions[i] for i in bottom_indices]
    for i in range(len(bottom_positions) - 1):
        top_a = bottom_positions[i]
        top_b = bottom_positions[i + 1]
        bot_a = hou.Vector3(top_a.x(), bottom_y_for(top_a), top_a.z())
        bot_b = hou.Vector3(top_b.x(), bottom_y_for(top_b), top_b.z())
        if max(top_a.y() - bot_a.y(), top_b.y() - bot_b.y()) < MIN_DEPTH:
            continue
        add_oriented_quad(top_a, top_b, bot_b, bot_a, n)
"""

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

foundation_clip = remake_clip('bld_foundation', 'bld_foundation_clip_mark', 'bld_foundation_clipped')

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

road_colored    = make_color_node('road_color',    road_clip,   COLORS['roads'])
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

# ── 4d. 道路挤出（road_extrude：0.18m 侧面 + 顶面）────────────────────
old_ext = hou.node(OBJ_PATH + '/road_extrude')
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
    'osm_import', 'dem_terrain', 'dem_subdivide',
    'extract_buildings', 'snap_bld_to_terrain', 'bld_footprint_bevel', 'extrude_buildings', 'post_normals',
    'snap_roads_to_terrain1', 'road_width_flat', 'road_strips',
    'snap_road_strips', 'road_bbox_clip', 'snap_road_clipped',
    'bld_clipped', 'bld_foundation', 'bld_foundation_clipped',
    'road_clipped', 'road_color', 'road_extrude',
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
    print('\n[Model QA]')
    _qa_cmd = [sys.executable, str(ROOT / 'Scripts' / 'houdini_model_qa.py'), '--mode', 'quick']
    _qa_result = subprocess.run(_qa_cmd, cwd=str(ROOT), capture_output=False)
    _qa_latest = ROOT / 'Reports' / 'model_qa' / 'latest.json'
    if _qa_latest.exists():
        qa_report = project_relative(_qa_latest)
        try:
            with open(_qa_latest, encoding='utf-8') as _f:
                qa_status = json.load(_f).get('status', '')
        except Exception as _exc:
            qa_status = 'unreadable'
            print('  [WARN] Model QA report unreadable: {}'.format(_exc))
    if _qa_result.returncode != 0:
        errors.append('model QA failed (see {})'.format(qa_report or 'Reports/model_qa/latest.json'))

# ── 结果汇报 ─────────────────────────────────────────
print()
if errors:
    print('[FAIL] 发现 {} 个错误:'.format(len(errors)))
    for e in errors:
        print('  - ' + e)
    _write_build_status(_area_id, 'failed', ARCHIVE_HIP, '; '.join(errors), qa_status, qa_report)
    sys.exit(1)
else:
    _msg = 'Houdini build completed'
    if qa_status:
        _msg += '; model QA quick {}'.format(qa_status)
    _write_build_status(_area_id, 'completed', ARCHIVE_HIP, _msg, qa_status, qa_report)
    print('[OK] 全部通过，hip 已保存')
    print('     Houdini 构建完成标记: Config/houdini_build_status.json')
    print('     请在 Houdini 视口选中 OUT_city 按 D 确认效果')

if conn:
    conn.close()
