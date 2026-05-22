"""修复 dem_import Python SOP 硬编码路径 → 改为读 active_area.json"""
import rpyc
from vc_paths import ROOT, ACTIVE_AREA

ROOT_STR = ROOT.as_posix()
CFG_FILE = ACTIVE_AREA.as_posix()

conn = rpyc.classic.connect('localhost', 18811)
hou = conn.modules.hou

n = hou.node('/obj/pattaya_osm/dem_import')
new_code = """
import hou, csv, json as _json

ROOT_DIR = r'__ROOT__'
CFG_FILE = r'__CFG__'
def _resolve_project_path(value):
    raw = str(value).replace('\\\\', '/')
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
    CSV_FILE = _resolve_project_path(_json.load(_f)['dem_csv'])

geo = hou.pwd().geometry()
pts = []
with open(CSV_FILE, newline='') as f:
    reader = csv.DictReader(f)
    for row in reader:
        p = geo.createPoint()
        p.setPosition(hou.Vector3(float(row['x']), float(row['y']), float(row['z'])))
        pts.append(p)
""".replace('__ROOT__', ROOT_STR).replace('__CFG__', CFG_FILE)
n.parm('python').set(new_code)
n.cook(force=True)
print('dem_import pts={}'.format(n.geometry().intrinsicValue('pointcount')))
hou.hipFile.save()
print('hip saved')
conn.close()
