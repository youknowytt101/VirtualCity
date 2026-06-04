"""Offline tests for the LaneForge lane upgrade entry contract."""

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


create_lane_upgrade_transaction = load_script(
    "create_lane_upgrade_transaction",
    "create_lane_upgrade_transaction.py",
)
execute_lane_upgrade = load_script("execute_lane_upgrade", "execute_lane_upgrade.py")
plan_lane_upgrade_propagation = load_script("plan_lane_upgrade_propagation", "plan_lane_upgrade_propagation.py")
apply_lane_upgrade_propagation = load_script("apply_lane_upgrade_propagation", "apply_lane_upgrade_propagation.py")
build_lane_upgrade_package = load_script("build_lane_upgrade_package", "build_lane_upgrade_package.py")
export_lane_graph_svg = load_script("export_lane_graph_svg", "export_lane_graph_svg.py")


class TestLaneUpgradeSystem(unittest.TestCase):
    def test_transaction_resolves_canonical_id_and_records_adjacent_junction_scope(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            processed = root / "data" / "processed"
            processed.mkdir(parents=True)
            (processed / "unit_road_graph.json").write_text(json.dumps({
                "type": "road_graph",
                "nodes": [
                    {"node_id": "n0", "kind": "junction"},
                    {"node_id": "n1", "kind": "dead_end"},
                ],
                "edges": [
                    {
                        "edge_id": "e_0042",
                        "canonical_road_id": "cr_0042",
                        "from_node": "n0",
                        "to_node": "n1",
                    }
                ],
            }), encoding="utf-8")

            result = create_lane_upgrade_transaction.create_transaction(
                area_id="unit",
                road_id="",
                canonical_road_id="cr_0042",
                target_physical_lane_count=3,
                reason="unit test",
                reviewer="test",
                source="web_lane_count_menu",
                root=root,
                activate=True,
            )

            transaction = result["transaction"]
            active = json.loads((processed / "unit_lane_upgrade_overrides.json").read_text(encoding="utf-8"))

        self.assertEqual(transaction["request"]["road_id"], "e_0042")
        self.assertEqual(transaction["request"]["canonical_road_id"], "cr_0042")
        self.assertEqual(transaction["affected_scope"]["endpoint_node_ids"], ["n0", "n1"])
        self.assertEqual(transaction["affected_scope"]["adjacent_junction_node_ids"], ["n0"])
        self.assertEqual(active["active_upgrades"][0]["road_id"], "e_0042")
        self.assertEqual(active["active_upgrades"][0]["canonical_road_id"], "cr_0042")

    def test_transaction_rejects_mismatched_road_and_canonical_ids(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            processed = root / "data" / "processed"
            processed.mkdir(parents=True)
            (processed / "unit_road_graph.json").write_text(json.dumps({
                "nodes": [],
                "edges": [{"edge_id": "e_0001", "canonical_road_id": "cr_0001"}],
            }), encoding="utf-8")

            with self.assertRaises(ValueError):
                create_lane_upgrade_transaction.create_transaction(
                    area_id="unit",
                    road_id="e_9999",
                    canonical_road_id="cr_0001",
                    target_physical_lane_count=2,
                    reason="unit test",
                    reviewer="test",
                    source="web_lane_count_menu",
                    root=root,
                    activate=False,
                )

    def test_svg_canonical_overlay_carries_road_graph_edge_id(self):
        svg, report = export_lane_graph_svg.build_svg(
            lane_graph={
                "lanes": [
                    {
                        "lane_id": "e_0042_f_1",
                        "road_id": "e_0042",
                        "direction": "forward",
                        "centerline_xz": [[0.0, 0.0], [10.0, 0.0]],
                    }
                ],
                "lane_links": [],
            },
            movement_corridors=None,
            compound_transactions=None,
            raw_roads=None,
            repaired_roads=None,
            canonical_roads={
                "type": "FeatureCollection",
                "metadata": {"origin_lon": 100.0, "origin_lat": 10.0},
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[100.0, 10.0], [100.0001, 10.0]],
                        },
                        "properties": {"canonical_road_id": "cr_0042", "highway": "residential"},
                    }
                ],
            },
            road_graph={
                "edges": [{"edge_id": "e_0042", "canonical_road_id": "cr_0042"}],
            },
            raw_topology_diagnostics=None,
            area_id="unit",
            width_px=600,
            max_height_px=900,
            max_lane_links=10,
            max_raw_roads=10,
            max_raw_topology_issues=10,
        )

        self.assertIn('data-vc-road-id="e_0042"', svg)
        self.assertIn('data-vc-road-graph-edge-id="e_0042"', svg)
        self.assertEqual(report["counts"]["canonical_roads_road_graph_edge_mapped"], 1)

    def test_execution_chooses_next_package_version(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package_root = root / "data" / "lane_upgrade_packages" / "unit"
            (package_root / "lane_package_v0001").mkdir(parents=True)
            (package_root / "lane_package_v0002").mkdir()

            self.assertEqual(execute_lane_upgrade.next_package_version(root, "unit"), "lane_package_v0003")

    def test_execution_transaction_command_includes_road_and_canonical_ids(self):
        cmd = execute_lane_upgrade.command_for_transaction(
            root=PIPELINE,
            area_id="unit",
            road_id="e_0042",
            canonical_road_id="cr_0042",
            target_lane_count=4,
            reason="unit test",
            reviewer="test",
            source="web_lane_count_menu",
        )

        self.assertIn("--road-id", cmd)
        self.assertIn("e_0042", cmd)
        self.assertIn("--canonical-road-id", cmd)
        self.assertIn("cr_0042", cmd)
        self.assertIn("--target-lane-count", cmd)
        self.assertIn("4", cmd)

    def test_restore_default_transaction_removes_active_override(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            processed = root / "data" / "processed"
            processed.mkdir(parents=True)
            (processed / "unit_road_graph.json").write_text(json.dumps({
                "nodes": [
                    {"node_id": "n0", "kind": "junction"},
                    {"node_id": "n1", "kind": "dead_end"},
                ],
                "edges": [
                    {
                        "edge_id": "e_0042",
                        "canonical_road_id": "cr_0042",
                        "from_node": "n0",
                        "to_node": "n1",
                    }
                ],
            }), encoding="utf-8")
            active_path = processed / "unit_lane_upgrade_overrides.json"
            active_path.write_text(json.dumps({
                "active_upgrades": [
                    {
                        "enabled": True,
                        "upgrade_id": "u0",
                        "road_id": "e_0042",
                        "canonical_road_id": "cr_0042",
                        "target_physical_lane_count": 3,
                    }
                ]
            }), encoding="utf-8")

            result = create_lane_upgrade_transaction.create_restore_transaction(
                area_id="unit",
                road_id="e_0042",
                canonical_road_id="cr_0042",
                reason="unit restore",
                reviewer="test",
                source="web_lane_count_menu",
                root=root,
                activate=True,
            )
            active = json.loads(active_path.read_text(encoding="utf-8"))

        self.assertEqual(result["transaction"]["request"]["action"], "restore_road_lane_count_default")
        self.assertEqual(result["transaction"]["request"]["target_physical_lane_count"], 0)
        self.assertEqual(active["active_upgrades"], [])

    def test_execution_restore_default_command_uses_restore_flag(self):
        cmd = execute_lane_upgrade.command_for_transaction(
            root=PIPELINE,
            area_id="unit",
            road_id="e_0042",
            canonical_road_id="cr_0042",
            target_lane_count=None,
            reason="unit restore",
            reviewer="test",
            source="web_lane_count_menu",
            restore_default=True,
        )

        self.assertIn("--restore-default", cmd)
        self.assertNotIn("--target-lane-count", cmd)
        self.assertIn("e_0042", cmd)

    def test_propagation_plan_finds_through_pair_and_short_edge_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            processed = root / "data" / "processed"
            reports = root / "reports"
            processed.mkdir(parents=True)
            reports.mkdir()
            road_graph_path = processed / "unit_road_graph.json"
            semantics_path = processed / "unit_junction_semantics.json"
            active_path = processed / "unit_lane_upgrade_overrides.json"
            output_path = root / "data" / "lane_upgrade_system" / "propagation" / "unit_lane_upgrade_propagation_plan_v0001.json"
            report_path = reports / "unit_lane_upgrade_propagation_report.json"
            road_graph_path.write_text(json.dumps({
                "nodes": [
                    {"node_id": "n0", "kind": "junction"},
                    {"node_id": "n1", "kind": "dead_end"},
                    {"node_id": "n2", "kind": "dead_end"},
                    {"node_id": "n3", "kind": "dead_end"},
                ],
                "edges": [
                    {"edge_id": "e0", "canonical_road_id": "cr0", "from_node": "n0", "to_node": "n1", "lanes": 2, "length_m": 100.0, "road_class": "residential"},
                    {"edge_id": "e1", "canonical_road_id": "cr1", "from_node": "n0", "to_node": "n2", "lanes": 2, "length_m": 90.0, "road_class": "residential"},
                    {"edge_id": "e2", "canonical_road_id": "cr2", "from_node": "n0", "to_node": "n3", "lanes": 1, "length_m": 12.0, "road_class": "service"},
                ],
            }), encoding="utf-8")
            semantics_path.write_text(json.dumps({
                "junctions": [
                    {
                        "junction_id": "j0",
                        "node_id": "n0",
                        "type": "T",
                        "through_pairs": [{"edge_a": "e0", "edge_b": "e1"}],
                        "approaches": [
                            {"edge_id": "e0", "role": "major_through"},
                            {"edge_id": "e1", "role": "major_through"},
                            {"edge_id": "e2", "role": "minor_branch"},
                        ],
                    }
                ],
            }), encoding="utf-8")
            active_path.write_text(json.dumps({
                "active_upgrades": [
                    {
                        "enabled": True,
                        "upgrade_id": "u0",
                        "road_id": "e0",
                        "target_physical_lane_count": 3,
                        "affected_scope": {"adjacent_junction_node_ids": ["n0"]},
                    }
                ],
            }), encoding="utf-8")

            report = plan_lane_upgrade_propagation.plan_propagation(
                area_id="unit",
                root=root,
                road_graph_path=road_graph_path,
                junction_semantics_path=semantics_path,
                active_overrides_path=active_path,
                output_path=output_path,
                report_path=report_path,
                short_edge_threshold_m=35.0,
            )
            plan = json.loads(output_path.read_text(encoding="utf-8"))

        rules_by_road = {candidate["candidate_road_id"]: candidate["rule_id"] for candidate in plan["candidates"]}
        self.assertEqual(report["counts"]["candidates"], 2)
        self.assertEqual(rules_by_road["e1"], "through_pair_lane_count_continuity_v2")
        self.assertEqual(rules_by_road["e2"], "short_edge_absorption_lane_count_v2")
        self.assertEqual(report["counts"]["high_confidence_candidates"], 2)

    def test_package_copies_latest_propagation_plan_when_present(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            area_id = "unit"
            processed = root / "data" / "processed"
            preview = root / "data" / "preview"
            reports = root / "reports"
            propagation = root / "data" / "lane_upgrade_system" / "propagation"
            processed.mkdir(parents=True)
            preview.mkdir(parents=True)
            reports.mkdir()
            propagation.mkdir(parents=True)
            (processed / f"{area_id}_lane_graph.json").write_text(json.dumps({
                "lanes": [{"lane_id": "l0", "road_id": "e0"}],
                "junctions": [],
                "continuity_links": [],
            }), encoding="utf-8")
            (preview / f"{area_id}_lane_surfaces_v1.geojson").write_text(json.dumps({"features": []}), encoding="utf-8")
            (preview / f"{area_id}_lane_surfaces_v1.obj").write_text("# obj\n", encoding="utf-8")
            (preview / f"{area_id}_lane_geometry_debug.geojson").write_text(json.dumps({"features": []}), encoding="utf-8")
            (reports / f"{area_id}_pipeline_audit_report.json").write_text(json.dumps({"status": "pass", "metrics": {}}), encoding="utf-8")
            (reports / f"{area_id}_lane_graph_report.json").write_text(json.dumps({"metrics": {}}), encoding="utf-8")
            (reports / f"{area_id}_lane_surface_v1_report.json").write_text(json.dumps({"counts": {}, "metrics": {}}), encoding="utf-8")
            plan_path = propagation / f"{area_id}_lane_upgrade_propagation_plan_v0001.json"
            report_path = reports / f"{area_id}_lane_upgrade_propagation_report.json"
            plan_path.write_text(json.dumps({"candidates": [{"candidate_id": "prop_0000"}]}), encoding="utf-8")
            report_path.write_text(json.dumps({"counts": {"high_confidence_candidates": 1}}), encoding="utf-8")
            (propagation / f"{area_id}_latest.json").write_text(json.dumps({
                "latest_plan": str(plan_path),
                "latest_report": str(report_path),
            }), encoding="utf-8")

            result = build_lane_upgrade_package.build_package(
                area_id=area_id,
                root=root,
                package_version="lane_package_v0001",
            )
            manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))

        self.assertEqual(manifest["contents"]["lane_upgrade_propagation_plan"], "lane_upgrade_propagation_plan.json")
        self.assertEqual(manifest["counts"]["lane_upgrade_propagation_candidates"], 1)
        self.assertEqual(manifest["counts"]["lane_upgrade_propagation_high_confidence"], 1)

    def test_apply_propagation_selects_only_high_confidence_through_pair_by_default(self):
        plan = {
            "candidates": [
                {
                    "candidate_id": "prop_0000",
                    "candidate_road_id": "e1",
                    "rule_id": "through_pair_lane_count_continuity_v2",
                    "status": "candidate_high_confidence",
                    "confidence": 0.84,
                },
                {
                    "candidate_id": "prop_0001",
                    "candidate_road_id": "e2",
                    "rule_id": "same_class_adjacent_approach_review_v2",
                    "status": "candidate_review",
                    "confidence": 0.54,
                },
            ]
        }

        selected = apply_lane_upgrade_propagation.selected_candidates(
            plan,
            candidate_ids=set(),
            allowed_rules=set(apply_lane_upgrade_propagation.DEFAULT_RULES),
            allowed_statuses=set(apply_lane_upgrade_propagation.DEFAULT_STATUSES),
            min_confidence=apply_lane_upgrade_propagation.DEFAULT_MIN_CONFIDENCE,
        )

        self.assertEqual([candidate["candidate_id"] for candidate in selected], ["prop_0000"])

    def test_apply_propagation_short_edge_policy_requires_tiny_same_class_edge(self):
        policy = apply_lane_upgrade_propagation.policy_config("short_edge_absorption_only_v1")
        plan = {
            "candidates": [
                {
                    "candidate_id": "prop_0000",
                    "candidate_road_id": "e1",
                    "rule_id": "short_edge_absorption_lane_count_v2",
                    "status": "candidate_high_confidence",
                    "confidence": 0.76,
                    "candidate_length_m": 8.5,
                    "candidate_road_class": "residential",
                    "source_road_class": "residential",
                },
                {
                    "candidate_id": "prop_0001",
                    "candidate_road_id": "e2",
                    "rule_id": "short_edge_absorption_lane_count_v2",
                    "status": "candidate_high_confidence",
                    "confidence": 0.76,
                    "candidate_length_m": 18.0,
                    "candidate_road_class": "residential",
                    "source_road_class": "residential",
                },
                {
                    "candidate_id": "prop_0002",
                    "candidate_road_id": "e3",
                    "rule_id": "short_edge_absorption_lane_count_v2",
                    "status": "candidate_high_confidence",
                    "confidence": 0.76,
                    "candidate_length_m": 8.5,
                    "candidate_road_class": "service",
                    "source_road_class": "residential",
                },
            ]
        }

        selected = apply_lane_upgrade_propagation.selected_candidates(
            plan,
            candidate_ids=set(),
            allowed_rules=set(policy["rules"]),
            allowed_statuses=set(policy["statuses"]),
            min_confidence=float(policy["min_confidence"]),
            max_candidate_length_m=policy["max_candidate_length_m"],
            require_same_road_class=bool(policy["require_same_road_class"]),
        )

        self.assertEqual([candidate["candidate_id"] for candidate in selected], ["prop_0000"])

    def test_apply_propagation_dry_run_writes_application_without_transactions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            propagation = root / "data" / "lane_upgrade_system" / "propagation"
            propagation.mkdir(parents=True)
            plan_path = propagation / "unit_lane_upgrade_propagation_plan_v0001.json"
            plan_path.write_text(json.dumps({
                "candidates": [
                    {
                        "candidate_id": "prop_0000",
                        "candidate_road_id": "e1",
                        "candidate_canonical_road_id": "cr1",
                        "rule_id": "through_pair_lane_count_continuity_v2",
                        "status": "candidate_high_confidence",
                        "confidence": 0.84,
                        "proposed_target_physical_lane_count": 3,
                    }
                ]
            }), encoding="utf-8")

            result = apply_lane_upgrade_propagation.apply_propagation(
                root=root,
                area_id="unit",
                plan_path=plan_path,
                candidate_ids=set(),
                allowed_rules=set(apply_lane_upgrade_propagation.DEFAULT_RULES),
                allowed_statuses=set(apply_lane_upgrade_propagation.DEFAULT_STATUSES),
                min_confidence=apply_lane_upgrade_propagation.DEFAULT_MIN_CONFIDENCE,
                reviewer="test",
                reason="unit",
                dry_run=True,
                no_rebuild=False,
                with_houdini=False,
            )

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(len(result["selected_candidates"]), 1)
        self.assertFalse((Path(td) / "data" / "processed" / "unit_lane_upgrade_overrides.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
