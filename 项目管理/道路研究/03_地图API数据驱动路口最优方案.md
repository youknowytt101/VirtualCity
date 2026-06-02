# 地图 API 数据驱动路口最优方案

> 目标：把“引用地图 API 道路数据，追求当前能达到的最高质量道路效果”整理成一套长期可落地的路口架构。
>
> 本文不是 CityEngine 复刻文档，也不是单纯 Houdini 路面素模方案。本文关注：如何把 OSM / Mapbox / HERE / TomTom / HD Map 等道路数据，整理成车道级路口语义，再用 Houdini 生成高质量道路几何。

## 1. 总体结论

地图 API 数据驱动的高质量路口，不应以 `Junction Fan` 作为主算法。`Junction Fan` 只适合做路口面填充、MVP 素模或语义缺失时的降级。

长期最优解应该是：

```text
地图 API / HD Map 数据
  -> DataProvider 统一契约
  -> road_graph.json
  -> lane_graph.json
  -> OpenDRIVE-inspired junction model
  -> junction connections / laneLinks / turn paths
  -> Houdini procedural geometry
  -> roads / curbs / sidewalks / markings / islands
```

核心变化：

- 从“中心线扩宽成路面”升级为“车道级拓扑驱动路口”。
- 从“路口 fan polygon”升级为“connection curves + lane surfaces + junction envelope fill”。
- 从“只看起来不破洞”升级为“每条车道知道如何进出路口”。

OpenDRIVE 在这里不是直接可用的 mesh 算法，而是最重要的 schema 参考：`junction -> connection -> connecting road -> laneLink`。我们不需要第一版完整实现 `.xodr`，但内部 `road_graph.json` / `lane_graph.json` 应该向这个结构靠拢。

## 2. 为什么不是只做 Junction Fan

当前 `road_surface_builder` 的 `Junction Fan` 逻辑可以解决：

- 多条道路中心线在路口相交后，路面不重叠。
- 路口没有明显空洞。
- 素模阶段道路面连成一体。
- Houdini 中有 `is_junction`、`seg_id`、`vc_part` 等属性。

但它解决不了高质量地图 API 道路的关键问题：

- 入口车道能否左转、直行、右转。
- 哪条入口车道接哪条出口车道。
- 转弯车道、合流车道、导流岛、渠化路口。
- 环岛、匝道、复杂多路口。
- 车道线、停止线、斑马线、箭头标线。
- 信号灯、优先权、禁转、限速、道路标牌。

所以最终定位应是：

```text
Junction Fan = 几何填充 / fallback / preview
Lane-level junction model = 高质量路口主算法
```

## 3. 目标效果分级

| 等级 | 数据模型 | 几何效果 | 适用阶段 |
|---|---|---|---|
| L0 Preview | 中心线 + width | Sweep / corridor，路口允许重叠 | 快速看范围 |
| L1 Clean Mesh | road graph + Junction Fan | 路口干净无洞，路缘石可用 | 当前 Houdini 素模 |
| L2 Semantic Junction | road graph + junction connections | 路口知道 from/to movement | 高质量城市道路 |
| L3 Lane-level | lane graph + laneLinks | 车道面、转弯路径、车道线 | 车辆 AI / 仿真 |
| L4 HD Road | HD Map / OpenDRIVE-compatible | 信号、标线、导流岛、道路对象 | 最高质量 / 仿真级 |

本文推荐目标是 L3，长期兼容 L4。

## 4. 数据源策略

### 4.1 数据源优先级

如果追求最高效果，数据源按能力排序：

1. **HD Map / 自动驾驶级地图**
   - 最强，可能包含车道边界、信号灯、停止线、标牌、车道级连接。
   - 成本和授权门槛最高。

2. **HERE / TomTom 等商业道路属性数据**
   - 适合构建高质量 road graph。
   - 通常能提供更可靠的道路等级、方向、限速、转弯限制、路口属性。

3. **Mapbox Streets / OSM / Overpass**
   - 适合开发期和中高质量视觉城市。
   - 车道数、宽度、禁转、交通控制信息覆盖不稳定。

4. **Google Roads API**
   - 更适合轨迹贴路、最近道路、限速辅助。
   - 不适合作为完整道路网络主数据源。

### 4.2 Provider 不直接进 Houdini

所有地图 API 都必须先经过 Provider 统一输出：

```text
Provider
  -> roads_raw.geojson
  -> semantic_clean_pipeline
  -> road_graph.json
  -> lane_graph.json
```

Houdini 不应该知道数据来自 OSM、HERE 还是 TomTom。这样换数据源时，Houdini 节点树和几何后端不需要重做。

## 5. 总体架构

```text
DataProvider
  OSMnxProvider
  OverpassProvider
  MapboxProvider
  HereProvider
  TomTomProvider
  HDMapProvider
        |
        v
roads_raw.geojson
  WGS84 geometry
  provider_tags
  source_feature_id
        |
        v
semantic_clean_pipeline.py
  normalize class / lanes / width / oneway
  turn restrictions
  coordinate projection
  topology cleanup
        |
        v
road_graph.json
  roads / nodes / widths / profiles
        |
        v
lane_model_builder.py
  lane centerlines
  lane boundaries
  lane ids
        |
        v
lane_graph.json
  lane topology
  junctions
  connections
  laneLinks
        |
        v
houdini_junction_builder
  approach ribbons
  turn paths
  lane surfaces
  junction envelope fill
  markings / curbs / sidewalks
```

## 6. 关键数据结构

### 6.1 `road_graph.json`

`road_graph.json` 表达道路级拓扑，不到车道级：

```json
{
  "roads": [
    {
      "road_id": "r_001",
      "source_provider": "here",
      "source_feature_id": "link_1001",
      "geometry_xz": [[0.0, 0.0], [80.0, 4.0], [160.0, 10.0]],
      "from_node": "n_001",
      "to_node": "n_002",
      "road_class": "primary",
      "oneway": false,
      "lanes_forward": 2,
      "lanes_backward": 2,
      "width_m": 15.0,
      "speed_limit_kph": 50,
      "turn_restrictions": []
    }
  ],
  "nodes": [
    {
      "node_id": "n_002",
      "position_xz": [160.0, 10.0],
      "incident_roads": ["r_001", "r_002", "r_003"],
      "kind": "junction_candidate"
    }
  ]
}
```

### 6.2 `lane_graph.json`

`lane_graph.json` 表达车道级拓扑：

```json
{
  "lanes": [
    {
      "lane_id": "r_001_f_1",
      "road_id": "r_001",
      "direction": "forward",
      "index": 1,
      "centerline_xz": [[0.0, 3.6], [80.0, 7.6], [160.0, 13.6]],
      "left_boundary_xz": [],
      "right_boundary_xz": [],
      "width_m": 3.5,
      "allowed_turns": ["left", "straight"]
    }
  ],
  "junctions": []
}
```

### 6.3 OpenDRIVE-inspired `junction`

路口 schema 推荐向 OpenDRIVE 的 connection / laneLink 思想靠拢：

```json
{
  "junction_id": "j_001",
  "center_xz": [160.0, 10.0],
  "incident_roads": ["r_001", "r_002", "r_003", "r_004"],
  "envelope_polygon_xz": [],
  "connections": [
    {
      "connection_id": "c_001",
      "from_road": "r_001",
      "to_road": "r_003",
      "turn": "left",
      "allowed": true,
      "restriction_source": "provider",
      "connecting_curve_xz": [],
      "lane_links": [
        {
          "from_lane": "r_001_f_1",
          "to_lane": "r_003_f_1",
          "confidence": 0.92
        }
      ]
    }
  ],
  "control": {
    "type": "signalized",
    "stop_lines": [],
    "crosswalks": []
  }
}
```

关键字段：

- `connections`：道路级 movement，例如从北向南直行、从西向南右转。
- `lane_links`：车道级连接关系。
- `connecting_curve_xz`：Houdini 生成转弯车道面的参考线。
- `envelope_polygon_xz`：路口整体填充边界，用于铺路面、裁剪路缘石。
- `control`：信号灯、停止线、斑马线、优先权等。

## 7. 路口求解流程

### 7.1 检测路口区域

路口不是单个点，而是一个区域。检测流程：

```text
road graph nodes
  -> cluster close nodes
  -> classify degree >= 3
  -> include nearby short connectors
  -> build junction candidate
```

需要处理：

- OSM 中一个真实路口可能由多个很近的 node 表达。
- 双向分隔道路可能形成多个相邻交点。
- 匝道或辅路可能被错误当成普通十字路。

建议参数：

```text
junction_cluster_radius: 8-25m
short_connector_threshold: 5-30m
min_junction_degree: 3
```

### 7.2 建立入口和出口

对每个路口，按道路方向判断：

```text
incoming approach
outgoing approach
bidirectional approach
```

每个 approach 要记录：

- road_id
- approach direction
- road class
- lane count
- one-way
- turn restrictions
- incoming lane ids
- outgoing lane ids

### 7.3 推断 movement

movement 是“从哪条路到哪条路”的道路级连接：

```python
def infer_movements(junction):
    for incoming in junction.incoming_approaches:
        for outgoing in junction.outgoing_approaches:
            if incoming.road_id == outgoing.road_id:
                continue
            turn = classify_turn(incoming.direction, outgoing.direction)
            if violates_turn_restriction(incoming, outgoing, turn):
                continue
            yield Movement(incoming, outgoing, turn)
```

转向分类：

```text
angle delta near 0       -> straight
angle delta positive     -> left
angle delta negative     -> right
angle delta near 180     -> u_turn
```

规则优先级：

1. Provider 明确给出的 turn restriction / turn lane。
2. 道路方向和 one-way。
3. 道路等级和几何夹角。
4. 默认交通规则。

### 7.4 生成 laneLinks

laneLink 是高质量路口的核心。

```python
def infer_lane_links(movement):
    incoming_lanes = movement.incoming.allowed_lanes_for(movement.turn)
    outgoing_lanes = movement.outgoing.compatible_lanes(movement.turn)

    if provider_lane_links_exist(movement):
        return provider_lane_links(movement)

    return match_by_lane_order(incoming_lanes, outgoing_lanes, movement.turn)
```

默认匹配规则：

- 直行：按车道顺序一一匹配。
- 右转：优先最右侧车道接目标道路最右侧车道。
- 左转：优先最左侧车道接目标道路最左侧车道。
- 多车道转弯：保持相对车道顺序。
- 数据不足时，生成低置信度 laneLink，并写入报告。

### 7.5 生成 connecting curves

每个 laneLink 都应生成一条转弯参考线：

```text
incoming lane centerline trimmed end
  -> tangent continuity
  -> connecting curve
  -> outgoing lane centerline trimmed start
```

推荐曲线策略：

| 情况 | 曲线 |
|---|---|
| 直行 | line 或轻微 cubic |
| 普通转弯 | cubic Bezier |
| 高质量驾驶路径 | arc + clothoid approximation |
| 匝道 / 高速连接 | clothoid / spiral 优先 |

MVP 可以先用 cubic Bezier：

```python
def build_turn_curve(p0, t0, p1, t1, radius_hint):
    d = max(distance(p0, p1) * 0.35, radius_hint)
    c0 = p0 + normalize(t0) * d
    c1 = p1 - normalize(t1) * d
    return cubic_bezier(p0, c0, c1, p1)
```

高质量阶段再升级为 clothoid / spiral，避免车辆路径曲率突变。

### 7.6 生成 junction envelope

路口 envelope 是路面整体填充边界：

```text
approach trim boundaries
  -> collect lane boundary endpoints
  -> add corner arcs / islands
  -> polygon cleanup
  -> envelope_polygon_xz
```

`Junction Fan` 可作为 envelope fallback，但成熟方案应使用 lane boundary、corner radius 和 traffic island 一起决定 envelope。

## 8. Houdini 几何生成

Houdini 后端应从 `lane_graph.json` 生成几何，而不是直接从原始 API 数据生成。

### 8.1 推荐节点/模块

```text
python_import_lane_graph
  -> build_approach_road_surfaces
  -> build_junction_connection_surfaces
  -> build_junction_envelope_fill
  -> build_lane_markings
  -> build_crosswalks_stoplines
  -> build_curbs_sidewalks_islands
  -> drape_to_terrain
  -> normal_material_groups
  -> OUT_street_complete
```

### 8.2 Approach road surfaces

普通道路段按 lane boundaries 生成，而不是只按 road width 生成：

```text
lane boundary left/right
  -> lane surface polygon
  -> road surface group
  -> lane marking source curves
```

### 8.3 Junction connection surfaces

每个 laneLink 生成一条 lane ribbon：

```text
connecting_curve
  -> offset by lane_width / 2
  -> turn lane surface
```

多条 turn lane surface 合并或保留分组：

```text
vc_part = "junction_lane"
junction_id = "j_001"
connection_id = "c_001"
from_lane = "r_001_f_1"
to_lane = "r_003_f_1"
turn = "left"
```

### 8.4 Junction envelope fill

connection surfaces 之间可能有小空隙，使用 envelope fill 填充：

```text
envelope_polygon
  - union(connection surfaces)
  -> fill remaining road surface
```

如果没有可靠 laneLink，降级：

```text
incident roads
  -> trim back
  -> Junction Fan
```

### 8.5 Markings / curbs / sidewalks / islands

高质量道路必须把这些作为独立输出：

- lane markings：实线、虚线、导向箭头。
- stop lines：停止线。
- crosswalks：斑马线。
- curbs：路缘石。
- sidewalks：人行道。
- medians：中央分隔带。
- traffic islands：导流岛。

这些不应写死在 road surface builder 里，而应从 lane graph / junction model 的语义属性派生。

## 9. 降级策略

地图 API 数据质量不稳定，必须分级降级。

```text
HD lane links available
  -> 直接使用 provider laneLinks

turn restrictions available, lanes available
  -> 推断 movement + laneLinks

only lanes / one-way available
  -> 几何夹角推断 movement

only centerlines available
  -> road_surface_builder + Junction Fan

bad topology / no width
  -> preview sweep + report warning
```

每一次降级都必须写入 `pipeline_report.json`：

```json
{
  "junctions": {
    "total": 124,
    "lane_level": 38,
    "movement_inferred": 61,
    "fan_fallback": 22,
    "failed": 3
  },
  "warnings": [
    "j_045 missing turn restriction, inferred from geometry",
    "j_087 lane count missing, used road class defaults",
    "j_102 used Junction Fan fallback"
  ]
}
```

## 10. QA 标准

### 10.1 拓扑 QA

- 每个 junction 至少有 2 个 approach。
- 每个 allowed movement 至少有 1 条 laneLink。
- laneLink 的 `from_lane` 和 `to_lane` 必须存在。
- one-way 道路不得生成逆向 movement。
- 禁转关系不得生成 laneLink。
- lane graph 不应有孤立 lane，除非标记为 dead_end。

### 10.2 几何 QA

- lane surface polygon 非空。
- turn curve 与入口/出口 lane tangent 连续。
- connection surfaces 不应大面积自交。
- junction envelope 应覆盖所有 connection surfaces。
- approach trim 后不能出现明显空洞。
- curb 不应穿过 junction lane surface。

### 10.3 视觉 QA

- 十字路、T 字路、斜交路口、环岛、匝道分别抽样检查。
- 左转车道和右转车道曲线方向正确。
- 车道线在路口处合理中断或延续。
- 斑马线位置不与车辆转弯路径冲突。
- 导流岛和人行道不侵入车行道。

### 10.4 数据质量 QA

- 车道数覆盖率。
- 宽度覆盖率。
- turn restriction 覆盖率。
- signal / stop / crosswalk 覆盖率。
- fallback 到 Junction Fan 的路口比例。

## 11. 实施路线

### M0：保留现有素模主线

```text
roads_clean.geojson
  -> road_surface_builder
  -> corridor quads + Junction Fan
```

目标：

- 继续保证 Houdini 能稳定输出干净路面。
- `Junction Fan` 作为 fallback 保留。
- 建立 `is_junction`、`vc_part`、`seg_id` 等属性。

### M1：新增 junction schema

```text
road_graph.json
  -> junctions[]
  -> connections[]
```

目标：

- 每个路口知道 incident roads。
- 推断道路级 left / straight / right movement。
- 加入禁转限制。
- 暂不生成 lane-level mesh。

### M2：新增 lane graph

```text
road_graph.json
  -> lane_model_builder
  -> lane_graph.json
```

目标：

- 按 lanes / width / road_class 生成 lane centerlines。
- 建立 lane ids。
- 推断 laneLinks。
- 输出连接曲线。

### M3：Houdini lane-level junction builder

```text
lane_graph.json
  -> lane ribbons
  -> turn connection surfaces
  -> junction envelope fill
```

目标：

- 路口从 fan 面升级为 connection surfaces。
- 生成车道面、转弯面、路口填充面。
- 保留 fallback 到 Junction Fan。

### M4：道路细节

目标：

- lane markings。
- stop lines。
- crosswalks。
- curbs / sidewalks / islands。
- medians / shoulders。
- traffic signals / signs placeholder。

### M5：OpenDRIVE 互操作

目标：

- 导入 `.xodr`。
- 导出 OpenDRIVE-inspired 数据。
- 与 RoadRunner / CARLA / 仿真工具建立转换通道。

注意：M5 不应阻塞 M1-M4。内部 schema 先向 OpenDRIVE 靠拢，等结构稳定后再做完整 `.xodr` 兼容。

## 12. 和现有文档的关系

### 与 `01_CityEngine道路生成逻辑复刻指南.md`

01 主要解决路线 B：程序化道路从零生长。本文不依赖 CityEngine 生长算法。

共用点：

- road graph。
- topology cleanup。
- local constraints 的事务式思想。
- road graph 到 mesh 后端。

差异：

- 01 的重点是生成道路中心线。
- 本文的重点是地图 API 数据进入后的车道级路口语义和几何生成。

### 与 `02_OSM到Houdini道路素模工作流.md`

02 是路线 A 的 MVP 到精致素模工作流。本文是 02 的长期升级路线。

02 中：

```text
DataProvider -> roads_clean.geojson -> road_surface_builder -> OUT_roads
```

本文升级为：

```text
DataProvider -> road_graph.json -> lane_graph.json -> lane-level junction builder -> OUT_street_complete
```

`road_surface_builder` 继续保留，但定位从主算法变为：

- approach road surface builder。
- simple junction fallback。
- envelope fill fallback。

## 13. 最小内部模块拆分

推荐新增：

```text
road_module/
  providers/
    base.py
    osmnx_provider.py
    overpass_provider.py
    here_provider.py
    tomtom_provider.py
  core/
    road_graph.py
    lane_graph.py
    junction_model.py
    turn_rules.py
  pipeline/
    semantic_clean_pipeline.py
    lane_model_builder.py
    junction_solver.py
  mesh/
    approach_surface_builder.py
    junction_connection_surface.py
    junction_envelope.py
    road_markings.py
    curbs_sidewalks.py
  backends/
    houdini/
      import_lane_graph.py
      build_street_complete.py
  reports/
    pipeline_report.py
  tests/
    test_turn_rules.py
    test_lane_links.py
    test_junction_solver.py
    test_connection_curves.py
```

## 14. 推荐决策

1. 不追求“完全复刻 CityEngine 路口算法”。CityEngine 内部算法不可见，且它不是地图 API 数据驱动最高质量方案的最佳目标。
2. 不把 `Junction Fan` 当最终主算法。它继续作为 fallback 和素模填充工具。
3. 用 OpenDRIVE 思想设计内部 schema，但不一开始完整实现 `.xodr`。
4. 把路线 A 的目标升级为 `road_graph -> lane_graph -> junction connections -> Houdini geometry`。
5. Provider 层必须可替换，早期 OSM / Mapbox，后期 HERE / TomTom / HD Map。
6. 每个降级都写入报告，保证数据质量和几何质量可追踪。

## 15. 参考资料

- ASAM OpenDRIVE 标准总览：`https://www.asam.net/standards/detail/opendrive/`
- ASAM OpenDRIVE Junction Connecting Roads：`https://publications.pages.asam.net/standards/ASAM_OpenDRIVE/ASAM_OpenDRIVE_Specification/latest/specification/12_junctions/12_04_connecting_roads.html`
- ASAM OpenDRIVE Geometries：`https://publications.pages.asam.net/standards/ASAM_OpenDRIVE/ASAM_OpenDRIVE_Specification/latest/specification/09_geometries/09_01_introduction.html`
- HERE Map Attributes 文档：`https://docs.here.com/map-attributes/docs/maps-and-layers`
- Mapbox Streets v8 文档：`https://docs.mapbox.com/data/tilesets/reference/mapbox-streets-v8/`
- Google Roads API 文档：`https://developers.google.com/maps/documentation/roads/overview`
- A/B Street geometry 文档：`https://a-b-street.github.io/docs/tech/map/geometry/index.html`
- SideFX Labs Road Generator：`https://www.sidefx.com/docs/houdini/nodes/sop/labs--road_generator.html`
