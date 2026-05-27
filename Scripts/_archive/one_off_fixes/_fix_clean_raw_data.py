"""Fix 3+4+6 in clean_raw_data.py"""
path = 'D:/VirtualCity/Scripts/clean_raw_data.py'
content = open(path, encoding='utf-8').read()

# Fix 3: floor height 3.0 -> 3.5
content = content.replace('FLOOR_HEIGHT_M    = 3.0', 'FLOOR_HEIGHT_M    = 3.5', 1)
print('Fix 3:', 'OK' if 'FLOOR_HEIGHT_M    = 3.5' in content else 'MISS')

# Fix 4: expand highway whitelist
OLD_WL = (
    '    "motorway", "trunk", "primary", "secondary", "tertiary",\n'
    '    "residential", "service", "unclassified",\n'
    '    "motorway_link", "trunk_link", "primary_link",\n'
    '}'
)
NEW_WL = (
    '    "motorway", "trunk", "primary", "secondary", "tertiary",\n'
    '    "residential", "service", "unclassified", "living_street",\n'
    '    "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",\n'
    '    "footway", "pedestrian", "path", "cycleway", "track",\n'
    '}'
)
if OLD_WL in content:
    content = content.replace(OLD_WL, NEW_WL, 1)
    print('Fix 4: OK')
elif NEW_WL in content:
    print('Fix 4: already updated')
else:
    print('Fix 4: MISS - whitelist block not found')

# Fix 6: atomic write for GeoJSON
OLD_GEOJSON_WRITE = (
    '        out_fc = {"type": "FeatureCollection", "features": kept}\n'
    '        with open(path, "w", encoding="utf-8", newline="\\n") as f:\n'
    '            json.dump(out_fc, f, ensure_ascii=False, separators=(",", ":"))\n'
    '        tmp.replace(path)\n'
)
# check if already patched
if 'tmp = path.with_suffix(".tmp")' in content:
    print('Fix 6 GeoJSON: already updated')
else:
    OLD2 = (
        '        out_fc = {"type": "FeatureCollection", "features": kept}\n'
        '        with open(path, "w", encoding="utf-8", newline="\\n") as f:\n'
        '            json.dump(out_fc, f, ensure_ascii=False, separators=(",", ":"))\n'
        '        print(f"  [buildings]'
    )
    NEW2 = (
        '        out_fc = {"type": "FeatureCollection", "features": kept}\n'
        '        tmp = path.with_suffix(".tmp")\n'
        '        with open(tmp, "w", encoding="utf-8", newline="\\n") as f:\n'
        '            json.dump(out_fc, f, ensure_ascii=False, separators=(",", ":"))\n'
        '        tmp.replace(path)\n'
        '        print(f"  [buildings]'
    )
    if OLD2 in content:
        content = content.replace(OLD2, NEW2, 1)
        print('Fix 6 GeoJSON: OK')
    else:
        print('Fix 6 GeoJSON: MISS')

# Fix 6: atomic write for OSM
if 'tempfile.mkstemp' in content:
    print('Fix 6 OSM: already updated')
else:
    OLD3 = (
        '    if not dry_run and ways_to_remove:\n'
        '        tree.write(path, encoding="unicode", xml_declaration=True)\n'
    )
    NEW3 = (
        '    if not dry_run and ways_to_remove:\n'
        '        import tempfile, os\n'
        '        tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")\n'
        '        os.close(tmp_fd)\n'
        '        tree.write(tmp_path, encoding="unicode", xml_declaration=True)\n'
        '        from pathlib import Path as _P; _P(tmp_path).replace(path)\n'
    )
    if OLD3 in content:
        content = content.replace(OLD3, NEW3, 1)
        print('Fix 6 OSM: OK')
    else:
        print('Fix 6 OSM: MISS')

open(path, 'w', encoding='utf-8', newline='\n').write(content)
print('written.')
