import xml.etree.ElementTree as ET
import json, math, os

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

AREA_ID = _cfg.get("area_id", "")
READY_DIR = r'__ROOT__' + '/RawData/_houdini_ready/' + AREA_ID
OSM_READY = READY_DIR + '/roads.osm'
BUILDINGS_READY = READY_DIR + '/buildings.geojson'

OSM_FILE = OSM_READY if os.path.exists(OSM_READY) else _resolve_project_path(_cfg["osm_file"])
BUILDINGS_FILE = (BUILDINGS_READY if os.path.exists(BUILDINGS_READY)
                  else _resolve_project_path(_cfg["buildings_file"]))
ORIGIN_LON     = _cfg["origin_lon"]
ORIGIN_LAT     = _cfg["origin_lat"]

# ── UTM 投影（内嵌，无外部依赖）─────────────────────────────────────
_A=6378137.0;_E=0.00669437999014;_E2=_E*_E;_E3=_E2*_E;_EP2=_E/(1-_E)
_K0=0.9996;_FE=500000.0;_FN=10000000.0
_M1=1-_E/4-3*_E2/64-5*_E3/256;_M2=3*_E/8+3*_E2/32+45*_E3/1024
_M3=15*_E2/256+45*_E3/1024;_M4=35*_E3/3072

def _utm_forward(lat, lon, force_zone=0):
    lr=math.radians(lat);sl=math.sin(lr);cl=math.cos(lr);tl=math.tan(lr)
    z=force_zone or int((lon+180)/6)+1
    dl=math.radians(lon-((z-1)*6-177))
    n=_A/math.sqrt(1-_E*sl*sl);t=tl*tl;c=_EP2*cl*cl;a=cl*dl
    m=_A*(_M1*lr-_M2*math.sin(2*lr)+_M3*math.sin(4*lr)-_M4*math.sin(6*lr))
    a2=a*a;a4=a2*a2;a6=a4*a2;t2=t*t
    x=_K0*n*(a+(1-t+c)*a2*a/6+(5-18*t+t2+72*c-58*_EP2)*a4*a/120)+_FE
    y=_K0*(m+n*tl*(a2/2+(5-t+9*c+4*c*c)*a4/24+(61-58*t+t2+600*c-330*_EP2)*a6/720))
    if lat<0:y+=_FN
    return x,y,z

_UTM_ZONE = int((ORIGIN_LON + 180) / 6) + 1
_OX, _OY, _ = _utm_forward(ORIGIN_LAT, ORIGIN_LON, _UTM_ZONE)

def wgs84_to_local(lon, lat):
    x, y, _ = _utm_forward(lat, lon, force_zone=_UTM_ZONE)
    return x - _OX, y - _OY

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

bld_tag_attrib  = geo.addAttrib(hou.attribType.Prim, 'bld_type', 'yes')
height_attrib   = geo.addAttrib(hou.attribType.Prim, 'height_m', 0.0)
hw_attrib       = geo.addAttrib(hou.attribType.Prim, 'highway', '')
lanes_attrib    = geo.addAttrib(hou.attribType.Prim, 'lanes', 0)
width_attrib    = geo.addAttrib(hou.attribType.Prim, 'osm_width', 0.0)
bld_class_attrib = geo.addAttrib(hou.attribType.Prim, 'bld_class', '')
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
        poly.setAttribValue(bld_class_attrib, str(props.get('class', 'building') or 'building'))
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
            # OSM lanes + width 标签（精度审核 #4：减少宽度误差）
            _lanes = 0
            _osm_w = 0.0
            try: _lanes = int(tags.get('lanes', '0') or '0')
            except (TypeError, ValueError): pass
            try: _osm_w = float(str(tags.get('width', '0') or '0').replace('m','').strip())
            except (TypeError, ValueError): pass
            poly.setAttribValue(lanes_attrib, _lanes)
            poly.setAttribValue(width_attrib, _osm_w)
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
