#!/usr/bin/env python3
"""Download a small OSM road sample for the isolated road research pipeline.

This script is intentionally standalone. It does not import VirtualCity
project modules and writes only inside road_test_pipeline.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any


ROAD_TAGS = [
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "service",
    "living_street",
]


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pipeline_root_from_config(config_path: Path) -> Path:
    return config_path.resolve().parents[1]


def bbox_from_center(lat: float, lon: float, width_m: float, height_m: float) -> dict[str, float]:
    half_h = height_m * 0.5
    half_w = width_m * 0.5
    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = 111_320.0 * math.cos(math.radians(lat))
    return {
        "south": lat - half_h / meters_per_deg_lat,
        "west": lon - half_w / meters_per_deg_lon,
        "north": lat + half_h / meters_per_deg_lat,
        "east": lon + half_w / meters_per_deg_lon,
    }


def build_query(bbox: dict[str, float]) -> str:
    s = bbox["south"]
    w = bbox["west"]
    n = bbox["north"]
    e = bbox["east"]
    road_filters = "\n  ".join(
        f'way["highway"="{tag}"]({s:.8f},{w:.8f},{n:.8f},{e:.8f});'
        for tag in ROAD_TAGS
    )
    return f"""[out:xml][timeout:120];
(
  {road_filters}
  relation["type"="restriction"]({s:.8f},{w:.8f},{n:.8f},{e:.8f});
);
out body;
>;
out skel qt;
"""


def post_overpass(endpoint: str, query: str, timeout_s: int = 150) -> bytes:
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "VirtualCityRoadResearch/0.1",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return resp.read()


def fetch_with_fallback(endpoints: list[str], query: str) -> tuple[bytes, str, list[str]]:
    errors: list[str] = []
    for endpoint in endpoints:
        try:
            payload = post_overpass(endpoint, query)
            if b"<osm" not in payload[:500]:
                errors.append(f"{endpoint}: response does not look like OSM XML")
                continue
            return payload, endpoint, errors
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            errors.append(f"{endpoint}: {exc}")
            time.sleep(1.0)
    raise RuntimeError("All Overpass endpoints failed:\n" + "\n".join(errors))


def parse_osm(xml_path: Path) -> tuple[dict[str, tuple[float, float]], list[dict[str, Any]], list[dict[str, Any]]]:
    root = ET.parse(xml_path).getroot()

    nodes: dict[str, tuple[float, float]] = {}
    for nd in root.findall("node"):
        node_id = nd.get("id")
        lat = nd.get("lat")
        lon = nd.get("lon")
        if node_id and lat and lon:
            nodes[node_id] = (float(lon), float(lat))

    ways: list[dict[str, Any]] = []
    for way in root.findall("way"):
        tags = {tag.get("k", ""): tag.get("v", "") for tag in way.findall("tag")}
        highway = tags.get("highway")
        if not highway:
            continue
        refs = [nd.get("ref") for nd in way.findall("nd") if nd.get("ref")]
        coords = [nodes[ref] for ref in refs if ref in nodes]
        ways.append(
            {
                "id": way.get("id", ""),
                "highway": highway,
                "tags": tags,
                "refs": refs,
                "coords": coords,
            }
        )

    restrictions: list[dict[str, Any]] = []
    for rel in root.findall("relation"):
        tags = {tag.get("k", ""): tag.get("v", "") for tag in rel.findall("tag")}
        if tags.get("type") != "restriction":
            continue
        restrictions.append(
            {
                "id": rel.get("id", ""),
                "restriction": tags.get("restriction", ""),
                "tags": tags,
            }
        )

    return nodes, ways, restrictions


def feature_from_way(index: int, way: dict[str, Any]) -> dict[str, Any] | None:
    coords = way["coords"]
    if len(coords) < 2:
        return None
    tags = way["tags"]
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[round(lon, 8), round(lat, 8)] for lon, lat in coords],
        },
        "properties": {
            "source_provider": "openstreetmap_overpass",
            "source_feature_id": way["id"],
            "seg_id": index,
            "highway": way["highway"],
            "name": tags.get("name", ""),
            "lanes": tags.get("lanes", ""),
            "lanes_forward": tags.get("lanes:forward", ""),
            "lanes_backward": tags.get("lanes:backward", ""),
            "turn_lanes": tags.get("turn:lanes", ""),
            "turn_lanes_forward": tags.get("turn:lanes:forward", ""),
            "turn_lanes_backward": tags.get("turn:lanes:backward", ""),
            "width_m": tags.get("width", ""),
            "oneway": tags.get("oneway", ""),
            "maxspeed": tags.get("maxspeed", ""),
            "bridge": tags.get("bridge", ""),
            "tunnel": tags.get("tunnel", ""),
            "layer": tags.get("layer", ""),
            "provider_tags": tags,
        },
    }


def write_geojson(output: Path, area_id: str, bbox: dict[str, float], ways: list[dict[str, Any]]) -> int:
    features = []
    for index, way in enumerate(ways):
        feat = feature_from_way(index, way)
        if feat:
            features.append(feat)
    fc = {
        "type": "FeatureCollection",
        "metadata": {
            "area_id": area_id,
            "schema": "road_test_pipeline.roads_raw.geojson",
            "coord_domain": "WGS84",
            "axes": "lon, lat",
            "bbox_swen": [
                bbox["south"],
                bbox["west"],
                bbox["north"],
                bbox["east"],
            ],
        },
        "features": features,
    }
    output.write_text(json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(features)


def build_report(
    cfg: dict[str, Any],
    bbox: dict[str, float],
    endpoint: str,
    endpoint_errors: list[str],
    xml_path: Path,
    geojson_path: Path,
    nodes: dict[str, tuple[float, float]],
    ways: list[dict[str, Any]],
    restrictions: list[dict[str, Any]],
) -> dict[str, Any]:
    class_counts = Counter(way["highway"] for way in ways)

    def has_tag(way: dict[str, Any], *keys: str) -> bool:
        return any(way["tags"].get(key) for key in keys)

    total = len(ways)
    report = {
        "area_id": cfg["area_id"],
        "label": cfg.get("label", ""),
        "center": cfg["center"],
        "size_m": cfg["size_m"],
        "bbox": bbox,
        "provider": "openstreetmap_overpass",
        "endpoint_used": endpoint,
        "endpoint_errors": endpoint_errors,
        "outputs": {
            "osm_xml": str(xml_path),
            "roads_raw_geojson": str(geojson_path),
        },
        "counts": {
            "nodes": len(nodes),
            "highway_ways": total,
            "turn_restriction_relations": len(restrictions),
            "ways_with_lanes": sum(has_tag(way, "lanes", "lanes:forward", "lanes:backward") for way in ways),
            "ways_with_turn_lanes": sum(
                has_tag(way, "turn:lanes", "turn:lanes:forward", "turn:lanes:backward")
                for way in ways
            ),
            "ways_with_width": sum(has_tag(way, "width") for way in ways),
            "ways_with_oneway": sum(has_tag(way, "oneway") for way in ways),
            "ways_with_maxspeed": sum(has_tag(way, "maxspeed") for way in ways),
            "ways_with_bridge_or_tunnel_or_layer": sum(
                has_tag(way, "bridge", "tunnel", "layer") for way in ways
            ),
        },
        "highway_class_counts": dict(class_counts.most_common()),
        "notes": [
            "This sample is isolated from the main VirtualCity pipeline.",
            "Lane-level data is expected to be partial in free OSM data; lane_graph must be inferred later.",
            "Topology repair, endpoint snapping and junction clustering are intentionally not performed in this downloader.",
        ],
    }
    if total == 0:
        report["warnings"] = ["No highway ways were returned. Check bbox, endpoint status or Overpass availability."]
    return report


def ensure_dirs(root: Path, cfg: dict[str, Any]) -> dict[str, Path]:
    output_cfg = cfg.get("output", {})
    dirs = {
        "raw": root / output_cfg.get("raw_dir", "data/raw"),
        "processed": root / output_cfg.get("processed_dir", "data/processed"),
        "reports": root / output_cfg.get("reports_dir", "reports"),
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def main() -> int:
    parser = argparse.ArgumentParser(description="Download an isolated Overpass road sample.")
    parser.add_argument("--config", required=True, help="Path to .area.json")
    args = parser.parse_args()

    config_path = Path(args.config)
    cfg = load_config(config_path)
    root = pipeline_root_from_config(config_path)
    dirs = ensure_dirs(root, cfg)

    center = cfg["center"]
    size = cfg["size_m"]
    bbox = bbox_from_center(
        lat=float(center["lat"]),
        lon=float(center["lon"]),
        width_m=float(size["width"]),
        height_m=float(size["height"]),
    )
    query = build_query(bbox)

    area_id = cfg["area_id"]
    query_path = dirs["raw"] / f"{area_id}.overpassql"
    xml_path = dirs["raw"] / f"{area_id}_roads.osm"
    geojson_path = dirs["processed"] / f"{area_id}_roads_raw.geojson"
    report_path = dirs["reports"] / f"{area_id}_download_report.json"

    query_path.write_text(query, encoding="utf-8")

    endpoints = cfg["data_source"]["endpoints"]
    payload, endpoint, endpoint_errors = fetch_with_fallback(endpoints, query)
    xml_path.write_bytes(payload)

    nodes, ways, restrictions = parse_osm(xml_path)
    write_geojson(geojson_path, area_id, bbox, ways)

    report = build_report(
        cfg=cfg,
        bbox=bbox,
        endpoint=endpoint,
        endpoint_errors=endpoint_errors,
        xml_path=xml_path,
        geojson_path=geojson_path,
        nodes=nodes,
        ways=ways,
        restrictions=restrictions,
    )
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "area_id": area_id,
        "endpoint": endpoint,
        "highway_ways": report["counts"]["highway_ways"],
        "turn_restrictions": report["counts"]["turn_restriction_relations"],
        "roads_raw_geojson": str(geojson_path),
        "report": str(report_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
