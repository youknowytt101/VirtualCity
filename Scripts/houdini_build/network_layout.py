"""Visual grouping for the generated Houdini SOP network."""
from __future__ import annotations

from dataclasses import dataclass


BOX_PAD_X = 1.35
BOX_PAD_Y = 0.55
COLUMN_SPACING = 7.4
ROW_SPACING = 1.35
SIDE_BRANCH_OFFSET_X = 2.8
SIDE_BRANCH_OFFSET_Y = -0.15


SIDE_BRANCH_LAYOUT: dict[str, tuple[str, float, float]] = {
    "road_capsule_surface_preview": (
        "road_profile_apply",
        SIDE_BRANCH_OFFSET_X,
        SIDE_BRANCH_OFFSET_Y,
    ),
}


@dataclass(frozen=True)
class NetworkGroup:
    key: str
    label: str
    color: tuple[float, float, float]
    nodes: tuple[str, ...]


NODE_NOTES: dict[str, str] = {
    "osm_import": "[输入] 读取 active_area 指定范围的 OSM/地图道路与建筑原始数据。",
    "dem_import": "[地形] 读取当前区域 DEM 高程栅格并转为 Houdini 几何。",
    "dem_terrain": "[地形] 将 DEM 点云/网格整理为可贴附的基础地形。",
    "dem_cut_and_fill": "[地形] 对道路附近地形做局部挖填，减少道路穿插与悬空。",
    "dem_subdivide": "[地形] 细分地形，作为道路和建筑贴地的 snap target。",
    "terrain_color_cd": "[地形] 给最终地形写入基础显示颜色。",
    "terrain_color": "[地形] 为带颜色的最终地形生成顶点法线，作为地形公开输出。",
    "extract_buildings": "[建筑] 从 OSM/地图数据中提取建筑 footprint。",
    "snap_bld_to_terrain": "[建筑] 将建筑 footprint 贴合到地形高度。",
    "procedural_height": "[建筑] 根据楼层、类型或默认规则生成建筑高度。",
    "fix_normals": "[建筑] 修正建筑面法线方向，为挤出和渲染做准备。",
    "fix_winding": "[建筑] 统一 footprint 顶点绕序，避免反面和异常挤出。",
    "promote_height": "[建筑] 将高度信息提升/整理到后续节点可读取的属性。",
    "fuse_bld": "[建筑] 合并重复建筑点，减少缝隙和碎片。",
    "divide_bld": "[建筑] 清理建筑多边形拓扑，保证后续 bevel/extrude 稳定。",
    "restore_height": "[建筑] 在拓扑清理后恢复建筑高度属性。",
    "bld_footprint_bevel": "[建筑] 对建筑 footprint 做倒角，软化直角轮廓。",
    "extrude_buildings": "[建筑] 按高度挤出建筑体块。",
    "post_normals": "[建筑] 重新计算建筑最终法线。",
    "bld_clipped": "[建筑] 按当前区域边界裁剪建筑主体。",
    "bld_color": "[建筑] 给建筑主体写入基础显示颜色。",
    "bld_foundation": "[建筑] 生成建筑地基，遮盖坡地贴合处的缝隙。",
    "bld_foundation_clipped": "[建筑] 按当前区域边界裁剪建筑地基。",
    "bld_foundation_color": "[建筑] 给建筑地基写入基础显示颜色。",
    "bld_with_foundation_merge": "[建筑] 合并建筑主体与地基。",
    "bld_with_foundation": "[建筑] 输出带地基的最终建筑几何。",
    "road_api_raw_lines": "[道路] 从地图 API/OSM 属性生成原始道路中心线。",
    "road_api_shared_topology": "[道路] 建立共享拓扑，融合端点并补齐交叉关系。",
    "road_centerline_resample": "[道路] 统一中心线点距，同时保留关键转角。",
    "road_turn_curve_smooth": "[道路] 平滑普通道路硬转角；不处理真实路口。",
    "road_vertex_cleanup": "[道路] 清理并均匀化道路顶点，保持共享点连接。",
    "road_junction_curve_smooth": "[道路] 在真实路口附近重写局部中心线并生成相切圆弧。",
    "snap_road_strips": "[道路] 将道路中心线/面点贴合到当前地形。",
    "road_bbox_clip": "[道路] 按当前区域边界裁剪道路几何。",
    "snap_road_clipped": "[道路] 裁剪后再次贴地，避免边界处高度漂移。",
    "road_clipped": "[道路] 标记并输出区域内道路几何。",
    "road_profile_apply": "[道路] 根据 road_profiles.json 注入车道数、车道宽、人行道和路缘属性。",
    "road_capsule_surface_preview": "[道路面主输出] 从中心线生成两头半圆、左右分开的胶囊车道面；进入 road_surface_color。",
    "road_curb_variation": "[道路] 注入路缘微小起伏属性，增加道路细节变化。",
    "road_color": "[道路调试] 给干净道路中心线写入颜色；保留为 debug，不进入 OUT_city。",
    "road_surface_color_cd": "[道路面主输出] 给胶囊车道面写入基础显示颜色。",
    "road_surface_color": "[道路面主输出] 为带颜色的胶囊车道面生成顶点法线；作为 merge_all 的道路输入。",
    "merge_all": "[总装] 合并建筑、道路和地形为城市总输出。",
    "OUT_city": "[总装] 最终城市输出节点，供视口、导出和 QA 使用。",
    "road_junction_tangent_arcs": "[旧实验] 早期路口相切圆弧实验节点；不属于当前主道路链路。",
}


GROUPS: tuple[NetworkGroup, ...] = (
    NetworkGroup(
        key="inputs",
        label="[VC] 输入 Inputs",
        color=(0.32, 0.32, 0.32),
        nodes=(
            "osm_import",
        ),
    ),
    NetworkGroup(
        key="terrain",
        label="[VC] 地形 Terrain",
        color=(0.20, 0.32, 0.45),
        nodes=(
            "dem_import",
            "dem_terrain",
            "dem_cut_and_fill",
            "dem_subdivide",
            "terrain_color_cd",
            "terrain_color",
        ),
    ),
    NetworkGroup(
        key="buildings",
        label="[VC] 建筑 Buildings",
        color=(0.46, 0.40, 0.34),
        nodes=(
            "extract_buildings",
            "snap_bld_to_terrain",
            "procedural_height",
            "fix_normals",
            "fix_winding",
            "promote_height",
            "fuse_bld",
            "divide_bld",
            "restore_height",
            "bld_footprint_bevel",
            "extrude_buildings",
            "post_normals",
            "bld_clipped",
            "bld_color",
            "bld_foundation",
            "bld_foundation_clipped",
            "bld_foundation_color",
            "bld_with_foundation_merge",
            "bld_with_foundation",
        ),
    ),
    NetworkGroup(
        key="roads",
        label="[VC] 道路 Roads",
        color=(0.25, 0.36, 0.28),
        nodes=(
            "road_api_raw_lines",
            "road_api_shared_topology",
            "road_centerline_resample",
            "road_turn_curve_smooth",
            "road_vertex_cleanup",
            "road_junction_curve_smooth",
            "snap_road_strips",
            "road_bbox_clip",
            "snap_road_clipped",
            "road_clipped",
            "road_profile_apply",
            "road_capsule_surface_preview",
            "road_curb_variation",
            "road_color",
            "road_surface_color_cd",
            "road_surface_color",
        ),
    ),
    NetworkGroup(
        key="assembly",
        label="[VC] 总装 Assembly",
        color=(0.34, 0.30, 0.48),
        nodes=(
            "merge_all",
            "OUT_city",
        ),
    ),
)


def _vector2(hou, x: float, y: float):
    try:
        return hou.Vector2(x, y)
    except TypeError:
        return hou.Vector2((x, y))


def _color(hou, rgb: tuple[float, float, float]):
    return hou.Color(rgb)


def _existing_nodes(hou, obj_path: str, names: tuple[str, ...]):
    nodes = []
    for name in names:
        node = hou.node(obj_path + "/" + name)
        if node is not None:
            nodes.append(node)
    return nodes


def _destroy_old_boxes(net) -> None:
    if not hasattr(net, "networkBoxes"):
        return
    for box in list(net.networkBoxes()):
        try:
            comment = box.comment()
        except Exception:
            comment = ""
        if str(comment).startswith("[VC] "):
            box.destroy()


def _add_node_to_box(box, node) -> None:
    if hasattr(box, "addNode"):
        box.addNode(node)
    else:
        box.addItem(node)


def apply_node_notes(hou, obj_path: str) -> int:
    """Write stable role comments onto known generated nodes."""
    updated = 0
    display_comment_flag = None
    try:
        display_comment_flag = hou.nodeFlag.DisplayComment
    except Exception:
        pass

    for name, note in NODE_NOTES.items():
        node = hou.node(obj_path + "/" + name)
        if node is None:
            continue
        try:
            node.setComment(note)
            updated += 1
        except Exception:
            continue
        if display_comment_flag is not None:
            try:
                node.setGenericFlag(display_comment_flag, True)
                continue
            except Exception:
                pass
        try:
            node.setDisplayComment(True)
        except Exception:
            pass
    return updated


def _place_group(hou, nodes, group_index: int) -> None:
    x = group_index * COLUMN_SPACING
    y = 0.0
    row = 0
    for node in nodes:
        if node.name() in SIDE_BRANCH_LAYOUT:
            continue
        try:
            node.setPosition(_vector2(hou, x, y - row * ROW_SPACING))
        except Exception:
            return
        row += 1


def _position_xy(position) -> tuple[float, float]:
    try:
        return float(position.x()), float(position.y())
    except Exception:
        return float(position[0]), float(position[1])


def _place_side_branches(hou, obj_path: str) -> None:
    """Keep surface branches visible without interrupting the centerline chain."""
    for branch_name, (anchor_name, offset_x, offset_y) in SIDE_BRANCH_LAYOUT.items():
        branch_node = hou.node(obj_path + "/" + branch_name)
        anchor_node = hou.node(obj_path + "/" + anchor_name)
        if branch_node is None or anchor_node is None:
            continue
        try:
            anchor_x, anchor_y = _position_xy(anchor_node.position())
            branch_node.setPosition(_vector2(hou, anchor_x + offset_x, anchor_y + offset_y))
        except Exception:
            continue


def _expand_box_bounds(hou, box) -> None:
    if not hasattr(box, "bounds") or not hasattr(box, "setBounds"):
        return
    try:
        bounds = box.bounds()
        min_x = bounds.min().x() - BOX_PAD_X
        max_x = bounds.max().x() + BOX_PAD_X
        min_y = bounds.min().y() - BOX_PAD_Y
        max_y = bounds.max().y() + BOX_PAD_Y
        box.setBounds(hou.BoundingRect(
            _vector2(hou, min_x, min_y),
            _vector2(hou, max_x, max_y),
        ))
    except Exception:
        pass


def apply_domain_network_layout(hou, net, obj_path: str) -> None:
    """Create visual domain lanes and network boxes without touching geometry."""
    _destroy_old_boxes(net)
    noted = apply_node_notes(hou, obj_path)

    created = 0
    for group_index, group in enumerate(GROUPS):
        nodes = _existing_nodes(hou, obj_path, group.nodes)
        if not nodes:
            continue

        group_color = _color(hou, group.color)
        for node in nodes:
            try:
                node.setColor(group_color)
            except Exception:
                pass

        _place_group(hou, nodes, group_index)
        _place_side_branches(hou, obj_path)

        if not hasattr(net, "createNetworkBox"):
            continue
        box = net.createNetworkBox()
        box.setComment(group.label)
        try:
            box.setColor(group_color)
        except Exception:
            pass
        for node in nodes:
            _add_node_to_box(box, node)
        try:
            box.fitAroundContents()
        except Exception:
            pass
        _expand_box_bounds(hou, box)
        created += 1

    print("  Houdini 网络分组: {} 个 [VC] Network Box 已更新；{} 个节点备注已写入".format(created, noted))
