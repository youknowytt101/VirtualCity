"""
vc_geo.py — VirtualCity 坐标系唯一权威模块
==========================================
集中所有 WGS84 ↔ 局部米制 ↔ Houdini 坐标的转换约定，消除散落在各脚本中的
重复实现，根除 z 符号 / 投影不一致导致的反复 bug（见 12_已知坑点 H-002 / D-003）。

约定（必须全项目统一遵守）:
  * 数据域 (data domain): 局部平面米制坐标 (x, z)，x=东向(+E)，z=北向(+N)。
    所有数据清洗 / 空间 join / 缓存指纹 / 高度补全都必须使用此约定，**禁止取 -z**。
  * Houdini 域: (x, 0, -z)，北向取反映射到 -Z。
    z 取反**只允许**发生在本模块的 `local_to_houdini()` / `local_xz_to_houdini_xz()`。

投影:
  基于 `_utm_lite` 的固定 zone UTM 正向投影，精度 < 0.01m @5km，适用于 <=1km² 区域。
  原点 UTM zone 由 `origin_lon` 决定，区域内所有点强制使用同一 zone。

用法:
    from vc_geo import LocalProjector, local_to_houdini, signed_area_xz, needs_winding_flip

    proj = LocalProjector(origin_lon, origin_lat)
    x, z = proj.to_local(lon, lat)          # 数据域，不翻 z
    hx, hy, hz = local_to_houdini(x, z)     # Houdini 域，唯一翻 z 处

    sa = signed_area_xz(local_pts)
    if needs_winding_flip(sa):
        local_pts = list(reversed(local_pts))
"""
from __future__ import annotations

from typing import Sequence

import _utm_lite as _utm

# 经度方向每度近似米数（赤道）。仅用于粗略的"度→米"容差换算，
# 真实坐标转换一律走 LocalProjector(UTM)，不要用这个常数。
_DEG_TO_M_EQUATOR = 111319.9


def zone_number(lon: float) -> int:
    """从经度推算 UTM zone number (1-60)。"""
    return _utm.zone_number(lon)


class LocalProjector:
    """绑定到单一原点的 WGS84 → 局部米制投影器。

    返回的局部坐标为**数据域** (x, z)，x=东向，z=北向，不做 Houdini z 翻转。
    原点 UTM 坐标在构造时计算一次并缓存，区域内所有点强制使用同一 zone。
    """

    __slots__ = ("origin_lon", "origin_lat", "zone", "_ox", "_oy")

    def __init__(self, origin_lon: float, origin_lat: float):
        self.origin_lon = float(origin_lon)
        self.origin_lat = float(origin_lat)
        ox, oy, zone = _utm.wgs84_to_utm(self.origin_lat, self.origin_lon)
        self._ox = ox
        self._oy = oy
        self.zone = zone

    def to_local(self, lon: float, lat: float) -> tuple[float, float]:
        """WGS84 (lon, lat) → 数据域局部坐标 (x, z) (米)。不翻 z。"""
        x, y, _ = _utm.wgs84_to_utm(lat, lon, force_zone=self.zone)
        return x - self._ox, y - self._oy

    def to_houdini(self, lon: float, lat: float, y: float = 0.0) -> tuple[float, float, float]:
        """WGS84 (lon, lat) → Houdini 域 (x, y, -z)。直接产出可写入几何的坐标。"""
        x, z = self.to_local(lon, lat)
        return x, y, -z


def wgs84_to_local(lon: float, lat: float,
                   origin_lon: float, origin_lat: float) -> tuple[float, float]:
    """便捷函数：WGS84 → 数据域局部坐标 (x, z)。

    单点调用可用此函数；批量转换请用 `LocalProjector` 复用原点缓存。
    """
    return LocalProjector(origin_lon, origin_lat).to_local(lon, lat)


def local_to_houdini(x: float, z: float, y: float = 0.0) -> tuple[float, float, float]:
    """数据域 (x, z) → Houdini 域 (x, y, -z)。**全项目唯一的 z 翻转处之一。**"""
    return x, y, -z


def local_xz_to_houdini_xz(x: float, z: float) -> tuple[float, float]:
    """数据域 (x, z) → Houdini 平面 (x, -z)。用于只需 2D 的场景（如 DEM 裁剪）。"""
    return x, -z


def signed_area_xz(pts: Sequence[Sequence[float]]) -> float:
    """XZ 平面 (数据域) 多边形有向面积（shoelace）。

    pts: [(x, z), ...]，可闭合可不闭合。
    > 0 / < 0 表示不同绕向；具体翻转判断用 `needs_winding_flip()`。
    """
    n = len(pts)
    area = 0.0
    for i in range(n):
        x0, z0 = pts[i][0], pts[i][1]
        x1, z1 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
        area += x0 * z1 - x1 * z0
    return area / 2.0


def needs_winding_flip(signed_area: float) -> bool:
    """H-002: 数据域 signed_area > 0 时，写入 Houdini (x,0,-z) 后法线朝下，需翻转顶点顺序。"""
    return signed_area > 0


def meters_per_degree(lat: float) -> tuple[float, float]:
    """返回给定纬度处 (经度方向, 纬度方向) 每度近似米数。

    仅供粗略 bbox 尺寸估算 / 度→米容差换算，不用于精确坐标转换。
    """
    import math
    deg_lon = _DEG_TO_M_EQUATOR * math.cos(math.radians(lat))
    deg_lat = _DEG_TO_M_EQUATOR
    return deg_lon, deg_lat


def bbox_size_m(bbox: Sequence[float]) -> tuple[float, float]:
    """bbox [west, south, east, north] → 近似 (宽, 高) 米。仅用于显示/记录。"""
    west, south, east, north = bbox[0], bbox[1], bbox[2], bbox[3]
    center_lat = (south + north) / 2.0
    deg_lon, deg_lat = meters_per_degree(center_lat)
    return (east - west) * deg_lon, (north - south) * deg_lat
