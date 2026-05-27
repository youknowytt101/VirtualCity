"""
Run this directly in Houdini Script Editor (Python mode).
Cooks the road pipeline in dependency order without MCP/RPYC timeout issues.
"""
import hou

ROOT = hou.node('/obj/pattaya_osm')
if ROOT is None:
    print("ERROR: /obj/pattaya_osm not found")
    raise SystemExit

COOK_ORDER = [
    'osm_import',
    'dem_terrain',
    'dem_subdivide',
    'extract_roads',
    'resample_roads',
    'snap_roads_to_terrain1',
    'road_width',
    'road_strips',
    'snap_road_strips',
    'road_clip_mark',
    'road_clipped',
    'road_color',
    'extract_buildings',
    'snap_bld_to_terrain',
    'procedural_height',
    'post_normals',
    'bld_clip_mark',
    'bld_clipped',
    'bld_color',
    'terrain_color',
    'merge_all',
]

for name in COOK_ORDER:
    n = ROOT.node(name)
    if n is None:
        print(f"  SKIP  {name}  (not found)")
        continue
    try:
        n.cook(force=True)
        try:
            g = n.geometry()
            print(f"  OK    {name:30s}  pts={len(g.points()):>7}  prims={len(g.prims()):>7}  errors={n.errors()}")
        except Exception:
            print(f"  OK    {name:30s}  (no geometry)  errors={n.errors()}")
    except Exception as e:
        print(f"  FAIL  {name}  {e}  errors={n.errors()}")

# Set final display/render flags
final = ROOT.node('merge_all') or ROOT.displayNode()
if final:
    final.setDisplayFlag(True)
    final.setRenderFlag(True)
    print(f"\nDisplay/Render set to: {final.path()}")

print("\nDone.")
