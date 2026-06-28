# 道路研究模块

这个目录用于把道路系统作为独立模块研究，尽量不被当前 WorldBuilder 既有实现细节绑住。

## 模块目标

道路研究模块关注四件事：

1. 程序化道路生成：CityEngine / Parish & Müller 风格的道路生长、major/minor 分层、global goals、local constraints。
2. 真实道路数据管线：OSM / OSMnx / Overpass 获取、清洗、投影、属性标准化。
3. Houdini 道路建模：道路中心线到道路面、路口、路缘石、人行道、材质分层。
4. 对接 WorldBuilder：当道路方案稳定后，再映射到当前工程脚本、Houdini SOP 和 UE5 导入流程。

## 目录结构

```text
RoadResearch/
  README.md
  01_CityEngine道路生成逻辑复刻指南.md
  02_OSM到Houdini道路素模工作流.md
  03_地图API数据驱动路口最优方案.md
```

## 研究原则

- 先把道路作为独立系统讲清楚，再考虑如何接入当前工程。
- 优先保留可复刻算法、数据结构、伪代码和 Houdini 节点流程。
- 当前工程里的脚本只能作为参考，不作为道路研究的唯一约束。
- 每个方案都要标清：研究级、MVP 可用、生产级推荐。
- 对 Houdini 方案要区分 preview hack 和可维护主方案。

## 与当前工程的关系

当前 WorldBuilder 已有一些道路相关实现：

- `Scripts/road_graph_builder.py`
- `Scripts/houdini_sops/road_topology_builder.py`
- `Scripts/houdini_road_pipeline.py`
- `Config/road_profiles.json`

这些实现可以作为落地参考，但本目录的文档允许提出更通用、更干净的道路模块设计。稳定后再决定是否改造当前工程。

## 后续建议

下一步可以继续拆成更细的研究文档：

- `04_道路图数据结构与拓扑清理.md`
- `05_Houdini道路面与路口建模.md`
- `06_路缘石人行道与街道家具.md`
- `07_道路模块实现路线图.md`

其中 `03_地图API数据驱动路口最优方案.md` 是长期高质量路线：把地图 API / HD Map 数据升级成 lane-level graph 和 OpenDRIVE-inspired junction model，再由 Houdini 生成车道面、路口连接面、标线、路缘石、人行道和导流岛。
