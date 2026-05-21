# 02 Houdini 处理流程

## 概览

Houdini 在本流程中承担三类工作：
1. **OSM 矢量数据解析** → 生成建筑/道路几何体
2. **Heightfield 地形处理** → 雕刻、分层、道路压入地形
3. **HDA 封装打包** → 将上述资产打包为 Houdini Digital Asset，供 UE5 调用

---

## 1. SideFX Labs 工具链（必装）

> SideFX Labs（原 GameDev Toolset）是官方出品的免费扩展工具集，包含 OSM 处理的核心节点。

### 安装方式

```
Houdini → 菜单 Windows → Package Manager → 搜索 SideFX Labs → Install
```
或从 GitHub 手动安装：https://github.com/sideeffects/SideFXLabs

### 关键 OSM 节点

| 节点名 | 功能 |
|--------|------|
| `Labs OSM Import` | 导入 .osm 文件，按 tag 分类输出 |
| `Labs OSM Filter` | 按 key/value 过滤要素（如只要建筑） |
| `Labs OSM Buildings` | 从建筑轮廓生成程序化建筑体量 |
| `Labs OSM Roads` | 将道路线段转为多边形路面 |
| `Labs OSM Landuse` | 处理地块分区（绿地/水域/工业区等） |

---

## 2. OSM → 建筑体量 标准节点网络

```
[Labs OSM Import]
    ↓  (output 1: buildings polygon)
[Labs OSM Filter]  key=building
    ↓
[PolyExtrude]  ← 按 building:levels 属性控制高度
    ↓
[Attribute Wrangle]  ← 分配楼层数、建筑类型属性
    ↓
[Labs OSM Buildings]  ← 自动处理屋顶类型
    ↓
[Switch/For-Each]  ← 按建筑类型分组打包

[Labs OSM Import]
    ↓  (output 2: roads lines)
[Labs OSM Roads]
    ↓
[ResampleSOP + PolyExtrude]  ← 道路宽度处理

→ [Merge] → [Output] → 打包为 HDA
```

---

## 3. Heightfield 地形处理标准流程

### 3.1 导入 DEM 高程数据

```
[Height Field File]  ← 导入 GeoTIFF 或 16-bit PNG
    ↓
[Height Field Resize]  ← 统一分辨率（建议 2048×2048 或 4096×4096）
    ↓
[Height Field Blur]  ← 平滑噪点
```

### 3.2 地形层分配（Splat Map）

```
[Height Field Layer]  ← 基础地形层
    ↓
[Height Field Mask by Feature]  ← 按坡度/高度生成岩石/草地/雪地蒙版
    ↓
[Height Field Paint]  ← 手动修正遮罩区域
    ↓
[Height Field Output]  ← 输出 Landscape + Layer Weight Maps
```

### 3.3 道路压入地形

```
[Resample]  ← OSM 道路线段重采样
    ↓
[Height Field Project]  ← 将道路线段投影并压平地形
    ↓
[Height Field Blur]  ← 道路边缘平滑过渡
```

---

## 4. HDA 制作规范（供 UE5 调用）

### 4.1 基本规范

- **输出节点**：使用 `null` 节点命名为 `OUT_geo`、`OUT_landscape` 等
- **暴露参数**：将需要在 UE5 中调整的参数通过 "Edit Parameter Interface" 暴露
- **坐标系**：Houdini 默认 Y-up，UE5 为 Z-up，Houdini Engine 插件会自动转换
- **单位**：1 Houdini unit = 1 UE5 cm（**注意：不是 1m**，需要在 HDA 中 scale ×100 或在 UE5 中调整）

### 4.2 常用暴露参数示例

```python
# 在 Parameter Interface 中暴露：
bbox_min      # 框选区域最小坐标
bbox_max      # 框选区域最大坐标
building_height_multiplier  # 建筑高度系数
road_width    # 道路宽度
lod_level     # 细节层级
```

### 4.3 输出类型与 UE5 对应关系

| Houdini 输出 | UE5 生成内容 |
|-------------|------------|
| Mesh geometry | Static Mesh Actor |
| Heightfield | Landscape Actor |
| Packed primitives | Instanced Static Mesh (ISM) |
| Points with attributes | PCG Points（需 PCG 版插件）|
| Curve | Spline Component |

---

## 5. 参考资源

- SideFX 官方教程 - OSM 城市生成：  
  https://www.sidefx.com/tutorials/city-building-with-osm-data/

- Houdini Heightfield 生成 UE5 Landscape 官方文档：  
  https://www.sidefx.com/docs/houdini/unreal/landscape/generate.html

- OSM Importer 工具文档：  
  https://www.sidefx.com/tutorials/osm-importer/

- UE5 City Sample 使用 Houdini 的完整案例（Epic 官方）：  
  https://dev.epicgames.com/documentation/en-us/unreal-engine/city-sample-quick-start-for-generating-a-city-and-freeway-using-houdini
