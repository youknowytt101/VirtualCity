"""
VirtualCity — 一键 Houdini 导出 FBX + UE5 导入
================================================
UE5 Editor 必须已运行（端口 30010）。
Houdini 必须已运行（RPYC 端口 18811）。

用法:
    uv run python Scripts/export_and_import.py
"""
import sys, os, time
from vc_paths import HIP, EXPORT, TRIGGER, SCRIPTS, load_active_area

HIP = HIP.as_posix()
EXPORT = EXPORT.as_posix()

# OBJ 网络名：从 active_area.json 读取
_cfg = load_active_area()
_OBJ_NET = _cfg.get('obj_network', 'city_gen')
_OBJ = '/obj/' + _OBJ_NET

# label, 首选SOP, 备用SOP, 输出FBX
EXPORTS = [
    ('buildings', f'{_OBJ}/bld_clipped',  f'{_OBJ}/post_normals', 'buildings_v001.fbx'),
    ('roads',     f'{_OBJ}/road_clipped', f'{_OBJ}/road_strips',  'roads_v001.fbx'),
    ('terrain',   f'{_OBJ}/dem_terrain',  f'{_OBJ}/dem_terrain',  'terrain_v001.fbx'),
]


def connect_hou():
    """H-001: 连接 Houdini，若 hip 未加载则自动加载"""
    import rpyc
    conn = rpyc.classic.connect('localhost', 18811,
                                config={'sync_request_timeout': 300})
    hou = conn.modules.hou
    if 'untitled' in hou.hipFile.path():
        hou.hipFile.load(HIP, suppress_save_prompt=True)
        print(f'  [hip] 已加载: {HIP}')
    return conn, hou


def resolve_sop_path(hou, path):
    if hou.node(path):
        return path
    if _OBJ_NET == 'city_gen' and path.startswith('/obj/city_gen/'):
        legacy_path = path.replace('/obj/city_gen/', '/obj/pattaya_osm/', 1)
        if hou.node(legacy_path):
            return legacy_path
    return path


def export_one(label, sop_primary, sop_fallback, fbx_name):
    """E-001: 每个 FBX 独立连接导出，崩溃不传染其他项目"""
    fbx_path = os.path.join(EXPORT, fbx_name).replace('\\', '/')
    conn, hou = connect_hou()
    try:
        sop_primary = resolve_sop_path(hou, sop_primary)
        sop_fallback = resolve_sop_path(hou, sop_fallback)
        sop_path = sop_primary if hou.node(sop_primary) else sop_fallback
        src = hou.node(sop_path)
        if src is None:
            print(f'  [{label}] 跳过: 节点不存在 {sop_path}')
            return False
        # E-002: 导出前确认几何非空
        src.cook(force=False)
        pts = src.geometry().intrinsicValue('pointcount')
        if pts == 0:
            print(f'  [{label}] 跳过: 几何为空 (E-002)')
            return False

        geo_name = f'_export_{label}'
        obj_net  = hou.node('/obj')
        out_net  = hou.node('/out')

        old = hou.node(f'/obj/{geo_name}')
        if old: old.destroy()
        geo_node = obj_net.createNode('geo', geo_name)
        om = geo_node.createNode('object_merge', 'merge_src')
        om.parm('objpath1').set(sop_path)
        om.parm('xformtype').set(0)
        om.setDisplayFlag(True)

        old_rop = hou.node(f'/out/fbx_{label}')
        if old_rop: old_rop.destroy()
        rop = out_net.createNode('filmboxfbx', f'fbx_{label}')
        rop.parm('startnode').set(f'/obj/{geo_name}')
        rop.parm('sopoutput').set(fbx_path)
        rop.parm('trange').set(0)
        rop.parm('convertunits').set(1)
        rop.parm('computesmoothinggroups').set(1)
        rop.render()
        geo_node.destroy()

        size = os.path.getsize(fbx_path) if os.path.exists(fbx_path) else 0
        if size < 1000:
            print(f'  [{label}] 警告: FBX 过小 ({size} bytes)，可能导出失败')
            return False
        print(f'  [{label}] OK: {size/1024:.1f} KB')
        return True
    finally:
        try: conn.close()
        except Exception: pass


# ── 1. 逐个导出 FBX ──────────────────────────────────
print('[1/2] Houdini 导出 FBX...')
os.makedirs(EXPORT, exist_ok=True)
failed = []
for label, primary, fallback, fbx in EXPORTS:
    ok = export_one(label, primary, fallback, fbx)
    if not ok:
        failed.append(label)
    time.sleep(1)

if failed:
    print(f'  [WARN] 失败: {failed}，其余已导出')
else:
    print('  [OK] 全部 FBX 导出完成')

# ── 2. 写触发文件，通知 UE5 执行导入 ────────────────
print("\n[2/2] 通知 UE5 导入 FBX...")
TRIGGER = TRIGGER.as_posix()
IMPORT_SCRIPT = (SCRIPTS / "ue5_import_fbx.py").as_posix()

with open(TRIGGER, "w", encoding="utf-8", newline="\n") as f:
    f.write(IMPORT_SCRIPT)

print(f"  触发文件已写入: {TRIGGER}")
print("  UE5 将在 2 秒内自动执行导入（请查看 UE5 Output Log）")
