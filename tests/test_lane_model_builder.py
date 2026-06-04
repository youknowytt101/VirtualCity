"""Offline tests for lane_model_builder optimized centerline use."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ProjectManagement" / "RoadResearch" / "road_test_pipeline" / "scripts" / "lane_model_builder.py"
spec = importlib.util.spec_from_file_location("lane_model_builder", SCRIPT)
lane_model_builder = importlib.util.module_from_spec(spec)
sys.modules["lane_model_builder"] = lane_model_builder
assert spec.loader is not None
spec.loader.exec_module(lane_model_builder)


class TestLaneModelBuilder(unittest.TestCase):
    def test_lane_link_trim_metadata_uses_longitudinal_station(self):
        from_lane = {"centerline_xz": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]]}
        to_lane = {"centerline_xz": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]]}
        curve = [[6.0, 0.0], [8.0, 2.0], [10.0, 4.0]]

        metadata = lane_model_builder.lane_link_endpoint_trim_metadata(curve, from_lane, to_lane)

        self.assertAlmostEqual(metadata["from_lane_trim_end_m"], 14.0)
        self.assertAlmostEqual(metadata["to_lane_trim_start_m"], 14.0)

    def test_reversed_corner_fillet_offsets_snap_to_backward_lane_endpoints(self):
        lanes = lane_model_builder.build_lanes([
            {
                "edge_id": "e0",
                "from_node": "n0",
                "to_node": "c",
                "geometry_xz": [[0.0, 0.0], [8.0, 0.0]],
            },
            {
                "edge_id": "e1",
                "from_node": "c",
                "to_node": "n1",
                "geometry_xz": [[10.0, 2.0], [10.0, 10.0]],
            },
        ])
        lanes_by_id = {lane["lane_id"]: lane for lane in lanes}
        links = lane_model_builder.build_continuity_links(lanes, [{
            "corner_node_id": "c",
            "corner_id": "c_fillet",
            "from_edge_id": "e0",
            "to_edge_id": "e1",
            "points": [(8.0, 0.0), (9.414, 0.586), (10.0, 2.0)],
        }])

        reverse = next(link for link in links if link["from_lane"] == "e1_b_1" and link["to_lane"] == "e0_b_1")

        self.assertEqual(reverse["connecting_curve_xz"][0], lanes_by_id["e1_b_1"]["centerline_xz"][-1])
        self.assertEqual(reverse["connecting_curve_xz"][-1], lanes_by_id["e0_b_1"]["centerline_xz"][0])
        self.assertAlmostEqual(reverse["from_lane_trim_end_m"], 0.0)
        self.assertAlmostEqual(reverse["to_lane_trim_start_m"], 0.0)
        self.assertGreater(reverse["connecting_curve_xz"][1][0], 9.414)
        self.assertEqual(reverse["rounding_style_id"], "unified_lane_geometry_rounding_style_v1")
        self.assertEqual(reverse["rounding_curve_family"], "tangent_circular_arc")

    def test_inner_corner_continuity_uses_lane_level_min_radius(self):
        lanes = lane_model_builder.build_lanes([
            {
                "edge_id": "e0",
                "from_node": "n0",
                "to_node": "c",
                "geometry_xz": [[0.0, 0.0], [8.0, 0.0]],
            },
            {
                "edge_id": "e1",
                "from_node": "c",
                "to_node": "n1",
                "geometry_xz": [[10.0, 2.0], [10.0, 10.0]],
            },
        ])
        links = lane_model_builder.build_continuity_links(lanes, [{
            "corner_node_id": "c",
            "corner_id": "c_fillet",
            "from_edge_id": "e0",
            "to_edge_id": "e1",
            "points": [(8.0, 0.0), (9.414, 0.586), (10.0, 2.0)],
            "arc_geometry": "circular_arc",
        }])
        lanes_by_id = {lane["lane_id"]: lane for lane in lanes}

        regularized = next(link for link in links if link["lane_level_radius_regularized"])

        self.assertEqual(
            regularized["lane_level_regularization_policy"],
            "lane_level_continuity_min_radius_regularization_v1",
        )
        self.assertGreaterEqual(regularized["lane_level_curve_min_radius_m"], 3.0)
        self.assertEqual(
            regularized["connecting_curve_xz"][0],
            lanes_by_id[regularized["from_lane"]]["centerline_xz"][-1],
        )
        self.assertEqual(
            regularized["connecting_curve_xz"][-1],
            lanes_by_id[regularized["to_lane"]]["centerline_xz"][0],
        )
        self.assertTrue(lanes_by_id[regularized["from_lane"]]["centerline_endpoint_rounding"])
        self.assertTrue(lanes_by_id[regularized["to_lane"]]["centerline_endpoint_rounding"])

    def test_near_straight_degree2_connector_gets_direct_continuity_links(self):
        graph = {
            "nodes": [
                {"node_id": "n0", "kind": "dead_end", "degree": 1, "incident_edges": ["e0"]},
                {"node_id": "c", "kind": "connector", "degree": 2, "incident_edges": ["e0", "e1"]},
                {"node_id": "n1", "kind": "dead_end", "degree": 1, "incident_edges": ["e1"]},
            ],
            "edges": [
                {"edge_id": "e0", "from_node": "n0", "to_node": "c", "geometry_xz": [[0.0, 0.0], [10.0, 0.0]]},
                {"edge_id": "e1", "from_node": "c", "to_node": "n1", "geometry_xz": [[10.0, 0.0], [20.0, 0.2]]},
            ],
        }
        lanes = lane_model_builder.build_lanes(graph["edges"])

        links, stats = lane_model_builder.build_direct_connector_continuity_links(
            graph=graph,
            lanes=lanes,
            corner_fillets=[],
        )

        self.assertEqual(stats["policy"], "degree2_connector_through_continuity_v1")
        self.assertEqual(stats["links_created"], 2)
        forward = next(link for link in links if link["from_lane"] == "e0_f_1")
        reverse = next(link for link in links if link["from_lane"] == "e1_b_1")
        self.assertEqual(forward["to_lane"], "e1_f_1")
        self.assertEqual(reverse["to_lane"], "e0_b_1")
        self.assertEqual(forward["source"], "degree2_connector_through_continuity_v1")
        self.assertEqual(forward["rounding_style_id"], "unified_lane_geometry_rounding_style_v1")
        self.assertEqual(forward["rounding_curve_family"], "straight_infinite_radius")
        self.assertLess(forward["turn_angle_deg"], 18.0)

    def test_direct_connector_micro_seam_snaps_lane_endpoints(self):
        graph = {
            "nodes": [
                {"node_id": "n0", "kind": "dead_end", "degree": 1, "incident_edges": ["e0"]},
                {"node_id": "c", "kind": "connector", "degree": 2, "incident_edges": ["e0", "e1"]},
                {"node_id": "n1", "kind": "dead_end", "degree": 1, "incident_edges": ["e1"]},
            ],
            "edges": [
                {"edge_id": "e0", "from_node": "n0", "to_node": "c", "geometry_xz": [[0.0, 0.0], [10.0, 0.0]]},
                {"edge_id": "e1", "from_node": "c", "to_node": "n1", "geometry_xz": [[10.063, 0.0], [20.063, 0.0]]},
            ],
        }
        lanes = lane_model_builder.build_lanes(graph["edges"])

        links, stats = lane_model_builder.build_direct_connector_continuity_links(
            graph=graph,
            lanes=lanes,
            corner_fillets=[],
        )

        forward = next(link for link in links if link["from_lane"] == "e0_f_1")
        lanes_by_id = {lane["lane_id"]: lane for lane in lanes}
        self.assertEqual(stats["micro_seams_absorbed"], 2)
        self.assertTrue(forward["micro_seam_absorbed"])
        self.assertEqual(forward["endpoint_gap_m"], 0.0)
        self.assertGreater(forward["original_endpoint_gap_m"], 0.0)
        self.assertLessEqual(forward["original_endpoint_gap_m"], 0.1)
        self.assertEqual(forward["curve_length_m"], 0.0)
        self.assertEqual(
            lanes_by_id[forward["from_lane"]]["centerline_xz"][-1],
            lanes_by_id[forward["to_lane"]]["centerline_xz"][0],
        )
        self.assertEqual(
            lanes_by_id[forward["from_lane"]]["centerline_endpoint_snap_policy"],
            "degree2_connector_micro_seam_endpoint_snap_v1",
        )

    def test_direct_connector_continuity_skips_real_corners(self):
        graph = {
            "nodes": [
                {"node_id": "n0", "kind": "dead_end", "degree": 1, "incident_edges": ["e0"]},
                {"node_id": "c", "kind": "connector", "degree": 2, "incident_edges": ["e0", "e1"]},
                {"node_id": "n1", "kind": "dead_end", "degree": 1, "incident_edges": ["e1"]},
            ],
            "edges": [
                {"edge_id": "e0", "from_node": "n0", "to_node": "c", "geometry_xz": [[0.0, 0.0], [10.0, 0.0]]},
                {"edge_id": "e1", "from_node": "c", "to_node": "n1", "geometry_xz": [[10.0, 0.0], [10.0, 10.0]]},
            ],
        }
        lanes = lane_model_builder.build_lanes(graph["edges"])

        links, stats = lane_model_builder.build_direct_connector_continuity_links(
            graph=graph,
            lanes=lanes,
            corner_fillets=[],
        )

        self.assertEqual(links, [])
        self.assertEqual(stats["skipped"]["above_turn_threshold"], 1)

    def test_optimized_approach_centerlines_replace_road_graph_geometry_for_lanes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            graph_path = root / "road_graph.json"
            semantics_path = root / "junction_semantics.json"
            optimized_path = root / "optimized.geojson"
            output_path = root / "lane_graph.json"
            report_path = root / "report.json"

            graph_path.write_text(json.dumps({
                "type": "road_graph",
                "metadata": {"schema": "road_test_pipeline.road_graph.v1"},
                "nodes": [
                    {"node_id": "n0", "kind": "boundary", "degree": 1, "incident_edges": ["e0"]},
                    {"node_id": "n1", "kind": "boundary", "degree": 1, "incident_edges": ["e0"]},
                ],
                "edges": [
                    {
                        "edge_id": "e0",
                        "from_node": "n0",
                        "to_node": "n1",
                        "geometry_xz": [[0.0, 0.0], [20.0, 0.0]],
                        "lanes": 2,
                        "lanes_source": "tag",
                        "oneway": False,
                        "oneway_direction": "bidirectional",
                    }
                ],
            }), encoding="utf-8")
            semantics_path.write_text(json.dumps({"junctions": []}), encoding="utf-8")
            optimized_path.write_text(json.dumps({
                "type": "FeatureCollection",
                "metadata": {"coord_domain": "local_xz_m"},
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "vc_part": "optimized_approach_centerline",
                            "source_edge_id": "e0",
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[5.0, 0.0], [15.0, 0.0]],
                        },
                    }
                ],
            }), encoding="utf-8")

            report = lane_model_builder.build_lane_graph(
                graph_path,
                semantics_path,
                output_path,
                report_path,
                "unit",
                optimized_path,
            )
            lane_graph = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertTrue(lane_graph["metadata"]["approach_centerlines_trimmed"])
        self.assertEqual(report["counts"]["optimized_approach_centerlines_applied"], 1)
        self.assertTrue(all(lane["centerline_source"] == "optimized_approach_centerline" for lane in lane_graph["lanes"]))
        self.assertTrue(all(lane["approach_centerline_trimmed"] for lane in lane_graph["lanes"]))
        self.assertAlmostEqual(lane_graph["lanes"][0]["centerline_xz"][0][0], 5.0)

    def test_lane_upgrade_override_is_deferred_by_temporary_two_lane_policy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            graph_path = root / "road_graph.json"
            semantics_path = root / "junction_semantics.json"
            upgrades_path = root / "lane_upgrades.json"
            output_path = root / "lane_graph.json"
            report_path = root / "report.json"

            graph_path.write_text(json.dumps({
                "type": "road_graph",
                "metadata": {"schema": "road_test_pipeline.road_graph.v1"},
                "nodes": [
                    {"node_id": "n0", "kind": "boundary", "degree": 1, "incident_edges": ["e0"]},
                    {"node_id": "n1", "kind": "boundary", "degree": 1, "incident_edges": ["e0"]},
                ],
                "edges": [
                    {
                        "edge_id": "e0",
                        "from_node": "n0",
                        "to_node": "n1",
                        "geometry_xz": [[0.0, 0.0], [20.0, 0.0]],
                        "lanes": 2,
                        "lanes_source": "default",
                        "oneway": False,
                        "oneway_direction": "bidirectional",
                    }
                ],
            }), encoding="utf-8")
            semantics_path.write_text(json.dumps({"junctions": []}), encoding="utf-8")
            upgrades_path.write_text(json.dumps({
                "metadata": {"schema": "lane_upgrade_system.active_overrides.v1"},
                "active_upgrades": [
                    {
                        "upgrade_id": "lane_upgrade_transaction_v0001",
                        "road_id": "e0",
                        "target_physical_lane_count": 3,
                        "distribution_policy": "balanced_bidirectional_left_traffic_v1",
                        "source": "web_lane_count_menu",
                    }
                ],
            }), encoding="utf-8")

            report = lane_model_builder.build_lane_graph(
                graph_path,
                semantics_path,
                output_path,
                report_path,
                "unit",
                None,
                upgrades_path,
            )
            lane_graph = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(report["counts"]["active_lane_upgrades_applied"], 0)
        self.assertEqual(report["counts"]["active_lane_upgrades_deferred"], 1)
        self.assertEqual(
            lane_graph["metadata"]["lane_upgrade_geometry_application_policy"],
            "defer_lane_upgrade_overrides_keep_all_roads_bidirectional_two_lane_v1",
        )
        self.assertEqual(lane_graph["metadata"]["lane_upgrade_deferred_road_ids"], ["e0"])
        self.assertEqual(len(lane_graph["lanes"]), 2)
        self.assertEqual(
            sorted(lane["lane_id"] for lane in lane_graph["lanes"]),
            ["e0_b_1", "e0_f_1"],
        )
        self.assertTrue(all(lane["source"] == "temporary_bidirectional_two_lane_policy" for lane in lane_graph["lanes"]))
        self.assertTrue(all(lane["lane_upgrade_id"] == "" for lane in lane_graph["lanes"]))
        self.assertTrue(all(lane["lane_upgrade_target_physical_lane_count"] == 0 for lane in lane_graph["lanes"]))
        self.assertEqual([lane["lateral_offset_m"] for lane in lane_graph["lanes"]], [1.6, -1.6])

    def test_derived_lane_centerline_smoothing_preserves_lane_endpoints(self):
        lanes = lane_model_builder.build_lanes([
            {
                "edge_id": "e0",
                "from_node": "n0",
                "to_node": "n1",
                "geometry_xz": [[0.0, 0.0], [50.0, 0.6], [100.0, 0.0]],
            }
        ])
        original = {
            lane["lane_id"]: {
                "first": list(lane["centerline_xz"][0]),
                "last": list(lane["centerline_xz"][-1]),
                "point_count": len(lane["centerline_xz"]),
            }
            for lane in lanes
        }

        stats = lane_model_builder.apply_derived_lane_centerline_smoothing(lanes)

        self.assertEqual(stats["policy"], "derived_lane_centerline_smoothing_v1")
        self.assertEqual(stats["rounding_style_id"], "unified_lane_geometry_rounding_style_v1")
        self.assertEqual(stats["curve_family"], "tangent_circular_arc")
        self.assertEqual(stats["smoothed_lane_count"], 2)
        self.assertEqual(stats["smoothed_bend_count"], 2)
        self.assertEqual(stats["curve_family_counts"]["tangent_circular_arc"], 2)
        self.assertEqual(stats["arc_fit_status_counts"]["exact_tangent_arc"], 2)
        self.assertGreater(stats["inserted_sample_points"], 0)
        self.assertLessEqual(stats["max_derivation_offset_m"], 0.35)
        for lane in lanes:
            lane_id = lane["lane_id"]
            self.assertEqual(lane["centerline_xz"][0], original[lane_id]["first"])
            self.assertEqual(lane["centerline_xz"][-1], original[lane_id]["last"])
            self.assertGreater(len(lane["centerline_xz"]), original[lane_id]["point_count"])
            self.assertEqual(lane["centerline_derivation_policy"], "derived_lane_centerline_smoothing_v1")
            self.assertEqual(
                lane["derived_centerline_smoothing"]["rounding_style_id"],
                "unified_lane_geometry_rounding_style_v1",
            )
            self.assertEqual(lane["derived_centerline_smoothing"]["curve_family"], "tangent_circular_arc")
            self.assertEqual(
                lane["derived_centerline_smoothing"]["derived_point_count"],
                len(lane["centerline_xz"]),
            )

    def test_derived_lane_centerline_smoothing_rounds_lane_level_hard_bends(self):
        lanes = lane_model_builder.build_lanes([
            {
                "edge_id": "e0",
                "from_node": "n0",
                "to_node": "n1",
                "geometry_xz": [[0.0, 0.0], [20.0, 20.0], [40.0, 0.0]],
            }
        ])
        original = {
            lane["lane_id"]: {
                "first": list(lane["centerline_xz"][0]),
                "last": list(lane["centerline_xz"][-1]),
                "point_count": len(lane["centerline_xz"]),
            }
            for lane in lanes
        }

        stats = lane_model_builder.apply_derived_lane_centerline_smoothing(lanes)

        self.assertEqual(stats["smoothed_lane_count"], 2)
        self.assertEqual(stats["smoothed_bend_count"], 2)
        self.assertEqual(stats["profile_counts"]["hard_bend_lane_level_rounding"], 2)
        self.assertEqual(stats["curve_family_counts"]["tangent_circular_arc"], 2)
        self.assertLessEqual(stats["max_derivation_offset_m"], 2.6)
        for lane in lanes:
            lane_id = lane["lane_id"]
            self.assertEqual(lane["centerline_xz"][0], original[lane_id]["first"])
            self.assertEqual(lane["centerline_xz"][-1], original[lane_id]["last"])
            self.assertGreater(len(lane["centerline_xz"]), original[lane_id]["point_count"])
            self.assertEqual(lane["centerline_derivation_policy"], "derived_lane_centerline_smoothing_v1")
            self.assertEqual(
                lane["derived_centerline_smoothing"]["profile_counts"]["hard_bend_lane_level_rounding"],
                1,
            )
            self.assertEqual(
                lane["derived_centerline_smoothing"]["arc_fit_status_counts"]["exact_tangent_arc"],
                1,
            )

    def test_derived_lane_centerline_smoothing_rounds_large_source_offset_hard_bends(self):
        lanes = lane_model_builder.build_lanes([
            {
                "edge_id": "e0",
                "from_node": "n0",
                "to_node": "n1",
                "geometry_xz": [[0.0, 0.0], [100.0, 100.0], [200.0, 0.0]],
            }
        ])
        original = {
            lane["lane_id"]: {
                "first": list(lane["centerline_xz"][0]),
                "last": list(lane["centerline_xz"][-1]),
                "point_count": len(lane["centerline_xz"]),
            }
            for lane in lanes
        }

        stats = lane_model_builder.apply_derived_lane_centerline_smoothing(lanes)

        self.assertEqual(stats["smoothed_lane_count"], 2)
        self.assertEqual(stats["profile_counts"]["hard_bend_lane_level_rounding"], 2)
        self.assertGreater(stats["max_source_bend_offset_m"], 24.0)
        self.assertLessEqual(stats["max_derivation_offset_m"], 2.6)
        for lane in lanes:
            lane_id = lane["lane_id"]
            self.assertEqual(lane["centerline_xz"][0], original[lane_id]["first"])
            self.assertEqual(lane["centerline_xz"][-1], original[lane_id]["last"])
            self.assertGreater(len(lane["centerline_xz"]), original[lane_id]["point_count"])
            self.assertEqual(lane["centerline_derivation_policy"], "derived_lane_centerline_smoothing_v1")

    def test_derived_lane_centerline_smoothing_rounds_short_connector_hard_bends(self):
        lanes = [
            {
                "lane_id": "e0_b_1",
                "road_id": "e0",
                "centerline_xz": [[0.0, 0.0], [4.0, 0.0], [4.0, 100.0]],
            },
            {
                "lane_id": "e0_f_1",
                "road_id": "e0",
                "centerline_xz": [[0.0, 0.0], [100.0, 0.0], [99.37, 1.79]],
            },
        ]
        original = {
            lane["lane_id"]: {
                "first": list(lane["centerline_xz"][0]),
                "last": list(lane["centerline_xz"][-1]),
                "point_count": len(lane["centerline_xz"]),
            }
            for lane in lanes
        }

        stats = lane_model_builder.apply_derived_lane_centerline_smoothing(lanes)

        self.assertEqual(stats["smoothed_lane_count"], 2)
        self.assertEqual(stats["smoothed_bend_count"], 2)
        self.assertEqual(stats["profile_counts"]["hard_bend_lane_level_rounding"], 2)
        self.assertNotIn("short_adjacent_segment", stats["skipped_bends"])
        self.assertLessEqual(stats["max_derivation_offset_m"], 2.6)
        for lane in lanes:
            lane_id = lane["lane_id"]
            self.assertEqual(lane["centerline_xz"][0], original[lane_id]["first"])
            self.assertEqual(lane["centerline_xz"][-1], original[lane_id]["last"])
            self.assertGreater(len(lane["centerline_xz"]), original[lane_id]["point_count"])
            self.assertEqual(lane["centerline_derivation_policy"], "derived_lane_centerline_smoothing_v1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
