import rpyc
conn = rpyc.classic.connect('127.0.0.1', 18811)
CODE = """
import hou, json, builtins
net = hou.node('/obj/pattaya_osm')
rs  = net.node('road_strips')
out = net.node('OUT_city')
g   = rs.geometry()
g2  = out.geometry() if out else None
info = {
    'road_strips_pts':   len(g.points()),
    'road_strips_prims': len(g.prims()),
    'out_pts':           len(g2.points()) if g2 else 0,
    'rs_errors':         list(rs.errors()),
}
builtins._verify_result = json.dumps(info)
"""
conn.execute(CODE)
import json
raw = conn.eval("__import__('builtins')._verify_result")
print(json.dumps(json.loads(raw), indent=2))
conn.close()
