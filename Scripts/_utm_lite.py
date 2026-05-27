"""
_utm_lite.py — 最小 UTM 正向投影（零依赖，纯 math）
======================================================
WGS84 经纬度 → UTM 东北坐标（米），精度 < 0.01m @5km。

用法:
    from _utm_lite import wgs84_to_utm, wgs84_to_local

    # 获取 UTM 绝对坐标 + zone
    x, y, zone = wgs84_to_utm(lat, lon)

    # 获取相对于原点的局部坐标（推荐）
    origin_x, origin_y, zone = wgs84_to_utm(ORIGIN_LAT, ORIGIN_LON)
    dx, dy = wgs84_to_local(lon, lat, ORIGIN_LON, ORIGIN_LAT, origin_x, origin_y, zone)
"""
import math

# WGS84 椭球参数
_A  = 6378137.0            # 长半轴 (m)
_E  = 0.00669437999014     # 第一偏心率²
_E2 = _E * _E
_E3 = _E2 * _E
_EP2 = _E / (1.0 - _E)
_K0 = 0.9996              # UTM 比例因子
_FE = 500000.0            # 东偏移 (m)
_FN = 10000000.0          # 南半球北偏移 (m)

# 子午线弧长系数（预计算）
_M1 = 1.0 - _E / 4.0 - 3.0 * _E2 / 64.0 - 5.0 * _E3 / 256.0
_M2 = 3.0 * _E / 8.0 + 3.0 * _E2 / 32.0 + 45.0 * _E3 / 1024.0
_M3 = 15.0 * _E2 / 256.0 + 45.0 * _E3 / 1024.0
_M4 = 35.0 * _E3 / 3072.0


def zone_number(lon: float) -> int:
    """从经度推算 UTM zone number (1-60)"""
    return int((lon + 180.0) / 6.0) + 1


def wgs84_to_utm(lat: float, lon: float, force_zone: int = 0):
    """
    WGS84 (lat, lon) → UTM (easting, northing, zone_number)

    Parameters:
        lat: 纬度（度，北纬为正）
        lon: 经度（度，东经为正）
        force_zone: 强制使用指定 zone（0=自动）

    Returns:
        (easting, northing, zone_number)
    """
    lat_r = math.radians(lat)
    sin_lat = math.sin(lat_r)
    cos_lat = math.cos(lat_r)
    tan_lat = math.tan(lat_r)

    zone = force_zone if force_zone else zone_number(lon)
    lon_origin = (zone - 1) * 6 - 180 + 3
    dlon_r = math.radians(lon - lon_origin)

    n = _A / math.sqrt(1.0 - _E * sin_lat * sin_lat)
    t = tan_lat * tan_lat
    c = _EP2 * cos_lat * cos_lat
    a = cos_lat * dlon_r

    m = _A * (_M1 * lat_r - _M2 * math.sin(2.0 * lat_r)
              + _M3 * math.sin(4.0 * lat_r) - _M4 * math.sin(6.0 * lat_r))

    a2 = a * a
    a4 = a2 * a2
    a6 = a4 * a2
    t2 = t * t

    x = _K0 * n * (a + (1.0 - t + c) * a2 * a / 6.0
                    + (5.0 - 18.0 * t + t2 + 72.0 * c - 58.0 * _EP2) * a4 * a / 120.0) + _FE

    y = _K0 * (m + n * tan_lat * (a2 / 2.0
               + (5.0 - t + 9.0 * c + 4.0 * c * c) * a4 / 24.0
               + (61.0 - 58.0 * t + t2 + 600.0 * c - 330.0 * _EP2) * a6 / 720.0))

    if lat < 0:
        y += _FN

    return x, y, zone


def wgs84_to_local(lon: float, lat: float,
                   origin_lon: float, origin_lat: float,
                   origin_x: float = None, origin_y: float = None,
                   force_zone: int = 0):
    """
    WGS84 经纬度 → 相对于原点的局部坐标 (dx, dy)。

    如果未传 origin_x/origin_y，会自动计算。
    force_zone: 强制 UTM zone（应与原点一致）。
    """
    if origin_x is None or origin_y is None:
        origin_x, origin_y, force_zone = wgs84_to_utm(origin_lat, origin_lon)
    elif not force_zone:
        force_zone = zone_number(origin_lon)

    x, y, _ = wgs84_to_utm(lat, lon, force_zone=force_zone)
    return x - origin_x, y - origin_y
