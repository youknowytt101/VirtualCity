# RawData

> 本目录存放 VirtualCity 当前管线的输入数据、区域裁切缓存和 Houdini 中间输入。
> 当前主数据源是 OSM 道路、FABDEM 优先 DEM、Overture 建筑轮廓。

---

## 当前目录职责

```text
RawData/
├── OSM/              ← 区域 .osm，主要负责道路和 OSM 建筑兜底
├── DEM/              ← 区域 DEM CSV / GeoTIFF，当前优先 FABDEM
├── Overture/         ← Overture 建筑轮廓 GeoJSON
├── Reference/        ← 参考截图、卫星图、Cesium 截图
├── GIS_Processed/    ← QGIS / GDAL / Python 处理后的长期成果
├── _clip_cache/      ← 按 bbox 裁切后的原始数据缓存，可提交小体量样区
├── _downloads/       ← 当前区域 raw snapshot，不提交
├── _cleaned/         ← 清洗中间结果，不提交
└── _houdini_ready/   ← Houdini 输入结果，不提交
```

---

## 当前命名

### OSM

```text
{area_id}_osm_v001.osm
```

### DEM

```text
{area_id}_dem_v001.csv
{area_id}_dem_v001.tif
```

### Overture 建筑

```text
{area_id}_buildings_overture_v001.geojson
```

### clip cache

```text
RawData/_clip_cache/bbox_{hash}/
├── _manifest.json
├── roads.osm
├── dem.csv
└── buildings.geojson
```

---

## 数据清洗流程

当前数据进入 Houdini 前会经过：

```text
set_area.py
    ↓
refine_data.py
    ↓
RawData/_houdini_ready/{area_id}/
```

`refine_data.py` 会：

- 保存 raw snapshot 到 `_downloads/{area_id}/`。
- 使用 `data_cleaning_cache.py` 判断是否可复用清洗结果。
- 清洗建筑、道路、DEM。
- 补全 OSM `building:levels` / `height`。
- 生成数据 QA 报告到 `Config/qa/`。

---

## 区域记录策略

快速实验阶段会生成很多 `area_12.xxx_100.xxx` 区域。不是每个快速测试区都需要写完整区域文档。

建议：

- 快速回归测试区：保留 RawData、hip、QA report 即可。
- 晋级为基准样区 / 展示样区：再补 `项目管理/区域记录/{area_id}.md`。

---

## 当前基准样区

最新完整流程通过：

```text
area_12.918_100.865
```

相关文件：

```text
RawData/OSM/area_12.918_100.865_osm_v001.osm
RawData/DEM/area_12.918_100.865_dem_v001.csv
RawData/Overture/area_12.918_100.865_buildings_overture_v001.geojson
Config/qa/area_12.918_100.865_qa_20260528_031731.json
```
