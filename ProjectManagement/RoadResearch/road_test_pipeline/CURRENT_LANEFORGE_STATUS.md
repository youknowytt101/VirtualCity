# LaneForge Current Status

This file is generated from `data/lane_upgrade_packages/<area_id>/latest.json` and the package manifest.

- area_id: `z47n_e704000_n1431000_w1000_h1000_s1000`
- latest_package_version: `lane_package_v0002`
- package_dir: `data/lane_upgrade_packages/z47n_e704000_n1431000_w1000_h1000_s1000/lane_package_v0002`
- manifest: `data/lane_upgrade_packages/z47n_e704000_n1431000_w1000_h1000_s1000/lane_package_v0002/manifest.json`
- houdini_manifest: `data/lane_upgrade_packages/z47n_e704000_n1431000_w1000_h1000_s1000/lane_package_v0002/houdini_manifest.json`
- qa_status: `warn`
- qa_gate_status: `manual_review_required`
- qa_warning_summary: `{"publishable_warn": 0, "manual_review_required": 3, "blocker": 0}`

## Counts

- active_corner_optimizations: `0`
- active_lane_upgrades: `0`
- continuity_links: `36`
- corner_optimization_accepted_active: `0`
- corner_optimization_accepted_active_candidates: `0`
- corner_optimization_accepted_active_overrides: `0`
- corner_optimization_candidates: `79`
- junction_envelope_surfaces: `176`
- junctions: `176`
- lane_links: `1278`
- lane_upgrade_propagation_candidates: `0`
- lane_upgrade_propagation_high_confidence: `0`
- lanes: `676`
- physical_lane_centerlines: `666`
- physical_lane_group_centerlines: `10`

## Semantic Review

- status: `manual_review_required`
- active_lane_policy: ``
- width_fallback_ratio: `1.0`
- lanes_fallback_ratio: `0.512`
- missing_turn_lanes_ratio: `None`
- lane_count_policy_override_ratio: `None`
- direction_policy_override_ratio: `None`
- source_oneway_ignored_approaches: `210`

## Handoff Rule

Houdini and downstream systems consume the latest standard lane package, not data/processed internals.
