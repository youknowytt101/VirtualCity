#!/usr/bin/env python3
"""Export lane_graph.json and movement corridors to an SVG visualization.

The SVG is a human QA view only. The source of truth remains the structured
JSON artifacts: lane_graph.json and movement_corridor_candidates.json.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


ANCHOR_MARKER_RADIUS_PX = 0.55
ANCHOR_MARKER_STROKE_WIDTH_PX = 0.12
DEFAULT_REVIEW_WIDTH_PX = 3200
DEFAULT_MAX_HEIGHT_PX = 9000


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pipeline_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def points_from_lanes(lane_graph: dict[str, Any]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for lane in lane_graph.get("lanes", []):
        for point in lane.get("centerline_xz") or []:
            if len(point) >= 2:
                points.append((float(point[0]), float(point[1])))
    return points


def points_from_movement_corridors(movement_corridors: dict[str, Any] | None) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    if not movement_corridors:
        return points
    for case in movement_corridors.get("cases", []):
        for anchor_key in ("lane_entry_anchor", "lane_exit_anchor"):
            anchor = case.get(anchor_key) or {}
            point = anchor.get("point_xz") or []
            if len(point) >= 2:
                points.append((float(point[0]), float(point[1])))
        for candidate in case.get("candidates", []):
            for point in candidate.get("centerline_xz") or []:
                if len(point) >= 2:
                    points.append((float(point[0]), float(point[1])))
    return points


def points_from_compound_transactions(compound_transactions: dict[str, Any] | None) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    if not compound_transactions:
        return points
    for case in compound_transactions.get("compound_movement_corridor_cases", []):
        for anchor_key in ("lane_entry_anchor", "lane_exit_anchor"):
            anchor = case.get(anchor_key) or {}
            point = anchor.get("point_xz") or []
            if len(point) >= 2:
                points.append((float(point[0]), float(point[1])))
        for candidate in case.get("candidates", []):
            for point in candidate.get("centerline_xz") or []:
                if len(point) >= 2:
                    points.append((float(point[0]), float(point[1])))
    return points


def lane_by_id(lane_graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(lane.get("lane_id") or ""): lane for lane in lane_graph.get("lanes", [])}


def scale_transform(
    points: list[tuple[float, float]],
    *,
    width_px: int,
    max_height_px: int,
    padding_px: int,
) -> tuple[int, int, Any]:
    if not points:
        return width_px, width_px, lambda x, z: (padding_px, padding_px)
    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_z = min(point[1] for point in points)
    max_z = max(point[1] for point in points)
    span_x = max(1.0, max_x - min_x)
    span_z = max(1.0, max_z - min_z)
    drawable_w = max(100, width_px - padding_px * 2)
    scale = drawable_w / span_x
    height_px = int(span_z * scale + padding_px * 2)
    height_px = max(720, min(max_height_px, height_px))
    drawable_h = max(100, height_px - padding_px * 2)
    scale = min(drawable_w / span_x, drawable_h / span_z)

    def transform(x: float, z: float) -> tuple[float, float]:
        sx = padding_px + (x - min_x) * scale
        sy = padding_px + (max_z - z) * scale
        return round(sx, 2), round(sy, 2)

    return width_px, height_px, transform


def polyline(points: list[list[float]], transform: Any) -> str:
    return " ".join(
        f"{transform(float(point[0]), float(point[1]))[0]},{transform(float(point[0]), float(point[1]))[1]}"
        for point in points
        if len(point) >= 2
    )


def svg_title(value: str) -> str:
    return f"<title>{html.escape(value)}</title>"


def endpoint(lane: dict[str, Any], side: str) -> tuple[float, float] | None:
    points = lane.get("centerline_xz") or []
    if not points:
        return None
    point = points[-1] if side == "end" else points[0]
    if len(point) < 2:
        return None
    return float(point[0]), float(point[1])


def candidate_for_visual(case: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [candidate for candidate in case.get("candidates", []) if isinstance(candidate, dict)]
    if not candidates:
        return None
    movement_kind = str(case.get("movement_kind") or "")
    if movement_kind == "through":
        preferred = ("topology_straight_baseline", "compound_topology_straight_baseline")
    else:
        preferred = ("bezier_g1_preview", "compound_bezier_g1_preview")
    for family in preferred:
        for candidate in candidates:
            if str(candidate.get("family") or "") == family:
                return candidate
    return candidates[0]


def movement_case_lines(
    *,
    movement_corridors: dict[str, Any],
    transform: Any,
    max_cases: int,
) -> tuple[list[str], list[str], dict[str, Any]]:
    corridor_lines: list[str] = []
    anchor_marks: list[str] = []
    rendered = 0
    source_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    issue_counts: dict[str, int] = {}

    for case in movement_corridors.get("cases", []):
        if rendered >= max_cases:
            break
        candidate = candidate_for_visual(case)
        if candidate is None:
            continue
        points = candidate.get("centerline_xz") or []
        if len(points) < 2:
            continue

        family = str(candidate.get("family") or "unknown")
        family_counts[family] = family_counts.get(family, 0) + 1
        for issue in candidate.get("issues") or []:
            issue = str(issue)
            issue_counts[issue] = issue_counts.get(issue, 0) + 1

        confidence = float(case.get("confidence") or 0.0)
        movement_kind = str(case.get("movement_kind") or "unknown")
        color = {
            "through": "#0ea5e9",
            "left": "#f97316",
            "right": "#a855f7",
        }.get(movement_kind, "#f59e0b")
        opacity = 0.18 + min(0.34, confidence * 0.38)
        width = 0.72 if confidence < 0.5 else 0.95
        tooltip = (
            f"corridor_id={case.get('corridor_id', '')}; "
            f"movement={movement_kind}; family={family}; confidence={confidence:.3f}"
        )
        corridor_lines.append(
            f'<polyline points="{polyline(points, transform)}" fill="none" '
            f'stroke="{color}" stroke-width="{width}" stroke-opacity="{opacity:.2f}" '
            f'stroke-linecap="round" stroke-linejoin="round">{svg_title(tooltip)}</polyline>'
        )

        for anchor_key, fill in (("lane_entry_anchor", "#22c55e"), ("lane_exit_anchor", "#ef4444")):
            anchor = case.get(anchor_key) or {}
            point = anchor.get("point_xz") or []
            if len(point) < 2:
                continue
            source = str(anchor.get("source") or "unknown")
            source_counts[source] = source_counts.get(source, 0) + 1
            sx, sy = transform(float(point[0]), float(point[1]))
            tooltip = (
                f"{anchor_key}; lane={anchor.get('lane_id', '')}; edge={anchor.get('edge_id', '')}; "
                f"source={source}; trim={anchor.get('entry_trim_m', '')}"
            )
            anchor_marks.append(
                f'<circle cx="{sx}" cy="{sy}" r="{ANCHOR_MARKER_RADIUS_PX}" fill="{fill}" fill-opacity="0.76" '
                f'stroke="#0f172a" stroke-width="{ANCHOR_MARKER_STROKE_WIDTH_PX}">{svg_title(tooltip)}</circle>'
            )
        rendered += 1

    metrics = {
        "movement_corridors_rendered": rendered,
        "anchor_markers_rendered": len(anchor_marks),
        "anchor_source_counts": dict(sorted(source_counts.items())),
        "visual_candidate_family_counts": dict(sorted(family_counts.items())),
        "visual_candidate_issue_counts": dict(sorted(issue_counts.items())),
    }
    return corridor_lines, anchor_marks, metrics


def compound_case_lines(
    *,
    compound_transactions: dict[str, Any],
    transform: Any,
    max_cases: int,
) -> tuple[list[str], list[str], dict[str, Any]]:
    corridor_lines: list[str] = []
    anchor_marks: list[str] = []
    rendered = 0
    family_counts: dict[str, int] = {}
    issue_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}

    for case in compound_transactions.get("compound_movement_corridor_cases", []):
        if rendered >= max_cases:
            break
        candidate = candidate_for_visual(case)
        if candidate is None:
            continue
        points = candidate.get("centerline_xz") or []
        if len(points) < 2:
            continue

        family = str(candidate.get("family") or "unknown")
        family_counts[family] = family_counts.get(family, 0) + 1
        status = str(case.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        for issue in candidate.get("issues") or []:
            issue = str(issue)
            issue_counts[issue] = issue_counts.get(issue, 0) + 1

        movement_kind = str(case.get("movement_kind") or "unknown")
        color = {
            "through": "#06b6d4",
            "left": "#ec4899",
            "right": "#8b5cf6",
        }.get(movement_kind, "#f43f5e")
        tooltip = (
            f"compound_case_id={case.get('compound_case_id', '')}; "
            f"movement={movement_kind}; family={family}; status={status}; "
            f"from={case.get('from_lane_id', '')}; to={case.get('to_lane_id', '')}"
        )
        corridor_lines.append(
            f'<polyline points="{polyline(points, transform)}" fill="none" '
            f'stroke="{color}" stroke-width="1.65" stroke-opacity="0.88" stroke-dasharray="4 2" '
            f'stroke-linecap="round" stroke-linejoin="round">{svg_title(tooltip)}</polyline>'
        )

        for anchor_key, fill in (("lane_entry_anchor", "#16a34a"), ("lane_exit_anchor", "#dc2626")):
            anchor = case.get(anchor_key) or {}
            point = anchor.get("point_xz") or []
            if len(point) < 2:
                continue
            sx, sy = transform(float(point[0]), float(point[1]))
            tooltip = (
                f"compound {anchor_key}; lane={anchor.get('lane_id', '')}; edge={anchor.get('edge_id', '')}; "
                f"source={anchor.get('source', '')}; trim={anchor.get('entry_trim_m', '')}"
            )
            anchor_marks.append(
                f'<circle cx="{sx}" cy="{sy}" r="{ANCHOR_MARKER_RADIUS_PX + 0.12}" fill="{fill}" fill-opacity="0.88" '
                f'stroke="#0f172a" stroke-width="{ANCHOR_MARKER_STROKE_WIDTH_PX + 0.04}">{svg_title(tooltip)}</circle>'
            )
        rendered += 1

    metrics = {
        "compound_corridors_rendered": rendered,
        "compound_anchor_markers_rendered": len(anchor_marks),
        "compound_case_status_counts": dict(sorted(status_counts.items())),
        "compound_visual_candidate_family_counts": dict(sorted(family_counts.items())),
        "compound_visual_candidate_issue_counts": dict(sorted(issue_counts.items())),
    }
    return corridor_lines, anchor_marks, metrics


def lane_link_preview_lines(
    *,
    links: list[dict[str, Any]],
    lanes_by_id: dict[str, dict[str, Any]],
    transform: Any,
    max_links: int,
) -> tuple[list[str], int]:
    link_lines: list[str] = []
    rendered_links = 0
    for link in links:
        if rendered_links >= max_links:
            break
        if str(link.get("link_kind") or "") != "junction_movement":
            continue
        from_lane = lanes_by_id.get(str(link.get("from_lane_id") or ""))
        to_lane = lanes_by_id.get(str(link.get("to_lane_id") or ""))
        if not from_lane or not to_lane:
            continue
        start = endpoint(from_lane, "end")
        end = endpoint(to_lane, "start")
        if start is None or end is None:
            continue
        sx, sy = transform(start[0], start[1])
        ex, ey = transform(end[0], end[1])
        confidence = float(link.get("confidence") or 0.0)
        opacity = 0.2 + min(0.5, confidence * 0.5)
        link_lines.append(
            f'<line x1="{sx}" y1="{sy}" x2="{ex}" y2="{ey}" '
            f'stroke="#d97706" stroke-width="0.7" stroke-opacity="{opacity:.2f}" />'
        )
        rendered_links += 1
    return link_lines, rendered_links


def build_svg(
    *,
    lane_graph: dict[str, Any],
    movement_corridors: dict[str, Any] | None,
    compound_transactions: dict[str, Any] | None,
    area_id: str,
    width_px: int,
    max_height_px: int,
    max_lane_links: int,
) -> tuple[str, dict[str, Any]]:
    lanes = lane_graph.get("lanes", [])
    links = lane_graph.get("lane_links", [])
    lanes_by_id = lane_by_id(lane_graph)
    all_points = (
        points_from_lanes(lane_graph)
        + points_from_movement_corridors(movement_corridors)
        + points_from_compound_transactions(compound_transactions)
    )
    svg_w, svg_h, transform = scale_transform(
        all_points,
        width_px=width_px,
        max_height_px=max_height_px,
        padding_px=96,
    )

    lane_casing_lines: list[str] = []
    lane_lines: list[str] = []
    for lane in lanes:
        points = lane.get("centerline_xz") or []
        if len(points) < 2:
            continue
        direction = str(lane.get("direction") or "")
        color = "#0f766e" if direction == "forward" else "#6d28d9"
        confidence = float(lane.get("overall_confidence") or 0.0)
        opacity = 0.48 + min(0.40, confidence * 0.42)
        width = 1.05 if confidence < 0.5 else 1.35
        casing_width = 3.25 if confidence < 0.5 else 3.85
        points_attr = polyline(points, transform)
        tooltip = (
            f"lane={lane.get('lane_id', '')}; edge={lane.get('edge_id', '')}; "
            f"direction={direction}; confidence={confidence:.3f}; "
            f"policy={lane.get('traffic_direction_policy', '')}"
        )
        lane_casing_lines.append(
            f'<polyline points="{points_attr}" fill="none" stroke="#d8e6e2" stroke-width="{casing_width}" '
            f'stroke-opacity="0.72" stroke-linecap="round" stroke-linejoin="round" />'
        )
        lane_lines.append(
            f'<polyline points="{points_attr}" fill="none" '
            f'stroke="{color}" stroke-width="{width}" stroke-opacity="{opacity:.2f}" '
            f'stroke-linecap="round" stroke-linejoin="round">{svg_title(tooltip)}</polyline>'
        )

    if movement_corridors:
        link_lines, anchor_marks, movement_metrics = movement_case_lines(
            movement_corridors=movement_corridors,
            transform=transform,
            max_cases=max_lane_links,
        )
        rendered_links = int(movement_metrics["movement_corridors_rendered"])
        link_source = "movement_corridor_anchors"
    else:
        link_lines, rendered_links = lane_link_preview_lines(
            links=links,
            lanes_by_id=lanes_by_id,
            transform=transform,
            max_links=max_lane_links,
        )
        anchor_marks = []
        movement_metrics = {
            "movement_corridors_rendered": 0,
            "anchor_markers_rendered": 0,
            "anchor_source_counts": {},
            "visual_candidate_family_counts": {},
            "visual_candidate_issue_counts": {},
        }
        link_source = "lane_graph_endpoint_preview"

    if compound_transactions:
        compound_lines, compound_anchor_marks, compound_metrics = compound_case_lines(
            compound_transactions=compound_transactions,
            transform=transform,
            max_cases=max_lane_links,
        )
    else:
        compound_lines = []
        compound_anchor_marks = []
        compound_metrics = {
            "compound_corridors_rendered": 0,
            "compound_anchor_markers_rendered": 0,
            "compound_case_status_counts": {},
            "compound_visual_candidate_family_counts": {},
            "compound_visual_candidate_issue_counts": {},
        }

    title = html.escape(f"{area_id} lane graph (车道拓扑图) visualization")
    subtitle = html.escape(
        "SVG is visualization（可视化） only; JSON artifacts remain source truth（源数据真值）. "
        f"Link source: {link_source}."
    )
    svg = "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w}" height="{svg_h}" viewBox="0 0 {svg_w} {svg_h}">',
        '<rect width="100%" height="100%" fill="#f8fafc" />',
        f'<text x="24" y="28" font-family="Arial, sans-serif" font-size="18" fill="#111827">{title}</text>',
        f'<text x="24" y="49" font-family="Arial, sans-serif" font-size="12" fill="#475569">{subtitle}</text>',
        '<g id="lane-road-casing">',
        *lane_casing_lines,
        '</g>',
        '<g id="lanes">',
        *lane_lines,
        '</g>',
        '<g id="lane-links">',
        *link_lines,
        '</g>',
        '<g id="compound-movement-corridors">',
        *compound_lines,
        '</g>',
        '<g id="movement-anchors">',
        *anchor_marks,
        *compound_anchor_marks,
        '</g>',
        '<g id="legend" font-family="Arial, sans-serif" font-size="12" fill="#334155">',
        '<rect x="24" y="64" width="360" height="136" fill="#ffffff" stroke="#cbd5e1" />',
        '<line x1="40" y1="86" x2="84" y2="86" stroke="#0f766e" stroke-width="2" /><text x="94" y="90">forward lane（正向车道）</text>',
        '<line x1="40" y1="106" x2="84" y2="106" stroke="#6d28d9" stroke-width="2" /><text x="94" y="110">backward lane（反向车道）</text>',
        '<line x1="40" y1="126" x2="84" y2="126" stroke="#f97316" stroke-width="2" /><text x="94" y="130">turn corridor preview（转向走廊预览）</text>',
        '<line x1="40" y1="146" x2="84" y2="146" stroke="#0ea5e9" stroke-width="2" /><text x="94" y="150">through corridor preview（直行走廊预览）</text>',
        '<line x1="40" y1="166" x2="84" y2="166" stroke="#ec4899" stroke-width="2" stroke-dasharray="4 2" /><text x="94" y="170">compound trial corridor（复合试运行走廊）</text>',
        '<circle cx="47" cy="185" r="3" fill="#22c55e" stroke="#111827" stroke-width="0.5" /><text x="94" y="189">entry / exit anchors（入口 / 出口锚点）</text>',
        '</g>',
        '</svg>',
    ])
    report = {
        "area_id": area_id,
        "stage": "lane_graph_svg_visualization",
        "status": "pass",
        "counts": {
            "lanes": len(lanes),
            "lane_links_total": len(links),
            "junction_connections_rendered": rendered_links,
            **movement_metrics,
            **compound_metrics,
        },
        "style": {
            "svg_width_px": svg_w,
            "svg_height_px": svg_h,
            "anchor_marker_radius_px": ANCHOR_MARKER_RADIUS_PX,
            "anchor_marker_stroke_width_px": ANCHOR_MARKER_STROKE_WIDTH_PX,
            "lane_casing": "enabled（已启用）",
            "visual_mode": "review_drawing（审图线稿）",
        },
        "link_source": link_source,
        "compound_link_source": "compound_junction_merge_transactions" if compound_transactions else "",
        "note": (
            "SVG visualization（可视化） only. lane_graph.json, movement_corridor_candidates.json and "
            "compound_junction_merge_transactions.json are structured artifacts（结构化产物）. "
            "Corridor curves are preview candidates（候选预览）, not final lane geometry（最终车道几何）."
        ),
    }
    return svg, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Export lane_graph.json to SVG visualization.")
    parser.add_argument("--area-id", default="pattaya_central_500m")
    parser.add_argument("--lane-graph", default="")
    parser.add_argument("--movement-corridors", default="", help="Optional movement_corridor_candidates.json. Defaults to processed/<area_id> file if present.")
    parser.add_argument("--compound-transactions", default="", help="Optional compound_junction_merge_transactions.json overlay.")
    parser.add_argument("--no-movement-corridors", action="store_true", help="Do not auto-load movement corridor overlay.")
    parser.add_argument("--no-compound-transactions", action="store_true", help="Do not auto-load compound junction merge transaction overlay.")
    parser.add_argument("--output", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--width-px", type=int, default=DEFAULT_REVIEW_WIDTH_PX)
    parser.add_argument("--max-height-px", type=int, default=DEFAULT_MAX_HEIGHT_PX)
    parser.add_argument("--max-lane-links", type=int, default=900)
    args = parser.parse_args()

    root = pipeline_root_from_script(Path(__file__))
    processed = root / "data" / "processed"
    reports = root / "reports"
    lane_graph_path = Path(args.lane_graph) if args.lane_graph else processed / f"{args.area_id}_lane_graph.json"
    movement_corridors_path = (
        None
        if args.no_movement_corridors
        else Path(args.movement_corridors)
        if args.movement_corridors
        else processed / f"{args.area_id}_movement_corridor_candidates.json"
    )
    movement_corridors = read_json(movement_corridors_path) if movement_corridors_path and movement_corridors_path.exists() else None
    compound_transactions_path = (
        None
        if args.no_compound_transactions
        else Path(args.compound_transactions)
        if args.compound_transactions
        else processed / f"{args.area_id}_compound_junction_merge_transactions.json"
    )
    compound_transactions = read_json(compound_transactions_path) if compound_transactions_path and compound_transactions_path.exists() else None
    output_path = Path(args.output) if args.output else reports / "visualizations" / f"{args.area_id}_lane_graph_topology.svg"
    report_path = Path(args.report) if args.report else reports / f"{args.area_id}_lane_graph_svg_report.json"

    svg, report = build_svg(
        lane_graph=read_json(lane_graph_path),
        movement_corridors=movement_corridors,
        compound_transactions=compound_transactions,
        area_id=args.area_id,
        width_px=args.width_px,
        max_height_px=args.max_height_px,
        max_lane_links=args.max_lane_links,
    )
    report["inputs"] = {
        "lane_graph": str(lane_graph_path),
        "movement_corridors": str(movement_corridors_path) if movement_corridors_path and movement_corridors is not None else "",
        "compound_junction_merge_transactions": str(compound_transactions_path) if compound_transactions_path and compound_transactions is not None else "",
    }
    report["outputs"] = {"svg": str(output_path), "report": str(report_path)}
    write_text(output_path, svg)
    write_json(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
