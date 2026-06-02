"""Houdini Python SOP: add curb height variation and micro-details to road geometry.

Input: road primitives with curb_height attribute (from road_profile_apply).

Output: same geometry with:
- Curb height variation (±2cm random noise along road flow direction)
- Micro-detail attributes for downstream Sweep SOP

This implements Milestone 3 "CGA Naturalization" — adding subtle randomness
to break perfect CG uniformity while maintaining overall road structure.
"""

import json
import math
from pathlib import Path

import hou

ROOT = Path(r"__ROOT__")

node = hou.pwd()
geo = node.geometry()
geo_in = node.inputs()[0].geometry() if node.inputs() else None

if geo_in is not None:
    geo.clear()
    geo.merge(geo_in)

# Ensure curb variation attributes exist
curb_height_var_a = geo.findPrimAttrib("curb_height_variation_m") or geo.addAttrib(
    hou.attribType.Prim, "curb_height_variation_m", 0.0
)
curb_noise_seed_a = geo.findPrimAttrib("curb_noise_seed") or geo.addAttrib(
    hou.attribType.Prim, "curb_noise_seed", 0
)

# Load curb variation config from Config/road_curb_variation.json if available
curb_config = {
    "variation_amplitude_m": 0.02,  # ±2cm
    "variation_frequency": 2.5,  # cycles per 10m
    "noise_type": "perlin",  # perlin or simplex
}

try:
    cfg_path = ROOT / "Config" / "road_curb_variation.json"
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            curb_config.update(loaded)
except Exception:
    pass


def pseudo_random(seed: int, x: float) -> float:
    """Simple pseudo-random generator based on seed and position."""
    val = math.sin(seed * 12.9898 + x * 78.233) * 43758.5453
    return val - math.floor(val)


def perlin_like_noise(seed: int, x: float, freq: float) -> float:
    """Simple Perlin-like noise approximation."""
    scaled_x = x * freq
    int_x = int(math.floor(scaled_x))
    frac_x = scaled_x - int_x
    # Smooth interpolation (Hermite curve)
    u = frac_x * frac_x * (3.0 - 2.0 * frac_x)
    # Two random values
    a = pseudo_random(seed, float(int_x))
    b = pseudo_random(seed, float(int_x + 1))
    return a + (b - a) * u


def prim_points(prim: hou.Prim) -> list[hou.Vector3]:
    """Get all points of a primitive in order."""
    return [v.point().position() for v in prim.vertices()]


def prim_flow_distance(prim: hou.Prim) -> float:
    """Estimate flow distance along primitive (perimeter or centerline)."""
    pts = prim_points(prim)
    dist = 0.0
    for i in range(len(pts) - 1):
        p0, p1 = pts[i], pts[i + 1]
        dist += math.hypot(p1.x() - p0.x(), p1.z() - p0.z())
    return dist


applied = 0
for prim in geo.prims():
    try:
        # Get curb height if available
        curb_h = 0.0
        try:
            if geo.findPrimAttrib("curb_height"):
                curb_h = float(prim.attribValue("curb_height") or 0.0)
        except Exception:
            pass

        # Compute flow distance and variation
        flow_dist = prim_flow_distance(prim)
        seed = hash(prim.number()) % 10000
        noise_val = perlin_like_noise(
            seed,
            flow_dist,
            curb_config["variation_frequency"] / 10.0,
        )
        # Map noise from [0, 1] to [-amplitude, +amplitude]
        variation = (noise_val - 0.5) * 2.0 * curb_config["variation_amplitude_m"]

        prim.setAttribValue(curb_height_var_a, float(variation))
        prim.setAttribValue(curb_noise_seed_a, int(seed))
        applied += 1
    except Exception:
        pass

# Global stats
try:
    geo.setGlobalAttribValue("road_curb_variation_applied_prims", int(applied))
    geo.setGlobalAttribValue("road_curb_variation_amplitude_m", float(curb_config["variation_amplitude_m"]))
    geo.setGlobalAttribValue("road_curb_variation_frequency", float(curb_config["variation_frequency"]))
except Exception:
    pass
