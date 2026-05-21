# 01 地图数据获取与 API 对比

## ⚠️ 重要更新（2024年10月）

> **SideFX Labs 内置 Mapbox 节点已被移除。**  
> Mapbox 单方面修改了 API 策略，SideFX 无法继续维护该工具。  
> 来源：https://www.sidefx.com/forum/post/432259/  
> 当前主流替代方案为 **OpenStreetMap (OSM)** 或 **Cesium**。

---

## 1. 数据源全景对比

| 数据源 | 类型 | 框选方式 | 免费额度 | Houdini支持 | 适用数据 |
|--------|------|---------|---------|------------|---------|
| **OpenStreetMap** | 矢量GIS | Overpass Turbo网页框选 | 完全免费 | ✅ SideFX Labs OSM Import | 建筑轮廓、道路、水系、POI |
| **Copernicus DEM** | 高程栅格 | 经纬度范围下载 | 完全免费 | ✅ 导入Heightfield | 地形高程（30m/90m分辨率） |
| **SRTM** | 高程栅格 | 经纬度范围下载 | 完全免费 | ✅ 导入Heightfield | 地形高程（30m分辨率） |
| **Mapbox** | 矢量+栅格 | API bbox参数 | 有限免费 | ❌ 官方节点已移除 | — |
| **Google Maps 3D Tiles** | 3D光照实景 | 无需框选（流式） | 需API Key | ⚠️ 通过Cesium中转 | 实景照片建模 |
| **HERE Maps** | 矢量+卫星 | API bbox | 商业授权 | 手动处理 | 高精度道路 |
| **天地图 / 高德 / 百度** | 国内地图 | API | 商业授权 | 需自定义处理 | 国内项目 |

---

## 2. 推荐路线 A：OpenStreetMap 框选导出（主流游戏/影视方案）

### 2.1 工具：Overpass Turbo

- 网址：https://overpass-turbo.eu/
- 操作：在地图上框选区域 → 点击"导出" → 选择 `.osm` 格式下载
- 支持 bounding box 精确坐标输入（适合脚本化批量下载）

### 2.2 OSM 数据包含内容

```
建筑 (building)        → 轮廓多边形 + 楼层属性
道路 (highway)         → 线段 + 道路类型属性
水系 (waterway/water)  → 多边形/线段
绿地 (landuse=grass)   → 多边形
铁路 (railway)         → 线段
地块边界 (landuse)     → 多边形
```

### 2.3 数据局限性

- 建筑高度数据（`building:height` 或 `building:levels`）**全球覆盖率不均**，中国城市覆盖较差
- 没有 LOD，没有纹理，只有拓扑形状
- 需要 Houdini 程序化生成细节

---

## 3. 推荐路线 B：Cesium + Google 3D Tiles（快速可视化）

### 适用场景

- 不需要可编辑几何体，只需真实视觉效果的场景
- 地理信息系统（GIS）可视化、城市规划展示
- 不适合游戏/影视的精细美术管线

### 流程简述

```
Google Maps Platform → 申请 API Key
    ↓
Cesium for Unreal 插件 → 在 UE5 中直接流式加载 Photorealistic 3D Tiles
    ↓
结合 UE5 Landscape / PCG 叠加自定义内容
```

- Google Photorealistic 3D Tiles 文档：  
  https://developers.google.com/maps/documentation/tile/3d-tiles
- Cesium for Unreal 教程：  
  https://cesium.com/learn/unreal/unreal-photorealistic-3d-tiles/

---

## 4. 推荐路线 C：DEM 高程 + OSM 矢量（地形驱动场景）

### 高程数据源

| 数据源 | 分辨率 | 下载地址 |
|--------|--------|---------|
| Copernicus DEM GLO-30 | 30m | https://spacedata.copernicus.eu |
| SRTM 1 Arc-Second | ~30m | https://earthexplorer.usgs.gov |
| ALOS World 3D | 30m | https://www.eorc.jaxa.jp/ALOS/en/dataset/aw3d30/aw3d30_e.htm |

### 处理格式

- 推荐导出为 **GeoTIFF (.tif)** 或 **16-bit PNG** 灰度图
- Houdini 使用 `Height Field File` SOP 导入

---

## 5. 国内项目特殊说明

中国境内使用地图数据需注意：
- **坐标系偏移**：国内地图使用 GCJ-02（火星坐标系），与 WGS-84 有偏移，需转换
- **合规性**：不允许将国内敏感地理数据用于境外服务
- 推荐使用 **天地图（tianditu.gov.cn）**官方数据或 **高德开放平台**
- OSM 中国地区数据质量参差不齐，大城市（北京/上海/深圳）较好
