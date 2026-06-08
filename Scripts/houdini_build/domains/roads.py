"""Road domain build helpers."""
from __future__ import annotations

from dataclasses import dataclass

import houdini_sops

from .contract import DomainContract


CONTRACT = DomainContract(
    key="roads",
    label="道路",
    depends_on=("terrain",),
    final_nodes=("road_clipped", "road_color"),
)


@dataclass(frozen=True)
class RoadSourceChain:
    raw_node: object
    api_shared_topology_node: object
    centerline_resample_node: object
    junction_curve_smooth_node: object
    mesh_input: object


def build_raw_api_lines(hou, net, obj_path: str, osm):
    """Extract raw Map API road lines directly from osm_import."""
    raw_lines_code = houdini_sops.load("road_api_raw_lines.py")
    api_raw_node = hou.node(obj_path + "/road_api_raw_lines")
    if api_raw_node is None:
        api_raw_node = net.createNode("python", "road_api_raw_lines")
    api_raw_node.setInput(0, osm, 0)
    api_raw_node.parm("python").set(raw_lines_code)
    api_raw_node.cook(force=True)
    print("  road_api_raw_lines connected: osm_import -> raw map API road lines")
    return api_raw_node


def build_shared_topology(
    hou,
    net,
    obj_path: str,
    source_node,
    node_name: str,
    enabled: bool,
    fuse_tolerance_m: float,
    intersection_tolerance_m: float,
    max_segments: int,
    downstream_node=None,
):
    """Create shared centerline points at fused vertices and road crossings."""
    shared_code = houdini_sops.load(
        "road_shared_topology.py",
        ENABLED=1 if enabled else 0,
        FUSE_TOLERANCE=fuse_tolerance_m,
        INTERSECTION_TOLERANCE=intersection_tolerance_m,
        MAX_SEGMENTS=max_segments,
    )
    shared_node = hou.node(obj_path + "/" + node_name)
    if shared_node is None:
        shared_node = net.createNode("python", node_name)
    shared_node.setInput(0, source_node, 0)
    shared_node.parm("python").set(shared_code)
    shared_node.cook(force=True)
    if downstream_node is not None:
        downstream_node.setInput(0, shared_node, 0)
    geo = shared_node.geometry()
    try:
        status = geo.attribValue("road_shared_topology_status")
        intersections = geo.attribValue("road_shared_topology_intersections")
        endpoint_splits = geo.attribValue("road_shared_topology_endpoint_splits")
        fused = geo.attribValue("road_shared_topology_fused_points")
        fallbacks = geo.attribValue("road_shared_topology_fallbacks")
    except Exception:
        status = "unknown"
        intersections = 0
        endpoint_splits = 0
        fused = 0
        fallbacks = 0
    print("  {}: status={} intersections={} endpoint_splits={} fused_points={} fallbacks={}".format(
        node_name, status, int(intersections), int(endpoint_splits), int(fused), int(fallbacks)))
    return shared_node


def build_centerline_resample(
    hou,
    net,
    obj_path: str,
    raw_node,
    enabled: bool,
    target_spacing_m: float,
    preserve_bend_deg: float,
):
    """Normalize centerline point spacing while keeping raw API lines intact."""
    resample_code = houdini_sops.load(
        "road_centerline_resample.py",
        ENABLED=1 if enabled else 0,
        TARGET_SPACING=target_spacing_m,
        PRESERVE_BEND_DEG=preserve_bend_deg,
    )
    resample_node = hou.node(obj_path + "/road_centerline_resample")
    if resample_node is None:
        resample_node = net.createNode("python", "road_centerline_resample")
    resample_node.setInput(0, raw_node, 0)
    resample_node.parm("python").set(resample_code)
    resample_node.cook(force=True)
    geo = resample_node.geometry()
    try:
        status = geo.attribValue("road_centerline_resample_status")
        inserted = geo.attribValue("road_centerline_resample_inserted_points")
        max_before = geo.attribValue("road_centerline_resample_max_segment_before")
        max_after = geo.attribValue("road_centerline_resample_max_segment_after")
    except Exception:
        status = "unknown"
        inserted = 0
        max_before = 0.0
        max_after = 0.0
    print("  road_centerline_resample: status={} spacing={:.2f}m inserted={} max_seg {:.2f}->{:.2f}m".format(
        status, float(target_spacing_m), int(inserted), float(max_before), float(max_after)))
    return resample_node


def build_junction_curve_smooth(
    hou,
    net,
    obj_path: str,
    source_node,
    enabled: bool,
    curve_distance_m: float,
    min_branch_distance_m: float,
    min_angle_deg: float,
    max_angle_deg: float,
    arc_spacing_m: float,
    smooth_iterations: int,
    max_junctions: int,
):
    """Round shared road junctions by rewriting local centerline spans."""
    smooth_code = houdini_sops.load(
        "road_junction_curve_smooth.py",
        ENABLED=1 if enabled else 0,
        CURVE_DISTANCE=curve_distance_m,
        MIN_BRANCH_DISTANCE=min_branch_distance_m,
        MIN_ANGLE_DEG=min_angle_deg,
        MAX_ANGLE_DEG=max_angle_deg,
        ARC_SPACING=arc_spacing_m,
        SMOOTH_ITERATIONS=smooth_iterations,
        MAX_JUNCTIONS=max_junctions,
        REUSE_TOLERANCE=0.01,
    )
    smooth_node = hou.node(obj_path + "/road_junction_curve_smooth")
    if smooth_node is None:
        smooth_node = net.createNode("python", "road_junction_curve_smooth")
    smooth_node.setInput(0, source_node, 0)
    smooth_node.parm("python").set(smooth_code)
    smooth_node.cook(force=True)
    geo = smooth_node.geometry()
    try:
        status = geo.attribValue("road_junction_curve_smooth_status")
        processed = geo.attribValue("road_junction_curve_smooth_processed_junctions")
        arcs = geo.attribValue("road_junction_curve_smooth_arc_prims")
        skipped = geo.attribValue("road_junction_curve_smooth_skipped_junctions")
        fallbacks = geo.attribValue("road_junction_curve_smooth_fallbacks")
    except Exception:
        status = "unknown"
        processed = 0
        arcs = 0
        skipped = 0
        fallbacks = 0
    print("  road_junction_curve_smooth: status={} processed={} arcs={} skipped={} fallbacks={}".format(
        status, int(processed), int(arcs), int(skipped), int(fallbacks)))
    return smooth_node


def remove_legacy_road_nodes(hou, obj_path: str) -> None:
    """Remove retired road/debug nodes so the SOP network exposes one road chain."""
    for road_legacy_node_name in (
        "road_centerline_filter",
        "road_width_flat",
        "road_vertical_smoother",
        "snap_roads_to_terrain1",
        "resample_roads",
        "road_shared_topology",
        "extract_roads",
        "road_junction_arc_smoother",
        "road_source",
        "road_topology_builder",
        "road_strips",
        "road_graph_filter",
    ):
        road_legacy_node = hou.node(obj_path + "/" + road_legacy_node_name)
        if road_legacy_node is not None:
            try:
                road_legacy_node.destroy()
                print("  raw road output: removed legacy road node " + road_legacy_node_name)
            except Exception as remove_exc:
                print("  [WARN] could not remove legacy road node {}: {}".format(
                    road_legacy_node_name, remove_exc))


def build_source_chain(
    hou,
    net,
    obj_path: str,
    osm,
    centerline_resample_enabled: bool = True,
    centerline_resample_spacing_m: float = 2.0,
    centerline_resample_preserve_bend_deg: float = 8.0,
    shared_topology_enabled: bool = True,
    shared_topology_fuse_tolerance_m: float = 0.35,
    shared_topology_intersection_tolerance_m: float = 0.08,
    shared_topology_max_segments: int = 2500,
    junction_curve_smooth_enabled: bool = True,
    junction_curve_smooth_distance_m: float = 5.0,
    junction_curve_smooth_min_branch_distance_m: float = 2.0,
    junction_curve_smooth_min_angle_deg: float = 25.0,
    junction_curve_smooth_max_angle_deg: float = 155.0,
    junction_curve_smooth_arc_spacing_m: float = 1.0,
    junction_curve_smooth_iterations: int = 1,
    junction_curve_smooth_max_junctions: int = 800,
) -> RoadSourceChain:
    """Build the stable raw-road source chain used by terrain and final road output."""
    remove_legacy_road_nodes(hou, obj_path)
    raw_node = build_raw_api_lines(hou, net, obj_path, osm)
    api_shared_topology_node = build_shared_topology(
        hou,
        net,
        obj_path,
        raw_node,
        "road_api_shared_topology",
        shared_topology_enabled,
        shared_topology_fuse_tolerance_m,
        shared_topology_intersection_tolerance_m,
        shared_topology_max_segments,
    )
    centerline_resample_node = build_centerline_resample(
        hou,
        net,
        obj_path,
        api_shared_topology_node,
        centerline_resample_enabled,
        centerline_resample_spacing_m,
        centerline_resample_preserve_bend_deg,
    )
    junction_curve_smooth_node = build_junction_curve_smooth(
        hou,
        net,
        obj_path,
        centerline_resample_node,
        junction_curve_smooth_enabled,
        junction_curve_smooth_distance_m,
        junction_curve_smooth_min_branch_distance_m,
        junction_curve_smooth_min_angle_deg,
        junction_curve_smooth_max_angle_deg,
        junction_curve_smooth_arc_spacing_m,
        junction_curve_smooth_iterations,
        junction_curve_smooth_max_junctions,
    )
    print("  road chain locked: road_api_raw_lines -> road_api_shared_topology -> road_centerline_resample -> road_junction_curve_smooth")
    return RoadSourceChain(
        raw_node=raw_node,
        api_shared_topology_node=api_shared_topology_node,
        centerline_resample_node=centerline_resample_node,
        junction_curve_smooth_node=junction_curve_smooth_node,
        mesh_input=junction_curve_smooth_node,
    )


def build_clipped_lines(
    hou,
    net,
    obj_path: str,
    road_mesh_input,
    snap_target,
    road_drape_vex,
    road_output_mode: str,
    asset_filter_code,
    remake_asset_filter,
):
    """Drape raw road lines to terrain and filter them to the active area."""
    old_drape = hou.node(obj_path + "/snap_road_strips")
    if old_drape:
        old_drape.destroy()
    snap_road_strips = net.createNode("attribwrangle", "snap_road_strips")
    snap_road_strips.setInput(0, road_mesh_input)
    snap_road_strips.setInput(1, snap_target)
    snap_road_strips.parm("class").set(2)  # Point
    snap_road_strips.parm("snippet").set(road_drape_vex)
    snap_road_strips.cook(force=True)
    rs_geo = snap_road_strips.geometry()
    rs_pts = rs_geo.intrinsicValue("pointcount")
    rs_bb = rs_geo.boundingBox()
    rs_ymin = rs_bb.minvec()[1]
    print("  snap_road_strips: mode={} pts={} prims={} Y_min={:.2f}m".format(
        road_output_mode, rs_pts, rs_geo.intrinsicValue("primitivecount"), rs_ymin))

    old_bbox_clip = hou.node(obj_path + "/road_bbox_clip")
    if old_bbox_clip:
        old_bbox_clip.destroy()
    road_bbox_clip = net.createNode("python", "road_bbox_clip")
    road_bbox_clip.setInput(0, snap_road_strips)
    road_bbox_clip.parm("python").set(asset_filter_code("primitive"))
    road_bbox_clip.cook(force=True)
    print("  road_bbox_clip: pts={} prims={} preserved_prims={}".format(
        road_bbox_clip.geometry().intrinsicValue("pointcount"),
        road_bbox_clip.geometry().intrinsicValue("primitivecount"),
        road_bbox_clip.geometry().attribValue("road_bbox_preserved_ngon_count")))

    old_final_drape = hou.node(obj_path + "/snap_road_clipped")
    if old_final_drape:
        old_final_drape.destroy()
    snap_road_clipped = net.createNode("attribwrangle", "snap_road_clipped")
    snap_road_clipped.setInput(0, road_bbox_clip)
    snap_road_clipped.setInput(1, snap_target)
    snap_road_clipped.parm("class").set(2)  # Point
    snap_road_clipped.parm("snippet").set(road_drape_vex)
    snap_road_clipped.cook(force=True)
    print("  snap_road_clipped: pts={} Y_min={:.2f}m".format(
        snap_road_clipped.geometry().intrinsicValue("pointcount"),
        snap_road_clipped.geometry().boundingBox().minvec()[1]))

    road_clip = remake_asset_filter("snap_road_clipped", "road_clip_mark", "road_clipped", "primitive")

    old_frag_cleanup = hou.node(obj_path + "/road_fragment_cleanup")
    if old_frag_cleanup:
        old_frag_cleanup.destroy()
        print("  road_fragment_cleanup: 已移除，road_clipped 直接进入 road_profile_apply")
    return road_clip


def apply_profiles(hou, net, obj_path: str, root_str: str, road_clip, enabled: bool):
    """Optionally write road profile attributes without changing geometry."""
    road_profile_src = road_clip
    try:
        old_prof = hou.node(obj_path + "/road_profile_apply")
        if enabled and road_clip is not None:
            if old_prof:
                old_prof.destroy()
            profile_apply_code = houdini_sops.load("road_profile_apply.py", ROOT=root_str)
            road_prof = net.createNode("python", "road_profile_apply")
            road_prof.setInput(0, road_clip)
            road_prof.parm("python").set(profile_apply_code)
            road_prof.cook(force=True)
            road_profile_src = road_prof
            prof_geo = road_prof.geometry()
            try:
                applied = prof_geo.attribValue("road_profile_applied_prims")
                fallback = prof_geo.attribValue("road_profile_fallback_prims")
            except Exception:
                applied = prof_geo.intrinsicValue("primitivecount")
                fallback = 0
            print("  road_profile_apply: 已注入 applied={} fallback={}（从 Config/road_profiles.json 读取截面参数）".format(
                applied, fallback))
        elif old_prof:
            old_prof.destroy()
            print("  road_profile_apply: 已关闭并移除旧节点")
    except Exception as exc:
        print(f"  [WARN] road_profile_apply 注入失败: {exc}")
    return road_profile_src


def apply_curb_variation(hou, net, obj_path: str, root_str: str, road_profile_src, enabled: bool):
    """Optionally write small curb variation attributes for road details."""
    road_curb_src = road_profile_src
    try:
        old_curb = hou.node(obj_path + "/road_curb_variation")
        if enabled and road_profile_src is not None:
            if old_curb:
                old_curb.destroy()
            curb_variation_code = houdini_sops.load("road_curb_variation.py", ROOT=root_str)
            road_curb = net.createNode("python", "road_curb_variation")
            road_curb.setInput(0, road_profile_src)
            road_curb.parm("python").set(curb_variation_code)
            road_curb.cook(force=True)
            road_curb_src = road_curb
            try:
                curb_applied = road_curb.geometry().attribValue("road_curb_variation_applied_prims")
            except Exception:
                curb_applied = road_curb.geometry().intrinsicValue("primitivecount")
            print("  road_curb_variation: 已注入 applied={} (±2cm 随机起伏)".format(curb_applied))
        elif old_curb:
            old_curb.destroy()
            print("  road_curb_variation: 已关闭并移除旧节点")
    except Exception as exc:
        print(f"  [WARN] road_curb_variation 注入失败: {exc}")
    return road_curb_src


def color_roads(hou, net, obj_path: str, src_node, rgb):
    """Create the public road_color output."""
    old = hou.node(obj_path + "/road_color")
    if old:
        old.destroy()
    road_color = net.createNode("attribwrangle", "road_color")
    road_color.setInput(0, src_node)
    road_color.parm("class").set(2)  # Point
    road_color.parm("snippet").set("@Cd = set({:.4f}, {:.4f}, {:.4f});".format(*rgb))
    road_color.cook(force=True)
    return road_color


def finalize_surface(hou, obj_path: str, road_colored):
    """Keep the current road output as flat/raw line geometry and remove old extrude nodes."""
    for old_road_node in ("road_pre_extrude_dissolve", "road_pre_extrude_fuse", "road_extrude"):
        old = hou.node(obj_path + "/" + old_road_node)
        if old:
            old.destroy()
            print("  道路挤出节点移除: " + old_road_node)
    road_surface = road_colored
    print("  road_surface: 使用平面道路面片（无挤出） pts={} prims={}".format(
        road_surface.geometry().intrinsicValue("pointcount"),
        road_surface.geometry().intrinsicValue("primitivecount")))
    return road_surface
