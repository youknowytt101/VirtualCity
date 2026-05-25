import xml.etree.ElementTree as ET
import json, math

# ── 区域配置从 active_area.json 读取，切换区域只改该文件 ──
_CFG_FILE = r"D:/VirtualCity/Config/active_area.json"
with open(_CFG_FILE, encoding="utf-8") as _f:
    _cfg = json.load(_f)


def _resolve_project_path(value):
    raw = str(value).replace(chr(92), '/')
    low = raw.lower()
    marker = '/virtualcity/'
    idx = low.find(marker)
    if idx >= 0:
        return r'D:/VirtualCity' + '/' + raw[idx + len(marker):]
    if low.endswith('/virtualcity'):
        return r'D:/VirtualCity'
    if ':' in raw[:3] or raw.startswith('/'):
        return raw
    return r'D:/VirtualCity' + '/' + raw

OSM_FILE       = _resolve_project_path(_cfg["osm_file"])
BUILDINGS_FILE = _resolve_project_path(_cfg["buildings_file"])
ORIGIN_LON     = _cfg["origin_lon"]
ORIGIN_LAT     = _cfg["origin_lat"]

def _resolve_project_path(value):
    raw = str(value).replace(chr(92), '/')
    low = raw.lower()
    marker = '/virtualcity/'
    idx = low.find(marker)
    if idx >= 0:
        return r'D:/VirtualCity' + '/' + raw[idx + len(marker):]
    if low.endswith('/virtualcity'):
        return r'D:/VirtualCity'
    if ':' in raw[:3] or raw.startswith('/'):
        return raw
    return r'D:/VirtualCity' + '/' + raw

def wgs84_to_local(lon, lat):
    dx = (lon - ORIGIN_LON) * math.cos(math.radians(ORIGIN_LAT)) * 111319.9
    dy = (lat - ORIGIN_LAT) * 111319.9
    return dx, dy

def signed_area_xz(pts):
    n = len(pts)
    area = 0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1]
        area -= pts[j][0] * pts[i][1]
    return area / 2.0

geo = hou.pwd().geometry()

bld_tag_attrib = geo.addAttrib(hou.attribType.Prim, 'bld_type', 'yes')
height_attrib  = geo.addAttrib(hou.attribType.Prim, 'height_m', 10.0)
hw_attrib      = geo.addAttrib(hou.attribType.Prim, 'highway', '')
bld_group  = geo.createPrimGroup('buildings')
road_group = geo.createPrimGroup('roads')

# --- 建筑：从 Google Open Buildings GeoJSON 读取（含真实高度）---
with open(BUILDINGS_FILE, encoding='utf-8') as f:
    fc = json.load(f)

for feature in fc['features']:
    geom = feature['geometry']
    props = feature['properties']
    h = props.get('height') or 10.0

    if geom is None: continue
    rings = geom['coordinates'] if geom['type'] == 'Polygon' else geom['coordinates'][0]
    ring = rings[0]

    local_pts = []
    for coord in ring:
        x, z = wgs84_to_local(coord[0], coord[1])
        local_pts.append((x, z))

    if len(local_pts) < 3:
        continue

    sa = signed_area_xz(local_pts)
    if sa > 0:
        local_pts = list(reversed(local_pts))

    hpts = []
    for (x, z) in local_pts:
        p = geo.createPoint()
        p.setPosition(hou.Vector3(x, 0, -z))
        hpts.append(p)

    if len(hpts) >= 3:
        poly = geo.createPolygon()
        for p in hpts[:-1]:
            poly.addVertex(p)
        poly.setAttribValue(bld_tag_attrib, 'yes')
        poly.setAttribValue(height_attrib, float(h))
        bld_group.add(poly)

# --- 道路：仍从 OSM 读取 ---
tree = ET.parse(OSM_FILE)
root = tree.getroot()

nodes = {}
for nd in root.findall('node'):
    nid = nd.get('id')
    nodes[nid] = (float(nd.get('lon')), float(nd.get('lat')))

for way in root.findall('way'):
    tags = {t.get('k'): t.get('v') for t in way.findall('tag')}
    hw = tags.get('highway', '')
    if not hw:
        continue
    nd_refs = [nr.get('ref') for nr in way.findall('nd')]
    pts = []
    for ref in nd_refs:
        if ref in nodes:
            x, z = wgs84_to_local(*nodes[ref])
            p = geo.createPoint()
            p.setPosition(hou.Vector3(x, 0, -z))
            pts.append(p)
    if len(pts) >= 2:
        poly = geo.createPolygon(is_closed=False)
        for p in pts:
            poly.addVertex(p)
        poly.setAttribValue(hw_attrib, hw)
        road_group.add(poly)
