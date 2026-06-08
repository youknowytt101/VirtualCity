"""Building domain build helpers."""
from __future__ import annotations

import houdini_sops

from .contract import DomainContract


CONTRACT = DomainContract(
    key="buildings",
    label="建筑",
    depends_on=("terrain",),
    final_nodes=("bld_clipped", "bld_with_foundation"),
)


def set_height_promote_restore_first(hou, obj_path: str) -> None:
    """Keep height attributes from bleeding between adjacent fused buildings."""
    for node_name in ["promote_height", "restore_height"]:
        node = hou.node(obj_path + "/" + node_name)
        if node and node.parm("method"):
            node.parm("method").set(1)  # 1 = First


def patch_footprint_divide_sop(hou, obj_path: str) -> None:
    """Keep building footprints as n-gons before downstream bevel/extrude."""
    divide_bld = hou.node(obj_path + "/divide_bld")
    if divide_bld:
        divide_bld.parm("convex").set(0)
        divide_bld.parm("usemaxsides").set(0)
        print("  SOP 修复: divide_bld (Q-001: 关闭 convex+numsides → 保留 n-gon footprint)")


def patch_snap_and_height_sops(hou, obj_path: str) -> None:
    """Patch existing building snap/height SOPs without changing their names."""
    bld_snap_vex = houdini_sops.load("bld_snap.vex")
    snap_bld = hou.node(obj_path + "/snap_bld_to_terrain")
    if snap_bld:
        snap_bld.parm("class").set(1)   # Primitive
        snap_bld.parm("snippet").set(bld_snap_vex)
        print("  SOP 修复: snap_bld_to_terrain (逐顶点 MAX 高度)")

    proc_height_vex = houdini_sops.load("procedural_height.vex")
    procedural_height = hou.node(obj_path + "/procedural_height")
    if procedural_height:
        procedural_height.parm("snippet").set(proc_height_vex)
        print("  SOP 修复: procedural_height (P0: height_m<=0 fallback)")


def build_footprint_bevel(hou, net, obj_path: str):
    """Rebuild bld_footprint_bevel and reconnect extrude_buildings."""
    set_height_promote_restore_first(hou, obj_path)
    bevel_code = houdini_sops.load("bld_footprint_bevel.py")

    old_bevel = hou.node(obj_path + "/bld_footprint_bevel")
    if old_bevel:
        old_bevel.destroy()
    bld_footprint_bevel = net.createNode("python", "bld_footprint_bevel")
    restore_height = hou.node(obj_path + "/restore_height")
    bld_footprint_bevel.setInput(0, restore_height)
    bld_footprint_bevel.parm("python").set(bevel_code)
    bld_footprint_bevel.cook(force=True)

    extrude_buildings = hou.node(obj_path + "/extrude_buildings")
    if extrude_buildings:
        extrude_buildings.setInput(0, bld_footprint_bevel)
    print("  bld_footprint_bevel: pts={} prims={}".format(
        bld_footprint_bevel.geometry().intrinsicValue("pointcount"),
        bld_footprint_bevel.geometry().intrinsicValue("primitivecount")))
    return bld_footprint_bevel


def clip_buildings(remake_asset_filter):
    """Clip building body geometry through the shared asset filter helper."""
    return remake_asset_filter("post_normals", "bld_clip_mark", "bld_clipped", "component")


def build_foundation(hou, net, obj_path: str, bld_clip, snap_target, remake_asset_filter):
    """Build terrain-aware foundations and return the clipped foundation node."""
    foundation_code = houdini_sops.load("bld_foundation.py")

    old_foundation = hou.node(obj_path + "/bld_foundation")
    if old_foundation:
        old_foundation.destroy()
    bld_foundation = net.createNode("python", "bld_foundation")
    bld_foundation.setInput(0, bld_clip)
    bld_foundation.setInput(1, snap_target)
    bld_foundation.parm("python").set(foundation_code)
    bld_foundation.cook(force=True)
    print("  bld_foundation: pts={} prims={}".format(
        bld_foundation.geometry().intrinsicValue("pointcount"),
        bld_foundation.geometry().intrinsicValue("primitivecount")))

    return remake_asset_filter(
        "bld_foundation",
        "bld_foundation_clip_mark",
        "bld_foundation_clipped",
        "component",
    )


def _make_color_node(hou, net, obj_path: str, name: str, src_node, rgb):
    old = hou.node(obj_path + "/" + name)
    if old:
        old.destroy()
    node = net.createNode("attribwrangle", name)
    node.setInput(0, src_node)
    node.parm("class").set(2)  # Point
    node.parm("snippet").set("@Cd = set({:.4f}, {:.4f}, {:.4f});".format(*rgb))
    node.cook(force=True)
    return node


def color_and_finalize_buildings(hou, net, obj_path: str, bld_clip, foundation_clip, rgb):
    """Create bld_color/foundation color and the bld_with_foundation output."""
    bld_colored = _make_color_node(hou, net, obj_path, "bld_color", bld_clip, rgb)
    foundation_colored = None
    if foundation_clip:
        foundation_colored = _make_color_node(
            hou,
            net,
            obj_path,
            "bld_foundation_color",
            foundation_clip,
            rgb,
        )

    old_bld_final = hou.node(obj_path + "/bld_with_foundation")
    if old_bld_final:
        old_bld_final.destroy()
    old_bld_merge = hou.node(obj_path + "/bld_with_foundation_merge")
    if old_bld_merge:
        old_bld_merge.destroy()
    bld_merge = net.createNode("merge", "bld_with_foundation_merge")
    bld_merge.setInput(0, bld_colored)
    if foundation_colored:
        bld_merge.setInput(1, foundation_colored)
    bld_merge.cook(force=True)

    bld_final = net.createNode("normal", "bld_with_foundation")
    bld_final.setInput(0, bld_merge)
    if bld_final.parm("type"):
        bld_final.parm("type").set(1)  # Vertex normals
    if bld_final.parm("cuspangle"):
        bld_final.parm("cuspangle").set(0.0)  # hard building edges, no wall smoothing
    if bld_final.parm("normalize"):
        bld_final.parm("normalize").set(1)
    bld_final.cook(force=True)
    print("  bld_with_foundation: pts={} prims={}".format(
        bld_final.geometry().intrinsicValue("pointcount"),
        bld_final.geometry().intrinsicValue("primitivecount")))
    return bld_final
