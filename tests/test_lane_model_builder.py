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

    def test_lane_upgrade_override_sets_physical_lane_count(self):
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

        self.assertEqual(report["counts"]["active_lane_upgrades_applied"], 1)
        self.assertEqual(len(lane_graph["lanes"]), 3)
        self.assertEqual(
            sorted(lane["lane_id"] for lane in lane_graph["lanes"]),
            ["e0_b_1", "e0_f_1", "e0_f_2"],
        )
        self.assertTrue(all(lane["lane_upgrade_id"] == "lane_upgrade_transaction_v0001" for lane in lane_graph["lanes"]))
        self.assertTrue(all(lane["lane_upgrade_target_physical_lane_count"] == 3 for lane in lane_graph["lanes"]))
        self.assertEqual(lane_graph["lanes"][1]["lateral_offset_m"], 4.8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
