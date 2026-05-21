import rpyc, json

conn = rpyc.classic.connect('localhost', 18811)
hou = conn.modules.hou

cfg = json.loads(open('F:/VirtualCity/配置/active_area.json', encoding='utf-8').read())
print('当前区域:', cfg['area_id'])
print('OSM:', cfg['osm_file'])
print('建筑:', cfg['buildings_file'])
print('原点: lon={} lat={}'.format(cfg['origin_lon'], cfg['origin_lat']))
print()

nodes = [
    '/obj/pattaya_osm/osm_import',
    '/obj/pattaya_osm/dem_terrain',
    '/obj/pattaya_osm/snap_bld_to_terrain',
    '/obj/pattaya_osm/post_normals',
    '/obj/pattaya_osm/road_strips',
]

for path in nodes:
    n = hou.node(path)
    if not n:
        print(path, ': NOT FOUND')
        continue
    n.cook(force=True)
    geo = n.geometry()
    pts = geo.intrinsicValue('pointcount')
    prims = geo.intrinsicValue('primitivecount')
    name = path.split('/')[-1]
    if pts > 0:
        bb = geo.boundingBox()
        mn = bb.minvec()
        mx = bb.maxvec()
        print('{:30s} pts={:6d} prims={:6d}  X[{:.0f}~{:.0f}]  Z[{:.0f}~{:.0f}]  Y[{:.1f}~{:.1f}]'.format(
            name, pts, prims, mn[0], mx[0], mn[2], mx[2], mn[1], mx[1]))
    else:
        print(name, ': EMPTY')

conn.close()
