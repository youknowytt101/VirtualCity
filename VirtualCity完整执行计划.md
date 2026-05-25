# VirtualCity 完整执行计划

> 目标：把“地图数据 → Houdini 程序化处理 → UE5 场景整合”的调研结论，转化为可执行、可验收、可扩展的完整落地计划。  
> 推荐策略：先做小范围 MVP，再逐步扩展到 1km²、World Partition、PCG、模块化建筑和动态城市系统。

---

## 1. 总体目标

最终形成一条稳定流程：

```text
地图数据 / OSM / DEM
    ↓
GIS 预处理 / 坐标统一
    ↓
Houdini 生成道路、建筑、地形、点位
    ↓
HDA 或静态资产导出
    ↓
UE5 Houdini Engine 导入
    ↓
Bake 成 Static Mesh / Landscape
    ↓
Nanite + Lumen + PCG + World Partition
```

第一阶段不要追求完整 City Sample，而是先做一个 **能跑、能看、能复现、能扩展** 的小城市原型。

---

## 2. 执行主线

项目拆成三条线并行推进：

### 主线 A：MVP 跑通

先完成一个 `200m × 200m` 到 `500m × 500m` 的真实城市小区块。

### 主线 B：管线标准化

固定数据、Houdini、UE5 的目录、命名、参数、导出格式。

### 主线 C：效果与规模扩展

MVP 稳定后，再扩展到 `1km²`、World Partition、PCG、模块化建筑。

---

## 3. Phase 0｜项目基建与环境准备

### 目标

搭建完整工具链，保证 Houdini、SideFX Labs、UE5、Houdini Engine 能互通。

### 工作内容

- **安装 Houdini**：推荐 Houdini `20.5` 或 `21.0`，如果插件兼容有问题，优先选择稳定版本。
- **安装 SideFX Labs**：用于 `OSM Import`、道路、建筑、地形等工具节点。
- **安装 UE5**：建议优先使用 `UE 5.4 / 5.5`，但要以 Houdini Engine 支持版本为准。
- **安装 Houdini Engine for Unreal**：普通版优先，第一阶段暂时不强依赖 PCG 版。
- **建立标准目录**。

### 推荐目录结构

```text
D:\VirtualCity\
├── RawData\
│   ├── OSM\
│   ├── DEM\
│   ├── Reference\
│   └── GIS_Processed\
├── Houdini\
│   ├── Hip\
│   ├── HDA\
│   ├── Export\
│   └── PDG_Output\
├── UE5\
│   └── VirtualCityUE\
├── 调研文档\
└── 执行方案.md
```

### 交付物

- **Houdini 测试文件**：`D:\VirtualCity\Houdini\Hip\VirtualCity_OSM_MVP.hip`
- **UE5 测试项目**：`D:\VirtualCity\UE5\VirtualCityUE\`
- **插件验证记录**：记录 Houdini、UE5、Houdini Engine、SideFX Labs 版本。

### 验收标准

- **Houdini 可用**：能搜索到 SideFX Labs 节点。
- **UE5 可用**：能启用 Houdini Engine 插件。
- **HDA 可导入**：UE5 能成功导入一个测试 `.hda`。

---

## 4. Phase 1｜测试区域与数据获取

### 目标

选定一个小范围真实城市区域，获取 OSM 和 DEM 数据。

### 推荐范围

第一版控制在：

```text
200m × 200m ～ 500m × 500m
```

不要一开始做整城或大地图。

### 选区标准

- **道路清晰**：最好有主路、支路、路口。
- **建筑完整**：OSM 里有较完整的建筑轮廓。
- **地形简单**：第一版避免山地、复杂高差、大水体。
- **区域典型**：最好包含住宅、商业、绿地、道路。

### 数据来源

| 数据 | 推荐来源 | 用途 |
|---|---|---|
| OSM | Overpass Turbo | 道路、建筑、绿地、水体 |
| DEM | Copernicus / SRTM / USGS | 地形高程 |
| 参考图 | Cesium / 卫星图截图 | 人工比对 |
| 国内地图 | 天地图 / 高德 | 仅作参考，注意坐标偏移和授权 |

### 工作内容

- **确定 bbox**：记录经纬度范围。
- **导出 OSM**：保存为 `mvp_area.osm`。
- **下载 DEM**：保存为 `mvp_area.tif`。
- **保存参考截图**：方便后续检查道路方向、建筑密度。
- **记录数据来源**：包括下载时间、坐标系、授权说明。

### 验收标准

- **OSM 文件存在**：`RawData/OSM/mvp_area.osm`
- **DEM 文件存在**：`RawData/DEM/mvp_area.tif`
- **bbox 已记录**：后续能重复下载同一区域数据。

---

## 5. Phase 2｜GIS 预处理与坐标统一

### 目标

在进 Houdini 之前，把地图数据整理成适合程序化处理的局部坐标。

### 必要性

OSM RawData通常是 WGS84 经纬度，不适合直接作为 Houdini / UE5 场景坐标。尤其是国内数据还可能涉及 `GCJ-02`、`BD-09`、`CGCS2000`。

### 工作内容

- **确认坐标系**：判断数据是 WGS84、GCJ-02、BD-09 还是 CGCS2000。
- **统一投影**：转成本地米制坐标，例如 UTM 或项目局部坐标。
- **建立项目原点**：以 bbox 中心或西南角作为局部坐标原点。
- **清洗几何**：修复重复点、断线、自交面、破碎建筑轮廓。
- **分类导出**：分离道路、建筑、水系、绿地、铁路、POI。

### 推荐工具

- **QGIS**：做可视化检查、投影、裁剪。
- **GDAL / ogr2ogr**：做格式转换和批处理。
- **Python**：做自动化坐标转换和数据清洗。

### 输出建议

```text
RawData/GIS_Processed/
├── mvp_buildings.geojson
├── mvp_roads.geojson
├── mvp_landuse.geojson
├── mvp_water.geojson
└── mvp_metadata.json
```

### 验收标准

- **坐标为米制**：Houdini 中导入后尺寸合理。
- **道路建筑对齐**：没有明显偏移。
- **数据可重复处理**：保留转换脚本或处理记录。

---

## 6. Phase 3｜Houdini MVP 城市生成

### 目标

在 Houdini 里生成第一版白盒城市：道路、建筑体量、地形。

### Houdini 节点主流程

```text
OSM / GeoJSON Import
    ↓
分类建筑 / 道路 / 绿地 / 水体
    ↓
道路生成
    ↓
建筑体量生成
    ↓
DEM Heightfield 导入
    ↓
道路压入地形
    ↓
材质与属性赋值
    ↓
输出 HDA / FBX / Heightmap
```

### 建筑生成规则

- **有 `building:height`**：直接使用高度。
- **有 `building:levels`**：使用 `levels × 3m`。
- **高度缺失**：根据建筑面积、道路等级、用地类型随机补全。
- **第一版不做复杂立面**：只做可信体量和基础材质。

### 道路生成规则

- **按 `highway` 类型决定宽度**：主路、次路、支路宽度不同。
- **路口先简化处理**：第一版不要追求复杂车道线。
- **道路要优先正确**：道路错了，后面建筑、PCG、交通都会错。

### 地形处理规则

- **DEM 导入为 Heightfield**：第一版地形分辨率不用太高。
- **道路区域压平**：避免道路悬空或穿地。
- **边缘平滑**：道路与地形交界要自然过渡。

### HDA 暴露参数

| 参数 | 用途 |
|---|---|
| `building_height_multiplier` | 建筑整体高度倍率 |
| `default_floor_height` | 默认层高 |
| `default_levels_min` | 默认最小楼层 |
| `default_levels_max` | 默认最大楼层 |
| `road_width_multiplier` | 道路宽度倍率 |
| `terrain_resolution` | 地形分辨率 |
| `preview_lod` | 预览精度 |
| `random_seed` | 随机种子 |

### 输出文件

```text
Houdini/Hip/VirtualCity_OSM_MVP.hip
Houdini/HDA/VC_OSM_CityBlock.hda
Houdini/Export/mvp_city_block.fbx
Houdini/Export/mvp_landscape_height.png
```

### 验收标准

- **能看到道路**：道路宽度基本可信。
- **能看到建筑体量**：建筑位置与 OSM 轮廓匹配。
- **能看到地形**：地形比例正确。
- **能导出 HDA**：后续可进 UE5。

---

## 7. Phase 4｜UE5 集成与 Bake

### 目标

把 Houdini 生成结果导入 UE5，并变成可运行、可保存、可脱离 Houdini 的关卡资产。

### UE5 工作流程

```text
创建 UE5 项目
    ↓
启用 Houdini Engine
    ↓
导入 VC_OSM_CityBlock.hda
    ↓
拖入 Level
    ↓
调参数 / Recook
    ↓
Bake 为 Static Mesh / Landscape
    ↓
启用 Nanite / Lumen
```

### UE5 基础设置

- **开启 Lumen**：用于动态全局光照。
- **开启 Virtual Shadow Maps**：用于大规模城市阴影。
- **Static Mesh 启用 Nanite**：建筑、道路、道具可以逐步开启。
- **第一阶段暂不强制 World Partition**：小范围 MVP 不需要过早复杂化。
- **第一阶段暂不做 Mass AI**：先把静态城市跑通。

### UE5 目录建议

```text
Content/VirtualCity/
├── Maps/
├── Houdini/
├── Meshes/
├── Materials/
├── PCG/
├── Blueprints/
└── DataLayers/
```

### Data Layer 建议

| Data Layer | 内容 |
|---|---|
| `DL_Terrain` | 地形 |
| `DL_Roads` | 道路、人行道、路缘 |
| `DL_Buildings` | 建筑体量 |
| `DL_Foliage` | 植被 |
| `DL_Props` | 路灯、垃圾桶、长椅 |
| `DL_Debug` | 调试参考线、bbox、坐标标记 |

### 验收标准

- **HDA 可 Recook**：UE5 内调参数能更新结果。
- **Bake 后可打开**：不依赖 Houdini Engine 也能查看场景。
- **Play 正常**：能进入关卡漫游。
- **比例正确**：人、车、建筑、道路比例合理。

---

## 8. Phase 5｜视觉展示与基础美术增强

### 目标

从“技术跑通”提升到“可以截图展示”。

### 工作内容

- **道路材质**：沥青、路缘、人行道基础材质。
- **建筑材质**：住宅、商业、工业、未知类型使用不同材质实例。
- **窗户假细节**：第一版用贴图或程序化窗格，不做复杂模块库。
- **PCG 散布**：沿道路散布树、路灯、垃圾桶、长椅。
- **灯光氛围**：做白天和夜晚两套基础光照。
- **镜头点位**：设置 3～5 个展示视角。

### 验收标准

- **可截图**：至少有 3 张能展示项目方向的截图。
- **可漫游**：第一人称或自由相机能浏览城市区块。
- **视觉可信**：道路、建筑、地形、植被没有明显错位。

---

## 9. Phase 6｜管线标准化

### 目标

把 MVP 做成可重复、可维护、可扩展的生产流程。

### 工作内容

- **固定目录规范**：RawData、处理中间数据、HDA、导出资产分离。
- **固定命名规范**：例如 `VC_Block_001_Buildings`、`VC_Block_001_Roads`。
- **固定单位规范**：Houdini 内部建议 `1 unit = 1m`，进 UE5 统一乘 `100`。
- **固定坐标规范**：所有数据都转换到项目局部坐标。
- **建立 metadata**：每个区块记录 bbox、数据来源、HDA 版本、随机种子。
- **建立 QA Checklist**：每次生成后检查道路断裂、建筑压路、坐标偏移、Tile 缝隙。

### 验收标准

- **换一个 bbox 能复用流程**：不需要重新设计节点网络。
- **参数可控**：建筑高度、道路宽度、地形精度都能通过 HDA 控制。
- **结果可追踪**：每次输出知道来源和版本。

---

## 10. Phase 7｜扩展到 1km² 样区

### 目标

从小区块扩展到可展示的城市级样区。

### 触发条件

- **MVP 稳定**：小范围已经能稳定生成和导入。
- **Cook 时间可接受**：单次生成不要长时间卡死。
- **UE5 性能可接受**：Play 模式没有明显卡顿。

### 工作内容

- **扩大 bbox**：从 `500m × 500m` 扩到 `1km × 1km`。
- **引入 Tile 分块**：按 `250m` 或 `500m` 分块生成。
- **引入 World Partition**：UE5 中开始测试大世界加载。
- **引入 HLOD**：为远景建筑和大规模资产做层级简化。
- **优化实例化**：建筑重复构件、路灯、树木尽量使用 ISM / HISM。

### 验收标准

- **1km² 可打开**：UE5 能稳定加载。
- **分块没有明显缝隙**：道路、地形、建筑边界连续。
- **性能可接受**：编辑器和运行时都能正常浏览。

---

## 11. Phase 8｜模块化建筑与 Shape Grammar

### 目标

从白盒建筑升级到更接近 City Sample 的程序化建筑。

### 工作内容

- **建立模块库**：底层、标准层、顶层、窗户、阳台、屋顶设备。
- **建立建筑分层规则**：按底商、标准层、屋顶进行拆分。
- **建立风格标签**：住宅、商业、办公、工业使用不同规则。
- **使用 Houdini 规则装配**：根据建筑轮廓和高度自动拼装立面模块。
- **启用 Nanite**：模块可用高精度模型，但要控制材质槽数量。

### 验收标准

- **建筑不再只是盒子**：有基础窗户、立面、屋顶变化。
- **规则可复用**：同一套规则能作用于不同地块。
- **性能仍可控**：使用实例化，不为每栋楼生成完全独立高模。

---

## 12. Phase 9｜交通、人群与城市动态系统

### 目标

在静态城市基础上加入动态内容。

### 工作内容

- **道路生成 ZoneGraph 数据**：为 UE5 交通系统准备路径。
- **输出 traffic zone**：Houdini 中根据道路等级生成交通密度属性。
- **输出 pedestrian density**：根据商业区、住宅区、路口生成行人密度。
- **接入 Mass AI**：做基础车辆和行人流动。
- **接入 PCG 动态点位**：控制垃圾、广告牌、临时道具等分布。

### 验收标准

- **车辆能沿路行驶**：不要求复杂 AI，先跑通路线。
- **行人能在指定区域出现**：密度可控。
- **动态系统不破坏性能**：不影响基础场景浏览。

---

## 13. 推荐时间排期

### 第一周：跑通 MVP

| 天数 | 目标 |
|---|---|
| Day 1 | 环境安装、目录整理、版本确认 |
| Day 2 | 选 bbox、下载 OSM、下载 DEM |
| Day 3 | Houdini 导入 OSM，生成道路和建筑体量 |
| Day 4 | 导入 DEM，处理地形和道路贴合 |
| Day 5 | 封装 HDA，暴露参数 |
| Day 6 | UE5 导入 HDA，Bake 成资产 |
| Day 7 | 加材质、灯光、截图、复盘 |

### 第二周：稳定管线

| 天数 | 目标 |
|---|---|
| Day 8-9 | 加 GIS 预处理、坐标转换记录 |
| Day 10-11 | 整理 HDA 参数和输出结构 |
| Day 12 | 加 PCG 树木、路灯、垃圾桶 |
| Day 13 | 性能检查和 Nanite 设置 |
| Day 14 | 固化 MVP 文档和问题清单 |

### 第三到四周：扩展 1km²

| 周期 | 目标 |
|---|---|
| Week 3 | Tile 分块、World Partition 初步接入 |
| Week 4 | HLOD、PCG 扩展、展示关卡优化 |

### 后续阶段

| 阶段 | 目标 |
|---|---|
| Month 2 | 模块化建筑和简单立面规则 |
| Month 3 | Shape Grammar、PDG、1km²+ 稳定生成 |
| Month 4+ | Mass AI、交通、人群、完整城市系统 |

---

## 14. 第一阶段明确不做的内容

- **不做完整 City Sample 复刻**：模块库、Rule Processor、Mass AI 后置。
- **不依赖 Google 3D Tiles 作为资产来源**：只作为参考或在线预览。
- **不做整城级地图**：先小区块，再扩大范围。
- **不做复杂交通 AI**：先静态城市，后动态系统。
- **不做高精度真实建筑复原**：OSM 数据不足以支持真实建筑复原，第一阶段只做体量和视觉可信。

---

## 15. 第一版最终交付物

### 文件交付

- **OSM 数据**：`RawData/OSM/mvp_area.osm`
- **DEM 数据**：`RawData/DEM/mvp_area.tif`
- **处理后 GIS 数据**：`RawData/GIS_Processed/`
- **Houdini 工程**：`Houdini/Hip/VirtualCity_OSM_MVP.hip`
- **HDA 文件**：`Houdini/HDA/VC_OSM_CityBlock.hda`
- **UE5 项目**：`UE5/VirtualCityUE/`
- **演示关卡**：UE5 中可 Play 的城市区块。

### 功能交付

- **真实 OSM 道路导入**。
- **建筑轮廓生成体量**。
- **DEM 地形导入**。
- **道路与地形贴合**。
- **Houdini HDA 导入 UE5**。
- **Bake 后脱离 Houdini 可运行**。
- **基础材质、灯光、PCG 点缀**。
- **3～5 张展示截图**。

---

## 16. 关键成功标准

第一阶段是否成功，不看城市有多大，而看以下几点：

- **流程能重复**：换一个 bbox 还能跑。
- **比例是对的**：人、车、路、楼尺度正常。
- **坐标是对的**：道路、建筑、地形不偏移。
- **UE5 能 Bake**：不依赖 Houdini 也能打开。
- **性能可接受**：小区块能顺畅浏览。
- **后续能扩展**：可以自然进入 1km²、World Partition、PCG、模块化建筑阶段。

---

## 17. 下一步建议

可以直接从以下三件事开始：

1. **确定测试区域 bbox**：选一个 `200m × 200m` 到 `500m × 500m` 的区域。
2. **下载 OSM 数据**：先不纠结 DEM，优先跑通道路和建筑。
3. **在 Houdini 建 MVP 节点网络**：先生成白盒城市，再进 UE5。

完成这三步后，项目就能从“调研文档”进入“可运行原型”。
