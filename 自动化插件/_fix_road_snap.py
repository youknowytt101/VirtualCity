"""
修复道路地形吸附 + 验证全链路 Y 值
所有统计计算在 Houdini 内部执行（避免 rpyc 大量传输超时）
"""
import rpyc

conn = rpyc.classic.connect('localhost', 18811)
hou  = conn.modules.hou

# 在 Houdini Python 环境内执行完整修复+验证代码
result = hou.session.hscriptExpression if False else None

RESULT_FILE = r'F:/VirtualCity/配置/_road_snap_result.txt'

CODE = r"""
import hou, json

OUT = r'F:/VirtualCity/配置/_road_snap_result.txt'
lines = []

net = hou.node('/obj/pattaya_osm')
errors = []

ROAD_SNAP_VEX = (
    'int hit_prim;\n'
    'vector uvw;\n'
    'xyzdist(1, @P, hit_prim, uvw);\n'
    'vector terrain_pos = primuv(1, "P", hit_prim, uvw);\n'
    '@P.y = terrain_pos.y;\n'
)

snap     = hou.node('/obj/pattaya_osm/snap_roads_to_terrain1')
resample = hou.node('/obj/pattaya_osm/resample_roads')
dem_t    = hou.node('/obj/pattaya_osm/dem_terrain')
road_w   = hou.node('/obj/pattaya_osm/road_width')

need_create = (snap is None) or (snap.type().name() != 'attribwrangle')

if need_create:
    if snap:
        snap.destroy()
    snap = net.createNode('attribwrangle', 'snap_roads_to_terrain1')
    snap.setInput(0, resample)
    snap.setInput(1, dem_t)
    snap.parm('class').set(2)  # 2 = Point
    snap.parm('snippet').set(ROAD_SNAP_VEX)
    lines.append('[fix] snap_roads_to_terrain1 recreated as attribwrangle (xyzdist, point-level)')
else:
    snap.parm('class').set(2)  # 2 = Point
    snap.parm('snippet').set(ROAD_SNAP_VEX)
    snap.setInput(0, resample)
    snap.setInput(1, dem_t)
    lines.append('[fix] snap_roads_to_terrain1 class=Point + VEX updated')

if road_w:
    road_w.setInput(0, snap)

# 强制 recook 全链路
for name in ['dem_terrain', 'snap_roads_to_terrain1', 'road_width', 'road_strips']:
    n = hou.node('/obj/pattaya_osm/' + name)
    if n:
        n.cook(force=True)

# 验证 Y 值（Houdini 内部计算，不通过 rpyc 传输点数据）
lines.append('')
lines.append('--- Y 值统计 ---')
for name in ['snap_roads_to_terrain1', 'road_width', 'road_strips']:
    n = hou.node('/obj/pattaya_osm/' + name)
    if not n:
        lines.append('{}: NOT FOUND'.format(name))
        errors.append(name + ' not found')
        continue
    geo = n.geometry()
    pts = geo.points()
    if not pts:
        lines.append('{}: 0 points'.format(name))
        errors.append(name + ' empty')
        continue
    ys   = [p.position()[1] for p in pts]
    ymin = min(ys)
    ymax = max(ys)
    zero = sum(1 for y in ys if abs(y) < 0.01)
    pct  = 100.0 * zero / len(ys)
    ok   = pct < 5.0
    tag  = 'OK' if ok else 'FAIL'
    lines.append('[{}] {:<28s} pts={:6d}  Y[{:.2f}~{:.2f}]  zero_y={:.0f}%'.format(
        tag, name, len(ys), ymin, ymax, pct))
    if not ok:
        errors.append(name + ' zero_y={:.0f}%'.format(pct))

net.layoutChildren()
hou.hipFile.save()

lines.append('')
if errors:
    lines.append('STATUS: FAIL')
    for e in errors:
        lines.append('  ' + e)
else:
    lines.append('STATUS: OK')

with open(OUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
"""

conn.execute(CODE)
conn.close()

import time, pathlib
time.sleep(3)
result_path = pathlib.Path(RESULT_FILE)
if result_path.exists():
    print(result_path.read_text(encoding='utf-8'))
else:
    print('[ERROR] 结果文件未生成，请检查 Houdini 控制台')
