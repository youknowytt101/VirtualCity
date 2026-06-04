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
repo: E:\VirtualCity\ProjectManagement\RoadResearch\road_test_pipeline
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
data/lane_upgrade_packages/pattaya_central_500m/lane_package_v0028/
```

Latest manifest facts:

```text
qa_status: pass
qa_gate_status: manual_review_required
qa_warning_summary: publishable_warn=0, manual_review_required=3, blocker=0
path_policy: portable_lane_package_paths_v1
lanes: 200
physical_lane_centerlines: 186
physical_lane_group_centerlines: 12
junctions: 49
lane_links: 306
continuity_links: 20
micro_seam_continuity_links: 12
surface_continuity_links: 8
direct_connector_continuity_links: 14
junction_envelope_surfaces: 49
active_lane_upgrades: 4
active_lane_upgrades_applied: 0
active_lane_upgrades_deferred: 4
active_corner_optimizations: 4
corner_optimization_candidates: 19
corner_optimization_accepted_active: 4
corner_optimization_accepted_active_candidates: 3
corner_optimization_accepted_active_overrides: 4
lane_upgrade_propagation_candidates: 10
lane_upgrade_propagation_high_confidence: 3
```

Important audit metrics:

```text
pipeline_audit: pass
qa_gate_status: manual_review_required
qa_warning_summary:
  publishable_warn: 0
  manual_review_required: 3
  blocker: 0
lane_curves_match_trimmed_lane_endpoints: pass
max_lane_link_start_gap_m: 0.000679
max_lane_link_end_gap_m: 0.000680
max_continuity_start_gap_m: 0.0
max_continuity_end_gap_m: 0.0
```

Houdini handoff:

```text
data/lane_upgrade_packages/pattaya_central_500m/lane_package_v0028/houdini_manifest.json
```

Houdini should read package outputs only:

```text
standard_lanes.json
standard_junctions.json
standard_lane_surfaces.geojson
standard_lane_surfaces.obj
```

`standard_lanes.json` now exposes both layers:

```text
lanes: source road-edge lane segments for traceability
physical_lane_centerlines: clean continuous lane centerlines for final consumption
```

Houdini import prefers `physical_lane_centerlines` and falls back to `lanes`
only for old packages.

Lane geometry debug now follows the same contract. Package
`lane_debug_geometry.geojson` and Houdini `OUT_lane_connections_debug` render
186 `physical_lane_centerlines`, while `lanes=200` remains traceability/source
segment data.

`latest.json`, `manifest.json`, and `houdini_manifest.json` now use package-
relative paths. Houdini cook entrypoints resolve the latest package manifest and
do not read `data/processed/*_lane_graph.json` or `data/preview/*_lane_surfaces`
directly.

Lane graph continuity note:

```text
degree2_connector_through_continuity_v1
```

Near-straight degree-2 connector nodes now receive direct through continuity
links. Example fixed case: `e_0082_f_1 -> e_0078_f_1` via
`n_0064_through_cl_01_00`; this is not a corner optimization transaction.

Short connector hard-bend note:

```text
derived_lane_centerline_smoothing_v1 now allows short connector hard bends when
local derivation offset remains within the hard-bend limit.
```

Example fixed case: `e_0079_f_1 / e_0079_b_1`. These were skipped because one
adjacent segment was shorter than the old 8m micro-bend threshold; they now use
`hard_bend_lane_level_rounding` in the derived lane graph only.

Degree-2 micro-seam note:

```text
degree2_connector_micro_seam_endpoint_snap_v1
```

Example fixed case: `n_0069_through_cl_01_00`. The original endpoint gap was
0.063m, which created a visible tiny continuity segment in SVG/surface output.
The current derived lane graph snaps the two lane endpoints to one seam point,
keeps the topology continuity link with `micro_seam_absorbed=true`, and skips
that seam in SVG/debug/surface geometry. This does not mutate
raw/repaired/canonical/road_graph truth layers.

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

Important current geometry policy:

```text
defer_lane_upgrade_overrides_keep_all_roads_bidirectional_two_lane_v1
```

The transaction records above still load and remain auditable, but they do not
alter lane count in the current lane graph. Current geometry output is:

```text
100 roads
200 lanes
0 non-two-lane roads
```

How they got here:

- `e_0015` came from the first web-menu execution smoke test.
- `e_0014` and `e_0013` came from controlled through-pair propagation.
- `e_0005` came from controlled short-edge absorption.

Do not delete the active lane upgrade transactions unless the user explicitly
asks. Also do not re-enable their geometry effect casually; the user currently
wants all roads to remain bidirectional two-lane until semantics are promoted
from temporary assumptions to rule inputs.

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
corner_0003: internal_centerline_bend, e_0017 / cr_0017, point_index=1
```

The first three degree-2 connector corners were applied one at a time through:

```powershell
python scripts\apply_corner_optimization.py --area-id pattaya_central_500m --candidate-id <corner_id> --reason "accepted low-risk degree2 connector corner"
```

`corner_0003` was applied through the new internal bend policy:

```powershell
python scripts\apply_corner_optimization.py --area-id pattaya_central_500m --candidate-id corner_0003 --policy low_risk_internal_centerline_bend_smoothing_v1 --reason "accepted low-risk internal centerline bend smoothing"
```

Current corner report:

```text
reports/pattaya_central_500m_corner_optimization_report.json
candidates: 19
accepted_active: 4
accepted_active_candidates: 3
accepted_active_overrides: 4
candidate_review: 16
degree2_connector_corner: 3
internal_centerline_bend: 16
low risk: 8
medium risk: 11
high risk: 0
candidate_id_reassignments: 16
```

Important: `corner_0003` is an active transaction ID and is intentionally not
reused by the current candidate list. After the smoothing changed the shape,
new review candidates on `e_0017` start at `corner_0004`.

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

The current `lane_package_v0028` copies the latest propagation plan/report into
the package. Historical `D:\VirtualCity` latest pointers are rebased to the
current pipeline root during package publish, and newly written propagation
latest/report paths are root-relative.

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
- Brand text is `LaneForge（道路升级系统）`.
- Key English UI labels have Chinese annotations.
- Cursor: simplified small black triangle.
- Marker and hit-target sizing is fixed in screen pixels, map-app style.
- Zoom lag introduced by fixed markers was fixed with scale caching,
  `requestAnimationFrame` coalescing, and `vector-effect: non-scaling-stroke`.
- Inspector is a right-side vertical rail panel; it prioritizes action panels
  and collapses technical details.
- Overlap picker is quiet by default.

Latest SVG report:

```text
lanes: 200
physical_lane_centerlines: 186
visible_lane_centerlines: 186
movement_corridors_rendered: 306
continuity_links_rendered: 8
continuity_micro_seams_skipped: 12
compound_corridor_overlay: removed
corner_candidates_rendered: 19
corner_candidate_status_counts:
  accepted_active: 3
  candidate_review: 16
canonical_roads_rendered: 100
canonical_roads_road_graph_edge_mapped: 100
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

Apply one low-risk internal bend:

```powershell
python scripts\apply_corner_optimization.py --area-id pattaya_central_500m --candidate-id corner_0004 --policy low_risk_internal_centerline_bend_smoothing_v1 --reason "accepted low-risk internal centerline bend smoothing"
```

## Verification Set

For code changes in this pipeline, run the focused test set:

```powershell
pytest E:\VirtualCity\tests\test_corner_optimization.py E:\VirtualCity\tests\test_lane_upgrade_system.py E:\VirtualCity\tests\test_lane_model_builder.py E:\VirtualCity\tests\test_lane_surface_v1.py E:\VirtualCity\tests\test_lane_geometry_debug.py E:\VirtualCity\tests\test_laneforge_houdini_contract.py E:\VirtualCity\tests\test_canonical_roads.py
```

Last known full result:

```text
155 passed
pytest E:\VirtualCity\tests
```

For docs-only changes, at minimum run:

```powershell
git diff --check
```

## Recommended Next Step

Implement `road_semantics_rule_inputs_v1`.

Goal: move road semantics from temporary assumptions toward auditable rule
inputs before re-enabling richer lane-count geometry. Current package output is
stable, package-boundary-safe, and QA-gated, but traffic organization is still
too dependent on fallback assumptions.

```text
oneway
width
lanes
turn:lanes
```

Suggested shape:

1. Keep the current temporary policy:
   `defer_lane_upgrade_overrides_keep_all_roads_bidirectional_two_lane_v1`.
2. Add a road semantics rule-input layer/report that records source,
   confidence, fallback reason, and production readiness for `oneway`, `width`,
   `lanes`, and `turn:lanes`.
3. Feed those rule-input metrics into `qa_warning_severity_tiers_v1`, especially
   the current `width_fallback_ratio=1.0` manual-review warning.
4. Do not immediately change lane counts or traffic direction geometry. First
   publish the rule inputs in reports/package manifest for review.
5. Keep Houdini manifest-driven and package-only. Houdini should consume the
   resulting standard package, not infer or repair semantics itself.

## Known Non-Blockers

- Some lower-level QA warnings remain expected data-quality warnings, such as
  topology repair and road graph width fallback warnings.
- `source_oneway` is currently observational only; temporary bidirectional lane
  policy is still active.
- Movement corridor curves are preview/QA candidates, not final lane geometry.
- The rejected compound corridor overlay/strategy has been removed from the
  main SVG QA viewer and scoring path.
- `repair_road_skeleton.py` exists as an older structural/Houdini path. For
  LaneForge package work, prefer `rebuild_road_test.py`.

## Guardrails

- Do not edit generated JSON by hand unless the task is explicitly a manual
  data repair.
- Do not let browser code mutate GeoJSON, lane graph, or active overrides.
- Do not let Houdini discover random internal paths; use package manifests.
- Keep package artifacts portable: no drive-letter paths in latest/package JSON.
- Do not bulk-apply propagation or corner candidates.
- Do not use `corner_optimization` to smooth every visual polyline kink.
- Keep all AI rules/audits versioned and reproducible.
