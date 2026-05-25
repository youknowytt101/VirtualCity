import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for a in sub.get_all_level_actors():
    loc = a.get_actor_location()
    scale = a.get_actor_scale3d()
    unreal.log(f"{a.get_actor_label()} | {a.get_class().get_name()} | Z={loc.z:.0f} | scale=({scale.x:.1f},{scale.y:.1f},{scale.z:.2f})")
