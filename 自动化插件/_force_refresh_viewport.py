"""强制 recook 整条输出链，刷新 Houdini 视口"""
import rpyc
from vc_paths import CONFIG

RESULT_FILE = (CONFIG / "_refresh_result.txt").as_posix()

conn = rpyc.classic.connect('localhost', 18811)
hou  = conn.modules.hou

CODE = r"""
import hou

net = hou.node('/obj/pattaya_osm')

# 完整强制 recook 顺序（依赖链从上到下）
FULL_CHAIN = [
    'osm_import',
    'dem_terrain',
    'extract_buildings',
    'snap_bld_to_terrain',
    'extrude_buildings',
    'post_normals',
    'snap_roads_to_terrain1',
    'road_width',
    'road_strips',
    'bld_clipped',
    'road_clipped',
    'merge_all',
    'OUT_city',
]

OUT = r'__RESULT_FILE__'
lines = []

for name in FULL_CHAIN:
    n = hou.node('/obj/pattaya_osm/' + name)
    if not n:
        lines.append('SKIP  {:<25s} (not found)'.format(name))
        continue
    n.cook(force=True)
    geo  = n.geometry()
    pts  = geo.intrinsicValue('pointcount')
    prms = geo.intrinsicValue('primitivecount')
    bb   = geo.boundingBox()
    lines.append('OK    {:<25s} pts={:7d}  prims={:6d}  Y[{:.1f}~{:.1f}]'.format(
        name, pts, prms, bb.minvec()[1], bb.maxvec()[1]))

# 确保 display flag 在 OUT_city
out_city = hou.node('/obj/pattaya_osm/OUT_city')
if out_city:
    out_city.setDisplayFlag(True)
    out_city.setRenderFlag(True)

with open(OUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
""".replace('__RESULT_FILE__', RESULT_FILE)

conn.execute(CODE)
conn.close()

import time, pathlib
time.sleep(5)
result = pathlib.Path(RESULT_FILE)
if result.exists():
    print(result.read_text(encoding='utf-8'))
else:
    print('[ERROR] 结果文件未生成')
