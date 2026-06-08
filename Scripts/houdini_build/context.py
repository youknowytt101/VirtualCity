"""Shared build context for Houdini recook orchestration."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.vc_paths import ACTIVE_AREA, HIP as MASTER_HIP, HOUDINI, ROOT, load_active_area


VALID_ROAD_SOURCE_MODES = ("auto", "legacy_debug", "strips", "builder", "topology", "rtb")
DEFAULT_COLORS = {
    "roads": (1.00, 1.00, 1.00),
    "buildings": (0.55, 0.55, 0.55),
    "terrain": (0.25, 0.25, 0.25),
}

FULL_REFRESH_CHAIN = [
    "osm_import", "dem_terrain", "dem_cut_and_fill", "dem_subdivide",
    "extract_buildings", "snap_bld_to_terrain", "bld_footprint_bevel", "extrude_buildings", "post_normals",
    "road_api_raw_lines", "road_api_shared_topology", "road_centerline_resample", "road_junction_curve_smooth",
    "snap_road_strips", "road_bbox_clip", "snap_road_clipped",
    "bld_clipped", "bld_foundation", "bld_foundation_clipped",
    "road_clipped", "road_profile_apply", "road_curb_variation", "road_color",
    "bld_color", "bld_foundation_color", "bld_with_foundation_merge", "bld_with_foundation",
    "terrain_color", "merge_all", "OUT_city",
]

QUICK_ROAD_REFRESH_CHAIN = [
    "road_api_raw_lines", "road_api_shared_topology", "road_centerline_resample", "road_junction_curve_smooth",
    "snap_road_strips", "road_bbox_clip", "snap_road_clipped",
    "road_clipped", "road_profile_apply", "road_curb_variation", "road_color", "OUT_city",
]


def _road_source_mode(cfg: dict[str, Any]) -> str:
    preferred = str(cfg.get("roads_topology_preferred", "strips")).lower().strip()
    mode = str(cfg.get("road_source_mode", preferred)).lower().strip()
    return mode if mode in VALID_ROAD_SOURCE_MODES else "auto"


@dataclass(frozen=True)
class BuildContext:
    """Immutable config snapshot for one Houdini recook run."""
    cfg: dict[str, Any]
    area_id: str
    run_id: str
    obj_net: str
    roads_cut_fill_enabled: bool
    dev_quick_roads: bool
    roads_topology_preferred: str
    road_source_mode: str
    qa_autorevert_topology_builder: bool
    junction_min_angle_deg: float
    sliver_edge_min_m: float
    roads_topology_max_prim_ratio: float
    roads_topology_qa_sample_prims: int
    road_output_mode: str = "lines"
    apply_road_profiles: bool = True
    apply_curb_variation: bool = True
    road_centerline_resample_enabled: bool = True
    road_centerline_resample_spacing_m: float = 2.0
    road_centerline_resample_preserve_bend_deg: float = 8.0
    road_shared_topology_enabled: bool = True
    road_shared_topology_fuse_tolerance_m: float = 0.35
    road_shared_topology_intersection_tolerance_m: float = 0.08
    road_shared_topology_max_segments: int = 2500
    road_junction_curve_smooth_enabled: bool = True
    road_junction_curve_smooth_distance_m: float = 5.0
    road_junction_curve_smooth_min_branch_distance_m: float = 2.0
    road_junction_curve_smooth_min_angle_deg: float = 25.0
    road_junction_curve_smooth_max_angle_deg: float = 155.0
    road_junction_curve_smooth_arc_spacing_m: float = 1.0
    road_junction_curve_smooth_iterations: int = 1
    road_junction_curve_smooth_max_junctions: int = 800
    colors: dict[str, tuple[float, float, float]] = field(default_factory=lambda: dict(DEFAULT_COLORS))

    @classmethod
    def from_active_area(cls) -> "BuildContext":
        return cls.from_config(load_active_area())

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "BuildContext":
        cfg = dict(cfg)
        preferred = str(cfg.get("roads_topology_preferred", "strips")).lower().strip()
        return cls(
            cfg=cfg,
            area_id=str(cfg.get("area_id", "")),
            run_id=str(cfg.get("run_id", "")),
            obj_net=str(cfg.get("obj_network", "city_gen")),
            roads_cut_fill_enabled=bool(cfg.get("roads_cut_fill_enabled", False)),
            dev_quick_roads=bool(cfg.get("dev_quick_roads", False)),
            roads_topology_preferred=preferred,
            road_source_mode=_road_source_mode(cfg),
            qa_autorevert_topology_builder=bool(cfg.get("qa_autorevert_topology_builder", True)),
            junction_min_angle_deg=float(cfg.get("junction_min_angle_deg", 2.0)),
            sliver_edge_min_m=float(cfg.get("sliver_edge_min_m", 0.01)),
            roads_topology_max_prim_ratio=float(cfg.get("roads_topology_max_prim_ratio", 5.0)),
            roads_topology_qa_sample_prims=int(cfg.get("roads_topology_qa_sample_prims", 500)),
            apply_road_profiles=bool(cfg.get("apply_road_profiles", True)),
            apply_curb_variation=bool(cfg.get("apply_curb_variation", True)),
            road_centerline_resample_enabled=bool(cfg.get("road_centerline_resample_enabled", True)),
            road_centerline_resample_spacing_m=float(cfg.get("road_centerline_resample_spacing_m", 2.0)),
            road_centerline_resample_preserve_bend_deg=float(
                cfg.get("road_centerline_resample_preserve_bend_deg", 8.0)
            ),
            road_shared_topology_enabled=bool(cfg.get("road_shared_topology_enabled", True)),
            road_shared_topology_fuse_tolerance_m=float(cfg.get("road_shared_topology_fuse_tolerance_m", 0.35)),
            road_shared_topology_intersection_tolerance_m=float(
                cfg.get("road_shared_topology_intersection_tolerance_m", 0.08)
            ),
            road_shared_topology_max_segments=int(cfg.get("road_shared_topology_max_segments", 2500)),
            road_junction_curve_smooth_enabled=bool(cfg.get("road_junction_curve_smooth_enabled", True)),
            road_junction_curve_smooth_distance_m=float(cfg.get("road_junction_curve_smooth_distance_m", 5.0)),
            road_junction_curve_smooth_min_branch_distance_m=float(
                cfg.get("road_junction_curve_smooth_min_branch_distance_m", 2.0)
            ),
            road_junction_curve_smooth_min_angle_deg=float(
                cfg.get("road_junction_curve_smooth_min_angle_deg", 25.0)
            ),
            road_junction_curve_smooth_max_angle_deg=float(
                cfg.get("road_junction_curve_smooth_max_angle_deg", 155.0)
            ),
            road_junction_curve_smooth_arc_spacing_m=float(
                cfg.get("road_junction_curve_smooth_arc_spacing_m", 1.0)
            ),
            road_junction_curve_smooth_iterations=int(cfg.get("road_junction_curve_smooth_iterations", 1)),
            road_junction_curve_smooth_max_junctions=int(cfg.get("road_junction_curve_smooth_max_junctions", 800)),
        )

    @property
    def obj_path(self) -> str:
        return f"/obj/{self.obj_net}"

    @property
    def root_str(self) -> str:
        return ROOT.as_posix()

    @property
    def cfg_file(self) -> str:
        return ACTIVE_AREA.as_posix()

    @property
    def hip_path(self) -> str:
        return MASTER_HIP.as_posix()

    @property
    def archive_hip_path(self) -> str:
        return (HOUDINI / "Hip" / f"VC_{self.area_id}_citygen_v001.hip").as_posix()

    def output_refresh_chain(self) -> list[str]:
        return list(QUICK_ROAD_REFRESH_CHAIN if self.dev_quick_roads else FULL_REFRESH_CHAIN)
