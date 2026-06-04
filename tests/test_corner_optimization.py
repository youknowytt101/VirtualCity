"""Offline tests for road corner optimization candidate planning."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "ProjectManagement" / "RoadResearch" / "road_test_pipeline"


def load_script(module_name: str, relative_path: str):
    script = PIPELINE / "scripts" / relative_path
    spec = importlib.util.spec_from_file_location(module_name, script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


plan_corner_optimization = load_script("plan_corner_optimization", "plan_corner_optimization.py")
export_lane_graph_svg = load_script("export_lane_graph_svg_for_corner_tests", "export_lane_graph_svg.py")
optimize_junction_centerlines = load_script("optimize_junction_centerlines_for_corner_tests", "optimize_junction_centerlines.py")
apply_corner_optimization = load_script("apply_corner_optimization", "apply_corner_optimization.py")


class TestCornerOptimization(unittest.TestCase):
    def test_plan_corner_candidates_finds_connector_and_internal_bend(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            processed = root / "data" / "processed"
            reports = root / "reports"
            processed.mkdir(parents=True)
            reports.mkdir()
            road_graph_path = processed / "unit_road_graph.json"
            optimized_path = processed / "unit_roads_optimized_centerlines.geojson"
            output_path = processed / "unit_corner_optimization_candidates.json"
            report_path = reports / "unit_corner_optimization_report.json"
            road_graph_path.write_text(json.dumps({
                "nodes": [
                    {"node_id": "n0", "x": 0.0, "z": 0.0, "kind": "dead_end", "degree": 1, "incident_edges": ["e0"]},
                    {"node_id": "n1", "x": 10.0, "z": 0.0, "kind": "connector", "degree": 2, "incident_edges": ["e0", "e1"]},
                    {"node_id": "n2", "x": 10.0, "z": 10.0, "kind": "dead_end", "degree": 1, "incident_edges": ["e1"]},
                    {"node_id": "n3", "x": 100.0, "z": 100.0, "kind": "junction", "degree": 3, "incident_edges": []},
                ],
                "edges": [
                    {
                        "edge_id": "e0",
                        "canonical_road_id": "cr0",
                        "from_node": "n0",
                        "to_node": "n1",
                        "length_m": 10.0,
                        "width_m": 6.0,
                        "road_class": "residential",
                        "geometry_xz": [[0.0, 0.0], [10.0, 0.0]],
                    },
                    {
                        "edge_id": "e1",
                        "canonical_road_id": "cr1",
                        "from_node": "n1",
                        "to_node": "n2",
                        "length_m": 10.0,
                        "width_m": 6.0,
                        "road_class": "residential",
                        "geometry_xz": [[10.0, 0.0], [10.0, 10.0]],
                    },
                ],
            }), encoding="utf-8")
            optimized_path.write_text(json.dumps({
                "type": "FeatureCollection",
                "metadata": {"origin_lon": 100.0, "origin_lat": 10.0},
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [
                                [100.0, 10.0],
                                [100.000092, 10.0],
                                [100.000092, 10.00009],
                            ],
                        },
                        "properties": {
                            "vc_part": "optimized_approach_centerline",
                            "source_edge_id": "e_internal",
                            "source_feature_id": "cr_internal",
                            "road_class": "residential",
                            "width_m": 6.0,
                        },
                    }
                ],
            }), encoding="utf-8")

            report = plan_corner_optimization.plan_corner_optimization(
                area_id="unit",
                road_graph_path=road_graph_path,
                optimized_centerlines_path=optimized_path,
                output_path=output_path,
                report_path=report_path,
            )
            data = json.loads(output_path.read_text(encoding="utf-8"))

        types = {candidate["candidate_type"] for candidate in data["candidates"]}
        self.assertIn("degree2_connector_corner", types)
        self.assertIn("internal_centerline_bend", types)
        self.assertEqual(report["counts"]["candidates"], 2)

    def test_svg_exports_corner_candidate_overlay(self):
        svg, report = export_lane_graph_svg.build_svg(
            lane_graph={
                "lanes": [
                    {
                        "lane_id": "e0_f_1",
                        "road_id": "e0",
                        "direction": "forward",
                        "centerline_xz": [[0.0, 0.0], [20.0, 0.0]],
                    }
                ],
                "lane_links": [],
            },
            movement_corridors=None,
            compound_transactions=None,
            raw_roads=None,
            repaired_roads=None,
            canonical_roads=None,
            road_graph=None,
            raw_topology_diagnostics=None,
            area_id="unit",
            width_px=600,
            max_height_px=900,
            max_lane_links=10,
            max_raw_roads=10,
            max_raw_topology_issues=10,
            corner_candidates={
                "candidates": [
                    {
                        "candidate_id": "corner_0000",
                        "candidate_type": "degree2_connector_corner",
                        "risk_level": "low",
                        "turn_angle_deg": 90.0,
                        "suggested_radius_m": 6.0,
                        "center_xz": [10.0, 0.0],
                        "context_polyline_xz": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]],
                    }
                ]
            },
        )

        self.assertIn('id="corner-optimization-candidates"', svg)
        self.assertIn('data-vc-kind="corner_candidate"', svg)
        self.assertIn('data-vc-corner-id="corner_0000"', svg)
        self.assertEqual(report["counts"]["corner_candidates_rendered"], 1)

    def test_corner_plan_marks_active_override_as_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            processed = root / "data" / "processed"
            reports = root / "reports"
            processed.mkdir(parents=True)
            reports.mkdir()
            road_graph_path = processed / "unit_road_graph.json"
            optimized_path = processed / "unit_roads_optimized_centerlines.geojson"
            overrides_path = processed / "unit_corner_optimization_overrides.json"
            output_path = processed / "unit_corner_optimization_candidates.json"
            report_path = reports / "unit_corner_optimization_report.json"
            road_graph_path.write_text(json.dumps({
                "nodes": [
                    {"node_id": "n0", "x": 0.0, "z": 0.0, "kind": "dead_end", "degree": 1, "incident_edges": ["e0"]},
                    {"node_id": "n1", "x": 10.0, "z": 0.0, "kind": "connector", "degree": 2, "incident_edges": ["e0", "e1"]},
                    {"node_id": "n2", "x": 10.0, "z": 10.0, "kind": "dead_end", "degree": 1, "incident_edges": ["e1"]},
                ],
                "edges": [
                    {"edge_id": "e0", "canonical_road_id": "cr0", "from_node": "n0", "to_node": "n1", "length_m": 10.0, "width_m": 6.0, "road_class": "residential", "geometry_xz": [[0.0, 0.0], [10.0, 0.0]]},
                    {"edge_id": "e1", "canonical_road_id": "cr1", "from_node": "n1", "to_node": "n2", "length_m": 10.0, "width_m": 6.0, "road_class": "residential", "geometry_xz": [[10.0, 0.0], [10.0, 10.0]]},
                ],
            }), encoding="utf-8")
            optimized_path.write_text(json.dumps({
                "type": "FeatureCollection",
                "metadata": {"origin_lon": 100.0, "origin_lat": 10.0},
                "features": [],
            }), encoding="utf-8")
            overrides_path.write_text(json.dumps({
                "active_corner_optimizations": [
                    {
                        "enabled": True,
                        "corner_optimization_id": "corner_app_v0001_corner_0000",
                        "application_id": "corner_optimization_application_v0001",
                        "candidate_id": "corner_0000",
                        "node_id": "n1",
                        "from_edge_id": "e0",
                        "to_edge_id": "e1",
                        "policy": "low_risk_degree2_connector_only_v1",
                    }
                ]
            }), encoding="utf-8")

            report = plan_corner_optimization.plan_corner_optimization(
                area_id="unit",
                road_graph_path=road_graph_path,
                optimized_centerlines_path=optimized_path,
                corner_overrides_path=overrides_path,
                output_path=output_path,
                report_path=report_path,
            )
            data = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(report["counts"]["accepted_active"], 1)
        self.assertEqual(report["counts"]["accepted_active_candidates"], 1)
        self.assertEqual(report["counts"]["accepted_active_overrides"], 1)
        self.assertEqual(data["candidates"][0]["status"], "accepted_active")
        self.assertEqual(data["candidates"][0]["corner_optimization_policy"], "low_risk_degree2_connector_only_v1")

    def test_corner_plan_marks_internal_bend_override_as_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            processed = root / "data" / "processed"
            reports = root / "reports"
            processed.mkdir(parents=True)
            reports.mkdir()
            road_graph_path = processed / "unit_road_graph.json"
            optimized_path = processed / "unit_roads_optimized_centerlines.geojson"
            overrides_path = processed / "unit_corner_optimization_overrides.json"
            output_path = processed / "unit_corner_optimization_candidates.json"
            report_path = reports / "unit_corner_optimization_report.json"
            road_graph_path.write_text(json.dumps({
                "nodes": [
                    {"node_id": "n_far", "x": 1000.0, "z": 1000.0, "kind": "junction", "degree": 3, "incident_edges": []},
                ],
                "edges": [],
            }), encoding="utf-8")
            optimized_path.write_text(json.dumps({
                "type": "FeatureCollection",
                "metadata": {"origin_lon": 100.0, "origin_lat": 10.0},
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [
                                [100.0, 10.0],
                                [100.000092, 10.0],
                                [100.000092, 10.00009],
                            ],
                        },
                        "properties": {
                            "vc_part": "optimized_approach_centerline",
                            "source_edge_id": "e_internal",
                            "source_feature_id": "cr_internal",
                            "road_class": "residential",
                            "width_m": 6.0,
                        },
                    }
                ],
            }), encoding="utf-8")
            overrides_path.write_text(json.dumps({
                "active_corner_optimizations": [
                    {
                        "enabled": True,
                        "corner_optimization_id": "corner_optimization_application_v0001_corner_0000",
                        "application_id": "corner_optimization_application_v0001",
                        "candidate_id": "corner_0000",
                        "candidate_type": "internal_centerline_bend",
                        "source_edge_id": "e_internal",
                        "point_index": 1,
                        "policy": "low_risk_internal_centerline_bend_smoothing_v1",
                    }
                ]
            }), encoding="utf-8")

            report = plan_corner_optimization.plan_corner_optimization(
                area_id="unit",
                road_graph_path=road_graph_path,
                optimized_centerlines_path=optimized_path,
                corner_overrides_path=overrides_path,
                output_path=output_path,
                report_path=report_path,
            )
            data = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(report["counts"]["accepted_active"], 1)
        self.assertEqual(report["counts"]["accepted_active_candidates"], 1)
        self.assertEqual(report["counts"]["accepted_active_overrides"], 1)
        self.assertEqual(data["candidates"][0]["status"], "accepted_active")
        self.assertEqual(data["candidates"][0]["corner_optimization_policy"], "low_risk_internal_centerline_bend_smoothing_v1")

    def test_corner_plan_counts_active_override_after_candidate_shape_is_smoothed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            processed = root / "data" / "processed"
            reports = root / "reports"
            processed.mkdir(parents=True)
            reports.mkdir()
            road_graph_path = processed / "unit_road_graph.json"
            optimized_path = processed / "unit_roads_optimized_centerlines.geojson"
            overrides_path = processed / "unit_corner_optimization_overrides.json"
            output_path = processed / "unit_corner_optimization_candidates.json"
            report_path = reports / "unit_corner_optimization_report.json"
            road_graph_path.write_text(json.dumps({
                "nodes": [
                    {"node_id": "n_far", "x": 1000.0, "z": 1000.0, "kind": "junction", "degree": 3, "incident_edges": []},
                ],
                "edges": [],
            }), encoding="utf-8")
            optimized_path.write_text(json.dumps({
                "type": "FeatureCollection",
                "metadata": {"origin_lon": 100.0, "origin_lat": 10.0},
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [
                                [100.0, 10.0],
                                [100.000092, 10.0],
                                [100.000184, 10.0],
                            ],
                        },
                        "properties": {
                            "vc_part": "optimized_approach_centerline",
                            "source_edge_id": "e_internal",
                            "source_feature_id": "cr_internal",
                            "road_class": "residential",
                            "width_m": 6.0,
                        },
                    }
                ],
            }), encoding="utf-8")
            overrides_path.write_text(json.dumps({
                "active_corner_optimizations": [
                    {
                        "enabled": True,
                        "corner_optimization_id": "corner_optimization_application_v0001_corner_0000",
                        "application_id": "corner_optimization_application_v0001",
                        "candidate_id": "corner_0000",
                        "candidate_type": "internal_centerline_bend",
                        "source_edge_id": "e_internal",
                        "point_index": 1,
                        "policy": "low_risk_internal_centerline_bend_smoothing_v1",
                    }
                ]
            }), encoding="utf-8")

            report = plan_corner_optimization.plan_corner_optimization(
                area_id="unit",
                road_graph_path=road_graph_path,
                optimized_centerlines_path=optimized_path,
                corner_overrides_path=overrides_path,
                output_path=output_path,
                report_path=report_path,
            )
            data = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(data["candidates"], [])
        self.assertEqual(report["counts"]["accepted_active"], 1)
        self.assertEqual(report["counts"]["accepted_active_candidates"], 0)
        self.assertEqual(report["counts"]["accepted_active_overrides"], 1)
        self.assertEqual(report["counts"]["active_internal_bend_overrides"], 1)

    def test_corner_plan_does_not_reuse_active_override_candidate_id_for_new_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            processed = root / "data" / "processed"
            reports = root / "reports"
            processed.mkdir(parents=True)
            reports.mkdir()
            road_graph_path = processed / "unit_road_graph.json"
            optimized_path = processed / "unit_roads_optimized_centerlines.geojson"
            overrides_path = processed / "unit_corner_optimization_overrides.json"
            output_path = processed / "unit_corner_optimization_candidates.json"
            report_path = reports / "unit_corner_optimization_report.json"
            road_graph_path.write_text(json.dumps({
                "nodes": [
                    {"node_id": "n_far", "x": 1000.0, "z": 1000.0, "kind": "junction", "degree": 3, "incident_edges": []},
                ],
                "edges": [],
            }), encoding="utf-8")
            optimized_path.write_text(json.dumps({
                "type": "FeatureCollection",
                "metadata": {"origin_lon": 100.0, "origin_lat": 10.0},
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [
                                [100.0, 10.0],
                                [100.000092, 10.0],
                                [100.000092, 10.00009],
                            ],
                        },
                        "properties": {
                            "vc_part": "optimized_approach_centerline",
                            "source_edge_id": "e_internal",
                            "source_feature_id": "cr_internal",
                            "road_class": "residential",
                            "width_m": 6.0,
                        },
                    }
                ],
            }), encoding="utf-8")
            overrides_path.write_text(json.dumps({
                "active_corner_optimizations": [
                    {
                        "enabled": True,
                        "corner_optimization_id": "corner_optimization_application_v0001_corner_0000",
                        "application_id": "corner_optimization_application_v0001",
                        "candidate_id": "corner_0000",
                        "candidate_type": "internal_centerline_bend",
                        "source_edge_id": "e_internal",
                        "point_index": 2,
                        "policy": "low_risk_internal_centerline_bend_smoothing_v1",
                    }
                ]
            }), encoding="utf-8")

            report = plan_corner_optimization.plan_corner_optimization(
                area_id="unit",
                road_graph_path=road_graph_path,
                optimized_centerlines_path=optimized_path,
                corner_overrides_path=overrides_path,
                output_path=output_path,
                report_path=report_path,
            )
            data = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(len(data["candidates"]), 1)
        self.assertEqual(data["candidates"][0]["status"], "candidate_review")
        self.assertEqual(data["candidates"][0]["candidate_id"], "corner_0001")
        self.assertEqual(data["candidates"][0]["candidate_id_reassigned_from"], "corner_0000")
        self.assertEqual(report["counts"]["candidate_id_reassignments"], 1)

    def test_apply_corner_dry_run_selects_only_explicit_low_risk_degree2_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            processed = root / "data" / "processed"
            processed.mkdir(parents=True)
            candidates_path = processed / "unit_corner_optimization_candidates.json"
            candidates_path.write_text(json.dumps({
                "candidates": [
                    {
                        "candidate_id": "corner_0000",
                        "candidate_type": "degree2_connector_corner",
                        "risk_level": "low",
                        "recommended_action": "candidate_for_auto_fillet_after_review",
                        "node_id": "n1",
                        "from_edge_id": "e0",
                        "to_edge_id": "e1",
                        "turn_angle_deg": 90.0,
                        "suggested_cut_m": 2.5,
                        "suggested_radius_m": 4.0,
                    },
                    {
                        "candidate_id": "corner_0001",
                        "candidate_type": "internal_centerline_bend",
                        "risk_level": "low",
                        "recommended_action": "candidate_for_smoothing_after_review",
                        "source_edge_id": "e2",
                        "turn_angle_deg": 45.0,
                    },
                ]
            }), encoding="utf-8")

            result = apply_corner_optimization.apply_corner_optimizations(
                root=root,
                area_id="unit",
                candidates_path=candidates_path,
                candidate_ids={"corner_0000"},
                policy_name=apply_corner_optimization.DEFAULT_POLICY,
                reason="unit",
                reviewer="test",
                dry_run=True,
                no_rebuild=False,
                with_houdini=False,
                all_matching_policy=False,
            )

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual([candidate["candidate_id"] for candidate in result["selected_candidates"]], ["corner_0000"])
        self.assertFalse((Path(td) / "data" / "processed" / "unit_corner_optimization_overrides.json").exists())

    def test_apply_internal_bend_policy_writes_edge_point_override(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            processed = root / "data" / "processed"
            processed.mkdir(parents=True)
            candidates_path = processed / "unit_corner_optimization_candidates.json"
            candidates_path.write_text(json.dumps({
                "candidates": [
                    {
                        "candidate_id": "corner_0000",
                        "candidate_type": "degree2_connector_corner",
                        "risk_level": "low",
                        "recommended_action": "candidate_for_auto_fillet_after_review",
                        "node_id": "n1",
                        "from_edge_id": "e0",
                        "to_edge_id": "e1",
                        "turn_angle_deg": 90.0,
                    },
                    {
                        "candidate_id": "corner_0001",
                        "candidate_type": "internal_centerline_bend",
                        "risk_level": "low",
                        "recommended_action": "candidate_for_smoothing_after_review",
                        "source_edge_id": "e2",
                        "canonical_road_id": "cr2",
                        "point_index": 2,
                        "turn_angle_deg": 45.0,
                        "suggested_cut_m": 1.8,
                        "suggested_radius_m": 2.4,
                        "center_xz": [10.0, 5.0],
                        "context_polyline_xz": [[0.0, 0.0], [10.0, 5.0], [20.0, 0.0]],
                    },
                ]
            }), encoding="utf-8")

            result = apply_corner_optimization.apply_corner_optimizations(
                root=root,
                area_id="unit",
                candidates_path=candidates_path,
                candidate_ids={"corner_0001"},
                policy_name=apply_corner_optimization.INTERNAL_BEND_POLICY,
                reason="unit internal bend",
                reviewer="test",
                dry_run=False,
                no_rebuild=True,
                with_houdini=False,
                all_matching_policy=False,
            )
            overrides = json.loads((processed / "unit_corner_optimization_overrides.json").read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "applied_without_rebuild")
        self.assertEqual([candidate["candidate_id"] for candidate in result["selected_candidates"]], ["corner_0001"])
        self.assertEqual(len(overrides["active_corner_optimizations"]), 1)
        item = overrides["active_corner_optimizations"][0]
        self.assertEqual(item["candidate_type"], "internal_centerline_bend")
        self.assertEqual(item["source_edge_id"], "e2")
        self.assertEqual(item["point_index"], 2)
        self.assertEqual(item["target_geometry"], "optimized_internal_centerline_bend_smoothing")

    def test_optimized_centerlines_annotates_transaction_corner_fillet(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            processed = root / "data" / "processed"
            reports = root / "reports"
            processed.mkdir(parents=True)
            reports.mkdir()
            road_graph_path = processed / "unit_road_graph.json"
            output_path = processed / "unit_roads_optimized_centerlines.geojson"
            report_path = reports / "unit_optimized_centerlines_report.json"
            overrides_path = processed / "unit_corner_optimization_overrides.json"
            road_graph_path.write_text(json.dumps({
                "metadata": {"origin_lon": 100.0, "origin_lat": 10.0},
                "nodes": [
                    {"node_id": "n0", "x": 0.0, "z": 0.0, "kind": "dead_end", "degree": 1, "incident_edges": ["e0"]},
                    {"node_id": "n1", "x": 10.0, "z": 0.0, "kind": "connector", "degree": 2, "incident_edges": ["e0", "e1"]},
                    {"node_id": "n2", "x": 10.0, "z": 10.0, "kind": "dead_end", "degree": 1, "incident_edges": ["e1"]},
                ],
                "edges": [
                    {
                        "edge_id": "e0",
                        "source_feature_id": "cr0",
                        "from_node": "n0",
                        "to_node": "n1",
                        "length_m": 10.0,
                        "width_m": 6.0,
                        "road_class": "residential",
                        "highway": "residential",
                        "lanes": 2,
                        "oneway": False,
                        "geometry_xz": [[0.0, 0.0], [10.0, 0.0]],
                    },
                    {
                        "edge_id": "e1",
                        "source_feature_id": "cr1",
                        "from_node": "n1",
                        "to_node": "n2",
                        "length_m": 10.0,
                        "width_m": 6.0,
                        "road_class": "residential",
                        "highway": "residential",
                        "lanes": 2,
                        "oneway": False,
                        "geometry_xz": [[10.0, 0.0], [10.0, 10.0]],
                    },
                ],
            }), encoding="utf-8")
            overrides_path.write_text(json.dumps({
                "active_corner_optimizations": [
                    {
                        "enabled": True,
                        "corner_optimization_id": "corner_optimization_application_v0001_corner_0000",
                        "application_id": "corner_optimization_application_v0001",
                        "candidate_id": "corner_0000",
                        "node_id": "n1",
                        "from_edge_id": "e0",
                        "to_edge_id": "e1",
                        "suggested_cut_m": 2.2,
                        "policy": "low_risk_degree2_connector_only_v1",
                    }
                ]
            }), encoding="utf-8")

            report = optimize_junction_centerlines.optimize_centerlines(
                road_graph_path,
                output_path,
                report_path,
                "unit",
                None,
                None,
                overrides_path,
            )
            data = json.loads(output_path.read_text(encoding="utf-8"))

        fillets = [
            feature
            for feature in data["features"]
            if (feature.get("properties") or {}).get("vc_part") == "optimized_corner_fillet"
        ]
        props = fillets[0]["properties"]
        self.assertEqual(report["counts"]["corner_transaction_fillets"], 1)
        self.assertEqual(props["corner_optimization_source"], "corner_optimization_transaction")
        self.assertEqual(props["corner_optimization_candidate_id"], "corner_0000")
        self.assertEqual(props["cut_m"], 2.2)

    def test_optimized_centerlines_applies_internal_bend_smoothing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            processed = root / "data" / "processed"
            reports = root / "reports"
            processed.mkdir(parents=True)
            reports.mkdir()
            road_graph_path = processed / "unit_road_graph.json"
            output_path = processed / "unit_roads_optimized_centerlines.geojson"
            report_path = reports / "unit_optimized_centerlines_report.json"
            overrides_path = processed / "unit_corner_optimization_overrides.json"
            road_graph_path.write_text(json.dumps({
                "metadata": {"origin_lon": 100.0, "origin_lat": 10.0},
                "nodes": [
                    {"node_id": "n0", "x": 0.0, "z": 0.0, "kind": "dead_end", "degree": 1, "incident_edges": ["e0"]},
                    {"node_id": "n1", "x": 10.0, "z": 10.0, "kind": "dead_end", "degree": 1, "incident_edges": ["e0"]},
                ],
                "edges": [
                    {
                        "edge_id": "e0",
                        "source_feature_id": "cr0",
                        "from_node": "n0",
                        "to_node": "n1",
                        "length_m": 20.0,
                        "width_m": 6.0,
                        "road_class": "residential",
                        "highway": "residential",
                        "lanes": 2,
                        "oneway": False,
                        "geometry_xz": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]],
                    },
                ],
            }), encoding="utf-8")
            overrides_path.write_text(json.dumps({
                "active_corner_optimizations": [
                    {
                        "enabled": True,
                        "corner_optimization_id": "corner_optimization_application_v0001_corner_0000",
                        "application_id": "corner_optimization_application_v0001",
                        "candidate_id": "corner_0001",
                        "candidate_type": "internal_centerline_bend",
                        "source_edge_id": "e0",
                        "point_index": 1,
                        "suggested_cut_m": 2.0,
                        "policy": "low_risk_internal_centerline_bend_smoothing_v1",
                    }
                ]
            }), encoding="utf-8")

            report = optimize_junction_centerlines.optimize_centerlines(
                road_graph_path,
                output_path,
                report_path,
                "unit",
                None,
                None,
                overrides_path,
            )
            data = json.loads(output_path.read_text(encoding="utf-8"))

        approaches = [
            feature
            for feature in data["features"]
            if (feature.get("properties") or {}).get("vc_part") == "optimized_approach_centerline"
        ]
        props = approaches[0]["properties"]
        self.assertEqual(report["counts"]["internal_bend_smoothing_applied"], 1)
        self.assertEqual(props["internal_bend_smoothing_count"], 1)
        self.assertEqual(props["internal_bend_smoothing_candidate_ids"], "corner_0001")
        self.assertGreater(len(approaches[0]["geometry"]["coordinates"]), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
