"""UE5 场景清理 — 删除旧版 Actor，保留 v001 版本"""
import unreal

subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
to_delete = {'Buildings_Pattaya', 'Roads_Pattaya', 'SM_Roads_v2'}

deleted = []
for a in subsystem.get_all_level_actors():
    if a.get_actor_label() in to_delete:
        label = a.get_actor_label()
        subsystem.destroy_actor(a)
        deleted.append(label)
        unreal.log(f"[VirtualCity] 已删除旧 Actor: {label}")

if deleted:
    unreal.log(f"[VirtualCity] 共删除 {len(deleted)} 个旧 Actor")
    unreal.EditorLoadingAndSavingUtils.save_current_level()
    unreal.log("[VirtualCity] 场景已保存")
else:
    unreal.log("[VirtualCity] 无需清理，旧 Actor 已不存在")
