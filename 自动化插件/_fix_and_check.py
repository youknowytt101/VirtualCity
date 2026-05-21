"""
修复 pattaya_v3 几何对齐问题并校验结果
Fix 1: 道路/建筑裁剪到 DEM 边界（防止 Ray 未命中的悬空几何）
"""
import rpyc

conn = rpyc.classic.connect('localhost', 18811)
hou = conn.modules.hou

# 加载 hip 文件
HIP = 'F:/VirtualCity/Houdini/Hip/VC_pattaya_sai6_mvp_citygen_v001.hip'
if 'untitled' in hou.hipFile.path():
    hou.hipFile.load(HIP, suppress_save_prompt=True)
    print('hip loaded:', hou.hipFile.path())

net = hou.node('/obj/pattaya_osm')

# ── Step 1: 读 DEM 真实边界 ───────────────────────────
dem = hou.node('/obj/pattaya_osm/dem_terrain')
dem.cook(force=True)
dem_geo = dem.geometry()
bb = dem_geo.boundingBox()
mn, mx = bb.minvec(), bb.maxvec()
dem_xmin, dem_xmax = mn[0], mx[0]
dem_zmin, dem_zmax = mn[2], mx[2]
print('DEM bounds: X[{:.0f}~{:.0f}]  Z[{:.0f}~{:.0f}]'.format(dem_xmin, dem_xmax, dem_zmin, dem_zmax))

MARGIN = 50  # 边界容差（米）
XMIN, XMAX = dem_xmin - MARGIN, dem_xmax + MARGIN
ZMIN, ZMAX = dem_zmin - MARGIN, dem_zmax + MARGIN

def clip_geo_to_bounds(src_node, clip_name):
    """attribwrangle 标记 @del + blast 删除，避免 removeprim 迭代崩溃"""
    for n in ['_w_' + clip_name, clip_name]:
        old = hou.node('/obj/pattaya_osm/' + n)
        if old: old.destroy()

    # Step A: 标记越界基元 @del=1
    wrangle = net.createNode('attribwrangle', '_w_' + clip_name)
    wrangle.setInput(0, src_node)
    wrangle.parm('class').set(1)  # run over Primitives
    vex = '''int pts[] = primpoints(0, @primnum);
int n = len(pts);
if (n == 0) {{ i@del = 1; return; }}
vector sum = {{0,0,0}};
for(int i=0; i<n; i++) sum += point(0,"P",pts[i]);
vector c = sum / n;
i@del = (c.x < {xmin} || c.x > {xmax} || c.z < {zmin} || c.z > {zmax}) ? 1 : 0;
'''.format(xmin=XMIN, xmax=XMAX, zmin=ZMIN, zmax=ZMAX)
    wrangle.parm('snippet').set(vex)

    # Step B: blast 删除标记的基元
    blast = net.createNode('blast', clip_name)
    blast.setInput(0, wrangle)
    blast.parm('group').set('@del==1')
    blast.parm('grouptype').set(4)   # Primitives
    blast.parm('negate').set(0)
    blast.cook(force=True)
    return blast

road_src = hou.node('/obj/pattaya_osm/snap_roads_to_terrain1') or \
           hou.node('/obj/pattaya_osm/snap_roads_to_terrain')
bld_src  = hou.node('/obj/pattaya_osm/post_normals')

road_clip = clip_geo_to_bounds(road_src, '_road_clip')
bld_clip  = clip_geo_to_bounds(bld_src,  '_bld_clip')

print('\n=== 裁剪结果 ===')
for label, node in [('road_clip', road_clip), ('bld_clip', bld_clip)]:
    geo = node.geometry()
    pts = geo.intrinsicValue('pointcount')
    prims = geo.intrinsicValue('primitivecount')
    if pts > 0:
        b = geo.boundingBox()
        m, x = b.minvec(), b.maxvec()
        print('{}: pts={} prims={}  X[{:.0f}~{:.0f}]  Z[{:.0f}~{:.0f}]  Y[{:.1f}~{:.1f}]'.format(
            label, pts, prims, m[0], x[0], m[2], x[2], m[1], x[1]))
    else:
        print(label, ': EMPTY after clip!')

# ── Step 3: 校验对齐 ──────────────────────────────────
print('\n=== 对齐校验 ===')
road_geo = road_clip.geometry()
bld_geo  = bld_clip.geometry()
dem_bb   = dem_geo.boundingBox()

def check_inside(name, geo, ref_bb):
    if geo.intrinsicValue('pointcount') == 0:
        print(name, ': EMPTY')
        return False
    bb = geo.boundingBox()
    margin = 200
    ok = (bb.minvec()[0] >= ref_bb.minvec()[0] - margin and
          bb.maxvec()[0] <= ref_bb.maxvec()[0] + margin and
          bb.minvec()[2] >= ref_bb.minvec()[2] - margin and
          bb.maxvec()[2] <= ref_bb.maxvec()[2] + margin)
    status = 'OK' if ok else 'WARNING: 超出 DEM 边界'
    print('{}: {}'.format(name, status))
    return ok

check_inside('道路', road_geo, dem_bb)
check_inside('建筑', bld_geo,  dem_bb)

print('\n✅ 检查完成 - 如上无 WARNING 则可导出')
conn.close()
