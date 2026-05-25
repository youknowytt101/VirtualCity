import rpyc, json

conn = rpyc.classic.connect('127.0.0.1', 18811)

CODE = """
import hou, json, builtins
net = hou.node('/obj/pattaya_osm')
ext   = net.node('road_extrude')
merge = net.node('merge_all')
out   = net.node('OUT_city')
info  = {
    'road_extrude_exists': ext is not None,
    'extrude_dist':  ext.parm('dist').eval() if ext else None,
    'extrude_pts':   len(ext.geometry().points()) if ext else 0,
    'extrude_prims': len(ext.geometry().prims()) if ext else 0,
    'merge_inputs':  [i.name() if i else None for i in merge.inputs()] if merge else [],
    'out_pts':       len(out.geometry().points()) if out else 0,
    'errors':        list(ext.errors()) if ext else [],
}
builtins._road_check = json.dumps(info)
"""

conn.execute(CODE)
raw = conn.eval("__import__('builtins')._road_check")
print(json.dumps(json.loads(raw), indent=2, ensure_ascii=False))
conn.close()
