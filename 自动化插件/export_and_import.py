"""
VirtualCity — 一键 Houdini 导出 FBX + UE5 导入
================================================
UE5 Editor 必须已运行（端口 30010）。
Houdini 必须已运行（RPYC 端口 18811）。

用法:
    uv run python 自动化插件/export_and_import.py
"""
import sys, os

# ── 1. Houdini 导出 FBX ──────────────────────────────
print("[1/2] Houdini 导出 FBX...")
import rpyc
conn = rpyc.classic.connect("localhost", 18811)
hou = conn.modules.hou

obj_net = hou.node('/obj')
out_net = hou.node('/out')

exports = {
    'buildings': ('/obj/pattaya_osm/post_normals', r'F:/VirtualCity/Houdini/Export/buildings_v001.fbx'),
    'roads':     ('/obj/pattaya_osm/road_strips',  r'F:/VirtualCity/Houdini/Export/roads_v001.fbx'),
    'terrain':   ('/obj/pattaya_osm/dem_terrain',  r'F:/VirtualCity/Houdini/Export/terrain_v001.fbx'),
}

for label, (sop_path, fbx_path) in exports.items():
    geo_name = f'_export_{label}'
    geo_node = hou.node(f'/obj/{geo_name}')
    if geo_node: geo_node.destroy()
    geo_node = obj_net.createNode('geo', geo_name)
    om = geo_node.createNode('object_merge', 'merge_src')
    om.parm('objpath1').set(sop_path)
    om.parm('xformtype').set(0)
    om.setDisplayFlag(True)

    rop = hou.node(f'/out/fbx_{label}')
    if rop: rop.destroy()
    rop = out_net.createNode('filmboxfbx', f'fbx_{label}')
    rop.parm('startnode').set(f'/obj/{geo_name}')
    rop.parm('sopoutput').set(fbx_path)
    rop.parm('trange').set(0)
    rop.parm('convertunits').set(1)        # 米 → 厘米（H-008）
    rop.parm('computesmoothinggroups').set(1)
    rop.render()
    geo_node.destroy()

    size = os.path.getsize(fbx_path) if os.path.exists(fbx_path) else 0
    print(f"  {label}: {size/1024:.1f} KB → {fbx_path}")

hou.hipFile.save()
conn.close()

# ── 2. 写触发文件，通知 UE5 执行导入 ────────────────
print("\n[2/2] 通知 UE5 导入 FBX...")
TRIGGER = r"F:/VirtualCity/.ue5_trigger"
IMPORT_SCRIPT = r"F:/VirtualCity/自动化插件/ue5_import_fbx.py"

with open(TRIGGER, "w", encoding="utf-8", newline="\n") as f:
    f.write(IMPORT_SCRIPT)

print(f"  触发文件已写入: {TRIGGER}")
print("  UE5 将在 2 秒内自动执行导入（请查看 UE5 Output Log）")
