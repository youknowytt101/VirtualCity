"""把 _road_strips_v2.py 推送到 road_strips 节点并重新 cook 下游链"""
import rpyc
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
code_v2 = (SCRIPTS / '_road_strips_v2.py').read_text(encoding='utf-8')

conn = rpyc.classic.connect('127.0.0.1', 18811)

EXEC = '''
import hou, json, builtins

net  = hou.node('/obj/pattaya_osm')
rs   = net.node('road_strips')
rs.parm('python').set(_road_strips_code)
rs.cook(force=True)

g = rs.geometry()
info = {'road_strips_pts': len(g.points()), 'road_strips_prims': len(g.prims()), 'errors': list(rs.errors())}

# Cook downstream
for name in ['snap_road_strips', 'road_clip_mark', 'road_clipped',
             'road_color', 'road_extrude', 'merge_all', 'OUT_city']:
    n = net.node(name)
    if n:
        n.cook(force=True)

out = net.node('OUT_city')
if out:
    out.setDisplayFlag(True)
    out.setRenderFlag(True)
    g2 = out.geometry()
    info['out_pts'] = len(g2.points())

builtins._push_result = json.dumps(info)
'''

import time, json

# 1. 注入代码到 Houdini session
conn.execute("import hou, threading, json, builtins")
conn.namespace['_road_strips_code'] = code_v2

# 2. 启动后台线程（不阻塞 rpyc transport）
LAUNCH = """
import threading, hou, json, builtins
hou.session._rs_done = False
hou.session._rs_result = {}

def _run():
    try:
        net = hou.node('/obj/pattaya_osm')
        rs  = net.node('road_strips')
        rs.parm('python').set(_road_strips_code)
        rs.cook(force=True)
        g = rs.geometry()
        info = {'pts': len(g.points()), 'prims': len(g.prims()), 'errors': list(rs.errors())}
        for name in ['snap_road_strips','road_clip_mark','road_clipped',
                     'road_color','road_extrude','merge_all','OUT_city']:
            n = net.node(name)
            if n:
                n.cook(force=True)
        out = net.node('OUT_city')
        if out:
            out.setDisplayFlag(True)
            out.setRenderFlag(True)
            info['out_pts'] = len(out.geometry().points())
        hou.session._rs_result = info
    except Exception as e:
        hou.session._rs_result = {'error': str(e)}
    hou.session._rs_done = True

threading.Thread(target=_run, daemon=True).start()
"""
conn.execute(LAUNCH)
print("Cook started in Houdini background thread...")

# 3. 轮询直到完成
for i in range(120):   # 最多等 2 分钟
    time.sleep(5)
    done = conn.eval("hou.session._rs_done")
    if done:
        result = conn.eval("hou.session._rs_result")
        print(json.dumps(dict(result), indent=2))
        break
    elapsed = (i+1)*5
    print(f"  waiting... {elapsed}s")
else:
    print("[TIMEOUT] cook took >2 min")

conn.close()
