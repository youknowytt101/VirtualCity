"""Terrain domain build helpers."""
from __future__ import annotations

import houdini_sops

from .contract import DomainContract


CONTRACT = DomainContract(
    key="terrain",
    label="地形",
    depends_on=(),
    final_nodes=("dem_subdivide", "terrain_color"),
)


def inject_dem_sops(hou, obj_path: str, root_str: str, cfg_file: str) -> None:
    """Patch DEM Python SOP source while preserving existing node names."""
    dem_import_code = houdini_sops.load("dem_import.py", ROOT=root_str, CFG=cfg_file)
    dem_terrain_code = houdini_sops.load("dem_terrain.py", ROOT=root_str, CFG=cfg_file)

    for node_path, code in [
        (obj_path + "/dem_import", dem_import_code),
        (obj_path + "/dem_terrain", dem_terrain_code),
    ]:
        node = hou.node(node_path)
        if node:
            node.parm("python").set(code)
            print("  SOP 修复: " + node_path.split("/")[-1])


def build_snap_target(hou, net, obj_path: str, road_width_node,
                      roads_cut_fill_enabled: bool, cut_fill_vex: str):
    """Build the terrain snap target node consumed by buildings and roads."""
    dem_terrain = hou.node(obj_path + "/dem_terrain")
    snap_target = hou.node(obj_path + "/dem_subdivide")
    if snap_target is None:
        snap_target = net.createNode("subdivide", "dem_subdivide")

    if roads_cut_fill_enabled and road_width_node is not None:
        cut_fill_target = hou.node(obj_path + "/dem_cut_and_fill")
        if cut_fill_target is None:
            cut_fill_target = net.createNode("attribwrangle", "dem_cut_and_fill")
        cut_fill_target.setInput(0, dem_terrain)
        cut_fill_target.setInput(1, road_width_node)
        cut_fill_target.parm("class").set(2)  # Point level
        cut_fill_target.parm("snippet").set(cut_fill_vex)
        cut_fill_target.cook(force=True)
        print("  dem_cut_and_fill VEX 削坡平整完成: pts={}".format(
            cut_fill_target.geometry().intrinsicValue("pointcount")))
        snap_target.setInput(0, cut_fill_target)
    else:
        if roads_cut_fill_enabled:
            print("  [WARN] roads_cut_fill_enabled 已开启，但当前道路主链没有宽度输入；跳过 dem_cut_and_fill")
        snap_target.setInput(0, dem_terrain)

    snap_target.parm("algorithm").set(4)   # OpenSubdiv Bilinear
    snap_target.parm("iterations").set(2)  # 30m -> ~7.5m
    snap_target.cook(force=True)
    print("  dem_subdivide: pts={} prims={} (Bilinear iterations=2)".format(
        snap_target.geometry().intrinsicValue("pointcount"),
        snap_target.geometry().intrinsicValue("primitivecount")))
    return snap_target


def retarget_snap_consumers(hou, obj_path: str, snap_target) -> None:
    """Point existing building/road snap nodes at the terrain domain output."""
    for snap_name in ["snap_bld_to_terrain"]:
        node = hou.node(obj_path + "/" + snap_name)
        if node:
            node.setInput(1, snap_target)


def color_terrain(hou, net, obj_path: str, snap_target, rgb):
    """Create the public terrain_color node used by assembly/export."""
    old = hou.node(obj_path + "/terrain_color")
    if old:
        old.destroy()
    node = net.createNode("attribwrangle", "terrain_color")
    node.setInput(0, snap_target)
    node.parm("class").set(2)  # Point
    node.parm("snippet").set("@Cd = set({:.4f}, {:.4f}, {:.4f});".format(*rgb))
    node.cook(force=True)
    return node
