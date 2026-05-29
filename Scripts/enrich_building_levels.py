"""
enrich_building_levels.py — OSM building:levels 高度补全
=========================================================
从 Overpass API 查询 bbox 内含 building:levels 的 OSM ways，
通过质心空间 join 更新 Overture GeoJSON 里对应建筑的高度。

逻辑优先级:
  OSM building:height (人工精确) > OSM building:levels × 3.5m > Google ML > 面积推算

用法:
    uv run python enrich_building_levels.py [area_id]
或由 set_area.py / _recook_new_area.py 调用:
    from enrich_building_levels import enrich_levels
"""
import json, math, sys, argparse, urllib.request, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Scripts'))
import vc_paths
from vc_geo import LocalProjector

FLOOR_H        = 3.5    # m per floor (consistent with VEX)
DEDUP_DIST     = 8.0    # max centroid distance to match (m) — 从15m收紧，减少密集城区错误匹配
OVERPASS_URLS  = [
    'https://overpass-api.de/api/interpreter',
    'https://lz4.overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
]


def _wgs84_to_local(lon, lat, origin_lon, origin_lat,
                    _cache={}):
    """数据域局部坐标 (x, z)，不翻 z。坐标约定集中在 vc_geo.LocalProjector。"""
    key = (origin_lon, origin_lat)
    proj = _cache.get(key)
    if proj is None:
        proj = _cache[key] = LocalProjector(origin_lon, origin_lat)
    return proj.to_local(lon, lat)


def _fetch_osm_levels(bbox, timeout=60):
    """Query Overpass for building ways with levels/height in bbox.
    Returns list of {'cx': float, 'cz': float, 'height': float}.
    """
    w, s, e, n = bbox
    query = (
        f'[out:json][timeout:{timeout}];\n'
        f'(\n'
        f'  way["building"]["building:levels"]({s},{w},{n},{e});\n'
        f'  way["building"]["height"]({s},{w},{n},{e});\n'
        f');\n'
        f'out body;\n>;\nout skel qt;\n'
    )
    data = urllib.parse.urlencode({'data': query}).encode()

    for url in OVERPASS_URLS:
        try:
            req = urllib.request.Request(url, data=data,
                                         headers={'User-Agent': 'VirtualCity/1.0'})
            with urllib.request.urlopen(req, timeout=timeout + 10) as resp:
                return json.loads(resp.read())
        except Exception as e:
            print(f'  [levels] Overpass {url[:40]} failed: {e}')
    return None


def _parse_osm_buildings(osm_json, origin_lon, origin_lat):
    """Extract (cx, cz, height) from Overpass JSON response."""
    if not osm_json:
        return []

    nodes = {el['id']: (el['lon'], el['lat'])
             for el in osm_json.get('elements', []) if el['type'] == 'node'}

    results = []
    for el in osm_json.get('elements', []):
        if el['type'] != 'way':
            continue
        tags = el.get('tags', {})
        if not tags.get('building'):
            continue

        # Parse height
        height = None
        raw_h = tags.get('height')
        if raw_h:
            try:
                height = float(str(raw_h).replace('m', '').strip())
            except ValueError:
                pass

        if height is None:
            raw_lvl = tags.get('building:levels')
            if raw_lvl:
                try:
                    height = float(raw_lvl) * FLOOR_H
                except ValueError:
                    pass

        if height is None or height < 2.5:
            continue

        nd_ids = el.get('nodes', [])
        coords = [nodes[nid] for nid in nd_ids if nid in nodes]
        if len(coords) < 3:
            continue

        lx_list = []
        lz_list = []
        for lon, lat in coords:
            lx, lz = _wgs84_to_local(lon, lat, origin_lon, origin_lat)
            lx_list.append(lx)
            lz_list.append(lz)

        cx = sum(lx_list) / len(lx_list)
        cz = sum(lz_list) / len(lz_list)
        results.append({'cx': cx, 'cz': cz, 'height': height})

    return results


def enrich_levels(area_cfg: dict, verbose: bool = True) -> dict:
    """
    Returns stats: {'total': int, 'updated': int, 'skipped': int}
    """
    bld_path   = vc_paths.resolve_project_path(area_cfg['buildings_file'])
    # derive bbox from buildings GeoJSON extent
    import json as _j2
    _bfc = _j2.load(open(vc_paths.resolve_project_path(area_cfg['buildings_file']), encoding='utf-8'))
    _lons, _lats = [], []
    for _f in _bfc['features']:
        _g = _f.get('geometry')
        if not _g: continue
        _rings = _g['coordinates'] if _g['type'] == 'Polygon' else _g['coordinates'][0]
        for _c in _rings[0]:
            _lons.append(_c[0]); _lats.append(_c[1])
    bbox = [min(_lons), min(_lats), max(_lons), max(_lats)]
    origin_lon = area_cfg['origin_lon']
    origin_lat = area_cfg['origin_lat']

    if not bld_path.exists():
        print('[levels] Buildings GeoJSON not found.')
        return {'total': 0, 'updated': 0, 'skipped': 0}

    if verbose:
        print(f'[levels] Querying Overpass for OSM building:levels in {bbox}...')

    osm_json  = _fetch_osm_levels(bbox, timeout=60)
    osm_blds  = _parse_osm_buildings(osm_json, origin_lon, origin_lat)

    if verbose:
        print(f'[levels] OSM buildings with levels/height: {len(osm_blds)}')

    if not osm_blds:
        return {'total': 0, 'updated': 0, 'skipped': 0}

    # Build spatial cell hash for fast lookup (DEDUP_DIST cell size)
    CELL = DEDUP_DIST
    cell_map: dict = {}
    for i, ob in enumerate(osm_blds):
        key = (int(ob['cx'] / CELL), int(ob['cz'] / CELL))
        cell_map.setdefault(key, []).append(i)

    def _find_nearest_osm(cx, cz):
        xi, zi = int(cx / CELL), int(cz / CELL)
        best_dist = DEDUP_DIST + 1
        best_h = None
        for di in range(-1, 2):
            for dj in range(-1, 2):
                for idx in cell_map.get((xi + di, zi + dj), []):
                    ob = osm_blds[idx]
                    d = math.sqrt((cx - ob['cx'])**2 + (cz - ob['cz'])**2)
                    if d < best_dist:
                        best_dist = d
                        best_h = ob['height']
        return best_h, best_dist

    # Load Overture GeoJSON
    with open(bld_path, encoding='utf-8') as f:
        fc = json.load(f)

    updated = 0
    skipped = 0
    for feat in fc['features']:
        geom = feat.get('geometry')
        if geom is None:
            skipped += 1
            continue
        rings = (geom['coordinates']
                 if geom['type'] == 'Polygon'
                 else geom['coordinates'][0])
        ring = rings[0]
        lx_list, lz_list = [], []
        for coord in ring:
            lx, lz = _wgs84_to_local(coord[0], coord[1], origin_lon, origin_lat)
            lx_list.append(lx)
            lz_list.append(lz)
        if not lx_list:
            skipped += 1
            continue
        cx = sum(lx_list) / len(lx_list)
        cz = sum(lz_list) / len(lz_list)

        best_h, best_dist = _find_nearest_osm(cx, cz)
        if best_h is not None and best_dist <= DEDUP_DIST:
            feat['properties']['height'] = best_h
            feat['properties']['height_source'] = 'osm'  # provenance（语义契约）
            updated += 1

    if verbose:
        print(f'[levels] Updated {updated} buildings from OSM levels (dist<={DEDUP_DIST}m)')

    if updated > 0:
        tmp = bld_path.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(fc, f, ensure_ascii=False, separators=(',', ':'))
        tmp.replace(bld_path)
        if verbose:
            print(f'[levels] Written: {bld_path.name}')

    return {'total': len(osm_blds), 'updated': updated, 'skipped': skipped}


def main():
    ap = argparse.ArgumentParser(description='OSM building:levels height enrichment')
    ap.add_argument('area_id', nargs='?', default=None)
    args = ap.parse_args()

    cfg = vc_paths.load_active_area()
    enrich_levels(cfg, verbose=True)


if __name__ == '__main__':
    main()
