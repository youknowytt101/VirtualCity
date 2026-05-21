# 原始数据

> 本目录存放 VirtualCity 管线输入数据。  
> AI 判断项目是否进入实施阶段时，优先检查这里是否已有 OSM / DEM / Reference 数据。

---

## 目录职责

```text
原始数据/
├── OSM/              ← OpenStreetMap .osm 原始导出
├── DEM/              ← GeoTIFF / 高程数据
├── Reference/        ← 参考截图、卫星图、Cesium 截图
└── GIS_Processed/    ← QGIS / GDAL / Python 处理后的 GeoJSON / SHP / metadata
```

---

## 推荐命名

### OSM

```text
{area_id}_osm_v001.osm
```

### DEM

```text
{area_id}_dem_v001.tif
```

### 参考图

```text
{area_id}_reference_satellite_v001.png
{area_id}_reference_cesium_v001.png
```

### 处理后 GIS

```text
{area_id}_buildings_v001.geojson
{area_id}_roads_v001.geojson
{area_id}_landuse_v001.geojson
{area_id}_water_v001.geojson
{area_id}_metadata_v001.json
```

---

## 数据记录要求

每个区域必须在 `项目管理/区域记录/` 下建立对应记录文件。

记录内容至少包括：

- 区域 ID。
- bbox。
- 数据来源。
- 下载时间。
- 原始坐标系。
- 是否经过 GIS 预处理。

---

## 当前状态

当前目录尚未放入 MVP 数据。下一步应先选择测试区域，并从 Overpass Turbo 导出第一份 `.osm`。
