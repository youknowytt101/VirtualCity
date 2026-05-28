import hou, csv, json as _json, os
ROOT_DIR = r'__ROOT__'
CFG_FILE = r'__CFG__'
def _resolve_project_path(value):
    raw = str(value).replace(chr(92), '/')
    low = raw.lower()
    marker = '/virtualcity/'
    idx = low.find(marker)
    if idx >= 0:
        return ROOT_DIR + '/' + raw[idx + len(marker):]
    if low.endswith('/virtualcity'):
        return ROOT_DIR
    if ':' in raw[:3] or raw.startswith('/'):
        return raw
    return ROOT_DIR + '/' + raw
with open(CFG_FILE, encoding='utf-8') as _f:
    _cfg = _json.load(_f)
    _ready = ROOT_DIR + '/RawData/_houdini_ready/' + _cfg.get('area_id', '') + '/dem.csv'
    CSV_FILE = _ready if os.path.exists(_ready) else _resolve_project_path(_cfg['dem_csv'])
geo = hou.pwd().geometry()
rows = []
with open(CSV_FILE, newline='') as f:
    for row in csv.DictReader(f):
        rows.append((float(row['x']), float(row['y']), float(row['z']),
                     int(row.get('row', 0)), int(row.get('col', 0))))
# H-005: 用 CSV 的 row/col 列直接构建网格（兼容 UTM 投影坐标）
grid = {}
for row in rows:
    x, y, z = row[0], row[1], row[2]
    ri, ci  = int(row[3]), int(row[4])
    p = geo.createPoint()
    p.setPosition(hou.Vector3(x, y, z))
    grid[(ri, ci)] = p
all_ri = sorted(set(k[0] for k in grid))
all_ci = sorted(set(k[1] for k in grid))
for i in range(len(all_ri) - 1):
    for j in range(len(all_ci) - 1):
        r0, r1 = all_ri[i], all_ri[i+1]
        c0, c1 = all_ci[j], all_ci[j+1]
        corners = [grid.get((r0,c0)), grid.get((r0,c1)),
                   grid.get((r1,c1)), grid.get((r1,c0))]
        if all(corners):
            poly = geo.createPolygon()
            for pt in corners:
                poly.addVertex(pt)
