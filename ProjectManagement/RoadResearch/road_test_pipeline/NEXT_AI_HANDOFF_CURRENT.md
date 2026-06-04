# NEXT_AI_HANDOFF_CURRENT

This is the authoritative current handoff for the next AI/Codex window.
Use Chinese with the user unless they ask otherwise.

## Core Intent

The project is no longer just a road-skeleton repair experiment. The user's
desired mental model is:

```text
raw map data
  -> LaneForge road/lane automatic upgrade system
  -> standard lane package
  -> Houdini construction pipeline
```

The web viewer is an inspection/action surface only. Do not move road truth,
lane graph truth, or geometry mutation into `svg_live_viewer.html`.

## Workspace

```text
repo: D:\VirtualCity\ProjectManagement\RoadResearch\road_test_pipeline
browser: http://localhost:8765/svg_live_viewer.html
area_id: pattaya_central_500m
```

Primary docs:

```text
AI_START_HERE.md
NEXT_AI_HANDOFF_CURRENT.md
LANEFORGE_LANE_UPGRADE_SYSTEM.md
scripts/README.md
```

Optional review note:

```text
AI点评.md
```

`AI点评.md` is a useful critique/scorecard, not source truth. Trust JSON
reports and package manifests for exact state.

Older files such as `NEXT_AI_HANDOFF.md`, `CURRENT_STAGE_SNAPSHOT.md`, and
some deep sections of historical docs are background only. If they disagree
with this file, trust this file and the latest JSON reports.

## Current Published State

Latest LaneForge package pointer:

```text
data/lane_upgrade_packages/pattaya_central_500m/latest.json
```

Latest package:

```text
data/lane_upgrade_packages/pattaya_central_500m/lane_package_v0009/
```

Latest manifest facts:

```text
qa_status: pass
lanes: 204
junctions: 49
lane_links: 308
continuity_links: 6
junction_envelope_surfaces: 49
active_lane_upgrades: 4
active_corner_optimizations: 3
corner_optimization_candidates: 20
corner_optimization_accepted_active: 3
lane_upgrade_propagation_candidates: 10
lane_upgrade_propagation_high_confidence: 3
```

Important audit metrics:

```text
pipeline_audit: pass
lane_curves_match_trimmed_lane_endpoints: pass
max_lane_link_start_gap_m: 0.000679
max_lane_link_end_gap_m: 0.000679
max_continuity_start_gap_m: 0.0
max_continuity_end_gap_m: 0.0
```

Houdini handoff:

```text
data/lane_upgrade_packages/pattaya_central_500m/lane_package_v0009/houdini_manifest.json
```

Houdini should read package outputs only:

```text
standard_lanes.json
standard_junctions.json
standard_lane_surfaces.geojson
standard_lane_surfaces.obj
```

## Active Lane Upgrades

Source file:

```text
data/processed/pattaya_central_500m_lane_upgrade_overrides.json
```

Current active roads:

```text
e_0005 / cr_0005 -> 3 physical lanes
e_0013 / cr_0013 -> 3 physical lanes
e_0014 / cr_0014 -> 3 physical lanes
e_0015 / cr_0015 -> 3 physical lanes
```

How they got here:

- `e_0015` came from the first web-menu execution smoke test.
- `e_0014` and `e_0013` came from controlled through-pair propagation.
- `e_0005` came from controlled short-edge absorption.

Do not assume extra lanes such as `e_0013_f_2` are test debris. They are active
LaneForge outputs caused by these versioned upgrades.

## Active Corner Optimizations

Source file:

```text
data/processed/pattaya_central_500m_corner_optimization_overrides.json
```

Accepted active corners:

```text
corner_0000: degree2_connector_corner, node n_0032, e_0039 -> e_0040
corner_0001: degree2_connector_corner, node n_0035, e_0040 -> e_0041
corner_0002: degree2_connector_corner, node n_0078, e_0080 -> e_0081
```

All three were applied one at a time through:

```powershell
python scripts\apply_corner_optimization.py --area-id pattaya_central_500m --candidate-id <corner_id> --reason "accepted low-risk degree2 connector corner"
```

Current corner report:

```text
reports/pattaya_central_500m_corner_optimization_report.json
candidates: 20
accepted_active: 3
candidate_review: 17
degree2_connector_corner: 3
internal_centerline_bend: 17
low risk: 9
medium risk: 11
high risk: 0
```

The remaining 17 `internal_centerline_bend` candidates need a separate
controlled policy. The existing degree-2 connector policy must not be reused
for them.

## Propagation State

Source files:

```text
data/lane_upgrade_system/propagation/pattaya_central_500m_latest.json
reports/pattaya_central_500m_lane_upgrade_propagation_report.json
```

Current report:

```text
status: pass
active_upgrades: 4
candidates: 10
high_confidence_candidates: 3
review_candidates: 5
context_review_candidates: 2
```

Rules currently in use:

```text
through_pair_lane_count_continuity_v2
short_edge_absorption_lane_count_v2
same_class_adjacent_approach_review_v2
adjacent_junction_context_review_v2
```

Application policies:

```text
through_pair_only_v1
short_edge_absorption_only_v1
```

Never apply all propagation candidates blindly. Apply one candidate, rebuild,
QA, refresh SVG, then review.

## Browser / Viewer State

Files:

```text
reports/visualizations/svg_live_viewer.html
reports/visualizations/pattaya_central_500m_lane_graph_topology.svg
reports/pattaya_central_500m_lane_graph_svg_report.json
```

Current viewer behavior:

- Toolbar toggles: `Auto`, `Raw`, `Repaired`, `Canonical`, `Corners`.
- Cursor: simplified small black triangle.
- Marker and hit-target sizing is fixed in screen pixels, map-app style.
- Zoom lag introduced by fixed markers was fixed with scale caching,
  `requestAnimationFrame` coalescing, and `vector-effect: non-scaling-stroke`.
- Inspector prioritizes action panels and collapses technical details.
- Overlap picker is quiet by default.

Latest SVG report:

```text
lanes: 204
movement_corridors_rendered: 306
compound_corridors_rendered: 24
corner_candidates_rendered: 20
corner_candidate_status_counts:
  accepted_active: 3
  candidate_review: 17
canonical_roads_rendered: 100
canonical_roads_road_graph_edge_mapped: 100
```

Last viewer QA screenshot:

```text
reports/visualizations/laneforge_interaction_simplified_v0009.png
```

## Main Commands

Rebuild and publish a package after source changes:

```powershell
python scripts\rebuild_road_test.py --area-id pattaya_central_500m --skip-houdini
```

Refresh SVG only:

```powershell
python scripts\export_lane_graph_svg.py --area-id pattaya_central_500m
```

Execute a web-menu lane-count upgrade:

```powershell
python scripts\execute_lane_upgrade.py --area-id pattaya_central_500m --road-id e_0012 --canonical-road-id cr_0012 --target-lane-count 3 --reason "web menu lane upgrade"
```

Plan propagation:

```powershell
python scripts\plan_lane_upgrade_propagation.py --area-id pattaya_central_500m
```

Apply one propagation candidate:

```powershell
python scripts\apply_lane_upgrade_propagation.py --area-id pattaya_central_500m --candidate-id prop_0000 --reason "accepted through-pair propagation"
```

Apply one short-edge propagation candidate:

```powershell
python scripts\apply_lane_upgrade_propagation.py --area-id pattaya_central_500m --candidate-id prop_0000 --policy short_edge_absorption_only_v1 --reason "accepted controlled short-edge absorption"
```

Plan corner candidates:

```powershell
python scripts\plan_corner_optimization.py --area-id pattaya_central_500m
```

Apply one low-risk degree-2 corner:

```powershell
python scripts\apply_corner_optimization.py --area-id pattaya_central_500m --candidate-id corner_0001 --reason "accepted low-risk degree2 connector corner"
```

## Verification Set

For code changes in this pipeline, run the focused test set:

```powershell
pytest D:\VirtualCity\tests\test_corner_optimization.py D:\VirtualCity\tests\test_lane_upgrade_system.py D:\VirtualCity\tests\test_lane_model_builder.py D:\VirtualCity\tests\test_lane_surface_v1.py D:\VirtualCity\tests\test_canonical_roads.py
```

Last known focused result:

```text
25 passed
```

For docs-only changes, at minimum run:

```powershell
git diff --check
```

## Recommended Next Step

Implement a separate controlled path for low-risk `internal_centerline_bend`
smoothing candidates.

Suggested shape:

1. Extend or create an apply path with a new explicit policy:
   `low_risk_internal_centerline_bend_smoothing_v1`.
2. Require explicit `--candidate-id` by default.
3. Support `--dry-run`.
4. Apply one candidate only.
5. Rebuild:

   ```powershell
   python scripts\rebuild_road_test.py --area-id pattaya_central_500m --skip-houdini
   ```

6. Confirm `pipeline_audit: pass`.
7. Refresh SVG and inspect the exact bend in the browser.

Important: internal bends change road interior shape. They are not the same
as degree-2 connector corner fillets. Keep the policy separate and visually
review the first application before widening scope.

## Known Non-Blockers

- Some lower-level QA warnings remain expected data-quality warnings, such as
  topology repair and road graph width fallback warnings.
- `source_oneway` is currently observational only; temporary bidirectional lane
  policy is still active.
- Movement corridor and compound corridor curves are preview/QA candidates, not
  final lane geometry.
- `repair_road_skeleton.py` exists as an older structural/Houdini path. For
  LaneForge package work, prefer `rebuild_road_test.py`.

## Guardrails

- Do not edit generated JSON by hand unless the task is explicitly a manual
  data repair.
- Do not let browser code mutate GeoJSON, lane graph, or active overrides.
- Do not let Houdini discover random internal paths; use package manifests.
- Do not bulk-apply propagation or corner candidates.
- Keep all AI rules/audits versioned and reproducible.
