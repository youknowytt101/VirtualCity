"""
预生成区域外边界本地包
========================
遍历 regions.json 的所有 osmId，从 Nominatim 抓取行政边界多边形，
用 shapely 做中度简化（Douglas-Peucker）后写入 frontend/boundaries/，
供 server.py 的 /boundary 优先读取，避免大国边界实时加载缓慢。

用法:
    uv run python Scripts/app/area_picker/build_boundaries.py
    uv run python Scripts/app/area_picker/build_boundaries.py --force   # 忽略已存在文件重新生成
"""

import json
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

from shapely.geometry import shape, mapping

HERE = Path(__file__).resolve().parent
REGIONS_FILE = HERE / 'frontend' / 'regions.json'
OUT_DIR = HERE / 'frontend' / 'boundaries'

COUNTRY_TOLERANCE = 0.01
CITY_TOLERANCE = 0.001
REQUEST_INTERVAL = 1.2
TIMEOUT = 30.0


def count_verts(coords):
    if isinstance(coords, (int, float)):
        return 0
    if coords and isinstance(coords[0], (int, float)):
        return 1
    return sum(count_verts(c) for c in coords)


def fetch_raw(osm_id):
    url = 'https://nominatim.openstreetmap.org/lookup?' + urllib.parse.urlencode({
        'osm_ids': 'R' + str(osm_id),
        'format': 'jsonv2',
        'polygon_geojson': '1',
    })
    req = urllib.request.Request(url, headers={
        'User-Agent': 'VirtualCity/0.1 area-picker boundary-prebuild',
        'Accept': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    item = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else None
    if not item:
        return None, None
    geojson = item.get('geojson')
    if not isinstance(geojson, dict) or geojson.get('type') not in ('Polygon', 'MultiPolygon'):
        return None, None
    bbox = item.get('boundingbox') if isinstance(item.get('boundingbox'), list) else []
    return geojson, bbox


def simplify_geojson(geojson, tolerance):
    geom = shape(geojson)
    simplified = geom.simplify(tolerance, preserve_topology=True)
    if simplified.is_empty:
        simplified = geom
    return mapping(simplified)


def build_one(name, osm_id, tolerance, force):
    key = 'R' + str(osm_id)
    out_file = OUT_DIR / (key + '.json')
    if out_file.exists() and not force:
        print('  skip %s (%s) 已存在' % (name, key))
        return False
    try:
        geojson, bbox = fetch_raw(osm_id)
    except Exception as exc:
        print('  FAIL %s (%s): %s' % (name, key, exc))
        return False
    if not geojson:
        print('  FAIL %s (%s): 无多边形边界' % (name, key))
        return False
    before = count_verts(geojson['coordinates'])
    simplified = simplify_geojson(geojson, tolerance)
    after = count_verts(simplified['coordinates'])
    result = {'ok': True, 'geojson': simplified, 'boundingbox': bbox}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, separators=(',', ':'))
    out_file.write_text(payload, encoding='utf-8')
    print('  OK   %s (%s): verts %d -> %d, %.0f KB' % (
        name, key, before, after, len(payload) / 1024))
    return True


def main():
    force = '--force' in sys.argv[1:]
    regions = json.loads(REGIONS_FILE.read_text(encoding='utf-8'))
    jobs = []
    for country in regions.get('countries', []):
        if country.get('osmId'):
            jobs.append((country['name'], country['osmId'], COUNTRY_TOLERANCE))
        for city in country.get('cities', []):
            if city.get('osmId'):
                jobs.append((city['name'], city['osmId'], CITY_TOLERANCE))
    print('共 %d 个区域待生成 (force=%s)' % (len(jobs), force))
    fetched = 0
    for name, osm_id, tol in jobs:
        did_fetch = build_one(name, osm_id, tol, force)
        if did_fetch:
            fetched += 1
            time.sleep(REQUEST_INTERVAL)
    print('完成：实际抓取 %d 个，输出目录 %s' % (fetched, OUT_DIR))


if __name__ == '__main__':
    main()