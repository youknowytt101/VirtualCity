"""Locks for RoadBuildParams packing — behaviour-preserving guarantee.

Road parameters drive Houdini road geometry. This refactor only changes how the
same values are passed (one RoadBuildParams bundle instead of 28 positional
args). These tests freeze that the packed values stay byte-identical to the
BuildContext fields, so the model output cannot drift via this path. A real
recook + model_fingerprint diff is the second line of defence outside pytest.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))

from houdini_build.context import BuildContext, RoadBuildParams


# RoadBuildParams field -> BuildContext field. The whole contract is that these
# pairs carry identical values; a wrong mapping or default is the bug we block.
FIELD_MAP = {
    "centerline_resample_enabled": "road_centerline_resample_enabled",
    "centerline_resample_spacing_m": "road_centerline_resample_spacing_m",
    "centerline_resample_preserve_bend_deg": "road_centerline_resample_preserve_bend_deg",
    "shared_topology_enabled": "road_shared_topology_enabled",
    "shared_topology_fuse_tolerance_m": "road_shared_topology_fuse_tolerance_m",
    "shared_topology_intersection_tolerance_m": "road_shared_topology_intersection_tolerance_m",
    "shared_topology_max_segments": "road_shared_topology_max_segments",
    "junction_curve_smooth_enabled": "road_junction_curve_smooth_enabled",
    "junction_curve_smooth_distance_m": "road_junction_curve_smooth_distance_m",
    "junction_curve_smooth_min_branch_distance_m": "road_junction_curve_smooth_min_branch_distance_m",
    "junction_curve_smooth_min_angle_deg": "road_junction_curve_smooth_min_angle_deg",
    "junction_curve_smooth_max_angle_deg": "road_junction_curve_smooth_max_angle_deg",
    "junction_curve_smooth_arc_spacing_m": "road_junction_curve_smooth_arc_spacing_m",
    "junction_curve_smooth_iterations": "road_junction_curve_smooth_iterations",
    "junction_curve_smooth_max_junctions": "road_junction_curve_smooth_max_junctions",
    "turn_curve_smooth_enabled": "road_turn_curve_smooth_enabled",
    "turn_curve_smooth_distance_m": "road_turn_curve_smooth_distance_m",
    "turn_curve_smooth_min_branch_distance_m": "road_turn_curve_smooth_min_branch_distance_m",
    "turn_curve_smooth_min_angle_deg": "road_turn_curve_smooth_min_angle_deg",
    "turn_curve_smooth_max_angle_deg": "road_turn_curve_smooth_max_angle_deg",
    "turn_curve_smooth_arc_spacing_m": "road_turn_curve_smooth_arc_spacing_m",
    "turn_curve_smooth_iterations": "road_turn_curve_smooth_iterations",
    "turn_curve_smooth_max_bends": "road_turn_curve_smooth_max_bends",
    "vertex_cleanup_enabled": "road_vertex_cleanup_enabled",
    "vertex_cleanup_spacing_m": "road_vertex_cleanup_spacing_m",
    "vertex_cleanup_min_spacing_m": "road_vertex_cleanup_min_spacing_m",
    "vertex_cleanup_anchor_angle_deg": "road_vertex_cleanup_anchor_angle_deg",
    "vertex_cleanup_reuse_tolerance_m": "road_vertex_cleanup_reuse_tolerance_m",
}


class TestRoadBuildParamsPacking(unittest.TestCase):
    def test_defaults_match_buildcontext_defaults(self):
        """Packed defaults equal the legacy BuildContext defaults, value+type."""
        ctx = BuildContext.from_config({})
        params = RoadBuildParams()
        for p_field, c_field in FIELD_MAP.items():
            with self.subTest(field=p_field):
                pv = getattr(params, p_field)
                cv = getattr(ctx, c_field)
                self.assertEqual(pv, cv)
                self.assertIs(type(pv), type(cv))

    def test_property_forwards_context_values(self):
        """ctx.road_build_params mirrors the same context, no value drift."""
        ctx = BuildContext.from_config({})
        packed = ctx.road_build_params
        for p_field, c_field in FIELD_MAP.items():
            with self.subTest(field=p_field):
                self.assertEqual(getattr(packed, p_field), getattr(ctx, c_field))

    def test_property_forwards_non_default_overrides(self):
        """Non-default cfg values flow through the packing unchanged."""
        cfg = {
            "road_shared_topology_fuse_tolerance_m": 0.5,
            "road_junction_curve_smooth_distance_m": 7.5,
            "road_vertex_cleanup_enabled": False,
            "road_turn_curve_smooth_max_bends": 999,
        }
        ctx = BuildContext.from_config(cfg)
        packed = ctx.road_build_params
        self.assertEqual(packed.shared_topology_fuse_tolerance_m, 0.5)
        self.assertEqual(packed.junction_curve_smooth_distance_m, 7.5)
        self.assertFalse(packed.vertex_cleanup_enabled)
        self.assertEqual(packed.turn_curve_smooth_max_bends, 999)

    def test_field_map_covers_all_param_fields(self):
        """Guard against a future param field escaping the lock."""
        from dataclasses import fields
        param_fields = {f.name for f in fields(RoadBuildParams)}
        self.assertEqual(param_fields, set(FIELD_MAP.keys()))


if __name__ == "__main__":
    unittest.main()