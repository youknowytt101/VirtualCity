# 区域记录：pattaya_sai6_mvp

> 当前区域来自用户提供的 Pattaya Sai 6 附近地图截图。  
> 该区域已作为第一个 MVP 候选区域接入项目，但 bbox 经纬度仍需用户从地图工具中复制后补全。

---

## 1. 基本信息

| 项 | 内容 |
|---|---|
| 区域 ID | `pattaya_sai6_mvp` |
| 城市 / 地点 | Pattaya Sai 6, Pattaya, Chon Buri, Thailand |
| 目标用途 | MVP 测试区域 |
| 创建日期 | 2026-05-21 |
| 负责人 | 用户 / AI 协作 |
| 当前状态 | bbox 已填入（估算值），可下载 OSM |

---

## 2. bbox

| 方向 | 经纬度 |
|---|---:|
| west | 100.866 |
| south | 12.946 |
| east | 100.876 |
| north | 12.957 |

> **精度说明**：当前坐标为从用户截图地标反推的估算值，误差约 50–100m。  
> 如需精确对齐，可到 [bboxfinder.com](http://bboxfinder.com) 验证后更新。  
> 估算尺寸：约 1000m × 1200m（可按需裁剪为更小的 MVP 范围）。

---

## 3. 坐标系

| 项 | 内容 |
|---|---|
| 原始坐标系 | WGS84，待确认 |
| Houdini 坐标 | 局部米制坐标 |
| UE5 坐标 | cm，局部世界坐标 |
| 原点策略 | bbox 中心（lon: 100.871, lat: 12.9515） |

---

## 4. 数据文件

| 数据 | 路径 | 来源 | 下载时间 |
|---|---|---|---|
| OSM | `RawData/OSM/pattaya_sai6_mvp_osm_v001.osm` | Overpass Turbo，待下载 | 待填写 |
| DEM | 暂不使用 | MVP 第一版可跳过 | - |
| 参考截图 | 用户已提供地图截图，尚未保存为项目文件 | 用户上传 | 2026-05-21 |
| 处理后 GIS | `RawData/GIS_Processed/` | 后续可选 | 待处理 |

---

## 5. Houdini 参数

| 参数 | 值 |
|---|---:|
| building_height_multiplier | 1.0 |
| default_floor_height | 3.0 |
| default_levels_min | 2 |
| default_levels_max | 8 |
| road_width_multiplier | 1.0 |
| terrain_resolution | 2048 |
| random_seed | 1001 |

---

## 6. 输出文件

| 类型 | 路径 |
|---|---|
| .hip | `Houdini/Hip/VC_pattaya_sai6_mvp_citygen_v001.hip` |
| .hda | `Houdini/HDA/VC_pattaya_sai6_mvp_cityblock_v001.hda` |
| .fbx | `Houdini/Export/VC_pattaya_sai6_mvp_buildings_v001.fbx` |
| heightmap | 暂不使用 |
| UE5 map | `LV_pattaya_sai6_mvp_MVP` |

---

## 7. QA 结果

| 检查项 | 结果 | 备注 |
|---|---|---|
| bbox 记录 | 通过（估算） | 从截图地标推算，误差 50–100m，可用于 OSM 下载 |
| OSM 文件 | 未检查 | 可立即使用 overpass.txt 中的查询下载 |
| 道路连续性 | 未检查 | Houdini 导入后检查 |
| 建筑位置 | 未检查 | Houdini 导入后检查 |
| 地形对齐 | 暂不使用 | MVP 第一版跳过 DEM |
| UE 比例 | 未检查 | UE5 导入后检查 |
| Bake 结果 | 未检查 | UE5 阶段检查 |
| 性能 | 未检查 | UE5 阶段检查 |

---

## 8. 问题记录

- bbox 为从截图地标反推的估算值，误差约 50–100m。如需精确对齐请到 bboxfinder.com 验证。
- 截图区域道路（Soi 5 / Soi 6）、建筑和水道清晰，适合作为第一个 MVP 测试区域。

---

## 9. 下一步

1. 打开 `Config/pattaya_sai6_mvp.overpass.txt`，复制查询内容。
2. 粘贴到 [overpass-turbo.eu](https://overpass-turbo.eu/) 并执行。
3. 导出 → Download as OSM (XML)。
4. 保存为 `RawData/OSM/pattaya_sai6_mvp_osm_v001.osm`。
5. 开始创建 Houdini MVP 工程：`Houdini/Hip/VC_pattaya_sai6_mvp_citygen_v001.hip`。
