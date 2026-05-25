"""Replace old osm_import patching in _recook_new_area.py with canonical code + update VEX."""
from pathlib import Path

RECOOK = Path('D:/VirtualCity/Scripts/_recook_new_area.py')
content = RECOOK.read_text(encoding='utf-8')

# ── 1. Replace old osm_import patching block (Fix 2 + 5) ───────────────────
OLD_PATCH_START = "osm = hou.node('/obj/pattaya_osm/osm_import')"
OLD_PATCH_END   = "    print('  SOP 修复: osm_import path resolver')\n"
i0 = content.find(OLD_PATCH_START)
i1 = content.find(OLD_PATCH_END)
if i0 < 0 or i1 < 0:
    print('osm_import patch block not found - already updated?')
else:
    OLD_BLOCK = content[i0 : i1 + len(OLD_PATCH_END)]

    # canonical osm_import code lives in _patch_osm_import_v2.py
    # we re-embed just the essential piece here as the replacement
    NEW_BLOCK = r"""# ── osm_import: canonical code (Fix 2+5: single resolver, OSM bld fallback) ──
_OSM_IMPORT_CODE = open(
    str(Path(ROOT_STR) / 'Scripts' / '_osm_import_canonical.py'),
    encoding='utf-8'
).read().replace('__ROOT__', ROOT_STR).replace('__CFG__', CFG_FILE)
osm = hou.node('/obj/pattaya_osm/osm_import')
if osm and osm.parm('python'):
    osm.parm('python').set(_OSM_IMPORT_CODE)
    print('  SOP 修复: osm_import (canonical: single resolver + OSM bld fallback)')
"""
    content = content.replace(OLD_BLOCK, NEW_BLOCK, 1)
    print('Fix 2+5: osm_import patch block replaced')

# ── 2. Update PROC_HEIGHT_VEX (Fix 1: catch 8.0) ───────────────────────────
OLD_VEX_TRIGGER = (
    "int needs_estimate = (abs(f@height_m - 10.0) < 0.1) || (f@height_m <= 0);\n"
    "if (!needs_estimate) return;"
)
NEW_VEX_TRIGGER = (
    "// 触发条件: ~10.0 (OSM default), ~8.0 (Overture DEFAULT_HEIGHT), <=0 (missing)\n"
    "int needs_estimate = (abs(f@height_m - 10.0) < 0.1)\n"
    "                  || (abs(f@height_m -  8.0) < 0.1)\n"
    "                  || (f@height_m <= 0);\n"
    "if (!needs_estimate) return;"
)
if OLD_VEX_TRIGGER in content:
    content = content.replace(OLD_VEX_TRIGGER, NEW_VEX_TRIGGER, 1)
    print('Fix 1: PROC_HEIGHT_VEX trigger updated')
elif NEW_VEX_TRIGGER in content:
    print('Fix 1: VEX already updated')
else:
    print('Fix 1: VEX trigger not found - manual check needed')

# Add Path import if missing
if 'from pathlib import Path' not in content and "import sys, rpyc, subprocess" in content:
    content = content.replace(
        "import sys, rpyc, subprocess\nfrom pathlib import Path",
        "import sys, rpyc, subprocess\nfrom pathlib import Path"
    )

RECOOK.write_text(content, encoding='utf-8')
print('_recook_new_area.py updated.')
