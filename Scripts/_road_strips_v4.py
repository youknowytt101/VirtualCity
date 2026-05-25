"""
road_strips v4 — 路段 quad + 路口局部 Shapely union
=====================================================
输入 0: road_width_flat (resample + half_width, Y=0)
输出:
  - 路段 quad strip（路口端收短 hw 米，避免重叠）
  - 路口填充多边形（仅端部短段的局部 unary_union，无大洞）

结果: 路口自然合并曲线，路段无 Z-fighting，城市街区保持空白
"""
import hou
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import unary_union

geo_in = hou.pwd().inputs()[0].geometry()
geo    = hou.pwd().geometry()

UP   = hou.Vector3(0, 1, 0)
RTOL = 1.0    # 路口检测哈希精度 (m)
JUNC_SEG_MULT = 1.5   # 路口端部取几倍 hw 的长度做 buffer

# ── 辅助 ─────────────────────────────────────────────────────────────────
def norm_v(v):
    l = v.length(); return v/l if l>1e-6 else hou.Vector3(1,0,0)
def make_perp(t): p=UP.cross(t); l=p.length(); return p/l if l>1e-6 else hou.Vector3(1,0,0)
def jkey(pos): return (round(pos[0]/RTOL)*RTOL, round(pos[2]/RTOL)*RTOL)

# ── 1. 读路，统计端点共享次数 ────────────────────────────────────────────
pt_usage  = {}
road_data = []   # [(hw, positions)]

for prim in geo_in.prims():
    try:    hw = float(prim.attribValue('half_width'))
    except: hw = 2.0
    verts = list(prim.vertices())
    if len(verts) < 2: continue
    positions = [v.point().position() for v in verts]
    road_data.append((hw, positions))
    for pos in [positions[0], positions[-1]]:
        k = jkey(pos)
        pt_usage[k] = pt_usage.get(k, 0) + 1

def is_junc(pos): return pt_usage.get(jkey(pos), 0) >= 2

# ── 2. 路段 quad（收短）+ 收集路口端部缓冲多边形 ─────────────────────────
junc_bufs = {}   # jkey -> [Shapely Polygon, ...]

for hw, positions in road_data:
    n = len(positions)
    if n < 2: continue

    # 各点切线
    tangs = []
    for i in range(n):
        if i==0:     t = norm_v(positions[1]-positions[0])
        elif i==n-1: t = norm_v(positions[-1]-positions[-2])
        else:        t = norm_v(positions[i+1]-positions[i-1])
        tangs.append(t)

    seg_len = sum((positions[i+1]-positions[i]).length() for i in range(n-1))
    if seg_len < 1e-6: continue

    st = is_junc(positions[0])
    en = is_junc(positions[-1])
    start_trim = hw if st else 0.0
    end_trim   = hw if en else 0.0

    # ── 收集路口端部 Shapely buffer ──────────────────────────────────────
    junc_local_len = hw * JUNC_SEG_MULT

    def collect_junc_buf(start_pos, tang, is_start):
        seg_pts = []
        if is_start:
            seg_pts = [positions[0]]
            cum = 0.0
            for i in range(n-1):
                seg_pts.append(positions[i+1])
                cum += (positions[i+1]-positions[i]).length()
                if cum >= junc_local_len: break
        else:
            seg_pts = [positions[-1]]
            cum = 0.0
            for i in range(n-1, 0, -1):
                seg_pts.append(positions[i-1])
                cum += (positions[i]-positions[i-1]).length()
                if cum >= junc_local_len: break
            seg_pts.reverse()
        if len(seg_pts) < 2:
            seg_pts = [positions[0], positions[1]] if is_start else [positions[-2], positions[-1]]
        coords = [(p[0], p[2]) for p in seg_pts]
        try:
            buf = LineString(coords).buffer(hw, cap_style=2, join_style=1, mitre_limit=3.0)
            if not buf.is_empty:
                k = jkey(positions[0] if is_start else positions[-1])
                junc_bufs.setdefault(k, []).append(buf)
        except Exception:
            pass

    if st: collect_junc_buf(positions[0],  tangs[0],  True)
    if en: collect_junc_buf(positions[-1], tangs[-1], False)

    # ── 生成路段 quad strip ──────────────────────────────────────────────
    lefts, rights = [], []
    cumlen = 0.0
    for i, pos in enumerate(positions):
        if i > 0: cumlen += (positions[i]-positions[i-1]).length()
        frac = cumlen / seg_len
        fs = start_trim / seg_len
        fe = 1.0 - end_trim / seg_len
        if frac < fs - 1e-4: continue
        if frac > fe + 1e-4: continue
        perp = make_perp(tangs[i])
        lefts.append(pos + perp*hw)
        rights.append(pos - perp*hw)

    for i in range(len(lefts)-1):
        pts_pos = [lefts[i], lefts[i+1], rights[i+1], rights[i]]
        hpts = [geo.createPoint() for _ in pts_pos]
        for p, pp in zip(hpts, pts_pos): p.setPosition(pp)
        quad = geo.createPolygon()
        for p in hpts: quad.addVertex(p)

# ── 3. 路口填充（局部 unary_union，只在 2+ 路汇聚处）────────────────────
def write_shapely(geo, sp):
    coords = list(sp.exterior.coords)
    if coords[0]==coords[-1]: coords=coords[:-1]
    if len(coords)<3: return
    hpts=[]
    for x,z in coords:
        p=geo.createPoint(); p.setPosition(hou.Vector3(x,0.0,z)); hpts.append(p)
    poly=geo.createPolygon()
    for p in hpts: poly.addVertex(p)

junc_count = 0
for k, bufs in junc_bufs.items():
    if len(bufs) < 2: continue
    try: merged = unary_union(bufs)
    except Exception: continue
    if isinstance(merged, Polygon): write_shapely(geo, merged); junc_count+=1
    elif isinstance(merged, MultiPolygon):
        for part in merged.geoms: write_shapely(geo, part)
        junc_count+=1

import sys
print('[road_strips_v4] quad_roads=%d junctions=%d total_prims=%d' % (
    len(road_data), junc_count, geo.primCount()), file=sys.stderr)
