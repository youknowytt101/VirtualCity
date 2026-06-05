# LaneForge Current Status

This file is generated from `data/lane_upgrade_packages/<area_id>/latest.json` and the package manifest.

- area_id: `pattaya_central_500m`
- latest_package_version: `lane_package_v0049`
- package_dir: `data/lane_upgrade_packages/pattaya_central_500m/lane_package_v0049`
- manifest: `data/lane_upgrade_packages/pattaya_central_500m/lane_package_v0049/manifest.json`
- houdini_manifest: `data/lane_upgrade_packages/pattaya_central_500m/lane_package_v0049/houdini_manifest.json`
- qa_status: `warn`
- qa_gate_status: `manual_review_required`
- qa_warning_summary: `{"publishable_warn": 0, "manual_review_required": 4, "blocker": 0}`

## Counts

- active_corner_optimizations: `5`
- active_lane_upgrades: `5`
- continuity_links: `20`
- corner_optimization_accepted_active: `5`
- corner_optimization_accepted_active_candidates: `4`
- corner_optimization_accepted_active_overrides: `5`
- corner_optimization_candidates: `19`
- junction_envelope_surfaces: `49`
- junctions: `49`
- lane_links: `306`
- lane_upgrade_propagation_candidates: `14`
- lane_upgrade_propagation_high_confidence: `4`
- lanes: `200`
- physical_lane_centerlines: `186`
- physical_lane_group_centerlines: `12`

## Semantic Review

- status: `manual_review_required`
- active_lane_policy: `temporary_all_roads_bidirectional_two_lane_v1`
- width_fallback_ratio: `1.0`
- lanes_fallback_ratio: `0.36`
- missing_turn_lanes_ratio: `1.0`
- lane_count_policy_override_ratio: `1.0`
- direction_policy_override_ratio: `1.0`
- source_oneway_ignored_approaches: `96`

## Handoff Rule

Houdini and downstream systems consume the latest standard lane package, not data/processed internals.
