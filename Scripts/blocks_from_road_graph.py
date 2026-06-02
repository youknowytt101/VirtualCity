"""
Build city Blocks (planar faces) from road_graph.json (Milestone 4 preparation).

- Input: Scripts-generated road_graph.json (see road_graph_builder.py)
- Output: blocks.geojson (FeatureCollection of Polygon, properties: id, area_m2, perimeter_m, hole_count)

This module is pure Python and has no side-effects unless build_blocks(...) is called.
It is not wired into the pipeline by default; refine_data.py can call it when a config flag is enabled.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

try:
    from shapely.geometry import LineString, Polygon, mapping
    from shapely.ops import polygonize
except Exception as e:  # pragma: no cover
    raise RuntimeError("blocks_from_road_graph requires shapely installed") from e


@dataclass
class Block:
    id: int
    polygon: Polygon

    @property
    def area_m2(self) -> float:
        return float(self.polygon.area)

    @property
    def perimeter_m(self) -> float:
        return float(self.polygon.length)

    @property
    def hole_count(self) -> int:
        return max(0, len(getattr(self.polygon, "interiors", [])))


def _edges_to_lines(road_graph: dict) -> List[LineString]:
    lines: List[LineString] = []
    for e in road_graph.get("edges", []):
        coords = e.get("geometry_coords") or []
        if len(coords) < 2:
            continue
        # geometry_coords are [x, z, y], we want XZ plane
        xz = [(float(c[0]), float(c[1])) for c in coords]
        # Deduplicate consecutive duplicates
        dedup = [xz[0]]
        for p in xz[1:]:
            if p != dedup[-1]:
                dedup.append(p)
        if len(dedup) >= 2:
            lines.append(LineString(dedup))
    return lines


def _filter_blocks(polys: Iterable[Polygon], min_area_m2: float, max_area_m2: float) -> List[Polygon]:
    out: List[Polygon] = []
    for p in polys:
        if not p.is_valid:
            # Try fix simple validity issues
            p = p.buffer(0)
        a = float(p.area)
        if a <= 1e-6:
            continue
        if a < min_area_m2:
            continue
        if max_area_m2 > 0 and a > max_area_m2:
            continue
        out.append(p)
    return out


def _subdivide_block_into_lots(block_poly: Polygon, setback_m: float = 4.0, target_lot_width_m: float = 30.0) -> List[Polygon]:
    """
    Subdivide a block polygon into individual lots using setback and grid-based division.

    - setback_m: inward offset from block boundary (red line setback, 3-5m typical)
    - target_lot_width_m: approximate width for each lot subdivision

    Returns list of lot polygons.
    """
    if not block_poly.is_valid or block_poly.area < 100.0:
        return [block_poly]

    # Apply setback (inward buffer)
    try:
        setback_poly = block_poly.buffer(-setback_m)
    except Exception:
        return [block_poly]

    if not setback_poly.is_valid or setback_poly.area < 50.0:
        return [block_poly]

    # For now, return the setback polygon as a single lot
    # Full subdivision (OBB-based or grid-based) can be added in future iterations
    if isinstance(setback_poly, Polygon):
        return [setback_poly]
    else:
        # MultiPolygon result from buffer
        return [p for p in setback_poly.geoms if isinstance(p, Polygon)]


def build_blocks(road_graph_path: Path, output_geojson_path: Path,
                 min_area_m2: float = 50.0, max_area_m2: float = 0.0,
                 enable_lot_subdivision: bool = False, setback_m: float = 4.0) -> dict:
    """
    Build planar blocks by polygonizing the road XZ lines.

    - min_area_m2: drop tiny slivers
    - max_area_m2: drop giant outer polygons (0 to disable upper bound)
    - enable_lot_subdivision: if True, subdivide blocks into lots with setback
    - setback_m: inward offset for lot boundaries (red line setback, 3-5m typical)

    Returns simple stats.
    """
    road_graph = json.loads(Path(road_graph_path).read_text(encoding="utf-8"))
    lines = _edges_to_lines(road_graph)
    polys = list(polygonize(lines))
    filtered = _filter_blocks(polys, min_area_m2=min_area_m2, max_area_m2=max_area_m2)

    features = []
    feature_id = 1
    for block_idx, poly in enumerate(filtered, start=1):
        if enable_lot_subdivision:
            lots = _subdivide_block_into_lots(poly, setback_m=setback_m)
        else:
            lots = [poly]

        for lot_poly in lots:
            if not lot_poly.is_valid or lot_poly.area < 10.0:
                continue
            blk = Block(id=feature_id, polygon=lot_poly)
            feat = {
                "type": "Feature",
                "id": f"lot_{feature_id}",
                "geometry": mapping(lot_poly),
                "properties": {
                    "id": feature_id,
                    "block_id": block_idx,
                    "area_m2": blk.area_m2,
                    "perimeter_m": blk.perimeter_m,
                    "hole_count": blk.hole_count,
                    "is_lot": enable_lot_subdivision,
                },
            }
            features.append(feat)
            feature_id += 1

    output_geojson_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_geojson_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False, indent=2)
        f.write("\n")

    return {
        "features": len(features),
        "min_area_m2": min((float(feat["properties"]["area_m2"]) for feat in features), default=None),
        "max_area_m2": max((float(feat["properties"]["area_m2"]) for feat in features), default=None),
    }


if __name__ == "__main__":  # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser(description="Build city blocks from road_graph.json")
    ap.add_argument("--graph", required=True, help="Path to road_graph.json")
    ap.add_argument("--out", required=True, help="Output blocks.geojson path")
    ap.add_argument("--min-area", type=float, default=50.0)
    ap.add_argument("--max-area", type=float, default=0.0)
    args = ap.parse_args()
    stats = build_blocks(Path(args.graph), Path(args.out), args.min_area, args.max_area)
    print("blocks:", stats)
