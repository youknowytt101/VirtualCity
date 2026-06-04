"""Offline checks for the LaneForge -> Houdini package boundary."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "ProjectManagement" / "RoadResearch" / "road_test_pipeline"
HOUDINI_BUILD = PIPELINE / "scripts" / "houdini_build_road_test.py"
HOUDINI_OPEN_SESSION = PIPELINE / "scripts" / "houdini_cook_open_session.py"


def test_houdini_cooks_are_manifest_driven():
    for path in (HOUDINI_BUILD, HOUDINI_OPEN_SESSION):
        text = path.read_text(encoding="utf-8")
        assert "resolve_latest_houdini_package" in text
        assert "python_import_standard_lanes" in text
        assert "standard_lanes_path" in text
        assert "standard_junctions_path" in text
        assert "standard_lane_surfaces_path" in text
        assert "OUT_roads_centerlines" in text
        assert "OUT_lane_connections_debug" in text
        assert "OUT_lane_surfaces_v1" in text
        assert 'root / "data" / "processed" / f"{area_id}_lane_graph.json"' not in text
        assert 'root / "data" / "preview" / f"{area_id}_lane_surfaces_v1.geojson"' not in text
        if path == HOUDINI_BUILD:
            assert "physical_lane_centerlines" in text
            assert "micro_seam_absorbed" in text
        else:
            assert "builder.python_lane_debug_code" in text
