# Houdini

> 本目录存放 VirtualCity 的 Houdini 工程、HDA、导出资产和后续 PDG 输出。  
> AI 判断 Houdini 阶段是否开始时，优先检查 `Hip/` 和 `HDA/` 是否存在有效文件。

---

## 推荐目录结构

```text
Houdini/
├── Hip/          ← .hip / .hiplc / .hipnc 工程文件
├── HDA/          ← .hda / .hdalc 数字资产
├── Export/       ← FBX / OBJ / Alembic / Heightmap / JSON 输出
└── PDG_Output/   ← 后续 TOPs / PDG 批处理输出
```

---

## MVP 阶段目标

第一版 Houdini 只需要完成：

- 导入 OSM。
- 分离建筑、道路、水体、绿地。
- 建筑轮廓拉伸成白盒体量。
- 道路线生成简单路面。
- 可选导入 DEM 为基础 Heightfield。
- 输出 HDA 或静态 FBX / Heightmap。

---

## 推荐命名

### Hip 文件

```text
VC_{area_id}_citygen_v001.hip
```

### HDA 文件

```text
VC_{area_id}_cityblock_v001.hda
```

### 导出文件

```text
VC_{area_id}_buildings_v001.fbx
VC_{area_id}_roads_v001.fbx
VC_{area_id}_landscape_height_v001.png
VC_{area_id}_params_v001.json
```

---

## HDA 输出规范

建议输出节点命名：

```text
OUT_buildings
OUT_roads
OUT_landscape
OUT_points
OUT_debug
```

建议暴露参数：

- `building_height_multiplier`
- `default_floor_height`
- `default_levels_min`
- `default_levels_max`
- `road_width_multiplier`
- `terrain_resolution`
- `preview_lod`
- `random_seed`

---

## 当前状态

当前目录尚未创建 Houdini 工程。下一步是在 `Hip/` 下创建第一个 MVP `.hip` 文件。
