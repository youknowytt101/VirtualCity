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
    PATH = ROOT / "Scripts" / "_recook_new_area.py"

    def test_outputs_flat_road_surface_without_polyextrude(self):
        text = self.PATH.read_text(encoding="utf-8")
        self.assertIn("road_surface = road_colored", text)
        self.assertIn("merge.setInput(1, road_surface)", text)
        self.assertIn("houdini_sops.load('road_graph_filter.py'", text)
        self.assertIn("_rs_node.setInput(0, _road_mesh_input, 0)", text)
        self.assertIn("rtb_node.setInput(0, _road_mesh_input, 0)", text)
        self.assertIn("'road_graph_filter'", text)
        self.assertNotIn("net.createNode('polyextrude::2.0', 'road_extrude')", text)
        self.assertNotIn("road_pre_extrude_fuse = net.createNode", text)
        self.assertNotIn("road_pre_extrude_dissolve = net.createNode", text)

    def test_road_topology_builder_keeps_qa_guarded_auto_mode(self):
        text = self.PATH.read_text(encoding="utf-8")
        self.assertIn("_cfg.get('roads_topology_preferred', 'strips')", text)
        self.assertIn("_roads_topology_max_prim_ratio", text)
        self.assertIn("_roads_topology_qa_sample_prims", text)
        self.assertIn("_builder_qa_ok", text)
        self.assertIn("_pref_mode == 'auto'", text)
        self.assertIn("selected={}", text)

    def test_road_profiles_are_enabled_and_in_full_chain(self):
        text = self.PATH.read_text(encoding="utf-8")
        self.assertIn("_cfg.get('apply_road_profiles', True)", text)
        self.assertIn("houdini_sops.load('road_profile_apply.py', ROOT=ROOT_STR)", text)
        self.assertIn("road_prof.cook(force=True)", text)
        self.assertIn("'road_profile_apply'", text)


class TestModelQaRoadChain(unittest.TestCase):
    PATH = ROOT / "Scripts" / "houdini_model_qa.py"

    def test_required_nodes_match_flat_road_chain(self):
        text = self.PATH.read_text(encoding="utf-8")
        self.assertIn('"road_graph_filter"', text)
        self.assertIn('"road_color"', text)
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
        self.assertIn("f'{_OBJ}/road_strips'", text)
        self.assertIn("[f'{_OBJ}/terrain_color', f'{_OBJ}/dem_subdivide', f'{_OBJ}/dem_terrain']", text)
        self.assertIn("prims = geo.intrinsicValue('primitivecount')", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
