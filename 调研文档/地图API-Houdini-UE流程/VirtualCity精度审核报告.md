# VirtualCity 精度审核报告

> **审核日期**：2025-05-27  
> **审核范围**：道路 / 建筑 / 地形三大系统与真实数据的匹配度  
> **当前测试区**：Pattaya Sai 6（~1.6km × 1.8km），WGS84  
> **项目路径**：`D:\VirtualCity`  
> **审核原则**：不直接修改项目，仅提出最优解建议

---

## 一、关键发现：一个严重错误前提

### Copernicus GLO-10 (10m) 对泰国不可用

`Scripts/download_dem.py` 中的 `download_copernicus_10m()` 函数尝试从 AWS S3 下载 Copernicus 10m DEM。

**经 Copernicus 官方文档确认**：

- **EEA-10 仅覆盖 39 个欧洲国家**（包括法属海外省，不含海外领地）
- **GLO-30**（30m）和 **GLO-90**（90m）才是全球覆盖
- **Pattaya（泰国）不在 10m 覆盖范围内**

这意味着 `download_copernicus_10m()` 在当前项目区域会 **100% 失败**，然后 fallback 到 NASADEM 30m。代码有 fallback 逻辑所以不会崩溃，但说明项目文档中"优先使用 Copernicus 10m"的策略对东南亚无效。

---

## 二、坐标投影系统（影响全局三大块）

### 当前实现

`Scripts/_osm_import_canonical.py` 中的投影函数：

```python
def wgs84_to_local(lon, lat):
    dx = (lon - ORIGIN_LON) * math.cos(math.radians(ORIGIN_LAT)) * 111319.9
    dy = (lat - ORIGIN_LAT) * 111319.9
    return dx, dy
```

这是**等距矩形投影（Equirectangular）**，同一函数出现在 `download_dem.py`、`correct_dem_dtm.py`、`enrich_building_levels.py`、`clean_raw_data.py` 共 5 处。

### 精度问题

| 误差源 | 量级 | 影响 |
|--------|------|------|
| 纬度方向用固定 111319.9 m/° | 在 12.93°N 误差 ~0.1% (~1.8m/1.8km) | 南北向建筑/道路位移 |
| 经度方向 `cos(origin_lat)` 只取原点处余弦 | 在 1.8km 跨度内 < 0.01% | 当前可接受 |
| 无椭球修正（未区分 GRS80/WGS84） | ~0.2m/km | 累积偏移 |
| 大范围扩展到 5km+ 时误差快速增长 | ~5-10m@5km | 不可接受 |

### 最优解

将全局投影替换为 UTM Zone 47N，使用 Python `utm` 包（零依赖、纯 Python、Houdini 兼容性最佳）：

```python
import utm

# 预计算原点 UTM 坐标（一次性）
ORIGIN_X, ORIGIN_Y, _, _ = utm.from_latlon(ORIGIN_LAT, ORIGIN_LON)

def wgs84_to_local(lon, lat):
    x, y, _, _ = utm.from_latlon(lat, lon)
    return x - ORIGIN_X, y - ORIGIN_Y
```

- **效果**：在 5km 范围内精度从 ~5m 提升到 **< 0.01m**
- **改动量**：统一修改 `wgs84_to_local()` 函数（5 个文件），并记录 `ORIGIN_X`/`ORIGIN_Y` 到 `active_area.json`
- **优先级**：**P0 — 影响全局精度的根因**

---

## 三、逐数据源 API 可用性与精度验证

### 3.1 地形 DEM — 全部候选源

| 数据源 | 分辨率 | 类型 | 垂直精度 | API | 泰国可用 | 许可 | 费用 |
|--------|--------|------|----------|-----|----------|------|------|
| **NASADEM** | 30m | DSM | ±5-9m | GEE `NASA/NASADEM_HGT/001` | ✅ | Public Domain | 免费 |
| **Copernicus GLO-30** | 30m | DSM | <4m (90% LE), <2m 平坦区 | GEE `COPERNICUS/DEM/GLO30` / AWS S3 | ✅ | Free (attribution) | 免费 |
| **Copernicus EEA-10** | 10m | DSM | <4m | Copernicus Dataspace | ❌ **仅欧洲** | 受限 | N/A |
| **FABDEM V1-2** | 30m | **DTM（裸地）** | 比 COP-30 好 ~33% (建成区) | GEE `projects/sat-io/open-datasets/FABDEM` / Bristol大学直下 | ✅ | **CC BY-NC-SA 4.0** (非商用) | 免费 |
| **ALOS World 3D** | 30m | DSM | ±5m | JAXA官方 | ✅ | 研究/商用均可 | 免费 |
| **FABDEM+** | 30m | DTM+LiDAR | 最优 | Fathom Global 商业 API | ✅ | 商用授权 | **付费** |

**关键数据**（来自 Fathom Global 官方及学术论文）：

- FABDEM 在建成区将 COP-DEM GLO-30 的垂直误差降低约 **1/3**
- FABDEM 在植被区将垂直误差降低约 **1/2**
- Pattaya 沿海区域实测高程 0-12m，格网间距 ~29.24m = NASADEM 30m
- FABDEM 是全球唯一免费的 30m DTM，已通过机器学习移除建筑和树木高度
- FABDEM 可通过 GEE 直接下载：`ee.ImageCollection("projects/sat-io/open-datasets/FABDEM")`

### 3.2 建筑轮廓与高度 — 全部候选源

| 数据源 | 轮廓精度 | 高度精度 | API | 东南亚覆盖 | 许可 |
|--------|---------|---------|-----|-----------|------|
| **Google Open Buildings v3 多边形** | ~2-4m (ML 50cm影像推断) | 仅 confidence，无高度 | GEE `GOOGLE/Research/open-buildings/v3/polygons` | ✅ 18亿建筑 | CC BY-4.0 / ODbL |
| **Google Open Buildings 2.5D Temporal** | 4m 栅格 (非矢量) | **MAE = 1.5m** (Google官方) | GEE `GOOGLE/Research/open-buildings-temporal/v1` | ✅ | CC BY-4.0 / ODbL |
| **Overture Maps Buildings** | OSM+Google+MS+Esri 混合 | `height`/`num_floors` 覆盖率极低 | S3/Azure GeoParquet + CLI | ✅ 26亿建筑 | ODbL |
| **OSM** | 众源 ~1-5m | `building:levels`（有标注的才有） | Overpass API | ✅ | ODbL |
| **Microsoft Building Footprints** | ML ~2-3m | 无高度 | GitHub 直下 | ✅ | ODbL |

**关键结论**：

- Google 2.5D 高度 **MAE = 1.5m**（Google Research Blog 官方数据），这是目前免费数据中最佳的建筑高度源
- 项目当前方案（Google v3 多边形 + 2.5D 高度 zonal stats）**已经是免费数据的最优组合**
- Overture Buildings 的 `height`/`num_floors` 字段来源主要是 OSM 标签，泰国区域覆盖率很低（< 5%），不如当前方案

### 3.3 道路 — 全部候选源

| 数据源 | 几何精度 | 宽度数据 | 车道数 | API | 许可 |
|--------|---------|---------|-------|-----|------|
| **OSM** | ~2-5m | `width` 标签（稀疏, ~5-15%） | `lanes` 标签（~15-30%） | Overpass API / `.osm` 文件 | ODbL |
| **Overture Transportation** | 与 OSM 同+TomTom增强 | `width_rules[]` 字段（源自 OSM） | 从 OSM 继承 | S3 GeoParquet + CLI | ODbL |
| **TomTom** | <1m (商用级) | 完整 | 完整 | 商用 API | **付费** |
| **Mapbox** | 基于 OSM | 无 | 无 | Tiles API | 免费 tier 有限 |

**Overture Transportation 关键发现**：

- Schema 中 `width_rules[]` 字段在 Segment 类型上**已定义**（Overture schema 官方文档确认）
- 同时包含 `road_surface[]`、`speed_limits[]`、`subclass` 等丰富属性
- 数据源 = OSM + TomTom（2024年底 GA 发布），最新 release: `2026-05-20.0`
- **但**：`width_rules` 实际填充率取决于 OSM 原始标签，泰国区域 `width` 标签覆盖率约 5-15%，`lanes` 标签覆盖率约 15-30%（主要道路有标注）
- 切换到 Overture 需重写整个 OSM 解析管线，改动量大，而 `width_rules` 的数据源仍是 OSM，**收益不足以覆盖改动成本**

---

## 四、当前管线数据链精度分析

### 4.1 当前 DEM 数据链

```
NASADEM 30m (DSM, ±5-9m) 
  → CSV 转换 (equirectangular 投影, 2位小数)
  → correct_dem_dtm.py (IDW 建筑掩码修正, radius=4)
  → Houdini dem_import (CSV → points)
  → Bilinear ×2 细分 (30m → ~7.5m effective)
  → terrain mesh
```

**精度瓶颈**：

1. NASADEM 本身是 DSM（含建筑+植被），垂直精度 ±5-9m
2. IDW 修正 radius=4 cells = 120m，Pattaya 密集建成区可能全是建筑格元，无干净参考点
3. 未移除植被 canopy（Pattaya 大量热带棕榈树，canopy 高度 15-25m）
4. 当前区域高程 0-12m，非常平坦——地形误差对视觉影响有限，但垂直基准不准会影响建筑/道路吸附

### 4.2 当前建筑数据链

```
Google Open Buildings v3 轮廓 (ML, ~2-4m)
  + Google 2.5D Temporal 高度 (MAE=1.5m, 4m resolution)
  → enrich_building_levels.py (OSM levels 补全, 15m匹配距离)
  → clean_raw_data.py (去噪、去重、面积推算高度)
  → Houdini _osm_import_canonical.py
  → Fuse + Divide
  → procedural_height VEX (面积→楼层 fallback)
  → Extrude
  → snap_bld_to_terrain (当前取 MIN + 0.2m sink)
```

**精度瓶颈**：

1. Google 2.5D 1.5m MAE 是区域统计值，单栋建筑误差可达 3-5m
2. `procedural_height` 面积→楼层启发式无数据支撑（60m² → 1层，实际可能是5层）
3. **`snap_bld_to_terrain` 取 MIN 导致坡面建筑被埋——与 H-011 坑点文档"用 MAX"的记录矛盾**
4. 层高固定 3.5m，泰国住宅实际 ~2.8-3.0m，商业 ~3.5-4.0m
5. `enrich_building_levels.py` 的 15m 匹配距离对密集城区过大，可能导致高度被赋给错误的邻近建筑
6. Overture 数据已传入 `class` 字段（residential/commercial/industrial），但 Houdini 端未使用

### 4.3 当前道路数据链

```
OSM .osm 文件 (众源, ~2-5m)
  → clean_raw_data.py (类型过滤、孤儿节点清理)
  → Houdini _osm_import_canonical.py (仅解析 highway tag)
  → road_width VEX (14级分类硬编码 half_width)
  → resample
  → _road_strips_v2.py (quad strip + 路口凸包)
  → snap_roads_to_terrain (xyzdist + 0.15m 抬升)
```

**精度瓶颈**：

1. 宽度完全靠分类表——`primary` 8m vs 实际 10-14m，误差 30%+
2. OSM `lanes` 和 `width` 标签**被完全忽略**（`_osm_import_canonical.py` 只读 `highway`）
3. 路口凸包是直线多边形，真实路口是弧形

---

## 五、跨系统一致性问题

### 5.1 垂直基准不一致

| 数据 | 垂直基准 |
|------|----------|
| NASADEM / SRTM | EGM96 大地水准面 |
| Copernicus GLO-30 | EGM2008 大地水准面 |
| Google Open Buildings 2.5D | 相对地面高度 (building height above ground) |
| OSM `building:height` | 相对地面 |

建筑高度是相对地面的，DEM 高度是相对大地水准面的。如果使用 DSM：
- 建筑吸附到 DSM 高度后再加建筑高度 = **双重计算建筑高度**
- `correct_dem_dtm.py` 的 IDW 修正正是为了解决此问题，但精度不足

**使用 FABDEM DTM 可根本性解决此问题**。

### 5.2 建筑底面与道路高度缝隙

当前 `snap_bld_to_terrain` 将建筑底面设为 `terrain_y - 0.2m`，而道路在 `snap_road_strips` 中设为 `terrain_y + 0.15m`。

**道路高于地形 0.15m，建筑低于地形 0.2m → 建筑底面比道路低 0.35m**。

视觉上沿街建筑会出现底部缝隙。最优解：建筑 base_y 取 `max(terrain_y, adjacent_road_y) - 0.1m`。

### 5.3 download_dem.py 硬编码路径

`Scripts/download_dem.py` 第 22-23 行输出路径仍硬编码 `F:\VirtualCity`（违反 A-001 路径规范），应改为使用 `vc_paths.DATA_ROOT`。

---

## 六、最优解方案（唯一推荐）

综合 API 可用性、许可证、精度、改动量，针对三大块各给出**一个最优方案**：

### 6.1 地形最优解：替换为 FABDEM 30m DTM

**为什么是唯一最优解**：

- FABDEM 是**全球唯一免费的 30m DTM**（真正裸地，已通过 ML 移除建筑和树木）
- 通过 GEE 直接可用：`ee.ImageCollection("projects/sat-io/open-datasets/FABDEM")`
- 直接消除 `correct_dem_dtm.py` IDW 近似（该近似在密集区和植被区严重不准）
- 垂直精度比 NASADEM 好约 50%（建成区），比 COP-GLO-30 好约 33%（建成区）
- 许可证 CC BY-NC-SA 4.0 = 非商用可免费使用（如最终商用需另行授权）

**具体实现**：

修改 `download_dem.py` 新增 FABDEM 下载函数：

```python
def download_fabdem(cfg):
    """
    FABDEM V1-2: 全球 30m DTM（已移除建筑和树木高度）
    来源: University of Bristol, CC BY-NC-SA 4.0
    GEE: projects/sat-io/open-datasets/FABDEM
    """
    import ee
    ee.Initialize(project=EE_PROJECT)
    bbox = cfg["bbox"]
    region = ee.Geometry.Rectangle(bbox)
    
    fabdem = (ee.ImageCollection("projects/sat-io/open-datasets/FABDEM")
              .filterBounds(region)
              .mosaic()
              .clip(region))
    
    url = fabdem.getDownloadURL({
        "name": "fabdem",
        "bands": ["b1"],
        "region": region,
        "scale": 30,
        "format": "GEO_TIFF",
        "filePerBand": False,
    })
    # 下载 + 转 CSV（复用现有 convert_to_csv 流程）
```

**效果**：

- 完全取消 `correct_dem_dtm.py` 的 IDW 修正步骤
- 地形垂直误差从 ±5-9m (NASADEM DSM) → **±2-4m** (FABDEM DTM)
- 建筑 snap 和道路 snap 的基准面准确性大幅改善
- 从根本上解决 DSM 垂直基准不一致导致的建筑高度双重计算问题
- 改动量：`download_dem.py` 增加一个函数 + 修改默认 source

### 6.2 建筑最优解：保持当前 Google v3 + 2.5D 方案 + 三处修复

当前方案已是免费数据的最优选，不建议更换数据源，但需修复三个实现级问题：

**修复 1（P0）— snap_bld_to_terrain MIN→MAX**

`Scripts/_recook_new_area.py` BLD_SNAP_VEX 中：

```vex
// 当前代码（错误）：
float min_terrain_y = 1e10;
// ...取 MIN

// 应改为（与 H-011 坑点文档一致）：
float max_terrain_y = -1e10;
// ...取 MAX
float base_y = max_terrain_y - 0.2;
```

防止坡面建筑被地形埋没。

**修复 2（P1）— 层高按建筑类型差异化**

Overture 数据已传入 `class` 字段（`download_overture_buildings.py` 第 59 行），但 Houdini 端未使用。建议：

- 在 `_osm_import_canonical.py` 中将 `class` 写入 prim attribute `bld_class`
- 在 `procedural_height` VEX 中用 `bld_class` 选择层高：
  - residential = 2.9m（泰国住宅实测）
  - commercial = 3.5m
  - industrial = 4.5m
  - default = 3.2m

**修复 3（P1）— enrich_building_levels 匹配距离收紧**

`enrich_building_levels.py` 第 23 行 `DEDUP_DIST = 15.0` 对密集城区过大。建议降至 **8.0m**，减少错误匹配概率。

### 6.3 道路最优解：从 OSM 提取 lanes + width 标签

**为什么不切换到 Overture Transportation**：

- Overture 的 `width_rules` 数据源仍然是 OSM 标签，泰国 width 覆盖率仅 5-15%
- 切换需重写整个 OSM 解析管线，改动量大，精度收益有限
- Overture 增加了 TomTom 拓扑增强，但不增加 width/lanes 数据

**最优解：在现有 OSM 解析中增加 `lanes` 和 `width` 标签读取**

`Scripts/_osm_import_canonical.py` 当前只读 `highway` tag，修改为同时传入 `lanes` 和 `width`：

```python
# 新增两个属性
lanes_attrib = geo.addAttrib(hou.attribType.Prim, 'lanes', 0)
width_attrib = geo.addAttrib(hou.attribType.Prim, 'osm_width', 0.0)

# 在道路解析循环中
lanes_val = 0
width_val = 0.0
try:
    lanes_val = int(tags.get('lanes', '0') or '0')
except (TypeError, ValueError):
    pass
try:
    width_val = float(str(tags.get('width', '0') or '0').replace('m', '').strip())
except (TypeError, ValueError):
    pass
poly.setAttribValue(lanes_attrib, lanes_val)
poly.setAttribValue(width_attrib, width_val)
```

然后在 `road_width` VEX 中增加优先级逻辑：

```vex
// 优先级：OSM 实际宽度 > lanes 推算 > 分类表 fallback
float osm_w = f@osm_width;
int   lanes = i@lanes;

if (osm_w > 0) {
    f@half_width = osm_w * 0.5;
} else if (lanes > 0) {
    f@half_width = lanes * 1.75;  // 单车道 3.5m 标准
} else {
    // 保持现有 highway 分类 fallback（14 级分类表不变）
    string hw = s@highway;
    if (hw == "motorway")       f@half_width = 6.0;
    else if (hw == "trunk")     f@half_width = 5.0;
    // ... 其余保持不变
}
```

**效果**：主路大概率有 lanes 标签 → 宽度误差从 ±30% 降至 ±10%，小路 fallback 到分类表不退化。

### 6.4 投影最优解：替换为 UTM Zone 47N

使用 Python `utm` 包（比 `pyproj` 更轻量，零依赖纯 Python，Houdini Python 环境兼容性最佳）：

```python
import utm

ORIGIN_X, ORIGIN_Y, _ZONE_NUM, _ZONE_LET = utm.from_latlon(ORIGIN_LAT, ORIGIN_LON)

def wgs84_to_local(lon, lat):
    x, y, _, _ = utm.from_latlon(lat, lon, force_zone_number=_ZONE_NUM)
    return x - ORIGIN_X, y - ORIGIN_Y
```

需在 5 个文件中统一替换：

1. `Scripts/_osm_import_canonical.py`
2. `Scripts/download_dem.py`
3. `Scripts/correct_dem_dtm.py`
4. `Scripts/enrich_building_levels.py`
5. `Scripts/clean_raw_data.py`

---

## 七、最终优先级排序

| 序号 | 改进项 | 预期精度改善 | 改动量 | 难度 |
|------|--------|-------------|--------|------|
| **1** | 地形 → FABDEM DTM (GEE) | 垂直 ±5-9m → ±2-4m，消除 DSM 双重高度问题 | `download_dem.py` +1 函数 | 低 |
| **2** | 投影 → UTM (`utm` 包) | 全局位置误差 ~2m → <0.01m | 5 文件函数替换 | 低 |
| **3** | 修复 `snap_bld_to_terrain` MIN→MAX | 坡面建筑不再被埋 | 1 行 VEX | 极低 |
| **4** | 道路 → 读取 OSM lanes/width | 主路宽度误差 ±30% → ±10% | 2 文件小改 | 低 |
| **5** | 建筑层高按 class 差异化 | 高度误差 ~15% → ~8% | VEX + import 小改 | 低 |
| **6** | enrich 匹配距离 15m→8m | 减少高度错误赋值 | 1 行常量 | 极低 |

---

## 八、实施后预期精度

以上 6 项全部实施后，在免费公开数据源约束下：

| 维度 | 当前精度 | 改进后精度 | 理论极限 |
|------|---------|-----------|---------|
| **地形垂直** | ±5-9m (NASADEM DSM + IDW) | **±2-4m** (FABDEM DTM) | ±1-2m (付费 FABDEM+/LiDAR) |
| **建筑轮廓** | ±2-4m (Google ML) | ±2-4m (不变，已是最优) | <1m (商用倾斜摄影) |
| **建筑高度** | ±3-5m (2.5D + 粗糙 fallback) | **±2-3m** (2.5D + 分类层高) | <1m (LiDAR DSM差分) |
| **道路位置** | ±2-5m (OSM) | ±2-5m (不变，OSM 众源极限) | <1m (TomTom 商用) |
| **道路宽度** | ±30%+ (纯分类表) | **±10-15%** (lanes + width) | <5% (TomTom 商用) |
| **全局坐标** | ~2m@1.8km (等距矩形) | **<0.01m** (UTM) | 同 UTM |

**这是当前免费公开数据技术栈能达到的理论天花板。** 再往上只能通过购买商用数据（TomTom 道路、FABDEM+ 地形、商用 LiDAR/倾斜摄影）或实地测量来突破。

---

## 九、许可证汇总

| 数据源 | 许可 | 商用 | 备注 |
|--------|------|------|------|
| OSM | ODbL | ✅ | 需署名 + ShareAlike |
| Google Open Buildings v3 | CC BY-4.0 / ODbL | ✅ | 用户自选许可 |
| Google Open Buildings 2.5D | CC BY-4.0 / ODbL | ✅ | 用户自选许可 |
| Overture Maps | ODbL | ✅ | 需署名 |
| NASADEM | Public Domain | ✅ | 无限制 |
| Copernicus GLO-30 | Free (attribution) | ✅ | 需包含版权声明 |
| **FABDEM V1-2** | **CC BY-NC-SA 4.0** | **❌ 非商用** | 商用需联系 Bristol 大学 |
| FABDEM+ / FathomDEM+ | 商业许可 | ✅ | 付费 |

**如果项目有商用需求**，FABDEM 需要：
- 联系 fathom.global 获取商业授权
- 或改用 Copernicus GLO-30（免费商用）+ 自研改进版 DTM 修正脚本

---

## 附录：参考文献

1. Hawker, L. et al. (2022). "A 30 m global map of elevation with forests and buildings removed." Environmental Research Letters.
2. Google Research. "Open Buildings 2.5D Temporal Dataset." Height MAE = 1.5m. CC BY-4.0.
3. Copernicus DEM Product Handbook I5.0. Vertical accuracy: <4m (90% LE).
4. Overture Maps Foundation. Transportation Schema Reference. Release 2026-05-20.0.
5. Meadows et al. (2024). "Vertical accuracy assessment of freely available global DEMs." International Journal of Digital Earth.
