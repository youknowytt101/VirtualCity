"""
应用 DEM 边界裁剪：
  1. 创建 _bld_clip / _road_clip（VEX @del + blast）
  2. 重连 merge_all 输入到裁剪后的节点
  3. 保存 hip 文件，供视口验证 + 导出
"""
import rpyc
conn = rpyc.classic.connect('localhost', 18811)
hou = conn.modules.hou

HIP = 'F:/VirtualCity/Houdini/Hip/VC_pattaya_sai6_mvp_citygen_v001.hip'
if 'untitled' in hou.hipFile.path():
    hou.hipFile.load(HIP, suppress_save_prompt=True)
    print('hip 已加载')

net = hou.node('/obj/pattaya_osm')

# DEM 边界
dem = hou.node('/obj/pattaya_osm/dem_terrain')
dem.cook(force=True)
bb = dem.geometry().boundingBox()
mn, mx = bb.minvec(), bb.maxvec()
MARGIN = 50
XMIN, XMAX = mn[0] - MARGIN, mx[0] + MARGIN
ZMIN, ZMAX = mn[2] - MARGIN, mx[2] + MARGIN
print('DEM bounds (含{}m容差): X[{:.0f}~{:.0f}] Z[{:.0f}~{:.0f}]'.format(MARGIN, XMIN, XMAX, ZMIN, ZMAX))

def make_clip(src_path, name):
    src = hou.node(src_path)
    for n in [name, '_w_' + name]:
        old = hou.node('/obj/pattaya_osm/' + n)
        if old: old.destroy()

    w = net.createNode('attribwrangle', '_w_' + name)
    w.setInput(0, src)
    w.parm('class').set(1)
    vex = '''int pts[] = primpoints(0, @primnum);
int n = len(pts);
if (n == 0) {{ i@del = 1; return; }}
vector sum = {{0,0,0}};
for(int i=0; i<n; i++) sum += point(0,"P",pts[i]);
vector c = sum / n;
i@del = (c.x < {xmin} || c.x > {xmax} || c.z < {zmin} || c.z > {zmax}) ? 1 : 0;
'''.format(xmin=XMIN, xmax=XMAX, zmin=ZMIN, zmax=ZMAX)
    w.parm('snippet').set(vex)

    b = net.createNode('blast', name)
    b.setInput(0, w)
    b.parm('group').set('@del==1')
    b.parm('grouptype').set(4)
    b.parm('negate').set(0)
    b.cook(force=True)
    return b

bld_clip  = make_clip('/obj/pattaya_osm/post_normals', '_bld_clip')
road_clip = make_clip('/obj/pattaya_osm/road_strips',  '_road_clip')

# 报告
for label, n in [('bld_clip', bld_clip), ('road_clip', road_clip)]:
    geo = n.geometry()
    pts = geo.intrinsicValue('pointcount')
    prims = geo.intrinsicValue('primitivecount')
    b = geo.boundingBox()
    print('  {}: pts={} prims={} X[{:.0f}~{:.0f}] Z[{:.0f}~{:.0f}] Y[{:.1f}~{:.1f}]'.format(
        label, pts, prims, b.minvec()[0], b.maxvec()[0], b.minvec()[2], b.maxvec()[2], b.minvec()[1], b.maxvec()[1]))

# 重连 merge_all
merge = hou.node('/obj/pattaya_osm/merge_all')
merge.setInput(0, bld_clip)
merge.setInput(1, road_clip)
# input[2] 保持 dem_terrain
print('\nmerge_all 重连完成:')
for i, inp in enumerate(merge.inputs()):
    if inp: print('  input[{}] <- {}'.format(i, inp.path()))

# 自动布局
net.layoutChildren()

# 保存
hou.hipFile.save()
print('\nhip 已保存。请在 Houdini 视口选中 OUT_city 查看效果')
conn.close()
