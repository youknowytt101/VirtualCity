"""
给道路添加挤出效果（road_extrude SOP）
在 road_color（或 road_clipped） -> merge_all 之间插入 polyextrude 节点
"""
import rpyc

conn = rpyc.classic.connect('127.0.0.1', 18811)

CODE = '''
import hou
net = hou.node('/obj/pattaya_osm')

EXTRUDE_DIST = 0.18   # 道路厚度，单位 m（可按需调整）

# ── 找道路末端节点（road_color > road_clipped > road_strips 优先级）
src = None
for candidate in ['road_color', 'road_clipped', 'snap_road_strips']:
    src = net.node(candidate)
    if src:
        break

if not src:
    print('[ERR] 找不到道路源节点')
else:
    # ── 删掉旧的同名节点（避免重复）
    old = net.node('road_extrude')
    if old:
        old.destroy()

    # ── 创建 polyextrude 节点
    ext = net.createNode('polyextrude::2.0', 'road_extrude')
    ext.setInput(0, src, 0)

    # 挤出距离（沿法线方向）
    ext.parm('dist').set(EXTRUDE_DIST)
    # 仅输出挤出侧面 + 顶面（不要背面，减少面数）
    ext.parm('outputback').set(0)
    ext.parm('outputfront').set(1)
    ext.parm('outputside').set(1)
    # 按图元法线挤出（道路贴地后法线朝上，效果正确）
    ext.parm('xformspace').set(0)  # Local

    ext.cook(force=True)
    g_ext = ext.geometry()

    # ── 重新连接 merge_all：把旧 road 输入替换为 road_extrude
    merge = net.node('merge_all')
    if merge:
        for i, inp in enumerate(merge.inputs()):
            if inp and inp.name() in ('road_color','road_clipped','snap_road_strips','road_strips'):
                merge.setInput(i, ext, 0)
                print(f"  merge_all input[{i}] -> road_extrude")
                break
        merge.cook(force=True)

    # ── OUT_city 刷新
    out = net.node('OUT_city') or net.node('merge_all')
    if out:
        out.setDisplayFlag(True)
        out.setRenderFlag(True)
        out.cook(force=True)
        g_out = out.geometry()
        print(f"[OK] road_extrude 完成: pts={len(g_ext.points())} prims={len(g_ext.prims())}")
        print(f"[OK] OUT_city: pts={len(g_out.points())} prims={len(g_out.prims())}")
    
    hou.hipFile.save()
    print("[OK] hip saved")

print("=== DONE ===")
'''

try:
    conn.execute(CODE)
    print("Script executed in Houdini.")
except Exception as e:
    print(f"[ERR] {e}")
finally:
    conn.close()
