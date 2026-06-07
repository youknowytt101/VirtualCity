"""探针：列出 UE5 内可用的 Landscape 相关 Python API"""
import unreal

sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

# 找 Landscape actor
landscape = None
for a in sub.get_all_level_actors():
    if a.get_class().get_name() == 'Landscape':
        landscape = a
        break

unreal.log(f"[PROBE] Landscape actor: {landscape}")

if landscape:
    # Actor 上的方法
    methods = sorted([m for m in dir(landscape)
                      if any(k in m.lower() for k in ('height','import','component','info','data'))])
    unreal.log(f"[PROBE] Landscape methods: {methods}")

    # LandscapeComponent
    comps = landscape.get_components_by_class(unreal.LandscapeComponent)
    unreal.log(f"[PROBE] LandscapeComponent count: {len(comps)}")
    if comps:
        c = list(comps)[0]
        comp_methods = sorted([m for m in dir(c)
                               if any(k in m.lower() for k in ('height','data','section','base'))])
        unreal.log(f"[PROBE] LandscapeComponent methods: {comp_methods}")
        base = c.get_editor_property('section_base_x'), c.get_editor_property('section_base_y')
        unreal.log(f"[PROBE] First component section_base: {base}")

# LandscapeEditorObject
try:
    leo = unreal.LandscapeEditorObject.get_default_object()
    leo_props = sorted([p for p in dir(leo)
                        if any(k in p.lower() for k in ('height','import','scale','file'))])
    unreal.log(f"[PROBE] LandscapeEditorObject props: {leo_props}")
except Exception as e:
    unreal.log(f"[PROBE] LandscapeEditorObject: {e}")

# LandscapeSubsystem
try:
    ls = unreal.get_editor_subsystem(unreal.LandscapeSubsystem)
    ls_methods = sorted([m for m in dir(ls) if not m.startswith('_')])
    unreal.log(f"[PROBE] LandscapeSubsystem methods: {ls_methods}")
except Exception as e:
    unreal.log(f"[PROBE] LandscapeSubsystem: {e}")
