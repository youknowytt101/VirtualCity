"""Houdini Python SOP: prune centerline primitives missing from road_graph.json.

The offline road graph builder can collapse short conflict edges before Houdini
builds surface patches. This SOP bridges that decision back into the Houdini
chain by removing centerline primitives whose seg_id no longer exists in the
current area's road_graph.json.
"""
import json
import re
from pathlib import Path

import hou

ROOT = Path(r"__ROOT__")
CFG = Path(r"__CFG__")

node = hou.pwd()
geo = node.geometry()
geo.clear()

geo_in = node.inputs()[0].geometry() if node.inputs() else None
if geo_in is not None:
    geo.merge(geo_in)


def ensure_global(name, default):
    try:
        if geo.findGlobalAttrib(name) is None:
            geo.addAttrib(hou.attribType.Global, name, default)
    except Exception:
        pass


def set_global(name, value):
    try:
        ensure_global(name, value)
        geo.setGlobalAttribValue(name, value)
    except Exception:
        pass


def load_area_id():
    try:
        cfg = json.loads(CFG.read_text(encoding="utf-8"))
        return str(cfg.get("area_id", "") or "")
    except Exception:
        return ""


def load_keep_seg_ids(area_id):
    if not area_id:
        return None, "missing_area_id", ""
    graph_path = ROOT / "RawData" / "_cleaned" / area_id / "road_graph.json"
    if not graph_path.exists():
        return None, "missing_graph", str(graph_path)
    try:
        data = json.loads(graph_path.read_text(encoding="utf-8"))
    except Exception:
        return None, "invalid_graph", str(graph_path)

    keep = set()
    for edge in data.get("edges", []):
        seg = edge.get("seg_id")
        if seg is None:
            match = re.match(r"^edge_(-?\d+)$", str(edge.get("id", "")))
            if match:
                seg = match.group(1)
        try:
            seg_int = int(seg)
        except (TypeError, ValueError):
            continue
        if seg_int >= 0:
            keep.add(seg_int)

    if not keep:
        return None, "empty_graph_ids", str(graph_path)
    return keep, "filtered", str(graph_path)


area_id = load_area_id()
keep_seg_ids, status, graph_path_text = load_keep_seg_ids(area_id)

removed = 0
kept = 0

if keep_seg_ids is not None:
    seg_attr = geo.findPrimAttrib("seg_id")
    if seg_attr is None:
        status = "missing_seg_id_attr"
        kept = len(geo.prims())
    else:
        doomed_numbers = set()
        for prim in geo.prims():
            try:
                seg_id = int(prim.attribValue(seg_attr))
            except Exception:
                seg_id = -1
            # Keep unknown seg_id values so non-road or legacy data is not
            # accidentally destroyed by a graph-only optimization pass.
            if seg_id >= 0 and seg_id not in keep_seg_ids:
                doomed_numbers.add(prim.number())
            else:
                kept += 1
        if doomed_numbers:
            doomed = [prim for prim in geo.prims() if prim.number() in doomed_numbers]
            removed = len(doomed)
            geo.deletePrims(doomed, False)
else:
    kept = len(geo.prims())

set_global("road_graph_filter_status", status)
set_global("road_graph_filter_area_id", area_id)
set_global("road_graph_filter_graph_path", graph_path_text)
set_global("road_graph_filter_kept_prims", int(kept))
set_global("road_graph_filter_removed_prims", int(removed))
set_global("road_graph_filter_keep_seg_ids", int(len(keep_seg_ids or ())))
