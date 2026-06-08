"""Visual grouping for the generated Houdini SOP network."""
from __future__ import annotations

from dataclasses import dataclass


BOX_PAD_X = 1.35
BOX_PAD_Y = 0.55
COLUMN_SPACING = 7.4
ROW_SPACING = 1.35


@dataclass(frozen=True)
class NetworkGroup:
    key: str
    label: str
    color: tuple[float, float, float]
    nodes: tuple[str, ...]


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
            "road_junction_curve_smooth",
            "snap_road_strips",
            "road_bbox_clip",
            "snap_road_clipped",
            "road_clipped",
            "road_profile_apply",
            "road_curb_variation",
            "road_color",
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


def _place_group(hou, nodes, group_index: int) -> None:
    x = group_index * COLUMN_SPACING
    y = 0.0
    for row, node in enumerate(nodes):
        try:
            node.setPosition(_vector2(hou, x, y - row * ROW_SPACING))
        except Exception:
            return


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

    print("  Houdini 网络分组: {} 个 [VC] Network Box 已更新".format(created))
