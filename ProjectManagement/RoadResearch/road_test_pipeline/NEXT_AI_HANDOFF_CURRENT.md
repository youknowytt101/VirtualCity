# NEXT_AI_HANDOFF_CURRENT

This handoff is for the next Codex conversation window. Read this file first,
then inspect the changed files and reports listed below before continuing.

## Core User Intent

The user wants the isolated road test pipeline to stay centered on structured
data:

```text
raw roads JSON/GeoJSON
-> topology repair JSON/GeoJSON
-> canonical roads JSON/GeoJSON
-> road graph JSON
-> lane graph / lane geometry JSON
-> Houdini clean JSON / importable artifacts
```

The web page and SVG viewer are only QA / inspection surfaces. Do not move
road repair, canonicalization, lane geometry, or topology truth into browser
code.

## Current Conversation Language

Use Chinese when talking to the user unless they ask otherwise.

The repo contains a mix of Chinese, English, and some older mojibake text in
`svg_live_viewer.html`. Do not assume all Chinese-looking garbled text was
introduced in this pass. Most of it was already present.

## Current Workspace

Root:

```text
D:\VirtualCity
```

Road test pipeline:

```text
D:\VirtualCity\ProjectManagement\RoadResearch\road_test_pipeline
```

Current browser page during the handoff:

```text
http://localhost:8765/svg_live_viewer.html
```

No commit has been made for this work. The working tree contains source edits
and regenerated road-test artifacts.

## What Was Implemented

### 1. Canonical Roads Stage

File:

```text
ProjectManagement\RoadResearch\road_test_pipeline\scripts\build_canonical_roads.py
```

Canonical roads now form the cleaner middle-layer representation between
topology repair and road graph construction.

The canonical stage includes conservative geometry refinement:

- preserves junction and terminal nodes
- removes only near-collinear redundant control points
- lightly smooths only small interior bends
- records refinement tuning and summary in the canonical report
- per-road properties include before/after point counts, removed count,
  smoothed count, and length delta

Do not make simplification aggressive. The intent is to preserve real road
shape and all topology-critical points.

### 2. SVG Exporter and Viewer QA Overlays

Files:

```text
ProjectManagement\RoadResearch\road_test_pipeline\scripts\export_lane_graph_svg.py
ProjectManagement\RoadResearch\road_test_pipeline\reports\visualizations\svg_live_viewer.html
```

The SVG/export flow now supports Raw / Repaired / Canonical road overlays.

Exporter behavior:

- projects arbitrary road GeoJSON layers into the same SVG coordinate space
- preserves provenance/canonical fields as `data-vc-*` attributes
- includes repaired/canonical layers in SVG canvas bounds
- renders repaired/canonical as audit overlays below the lane graph
- extends legend and report stats
- auto-discovers repaired/canonical GeoJSON inputs
- has disable switches for overlay inputs

Viewer behavior:

- toolbar toggles for `Raw`, `Repaired`, `Canonical`
- generalized road overlay visibility function
- hidden overlay hit targets are hidden with the layer
- inspector recognizes `repaired_road` and `canonical_road`
- inspector displays provenance fields:
  - `canonical_road_id`
  - `source_feature_ids`
  - `repaired_source_feature_ids`
  - `repair_edge_ids`
- hit-target priority was fixed so visible QA overlays can be selected even
  though lane graph visuals are drawn above them

Important detail: the viewer still contains older Chinese/mojibake labels.
Avoid broad cleanup unless the user explicitly asks for a language/encoding
cleanup pass.

### 3. Lane Model Geometry Contract Fix

File:

```text
ProjectManagement\RoadResearch\road_test_pipeline\scripts\lane_model_builder.py
```

Root cause of the final audit failure:

- `lane_model_builder.py` already had `edges_with_optimized_approaches(...)`
  but the main build flow was not using it earlier.
- Lanes were generated from `road_graph` centerlines while continuity/corner
  geometry was based on optimized approach/corner geometry.
- This created a geometry-contract mismatch at lane curve endpoints.

Fixes now applied:

- optimized approach centerlines are actually used to build lanes
- `approach_centerlines_trimmed` is now true when optimized approaches are
  applied
- lane link trim metadata now stores longitudinal trim along the lane polyline,
  not straight-line endpoint-to-curve distance
- reversed corner fillet offsets flip lateral sign correctly
- continuity curves snap their first/last point to the actual lane endpoints

Key functions/lines to inspect:

```text
lane_model_builder.py
  nearest_station_on_polyline
  longitudinal_trim_to_point
  lane_link_endpoint_trim_metadata
  add_continuity_links_for_direction
  build_lane_graph
```

### 4. Regression Tests

Files:

```text
D:\VirtualCity\tests\test_canonical_roads.py
D:\VirtualCity\tests\test_lane_model_builder.py
```

Added coverage:

- canonical refine removes redundant near-straight control points
- canonical refine preserves a 90-degree corner
- lane link trim metadata uses longitudinal station, not Euclidean distance
- reversed corner fillet offsets snap to backward lane endpoints
- optimized approach centerlines replace road graph geometry for lane graph
  lane centerlines

## Verification Already Run

Focused tests:

```powershell
pytest tests\test_lane_model_builder.py tests\test_canonical_roads.py
```

Result:

```text
5 passed
```

Syntax check:

```powershell
python -m py_compile ProjectManagement\RoadResearch\road_test_pipeline\scripts\lane_model_builder.py
```

Full road-test rebuild without Houdini:

```powershell
python ProjectManagement\RoadResearch\road_test_pipeline\scripts\rebuild_road_test.py --area-id pattaya_central_500m --skip-houdini
```

Result:

```text
status: completed
houdini_status: skipped
pipeline_audit: pass
```

Final pipeline audit report:

```text
ProjectManagement\RoadResearch\road_test_pipeline\reports\pattaya_central_500m_pipeline_audit_report.json
```

Important audit metrics:

```text
lane_curves_match_trimmed_lane_endpoints: pass
max_lane_link_start_gap_m: 0.000679
max_lane_link_end_gap_m: 0.000679
max_continuity_start_gap_m: 0.0
max_continuity_end_gap_m: 0.0
```

SVG export:

```powershell
python ProjectManagement\RoadResearch\road_test_pipeline\scripts\export_lane_graph_svg.py --area-id pattaya_central_500m
```

Result:

```text
status: pass
raw_roads_rendered: 44
repaired_roads_rendered: 171
canonical_roads_rendered: 100
```

SVG report:

```text
ProjectManagement\RoadResearch\road_test_pipeline\reports\pattaya_central_500m_lane_graph_svg_report.json
```

Browser QA performed in the in-app browser:

- refreshed `http://localhost:8765/svg_live_viewer.html`
- confirmed controls exist:
  - `Raw`
  - `Repaired`
  - `Canonical`
- confirmed visible overlay counts go nonzero when enabled
- confirmed visible overlay counts return to zero when disabled
- confirmed canonical road hit target can be selected
- confirmed inspector showed:
  - `canonical_road_id`
  - `source_feature_ids`
  - `repaired_source_feature_ids`
  - `repair_edge_ids`
- confirmed turning canonical overlay off hides its hit targets and clears
  inspector

## Generated / Modified Artifacts

Regenerated processed data includes:

```text
ProjectManagement\RoadResearch\road_test_pipeline\data\processed\pattaya_central_500m_junction_semantics.json
ProjectManagement\RoadResearch\road_test_pipeline\data\processed\pattaya_central_500m_lane_graph.json
ProjectManagement\RoadResearch\road_test_pipeline\data\processed\pattaya_central_500m_road_graph.json
ProjectManagement\RoadResearch\road_test_pipeline\data\processed\pattaya_central_500m_roads_canonical.geojson
ProjectManagement\RoadResearch\road_test_pipeline\data\processed\pattaya_central_500m_roads_optimized_centerlines.geojson
```

Regenerated reports include:

```text
ProjectManagement\RoadResearch\road_test_pipeline\reports\pattaya_central_500m_canonical_analysis.json
ProjectManagement\RoadResearch\road_test_pipeline\reports\pattaya_central_500m_canonical_roads_report.json
ProjectManagement\RoadResearch\road_test_pipeline\reports\pattaya_central_500m_lane_graph_report.json
ProjectManagement\RoadResearch\road_test_pipeline\reports\pattaya_central_500m_lane_graph_svg_report.json
ProjectManagement\RoadResearch\road_test_pipeline\reports\pattaya_central_500m_pipeline_audit_report.json
ProjectManagement\RoadResearch\road_test_pipeline\reports\pattaya_central_500m_rebuild_report.json
ProjectManagement\RoadResearch\road_test_pipeline\reports\pattaya_central_500m_road_graph_report.json
ProjectManagement\RoadResearch\road_test_pipeline\reports\pattaya_central_500m_road_preview_report.json
ProjectManagement\RoadResearch\road_test_pipeline\reports\pattaya_central_500m_lane_geometry_debug_report.json
ProjectManagement\RoadResearch\road_test_pipeline\reports\pattaya_central_500m_lane_surface_v1_report.json
ProjectManagement\RoadResearch\road_test_pipeline\reports\last_rebuild.log
```

Regenerated visualization:

```text
ProjectManagement\RoadResearch\road_test_pipeline\reports\visualizations\pattaya_central_500m_lane_graph_topology.svg
```

Generated preview directory:

```text
ProjectManagement\RoadResearch\road_test_pipeline\data\preview\
```

## Current Known Warnings / Non-Blockers

The final pipeline contract passes, but lower-level QA still reports expected
warnings:

- topology repair:
  - dangling endpoint ratio is still above the warn threshold
- road graph:
  - dead end ratio warning
  - width fallback ratio warning

These are not the lane endpoint audit failure. Do not treat them as regressions
from the lane geometry fix unless the user specifically asks to address them.

Houdini was skipped in the last rebuild:

```text
--skip-houdini
```

Run Houdini sync only if the user asks or if a task explicitly requires it.

## Suggested Next Steps

1. Start by running:

   ```powershell
   git status --short
   ```

2. Inspect the key diffs:

   ```powershell
   git diff -- ProjectManagement\RoadResearch\road_test_pipeline\scripts\lane_model_builder.py
   git diff -- ProjectManagement\RoadResearch\road_test_pipeline\scripts\build_canonical_roads.py
   git diff -- ProjectManagement\RoadResearch\road_test_pipeline\scripts\export_lane_graph_svg.py
   git diff -- ProjectManagement\RoadResearch\road_test_pipeline\reports\visualizations\svg_live_viewer.html
   git diff -- tests\test_lane_model_builder.py tests\test_canonical_roads.py
   ```

3. If continuing implementation, preserve the architecture:

   ```text
   JSON artifacts are source of truth.
   Browser is QA only.
   Houdini imports/builds from published artifacts.
   ```

4. If asked to clean language/encoding in the viewer, do that as a separate
   scoped pass. Do not mix broad UI text cleanup with geometry/data changes.

5. If asked to commit, include both source changes and intentional regenerated
   road-test artifacts. Be careful with any unrelated dirty files.

## Most Important Fact

The previous blocking final audit failure is fixed. The rebuild after the fix
passed the final road pipeline audit.

## Current Addendum: Junction Envelope Surface Pass

This pass continued the structured road-system optimization after the lane
geometry contract fix.

Implemented:

- `generate_lane_surface_v1.py` now publishes one
  `junction_envelope_surface_v1` polygon for each junction with laneLinks.
- Each envelope is derived from the actual laneLink ribbon boundaries, then
  converted into a conservative convex envelope. It is not browser/SVG truth.
- The lane surface report now records envelope counts, area metrics and
  `junction_envelope_padding_m`.
- `audit_road_pipeline.py` now requires every junction with laneLinks to have a
  non-empty junction envelope surface.
- `houdini_build_road_test.py` imports the new envelope part into a dedicated
  `junction_envelope_surface_v1` primitive group while keeping
  `OUT_roads_centerlines` as the default display output.
- Added `tests/test_lane_surface_v1.py` for offline envelope generation
  coverage.

Verification:

```powershell
pytest tests\test_lane_surface_v1.py tests\test_lane_model_builder.py tests\test_canonical_roads.py
python -m py_compile ProjectManagement\RoadResearch\road_test_pipeline\scripts\generate_lane_surface_v1.py ProjectManagement\RoadResearch\road_test_pipeline\scripts\audit_road_pipeline.py ProjectManagement\RoadResearch\road_test_pipeline\scripts\houdini_build_road_test.py
python ProjectManagement\RoadResearch\road_test_pipeline\scripts\rebuild_road_test.py --area-id pattaya_central_500m --skip-houdini
python ProjectManagement\RoadResearch\road_test_pipeline\scripts\export_lane_graph_svg.py --area-id pattaya_central_500m
```

Latest metrics:

```text
pipeline_audit: pass
lane_surface_v1:
  lane_surfaces: 200
  lane_turn_surfaces: 306
  lane_continuity_surfaces: 6
  junction_envelope_surfaces: 49
  obj_faces: 561
  avg_junction_envelope_area_m2: 310.707
  max_junction_envelope_area_m2: 605.164
```

Suggested next step:

Use the audit as the gate before adding curb, island, marking and swept-envelope
geometry. Keep those as structured artifacts first; visualization and Houdini
remain QA/build surfaces.

## Current Addendum: LaneForge Lane Upgrade System

The user confirmed the middle road/lane processing system should become a
named, evolvable lane upgrade system. This pass names it:

```text
LaneForge 车道升级系统
```

Human mental model:

```text
raw map data -> LaneForge lane upgrade system -> standard lane package -> Houdini construction pipeline
```

Implemented first skeleton:

- Added `LANEFORGE_LANE_UPGRADE_SYSTEM.md`.
- Added `scripts/create_lane_upgrade_transaction.py`.
  - Creates versioned `lane_upgrade_transaction_vXXXX` records.
  - Updates `data/processed/<area_id>_lane_upgrade_overrides.json` when active.
  - Supports the future web menu values: 1 / 2 / 3 / 4 physical lanes.
- Added `scripts/build_lane_upgrade_package.py`.
  - Publishes a standard package at:
    `data/lane_upgrade_packages/<area_id>/lane_package_v0001/`
  - Package includes:
    `manifest.json`, `standard_lanes.json`, `standard_junctions.json`,
    `standard_lane_surfaces.geojson`, `standard_lane_surfaces.obj`,
    `lane_debug_geometry.geojson`, QA reports, and `houdini_manifest.json`.
- `lane_model_builder.py` now consumes active LaneForge overrides.
  - No active override means old behavior stays unchanged.
  - Active road lane count override rebuilds lanes and adjacent junction
    laneLinks from structured semantics.
  - Current v1 distribution:
    - 1 physical lane -> shared bidirectional representation
    - 2 -> 1 forward + 1 backward
    - 3 -> 2 forward + 1 backward
    - 4 -> 2 forward + 2 backward
- `rebuild_road_test.py` now publishes the LaneForge standard package after
  the pipeline audit passes.
- Added regression coverage in `tests/test_lane_model_builder.py`.

Verification:

```powershell
pytest tests\test_lane_model_builder.py tests\test_lane_surface_v1.py tests\test_canonical_roads.py
python -m py_compile ProjectManagement\RoadResearch\road_test_pipeline\scripts\lane_model_builder.py ProjectManagement\RoadResearch\road_test_pipeline\scripts\create_lane_upgrade_transaction.py ProjectManagement\RoadResearch\road_test_pipeline\scripts\build_lane_upgrade_package.py ProjectManagement\RoadResearch\road_test_pipeline\scripts\rebuild_road_test.py
python ProjectManagement\RoadResearch\road_test_pipeline\scripts\rebuild_road_test.py --area-id pattaya_central_500m --skip-houdini
```

Latest rebuild:

```text
pipeline_audit: pass
LaneForge package: lane_package_v0001
package lanes: 200
package junctions: 49
package lane_links: 306
active_lane_upgrades: 0
```

Important next step:

Wire the SVG/web viewer road click action to call or emit a LaneForge
transaction request. The static viewer should still not mutate road truth
directly; it should only create/submit a transaction, then the pipeline rebuild
and audit decide whether to publish the next standard lane package.

## Current Addendum: LaneForge Viewer Mapping and Transaction Scope

This pass continued the web-click lane upgrade entry without moving road truth
into the browser.

Implemented:

- `export_lane_graph_svg.py` now loads `road_graph.json` by default and exports
  `data-vc-road-graph-edge-id` on canonical road overlay elements.
- `svg_live_viewer.html` now prefers that structured edge id when building a
  LaneForge transaction request. The old `cr_0002 -> e_0002` derivation remains
  only as a fallback.
- The viewer-generated CLI command now includes both `--road-id` and
  `--canonical-road-id` when the selected object has both.
- `create_lane_upgrade_transaction.py` now accepts `--canonical-road-id`,
  validates road/canonical references against `data/processed/<area>_road_graph.json`,
  rejects mismatches, and records a v1 direct endpoint junction scope:
  affected road, endpoint nodes, and endpoint nodes classified as junction.
- Added `tests/test_lane_upgrade_system.py` for the SVG mapping and transaction
  validation contract.
- Updated `LANEFORGE_LANE_UPGRADE_SYSTEM.md` with the viewer transaction
  contract.

Verification:

```powershell
python -m py_compile ProjectManagement\RoadResearch\road_test_pipeline\scripts\export_lane_graph_svg.py ProjectManagement\RoadResearch\road_test_pipeline\scripts\create_lane_upgrade_transaction.py
pytest tests\test_lane_upgrade_system.py tests\test_lane_model_builder.py tests\test_lane_surface_v1.py tests\test_canonical_roads.py
python ProjectManagement\RoadResearch\road_test_pipeline\scripts\export_lane_graph_svg.py --area-id pattaya_central_500m
```

Results:

```text
11 passed
SVG export status: pass
canonical_roads_rendered: 100
canonical_roads_road_graph_edge_mapped: 100
```

Browser QA:

- Reloaded `http://localhost:8765/svg_live_viewer.html`.
- Confirmed all 100 canonical hit targets carry `roadGraphEdgeId`.
- Clicked a canonical road, confirmed the inspector shows the LaneForge
  1/2/3/4 lane menu.
- Clicked `3车道`; generated transaction request JSON includes
  `target_physical_lane_count: 3`, a resolved `road_id`, the matching
  `canonical_road_id`, and a CLI command with both ids.
- No browser console errors were reported.

Screenshot saved at:

```text
ProjectManagement\RoadResearch\road_test_pipeline\reports\visualizations\laneforge_viewer_check.png
```

## Current Addendum: LaneForge Upgrade Execution v1

This pass turned the viewer request into a real audited backend execution loop.

Implemented:

- Simplified the in-viewer cursor to a single custom triangle cursor. The map,
  hit targets and drag state now use one cursor instead of multiple cursor
  modes.
- Added `scripts/execute_lane_upgrade.py`.
  - Creates an active LaneForge transaction.
  - Runs `rebuild_road_test.py` with Houdini skipped by default.
  - Publishes the next versioned package, for example `lane_package_v0002`.
  - Refreshes `pattaya_central_500m_lane_graph_topology.svg`.
  - Writes an execution report under
    `data/lane_upgrade_system/executions/`.
- Updated `svg_live_viewer.html`.
  - LaneForge JSON now includes `execute_cli_command`.
  - `next_cli_command` now points to `execute_lane_upgrade.py`.
  - Inspector has both `复制事务 JSON` and `复制执行命令`.
- Updated `export_lane_graph_svg.py` so lane elements export
  `data-vc-road-id` and `data-vc-edge-id` from the lane `road_id`.
  This lets direct lane clicks enter the same LaneForge upgrade path as
  canonical road clicks.
- Extended `tests/test_lane_upgrade_system.py`.

Verification:

```powershell
python -m py_compile ProjectManagement\RoadResearch\road_test_pipeline\scripts\execute_lane_upgrade.py ProjectManagement\RoadResearch\road_test_pipeline\scripts\export_lane_graph_svg.py
pytest tests\test_lane_upgrade_system.py tests\test_lane_model_builder.py tests\test_lane_surface_v1.py tests\test_canonical_roads.py
python ProjectManagement\RoadResearch\road_test_pipeline\scripts\execute_lane_upgrade.py --area-id pattaya_central_500m --road-id e_0015 --canonical-road-id cr_0015 --target-lane-count 3 --reason "LaneForge execution v1 smoke test"
python ProjectManagement\RoadResearch\road_test_pipeline\scripts\export_lane_graph_svg.py --area-id pattaya_central_500m
```

Results:

```text
13 passed
execution: completed
transaction: lane_upgrade_transaction_v0001
active override: e_0015 / cr_0015 -> 3 physical lanes
pipeline_audit: pass
latest package: lane_package_v0002
lane graph lanes: 201
e_0015 lanes: e_0015_f_1, e_0015_f_2, e_0015_b_1
canonical_roads_road_graph_edge_mapped: 100
```

Browser QA:

- Reloaded `http://localhost:8765/svg_live_viewer.html`.
- Confirmed the single triangle cursor is active.
- Confirmed direct lane hit targets now carry road ids.
- Clicked a visible lane and confirmed the LaneForge 1/2/3/4 menu opens.
- Clicked `3车道`; generated JSON includes
  `execute_cli_command: python scripts\execute_lane_upgrade.py ...`.
- No browser console errors were reported.

Suggested next step:

Start LaneForge junction propagation rules v2. The current v1 scope is direct
endpoint junctions only. The next rule layer should decide when a lane-count
upgrade should propagate across short edges, compound junctions, paired one-way
roads, or nearby corridor cases.

## Current Addendum: Junction Propagation Rules v2

This pass started LaneForge propagation v2 as a proposal-only rule layer.

Implemented:

- Updated `svg_live_viewer.html` cursor to match the user's requested plain
  black arrow cursor. The viewer now uses one small black triangular cursor for
  map, hit targets and drag state.
- Added `scripts/plan_lane_upgrade_propagation.py`.
  - Reads active lane upgrades, road graph and junction semantics.
  - Writes versioned propagation plans under:
    `data/lane_upgrade_system/propagation/`
  - Writes report:
    `reports/<area_id>_lane_upgrade_propagation_report.json`
  - Does not modify active overrides.
- Connected propagation planning into `execute_lane_upgrade.py` after rebuild
  and before package publish.
- Updated `build_lane_upgrade_package.py` so packages copy the latest
  propagation plan/report when present.
- Extended `tests/test_lane_upgrade_system.py` to cover propagation planning
  and package copying.
- Updated `LANEFORGE_LANE_UPGRADE_SYSTEM.md`.

Current propagation v2 rules:

```text
through_pair_lane_count_continuity_v2
short_edge_absorption_lane_count_v2
same_role_same_class_junction_balance_v2
same_class_adjacent_approach_review_v2
adjacent_junction_context_review_v2
```

Verification:

```powershell
python -m py_compile ProjectManagement\RoadResearch\road_test_pipeline\scripts\plan_lane_upgrade_propagation.py ProjectManagement\RoadResearch\road_test_pipeline\scripts\execute_lane_upgrade.py ProjectManagement\RoadResearch\road_test_pipeline\scripts\build_lane_upgrade_package.py
pytest tests\test_lane_upgrade_system.py tests\test_lane_model_builder.py tests\test_lane_surface_v1.py tests\test_canonical_roads.py
python ProjectManagement\RoadResearch\road_test_pipeline\scripts\plan_lane_upgrade_propagation.py --area-id pattaya_central_500m
python ProjectManagement\RoadResearch\road_test_pipeline\scripts\build_lane_upgrade_package.py --area-id pattaya_central_500m --version lane_package_v0003
```

Results:

```text
15 passed
propagation report: pass
active_upgrades: 1
propagation candidates: 3
high_confidence_candidates: 1
latest package with propagation plan: lane_package_v0003
browser console errors: 0
```

## Current Addendum: Corner Optimization Candidate Stage v1

The user confirmed road corner optimization should start now and clarified that
it belongs inside the main road automatic upgrade system, not Houdini and not
browser truth.

Implemented proposal-only corner stage:

- Added `scripts/plan_corner_optimization.py`.
- Connected it into `scripts/rebuild_road_test.py` immediately after
  `optimize_junction_centerlines.py` and before `lane_model_builder.py`.
- It reads:
  - `data/processed/<area_id>_road_graph.json`
  - `data/processed/<area_id>_roads_optimized_centerlines.geojson`
- It writes:
  - `data/processed/<area_id>_corner_optimization_candidates.json`
  - `reports/<area_id>_corner_optimization_report.json`
- It detects:
  - `degree2_connector_corner`
  - `internal_centerline_bend`
- It records each candidate as structured JSON with:
  - candidate id/type/status/risk
  - involved road graph node/edges
  - turn angle and interior angle
  - suggested cut distance
  - suggested radius
  - nearest junction distance
  - context polyline and center point
- It does not mutate optimized centerline geometry.

SVG / viewer integration:

- `export_lane_graph_svg.py` now auto-loads
  `<area_id>_corner_optimization_candidates.json`.
- Added a visible `corner_optimization` overlay layer to the SVG.
- Added corner candidate SVG report metrics.
- `svg_live_viewer.html` now has a `Corners` toggle.
- `corner_candidate` is recognized by inspector labels, hit targets and
  fixed-screen marker sizing.
- Clicking a candidate in the viewer shows fields such as:
  `candidate_type`, `risk_level`, `turn_angle_deg`, `suggested_cut_m`,
  `suggested_radius_m`, `from_edge_id`, `to_edge_id`.

Tests:

```powershell
pytest tests\test_corner_optimization.py tests\test_lane_upgrade_system.py tests\test_lane_model_builder.py tests\test_lane_surface_v1.py tests\test_canonical_roads.py
```

Result:

```text
20 passed
```

Full rebuild:

```powershell
python scripts\rebuild_road_test.py --area-id pattaya_central_500m --skip-houdini
```

Result:

```text
pipeline_audit: pass
corner candidates: 20
  degree2_connector_corner: 3
  internal_centerline_bend: 17
  low risk: 9
  medium risk: 11
  high risk: 0
lane graph lanes: 204
lane graph laneLinks: 308
```

SVG export:

```powershell
python scripts\export_lane_graph_svg.py --area-id pattaya_central_500m
```

Result:

```text
corner_candidates_rendered: 20
corner_candidate_type_counts:
  degree2_connector_corner: 3
  internal_centerline_bend: 17
corner_candidate_risk_counts:
  low: 9
  medium: 11
```

Browser QA:

- Reloaded `http://localhost:8765/svg_live_viewer.html`.
- Confirmed `Corners` toggle exists and is checked.
- Confirmed corner overlay / hit targets exist.
- Clicked `corner_0001`.
- Inspector opened and showed:
  - `candidate_type: degree2_connector_corner`
  - `risk_level: low`
  - `recommended_action: candidate_for_auto_fillet_after_review`
  - `from_edge_id: e_0040`
  - `to_edge_id: e_0041`
  - `turn_angle_deg: 89.253`
  - `suggested_cut_m: 2.43`
  - `suggested_radius_m: 4.08`
- Browser console errors: 0.

Suggested next step:

Visually review low-risk corner candidates first. The next implementation pass
should create an accept/apply path for low-risk `degree2_connector_corner`
candidates only, as versioned geometry transactions. Do not directly rewrite
all internal bends yet.

Candidate summary for the active `e_0015 / cr_0015 -> 3 lanes` upgrade:

```text
prop_0000: e_0014 / cr_0014
  rule: through_pair_lane_count_continuity_v2
  status: candidate_high_confidence
  confidence: 0.84

prop_0001: e_0019 / cr_0019
  rule: same_class_adjacent_approach_review_v2
  status: candidate_review
  confidence: 0.54

prop_0002: e_0020 / cr_0020
  rule: same_class_adjacent_approach_review_v2
  status: candidate_review
  confidence: 0.54
```

Suggested next step:

Add a controlled accept/apply path for selected propagation candidates. Start
with high-confidence `through_pair_lane_count_continuity_v2` candidates only,
generate transactions for them, rebuild, QA, and compare before/after reports.

## Current Addendum: Propagation Application v1

This pass added and executed the controlled accept path for propagation
candidates.

Implemented:

- Added `scripts/apply_lane_upgrade_propagation.py`.
  - Default policy accepts only:
    `candidate_high_confidence`,
    `through_pair_lane_count_continuity_v2`,
    confidence >= `0.8`.
  - Creates normal LaneForge transactions for accepted candidates.
  - Rebuilds the pipeline, replans propagation, publishes the next package and
    refreshes SVG.
  - Writes application reports under:
    `data/lane_upgrade_system/propagation_applications/`.
- Extended `tests/test_lane_upgrade_system.py`.
- Updated `LANEFORGE_LANE_UPGRADE_SYSTEM.md`.

Verification:

```powershell
python -m py_compile ProjectManagement\RoadResearch\road_test_pipeline\scripts\apply_lane_upgrade_propagation.py ProjectManagement\RoadResearch\road_test_pipeline\scripts\plan_lane_upgrade_propagation.py ProjectManagement\RoadResearch\road_test_pipeline\scripts\execute_lane_upgrade.py
pytest tests\test_lane_upgrade_system.py tests\test_lane_model_builder.py tests\test_lane_surface_v1.py tests\test_canonical_roads.py
python ProjectManagement\RoadResearch\road_test_pipeline\scripts\apply_lane_upgrade_propagation.py --area-id pattaya_central_500m --candidate-id prop_0000 --reason "accepted high-confidence through-pair propagation"
```

Results:

```text
17 passed
accepted candidate: prop_0000
accepted road: e_0014 / cr_0014
transaction: lane_upgrade_transaction_v0002
active upgrades: 2
lane graph lanes: 202
lane graph laneLinks: 307
pipeline_audit: pass
latest package: lane_package_v0004
```

Before/after for accepted candidate:

```text
before e_0014: e_0014_f_1, e_0014_b_1
after  e_0014: e_0014_f_1, e_0014_f_2, e_0014_b_1
```

Current active upgraded road pair:

```text
e_0014 / cr_0014 -> 3 lanes
e_0015 / cr_0015 -> 3 lanes
```

Browser QA:

- Reloaded `http://localhost:8765/svg_live_viewer.html`.
- Confirmed SVG loads.
- Confirmed `e_0014` and `e_0015` lane hit targets exist.
- Confirmed plain black arrow cursor remains active.
- No browser console errors were reported.

Current next propagation report after applying `prop_0000`:

```text
active_upgrades: 2
candidates: 6
high_confidence_candidates: 1
review_candidates: 4
context_review_candidates: 1
```

Suggested next step:

Review the new high-confidence propagation candidate before applying it. If it
is another through-pair continuation, apply it through the same controlled
application script and watch whether the upgraded corridor chain remains stable
under QA.

## Current Addendum: Selection Highlight and Propagation Application v2

This pass continued after the user asked to shrink the selected-line endpoint
markers and proceed with the next LaneForge step.

Implemented:

- `svg_live_viewer.html` selection endpoint pins were reduced:
  - radius `4.2 -> 2.8`
  - stroke width `3 -> 2`
- Reviewed the latest propagation plan `v0002`.
- Applied the next safe candidate through the existing controlled policy:
  - accepted `prop_0000`
  - candidate road `e_0013 / cr_0013`
  - source road `e_0014 / cr_0014`
  - rule `through_pair_lane_count_continuity_v2`
  - confidence `0.84`
  - transaction `lane_upgrade_transaction_v0003`
- The pipeline rebuilt, replanned propagation, refreshed SVG, and published:
  `lane_package_v0005`.

Verification:

```powershell
python -m py_compile scripts\apply_lane_upgrade_propagation.py scripts\plan_lane_upgrade_propagation.py scripts\execute_lane_upgrade.py scripts\build_lane_upgrade_package.py
pytest D:\VirtualCity\tests\test_lane_upgrade_system.py D:\VirtualCity\tests\test_lane_model_builder.py D:\VirtualCity\tests\test_lane_surface_v1.py D:\VirtualCity\tests\test_canonical_roads.py
python scripts\apply_lane_upgrade_propagation.py --area-id pattaya_central_500m --candidate-id prop_0000 --reason "accepted next high-confidence through-pair propagation"
```

Results:

```text
17 passed
pipeline_audit: pass
latest package: lane_package_v0005
active upgrades: 3
lane graph lanes: 203
lane graph laneLinks: 308
```

Current active upgraded corridor:

```text
e_0013 / cr_0013 -> 3 lanes
e_0014 / cr_0014 -> 3 lanes
e_0015 / cr_0015 -> 3 lanes
```

Before/after for the accepted candidate:

```text
before e_0013: e_0013_f_1, e_0013_b_1
after  e_0013: e_0013_f_1, e_0013_f_2, e_0013_b_1
```

Browser QA:

- Reloaded `http://localhost:8765/svg_live_viewer.html`.
- Confirmed SVG loads after the refreshed export.
- Confirmed hit targets increased to `2044`.
- Confirmed selected endpoint pins now render as `r=2.8` and
  `stroke-width=2px`.
- Confirmed inspector and LaneForge menu still open after selecting a road.
- No browser console errors were reported.

Important next propagation state:

The next high-confidence candidate is no longer a through-pair continuation:

```text
prop_0000:
  source: e_0013
  candidate: e_0005 / cr_0005
  rule: short_edge_absorption_lane_count_v2
  status: candidate_high_confidence
  confidence: 0.76
  candidate_length_m: 8.688
```

Do not auto-apply this under the current `high_confidence_through_pair_only_v1`
policy. It should be reviewed visually or handled by a new, explicitly scoped
short-edge absorption accept policy before becoming an active upgrade.

## Current Addendum: Controlled Short-Edge Absorption Application v1

The user said to start the next step after the propagation review. This pass
implemented the explicitly scoped short-edge absorption accept path and applied
the current short connector candidate.

Implemented:

- `scripts/apply_lane_upgrade_propagation.py` now supports a named
  `--policy short_edge_absorption_only_v1`.
- The default policy remains `through_pair_only_v1`; short-edge absorption is
  not part of the default accept path.
- The short-edge policy only accepts:
  - `candidate_high_confidence`
  - `short_edge_absorption_lane_count_v2`
  - confidence >= `0.74`
  - `candidate_length_m <= 12.0`
  - `candidate_road_class == source_road_class`
- Added regression coverage in `tests/test_lane_upgrade_system.py`.
- Updated `LANEFORGE_LANE_UPGRADE_SYSTEM.md` with the short-edge policy
  contract and command.

Verification before applying:

```powershell
python -m py_compile scripts\apply_lane_upgrade_propagation.py scripts\plan_lane_upgrade_propagation.py scripts\execute_lane_upgrade.py
pytest D:\VirtualCity\tests\test_lane_upgrade_system.py D:\VirtualCity\tests\test_lane_model_builder.py D:\VirtualCity\tests\test_lane_surface_v1.py D:\VirtualCity\tests\test_canonical_roads.py
python scripts\apply_lane_upgrade_propagation.py --area-id pattaya_central_500m --candidate-id prop_0000 --policy short_edge_absorption_only_v1 --reason "dry run controlled short-edge absorption" --dry-run
```

Results:

```text
18 passed
dry_run selected only prop_0000:
  e_0005 / cr_0005
  length 8.688m
  residential -> residential
```

Applied:

```powershell
python scripts\apply_lane_upgrade_propagation.py --area-id pattaya_central_500m --candidate-id prop_0000 --policy short_edge_absorption_only_v1 --reason "accepted controlled short-edge absorption"
```

Results:

```text
application: pattaya_central_500m_lane_upgrade_propagation_application_v0004.json
transaction: lane_upgrade_transaction_v0004
accepted road: e_0005 / cr_0005
active upgrades: 4
pipeline_audit: pass
latest package: lane_package_v0006
lane graph lanes: 204
lane graph laneLinks: 308
junction envelope surfaces: 49
```

Before/after for accepted candidate:

```text
before e_0005: e_0005_f_1, e_0005_b_1
after  e_0005: e_0005_f_1, e_0005_f_2, e_0005_b_1
```

Current active upgraded roads:

```text
e_0005 / cr_0005 -> 3 lanes
e_0013 / cr_0013 -> 3 lanes
e_0014 / cr_0014 -> 3 lanes
e_0015 / cr_0015 -> 3 lanes
```

Current next propagation plan:

```text
latest plan: v0004
candidates: 10
high_confidence_candidates: 3
review_candidates: 5
context_review_candidates: 2
```

High-confidence candidates after applying the short edge:

```text
prop_0000: e_0004 / cr_0004
  source: e_0005
  rule: through_pair_lane_count_continuity_v2
  confidence: 0.84
  length: 148.519m

prop_0001: e_0085 / cr_0085
  source: e_0005
  rule: short_edge_absorption_lane_count_v2
  confidence: 0.76
  length: 8.683m

prop_0002: e_0006 / cr_0006
  source: e_0005
  rule: through_pair_lane_count_continuity_v2
  confidence: 0.84
  length: 39.579m
```

Browser QA:

- Reloaded `http://localhost:8765/svg_live_viewer.html`.
- SVG present and loaded after refreshed export.
- `e_0005` has hit targets in the DOM.
- Clicked a visible road target; inspector opened with the LaneForge 1/2/3/4
  menu.
- Selection overlay rendered with 4 children.
- Map/SVG/hit targets still use the black triangle cursor.
- Browser console errors: 0.

Suggested next step:

Review the three new high-confidence candidates visually. Do not blindly apply
all three at once. A safe next slice is to apply one through-pair candidate
with the default policy, or review the new short-edge `e_0085` under the
short-edge policy before applying it.

## Current Addendum: Fixed-Screen Marker and Hit Target Interaction Pass

The user reported that specific line/marker clicks in the web viewer were still
not accurate, and asked for map-app-style icons that do not scale with zoom.

Implemented in:

```text
reports\visualizations\svg_live_viewer.html
```

Changes:

- Added screen-pixel sizing helpers that derive the current SVG-unit-to-screen
  ratio from the viewer `viewBox`.
- Non-hit SVG marker circles now keep fixed screen radii while zooming:
  - movement / compound anchors: about `4.2px`
  - topology issues: about `5px`
  - raw endpoints: about `3.2px`
  - raw vertices: about `2.8px`
- Transparent circle hit targets now keep fixed screen hit radii:
  - movement / compound anchors: about `13px`
  - topology issues: about `15px`
  - raw road points: about `11px`
- Transparent line hit targets now keep fixed screen stroke widths:
  - canonical roads: about `16px`
  - repaired/raw roads: about `14px`
  - movement corridors: about `15px`
  - lanes: about `12px`
- Selection endpoint pins are also rescaled after zoom so they stay a small
  screen-sized marker.
- Fixed sizing is reapplied on every `updateViewBox()` and immediately after
  drawing a selection overlay.

Browser QA:

- Reloaded `http://localhost:8765/svg_live_viewer.html`.
- Initial fit view:
  - movement anchor visual radius measured about `4.2px`
  - movement anchor hit radius measured about `13px`
  - lane hit width measured about `12px`
- After zooming in several times:
  - movement anchor visual radius stayed about `4.19px`
  - movement anchor hit radius stayed about `12.99px`
  - lane hit width stayed about `12px`
- Clicked a current viewport target; inspector opened normally.
- In a line/marker overlap, the marker won selection priority, which matches
  map-app-style behavior.
- Browser console errors: 0.

Suggested next step:

Continue with visual review of propagation candidates after the viewer
interaction feels stable enough. If clicks are still ambiguous in dense
junctions, add an explicit hover/click candidate picker layer rather than
changing road truth or SVG export geometry.

## Current Addendum: Zoom Performance Fix After Fixed Marker Pass

The user reported zoom became laggy after the fixed-screen marker change.

Root cause:

- `updateViewBox()` was calling fixed-screen sizing on every zoom and pan.
- The sizing pass queried and rewrote many SVG attributes every time:
  - about 993 marker circles
  - about 2046 hit targets
- Transparent line hit targets were also being resized manually even though SVG
  can keep stroke width fixed with `vector-effect: non-scaling-stroke`.

Fix in:

```text
reports\visualizations\svg_live_viewer.html
```

Changes:

- Added `state.fixedSizingScale` so pan-only viewBox updates do not recompute
  marker sizes when zoom scale did not change.
- Added `requestAnimationFrame` coalescing for fixed-size marker updates.
- Changed transparent line hit targets to use:

```text
vector-effect="non-scaling-stroke"
```

- Selection overlay still forces one immediate sizing pass when drawn.
- SVG reload resets the fixed-size cache.

Browser QA after fix:

```text
initial movement anchor visual radius: ~4.20px
initial movement anchor hit radius: ~13.00px
initial lane hit target stroke width: 12, vector-effect non-scaling-stroke
after 8 zoom-in clicks visual radius: ~4.20px
after 8 zoom-in clicks hit radius: ~13.00px
browser console errors: 0
```

## Current Addendum: Controlled Corner Optimization Application v1

The user confirmed continuing the main LaneForge road/corner optimization flow.
This pass added a controlled accept/apply path for low-risk road corner
optimization candidates.

Implemented:

- Added `scripts/apply_corner_optimization.py`.
  - Default policy: `low_risk_degree2_connector_only_v1`.
  - Requires explicit `--candidate-id` unless `--all-matching-policy` is
    intentionally passed.
  - Writes active geometry overrides to:
    `data/processed/<area_id>_corner_optimization_overrides.json`.
  - Writes versioned application reports under:
    `data/lane_upgrade_system/corner_applications/`.
  - Rebuilds, audits, publishes the next LaneForge package and refreshes SVG.
- `optimize_junction_centerlines.py` now consumes active corner overrides and
  annotates matching `optimized_corner_fillet` features with transaction
  metadata.
- `plan_corner_optimization.py` now marks matching candidates as
  `accepted_active` and records `accepted_active` counts.
- `build_lane_upgrade_package.py` now copies active corner optimizations,
  corner candidates and corner report into the standard package manifest.
- `export_lane_graph_svg.py` now reports corner status counts and colors
  accepted active corner candidates blue.
- `svg_live_viewer.html` now shows a LaneForge corner optimization panel when
  clicking a corner candidate, including copyable JSON and apply command.
- Added regression coverage in `tests/test_corner_optimization.py`.

Verification:

```powershell
python -m py_compile scripts\apply_corner_optimization.py scripts\optimize_junction_centerlines.py scripts\plan_corner_optimization.py scripts\export_lane_graph_svg.py scripts\build_lane_upgrade_package.py
pytest D:\VirtualCity\tests\test_corner_optimization.py D:\VirtualCity\tests\test_lane_upgrade_system.py D:\VirtualCity\tests\test_lane_model_builder.py D:\VirtualCity\tests\test_lane_surface_v1.py D:\VirtualCity\tests\test_canonical_roads.py
python scripts\apply_corner_optimization.py --area-id pattaya_central_500m --candidate-id corner_0001 --reason "accepted low-risk degree2 connector corner"
```

Results:

```text
23 passed
pipeline_audit: pass
accepted corner: corner_0001
node: n_0035
edges: e_0040 -> e_0041
active_corner_optimizations: 1
corner candidates: 20
accepted_active: 1
lane graph lanes: 204
lane graph laneLinks: 308
continuity_links: 6
optimized_corner_fillets: 3
latest package: lane_package_v0007
```

Browser QA:

- Reloaded `http://localhost:8765/svg_live_viewer.html`.
- Confirmed `Corners` is checked.
- Confirmed `corner_0001` is `accepted_active` and renders with blue fill.
- Clicked the accepted marker; inspector opened with the LaneForge corner
  optimization panel.
- Confirmed the copyable JSON contains an `apply_cli_command`.
- Browser console errors: 0.

Suggested next step:

Visually review the remaining two low-risk `degree2_connector_corner`
candidates (`corner_0000`, `corner_0002`). If they look correct, apply them
one at a time through `apply_corner_optimization.py`, then continue to a
separate proposal/apply path for low-risk `internal_centerline_bend` smoothing.

## Current Addendum: Remaining Degree-2 Corner Applications and UI Simplification

The user approved continuing, and also noted that the web interaction felt a
bit complex.

Implemented in `reports\visualizations\svg_live_viewer.html`:

- Inspector now prioritizes action panels first:
  - LaneForge lane actions
  - LaneForge corner optimization actions
  - overlap picker when needed
  - scoring only when a real scoring case exists
  - source attributes collapsed behind `技术详情 / 源属性`
- Overlapping click candidates are now collapsed by default behind a quiet
  `重叠选择` entry instead of rendering a long list immediately.
- Corner optimization request JSON is hidden by default behind `请求详情`;
  the common action remains `复制应用命令`.
- Empty "no scoring match" rows are no longer shown for normal lane/road/corner
  selections.

Applied the remaining low-risk `degree2_connector_corner` candidates one at a
time through the controlled policy:

```powershell
python scripts\apply_corner_optimization.py --area-id pattaya_central_500m --candidate-id corner_0000 --reason "accepted low-risk degree2 connector corner"
python scripts\apply_corner_optimization.py --area-id pattaya_central_500m --candidate-id corner_0002 --reason "accepted low-risk degree2 connector corner"
```

Results:

```text
corner_0000 -> application v0003 -> package lane_package_v0008
corner_0002 -> application v0004 -> package lane_package_v0009
pipeline_audit: pass
latest package: lane_package_v0009
active_corner_optimizations: 3
corner candidates: 20
accepted_active: 3
candidate_review: 17
lane graph lanes: 204
lane graph laneLinks: 308
continuity_links: 6
```

Verification:

```powershell
python -m py_compile scripts\apply_corner_optimization.py scripts\plan_corner_optimization.py scripts\optimize_junction_centerlines.py scripts\export_lane_graph_svg.py scripts\build_lane_upgrade_package.py
pytest D:\VirtualCity\tests\test_corner_optimization.py D:\VirtualCity\tests\test_lane_upgrade_system.py D:\VirtualCity\tests\test_lane_model_builder.py D:\VirtualCity\tests\test_lane_surface_v1.py D:\VirtualCity\tests\test_canonical_roads.py
```

Result:

```text
25 passed
```

Browser QA:

- Reloaded `http://localhost:8765/svg_live_viewer.html`.
- Confirmed the SVG loads and the toolbar still exposes:
  `Auto`, `Raw`, `Repaired`, `Canonical`, `Corners`.
- Confirmed real report state:
  `corner_candidate_status_counts = { accepted_active: 3, candidate_review: 17 }`.
- Clicked an accepted corner candidate after fitting the view.
- Inspector opened as `Corner candidate（转角候选）`.
- Confirmed the simplified panel:
  - `LaneForge 转角优化`
  - `复制应用命令`
  - `请求详情`
  - `技术详情 / 源属性` collapsed by default
  - no empty scoring section
- Browser console errors from the viewer: 0.

Screenshot saved:

```text
reports\visualizations\laneforge_interaction_simplified_v0009.png
```

Suggested next step:

Start a new, separate controlled path for low-risk `internal_centerline_bend`
smoothing candidates. Do not apply all internal bends with the existing
degree-2 connector policy; they need their own proposal/apply policy and visual
review because they alter road interior shape, not just connector corner
fillets.
