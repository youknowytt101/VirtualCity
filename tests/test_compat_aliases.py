"""Locks for the root-level compatibility aliases.

These thin ``Scripts/<name>.py`` modules forward to the real implementation via
``sys.modules[__name__] = _impl``. They are NOT dead code: Houdini-injected SOP
source (``_osm_import_canonical.py``) and several active scripts import the bare
names (``import vc_geo``) inside both the local and the Houdini process.

If a forward is silently broken (e.g. turned into a copy or a partial shim), the
injected code could import a wrong/empty module and fail only during a real
recook — a path pytest cannot see. These tests freeze the contract: each alias
must resolve to the *same module object* as its canonical implementation.
"""
import importlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))


# alias module name -> canonical implementation module name
ALIASES = {
    "vc_geo": "shared.vc_geo",
    "vc_paths": "shared.vc_paths",
    "vc_buildings": "shared.vc_buildings",
    "vc_schema": "shared.vc_schema",
    "pipeline_state": "orchestration.pipeline_state",
    "refine_data": "cleaning.refine_data",
    "area_picker": "app.area_picker.server",
}


class TestAliasForwardsToSameObject(unittest.TestCase):
    def test_alias_is_same_module_object_as_impl(self):
        for alias_name, impl_name in ALIASES.items():
            with self.subTest(alias=alias_name):
                alias_mod = importlib.import_module(alias_name)
                impl_mod = importlib.import_module(impl_name)
                self.assertIs(
                    alias_mod, impl_mod,
                    f"{alias_name} must alias {impl_name} (same object), "
                    f"not a copy — Houdini-injected imports depend on this",
                )

    def test_vc_geo_authority_symbols_present(self):
        import vc_geo
        for sym in ("LocalProjector", "local_xz_to_houdini_xz", "signed_area_xz"):
            self.assertTrue(
                hasattr(vc_geo, sym),
                f"vc_geo alias missing {sym} required by injected SOP source",
            )


if __name__ == "__main__":
    unittest.main()