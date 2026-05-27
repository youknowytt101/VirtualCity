# Houdini

> 本目录存放 VirtualCity 的 Houdini master hip、区域 hip、HDA 预留和导出资产。
> 当前阶段的核心工作在 Houdini：道路、建筑、地形和 Model QA 的快速质量迭代。

---

## 当前状态

当前 master hip：

```text
Houdini/Hip/VC_master_citygen_v001.hip
```

最新通过全流程测试的区域 hip：

```text
Houdini/Hip/VC_area_12.918_100.865_citygen_v001.hip
```

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
extract_buildings / extract_roads
    ↓
snap_bld_to_terrain / snap_roads_to_terrain1
    ↓
bld_footprint_bevel / road_width_flat
    ↓
extrude_buildings / road_strips
    ↓
post_normals / snap_road_strips
    ↓
bld_clipped / road_clipped
    ↓
bld_foundation / road_extrude
    ↓
bld_with_foundation / terrain_color
    ↓
merge_all
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

- `road_width_flat` 负责道路宽度和属性。
- `road_strips` 将道路中心线生成面片，包含全顶点路口处理和凸包填充。
- `snap_road_strips` 对道路条带所有顶点二次贴地，修复坡地侧边埋入地形。
- `road_faces` QA 检查异常大面片、开放面和过多顶点。

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

成功标准：

- `Reports/model_qa/latest.json` 中 `status=pass`
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
