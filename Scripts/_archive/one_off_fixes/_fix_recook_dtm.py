"""Hook correct_dem_dtm and enrich_building_levels into _recook_new_area.py"""
from pathlib import Path

path = Path('D:/VirtualCity/Scripts/_recook_new_area.py')
c = path.read_text(encoding='utf-8')

OLD = """# ── 前置：原始数据清洗（GeoJSON 几何/高度 + OSM 道路）──────────────
print('[数据清洗]')
_clean_result = subprocess.run(
    [sys.executable, str(ROOT / 'Scripts' / 'clean_raw_data.py'), '--report'],
    capture_output=True, text=True, encoding='utf-8', errors='replace'
)
for _line in _clean_result.stdout.splitlines():
    sys.stdout.buffer.write(('  ' + _line + '\\n').encode('utf-8', errors='replace'))
if _clean_result.returncode != 0:
    print('  [WARN] clean_raw_data 退出码非 0，继续执行...')
    print(_clean_result.stderr[:400])"""

NEW = """# ── 前置：原始数据清洗（GeoJSON 几何/高度 + OSM 道路）──────────────
print('[数据清洗]')
_clean_result = subprocess.run(
    [sys.executable, str(ROOT / 'Scripts' / 'clean_raw_data.py'), '--report'],
    capture_output=True, text=True, encoding='utf-8', errors='replace'
)
for _line in _clean_result.stdout.splitlines():
    sys.stdout.buffer.write(('  ' + _line + '\\n').encode('utf-8', errors='replace'))
if _clean_result.returncode != 0:
    print('  [WARN] clean_raw_data 退出码非 0，继续执行...')
    print(_clean_result.stderr[:400])

# ── 前置：OSM building:levels 高度补全 ─────────────────────────────
print('[heights] OSM building:levels enrichment...')
try:
    sys.path.insert(0, str(ROOT / 'Scripts'))
    from enrich_building_levels import enrich_levels as _enrich_levels
    _lvl_cfg = load_active_area()
    _lvl_stats = _enrich_levels(_lvl_cfg, verbose=False)
    print(f'  [heights] OSM levels matched: {_lvl_stats[\"updated\"]} buildings updated')
except Exception as _e:
    print(f'  [WARN] enrich_building_levels failed: {_e}')

# ── 前置：DEM DSM -> DTM 修正（建筑掩码插值）────────────────────────
print('[dem] DTM correction (building mask)...')
try:
    from correct_dem_dtm import correct_dtm as _correct_dtm
    _dtm_cfg = load_active_area()
    _dtm_ok = _correct_dtm(_dtm_cfg, verbose=False)
    if _dtm_ok:
        print('  [dem] DTM correction applied')
    else:
        print('  [dem] DTM correction skipped (no cells masked)')
except Exception as _e:
    print(f'  [WARN] correct_dem_dtm failed: {_e}')"""

if OLD in c:
    c = c.replace(OLD, NEW, 1)
    path.write_text(c, encoding='utf-8')
    print('hooked DTM + levels enrichment into _recook_new_area.py')
else:
    print('pattern not found')
