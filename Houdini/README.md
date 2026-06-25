# Houdini

> 本目录存放 VirtualCity 的 Houdini master hip、区域 hip、HDA 预留和导出资产。
> 当前阶段的核心工作在 Houdini：道路、建筑、地形和 Model QA 的快速质量迭代。

---

## 当前状态

当前 master hip：

```text
Houdini/Hip/VC_master_citygen_v001.hip
```

最新运行区实验快照 hip：

```text
Houdini/Hip/VC_z47n_e702000_n1428000_w1000_h1000_s1000_citygen_v001.hip
```

最新 Model QA quick 为 `fail`：`building_terrain_fit` 与 `road_terrain_fit`
仍需检查，当前输出不能直接晋级为基准。

当前主要输出节点：

```text
/obj/pattaya_osm/OUT_city
```

注意：脚本默认目标正在向 `city_gen` 迁移，但当前历史 hip 内仍保留 `pattaya_osm` 网络名，自动化脚本会兼容该旧名。

---

## 当前 Houdini 主链路

```text
osm_import
    ↓
extract_buildings / road_api_raw_lines
    ↓
建筑链：snap_bld_to_terrain → bld_footprint_bevel → extrude_buildings → bld_with_foundation
    ↓
道路中线链：road_api_shared_topology → road_centerline_resample → road_turn_curve_smooth
    ↓
road_vertex_cleanup → road_junction_curve_smooth → road_clipped → road_profile_apply
    ↓
道路面链：road_capsule_surface_preview → road_surface_color
    ↓
merge_all（bld_with_foundation + road_surface_color + terrain_color）
    ↓
OUT_city
```

---

## 近期重点设计

### 地形

- `dem_terrain` 从 DEM CSV 构建规则格网。
- `dem_subdivide` 使用 Bilinear iterations=2，加密为道路和建筑吸附目标。
- 加密改善视觉和贴地稳定性，但不增加真实 DEM 精度。

### 道路

- `road_api_raw_lines → road_api_shared_topology → road_centerline_resample → road_turn_curve_smooth → road_vertex_cleanup → road_junction_curve_smooth` 是当前稳定道路中线链。
- `road_clipped → road_profile_apply` 给裁剪后的干净中线注入车道、路缘和人行道属性。
- `road_capsule_surface_preview` 从中线生成固定宽度胶囊车道面；面片左右分开，中间有真实中心边，两端为半圆 cap。
- `road_surface_color` 是当前道路面主输出，并接入 `merge_all / OUT_city`；`road_color` 仅保留为中线 debug，不进入最终总装。
- `road_surface_union_preview` / `road_surface_quad_preview` 已从主流程移除，自动构建会清理旧节点。
- `road_faces` QA 现在检查 `road_surface_color` 的闭合面片、自交、顶点数、长宽比和异常面积；`road_clipped_lines` 检查裁剪后的道路中线是否非空。

### 建筑

- `snap_bld_to_terrain` 用逐顶点 MAX 地形高度，优先保证建筑不被坡地埋没。
- `bld_footprint_bevel` 对建筑 footprint 外角倒角；当前角度阈值为 `<=100°`，带 `2°` 容差。
- `bld_foundation` 从最终建筑 body 底边生成裙边，解决坡地下坡侧悬空。
- `bld_with_foundation` 合并 body 与 foundation，并保留 `is_foundation` 标签供 QA 检查。

---

## Model QA

Houdini 构建完成后自动运行：

```bash
cd Scripts
uv run python houdini_model_qa.py --mode quick
```

报告目录：

```text
Reports/model_qa/
```

完成标准：

- `Reports/model_qa/latest.json` 已写入且无 `fail`；`warn` 代表流程完成但需要人工审核后才能晋级为基准。
- `Config/houdini_build_status.json` 中同一区域 `status=completed`

Model QA 是自动回归护栏，不替代人工视口审核。人工审核仍需查看：

- 道路是否贴地、连续、无异常大面片。
- 建筑是否不埋地、不明显悬空。
- 裙边是否不错位、不反色。
- 倒角是否只出现在合理外角。
- 俯视角城市关系是否可信。

---

## 推荐目录结构

```text
Houdini/
├── Hip/          ← master hip 与区域 hip
├── HDA/          ← 后续 .hda / .hdalc 数字资产
├── Export/       ← FBX / OBJ / Alembic / Heightmap / JSON 输出
└── PDG_Output/   ← 后续 TOPs / PDG 批处理输出
```

---

## 导出原则

当前默认流程不自动进入 UE5。只有 Houdini 视口审核通过后，再运行：

```bash
cd Scripts
uv run python export_and_import.py
```

导出到 UE5 时仍遵守单位规则：

```text
Houdini: 1 unit = 1 meter
UE5: 1 Unreal unit = 1 centimeter
FBX ROP: convertunits = 1
```
