"""Export the cooked whitebox to a layered GLB via the GLTF ROP.

Called at the end of recook within the existing Houdini rpyc session — no new
connection, geometry already cooked in memory — so it's cheap and has no
contention with a separate export process.
"""
import os

from shared.vc_paths import EXPORT

_LAYER_SOURCES = {
    "terrain": ("terrain_color", "dem_subdivide", "dem_terrain"),
    "buildings": ("bld_with_foundation", "bld_clipped", "post_normals"),
    "roads": ("road_surface_color", "road_capsule_surface_preview", "road_clipped"),
}


def _set_first(node, names, value):
    """Set the first parm that exists (GLTF ROP parm names vary by H version)."""
    for name in names:
        parm = node.parm(name)
        if parm is not None:
            parm.set(value)
            return name
    raise RuntimeError("none of parms {} on {}".format(names, node.path()))


def _set_first_optional(node, names, value):
    for name in names:
        parm = node.parm(name)
        if parm is not None:
            parm.set(value)
            return name
    return None


def _set_if_present(node, name, value):
    parm = node.parm(name)
    if parm is None:
        return False
    parm.set(value)
    return True


def _set_export_root(rop, layers):
    _set_if_present(rop, "usesoppath", 0)
    if _set_if_present(rop, "objpath", "/obj"):
        _set_if_present(rop, "objects", "VC_whitebox_*")
        _set_if_present(rop, "forceobjects", "")
        _set_if_present(rop, "exportmaterials", 0)
        _set_if_present(rop, "exportnames", 1)
        _set_if_present(rop, "exportmeshnames", 1)
        return
    if _set_first_optional(rop, ["objpath1", "object1", "rootpath", "scenepath"], "/obj"):
        _set_if_present(rop, "objects", "VC_whitebox_*")
        _set_if_present(rop, "forceobjects", "")
        _set_if_present(rop, "exportmaterials", 0)
        _set_if_present(rop, "exportnames", 1)
        _set_if_present(rop, "exportmeshnames", 1)
        return
    display_sops = []
    for layer in layers:
        display = layer.displayNode()
        if display is not None:
            display_sops.append(display.path())
    if not display_sops:
        raise RuntimeError("whitebox layers have no display SOPs")
    _set_first(rop, ["soppath", "startnode"], display_sops[0])


def _has_geometry(node):
    if node is None:
        return False
    geo = node.geometry()
    return bool(geo is not None and geo.intrinsicValue("primitivecount") > 0)


def _select_layer_source(hou, obj_path, layer_key):
    for name in _LAYER_SOURCES[layer_key]:
        node = hou.node(obj_path + "/" + name)
        if _has_geometry(node):
            return node
    return None


def _destroy_node(node):
    if node:
        node.destroy()


def _destroy_whitebox_layers(layers):
    for layer in layers or []:
        _destroy_node(layer)


def _set_flag_if_present(node, method_name, value):
    method = getattr(node, method_name, None)
    if method is not None:
        method(value)
        return True
    return False


def _build_layered_whitebox_objects(hou, obj_path):
    obj = hou.node("/obj")
    _destroy_node(hou.node("/obj/VC_whitebox"))
    for layer_key in ("terrain", "buildings", "roads"):
        _destroy_node(hou.node("/obj/VC_whitebox_{}".format(layer_key)))
    exported = []
    layers = []
    for layer_key in ("terrain", "buildings", "roads"):
        src = _select_layer_source(hou, obj_path, layer_key)
        if src is None:
            print("  [GLB] {} 图层跳过: 找不到有效源 {}".format(layer_key, _LAYER_SOURCES[layer_key]))
            continue
        layer = obj.createNode("geo", "VC_whitebox_{}".format(layer_key))
        for child in list(layer.children()):
            child.destroy()
        merge = layer.createNode("object_merge", "{}_source".format(layer_key))
        _set_first(merge, ["objpath1", "objpath", "object1"], src.path())
        xformtype = merge.parm("xformtype")
        if xformtype is not None:
            xformtype.set(1)
        _set_flag_if_present(merge, "setDisplayFlag", True)
        _set_flag_if_present(merge, "setRenderFlag", True)
        _set_flag_if_present(layer, "setDisplayFlag", True)
        layers.append(layer)
        exported.append(layer_key)
    if not exported:
        for layer in layers:
            layer.destroy()
        return None
    obj.layoutChildren(layers)
    print("  [GLB] 白盒图层: {}".format(", ".join(exported)))
    return layers


def export_whitebox(hou, obj_path):
    """Export terrain/buildings/roads under obj_path to EXPORT/whitebox_v001.glb.

    Returns the GLB path on success, else None. Never raises — the caller
    treats a GLB failure as advisory (it must not fail the build).
    """
    layers = _build_layered_whitebox_objects(hou, obj_path)
    if layers is None:
        print("  [GLB] 跳过: 找不到有效白盒图层")
        return None

    glb_path = (EXPORT / "whitebox_v001.glb").as_posix()
    os.makedirs(EXPORT.as_posix(), exist_ok=True)
    rop = None
    try:
        out_net = hou.node("/out")
        old = hou.node("/out/gltf_whitebox")
        _destroy_node(old)
        rop = out_net.createNode("gltf", "gltf_whitebox")
        _set_first(rop, ["file", "sopoutput", "outputfile"], glb_path)
        _set_export_root(rop, layers)
        trange = rop.parm("trange")
        if trange is not None:
            trange.set(0)
        rop.render()
    finally:
        if rop is not None:
            rop.destroy()
        _destroy_whitebox_layers(layers)

    size = os.path.getsize(glb_path) if os.path.exists(glb_path) else 0
    if size < 100:
        print("  [GLB] 警告: GLB 过小或未生成 ({} bytes)".format(size))
        return None
    print("  [GLB] 白盒导出: {} ({:.1f} KB)".format(glb_path, size / 1024))
    return glb_path
