"""
vc_schema.py — VirtualCity 语义契约（唯一权威）
================================================
正式定义每一层进入 Houdini 前必须携带的属性、类型、允许值、缺失默认与来源
（provenance），并提供校验函数供 refine_data 的 QA 与未来 Houdini Model QA 复用。

设计原则（与 vc_geo / vc_buildings 同模式：单一权威 + 检查驱动）:
  * 几何可替换，语义昂贵：白盒阶段就锁住"城市将来需要的信息别丢"。
  * provenance 优先：height_source 让我们随时知道高度是真数据还是程序推算。
  * 渐进：现在只锁已有属性 + 来源；道路图拓扑字段（seg/from/to）先留 optional。

校验返回统一格式（与 refine_data 的 check dict 一致）:
    {"name": str, "status": "pass"|"warn"|"fail", "message": str}
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

CONTRACT_VERSION = "v1_2026_05_29"


@dataclass(frozen=True)
class Attr:
    type: type
    required: bool = False
    default: Any = None
    enum: frozenset | None = None
    minimum: float | None = None
    maximum: float | None = None
    optional: bool = False   # 城市阶段才强制，现在仅记录
    derived: bool = False     # 由管线推导，非原始数据


# ── 建筑层契约 ────────────────────────────────────────────────────────────────
# height_source 的取值含义：
#   overture          —— Overture 提供了正高度
#   osm               —— OSM building:levels/height 匹配补全（refine L3）
#   estimated_pending —— 清洗时高度缺失，写 0，交 Houdini procedural_height 推算
HEIGHT_SOURCES = frozenset({"overture", "osm", "estimated_pending"})

BUILDINGS = {
    "height": Attr(float, required=True, minimum=0.0, maximum=600.0),
    "height_source": Attr(str, required=True, enum=HEIGHT_SOURCES),
    "class": Attr(str, default="building"),
}

# ── 道路层契约（OSM way tags）────────────────────────────────────────────────
ROADS_WAY = {
    "highway": Attr(str, required=True),
    "lanes": Attr(int, default=0),       # 0 = 未知
    "oneway": Attr(str, default="no"),
    "width": Attr(float, default=0.0),   # 0 = 未知 → 按等级推
    # —— 道路图拓扑（城市阶段升为 required）——
    "seg_id": Attr(int, optional=True),
    "from_node": Attr(int, optional=True),
    "to_node": Attr(int, optional=True),
}


def _chk(name: str, status: str, message: str) -> dict:
    return {"name": name, "status": status, "message": message}


# ══════════════════════════════════════════════════════════════════════════════
# 建筑 GeoJSON 校验
# ══════════════════════════════════════════════════════════════════════════════

def check_buildings(features: Iterable[dict]) -> list[dict]:
    feats = list(features)
    checks: list[dict] = []
    n = len(feats)
    if n == 0:
        return [_chk("bld_attr_present", "fail", "建筑 0 个")]

    missing_height = 0
    out_of_range = 0
    missing_source = 0
    bad_source = 0
    source_counts: dict[str, int] = defaultdict(int)

    for feat in feats:
        props = feat.get("properties") or {}
        h = props.get("height")
        if not isinstance(h, (int, float)):
            missing_height += 1
        elif h < 0 or h > 600:
            out_of_range += 1

        src = props.get("height_source")
        if src is None:
            missing_source += 1
        else:
            source_counts[src] += 1
            if src not in HEIGHT_SOURCES:
                bad_source += 1

    # 必需属性 height
    if missing_height:
        checks.append(_chk("bld_height_present", "fail",
                           f"{missing_height}/{n} 建筑缺 height"))
    else:
        checks.append(_chk("bld_height_present", "pass", f"{n} 建筑均有 height"))

    if out_of_range:
        checks.append(_chk("bld_height_range", "warn",
                           f"{out_of_range}/{n} 建筑 height 越界(0~600)"))

    # provenance 完整性
    if missing_source:
        checks.append(_chk("bld_height_source", "fail",
                           f"{missing_source}/{n} 建筑缺 height_source（语义契约要求）"))
    elif bad_source:
        checks.append(_chk("bld_height_source", "fail",
                           f"{bad_source}/{n} 建筑 height_source 非法值"))
    else:
        real = source_counts.get("overture", 0) + source_counts.get("osm", 0)
        pend = source_counts.get("estimated_pending", 0)
        checks.append(_chk("bld_height_source", "pass",
                           f"真值 {real} / 待推算 {pend}（{dict(source_counts)}）"))

    return checks


# ══════════════════════════════════════════════════════════════════════════════
# 道路 OSM 校验 + 连通性
# ══════════════════════════════════════════════════════════════════════════════

def _parse_osm_roads(root: ET.Element) -> tuple[list[list[str]], dict[str, dict]]:
    """返回 (highway_ways 的 node-ref 列表, way->tags)。"""
    ways: list[list[str]] = []
    tags_list: list[dict] = []
    for way in root.findall("way"):
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        if not tags.get("highway"):
            continue
        refs = [nr.get("ref") for nr in way.findall("nd") if nr.get("ref")]
        if len(refs) >= 2:
            ways.append(refs)
            tags_list.append(tags)
    return ways, tags_list


def check_roads(osm_source: str | Path | ET.Element) -> list[dict]:
    if isinstance(osm_source, ET.Element):
        root = osm_source
    else:
        try:
            root = ET.parse(str(osm_source)).getroot()
        except ET.ParseError as exc:
            return [_chk("road_parse", "fail", f"OSM 解析失败: {exc}")]

    ways, tags_list = _parse_osm_roads(root)
    checks: list[dict] = []
    n = len(ways)
    if n == 0:
        return [_chk("road_present", "fail", "无 highway way")]

    # 属性覆盖率（informational，不阻断）
    with_lanes = sum(1 for t in tags_list if str(t.get("lanes", "")).strip() not in ("", "0"))
    with_oneway = sum(1 for t in tags_list if t.get("oneway"))
    with_width = sum(1 for t in tags_list if str(t.get("width", "")).strip() not in ("", "0"))
    checks.append(_chk("road_attr_coverage", "pass",
                       f"highway {n}：lanes {with_lanes} · oneway {with_oneway} · width {with_width}"))

    # 连通性：并查集统计连通分量 + 悬挂端点
    parent: dict[str, str] = {}

    def find(a: str) -> str:
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    node_degree: dict[str, int] = defaultdict(int)
    for refs in ways:
        for a, b in zip(refs, refs[1:]):
            union(a, b)
        for r in refs:
            node_degree[r] += 0
        # 端点度（用于悬挂统计）
        node_degree[refs[0]] += 1
        node_degree[refs[-1]] += 1

    # 每条 way 落到一个分量；统计分量大小（按 way 数）
    comp_ways: dict[str, int] = defaultdict(int)
    for refs in ways:
        comp_ways[find(refs[0])] += 1
    components = len(comp_ways)
    largest = max(comp_ways.values()) if comp_ways else 0
    frac = largest / n if n else 0.0
    dangling = sum(1 for d in node_degree.values() if d == 1)

    msg = f"分量 {components} · 最大连通占比 {frac:.0%} · 悬挂端点 {dangling}"
    if frac < 0.6 and components > 1:
        checks.append(_chk("road_connectivity", "warn", f"路网较碎：{msg}"))
    else:
        checks.append(_chk("road_connectivity", "pass", msg))

    return checks
