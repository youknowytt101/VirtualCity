"""Fixed UTM build tiles for the VirtualCity area picker."""
from __future__ import annotations

import math
import re
from typing import Any, Sequence

import _tile_cache
import _utm_lite
import data_cleaning_cache as dcc


TILE_SIZE_M = 1000
MAX_VIEW_TILES = 400
MAX_SELECTION_TILES = 256
_TILE_ID_RE = re.compile(r"^z(?P<zone>\d+)(?P<hemi>[ns])_e(?P<easting>-?\d+)_n(?P<northing>-?\d+)_s(?P<size>\d+)$")


def tile_id(zone: int, easting: int, northing: int,
            *, size_m: int = TILE_SIZE_M, northern: bool = True) -> str:
    hemisphere = "n" if northern else "s"
    return f"z{int(zone)}{hemisphere}_e{int(easting)}_n{int(northing)}_s{int(size_m)}"


def selection_id(zone: int, easting: int, northing: int, width_m: int, height_m: int,
                 *, size_m: int = TILE_SIZE_M, northern: bool = True) -> str:
    hemisphere = "n" if northern else "s"
    return (f"z{int(zone)}{hemisphere}_e{int(easting)}_n{int(northing)}"
            f"_w{int(width_m)}_h{int(height_m)}_s{int(size_m)}")


def parse_tile_id(value: str) -> dict[str, Any]:
    """Parse a fixed-grid tile id and validate its alignment."""
    match = _TILE_ID_RE.match(str(value or ""))
    if not match:
        raise ValueError("invalid tile id")
    zone = int(match.group("zone"))
    size_m = int(match.group("size"))
    easting = int(match.group("easting"))
    northing = int(match.group("northing"))
    if not (1 <= zone <= 60):
        raise ValueError("invalid UTM zone")
    if size_m != TILE_SIZE_M:
        raise ValueError(f"unsupported tile size: {size_m}")
    if easting % size_m != 0 or northing % size_m != 0:
        raise ValueError("tile is not aligned to its size")
    return {
        "zone": zone,
        "northern": match.group("hemi") == "n",
        "easting": easting,
        "northing": northing,
        "size_m": size_m,
    }


def tile_by_id(value: str) -> dict[str, Any]:
    spec = parse_tile_id(value)
    return make_tile(**spec)


def _rect_corners(zone: int, easting: int, northing: int, width_m: int, height_m: int, *,
                  northern: bool = True) -> list[list[float]]:
    points = [
        (easting, northing),
        (easting + width_m, northing),
        (easting + width_m, northing + height_m),
        (easting, northing + height_m),
    ]
    corners = []
    for x, y in points:
        lat, lon = _utm_lite.utm_to_wgs84(x, y, zone, northern=northern)
        corners.append([round(lat, 7), round(lon, 7)])
    return corners


def _tile_corners(zone: int, easting: int, northing: int, *,
                  size_m: int = TILE_SIZE_M, northern: bool = True) -> list[list[float]]:
    return _rect_corners(zone, easting, northing, size_m, size_m, northern=northern)


def _envelope(corners: Sequence[Sequence[float]]) -> list[float]:
    lats = [float(p[0]) for p in corners]
    lons = [float(p[1]) for p in corners]
    return [
        round(min(lons), 7),
        round(min(lats), 7),
        round(max(lons), 7),
        round(max(lats), 7),
    ]


def cache_coverage(bbox: Sequence[float]) -> dict[str, Any]:
    """Return whether all raw inputs for bbox can be restored locally."""
    macro = _tile_cache.find_covering_tile(bbox)
    if macro:
        return {"cached": True, "source": "macro_tile"}

    clip = dcc.find_covering_clip_cache(
        bbox,
        source_signature=dcc.CURRENT_ACQUISITION_PROFILE,
    )
    if clip:
        return {
            "cached": True,
            "source": "clip_cache",
            "cache_key": clip.get("key", ""),
        }

    return {"cached": False, "source": ""}


def make_tile(zone: int, easting: int, northing: int, *,
              size_m: int = TILE_SIZE_M, northern: bool = True) -> dict[str, Any]:
    corners = _tile_corners(zone, easting, northing, size_m=size_m, northern=northern)
    bbox = _envelope(corners)
    center_lat, center_lon = _utm_lite.utm_to_wgs84(
        easting + size_m / 2.0,
        northing + size_m / 2.0,
        zone,
        northern=northern,
    )
    coverage = cache_coverage(bbox)
    return {
        "tile_id": tile_id(zone, easting, northing, size_m=size_m, northern=northern),
        "zone": int(zone),
        "northern": bool(northern),
        "easting": int(easting),
        "northing": int(northing),
        "size_m": int(size_m),
        "bbox": bbox,
        "corners": corners,
        "center": [round(center_lat, 7), round(center_lon, 7)],
        **coverage,
    }


def selection_from_tile_ids(tile_ids: Sequence[str], *,
                            max_tiles: int = MAX_SELECTION_TILES) -> dict[str, Any]:
    """Validate a rectangular selection of fixed 1 km tiles and return its bbox."""
    ids = list(dict.fromkeys(str(v).strip() for v in tile_ids if str(v).strip()))
    if not ids:
        raise ValueError("empty tile selection")
    if len(ids) > max_tiles:
        raise ValueError(f"selection contains {len(ids)} tiles; limit is {max_tiles}")

    specs = [parse_tile_id(value) for value in ids]
    zone = specs[0]["zone"]
    northern = specs[0]["northern"]
    size_m = specs[0]["size_m"]
    for spec in specs:
        if spec["zone"] != zone or spec["northern"] != northern or spec["size_m"] != size_m:
            raise ValueError("selection crosses UTM zone, hemisphere, or tile size")

    eastings = sorted({spec["easting"] for spec in specs})
    northings = sorted({spec["northing"] for spec in specs})
    expected_eastings = list(range(eastings[0], eastings[-1] + size_m, size_m))
    expected_northings = list(range(northings[0], northings[-1] + size_m, size_m))
    if eastings != expected_eastings or northings != expected_northings:
        raise ValueError("selection has gaps")

    selected = {(spec["easting"], spec["northing"]) for spec in specs}
    expected = {(easting, northing) for northing in expected_northings for easting in expected_eastings}
    if selected != expected:
        raise ValueError("selection must be a continuous rectangle")

    min_e = eastings[0]
    min_n = northings[0]
    width_m = len(eastings) * size_m
    height_m = len(northings) * size_m
    corners = _rect_corners(zone, min_e, min_n, width_m, height_m, northern=northern)
    bbox = _envelope(corners)
    center_lat, center_lon = _utm_lite.utm_to_wgs84(
        min_e + width_m / 2.0,
        min_n + height_m / 2.0,
        zone,
        northern=northern,
    )
    tiles = [
        make_tile(zone, easting, northing, size_m=size_m, northern=northern)
        for northing in expected_northings
        for easting in expected_eastings
    ]
    cached_tiles = sum(1 for tile in tiles if tile.get("cached"))
    return {
        "selection_id": selection_id(
            zone, min_e, min_n, width_m, height_m,
            size_m=size_m,
            northern=northern,
        ),
        "zone": zone,
        "northern": northern,
        "easting": min_e,
        "northing": min_n,
        "cols": len(eastings),
        "rows": len(northings),
        "width_m": width_m,
        "height_m": height_m,
        "size_m": size_m,
        "tile_count": len(tiles),
        "cached_tiles": cached_tiles,
        "cached": cached_tiles == len(tiles),
        "sources": sorted({tile.get("source", "") for tile in tiles if tile.get("source")}),
        "tile_ids": [tile["tile_id"] for tile in tiles],
        "bbox": bbox,
        "corners": corners,
        "center": [round(center_lat, 7), round(center_lon, 7)],
        "tiles": tiles,
    }


def tiles_for_bbox(bbox: Sequence[float], *, size_m: int = TILE_SIZE_M,
                   max_tiles: int = MAX_VIEW_TILES) -> dict[str, Any]:
    """Generate fixed UTM tiles intersecting a WGS84 viewport envelope."""
    west, south, east, north = [float(v) for v in bbox]
    center_lon = (west + east) / 2.0
    center_lat = (south + north) / 2.0
    zone = _utm_lite.zone_number(center_lon)
    northern = center_lat >= 0
    projected = [
        _utm_lite.wgs84_to_utm(lat, lon, force_zone=zone)[:2]
        for lon, lat in ((west, south), (east, south), (east, north), (west, north))
    ]
    min_e = math.floor(min(p[0] for p in projected) / size_m) * size_m
    max_e = math.floor(max(p[0] for p in projected) / size_m) * size_m
    min_n = math.floor(min(p[1] for p in projected) / size_m) * size_m
    max_n = math.floor(max(p[1] for p in projected) / size_m) * size_m
    cols = int((max_e - min_e) / size_m) + 1
    rows = int((max_n - min_n) / size_m) + 1
    count = cols * rows
    if count > max_tiles:
        return {
            "tiles": [],
            "truncated": True,
            "message": f"viewport contains {count} tiles; zoom in to show at most {max_tiles}",
            "tile_size_m": size_m,
            "zone": zone,
        }

    tiles = [
        make_tile(zone, easting, northing, size_m=size_m, northern=northern)
        for northing in range(min_n, max_n + size_m, size_m)
        for easting in range(min_e, max_e + size_m, size_m)
    ]
    return {
        "tiles": tiles,
        "truncated": False,
        "tile_size_m": size_m,
        "zone": zone,
    }
