"""Offline tests for raw clip cache discovery and parent-cache restore."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))

import data_cleaning_cache as dcc
import vc_geo


def _write_clip_cache(base: Path, key: str, bbox: list[float], *, signature: dict) -> None:
    item = base / key
    item.mkdir(parents=True)
    for name in dcc.OUTPUT_NAMES.values():
        (item / name).write_text("stub", encoding="utf-8")
    (item / "_manifest.json").write_text(json.dumps({
        "schema": dcc.CACHE_SCHEMA_VERSION,
        "key": key,
        "bbox": bbox,
        "origin_lon": (bbox[0] + bbox[2]) / 2,
        "origin_lat": (bbox[1] + bbox[3]) / 2,
        "dem_source": "unit",
        "source_signature": signature,
    }), encoding="utf-8")


class TestCoveringClipCache(unittest.TestCase):
    def test_finds_smallest_valid_covering_cache(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "_clip_cache"
            signature = dcc.CURRENT_ACQUISITION_PROFILE
            _write_clip_cache(root, "large", [100.80, 12.80, 100.95, 12.99], signature=signature)
            _write_clip_cache(root, "small", [100.84, 12.88, 100.90, 12.95], signature=signature)

            with patch.object(dcc, "CLIP_CACHE_DIR", root):
                found = dcc.find_covering_clip_cache(
                    [100.86, 12.90, 100.88, 12.92],
                    source_signature=signature,
                )

        self.assertIsNotNone(found)
        self.assertEqual(found["key"], "small")

    def test_source_signature_must_match(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "_clip_cache"
            _write_clip_cache(root, "wrong_profile", [100.80, 12.80, 100.95, 12.99],
                              signature={"profile": "old"})

            with patch.object(dcc, "CLIP_CACHE_DIR", root):
                found = dcc.find_covering_clip_cache(
                    [100.86, 12.90, 100.88, 12.92],
                    source_signature=dcc.CURRENT_ACQUISITION_PROFILE,
                )

        self.assertIsNone(found)


class TestParentClipRestore(unittest.TestCase):
    def test_restores_child_bbox_from_larger_clip_cache(self):
        try:
            import shapely  # noqa: F401
        except ImportError:
            self.skipTest("shapely is required for building-cache filtering")

        parent_bbox = [100.843163, 12.888621, 100.937748, 12.98114]
        child_bbox = [100.860672, 12.914891, 100.875864, 12.930535]
        parent_lon = (parent_bbox[0] + parent_bbox[2]) / 2
        parent_lat = (parent_bbox[1] + parent_bbox[3]) / 2
        parent_proj = vc_geo.LocalProjector(parent_lon, parent_lat)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cache_root = root / "_clip_cache"
            key = "bbox_parent"
            cache_dir = cache_root / key
            cache_dir.mkdir(parents=True)
            (cache_dir / "_manifest.json").write_text(json.dumps({
                "schema": dcc.CACHE_SCHEMA_VERSION,
                "key": key,
                "bbox": dcc.normalize_bbox(parent_bbox),
                "origin_lon": parent_lon,
                "origin_lat": parent_lat,
                "dem_source": "unit",
                "source_signature": dcc.CURRENT_ACQUISITION_PROFILE,
            }), encoding="utf-8")
            (cache_dir / "roads.osm").write_text("""<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6">
  <node id="1" lat="12.920000" lon="100.866000" />
  <node id="2" lat="12.921000" lon="100.867000" />
  <way id="10"><nd ref="1" /><nd ref="2" /><tag k="highway" v="residential" /></way>
  <node id="3" lat="12.970000" lon="100.930000" />
  <node id="4" lat="12.971000" lon="100.931000" />
  <way id="20"><nd ref="3" /><nd ref="4" /><tag k="highway" v="residential" /></way>
</osm>
""", encoding="utf-8")
            (cache_dir / "buildings.geojson").write_text(json.dumps({
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"id": "inside"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[100.866, 12.920], [100.867, 12.920],
                                             [100.867, 12.921], [100.866, 12.921],
                                             [100.866, 12.920]]],
                        },
                    },
                    {
                        "type": "Feature",
                        "properties": {"id": "outside"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[100.930, 12.970], [100.931, 12.970],
                                             [100.931, 12.971], [100.930, 12.971],
                                             [100.930, 12.970]]],
                        },
                    },
                ],
            }), encoding="utf-8")
            with open(cache_dir / "dem.csv", "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["x", "y", "z", "row", "col"])
                for row, (lon, lat, elev) in enumerate((
                        (100.866, 12.920, 5.0),
                        (100.867, 12.921, 6.0),
                        (100.930, 12.970, 9.0),
                )):
                    x, north = parent_proj.to_local(lon, lat)
                    writer.writerow([f"{x:.2f}", f"{elev:.2f}", f"{-north:.2f}", row, 0])

            out = root / "out"
            outputs = {
                "roads": out / "roads.osm",
                "buildings": out / "buildings.geojson",
                "dem": out / "dem.csv",
            }
            with patch.object(dcc, "CLIP_CACHE_DIR", cache_root):
                restored = dcc.restore_clip_cache(
                    child_bbox,
                    outputs,
                    source_signature=dcc.CURRENT_ACQUISITION_PROFILE,
                )

            self.assertIsNotNone(restored)
            self.assertEqual(restored["restore_mode"], "parent_clip")
            self.assertEqual(restored["restored_bbox"], dcc.normalize_bbox(child_bbox))
            self.assertIn('way id="10"', outputs["roads"].read_text(encoding="utf-8"))
            self.assertNotIn('way id="20"', outputs["roads"].read_text(encoding="utf-8"))
            buildings = json.loads(outputs["buildings"].read_text(encoding="utf-8"))
            self.assertEqual([f["properties"]["id"] for f in buildings["features"]], ["inside"])
            with open(outputs["dem"], encoding="utf-8", newline="") as f:
                dem_rows = list(csv.DictReader(f))
            self.assertEqual(len(dem_rows), 2)
            self.assertEqual({int(r["row"]) for r in dem_rows}, {0, 1})


if __name__ == "__main__":
    unittest.main(verbosity=2)
