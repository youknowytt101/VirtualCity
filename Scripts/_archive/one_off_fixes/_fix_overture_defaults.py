"""Fix download_overture_buildings.py and set_area.py / _tile_cache.py for OSM building fallback."""
from pathlib import Path

# ── Fix 7: DEFAULT_HEIGHT 8.0 -> 0.0, FLOOR_HEIGHT 3.0 -> 3.5 ──────────────
p = Path('D:/VirtualCity/Scripts/download_overture_buildings.py')
c = p.read_text(encoding='utf-8')
c = c.replace('DEFAULT_HEIGHT   = 8.0', 'DEFAULT_HEIGHT   = 0.0', 1)
c = c.replace('FLOOR_HEIGHT     = 3.0', 'FLOOR_HEIGHT     = 3.5', 1)
p.write_text(c, encoding='utf-8')
print('download_overture_buildings.py: DEFAULT_HEIGHT=0.0, FLOOR_HEIGHT=3.5')

# ── Fix 5a: _tile_cache.py filter_osm — also pass building ways ─────────────
p2 = Path('D:/VirtualCity/Scripts/_tile_cache.py')
c2 = p2.read_text(encoding='utf-8')
old = "            if not tags.get(\"highway\"):\n                continue"
new = "            if not tags.get(\"highway\") and not tags.get(\"building\"):\n                continue"
if old in c2:
    c2 = c2.replace(old, new, 1)
    p2.write_text(c2, encoding='utf-8')
    print('_tile_cache.py: filter_osm now passes building ways')
else:
    print('_tile_cache.py: pattern not found, skipping')

# ── Fix 5b: set_area.py Overpass query — add building ways ──────────────────
p3 = Path('D:/VirtualCity/Scripts/set_area.py')
c3 = p3.read_text(encoding='utf-8')
old3 = ('    query = (\n'
        '        f"[out:xml][timeout:180];\\n"\n'
        '        f"(\\n"\n'
        '        f\'  way["highway"]({s},{w},{n},{e});\\n\'\n'
        '        f");\\n"\n'
        '        f"out body;\\n>;\\nout skel qt;\\n"\n'
        '    )')
new3 = ('    query = (\n'
        '        f"[out:xml][timeout:180];\\n"\n'
        '        f"(\\n"\n'
        '        f\'  way["highway"]({s},{w},{n},{e});\\n\'\n'
        '        f\'  way["building"]({s},{w},{n},{e});\\n\'\n'
        '        f");\\n"\n'
        '        f"out body;\\n>;\\nout skel qt;\\n"\n'
        '    )')
if old3 in c3:
    c3 = c3.replace(old3, new3, 1)
    p3.write_text(c3, encoding='utf-8')
    print('set_area.py: Overpass query now includes building ways')
elif 'way["building"]' in c3:
    print('set_area.py: already includes building ways')
else:
    print('set_area.py: pattern not found, skipping')
