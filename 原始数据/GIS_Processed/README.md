# GIS_Processed

> 存放经过 QGIS / GDAL / Python 预处理后的 GIS 数据。

---

## 推荐文件

```text
{area_id}_buildings_v001.geojson
{area_id}_roads_v001.geojson
{area_id}_landuse_v001.geojson
{area_id}_water_v001.geojson
{area_id}_metadata_v001.json
```

---

## 处理内容

- 坐标系统一。
- bbox 裁剪。
- 道路 / 建筑 / 水体 / 绿地分类。
- 破碎几何修复。
- 重复点和无效线清理。

---

## 当前状态

MVP 前期可以先跳过 GIS 预处理，直接用 `.osm` 进入 Houdini。等流程跑通后再补这一层。
