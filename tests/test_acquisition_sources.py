"""Offline locks for the declarative acquisition source registry.

These tests freeze the cache-fingerprint contract: the serialized profile must
stay byte-identical so existing clip/clean caches keep validating. They also
assert the registry stays the single source of truth (cache profile + UI
metadata derive from it, with matching labels).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))

import data_cleaning_cache as dcc
from acquisition import sources


# Historical CURRENT_ACQUISITION_PROFILE serialized via stable_json (sort_keys).
# Changing this constant is a deliberate full-cache-invalidation event.
FROZEN_PROFILE_JSON = (
    '{"buildings":"tile_cache_overture_else_overture_api_v1",'
    '"dem":"fabdem_else_tile_cache_else_nasadem_v1",'
    '"roads":"tile_cache_osm_else_overpass_v1",'
    '"schema":1}'
)


class TestProfileFingerprintFrozen(unittest.TestCase):
    def test_derived_profile_matches_frozen_bytes(self):
        self.assertEqual(
            dcc.stable_json(dcc.CURRENT_ACQUISITION_PROFILE),
            FROZEN_PROFILE_JSON,
        )

    def test_registry_and_cache_module_agree(self):
        self.assertEqual(
            dcc.CURRENT_ACQUISITION_PROFILE,
            sources.acquisition_profile(),
        )

    def test_profile_has_exact_keys(self):
        self.assertEqual(
            set(dcc.CURRENT_ACQUISITION_PROFILE),
            {"schema", "roads", "buildings", "dem"},
        )


class TestRegistryIsSingleSourceOfTruth(unittest.TestCase):
    def test_display_strategy_mirrors_profile_label(self):
        by_key = {spec.key: spec for spec in sources.SOURCES.values()}
        for item in sources.display_items():
            self.assertEqual(item["strategy"], by_key[item["key"]].profile)

    def test_display_items_cover_all_sources(self):
        self.assertEqual(
            [item["key"] for item in sources.display_items()],
            list(sources.SOURCES.keys()),
        )

    def test_profile_labels_unchanged(self):
        self.assertEqual(sources.SOURCES["roads"].profile,
                         "tile_cache_osm_else_overpass_v1")
        self.assertEqual(sources.SOURCES["buildings"].profile,
                         "tile_cache_overture_else_overture_api_v1")
        self.assertEqual(sources.SOURCES["dem"].profile,
                         "fabdem_else_tile_cache_else_nasadem_v1")


if __name__ == "__main__":
    unittest.main()