# Road Test Pipeline

> 独立道路研究测试管线。这个目录只服务 `项目管理/道路研究`，不读写 VirtualCity 主管线的 `RawData/`、`Config/`、`Scripts/`、`Houdini/` 输出。

## 目标

用一个 500m x 500m 的代表性道路样本，独立研究：

- 免费地图 API 数据质量。
- 道路断点、吸附、相交切分、路口聚类。
- `roads_raw.geojson -> road_graph.json -> lane_graph.json` 的升级路线。
- `Junction Fan` fallback 和 lane-level junction model 的差异。

## 隔离规则

- 不 import 外部 `Scripts/` 下的工程模块。
- 不写入外部 `RawData/`、`Reports/`、`Config/`。
- 所有输入输出都留在本目录。
- 网络下载只进入 `data/raw/`。
- 派生数据只进入 `data/processed/`。
- 质量报告只进入 `reports/`。

## 目录结构

```text
road_test_pipeline/
  README.md
  config/
    pattaya_central_500m.area.json
  data/
    raw/
    processed/
  reports/
  scripts/
    download_overpass.py
```

## 第一个测试区

测试区：`pattaya_central_500m`

选择理由：

- 位于芭提雅中心海滩和 Second Road 附近。
- 500m 范围内包含主路、支路、小巷、商业街区和多个普通路口。
- 适合测试免费道路数据的断点、道路等级、oneway、lanes、turn restriction 覆盖情况。
- 适合作为 `road_graph -> junction_solver -> Houdini geometry` 的第一块研究样本。

## 运行方式

### 双击 Houdini 自动构建

这个入口服务两种情况：

```text
情况 A：第一次开启道路测试
1. 用户手动打开 Houdini
2. Houdini Textport 打开 command port
3. 双击 RUN_HOUDINI_ROAD_TEST.bat
4. 当前 Houdini 场景自动创建道路测试节点并 cook

情况 B：迭代中刷新道路测试
1. Houdini 已经打开
2. 用户双击同一个入口
3. 独立测试管线自动重跑 repair / QA / preview
4. Houdini 中同名 road_test 节点被替换并刷新 cook
```

先手动打开 Houdini。第一次使用时，需要在 Houdini 里打开 command port：

```text
openport 18888
```

位置：Houdini **Textport / HScript 命令行**，不是 Python Shell。运行后可以再输入：

```text
openport
```

如果端口成功打开，它会列出当前端口。也可以在 Python Source Editor 运行：

```python
exec(open(r"D:/VirtualCity/项目管理/道路研究/road_test_pipeline/scripts/enable_command_port_in_houdini.py", encoding="utf-8").read())
```

只要当前 Houdini 会话开着这个端口，下面的双击入口就会把道路测试直接构建到当前 Houdini 场景和视口里。

直接双击：

```text
RUN_HOUDINI_ROAD_TEST.bat
```

它会自动：

1. 查找 Houdini，默认优先 `D:\houdini21`。
2. 如果 `data/processed/pattaya_central_500m_roads_raw.geojson` 不存在，先用 Overpass 下载样本。
3. 运行 `topology_repair.py`，生成 repaired GeoJSON。
4. 分析 repaired roads。
5. 运行 topology repair 自动 QA。
6. 生成 standalone preview 文件。
7. 用 `hcommand` 连接当前 Houdini 的 `18888` 端口。
8. 在当前场景中创建 / 更新道路测试节点并 cook。

生成的 Houdini 节点在：

```text
/obj/road_test_pattaya_central_500m
  python_import_roads_raw
  OUT_centerlines
  python_build_preview_surfaces
  python_debug_junction_candidates
  OUT_roads_preview
```

这只是独立道路研究预览 cook，不会调用主管线的 Houdini 文件或 HDA，也不会清空或保存你当前打开的 HIP。它只会替换同名测试节点：

```text
/obj/road_test_pattaya_central_500m
```

每次双击都会写运行日志：

```text
reports/last_run.log
reports/pattaya_central_500m_open_session_cook_report.json
```

### 命令行下载数据

在 `D:/VirtualCity` 下运行：

```powershell
python "项目管理/道路研究/road_test_pipeline/scripts/download_overpass.py" --config "项目管理/道路研究/road_test_pipeline/config/pattaya_central_500m.area.json"
```

输出：

```text
road_test_pipeline/data/raw/<area_id>_roads.osm
road_test_pipeline/data/raw/<area_id>.overpassql
road_test_pipeline/data/processed/<area_id>_roads_raw.geojson
road_test_pipeline/reports/<area_id>_download_report.json
```

### 命令行构建 Houdini 测试

如果不想双击，也可以用 hython 离线生成一个独立 HIP：

```powershell
D:/houdini21/bin/hython.exe "项目管理/道路研究/road_test_pipeline/scripts/houdini_build_road_test.py" --root "项目管理/道路研究/road_test_pipeline" --config "项目管理/道路研究/road_test_pipeline/config/pattaya_central_500m.area.json"
```

输出：

```text
road_test_pipeline/houdini/pattaya_central_500m_road_test.hip
road_test_pipeline/reports/pattaya_central_500m_houdini_cook_report.json
```

## 当前阶段

这个测试管线先只做数据获取和基础统计，不做主管线级 Houdini cook。后续再逐步加入：

1. raw roads 自动 QA。
2. topology repair。
3. junction clustering。
4. road_graph builder。
5. lane_graph builder。
6. Houdini 独立测试 HDA。

## 自动 QA

QA 规则：

```text
qa/qa_rules.json
```

公共工具：

```text
scripts/qa_common.py
scripts/run_auto_qa.py
```

Raw roads 分析：

```powershell
python "项目管理/道路研究/road_test_pipeline/scripts/analyze_raw_roads.py" --area-id pattaya_central_500m
python "项目管理/道路研究/road_test_pipeline/scripts/run_auto_qa.py" --stage raw_roads --area-id pattaya_central_500m
```

输出：

```text
reports/pattaya_central_500m_raw_analysis.json
reports/qa/pattaya_central_500m_raw_roads_qa_report.json
```

固定流程：

```text
生成阶段产物
  -> 自动 QA
  -> 写 reports/qa
  -> Houdini cook debug view
  -> 人工目测反馈
  -> 调整规则或算法
```

Topology repair 初版：

```powershell
python "项目管理/道路研究/road_test_pipeline/scripts/topology_repair.py" --area-id pattaya_central_500m
python "项目管理/道路研究/road_test_pipeline/scripts/analyze_raw_roads.py" --area-id pattaya_central_500m --input "项目管理/道路研究/road_test_pipeline/data/processed/pattaya_central_500m_roads_repaired.geojson" --output "项目管理/道路研究/road_test_pipeline/reports/pattaya_central_500m_repaired_analysis.json"
python "项目管理/道路研究/road_test_pipeline/scripts/run_auto_qa.py" --stage topology_repair --area-id pattaya_central_500m
```

输出：

```text
data/processed/pattaya_central_500m_roads_repaired.geojson
reports/pattaya_central_500m_repair_report.json
reports/pattaya_central_500m_repaired_analysis.json
reports/qa/pattaya_central_500m_topology_repair_qa_report.json
```

直接生成道路预览：

```powershell
python "项目管理/道路研究/road_test_pipeline/scripts/generate_road_preview.py" --area-id pattaya_central_500m
```

输出：

```text
data/preview/pattaya_central_500m_roads_preview.svg
data/preview/pattaya_central_500m_roads_preview.obj
data/preview/pattaya_central_500m_roads_preview_surfaces.geojson
reports/pattaya_central_500m_road_preview_report.json
```

## 当前样本下载结果

下载时间：2026-06-02

```text
area_id: pattaya_central_500m
bbox: south=12.93200422, west=100.88139576, north=12.93649578, east=100.88600424
source: OpenStreetMap Overpass
highway ways: 44
nodes: 268
turn restriction relations: 1
ways with lanes: 16
ways with turn:lanes: 0
ways with width: 0
ways with oneway: 10
ways with maxspeed: 1
```

道路等级分布：

```text
service: 27
residential: 14
secondary: 3
```

这个结果说明免费 OSM 数据可以提供道路图和部分车道数，但车道转向、宽度、限速覆盖明显不足。它适合作为第一轮研究样本，因为后续必须测试：

- 缺失 width 时的宽度推断。
- 缺失 `turn:lanes` 时的 movement 推断。
- `service/residential/secondary` 混合路网的路口聚类。
- `Junction Fan` fallback 和 lane-level junction model 的分层关系。

## 第一轮自动 QA 结果

运行时间：2026-06-02

```text
stage: raw_roads
status: warn
feature_count: 44 / pass
empty_geometry: 0 / pass
duplicate_point_features: 0 / pass
too_short_features: 0 / pass
lanes_coverage_pct: 36.364 / pass
width_coverage_pct: 0.0 / warn
turn_lanes_coverage_pct: 0.0 / warn
oneway_coverage_pct: 22.727 / pass
dangling_endpoint_ratio: 0.952 / warn
possible_unsplit_crossings: 0 / pass
low_confidence_endpoint_clusters: 2 / warn
```

结论：

- 样本数量足够，基础几何有效。
- OSM 免费数据没有提供宽度，后续必须做 width fallback。
- 没有 `turn:lanes`，后续必须做 movement 推断。
- dangling endpoint 比例很高，下一步必须先做 topology repair 和 bbox 边界端点分类。
- 没有发现明显未切分平面交叉，第一轮重点不是 intersection split，而是 endpoint / junction cleanup。

## 第一版 Topology Repair 结果

目标：只解决道路连续 + 路口交汇。

```text
stage: topology_repair_v1
input_features: 44
output_edges: 258
duplicate_points_removed: 0
endpoint_snaps: 2
endpoint_to_edge_snaps: 0
intersection_split_insertions: 0
```

输出 edge 端点统计：

```text
endpoint_clusters: 248
dangling_endpoint_clusters: 31
dangling_endpoint_ratio: 0.125
possible_unsplit_crossings: 0
```

自动 QA：

```text
stage: topology_repair
status: warn
output_edges: pass
empty_geometry: pass
duplicate_point_features: pass
too_short_features: warn (7)
dangling_endpoint_ratio: pass
possible_unsplit_crossings: pass
```

结论：

- 第一版已经把道路拆成可用于 road graph 的简单 edge。
- 输出边之间的端点连接情况明显优于 raw roads。
- 当前唯一主要警告是 7 条短边，下一轮可以做短边合并 / junction 内短 connector 标记。
- Houdini cook 已改为优先读取 `pattaya_central_500m_roads_repaired.geojson`；如果该文件不存在，才回退到 raw GeoJSON。

## 第一版道路直接生成结果

在不依赖 Houdini 的情况下，已直接生成测试区道路预览。

```text
input: data/processed/pattaya_central_500m_roads_repaired.geojson
edges: 258
endpoint_clusters: 248
junction_nodes_degree_ge_3: 49
road_surface_polygons: 258
junction_patch_polygons: 49
obj_vertices: 1926
obj_faces: 307
```

说明：

- 这一版使用 repaired edge 生成 road surface quads。
- degree >= 3 的端点聚类生成 circular junction patch，用于第一版路口交汇覆盖。
- 这是 continuity / junction visual test，不是最终 lane-level geometry。
