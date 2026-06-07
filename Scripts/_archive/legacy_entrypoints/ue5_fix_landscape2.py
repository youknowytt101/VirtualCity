"""修正 1009×1009 Landscape 的 Y 比例 + 清理旧 FBX 地形"""
import unreal

sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
fixed = False

for a in sub.get_all_level_actors():
    cls = a.get_class().get_name()
    label = a.get_actor_label()

    if cls == 'Landscape':
        s = a.get_actor_scale3d()
        new_scale = unreal.Vector(s.x, 309.5, s.z)
        a.set_actor_scale3d(new_scale)
        unreal.log(f"[VirtualCity] Landscape scale: ({s.x:.1f},{s.y:.1f},{s.z:.2f}) → {new_scale}")
        fixed = True

    if label == 'SM_Terrain_v001':
        sub.destroy_actor(a)
        unreal.log("[VirtualCity] 已删除 SM_Terrain_v001")

if not fixed:
    unreal.log("[VirtualCity] WARNING: 未找到 Landscape actor")

unreal.EditorLoadingAndSavingUtils.save_current_level()
unreal.log("[VirtualCity] 场景已保存")
