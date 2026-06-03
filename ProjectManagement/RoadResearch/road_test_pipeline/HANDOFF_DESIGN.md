# Road Pipeline Handoff: Corner Continuity vs Junction Semantics

Date: 2026-06-03
Area: `pattaya_central_500m`

## Goal

The current replay state keeps the fixed-width road/lane baseline while preserving the hard-corner roundover fix without letting that fix pollute true T, Y, fork, merge, split, or cross junction lane behavior.

The important design rule is:

> Geometry continuity and junction movement semantics are separate layers.

Map input should be treated as skeleton plus partial semantics. The pipeline may infer missing structure, but it should keep those inferences auditable and avoid using one geometry convenience path as the source of all lane movement truth.

## Pipeline Layers

1. `topology_repair.py`
   - Repairs and splits raw OSM-like centerline input.
   - Produces repaired road centerlines.

2. `road_graph_builder.py`
   - Builds the node/edge graph.
   - Keeps road geometry and basic lane counts/tags.

3. `junction_semantics_builder.py`
   - Classifies true graph junctions and infers allowed/blocked road-level movements.
   - Current sample has mostly T junctions plus a small number of cross junctions.

4. `optimize_junction_centerlines.py`
   - Produces road-level optimized centerlines for visual skeleton continuity.
   - Emits:
     - `optimized_approach_centerline`
     - `optimized_junction_connector`
     - `optimized_corner_fillet`
   - `optimized_junction_connector` belongs to the road skeleton layer, not the laneLink semantic layer.

5. `lane_model_builder.py`
   - Builds fixed-width lanes from raw road graph edges.
   - Builds semantic laneLinks from `junction_semantics`.
   - Builds separate corner `continuity_links` from degree-2 `optimized_corner_fillet` features.

6. `generate_lane_geometry_debug.py`
   - Builds lane debug centerlines/ribbons, semantic laneLink debug geometry, and corner continuity debug geometry.

7. `generate_lane_surface_v1.py`
   - Builds lane approach surfaces, semantic turn surfaces, and corner continuity surfaces.

8. Houdini import/cook scripts
   - Import the optimized road centerline preview and lane debug/surface outputs.
   - Default visible output remains `OUT_roads_centerlines`.

## Classification Contract

Ordinary road bends / alignment corners:

- Topology: effectively degree 2.
- Semantics: no merge/split/fork meaning.
- Geometry source: `optimized_corner_fillet`.
- Lane output: `continuity_links`.
- Surface output: `lane_continuity_surface_v1`.

True junctions / forks / merge-split nodes:

- Topology: degree >= 3.
- Semantics: T, Y, cross, fork, merge, split, or equivalent road movement logic.
- Geometry source for laneLinks: semantic lane endpoints.
- Lane output: junction `connections[].lane_links[]`.
- Must not consume `optimized_junction_connector` as the laneLink curve source.

## Why The Regression Happened

The hard-corner fix itself was correct: it rounded ordinary road bends using `optimized_corner_fillet` and converted those into lane-level continuity links.

The regression happened when road-level `optimized_junction_connector` geometry was also pushed down into laneLink generation. That made true T/cross/fork movements inherit a road-skeleton connector shape instead of using independent semantic movement logic. The visual skeleton improvement and the junction movement model became coupled.

## Current Implementation Points

`scripts/lane_model_builder.py`

- `build_lane_graph()` now builds lanes from `graph["edges"]`, not from globally substituted optimized approach edges.
- `optimized_approach_centerlines` are still counted and reported, but `approach_centerlines_trimmed` is false for the lane graph.
- `build_junctions_from_semantics()` no longer accepts or indexes optimized junction connectors.
- `build_lane_link_records()` always sets:
  - `curve_source = "junction_lane_endpoint_bezier"`
  - `connector_id = ""`
  - `connector_kind = ""`
- `build_continuity_links()` remains the only lane-level consumer of `optimized_corner_fillet`.
- Report contract:
  - `junction_lane_strategy = "semantic_lane_endpoint_bezier"`
  - `corner_continuity_strategy = "optimized_corner_fillet_only"`
  - `optimized_junction_connector_lane_links = 0`

`scripts/generate_lane_geometry_debug.py`

- Trims lane debug centerlines using semantic laneLink trim distances and locked corner continuity trim distances.
- Emits separate debug primitives for laneLinks and continuity links.

`scripts/generate_lane_surface_v1.py`

- Builds exactly three surface classes:
  - lane approach surfaces
  - semantic lane turn surfaces
  - corner continuity surfaces
- Keeps all lane and turn widths at the fixed `3.2m` baseline.

`scripts/audit_road_pipeline.py`

- Replaced the old expectation that optimized junction connectors should feed laneLinks.
- New audit check: `junction_lane_links_are_semantic_not_optimized_connectors`.
- The check passes only when laneLink curve sources contain neither `optimized_junction_connector` nor `optimized_approach_endpoint_bezier`.

`scripts/houdini_build_road_test.py`

- Houdini-side debug lane trimming now mirrors the standalone debug/surface trim policy.
- `OUT_lane_connections_debug` reflects the same semantic laneLinks plus corner continuity links.
- Default display node remains `OUT_roads_centerlines`.

## Curve And Trim Strategy

Semantic laneLinks:

- Start with from-lane and to-lane endpoint geometry.
- Use endpoint Bezier construction through `lane_connection_curve()`.
- Apply junction trim metadata after the lane graph has all laneLinks and continuity links.
- Maintain tiny endpoint gaps after trimming:
  - max laneLink start gap: `0.000637m`
  - max laneLink end gap: `0.000637m`

Corner continuity links:

- Use road-level `optimized_corner_fillet` sample points.
- Offset the fillet per connected lane lateral offset.
- Lock the source and target lane trims to the fillet endpoints.
- Maintain tiny endpoint gaps:
  - max continuity start gap: `0.001268m`
  - max continuity end gap: `0.001268m`

Lane/surface trimming:

- True junction laneLinks use the existing junction trim policy, currently `8.0m`.
- Corner continuity trims are locked so ordinary bends do not leave hard gaps.
- No global optimized-approach replacement is used for lane graph geometry.

## Verified Metrics

Full rebuild command:

```powershell
uv --cache-dir E:\VirtualCity\Scripts\.uv-cache run python ProjectManagement/RoadResearch/road_test_pipeline/scripts/rebuild_road_test.py
```

Status:

- Full rebuild: completed
- Pipeline audit: pass
- Houdini RPYC cook: completed
- Houdini display node: `/obj/road_test_pattaya_central_500m/OUT_roads_centerlines`

Lane graph:

- lanes: `612`
- junctions: `49`
- connections: `164`
- laneLinks: `253`
- continuity links: `42`
- optimized approach centerlines: `243`
- optimized junction connectors: `149`
- optimized junction connector laneLinks: `0`
- optimized corner fillet links: `42`
- lane centerline source counts: `road_graph = 612`
- laneLink curve source counts: `junction_lane_endpoint_bezier = 253`
- lane width: fixed `3.2m`

Surface/debug:

- lane debug primitives in Houdini: `1814`
- lane debug points in Houdini: `11637`
- lane surface primitives in Houdini: `907`
- lane surface points in Houdini: `7758`
- standalone lane surfaces: `612`
- semantic turn surfaces: `253`
- continuity surfaces: `42`
- total lane/surface OBJ faces: `907`

Road skeleton preview:

- optimized road features: `413`
- preview output prims: `413`
- preview output points: `2282`
- road preview remains centerline-only with no polygon road-surface fan output.

QA:

- topology repair QA: pass
- road graph QA: warn
- lane graph QA: pass
- pipeline audit failed/warn checks: none

The road graph warning is the known fixed-width fallback warning:

- `width_fallback_ratio = 1.0`
- This is expected in the fixed-width rollback state.

## Unresolved / Watch Items

- True junction movement semantics are still inferred from geometry because this OSM sample lacks reliable turn restrictions.
- `optimized_junction_connector` remains useful for the road skeleton preview but must stay out of laneLink generation.
- The fixed-width `3.2m` baseline is intentional for this phase. Do not reintroduce width inference unless the design explicitly moves back to a width-model stage.
- Road surface fan/polygon generation is intentionally disabled in the preview path. Do not use a large junction fan/patch as the main solution for this issue.

## Next Tasks For Another AI Window

1. Preserve the current separation contract while doing any future road/lane work.
2. If improving T/Y/fork behavior, modify semantic movement inference or laneLink endpoint construction, not `optimized_junction_connector` reuse.
3. If adding visual QA, compare:
   - `OUT_roads_centerlines`
   - `OUT_lane_connections_debug`
   - `OUT_lane_surfaces_v1`
4. Keep audit coverage for:
   - `optimized_junction_connector_lane_links == 0`
   - `continuity_links == optimized_corner_fillet_links`
   - fixed lane width remains `3.2m`
5. Only after a new explicit design decision should width inference, optimized approach lane replacement, or road-surface fan geometry be reintroduced.
