"""修正 Landscape Y 轴比例 + 删除旧 FBX 地形"""
import unreal

sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

for a in sub.get_all_level_actors():
    cls = a.get_class().get_name()
    label = a.get_actor_label()

    # 修正 Landscape Y 比例：604 → 619
    if cls == 'Landscape':
        s = a.get_actor_scale3d()
        a.set_actor_scale3d(unreal.Vector(s.x, 619.0, s.z))
        unreal.log(f"[VirtualCity] Landscape scale → {a.get_actor_scale3d()}")

    # 删除旧 FBX 地形
    if label == 'SM_Terrain_v001':
        sub.destroy_actor(a)
        unreal.log("[VirtualCity] 已删除 SM_Terrain_v001 (FBX 地形)")

unreal.EditorLoadingAndSavingUtils.save_current_level()
unreal.log("[VirtualCity] 场景已保存")
