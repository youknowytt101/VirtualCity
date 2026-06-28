import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "Scripts"))

import download_overture_buildings as dob


class _FakeBatch:
    def to_pydict(self):
        return {
            "geometry": [b"wkb"],
            "height": [12],
            "num_floors": [None],
            "subtype": ["residential"],
            "class": [None],
        }


class _FlakyReader:
    def __init__(self):
        self.calls = []

    def record_batch_reader(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if len(self.calls) == 1:
            raise OSError("transient parquet read failure")
        return [_FakeBatch()]


class TestOvertureBuildingFetch(unittest.TestCase):
    def test_uses_stac_timeouts_and_retries_transient_reader_failure(self):
        fake_overture = _FlakyReader()
        fake_shapely = types.SimpleNamespace(from_wkb=lambda _data: object())
        fake_geometry = types.SimpleNamespace(mapping=lambda _geom: {"type": "Polygon", "coordinates": []})

        with patch.dict(sys.modules, {
            "overturemaps": fake_overture,
            "shapely": fake_shapely,
            "shapely.geometry": fake_geometry,
        }):
            features = dob._fetch_overture((103.84, 1.28, 103.85, 1.29))

        self.assertEqual(len(features), 1)
        self.assertEqual(len(fake_overture.calls), 2)
        args, kwargs = fake_overture.calls[-1]
        self.assertEqual(args, ("building",))
        self.assertEqual(kwargs["bbox"], (103.84, 1.28, 103.85, 1.29))
        self.assertIs(kwargs["stac"], True)
        self.assertGreaterEqual(kwargs["connect_timeout"], 10)
        self.assertGreaterEqual(kwargs["request_timeout"], 60)


if __name__ == "__main__":
    unittest.main()
