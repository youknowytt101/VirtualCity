# OSM 到 Houdini 道路素模工作流

> 目标：从真实 OSM 道路数据获取开始，经过 Python 清洗、投影、属性标准化，最终在 Houdini 里生成可用道路素模。
>
> 本文和 `01_CityEngine道路生成逻辑复刻指南.md` 的关系：01 讲“从零程序化生长道路”，本文讲“已有真实 OSM 道路 -> Houdini 建模管线”。两者可以共用后半段 road graph / road topology / road mesh 逻辑。

## 1. 总体评审结论

这套 “OSM 数据获取 -> 清洗转换 -> Python 中间处理 -> Houdini 节点建模” 方案方向正确，而且更接近独立道路模块的真实数据落地路径。

需要保留：

- OSMnx 或 Overpass 获取真实道路。
- WGS84 经纬度转米制局部坐标。
- 清洗 `highway / lanes / width / oneway / geometry`。
- 输出 Houdini 可读的中间格式。
- Houdini 内用 Python SOP 建中心线，再用拓扑/宽度节点生成道路面。

需要修正：

- OSMnx 2.x 的 `graph_from_bbox` 推荐传单个 `bbox=(left, bottom, right, top)`，不是旧版 `north/south/east/west` 参数。
- 道路模块必须有统一坐标模块，例如 `road_coords.py`。新脚本不要各自写一套 `Vector3(x, 0, -y)`，应统一走 `LocalProjector` 和 `local_to_houdini()`。
- Houdini 的 PolyWire 更适合管线/圆截面，不适合扁平道路面。道路素模建议优先用 `road_surface_builder` / Sweep / 自定义 offset 面片。
- 交叉口不建议依赖 VDB Union 做主方案。VDB 会丢属性、破坏拓扑、让材质分层变难。可以作为快速预览方案，但生产管线应使用路口裁剪和 junction fan。
- OSM 道路是 graph，CSV 两张表可用，但 GeoJSON/road_graph.json 更利于保留折线、属性和后续测试。

## 2. 推荐管线

```text
DataProvider
  -> OSMnxProvider / OverpassProvider / TomTomProvider / HereProvider / MapboxProvider
  -> roads_raw.geojson
  -> clean_pipeline.py
  -> WGS84 -> 道路模块局部米制数据域 (x, z)
  -> roads_clean.geojson
  -> road_graph.json
  -> Houdini Python SOP 导入中心线
  -> width/profile 属性
  -> road_surface_builder 生成道路条带 + 路口面
  -> drape / cut-fill / material groups
  -> OUT_roads
```

建议道路模块拆出这些通用组件：

- `providers/base.py`：`DataProvider` 抽象接口和统一输出契约。
- `providers/osmnx_provider.py`：开发期免费数据源，适合快速迭代。
- `providers/overpass_provider.py`：免费数据源，适合原始 XML 缓存和离线复现。
- `providers/tomtom_provider.py` / `providers/here_provider.py`：付费数据源适配层，只改字段映射，不改清洗主线。
- `schemas/roads_raw_contract.md`：`roads_raw.geojson` 字段契约。
- `clean_pipeline.py`：只负责清洗、投影、字段标准化和质量报告，不关心数据来源。
- `io/osm_download.py`：Overpass 下载 OSM XML。
- `io/osmnx_import.py`：OSMnx graph 获取和标准化。
- `core/road_coords.py`：WGS84、局部米制、Houdini 坐标转换的唯一权威。
- `core/road_graph.py`：道路图结构、宽度、路口样式、冲突短边分析。
- `mesh/road_surface_builder.py`：道路中心线转道路面片和路口 fan。
- `backends/houdini/`：Houdini Python SOP、VEX、节点模板。

### 2.1 DataProvider 抽象接口

早期可以用免费 API 跑通管线，管线成熟后再换付费 API。但 OSMnx、Overpass、TomTom、HERE、Mapbox 不应该直接喂给下游清洗脚本；它们必须先适配成同一个 `roads_raw.geojson` 契约。

推荐接口：

```python
class DataProvider:
    provider_name: str

    def fetch(self, area: AreaSpec, cache: CacheStore) -> ProviderResult:
        """获取或恢复原始数据，返回本次运行的原始文件路径和元数据。"""

    def normalize(self, result: ProviderResult, output: Path) -> None:
        """把数据源私有字段映射到 roads_raw.geojson 契约。"""
```

Provider 只做三件事：

1. 获取或恢复原始数据。
2. 保留原始供应商字段到 `provider_tags`。
3. 输出统一字段名，供 `clean_pipeline.py` 继续处理。

下游 `clean_pipeline.py` 不应该 import `osmnx`、`requests` 或任何付费 SDK。换数据源时，只新增或替换 Provider。

### 2.2 `roads_raw.geojson` 输出契约

所有 Provider 都输出 `FeatureCollection`，geometry 使用 WGS84 经纬度 `LineString` 或 `MultiLineString`，属性至少包含：

| 字段 | 类型 | 含义 |
|---|---|---|
| `source_provider` | string | `osmnx` / `overpass` / `tomtom` / `here` / `mapbox` |
| `source_feature_id` | string | 原始道路 ID，例如 OSM way id 或供应商 link id |
| `highway` | string | 归一化前的道路等级，缺失时可为空 |
| `road_class` | string | 模块内部道路等级，允许先为空，由清洗阶段补齐 |
| `name` | string | 道路名称 |
| `lanes` | int/string | 原始车道数，允许字符串，清洗阶段转 int |
| `width_m` | float/string | 原始道路宽度，清洗阶段转 float |
| `oneway` | bool/string | 单向信息 |
| `maxspeed` | int/string | 限速，可选 |
| `turn_restrictions` | array/string | 转弯限制，可选，付费源通常更完整 |
| `provider_tags` | object | 供应商原始字段快照 |

`roads_clean.geojson` 再保证以下字段已经可直接用于 Houdini：

```json
{
  "seg_id": 101,
  "highway": "primary",
  "road_class": "primary",
  "lanes": 2,
  "osm_width": 12.0,
  "half_width": 6.0,
  "oneway": false,
  "length_m": 183.4,
  "source_provider": "overpass"
}
```

付费 API 和 OSM 的关键差异通常集中在三类字段：车道数、转弯限制、道路宽度。字段映射表应放在 Provider 或 schema 层：

```python
FIELD_MAP = {
    "tomtom": {
        "lanes": ["numberOfLanes", "laneInfo.count"],
        "width_m": ["roadWidth", "widthMeters"],
        "turn_restrictions": ["restrictions.turns"],
    },
    "here": {
        "lanes": ["lanes.count"],
        "width_m": ["physicalWidth"],
        "turn_restrictions": ["access.turnRestriction"],
    },
    "osm": {
        "lanes": ["lanes"],
        "width_m": ["width"],
        "turn_restrictions": ["restriction"],
    },
}
```

### 2.3 缓存和版本化目录

调道路宽度、路口裁剪、Houdini 参数时会频繁重跑管线。原始请求必须缓存，尤其是未来接入付费 API 后，避免每次 cook 都重新计费。

推荐目录：

```text
pipeline/
  cache/
    raw/
      osm/
        {area_id}_{bbox_hash}_v{date}.osm
      osmnx/
        {area_id}_{bbox_hash}_v{date}.graphml
      tomtom/
        {area_id}_{bbox_hash}_v{date}.json
      here/
        {area_id}_{bbox_hash}_v{date}.json
    processed/
      {area_id}_roads_raw_{provider}_{hash}.geojson
      {area_id}_roads_clean_{hash}.geojson
      {area_id}_road_graph_{hash}.json
  reports/
    {area_id}_pipeline_report_{timestamp}.json
```

缓存 key 至少包含：

- `area_id`
- bbox 或 polygon hash
- provider 名称和版本
- query 参数 hash
- 字段映射版本
- 清洗参数 hash

### 2.4 `pipeline_report.json`

清洗阶段不能只“跳过坏数据”，必须记录跳过了什么。建议每次运行输出：

```json
{
  "area_id": "pattaya_sai6_mvp",
  "provider": "overpass",
  "input_ways": 3842,
  "output_features": 3701,
  "skipped": {
    "no_geometry": 12,
    "too_short": 18,
    "unknown_highway": 111,
    "self_intersection": 3
  },
  "warnings": [
    "27 edges missing width, using defaults",
    "3 edges with self-intersection detected"
  ],
  "outputs": {
    "roads_raw": "pipeline/cache/processed/pattaya_roads_raw_overpass_abc123.geojson",
    "roads_clean": "pipeline/cache/processed/pattaya_roads_clean_def456.geojson",
    "road_graph": "pipeline/cache/processed/pattaya_road_graph_def456.json"
  }
}
```

这个报告是后续切换付费 API 时的对比基线：如果 TomTom 输出道路数、宽度缺失率或转弯限制覆盖率明显变化，可以直接从报告里定位。

## 3. 阶段 1：数据获取

### 3.1 方式 A：OSMnx

OSMnx 适合快速获取道路网络并直接得到 NetworkX graph。

安装：

```bash
uv add osmnx geopandas shapely pyproj
```

按城市名获取：

```python
import osmnx as ox

G = ox.graph_from_place(
    "Shinjuku, Tokyo, Japan",
    network_type="drive",
    retain_all=False,
    truncate_by_edge=True,
)
```

按 bbox 获取。OSMnx 2.x 推荐：

```python
import osmnx as ox

# bbox = (left, bottom, right, top) = (west, south, east, north)
bbox = (139.6900, 35.6750, 139.7200, 35.6950)

G = ox.graph_from_bbox(
    bbox,
    network_type="drive",
    retain_all=False,
    truncate_by_edge=True,
)
```

如果使用旧版 OSMnx，可能仍是 `north, south, east, west` 参数。写工具脚本时建议检测版本：

```python
import osmnx as ox
from packaging.version import parse

if parse(ox.__version__) >= parse("2.0.0"):
    G = ox.graph_from_bbox((west, south, east, north), network_type="drive")
else:
    G = ox.graph_from_bbox(north, south, east, west, network_type="drive")
```

按 polygon 获取：

```python
from shapely.geometry import box
import osmnx as ox

polygon = box(139.6900, 35.6750, 139.7200, 35.6950)
G = ox.graph_from_polygon(polygon, network_type="drive")
```

推荐保存原始图，方便复现：

```python
ox.save_graphml(G, "roads_raw.graphml")
```

### 3.2 方式 B：Overpass API

Overpass 更适合做独立数据获取层，便于控制 query、缓存原始 XML，并和后续清洗流程解耦。

```python
import requests
from pathlib import Path

overpass_url = "https://overpass-api.de/api/interpreter"

# Overpass bbox 顺序: south, west, north, east
s, w, n, e = 35.6750, 139.6900, 35.6950, 139.7200

query = f"""
[out:xml][timeout:120];
(
  way["highway"]({s},{w},{n},{e});
);
out body;
>;
out skel qt;
""".strip()

resp = requests.post(
    overpass_url,
    data={"data": query},
    headers={"User-Agent": "RoadResearch/1.0"},
    timeout=180,
)
resp.raise_for_status()
Path("roads_raw.osm").write_bytes(resp.content)
```

推荐保留多个 Overpass 服务器 fallback：

```python
OVERPASS_SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
```

### 3.3 network_type 选择

```text
drive       机动车道路，适合城市道路素模主流程
walk        步行网络，含 footway/path
bike        自行车网络
all         全部可通行路径，噪声较多
all_private 包括私有道路，通常不建议默认使用
```

MVP 推荐 `drive`，后续再单独叠加 `walk` 或 `footway`。

## 4. 阶段 2：Python 清洗与投影

### 4.1 坐标约定

独立道路模块必须定义唯一坐标模块，例如 `core/road_coords.py`：

```text
数据域: (x, z)
  x = 东向米制
  z = 北向米制

Houdini 域: (x, y, -z)
  只允许在 road_coords.local_to_houdini() / LocalProjector.to_houdini() 内翻 z
```

不要在数据处理脚本里散落写：

```python
hou.Vector3(x, 0.0, -y)
```

应统一写：

```python
from road_coords import LocalProjector, local_to_houdini

proj = LocalProjector(origin_lon, origin_lat)
x, z = proj.to_local(lon, lat)
hx, hy, hz = local_to_houdini(x, z)
```

### 4.2 OSMnx Provider 输出示例

下面是可作为 `providers/osmnx_provider.py` 起点的版本。注意它输出的是 `roads_raw.geojson`，字段尽量保留原貌；宽度、车道和道路等级的最终归一化由 `clean_pipeline.py` 负责。

```python
from __future__ import annotations

import json
from pathlib import Path

import osmnx as ox


def osmnx_to_roads_raw(bbox: tuple[float, float, float, float], output: Path) -> None:
    west, south, east, north = bbox
    G = ox.graph_from_bbox(
        bbox,
        network_type="drive",
        retain_all=False,
        truncate_by_edge=True,
    )

    _nodes, edges = ox.graph_to_gdfs(G)

    features = []
    for idx, row in edges.reset_index().iterrows():
        geom = row.get("geometry")
        if geom is None:
            continue

        coords_wgs84 = []
        for lon, lat in geom.coords:
            coords_wgs84.append([float(lon), float(lat)])

        if len(coords_wgs84) < 2:
            continue

        props = {
            "source_provider": "osmnx",
            "source_feature_id": f'{row.get("u", "")}-{row.get("v", "")}-{row.get("key", idx)}',
            "highway": row.get("highway", ""),
            "road_class": "",
            "name": row.get("name", ""),
            "lanes": row.get("lanes", ""),
            "width_m": row.get("width", ""),
            "oneway": row.get("oneway", ""),
            "maxspeed": row.get("maxspeed", ""),
            "length_m": float(row.get("length", 0.0) or 0.0),
            "provider_tags": {
                "u": str(row.get("u", "")),
                "v": str(row.get("v", "")),
                "key": str(row.get("key", "")),
                "osmid": row.get("osmid", ""),
            },
        }
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords_wgs84},
            "properties": props,
        })

    fc = {
        "type": "FeatureCollection",
        "metadata": {
            "schema": "roads_raw.geojson",
            "coord_domain": "WGS84",
            "axes": "lon, lat",
            "source_provider": "osmnx",
            "bbox_wsen": [west, south, east, north],
        },
        "features": features,
    }
    output.write_text(json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")
```

### 4.3 Overpass XML Provider

如果已经有 `.osm` XML，可以直接解析成同一份 `roads_raw.geojson` 契约：

```python
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path


def overpass_xml_to_roads_raw(osm_file: Path, output: Path) -> None:
    tree = ET.parse(osm_file)
    root = tree.getroot()

    nodes = {}
    for nd in root.findall("node"):
        nid = nd.get("id")
        nodes[nid] = (float(nd.get("lon")), float(nd.get("lat")))

    features = []
    for way in root.findall("way"):
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        highway = tags.get("highway")
        if not highway:
            continue

        coords = []
        for nr in way.findall("nd"):
            ref = nr.get("ref")
            if ref not in nodes:
                continue
            lon, lat = nodes[ref]
            coords.append([float(lon), float(lat)])

        if len(coords) < 2:
            continue

        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "source_provider": "overpass",
                "source_feature_id": way.get("id"),
                "highway": highway,
                "road_class": "",
                "name": tags.get("name", ""),
                "lanes": tags.get("lanes", ""),
                "width_m": tags.get("width", ""),
                "oneway": tags.get("oneway", ""),
                "maxspeed": tags.get("maxspeed", ""),
                "bridge": tags.get("bridge", ""),
                "tunnel": tags.get("tunnel", ""),
                "turn_restrictions": [],
                "provider_tags": tags,
            },
        })

    output.write_text(json.dumps({
        "type": "FeatureCollection",
        "metadata": {
            "schema": "roads_raw.geojson",
            "coord_domain": "WGS84",
            "axes": "lon, lat",
            "source_provider": "overpass",
            "source_file": str(osm_file),
        },
        "features": features,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
```

### 4.4 `clean_pipeline.py` 字段标准化

`clean_pipeline.py` 的输入只有 `roads_raw.geojson`，输出 `roads_clean.geojson` 和 `pipeline_report.json`。核心逻辑：

```python
def clean_pipeline(raw_geojson: Path, output_geojson: Path, report_path: Path, params: CleanParams) -> None:
    fc = json.loads(raw_geojson.read_text(encoding="utf-8"))
    proj = LocalProjector(params.origin_lon, params.origin_lat)
    report = PipelineReport(area_id=params.area_id, provider=fc["metadata"]["source_provider"])
    features = []

    for feat in fc.get("features", []):
        geom = feat.get("geometry") or {}
        props = feat.get("properties") or {}

        coords_wgs84 = flatten_line_geometry(geom)
        if len(coords_wgs84) < 2:
            report.skip("no_geometry")
            continue

        highway = normalize_highway(props.get("highway"))
        if highway is None:
            report.skip("unknown_highway")
            continue

        coords_local = [proj.to_local(lon, lat) for lon, lat in coords_wgs84]
        coords_local = remove_duplicate_points(coords_local, params.merge_epsilon)
        if polyline_length(coords_local) < params.min_length_m:
            report.skip("too_short")
            continue

        lanes = normalize_lanes(props.get("lanes"), highway)
        width = normalize_width(props.get("width_m"), highway, lanes)

        features.append(make_clean_feature(
            coords_local=coords_local,
            source_props=props,
            highway=highway,
            lanes=lanes,
            width=width,
        ))

    write_roads_clean(output_geojson, features, params)
    report.output_features = len(features)
    report_path.write_text(report.to_json(), encoding="utf-8")
```

清洗阶段要集中处理：

- `LineString` / `MultiLineString` 展平。
- 空 geometry、重复点、过短线段、自交叉线段。
- `highway` 等级映射。
- `lanes`、`width_m`、`oneway` 的类型归一化。
- `width_m > lanes > highway fallback` 的宽度优先级。

## 5. 阶段 3：中间格式选择

### 5.1 推荐格式

优先顺序：

1. `roads_raw.geojson`：Provider 统一输出契约，保留 WGS84 geometry 和供应商原始字段。
2. `roads_clean.geojson`：清洗后局部米制中心线，保留折线和 Houdini 可用属性。
3. `road_graph.json`：保留 nodes/edges/topology，适合后续路口、block、QA。
4. `road_nodes.csv + road_edges.csv`：Houdini 简单读入方便，但拓扑信息容易丢。

推荐输出：

```text
pipeline/cache/raw/<provider>/<area_id>_<bbox_hash>_v<date>.<ext>
pipeline/cache/processed/<area_id>_roads_raw_<provider>_<hash>.geojson
pipeline/cache/processed/<area_id>_roads_clean_<hash>.geojson
pipeline/cache/processed/<area_id>_road_graph_<hash>.json
pipeline/reports/<area_id>_pipeline_report_<timestamp>.json
```

### 5.2 CSV 格式

如果要走两张 CSV，建议字段如下。

`road_nodes.csv`：

```csv
node_id,x,z,y,degree
```

`road_edges.csv`：

```csv
edge_id,node_from,node_to,highway,road_width,half_width,lanes,length_m,oneway,polyline_xz
```

`polyline_xz` 用 JSON 字符串：

```json
[[0.0, 0.0], [10.5, 3.2], [24.0, 8.1]]
```

注意字段名使用 `x,z`，不要用 `x,y` 表示平面坐标，以免和 Houdini 的 Y-up 混淆。

## 6. 阶段 4：Houdini 导入

### 6.1 Python SOP：从 GeoJSON 建中心线

这个版本直接读 `roads_clean.geojson`。输入坐标已经是道路模块数据域 `(x, z)`。

```python
import hou
import json

from road_coords import local_to_houdini

node = hou.pwd()
geo = node.geometry()
geo.clear()

geo.addAttrib(hou.attribType.Prim, "highway", "")
geo.addAttrib(hou.attribType.Prim, "osm_width", 0.0)
geo.addAttrib(hou.attribType.Prim, "half_width", 0.0)
geo.addAttrib(hou.attribType.Prim, "lanes", 0)
geo.addAttrib(hou.attribType.Prim, "length_m", 0.0)
geo.addAttrib(hou.attribType.Prim, "oneway", 0)
geo.addAttrib(hou.attribType.Prim, "seg_id", -1)

road_group = geo.createPrimGroup("roads")

path_parm = node.parm("geojson_path")
if path_parm is None:
    raise hou.NodeError("Missing required parameter: geojson_path")

path = hou.expandString(path_parm.eval())
with open(path, encoding="utf-8") as f:
    fc = json.load(f)

for i, feat in enumerate(fc.get("features", [])):
    geom = feat.get("geometry") or {}
    props = feat.get("properties") or {}
    if geom.get("type") != "LineString":
        continue

    coords = geom.get("coordinates") or []
    if len(coords) < 2:
        continue

    poly = geo.createPolygon(is_closed=False)
    for x, z in coords:
        pt = geo.createPoint()
        pt.setPosition(hou.Vector3(*local_to_houdini(float(x), float(z))))
        poly.addVertex(pt)

    highway = str(props.get("highway", "unclassified") or "unclassified")
    width = float(props.get("osm_width", 0.0) or 0.0)
    lanes = int(props.get("lanes", 0) or 0)
    if width <= 0:
        width = max(4.0, lanes * 3.2) if lanes > 0 else 6.0

    poly.setAttribValue("highway", highway)
    poly.setAttribValue("osm_width", width)
    poly.setAttribValue("half_width", width * 0.5)
    poly.setAttribValue("lanes", lanes)
    poly.setAttribValue("length_m", float(props.get("length_m", 0.0) or 0.0))
    poly.setAttribValue("oneway", 1 if str(props.get("oneway", "")).lower() in ("1", "true", "yes") else 0)
    poly.setAttribValue("seg_id", int(props.get("seg_id", i) or i))
    road_group.add(poly)
```

### 6.2 Houdini 节点树：推荐版

```text
geo_roads
  python_import_roads_geojson
    -> attribwrangle_width_fallback
    -> road_surface_builder_python_sop
    -> resample_corridor_edges_or_subdivide_surface
    -> road_drape_to_terrain
    -> normal
    -> OUT_roads
```

不要在 `road_surface_builder` 之前对中心线做 Resample。路口裁剪依赖道路端点精确落在 graph node 上，提前重采样会制造额外端点或轻微漂移，导致 junction 裁剪、T 字路识别和 dead-end cap 不稳定。

如果需要更密的面片用于贴地、法线或材质插值，应在道路面生成之后处理：

- 对 corridor quads 沿道路方向细分。
- 对外边界线做 Resample 后再生成 curb。
- 对最终 mesh 用 Subdivide/Remesh，但保留 `seg_id`、`is_junction`、`vc_part` 等属性。

其中 `road_surface_builder_python_sop` 应实现：

```text
mesh/road_surface_builder.py
```

它已经做了：

- 从中心线端点构建 adjacency graph。
- 识别 degree >= 3 的 junction。
- 按宽度和夹角动态裁剪路口。
- 输出道路 corridor quads。
- 输出 junction fan polygon。
- dead-end cap。

HDA 层面建议暴露参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| `geojson_path` | file | 当前区域 `roads_clean.geojson`，不要在 Python SOP 中硬写 `$HIP/roads_clean.geojson` |
| `road_graph_path` | file | 可选，已有拓扑图时优先读 `road_graph.json` |
| `junction_radius` | float | 路口 fan 基础半径 |
| `min_junction_angle` | float | 路口裁剪最小夹角 |
| `build_curbs` | toggle | 是否生成路缘石 |
| `debug_junctions` | toggle | 输出路口调试属性和点 |

外部管线脚本只需要修改 HDA 参数即可批量处理不同区域：

```python
node.parm("geojson_path").set("$HIP/../RawData/GIS_Processed/pattaya_roads_clean.geojson")
node.parm("junction_radius").set(6.0)
node.cook(force=True)
```

### 6.3 Houdini 节点树：快速预览版

如果只是快速看道路素模，可以用 Sweep：

```text
python_import_roads_geojson
  -> resample1
  -> polyframe1
  -> sweep1
  -> normal1
  -> OUT_roads_preview
```

Sweep 横截面是一条宽度为 1 的线，然后按 `half_width` 缩放。

注意：快速预览版路口会重叠，不适合作为最终 mesh。

## 7. 宽度属性

Primitive Wrangle：

```c
string hw = prim(0, "highway", @primnum);
float w = prim(0, "osm_width", @primnum);
int lanes = prim(0, "lanes", @primnum);

if (w <= 0) {
    if (lanes > 0) {
        w = lanes * 3.2;
    } else {
        if      (hw == "motorway")    w = 28.0;
        else if (hw == "trunk")       w = 22.0;
        else if (hw == "primary")     w = 16.0;
        else if (hw == "secondary")   w = 12.0;
        else if (hw == "tertiary")    w = 9.0;
        else if (hw == "residential") w = 6.0;
        else if (hw == "service")     w = 4.0;
        else                          w = 6.0;
    }
}

f@osm_width = w;
f@half_width = w * 0.5;
f@road_half_width = f@half_width;
```

独立模块中建议把更完整版本沉淀为：

```text
backends/houdini/road_width.vex
```

优先复用它。

## 8. 路口处理

### 8.1 不推荐作为主方案：VDB Union

VDB Union 可以快速把重叠路面融成一张网格：

```text
sweep
  -> vdbfrompolygons
  -> vdbreshape dilate
  -> vdbreshape erode
  -> convertvdb
```

但缺点明显：

- 道路等级、材质、车道属性容易丢。
- 交叉口拓扑不可控。
- 边缘会被体素化，素模可以，生产网格不够干净。
- 后续分人行道/车道线更麻烦。

只建议用于 preview 或远景。

### 8.2 推荐主方案：路口裁剪 + Junction Fan

使用 `road_surface_builder` 的思路：

```text
centerline + half_width
  -> build endpoint graph
  -> classify junction
  -> trim road ends by clip_margin
  -> emit corridor quads
  -> gather boundary points around junction
  -> radial sort
  -> emit junction fan polygon
```

路口裁剪距离：

```python
clip_margin = neighbor_half_width / (2 * sin(min_angle)) + junction_radius
```

这样比 VDB 合并更适合后续材质、车道、人行道和 UE 导入。

### 8.3 `road_surface_builder` 核心算法

`road_surface_builder` 是整条 Houdini 道路素模管线里风险最高的部分，应该单独实现、单独测试。它至少拆成四步：

1. 从中心线 primitive 构建 endpoint graph。
2. 为每条 edge 计算端点处方向、宽度和裁剪距离。
3. 输出 road corridor quads。
4. 为 degree >= 3 的 node 输出 junction fan polygon。

推荐内部结构：

```python
@dataclass
class RoadEdge:
    seg_id: int
    points: list[Vec2]
    half_width: float
    highway: str
    lanes: int


@dataclass
class EdgeEnd:
    edge: RoadEdge
    node_id: str
    direction_out: Vec2
    angle: float
    half_width: float
    clip_margin: float = 0.0
```

构建 adjacency 时不要用浮点坐标直接当 key，先做端点量化：

```python
def node_key(p: Vec2, eps: float = 0.05) -> tuple[int, int]:
    return (round(p.x / eps), round(p.z / eps))
```

#### 8.3.1 端点方向

道路折线在路口处的方向要取靠近端点的第一段，而不是整条折线首尾方向：

```python
def direction_at_node(edge: RoadEdge, node_pos: Vec2) -> Vec2:
    pts = edge.points
    if distance(pts[0], node_pos) < distance(pts[-1], node_pos):
        return normalize(pts[1] - pts[0])
    return normalize(pts[-2] - pts[-1])
```

`direction_out` 表示从路口向道路外走的方向。后续 corridor 裁剪点是：

```python
trimmed_center = node_pos + direction_out * clip_margin
```

#### 8.3.2 路口裁剪距离

对每个 node，把 incident edges 按 `angle = atan2(direction_out.z, direction_out.x)` 排序。某条 edge 的裁剪距离由它和左右相邻 edge 的夹角共同决定：

```python
def compute_clip_margin(edge_end, prev_end, next_end, params):
    a0 = angle_between(edge_end.direction_out, prev_end.direction_out)
    a1 = angle_between(edge_end.direction_out, next_end.direction_out)
    min_angle = max(params.min_junction_angle, min(a0, a1))
    neighbor_hw = max(edge_end.half_width, prev_end.half_width, next_end.half_width)
    return neighbor_hw / max(0.25, 2.0 * sin(min_angle)) + params.junction_radius
```

要给上限，避免锐角路口裁剪过长：

```python
clip_margin = min(clip_margin, edge.length * 0.45, params.max_clip_margin)
```

如果 edge 很短，两端裁剪距离相加超过长度，应进入短边降级策略：

- 合并到较大的相邻路口。
- 或把该 edge 标记为 `skipped_short_connector`，在报告里记录。
- MVP 可先把两端裁剪比例压缩到总长的 80%。

#### 8.3.3 Corridor Quads

每条 polyline 先按两个端点的 clip margin 裁剪中心线，再对裁剪后的折线做左右 offset，输出道路条带。

```python
def build_corridor(edge, trim_start, trim_end):
    centerline = trim_polyline(edge.points, trim_start, trim_end)
    left = offset_polyline(centerline, +edge.half_width)
    right = offset_polyline(centerline, -edge.half_width)
    return Polygon(left + list(reversed(right)))
```

属性：

```text
is_junction = 0
vc_part = "road_surface"
seg_id = edge.seg_id
highway = edge.highway
half_width = edge.half_width
lanes = edge.lanes
```

MVP 阶段可以让 corridor 是一整张 polygon；后续为了 drape 和材质插值，再沿 centerline 分段输出 quads。

#### 8.3.4 Junction Fan

Junction Fan 的核心是收集所有 incident edge 在路口附近的左右边界点，并按角度排序生成一张路口面。

```python
def build_junction_fan(node_pos: Vec2, edge_ends: list[EdgeEnd], params) -> Polygon:
    boundary_pts = []

    sorted_ends = sorted(edge_ends, key=lambda e: e.angle)
    for e in sorted_ends:
        d = e.direction_out
        n_left = rotate90(d)
        n_right = -n_left
        c = node_pos + d * e.clip_margin

        right_pt = c + n_right * e.half_width
        left_pt = c + n_left * e.half_width

        boundary_pts.append(right_pt)
        boundary_pts.append(left_pt)

    boundary_pts = sort_by_angle_around(node_pos, boundary_pts)
    poly = Polygon(boundary_pts)

    if poly.is_self_intersecting():
        return fallback_triangle_fan(node_pos, boundary_pts)

    return poly
```

输出属性：

```text
is_junction = 1
vc_part = "junction_surface"
junction_id = node_id
junction_degree = len(edge_ends)
```

不建议把 `node_pos` 作为 polygon 第一个顶点直接生成 `[center] + boundary_pts` 的单个 n-gon。Houdini polygon 本身只需要边界环；如果要三角扇，应该显式输出多个 triangle，并把中心点作为共享点。

#### 8.3.5 Dead-End Cap

degree == 1 的端点不需要 junction fan，但需要 cap：

```python
def build_dead_end_cap(node_pos, edge_end, style):
    if style == "straight":
        return straight_cut_cap(edge_end)
    if style == "bevel45":
        return bevel_cap(edge_end, angle=45)
    if style == "round":
        return arc_cap(edge_end, segments=6)
```

MVP 推荐 `straight`，精致素模阶段再做 `round` 或 `bevel45`。

#### 8.3.6 单元测试用例

至少覆盖：

- 十字路口：4 条等宽道路输出 4 个 corridor + 1 个 junction fan。
- T 字路：3 条道路 fan 无自交。
- 斜交路口：锐角处 clip margin 有上限。
- 宽窄路交汇：junction fan 能覆盖窄路和宽路边界。
- dead-end：端点有 cap，且没有生成 junction。
- 短 connector：两端裁剪不超过道路长度。

### 8.4 pscale 放大端点的限制

用 `pscale *= 1.2` 放大路口点可以遮住小缝，但它不是拓扑正确的交叉口：

- 无法保证面片无自交。
- 无法处理宽窄路交汇。
- 无法保留干净的路口边界。
- 对 T 字路和斜交路口很容易出奇怪形状。

只能作为 preview hack。

## 9. 路缘石生成方案

### 9.1 总体评审

从已有 `OUT_roads` mesh 上提取外边缘，再沿边缘 Sweep 路缘石截面，是可行的 Houdini 工作流。它比从中心线重新算 curb 更快，也能自然跟随已经裁剪好的道路边界。

但直接使用：

```text
Group Unshared Edges -> Extract Edges -> Sweep
```

会有几个风险：

- `road_surface_builder` 输出通常包含 corridor quads、dead-end caps、junction fan。所有外露边都会被选中，路口 fan 边界和道路外轮廓会混在一起。
- 如果道路 mesh 在路口处已经 watertight，路口内部边不会被选中，但路口外轮廓仍会被选中。是否需要给路口外圈做 curb，要按城市风格决定。
- 只靠 PolyFrame 的 `N` 不一定能保证截面朝道路外侧。
- Attribute Transfer 会把路面属性传给边缘线，但 junction 面的 `highway` 通常是 `junction`，可能导致路缘石高度/材质丢失道路等级。
- Sweep 后再按 `@P.y *= h / 0.15` 会把地形高度也缩放掉。如果道路已经贴地，不应该缩放世界 Y，而应沿局部截面高度方向调整。

因此，推荐把它作为“可执行方案”，但要加两个补丁：

1. 提边前先按 `is_junction`、`highway`、面积等属性决定哪些面参与 curb。
2. 提边后计算每条边相对道路面的外侧方向，给 Sweep 提供稳定的 `N/up/tangentu`。

### 9.2 推荐节点树

接在 `OUT_roads` 后面：

```text
OUT_roads
  -> blast_filter_curb_source
  -> group_boundary_edges
  -> extract_edges
  -> attribute_transfer_from_roads
  -> polyframe_edge_frame
  -> wrangle_fix_curb_outward
  -> sweep_curb_profile
  -> wrangle_set_curb_attrs
  -> normal
  -> OUT_curb
```

最终合并：

```text
OUT_roads
OUT_curb
  -> merge
  -> material
  -> OUT_street_complete
```

### 9.3 选择 curb 来源面

如果 roads mesh 来自 `road_surface_builder`，建议至少包含这些 primitive 属性：

- `is_junction`
- `half_width`
- `highway`
- `seg_id`
- `from_node`
- `to_node`
- `road_face_area`

建议先保留常规道路 corridor，按需求决定是否保留 junction：

```c
// Primitive Wrangle or Blast condition
// 方案 A：只从普通道路边生成 curb，不从路口 fan 生成
if (i@is_junction == 1) {
    removepoint(0, @ptnum);
}
```

上面在 Primitive Wrangle 里不合适，因为 `@ptnum` 不存在。更推荐用 Blast SOP：

```text
Group Expression:
@is_junction==1
Delete Non Selected: off
```

或者在 Primitive Wrangle 里：

```c
if (i@is_junction == 1) {
    removeprim(0, @primnum, 1);
}
```

如果想让路口外圈也有 curb，可以保留 junction，但要接受路口处 curb 可能形成复杂闭环。MVP 推荐先排除 junction。

### 9.4 Group SOP：选择外边缘

```text
Group Type: Edges
Group Name: boundary_edges
Base Group: 留空或使用上一步过滤后的全部面
Include By Edges: Unshared Edges
```

Unshared Edges 的含义是只有一侧有 polygon 的边，通常就是道路外轮廓。

### 9.5 Extract Edges SOP

```text
Input Group: boundary_edges
Connectivity: Connected
```

如果 Extract 后碎段太多，可以加：

```text
Fuse SOP: 0.01m
Polypath SOP: 合并连续线段
Clean SOP: Remove Degenerate
```

### 9.6 属性传递

Attribute Transfer：

```text
Input 0: edge polylines
Input 1: OUT_roads
Transfer Primitive Attributes: highway half_width seg_id is_junction
Max Search Distance: 0.5
```

推荐统一属性名为 `highway`。如果外部方案使用 `highway_type`，建议在导入时统一映射：

```c
// Primitive Wrangle
if (s@highway == "" && s@highway_type != "") {
    s@highway = s@highway_type;
}
```

### 9.7 截面 Profile

Python SOP 创建路缘石截面：

```python
import hou

geo = hou.pwd().geometry()
geo.clear()

pts = [
    (0.00, 0.00, 0.0),  # road edge
    (0.00, 0.15, 0.0),  # curb front top
    (0.12, 0.15, 0.0),  # curb top back
    (0.12, 0.05, 0.0),  # sidewalk side
]

poly = geo.createPolygon()
poly.setIsClosed(False)
for pos in pts:
    pt = geo.createPoint()
    pt.setPosition(hou.Vector3(*pos))
    poly.addVertex(pt)
```

建议初始尺寸：

```text
curb_height: 0.12-0.18m
curb_depth:  0.10-0.18m
sidewalk_y:  0.04-0.08m
```

### 9.8 外侧方向修正

仅用 `road_center = {0,0,0}` 判断内外是不可靠的。道路可能不围绕世界原点，环路和弯路也会判断错。

更稳的办法：

1. 从 `OUT_roads` 计算每个 edge polyline 点附近最近道路 primitive。
2. 取 edge 点到该 primitive 中心的向量，作为“从道路内部指向边缘”的方向参考。
3. 如果 Sweep 的 `N` 指向道路内部，就翻转。

Point Wrangle，输入 0 为 edge polylines，输入 1 为 OUT_roads：

```c
int prim;
vector uvw;
float d = xyzdist(1, @P, prim, uvw);
vector c = primuv(1, "P", prim, {0.5, 0.5, 0});
vector outward_hint = normalize(@P - c);

vector tangent = normalize(v@tangentu);
if (length(tangent) < 1e-4) {
    tangent = normalize(@P - point(0, "P", max(@ptnum - 1, 0)));
}

vector side = normalize(cross({0,1,0}, tangent));

if (dot(side, outward_hint) < 0) {
    side *= -1;
}

v@N = side;
v@up = {0,1,0};
```

前面需要 PolyFrame SOP：

```text
Tangent Attribute: tangentu
Normal Attribute: N
Correct for Twist: on
```

### 9.9 Sweep SOP

```text
Input 0: boundary edge polylines
Input 1: curb profile
Orient Cross-section to Path: on
Use N/up/tangentu attributes if available
Scale: 1.0
End Caps: off
```

如果发现截面朝内，优先翻转 `N`，不要手动旋转 profile 到碰巧可用。

### 9.10 高度按道路等级调整

不要在 Sweep 后直接缩放世界坐标 `@P.y`。如果道路已经贴地，`@P.y *= h / 0.15` 会连地形高度一起缩放。

更好的做法是在 Sweep 前给 profile 或 path 设置 `curb_height` 属性，或者在 Sweep 后只移动相对底边高度。最简单的 MVP 方案是做多个 profile：

```text
motorway/trunk: 0.20m
primary/secondary: 0.15m
residential/service: 0.10m
```

如果一定要在 Sweep 后处理，需要先记录每个点的 base_y：

```c
// Sweep 前在 path 点上
f@base_y = @P.y;
```

Sweep 后：

```c
string hw = prim(0, "highway", @primnum);
float target_h = 0.15;

if (hw == "motorway" || hw == "trunk") {
    target_h = 0.20;
} else if (hw == "residential" || hw == "service") {
    target_h = 0.10;
}

float base_y = point(0, "base_y", @ptnum);
float rel_y = @P.y - base_y;
@P.y = base_y + rel_y * (target_h / 0.15);
```

注意：Sweep 后点号不一定能可靠对应 Sweep 前 path 点。生产级建议在 profile 上按参数生成目标高度，而不是事后缩放。

### 9.11 材质

Merge 前分别设置材质更稳定：

Road branch:

```c
s@shop_materialpath = "/mat/road_surface";
s@vc_part = "road_surface";
```

Curb branch:

```c
s@shop_materialpath = "/mat/curb_concrete";
s@vc_part = "curb";
```

### 9.12 QA 检查

路缘石生成后检查：

- `OUT_curb` primitive 数量 > 0。
- curb 高度在 0.08m 到 0.25m 之间。
- curb 没有明显朝道路内部生长。
- 路口处没有大量交叉穿插。
- `vc_part=curb` 材质属性存在。
- 与道路 mesh 合并后法线方向正确。

## 10. 完整执行清单

### 10.1 MVP 跑通标准与精致标准

“精致素模”需要拆成两个里程碑。第一步先做可用，保证整条链路跑通；第二步再追求路口和边缘质量。

| 要素 | MVP 可用标准 | 精致素模标准 |
|---|---|---|
| 路面 | 中心线 Sweep 或 corridor 条带，允许少量路口重叠 | Junction Fan 裁剪，路口无明显空洞和重叠 |
| 路缘石 | 从外边界 Sweep，允许路口处简化 | 外侧方向稳定，路口处截断干净 |
| Dead-end | 直切 cap | 圆弧 cap 或 45 度收口 |
| 法线 | 朝上且无黑面 | 边缘硬边、路面平滑、路缘石法线稳定 |
| 属性 | `highway`、`width`、`seg_id` | `highway`、`width`、`lanes`、`seg_id`、`is_junction`、`vc_part`、`source_provider` |
| 报告 | 能记录输入/输出数量 | 能记录 skip 原因、宽度 fallback、短边降级和自交警告 |

建议先把 `DataProvider -> clean_pipeline -> Houdini import -> road_surface_builder -> OUT_roads` 作为第一里程碑。路口裁剪稳定后，再进入路缘石、人行道、标线和材质分层。

### 10.2 OSMnx 路线

```text
1. 选择 bbox / place / polygon
2. OSMnxProvider 获取 / 恢复 GraphML 缓存
3. normalize -> roads_raw.geojson
4. clean_pipeline 标准化 highway / lanes / width
5. road_coords.LocalProjector 投影到 (x,z)
6. 输出 roads_clean.geojson + pipeline_report.json
7. Houdini Python SOP 从 geojson_path 导入
8. road_surface_builder 生成道路面
```

### 10.3 Overpass 路线

```text
1. build Overpass query
2. OverpassProvider 获取 / 恢复 .osm XML 缓存
3. xml.etree.ElementTree 解析 node / way
4. 过滤 way["highway"]
5. normalize -> roads_raw.geojson
6. clean_pipeline 投影到 (x,z)，输出 roads_clean.geojson 或 road_graph.json
7. 写 pipeline_report.json
8. Houdini Python SOP 从 geojson_path 导入
9. road_surface_builder 生成道路面
```

### 10.4 付费 Provider 切换路线

```text
1. 新增 TomTomProvider / HereProvider / MapboxProvider
2. 在 Provider 内完成 SDK/API 调用和原始响应缓存
3. 按 roads_raw.geojson 契约输出统一字段
4. 在 FIELD_MAP 中补 lanes / width / turn_restrictions 映射
5. 用同一套 clean_pipeline 生成 roads_clean.geojson
6. 对比 pipeline_report.json，确认道路数、宽度缺失率、车道覆盖率变化
7. Houdini 端不改节点树，只替换 geojson_path 或 road_graph_path
```

## 11. QA 检查

Python 处理后检查：

```python
assert len(features) > 0
assert all(len(f["geometry"]["coordinates"]) >= 2 for f in features)
assert all("highway" in f["properties"] for f in features)
assert all(float(f["properties"].get("osm_width", 0) or 0) >= 0 for f in features)
```

Provider 契约检查：

- 所有 Provider 输出 `roads_raw.geojson`。
- `roads_raw.geojson` geometry 为 WGS84，经纬度没有提前转 Houdini。
- 每条 feature 有 `source_provider` 和 `source_feature_id`。
- `provider_tags` 保留原始字段，便于追查供应商差异。
- 同一 bbox、同一参数二次运行命中 cache，不重复请求 API。

`pipeline_report.json` 检查：

- `input_ways` / `output_features` 数量合理。
- `skipped.no_geometry`、`skipped.too_short`、`skipped.unknown_highway` 有计数。
- 宽度 fallback 数量被记录。
- 自交、短 connector、缺失车道等 warning 被记录。
- 报告写入当前区域和缓存 hash。

空间检查：

- 总道路数。
- highway 类型分布。
- 坐标范围是否符合 bbox 尺度。
- 是否有超长异常边。
- 是否有空 geometry。
- 是否有重复 edge。

Houdini 检查：

- 中心线 primitive 数量 > 0。
- 所有道路 primitive 有 `highway`。
- 所有道路 primitive 有 `half_width > 0`。
- `road_surface_builder` 输出 polygon 数量 > 0。
- 路口处没有大面积重叠或空洞。

## 12. 可选工程适配层

独立道路模块不应该把某个工程的脚本路径作为默认前提。推荐的结构是：

```text
road_module/
  io/
  core/
  mesh/
  backends/houdini/
  adapters/
    project_a_adapter.py
    project_b_adapter.py
```

适配层只负责：

1. 读取工程自己的区域配置、路径配置和坐标原点。
2. 把工程数据转换为道路模块标准输入：`roads_clean.geojson` / `road_graph.json`。
3. 调用道路模块的核心算法和 Houdini 后端。
4. 把输出 mesh、材质、报告写回工程指定目录。

道路模块的主流程保持不变：

```text
DataProvider
  -> roads_raw.geojson
  -> clean_pipeline.py
  -> roads_clean.geojson
  -> road_graph.json
  -> road_surface_builder
  -> OUT_roads / OUT_curb / OUT_street_complete
```

这样同一套道路研究成果可以接入不同项目，而不是和某个工程深度绑定。

## 13. 参考资料

- OSMnx 文档：`https://osmnx.readthedocs.io/`
- Overpass API 文档：`https://wiki.openstreetmap.org/wiki/Overpass_API`
- Overpass QL 文档：`https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL`
- Houdini Python SOP 文档：`https://www.sidefx.com/docs/houdini/hom/hou/SopNode.html`
- Houdini Geometry HOM 文档：`https://www.sidefx.com/docs/houdini/hom/hou/Geometry.html`
