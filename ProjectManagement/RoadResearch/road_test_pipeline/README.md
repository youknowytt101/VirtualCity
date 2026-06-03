# Road Test Pipeline

This folder is an isolated road-research pipeline for `ProjectManagement/RoadResearch`.
It does not read from or write to the main VirtualCity `RawData/`, `Scripts/`,
`Config/`, `Reports/`, or `Houdini/` pipeline.

## Current Contract

The current working boundary is:

```text
raw map data
  -> road repair / pre-Houdini engineering
  -> clean road skeleton in Houdini
  -> Houdini construction starts after skeleton acceptance
```

Houdini is now a visualization and construction environment. It must not be the
place where road topology is repaired or where data truth is invented.

## Main Entry Point

Run the current road-repair stage from the repository root:

```powershell
uv --cache-dir E:\VirtualCity\Scripts\.uv-cache run python ProjectManagement/RoadResearch/road_test_pipeline/scripts/repair_road_skeleton.py --area-id pattaya_central_500m --sync-houdini
```

This runner stops before lane graph, lane surface, and OpenDRIVE export.

It performs:

```text
L3 topology repair
L3 topology repair QA
L4 road graph
L4 road graph QA
L5 junction semantics
L6 engineering centerline
L6 junction geometry audit
L6 clean skeleton artifact
L9 optional Houdini raw preview + clean skeleton sync
```

Manual topology overrides are read from `config/<area_id>.manual_overrides.json`
when the file exists. High-confidence review candidates are still report-only
unless they are listed in that override file or the runner is called with
`--apply-high-confidence`.

The Houdini sync replaces `/obj/road_test_<area_id>` with a comparison view:

```text
/obj/road_test_pattaya_central_500m
  python_import_raw_roads
  OUT_raw_road_lines
  python_import_clean_road_skeleton
  OUT_clean_road_skeleton
```

## Current Outputs

Core stage artifacts:

```text
data/processed/<area_id>_roads_raw.geojson
data/processed/<area_id>_roads_repaired.geojson
data/processed/<area_id>_repair_candidates.json
data/processed/<area_id>_repair_decisions.json
data/processed/<area_id>_repair_casebook.json
data/processed/<area_id>_road_graph.json
data/processed/<area_id>_junction_semantics.json
data/processed/<area_id>_roads_optimized_centerlines.geojson
data/processed/<area_id>_roads_clean_skeleton.geojson
```

Core reports:

```text
reports/<area_id>_repair_report.json
reports/qa/<area_id>_topology_repair_qa_report.json
reports/<area_id>_road_graph_report.json
reports/qa/<area_id>_road_graph_qa_report.json
reports/<area_id>_junction_semantics_report.json
reports/<area_id>_optimized_centerlines_report.json
reports/<area_id>_junction_geometry_audit_report.json
reports/<area_id>_road_skeleton_repair_report.json
reports/<area_id>_road_skeleton_repair_summary.json
reports/<area_id>_houdini_raw_road_preview_report.json
reports/<area_id>_houdini_clean_skeleton_report.json
```

## Layer Rules

- Raw data is read-only after ingest.
- Repair, semantics, engineering geometry, lane generation, and visualization are separate layers.
- Every layer writes stable artifacts and reports.
- Houdini imports artifacts; it does not repair topology.
- Clean skeleton output is the handoff into Houdini construction.
- Lane graph, lane surface, lane-level junctions, and XODR export are future downstream stages.

## Important Scripts

Current stage:

```text
scripts/repair_road_skeleton.py
scripts/topology_repair.py
scripts/build_road_graph.py
scripts/build_junction_semantics.py
scripts/optimize_junction_centerlines.py
scripts/junction_geometry_audit.py
scripts/run_auto_qa.py
```

Houdini helpers:

```text
scripts/enable_rpyc_in_houdini.py
scripts/houdini_build_road_test.py
scripts/houdini_cook_rpyc.py
```

Downstream or legacy research stages, not part of the current clean skeleton entry:

```text
scripts/rebuild_road_test.py
scripts/lane_model_builder.py
scripts/generate_lane_geometry_debug.py
scripts/generate_lane_surface_v1.py
scripts/generate_road_preview.py
scripts/audit_road_pipeline.py
```

Keep these scripts for later lane/OpenDRIVE work, but do not use them as the
current road-repair entry point.

## Junction Geometry Status

The current clean skeleton keeps visual connector arcs, but the engineering
audit flags connector arcs whose radius is below the design threshold.

Known current sample status:

```text
junction connector arcs: 107 circular arcs + 42 near-straight infinite-radius connectors
radius_below_design_min: 96
```

Those violations are diagnostics for the next engineering model pass. They
should be solved by junction-area regularization and connecting-road generation,
not by editing Houdini display geometry.

## Next Development Stage

After the clean skeleton is accepted, continue with:

```text
engineering_reference_lines.json
road reference line + laneSection
junction connecting roads
laneLink model
Houdini debug layers
XODR export
```
