# Houdini Python SOP — Road Vertical Smoother
# Input 0: centerlines with "highway" and height snapped to DEM
# Output: centerlines with vertically smoothed and slope-clamped height (Y coordinate)
#
import math
import hou

node = hou.pwd()
geo_out = node.geometry()
geo_out.clear()

geo_in = node.inputs()[0].geometry() if node.inputs() else None
if geo_in is None:
    raise hou.Error("road_vertical_smoother: no input centerlines")

# Copy the entire input geometry to output as a starting point
geo_out.copy(geo_in)

# Map highway types to maximum allowed longitudinal slopes
SLOPE_LIMITS = {
    "motorway": 0.06,       # 6%
    "motorway_link": 0.06,
    "trunk": 0.06,
    "trunk_link": 0.06,
    "primary": 0.08,        # 8%
    "primary_link": 0.08,
    "secondary": 0.08,
    "secondary_link": 0.08,
    "tertiary": 0.10,       # 10%
    "tertiary_link": 0.10,
    "residential": 0.12,    # 12%
    "service": 0.12,
    "unclassified": 0.12,
    "living_street": 0.12,
    "footway": 0.15,        # 15%
    "pedestrian": 0.12,
    "path": 0.15,
}

# ── Step 1: Laplacian 1D Smoothing on Elevations ──────────────────
# Smooth the height along each individual road curve (primitive)
for prim in geo_out.prims():
    pts = list(prim.points())
    n_pts = len(pts)
    if n_pts < 3:
        continue

    # Perform 30 iterations of Laplacian 1D smoothing on point Y coordinate
    y_vals = [p.position()[1] for p in pts]
    for _ in range(30):
        new_y = list(y_vals)
        for i in range(1, n_pts - 1):
            new_y[i] = 0.5 * y_vals[i] + 0.25 * (y_vals[i-1] + y_vals[i+1])
        y_vals = new_y

    for i, p in enumerate(pts):
        pos = p.position()
        p.setPosition(hou.Vector3(pos[0], y_vals[i], pos[2]))

# ── Step 2: Longitudinal Slope Clamping ───────────────────────────
# Apply forward-backward clamping passes to prevent sudden steep drops
for prim in geo_out.prims():
    hw = prim.attribValue("highway") if prim.geometry().findPrimAttrib("highway") else "residential"
    max_slope = SLOPE_LIMITS.get(hw, 0.12)

    pts = list(prim.points())
    n_pts = len(pts)
    if n_pts < 2:
        continue

    # Read smoothed positions
    positions = [p.position() for p in pts]

    # Forward pass: clamp slopes going forward
    for i in range(n_pts - 1):
        p1 = positions[i]
        p2 = positions[i+1]
        dxz = math.hypot(p2[0] - p1[0], p2[2] - p1[2])
        if dxz > 1e-4:
            max_dy = dxz * max_slope
            dy = p2[1] - p1[1]
            if abs(dy) > max_dy:
                # Clamp next height relative to current
                clamped_y = p1[1] + math.copysign(max_dy, dy)
                positions[i+1] = hou.Vector3(p2[0], clamped_y, p2[2])

    # Backward pass: clamp slopes going backward
    for i in range(n_pts - 1, 0, -1):
        p1 = positions[i]
        p2 = positions[i-1]
        dxz = math.hypot(p2[0] - p1[0], p2[2] - p1[2])
        if dxz > 1e-4:
            max_dy = dxz * max_slope
            dy = p2[1] - p1[1]
            if abs(dy) > max_dy:
                # Clamp previous height relative to current
                clamped_y = p1[1] + math.copysign(max_dy, dy)
                positions[i-1] = hou.Vector3(p2[0], clamped_y, p2[2])

    # Apply final positions
    for i, p in enumerate(pts):
        p.setPosition(positions[i])
