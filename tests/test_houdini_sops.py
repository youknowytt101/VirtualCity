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
        "bld_footprint_bevel.py",
        "bld_foundation.py",
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


class TestPythonSopValidity(unittest.TestCase):
    """substitute 后的 Python SOP 必须是合法 Python 源码。"""

    def test_python_sops_parse(self):
        cases = {
            "dem_import.py": dict(ROOT="/proj/VirtualCity", CFG="/proj/VirtualCity/Config/active_area.json"),
            "dem_terrain.py": dict(ROOT="/proj/VirtualCity", CFG="/proj/VirtualCity/Config/active_area.json"),
            "bld_footprint_bevel.py": {},
            "bld_foundation.py": {},
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
