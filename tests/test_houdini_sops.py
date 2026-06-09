"""
test_houdini_sops.py — Houdini SOP 文本外置回归测试（离线，不需要 Houdini）
=========================================================================
验证 _recook_new_area.py 依赖的所有外置 SOP 源码文本:
  * 文件存在且可加载
  * 占位符 substitute 后无残留 __TOKEN__
  * Python SOP (.py) 在 substitute 后是合法 Python 源码
  * 关键 sentinel 内容存在，防止误删/截断

运行:
    python -m unittest discover -s tests
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))

import houdini_sops
from houdini_build.context import BuildContext, FULL_REFRESH_CHAIN, QUICK_ROAD_REFRESH_CHAIN
from houdini_build.domains import BUILD_ORDER, domain_summary


class TestSopFilesExist(unittest.TestCase):
    EXPECTED = [
        "dem_import.py",
        "dem_terrain.py",
        "bld_snap.vex",
        "procedural_height.vex",
        "dem_clip.vex",
        "asset_bounds_filter.py",
        "bld_footprint_bevel.py",
        "bld_foundation.py",
        "road_vertical_smoother.py",
        "road_graph_filter.py",
        "road_api_raw_lines.py",
        "road_shared_topology.py",
        "road_centerline_resample.py",
        "road_turn_curve_smooth.py",
        "road_vertex_cleanup.py",
        "road_junction_curve_smooth.py",
        "road_junction_arc_smoother.py",
        "road_topology_builder.py",
        "road_profile_apply.py",
    ]

    def test_all_present(self):
        sop_dir = Path(houdini_sops.__file__).resolve().parent
        for name in self.EXPECTED:
            self.assertTrue((sop_dir / name).exists(), f"missing SOP file: {name}")


class TestPlaceholderSubstitution(unittest.TestCase):
    def test_dem_import_substitutes_root_and_cfg(self):
        code = houdini_sops.load("dem_import.py", ROOT="/proj/VirtualCity", CFG="/proj/VirtualCity/Config/active_area.json")
        self.assertNotIn("__ROOT__", code)
        self.assertNotIn("__CFG__", code)
        self.assertIn("/proj/VirtualCity", code)

    def test_dem_terrain_substitutes(self):
        code = houdini_sops.load("dem_terrain.py", ROOT="/proj/VirtualCity", CFG="/proj/VirtualCity/Config/active_area.json")
        self.assertNotIn("__ROOT__", code)
        self.assertNotIn("__CFG__", code)
        self.assertIn("H-005", code)  # sentinel comment

    def test_dem_clip_substitutes_bounds(self):
        code = houdini_sops.load("dem_clip.vex", XMIN=-100.0, XMAX=200.0, ZMIN=-50.0, ZMAX=150.0)
        for tok in ("__XMIN__", "__XMAX__", "__ZMIN__", "__ZMAX__"):
            self.assertNotIn(tok, code)
        self.assertIn("-100.0", code)
        self.assertIn("i@del", code)

    def test_road_profile_apply_substitutes_root(self):
        code = houdini_sops.load("road_profile_apply.py", ROOT="/proj/VirtualCity")
        self.assertNotIn("__ROOT__", code)
        self.assertIn("/proj/VirtualCity", code)
        self.assertIn("road_profiles.json", code)
        self.assertNotIn("hou.hipFile.path", code)


class TestPythonSopValidity(unittest.TestCase):
    """substitute 后的 Python SOP 必须是合法 Python 源码。"""

    def test_python_sops_parse(self):
        cases = {
            "dem_import.py": dict(ROOT="/proj/VirtualCity", CFG="/proj/VirtualCity/Config/active_area.json"),
            "dem_terrain.py": dict(ROOT="/proj/VirtualCity", CFG="/proj/VirtualCity/Config/active_area.json"),
            "asset_bounds_filter.py": dict(XMIN=-100.0, XMAX=200.0, ZMIN=-50.0, ZMAX=150.0, MODE="component"),
            "bld_footprint_bevel.py": {},
            "bld_foundation.py": {},
            "road_vertical_smoother.py": {},
            "road_graph_filter.py": dict(ROOT="/proj/VirtualCity", CFG="/proj/VirtualCity/Config/active_area.json"),
            "road_api_raw_lines.py": {},
            "road_shared_topology.py": dict(
                ENABLED=1,
                FUSE_TOLERANCE=0.35,
                INTERSECTION_TOLERANCE=0.08,
                MAX_SEGMENTS=2500,
            ),
            "road_centerline_resample.py": dict(
                ENABLED=1,
                TARGET_SPACING=2.0,
                PRESERVE_BEND_DEG=8.0,
            ),
            "road_turn_curve_smooth.py": dict(
                ENABLED=1,
                CURVE_DISTANCE=5.0,
                MIN_BRANCH_DISTANCE=2.0,
                MIN_ANGLE_DEG=25.0,
                MAX_ANGLE_DEG=155.0,
                ARC_SPACING=1.0,
                SMOOTH_ITERATIONS=1,
                MAX_BENDS=2000,
                REUSE_TOLERANCE=0.01,
            ),
            "road_vertex_cleanup.py": dict(
                ENABLED=1,
                TARGET_SPACING=2.0,
                MIN_SPACING=0.75,
                ANCHOR_ANGLE_DEG=20.0,
                REUSE_TOLERANCE=0.05,
            ),
            "road_junction_curve_smooth.py": dict(
                ENABLED=1,
                CURVE_DISTANCE=5.0,
                MIN_BRANCH_DISTANCE=2.0,
                MIN_ANGLE_DEG=25.0,
                MAX_ANGLE_DEG=155.0,
                ARC_SPACING=1.0,
                SMOOTH_ITERATIONS=1,
                MAX_JUNCTIONS=800,
                REUSE_TOLERANCE=0.01,
            ),
            "road_junction_arc_smoother.py": dict(
                ENABLED=1,
                ARC_DISTANCE=6.0,
                ARC_SEGMENTS=5,
                JUNCTION_GRID=1.0,
                MIN_DEGREE=3,
                MAX_BEND=0.32,
                MAX_APPROACH_FRACTION=0.38,
            ),
            "road_topology_builder.py": {},
            "road_profile_apply.py": dict(ROOT="/proj/VirtualCity"),
        }
        for name, subs in cases.items():
            code = houdini_sops.load(name, **subs)
            try:
                ast.parse(code)
            except SyntaxError as exc:
                self.fail(f"{name} is not valid Python after substitution: {exc}")


class TestSentinels(unittest.TestCase):
    def test_vex_sentinels(self):
        self.assertIn("max_terrain_y", houdini_sops.load("bld_snap.vex"))
        self.assertIn("f@height_m", houdini_sops.load("procedural_height.vex"))
        self.assertIn("is_foundation", houdini_sops.load("bld_foundation.py"))
        self.assertIn("footprint_bevel_count", houdini_sops.load("bld_footprint_bevel.py"))
        self.assertIn("asset_bounds_filter_mode", houdini_sops.load(
            "asset_bounds_filter.py",
            XMIN=-100.0, XMAX=200.0, ZMIN=-50.0, ZMAX=150.0, MODE="component"))

    def test_road_topology_builder_skips_degenerate_faces(self):
        text = houdini_sops.load("road_topology_builder.py")
        self.assertIn("rtb_skipped_degenerate_corridors", text)
        self.assertIn("rtb_skipped_degenerate_junction_tris", text)
        self.assertIn("q_area < 0.05 or q_min_edge < 0.05", text)
        self.assertIn("t_angle is not None and t_angle < 2.0", text)

    def test_road_junction_arc_smoother_preserves_centerline_contract(self):
        text = houdini_sops.load(
            "road_junction_arc_smoother.py",
            ENABLED=1,
            ARC_DISTANCE=6.0,
            ARC_SEGMENTS=5,
            JUNCTION_GRID=1.0,
            MIN_DEGREE=3,
            MAX_BEND=0.32,
            MAX_APPROACH_FRACTION=0.38,
        )
        self.assertIn("road_junction_arc_smoothed_roads", text)
        self.assertIn("copy_prim_attrs", text)
        self.assertIn("cubic_bezier", text)
        self.assertIn("shared junction endpoints are preserved exactly", text)

    def test_road_centerline_resample_preserves_raw_source_contract(self):
        text = houdini_sops.load(
            "road_centerline_resample.py",
            ENABLED=1,
            TARGET_SPACING=2.0,
            PRESERVE_BEND_DEG=8.0,
        )
        self.assertIn("road_centerline_resample_status", text)
        self.assertIn("road_centerline_resample_max_segment_after", text)
        self.assertIn("primitive attributes and primitive groups are copied through", text)
        self.assertIn("endpoints are kept exactly", text)
        self.assertIn("shared input points from road_api_shared_topology stay shared", text)
        self.assertIn("shared_input_point_numbers", text)
        self.assertIn("output_point_by_input_number", text)
        self.assertIn("road_centerline_resample_preserved_shared_points", text)
        self.assertIn("road_centerline_resample_reused_shared_points", text)

    def test_road_shared_topology_creates_shared_crossing_points(self):
        text = houdini_sops.load(
            "road_shared_topology.py",
            ENABLED=1,
            FUSE_TOLERANCE=0.35,
            INTERSECTION_TOLERANCE=0.08,
            MAX_SEGMENTS=2500,
        )
        self.assertIn("road_shared_topology_intersections", text)
        self.assertIn("road_shared_topology_endpoint_splits", text)
        self.assertIn("segment_intersection_xz", text)
        self.assertIn("crossing line segments are split", text)

    def test_road_junction_curve_smooth_rewrites_centerline_spans(self):
        text = houdini_sops.load(
            "road_junction_curve_smooth.py",
            ENABLED=1,
            CURVE_DISTANCE=5.0,
            MIN_BRANCH_DISTANCE=2.0,
            MIN_ANGLE_DEG=25.0,
            MAX_ANGLE_DEG=155.0,
            ARC_SPACING=1.0,
            SMOOTH_ITERATIONS=1,
            MAX_JUNCTIONS=800,
            REUSE_TOLERANCE=0.01,
        )
        self.assertIn("road_junction_curve_smooth_status", text)
        self.assertIn("build_tangent_arc", text)
        self.assertIn("project_center_to_equal_radii", text)
        self.assertIn("T junctions keep the nearly straight through road untrimmed", text)
        self.assertIn("road_junction_curve_smooth_t_junctions", text)
        self.assertIn("through_keys", text)
        self.assertIn("forced_insert_distances", text)
        self.assertIn("branch_cut_distance", text)
        self.assertIn("MIN_WALK_DISTANCE", text)
        self.assertIn("T_JUNCTION_SIDE_MAX_ANGLE_DEG", text)
        self.assertIn("original centerline spans near the crossing are trimmed away", text)

    def test_road_turn_curve_smooth_rounds_non_junction_bends(self):
        text = houdini_sops.load(
            "road_turn_curve_smooth.py",
            ENABLED=1,
            CURVE_DISTANCE=5.0,
            MIN_BRANCH_DISTANCE=2.0,
            MIN_ANGLE_DEG=25.0,
            MAX_ANGLE_DEG=155.0,
            ARC_SPACING=1.0,
            SMOOTH_ITERATIONS=1,
            MAX_BENDS=2000,
            REUSE_TOLERANCE=0.01,
        )
        self.assertIn("road_turn_curve_smooth_status", text)
        self.assertIn("build_tangent_arc", text)
        self.assertIn("project_center_to_equal_radii", text)
        self.assertIn("turn_candidate_indices", text)
        self.assertIn("local_turn_angle_deg", text)
        self.assertIn("rotate_closed_chain", text)
        self.assertIn("ring_turn_angle_deg", text)
        self.assertIn("ring_distance_markers", text)
        self.assertIn("cyclic_marker_distance", text)
        self.assertIn("closed_chain_endpoint_match", text)
        self.assertIn("choose_closed_chain_seam_edge", text)
        self.assertIn("cyclic_distance", text)
        self.assertIn("primitive_is_closed", text)
        self.assertIn("rdp_indices", text)
        self.assertIn("point_incident_directions", text)
        self.assertIn("add_unique_direction", text)
        self.assertIn("build_chains", text)
        self.assertIn("mergeable_endpoint", text)
        self.assertIn("endpoint_direction_groups", text)
        self.assertIn("CHAIN_ENDPOINT_TOLERANCE", text)
        self.assertIn("endpoint_cluster_key", text)
        self.assertIn("chain_endpoint_key", text)
        self.assertIn("nearest_boundary_indices", text)
        self.assertIn("shared_point_numbers", text)
        self.assertIn("same_prim_repeated_point_numbers", text)
        self.assertIn("prim_occurrences", text)
        self.assertIn("classify_primitive_topology", text)
        self.assertIn("topology_kind", text)
        self.assertIn("open_chain", text)
        self.assertIn("closed_ring", text)
        self.assertIn("self_touch", text)
        self.assertIn("endpoint_closed", text)
        self.assertIn("is_implicit_primitive_closed", text)
        self.assertIn("protected_self_touch_point_numbers", text)
        self.assertIn("repeated_point_numbers", text)
        self.assertIn("protected_point_numbers", text)
        self.assertIn("topological_shared_point_numbers", text)
        self.assertIn("Valence-two endpoint joins should be chain-merged", text)
        self.assertIn("shared_point_numbers = set(protected_point_numbers)", text)
        self.assertIn("point_number_at_distance", text)
        self.assertIn("output_point_by_input_number", text)
        self.assertIn("road_turn_curve_smooth_protected_endpoint_clusters", text)
        self.assertIn("adjacent_candidate_walk_limit", text)
        self.assertIn("TURN_WINDOW_JOIN_TOLERANCE", text)
        self.assertIn("road_turn_curve_smooth_spacing_limited_bends", text)
        self.assertIn("MIN_TURN_WALK_DISTANCE", text)
        self.assertIn("road_turn_curve_smooth_short_walk_bends", text)
        self.assertIn("is_simple_closed_seam_occurrence", text)
        self.assertIn("road_turn_curve_smooth_closed_loop_seams", text)
        self.assertIn("road_turn_curve_smooth_processed_bends", text)

    def test_road_vertex_cleanup_evenly_resamples_vertices(self):
        text = houdini_sops.load(
            "road_vertex_cleanup.py",
            ENABLED=1,
            TARGET_SPACING=2.0,
            MIN_SPACING=0.75,
            ANCHOR_ANGLE_DEG=20.0,
            REUSE_TOLERANCE=0.05,
        )
        self.assertIn("road_vertex_cleanup_status", text)
        self.assertIn("TARGET_SPACING", text)
        self.assertIn("MIN_SPACING", text)
        self.assertIn("ANCHOR_ANGLE_DEG", text)
        self.assertIn("shared_point_numbers", text)
        self.assertIn("resample_refs", text)
        self.assertIn("road_vertex_cleanup_close_segments_before", text)
        self.assertIn("road_vertex_cleanup_close_segments_after", text)
        self.assertIn("road_vertex_cleanup_reused_shared_points", text)
        self.assertIn("road_vertex_cleanup_reused_spatial_points", text)

class TestOsmImportCanonical(unittest.TestCase):
    """osm_import SOP（Houdini 内运行）已接入 vc_geo，移除内嵌第 4 份 UTM 实现。"""

    PATH = ROOT / "Scripts" / "_osm_import_canonical.py"

    def _substituted(self):
        text = self.PATH.read_text(encoding="utf-8")
        return text.replace("__ROOT__", "/proj/VirtualCity").replace(
            "__CFG__", "/proj/VirtualCity/Config/active_area.json")

    def test_parses_after_substitution(self):
        ast.parse(self._substituted())

    def test_uses_vc_geo_and_drops_inline_utm(self):
        text = self.PATH.read_text(encoding="utf-8")
        self.assertIn("import vc_geo", text)
        self.assertIn("vc_geo.local_to_houdini", text)
        self.assertIn("vc_geo.needs_winding_flip", text)
        # 内嵌 UTM 实现必须已删除
        self.assertNotIn("_utm_forward", text)
        self.assertNotIn("hou.Vector3(x, 0, -z)", text)

    def test_passes_cleaned_road_graph_metadata_to_houdini(self):
        text = self.PATH.read_text(encoding="utf-8")
        for attr in ("seg_id", "from_node", "to_node"):
            self.assertIn(f"'{attr}'", text)
            self.assertIn(f"tags.get('{attr}'", text)


class TestRoadStripsV2(unittest.TestCase):
    PATH = ROOT / "Scripts" / "_road_strips_v2.py"

    def test_parses(self):
        ast.parse(self.PATH.read_text(encoding="utf-8"))

    def test_simplifies_dense_straight_runs_without_dropping_junctions(self):
        text = self.PATH.read_text(encoding="utf-8")
        self.assertIn("def simplify_positions", text)
        self.assertIn("preserve_junction_keys", text)
        self.assertIn("keep_for_junction", text)
        self.assertIn("ROAD_SIMPLIFY_MAX_STEP", text)


class TestRecookRoadChain(unittest.TestCase):
    PATH = ROOT / "Scripts" / "houdini_build" / "recook_new_area.py"
    PREFLIGHT_PATH = ROOT / "Scripts" / "houdini_build" / "preflight.py"
    CONTEXT_PATH = ROOT / "Scripts" / "houdini_build" / "context.py"
    NETWORK_LAYOUT_PATH = ROOT / "Scripts" / "houdini_build" / "network_layout.py"
    TERRAIN_PATH = ROOT / "Scripts" / "houdini_build" / "domains" / "terrain.py"
    BUILDINGS_PATH = ROOT / "Scripts" / "houdini_build" / "domains" / "buildings.py"
    ROADS_PATH = ROOT / "Scripts" / "houdini_build" / "domains" / "roads.py"

    def test_outputs_road_centerlines_without_polyextrude(self):
        text = self.PATH.read_text(encoding="utf-8")
        context = self.CONTEXT_PATH.read_text(encoding="utf-8")
        roads = self.ROADS_PATH.read_text(encoding="utf-8")
        self.assertEqual(BuildContext.from_config({}).road_output_mode, "lines")
        self.assertIn("road_source_chain = roads_domain.build_source_chain", text)
        self.assertIn("_road_mesh_input = road_source_chain.mesh_input", text)
        self.assertIn("road_surface = road_colored", roads)
        self.assertIn("merge.setInput(1, road_surface)", text)
        self.assertIn('houdini_sops.load("road_api_raw_lines.py"', roads)
        self.assertIn('"road_shared_topology.py"', roads)
        self.assertIn('houdini_sops.load(\n        "road_centerline_resample.py"', roads)
        self.assertIn('"road_turn_curve_smooth.py"', roads)
        self.assertIn('"road_vertex_cleanup.py"', roads)
        self.assertIn('"road_junction_curve_smooth.py"', roads)
        self.assertIn("api_raw_node.setInput(0, osm, 0)", roads)
        self.assertIn("\"road_api_shared_topology\"", roads)
        self.assertIn("resample_node.setInput(0, raw_node, 0)", roads)
        self.assertIn("mesh_input=junction_curve_smooth_node", roads)
        self.assertIn("vertex_cleanup_node", roads)
        self.assertIn("road chain locked", roads)
        self.assertIn('"extract_roads"', roads)
        self.assertIn('"snap_roads_to_terrain1"', roads)
        self.assertIn('"road_width_flat"', roads)
        self.assertNotIn("extract_roads = hou.node", roads)
        self.assertNotIn("downstream_node=resample_roads", roads)
        self.assertNotIn('"road_shared_topology"', context)
        self.assertIn('"road_api_raw_lines",', context)
        self.assertIn('"road_api_shared_topology"', context)
        self.assertIn('"road_centerline_resample",', context)
        self.assertIn('"road_turn_curve_smooth"', context)
        self.assertIn('"road_vertex_cleanup"', context)
        self.assertIn('"road_junction_curve_smooth"', context)
        self.assertNotIn("if _road_output_mode == 'surfaces':", text)
        self.assertNotIn("_cfg.get('road_output_mode'", text)
        self.assertNotIn("_cfg.get('road_junction_arc_smoothing_enabled'", text)
        self.assertNotIn("ROAD_GRAPH_FILTER_CODE = houdini_sops.load('road_graph_filter.py'", text)
        self.assertNotIn("net.createNode('polyextrude::2.0', 'road_extrude')", text)
        self.assertNotIn("net.createNode(\"polyextrude::2.0\", \"road_extrude\")", roads)
        self.assertNotIn("road_pre_extrude_fuse = net.createNode", text)
        self.assertNotIn("road_pre_extrude_dissolve = net.createNode", text)

    def test_road_topology_builder_is_not_in_raw_line_main_flow(self):
        text = self.PATH.read_text(encoding="utf-8")
        roads = self.ROADS_PATH.read_text(encoding="utf-8")
        self.assertIn("road chain locked", roads)
        self.assertIn("mesh_input=junction_curve_smooth_node", roads)
        self.assertNotIn("RTB_CODE = houdini_sops.load('road_topology_builder.py')", text)
        self.assertNotIn('RTB_CODE = houdini_sops.load("road_topology_builder.py")', roads)
        self.assertNotIn("rtb_node = hou.node", text)
        self.assertNotIn("_builder_qa_ok", text)
        self.assertNotIn("source_switch = hou.node", text)

    def test_road_profiles_are_enabled_and_in_full_chain(self):
        text = self.PATH.read_text(encoding="utf-8")
        context = self.CONTEXT_PATH.read_text(encoding="utf-8")
        roads = self.ROADS_PATH.read_text(encoding="utf-8")
        self.assertIn('apply_road_profiles=bool(cfg.get("apply_road_profiles", True))', context)
        self.assertIn('houdini_sops.load("road_profile_apply.py", ROOT=root_str)', roads)
        self.assertIn("road_prof.cook(force=True)", roads)
        self.assertIn('"road_profile_apply"', context)

    def test_recook_only_preflights_houdini_ready_data(self):
        text = self.PATH.read_text(encoding="utf-8")
        preflight = self.PREFLIGHT_PATH.read_text(encoding="utf-8")
        self.assertIn("Houdini-ready preflight failed", preflight)
        self.assertIn("check_houdini_ready", text)
        self.assertIn("dcc.ready_outputs_exist", preflight)
        self.assertNotIn("_refine_result", text)
        self.assertNotIn("str(ROOT / 'Scripts' / 'refine_data.py')", text)

    def test_houdini_build_domain_registry_documents_asset_boundaries(self):
        keys = [domain.key for domain in BUILD_ORDER]
        self.assertEqual(keys, ["terrain", "buildings", "roads", "nature", "assembly"])
        self.assertIn("自然 (no-op)", domain_summary())
        deps = {domain.key: domain.depends_on for domain in BUILD_ORDER}
        self.assertEqual(deps["buildings"], ("terrain",))
        self.assertEqual(deps["roads"], ("terrain",))
        self.assertEqual(deps["nature"], ("terrain", "buildings", "roads"))

    def test_houdini_build_context_preserves_current_external_contract(self):
        ctx = BuildContext.from_config({
            "area_id": "area_test",
            "run_id": "run_test",
            "obj_network": "city_gen",
        })
        self.assertEqual(ctx.obj_path, "/obj/city_gen")
        self.assertEqual(ctx.road_output_mode, "lines")
        self.assertTrue(ctx.apply_road_profiles)
        self.assertEqual(ctx.output_refresh_chain(), FULL_REFRESH_CHAIN)

        quick = BuildContext.from_config({
            "area_id": "area_test",
            "run_id": "run_test",
            "dev_quick_roads": True,
        })
        self.assertEqual(quick.output_refresh_chain(), QUICK_ROAD_REFRESH_CHAIN)

    def test_terrain_domain_owns_dem_nodes_and_public_output(self):
        text = self.PATH.read_text(encoding="utf-8")
        terrain = self.TERRAIN_PATH.read_text(encoding="utf-8")
        self.assertIn("terrain_domain.inject_dem_sops", text)
        self.assertIn("terrain_domain.build_snap_target", text)
        self.assertIn("terrain_domain.color_terrain", text)
        self.assertIn('houdini_sops.load("dem_import.py"', terrain)
        self.assertIn('houdini_sops.load("dem_terrain.py"', terrain)
        self.assertIn('net.createNode("subdivide", "dem_subdivide")', terrain)
        self.assertIn('net.createNode("attribwrangle", "terrain_color")', terrain)
        self.assertIn('final_nodes=("dem_subdivide", "terrain_color")', terrain)

    def test_buildings_domain_owns_building_nodes_and_public_outputs(self):
        text = self.PATH.read_text(encoding="utf-8")
        buildings = self.BUILDINGS_PATH.read_text(encoding="utf-8")
        self.assertIn("buildings_domain.patch_footprint_divide_sop", text)
        self.assertIn("buildings_domain.patch_snap_and_height_sops", text)
        self.assertIn("buildings_domain.build_footprint_bevel", text)
        self.assertIn("buildings_domain.clip_buildings", text)
        self.assertIn("buildings_domain.build_foundation", text)
        self.assertIn("buildings_domain.color_and_finalize_buildings", text)
        self.assertIn('houdini_sops.load("bld_snap.vex")', buildings)
        self.assertIn('houdini_sops.load("procedural_height.vex")', buildings)
        self.assertIn('houdini_sops.load("bld_footprint_bevel.py")', buildings)
        self.assertIn('houdini_sops.load("bld_foundation.py")', buildings)
        self.assertIn('return remake_asset_filter("post_normals", "bld_clip_mark", "bld_clipped", "component")', buildings)
        self.assertIn('"bld_foundation_clipped"', buildings)
        self.assertIn('net.createNode("normal", "bld_with_foundation")', buildings)
        self.assertIn('final_nodes=("bld_clipped", "bld_with_foundation")', buildings)

    def test_roads_domain_owns_road_nodes_and_public_outputs(self):
        text = self.PATH.read_text(encoding="utf-8")
        roads = self.ROADS_PATH.read_text(encoding="utf-8")
        self.assertIn("roads_domain.build_source_chain", text)
        self.assertIn("roads_domain.build_clipped_lines", text)
        self.assertIn("roads_domain.apply_profiles", text)
        self.assertIn("roads_domain.apply_curb_variation", text)
        self.assertIn("roads_domain.color_roads", text)
        self.assertIn("roads_domain.finalize_surface", text)
        self.assertIn('houdini_sops.load("road_api_raw_lines.py")', roads)
        self.assertIn('"road_shared_topology.py"', roads)
        self.assertIn('"road_centerline_resample.py"', roads)
        self.assertIn('"road_turn_curve_smooth.py"', roads)
        self.assertIn('"road_vertex_cleanup.py"', roads)
        self.assertIn('"road_junction_curve_smooth.py"', roads)
        self.assertIn('houdini_sops.load("road_profile_apply.py", ROOT=root_str)', roads)
        self.assertIn('houdini_sops.load("road_curb_variation.py", ROOT=root_str)', roads)
        self.assertNotIn('houdini_sops.load("road_fragment_cleanup.py")', roads)
        self.assertNotIn('net.createNode("attribwrangle", "snap_roads_to_terrain1")', roads)
        self.assertNotIn('houdini_sops.load("road_vertical_smoother.py")', roads)
        self.assertIn('net.createNode("python", "road_api_raw_lines")', roads)
        self.assertIn('net.createNode("python", node_name)', roads)
        self.assertIn('net.createNode("python", "road_centerline_resample")', roads)
        self.assertIn('net.createNode("python", "road_turn_curve_smooth")', roads)
        self.assertIn('net.createNode("python", "road_vertex_cleanup")', roads)
        self.assertIn('net.createNode("python", "road_junction_curve_smooth")', roads)
        self.assertIn('net.createNode("attribwrangle", "snap_road_strips")', roads)
        self.assertIn('net.createNode("python", "road_bbox_clip")', roads)
        self.assertIn('net.createNode("attribwrangle", "snap_road_clipped")', roads)
        self.assertNotIn('net.createNode("python", "road_fragment_cleanup")', roads)
        self.assertIn('net.createNode("attribwrangle", "road_color")', roads)
        self.assertIn('final_nodes=("road_clipped", "road_color")', roads)

    def test_network_layout_groups_domain_nodes_visually_only(self):
        text = self.PATH.read_text(encoding="utf-8")
        layout = self.NETWORK_LAYOUT_PATH.read_text(encoding="utf-8")
        self.assertIn("from houdini_build.network_layout import apply_domain_network_layout", text)
        self.assertIn("apply_domain_network_layout(hou, net, OBJ_PATH)", text)
        self.assertIn("[WARN] Houdini 网络分组失败", text)
        self.assertIn('"[VC] 地形 Terrain"', layout)
        self.assertIn('"[VC] 建筑 Buildings"', layout)
        self.assertIn('"[VC] 道路 Roads"', layout)
        self.assertIn('"[VC] 总装 Assembly"', layout)
        self.assertIn('"dem_subdivide"', layout)
        self.assertIn('"bld_with_foundation"', layout)
        self.assertNotIn('"road_shared_topology"', layout)
        self.assertNotIn('"extract_roads"', layout)
        self.assertNotIn('"resample_roads"', layout)
        self.assertNotIn('"snap_roads_to_terrain1"', layout)
        self.assertNotIn('"road_width_flat"', layout)
        self.assertIn('"road_api_raw_lines"', layout)
        self.assertIn('"road_api_shared_topology"', layout)
        self.assertIn('"road_centerline_resample"', layout)
        self.assertIn('"road_turn_curve_smooth"', layout)
        self.assertIn('"road_vertex_cleanup"', layout)
        self.assertIn('"road_junction_curve_smooth"', layout)
        self.assertNotIn('"road_fragment_cleanup"', layout)
        self.assertIn('"road_color"', layout)
        self.assertIn('"merge_all"', layout)
        self.assertIn('"OUT_city"', layout)
        self.assertNotIn('"laneforge_lane_surfaces"', layout)
        self.assertNotIn('"UnrealEngine_lane_surfaces"', layout)
        self.assertIn("'laneforge_lane_surfaces'", text)
        self.assertIn("'UnrealEngine_lane_surfaces'", text)
        self.assertIn("net.createNetworkBox()", layout)
        self.assertIn("box.fitAroundContents()", layout)
        self.assertIn("BOX_PAD_X", layout)
        self.assertIn("COLUMN_SPACING", layout)
        self.assertIn("box.setBounds", layout)

    def test_legacy_recook_wrapper_points_to_houdini_build_layer(self):
        text = (ROOT / "Scripts" / "_recook_new_area.py").read_text(encoding="utf-8")
        self.assertIn('SCRIPTS / "houdini_build" / "recook_new_area.py"', text)
        self.assertIn("runpy.run_path", text)


class TestModelQaRoadChain(unittest.TestCase):
    PATH = ROOT / "Scripts" / "houdini_model_qa.py"

    def test_required_nodes_match_flat_road_chain(self):
        text = self.PATH.read_text(encoding="utf-8")
        self.assertIn('"road_api_raw_lines"', text)
        self.assertIn('"road_api_shared_topology"', text)
        self.assertIn('"road_centerline_resample"', text)
        self.assertIn('"road_vertex_cleanup"', text)
        self.assertIn('"road_junction_curve_smooth"', text)
        self.assertIn('"road_color"', text)
        self.assertIn('"road_clipped_lines"', text)
        self.assertNotIn('"road_extrude"', text)

    def test_qa_checks_road_profile_attributes(self):
        text = self.PATH.read_text(encoding="utf-8")
        self.assertIn("def check_road_profile_attrs", text)
        self.assertIn('"road_profile_applied_prims"', text)
        self.assertIn("self.check_road_profile_attrs()", text)


class TestExportAndImportChain(unittest.TestCase):
    PATH = ROOT / "Scripts" / "export_and_import.py"

    def test_export_uses_final_cooked_nodes_before_fallbacks(self):
        text = self.PATH.read_text(encoding="utf-8")
        self.assertIn("pipeline_status.export_gate", text)
        self.assertIn("select_sop_path", text)
        self.assertIn("[f'{_OBJ}/bld_with_foundation', f'{_OBJ}/bld_clipped', f'{_OBJ}/post_normals']", text)
        removed_lane_surface_node = "lane" + "forge_lane_surfaces"
        self.assertNotIn(removed_lane_surface_node, text)
        self.assertIn("f'{_OBJ}/road_centerline_resample'", text)
        self.assertIn("f'{_OBJ}/road_vertex_cleanup'", text)
        self.assertIn("f'{_OBJ}/road_junction_curve_smooth'", text)
        self.assertIn("f'{_OBJ}/road_api_shared_topology'", text)
        self.assertIn("f'{_OBJ}/road_api_raw_lines'", text)
        self.assertNotIn("f'{_OBJ}/road_junction_arc_smoother'", text)
        self.assertNotIn("f'{_OBJ}/road_strips'", text)
        self.assertIn("[f'{_OBJ}/terrain_color', f'{_OBJ}/dem_subdivide', f'{_OBJ}/dem_terrain']", text)
        self.assertIn("prims = geo.intrinsicValue('primitivecount')", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
