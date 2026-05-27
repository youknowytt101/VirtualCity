path = 'D:/VirtualCity/Scripts/enrich_building_levels.py'
c = open(path, encoding='utf-8').read()

OLD = "    bbox       = area_cfg['bbox']          # [west, south, east, north]"
NEW = """    # derive bbox from buildings GeoJSON extent
    import json as _j2
    _bfc = _j2.load(open(vc_paths.resolve_project_path(area_cfg['buildings_file']), encoding='utf-8'))
    _lons, _lats = [], []
    for _f in _bfc['features']:
        _g = _f.get('geometry')
        if not _g: continue
        _rings = _g['coordinates'] if _g['type'] == 'Polygon' else _g['coordinates'][0]
        for _c in _rings[0]:
            _lons.append(_c[0]); _lats.append(_c[1])
    bbox = [min(_lons), min(_lats), max(_lons), max(_lats)]"""

if OLD in c:
    c = c.replace(OLD, NEW, 1)
    open(path, 'w', encoding='utf-8', newline='\n').write(c)
    print('fixed')
else:
    print('pattern not found')
    print(repr(c[c.find("bbox"):c.find("bbox")+80]))
