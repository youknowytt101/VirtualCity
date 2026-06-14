"""Pure geographic aggregation of downloaded tiles into contiguous areas.

A "downloaded area" is not a stored entity but a view over the set of all
downloaded 1km tiles. Orthogonally adjacent tiles (sharing an edge) form one
connected component, counted/named/bounded as a unit. Tiles are the truth;
an area is a pure projection of them. This is why two separately-recorded
downloads that touch (pattaya's 11x11 block and the single tile immediately
east of it) collapse into one area with a combined count.

Input sources are plain records:
  {"id": str, "label": str, "named": bool, "tile_ids": [str, ...]}
The first source to claim a tile owns it (for naming); duplicates are ignored.
"""
from __future__ import annotations

from typing import Any, Sequence

import vc_grid


def _parse(tile_id: str):
    try:
        return vc_grid.parse_tile_id(tile_id)
    except ValueError:
        return None


def _envelope(tile_ids: Sequence[str]) -> list[float]:
    lons: list[float] = []
    lats: list[float] = []
    for tid in tile_ids:
        try:
            west, south, east, north = vc_grid.tile_by_id(tid)["bbox"]
        except ValueError:
            continue
        lons += [west, east]
        lats += [south, north]
    if not lons:
        return []
    return [min(lons), min(lats), max(lons), max(lats)]


def aggregate(sources: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group all source tiles into edge-connected components on the fixed grid."""
    tile_origin: dict[str, str] = {}
    source_named: dict[str, bool] = {}
    source_label: dict[str, str] = {}
    for src in sources:
        sid = str(src.get("id") or "")
        source_named[sid] = bool(src.get("named"))
        source_label[sid] = str(src.get("label") or "")
        for tid in src.get("tile_ids") or []:
            tile_origin.setdefault(str(tid), sid)

    nodes: dict[tuple, str] = {}
    for tid in tile_origin:
        spec = _parse(tid)
        if not spec:
            continue
        key = (spec["zone"], spec["northern"], spec["easting"], spec["northing"])
        nodes[key] = tid

    size = vc_grid.TILE_SIZE_M
    visited: set[tuple] = set()
    components: list[list[tuple]] = []
    for key in nodes:
        if key in visited:
            continue
        stack = [key]
        visited.add(key)
        comp: list[tuple] = []
        while stack:
            z, hemi, e, n = stack.pop()
            comp.append((z, hemi, e, n))
            for de, dn in ((size, 0), (-size, 0), (0, size), (0, -size)):
                nb = (z, hemi, e + de, n + dn)
                if nb in nodes and nb not in visited:
                    visited.add(nb)
                    stack.append(nb)
        components.append(comp)

    areas: list[dict[str, Any]] = []
    for comp in components:
        tids = [nodes[k] for k in comp]
        contrib: dict[str, int] = {}
        for tid in tids:
            sid = tile_origin.get(tid, "")
            contrib[sid] = contrib.get(sid, 0) + 1
        named = [s for s in contrib if source_named.get(s)]
        pool = named or list(contrib)
        best = max(pool, key=lambda s: (contrib[s], s)) if pool else ""
        bbox = _envelope(tids)
        if not bbox:
            continue
        center = [(bbox[1] + bbox[3]) / 2.0, (bbox[0] + bbox[2]) / 2.0]
        areas.append({
            "id": best,
            "label": source_label.get(best) or best,
            "tile_count": len(tids),
            "tile_ids": sorted(tids),
            "bbox": bbox,
            "center": center,
        })

    areas.sort(key=lambda a: (-a["tile_count"], a["id"]))
    return areas