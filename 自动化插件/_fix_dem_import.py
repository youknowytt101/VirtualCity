"""修复 dem_import Python SOP 硬编码路径 → 改为读 active_area.json"""
import rpyc
conn = rpyc.classic.connect('localhost', 18811)
hou = conn.modules.hou

n = hou.node('/obj/pattaya_osm/dem_import')
new_code = """
import hou, csv, json as _json

with open(r'F:/VirtualCity/配置/active_area.json', encoding='utf-8') as _f:
    CSV_FILE = _json.load(_f)['dem_csv']

geo = hou.pwd().geometry()
pts = []
with open(CSV_FILE, newline='') as f:
    reader = csv.DictReader(f)
    for row in reader:
        p = geo.createPoint()
        p.setPosition(hou.Vector3(float(row['x']), float(row['y']), float(row['z'])))
        pts.append(p)
"""
n.parm('python').set(new_code)
n.cook(force=True)
print('dem_import pts={}'.format(n.geometry().intrinsicValue('pointcount')))
hou.hipFile.save()
print('hip saved')
conn.close()
