"""
VirtualCity - UE5 FBX 批量导入脚本
====================================
在 UnrealEditor-Cmd.exe 内运行，自动将建筑和道路 FBX 导入到 /Game/City/

用法（由 run_ue5_import.bat 调用，勿手动执行）:
    UnrealEditor-Cmd.exe <project.uproject> -run=pythonscript -script=<this_file>
"""

import unreal

IMPORTS = [
    {
        "fbx":  r"F:/VirtualCity/Houdini/Export/buildings_v001.fbx",
        "dest": "/Game/City/Buildings",
        "name": "SM_Buildings_v001",
    },
    {
        "fbx":  r"F:/VirtualCity/Houdini/Export/roads_v001.fbx",
        "dest": "/Game/City/Roads",
        "name": "SM_Roads_v001",
    },
]


def make_fbx_options():
    opts = unreal.FbxImportUI()
    opts.set_editor_property("import_mesh", True)
    opts.set_editor_property("import_as_skeletal", False)
    opts.set_editor_property("import_animations", False)
    opts.set_editor_property("import_textures", False)
    opts.set_editor_property("import_materials", False)
    opts.set_editor_property("create_physics_asset", False)

    mesh_opts = opts.get_editor_property("static_mesh_import_data")
    mesh_opts.set_editor_property("combine_meshes", True)
    mesh_opts.set_editor_property("generate_lightmap_u_vs", True)
    mesh_opts.set_editor_property("auto_generate_collision", False)
    return opts


def import_all():
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    tasks = []

    for cfg in IMPORTS:
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", cfg["fbx"])
        task.set_editor_property("destination_path", cfg["dest"])
        task.set_editor_property("destination_name", cfg["name"])
        task.set_editor_property("replace_existing", True)
        task.set_editor_property("automated", True)
        task.set_editor_property("save", True)
        task.set_editor_property("options", make_fbx_options())
        tasks.append(task)
        unreal.log(f"  Queued: {cfg['fbx']} → {cfg['dest']}/{cfg['name']}")

    asset_tools.import_asset_tasks(tasks)

    for cfg in IMPORTS:
        path = f"{cfg['dest']}/{cfg['name']}"
        asset = unreal.EditorAssetLibrary.load_asset(path)
        if asset:
            unreal.log(f"  OK: {path}")
        else:
            unreal.log_warning(f"  MISSING: {path}")

    unreal.log("[VirtualCity] FBX import complete.")


import_all()
