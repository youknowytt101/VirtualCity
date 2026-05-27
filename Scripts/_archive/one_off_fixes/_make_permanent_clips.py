"""永久化 DEM 边界裁剪节点到 hip 文件"""
import rpyc

conn = rpyc.classic.connect('localhost', 18811)
hou = conn.modules.hou
net = hou.node('/obj/pattaya_osm')

# DEM 边界
dem = hou.node('/obj/pattaya_osm/dem_terrain')
dem.cook(force=False)
bb = dem.geometry().boundingBox()
mn, mx = bb.minvec(), bb.maxvec()
MARGIN = 50
XMIN, XMAX = mn[0] - MARGIN, mx[0] + MARGIN
ZMIN, ZMAX = mn[2] - MARGIN, mx[2] + MARGIN
print('DEM bounds: X[{:.0f}~{:.0f}] Z[{:.0f}~{:.0f}]'.format(XMIN, XMAX, ZMIN, ZMAX))

VEX = (
    'int pts[] = primpoints(0, @primnum);\n'
    'int n = len(pts);\n'
    'if (n == 0) { i@del = 1; return; }\n'
    'vector sum = {0,0,0};\n'
    'for(int i=0; i<n; i++) sum += point(0,"P",pts[i]);\n'
    'vector c = sum / n;\n'
    'i@del = (c.x < XMIN || c.x > XMAX || c.z < ZMIN || c.z > ZMAX) ? 1 : 0;\n'
).replace('XMIN', str(XMIN)).replace('XMAX', str(XMAX)) \
 .replace('ZMIN', str(ZMIN)).replace('ZMAX', str(ZMAX))


def make_perm_clip(src_name, mark_name, out_name):
    # 清理所有旧版本
    for n in [out_name, mark_name, '_w__bld_clip', '_bld_clip',
              '_w__road_clip', '_road_clip']:
        old = hou.node('/obj/pattaya_osm/' + n)
        if old:
            old.destroy()

    src = hou.node('/obj/pattaya_osm/' + src_name)
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

    geo = b.geometry()
    pts   = geo.intrinsicValue('pointcount')
    prims = geo.intrinsicValue('primitivecount')
    bbs   = geo.boundingBox()
    print('  {}: pts={} prims={}  Y[{:.1f}~{:.1f}]'.format(
        out_name, pts, prims, bbs.minvec()[1], bbs.maxvec()[1]))
    return b


print('创建永久裁剪节点...')
bld_clip  = make_perm_clip('post_normals', 'bld_clip_mark',  'bld_clipped')
road_clip = make_perm_clip('road_strips',  'road_clip_mark', 'road_clipped')

# 重连 merge_all
merge = hou.node('/obj/pattaya_osm/merge_all')
merge.setInput(0, bld_clip)
merge.setInput(1, road_clip)
print('\nmerge_all 输入:')
for i, inp in enumerate(merge.inputs()):
    if inp:
        print('  [{}] -> {}'.format(i, inp.path()))

net.layoutChildren()
hou.hipFile.save()
print('\nhip 已保存，裁剪节点永久化完成')
conn.close()
