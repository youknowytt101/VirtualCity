"""Houdini Python SOP: apply Config/road_profiles.json to road primitives.

Input: road polygons (for example road_clipped) with a highway-like primitive
attribute.

Output: identical geometry plus per-primitive cross-section attributes:
lane_num, lane_width, sidewalk_l, sidewalk_r, curb_height, median_w.
"""

import json
from pathlib import Path

import hou

ROOT = Path(r"__ROOT__")

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


# Load profiles from project root Config/road_profiles.json.
prof_path = ROOT / "Config" / "road_profiles.json"
try:
    with open(prof_path, "r", encoding="utf-8") as f:
        profiles = json.load(f)
except Exception:
    profiles = {}

# Ensure primitive attributes exist
lane_num_a = geo.findPrimAttrib("lane_num") or geo.addAttrib(hou.attribType.Prim, "lane_num", 0)
lane_width_a = geo.findPrimAttrib("lane_width") or geo.addAttrib(hou.attribType.Prim, "lane_width", 0.0)
sidewalk_l_a = geo.findPrimAttrib("sidewalk_l") or geo.addAttrib(hou.attribType.Prim, "sidewalk_l", 0.0)
sidewalk_r_a = geo.findPrimAttrib("sidewalk_r") or geo.addAttrib(hou.attribType.Prim, "sidewalk_r", 0.0)
curb_h_a = geo.findPrimAttrib("curb_height") or geo.addAttrib(hou.attribType.Prim, "curb_height", 0.0)
median_w_a = geo.findPrimAttrib("median_w") or geo.addAttrib(hou.attribType.Prim, "median_w", 0.0)
profile_key_a = geo.findPrimAttrib("road_profile_key") or geo.addAttrib(hou.attribType.Prim, "road_profile_key", "")
profile_applied_a = geo.findPrimAttrib("road_profile_applied") or geo.addAttrib(hou.attribType.Prim, "road_profile_applied", 0)


def normalize_highway(raw: str) -> str:
    hw = str(raw or "").strip()
    if hw in profiles:
        return hw
    if hw.endswith("_link") and hw[:-5] in profiles:
        return hw[:-5]
    aliases = {
        "living_street": "residential",
        "unclassified": "residential",
        "pedestrian": "footway",
        "path": "footway",
        "bridleway": "footway",
        "cycleway": "footway",
        "steps": "footway",
        "track": "service",
        "junction": "residential",
    }
    return aliases.get(hw, "residential")


def prim_highway(prim: hou.Prim) -> str:
    for attr_name in ("highway", "road_highway"):
        try:
            if prim.geometry().findPrimAttrib(attr_name):
                v = prim.attribValue(attr_name)
                if v:
                    return str(v)
        except Exception:
            pass
    return ""


applied = 0
fallback = 0
profile_counts = {}

for prim in geo.prims():
    hw = prim_highway(prim)
    key = normalize_highway(hw)
    prof = profiles.get(key) or profiles.get("residential") or {}
    if key != hw:
        fallback += 1
    try:
        prim.setAttribValue(lane_num_a, int(prof.get("lane_num", 0)))
        prim.setAttribValue(lane_width_a, float(prof.get("lane_width", 0.0)))
        prim.setAttribValue(sidewalk_l_a, float(prof.get("sidewalk_l", 0.0)))
        prim.setAttribValue(sidewalk_r_a, float(prof.get("sidewalk_r", 0.0)))
        prim.setAttribValue(curb_h_a, float(prof.get("curb_height", 0.0)))
        prim.setAttribValue(median_w_a, float(prof.get("median_w", 0.0)))
        prim.setAttribValue(profile_key_a, str(key))
        prim.setAttribValue(profile_applied_a, 1 if prof else 0)
        applied += 1 if prof else 0
        profile_counts[key] = profile_counts.get(key, 0) + 1
    except Exception:
        pass

set_global("road_profile_config_path", prof_path.as_posix())
set_global("road_profile_profile_count", int(len(profiles)))
set_global("road_profile_applied_prims", int(applied))
set_global("road_profile_fallback_prims", int(fallback))
set_global("road_profile_keys", json.dumps(profile_counts, sort_keys=True))
