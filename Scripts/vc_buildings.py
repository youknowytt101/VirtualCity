"""
vc_buildings.py — 建筑 GeoJSON 清洗的纯函数实现
=================================================
把建筑清洗逻辑从 clean_raw_data.py 抽成不做 IO 的纯函数，便于单测与复用。

设计原则:
  * transform_buildings(features) -> (kept_features, stats)，不读写文件。
  * 几何**原样透传**（只修正 height、做过滤），不重写顶点；
    holes / MultiPolygon 的几何在输出里保持与输入一致，交由 Houdini 端处理。
  * 坐标 / 面积一律走 vc_geo（全项目唯一坐标权威），不直接 import _utm_lite。

过滤规则（与历史 clean_buildings 对齐，MultiPolygon 决策更准）:
  1. 删除 geometry 为 null 或非 Polygon/MultiPolygon。
  2. 删除退化多边形（没有任何外环 >= 3 个去重顶点）。
  3. 删除过小建筑（所有外环面积之和 < MIN_AREA_M2）。
  4. 高度清洗：无效/<=0 写 0（交 Houdini procedural_height 推算）；> MAX 截断。
  5. 近重复去重：质心 < DEDUP_DIST_M（用空间网格，O(n) 量级）。
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Sequence

from vc_geo import LocalProjector, ring_area_m2

# ── 清洗阈值（与 clean_raw_data 保持同一份来源）──────────────────────────────
MIN_AREA_M2 = 5.0      # 建筑最小面积（m²），小于此视为噪声
MAX_HEIGHT_M = 600.0   # 建筑最大合理高度（m）
DEDUP_DIST_M = 3.0     # 近重复建筑中心点距离阈值（m）


def _unique_points(ring: Sequence[Sequence[float]]) -> list[tuple[float, float]]:
    """去除多边形首尾重复点并去重相邻完全相同点。"""
    pts = [tuple(c[:2]) for c in ring]
    if pts and pts[0] == pts[-1]:
        pts = pts[:-1]
    if not pts:
        return []
    out = [pts[0]]
    for p in pts[1:]:
        if p != out[-1]:
            out.append(p)
    return out


def _ring_centroid(coords: Sequence[Sequence[float]]) -> tuple[float, float]:
    n = len(coords)
    return sum(c[0] for c in coords) / n, sum(c[1] for c in coords) / n


def _feature_polygons(geom: dict) -> list[list]:
    """返回 polygon 列表，每个 polygon = [outer_ring, hole1, ...]；类型非法返回 []。"""
    gtype = geom.get("type", "")
    if gtype == "Polygon":
        coords = geom.get("coordinates", [])
        return [coords] if coords else []
    if gtype == "MultiPolygon":
        return [poly for poly in geom.get("coordinates", []) if poly]
    return []


def _dedup_by_grid(prelim: list[tuple[dict, tuple[float, float]]], stats: dict) -> list[dict]:
    """对 (feature, centroid_lonlat) 列表按米制网格做近重复去重，保留先出现者。"""
    if not prelim:
        return []
    mean_lon = sum(c[0] for _, c in prelim) / len(prelim)
    mean_lat = sum(c[1] for _, c in prelim) / len(prelim)
    proj = LocalProjector(mean_lon, mean_lat)
    cell = max(DEDUP_DIST_M, 0.01)
    grid: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
    kept: list[dict] = []

    for feat, (lon, lat) in prelim:
        x, z = proj.to_local(lon, lat)
        gx, gy = int(math.floor(x / cell)), int(math.floor(z / cell))
        is_dup = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for ox, oz in grid.get((gx + dx, gy + dy), ()):
                    if math.hypot(x - ox, z - oz) < DEDUP_DIST_M:
                        is_dup = True
                        break
                if is_dup:
                    break
            if is_dup:
                break
        if is_dup:
            stats["removed_duplicate"] += 1
            continue
        grid[(gx, gy)].append((x, z))
        kept.append(feat)
    return kept


def transform_buildings(features: Sequence[dict]) -> tuple[list[dict], dict[str, Any]]:
    """纯函数：过滤 + 高度清洗 + 近重复去重。返回 (kept_features, stats)。"""
    total_in = len(features)
    stats: dict[str, Any] = {
        "total_in": total_in,
        "removed_null": 0,
        "removed_degenerate": 0,
        "removed_tiny": 0,
        "removed_duplicate": 0,
        "fixed_height": 0,
        "clamped_height": 0,
        "total_out": 0,
    }

    prelim: list[tuple[dict, tuple[float, float]]] = []

    for feat in features:
        geom = feat.get("geometry")
        props = feat.get("properties") or {}

        if geom is None:
            stats["removed_null"] += 1
            continue

        polys = _feature_polygons(geom)
        if not polys:
            stats["removed_null"] += 1
            continue

        # 收集所有有效外环（>=3 去重顶点），并累计外环面积
        outers: list[list[tuple[float, float]]] = []
        total_area = 0.0
        for poly in polys:
            outer = _unique_points(poly[0]) if poly else []
            if len(outer) >= 3:
                outers.append(outer)
                total_area += ring_area_m2(outer)

        if not outers:
            stats["removed_degenerate"] += 1
            continue

        if total_area < MIN_AREA_M2:
            stats["removed_tiny"] += 1
            continue

        # 高度清洗
        h = props.get("height")
        try:
            h = float(h) if h is not None else None
        except (TypeError, ValueError):
            h = None
        if h is None or h <= 0:
            # 写 0，让 Houdini procedural_height VEX 唯一负责推算
            h = 0.0
            stats["fixed_height"] += 1
        elif h > MAX_HEIGHT_M:
            h = MAX_HEIGHT_M
            stats["clamped_height"] += 1

        # 去重用质心：取面积最大的外环
        largest = max(outers, key=ring_area_m2)
        ctr = _ring_centroid(largest)

        new_feat = {
            "type": "Feature",
            "geometry": feat["geometry"],
            "properties": {**props, "height": h},
        }
        prelim.append((new_feat, ctr))

    kept = _dedup_by_grid(prelim, stats)
    stats["total_out"] = len(kept)
    return kept, stats
