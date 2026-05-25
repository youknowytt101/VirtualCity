import xml.etree.ElementTree as ET
import json, math

_CFG_FILE = r"__CFG__"
with open(_CFG_FILE, encoding="utf-8") as _f:
    _cfg = json.load(_f)

def _resolve_project_path(value):
    raw = str(value).replace(chr(92), '/')
    low = raw.lower()
    marker = '/virtualcity/'
    idx = low.find(marker)
    if idx >= 0:
        return r'__ROOT__' + '/' + raw[idx + len(marker):]
    if low.endswith('/virtualcity'):
        return r'__ROOT__'
    if ':' in raw[:3] or raw.startswith('/'):
        return raw
    return r'__ROOT__' + '/' + raw

OSM_FILE       = _resolve_project_path(_cfg["osm_file"])
BUILDINGS_FILE = _resolve_project_path(_cfg["buildings_file"])
ORIGIN_LON     = _cfg["origin_lon"]
ORIGIN_LAT     = _cfg["origin_lat"]

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

def _parse_height(h_raw, levels_raw=None):
    # Return height in metres. 0.0 means unknown -> procedural_height fills in.
    try:
        h = float(h_raw) if h_raw is not None else None
    except (TypeError, ValueError):
        h = None
    if h is not None and h > 0:
        return h
    try:
        lvl = float(levels_raw) if levels_raw is not None else None
    except (TypeError, ValueError):
        lvl = None
    if lvl is not None and lvl > 0:
        return lvl * 3.5
    return 0.0

geo = hou.pwd().geometry()

bld_tag_attrib = geo.addAttrib(hou.attribType.Prim, 'bld_type', 'yes')
height_attrib  = geo.addAttrib(hou.attribType.Prim, 'height_m', 0.0)
hw_attrib      = geo.addAttrib(hou.attribType.Prim, 'highway', '')
bld_group  = geo.createPrimGroup('buildings')
road_group = geo.createPrimGroup('roads')

# ── Part 1: Overture buildings (primary source) ───────────────────────────────
_CELL = 15.0
overture_cells = set()

with open(BUILDINGS_FILE, encoding='utf-8') as f:
    fc = json.load(f)

for feature in fc['features']:
    geom  = feature['geometry']
    props = feature['properties']
    if geom is None:
        continue
    rings = geom['coordinates'] if geom['type'] == 'Polygon' else geom['coordinates'][0]
    ring  = rings[0]
    local_pts = []
    for coord in ring:
        x, z = wgs84_to_local(coord[0], coord[1])
        local_pts.append((x, z))
    if len(local_pts) < 3:
        continue
    sa = signed_area_xz(local_pts)
    if sa > 0:
        local_pts = list(reversed(local_pts))
    h = _parse_height(props.get('height'))
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
        poly.setAttribValue(height_attrib, h)
        bld_group.add(poly)
        cx = sum(p[0] for p in local_pts) / len(local_pts)
        cz = sum(p[1] for p in local_pts) / len(local_pts)
        overture_cells.add((int(cx / _CELL), int(cz / _CELL)))

# ── Part 2: OSM roads + building fallback ────────────────────────────────────
tree = ET.parse(OSM_FILE)
root = tree.getroot()

nodes = {}
for nd in root.findall('node'):
    nid = nd.get('id')
    nodes[nid] = (float(nd.get('lon')), float(nd.get('lat')))

def _overture_covered(cx, cz):
    xi, zi = int(cx / _CELL), int(cz / _CELL)
    return any((xi+di, zi+dj) in overture_cells
               for di in range(-1, 2) for dj in range(-1, 2))

osm_bld_added = 0
for way in root.findall('way'):
    tags   = {t.get('k'): t.get('v') for t in way.findall('tag')}
    hw     = tags.get('highway', '')
    is_bld = bool(tags.get('building'))
    nd_refs = [nr.get('ref') for nr in way.findall('nd')]

    if hw:
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

    elif is_bld:
        coords = [nodes[r] for r in nd_refs if r in nodes]
        if len(coords) < 3:
            continue
        local_pts = [wgs84_to_local(lon, lat) for lon, lat in coords]
        cx = sum(p[0] for p in local_pts) / len(local_pts)
        cz = sum(p[1] for p in local_pts) / len(local_pts)
        if _overture_covered(cx, cz):
            continue
        sa = signed_area_xz(local_pts)
        if sa > 0:
            local_pts = list(reversed(local_pts))
        h = _parse_height(tags.get('height'), tags.get('building:levels'))
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
            poly.setAttribValue(height_attrib, h)
            bld_group.add(poly)
            overture_cells.add((int(cx / _CELL), int(cz / _CELL)))
            osm_bld_added += 1
