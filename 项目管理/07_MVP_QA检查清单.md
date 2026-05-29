# 07 QA 检查清单

> 本文件用于检查 VirtualCity 当前阶段的城市区块是否真的可复现、可审核。
> 当前重点是数据清洗到 Houdini 自动构建，不是最终 UE5 Bake。

---

## 1. 数据 QA

| 检查项 | 通过标准 | 当前自动化 |
|---|---|---|
| bbox 已记录 | `Config/active_area.json` 有 west / south / east / north | `set_area.py` |
| OSM 文件存在 | `RawData/OSM/{area_id}_osm_v001.osm` | `set_area.py` |
| DEM 文件存在 | `RawData/DEM/{area_id}_dem_v001.csv` | `set_area.py` |
| 建筑文件存在 | `RawData/Overture/{area_id}_buildings_overture_v001.geojson` | `set_area.py` |
| raw snapshot | `_downloads/{area_id}/` 保留输入快照 | `refine_data.py` |
| 数据清洗输出 | `_houdini_ready/{area_id}/` 生成 Houdini 输入 | `refine_data.py` |
| 数据 QA 报告 | `Config/qa/{area_id}_qa_*.json` | `refine_data.py` |

数据 QA 允许 warning，但不允许 failed。

---

## 2. Houdini Model QA

自动入口：

```bash
cd Scripts
uv run python houdini_model_qa.py --mode quick
```

| 检查项 | 通过标准 |
|---|---|
| required_nodes | 关键 SOP 节点存在且非空 |
| terrain_density | `dem_subdivide` 比 `dem_terrain` 更密，作为吸附目标 |
| building_color | 建筑 body、foundation、final 颜色一致 |
| footprint_bevel | 外角倒角产生，且没有过短边 |
| building_normals | 法线存在、非零、与面法线一致 |
| foundation_tags | `is_foundation` 数量与 body/foundation prim 数匹配 |
| foundation_normals | 裙边侧面法线与建筑侧面一致 |
| foundation_alignment | 裙边顶边与建筑底边 XZ 对齐 |
| building_terrain_fit | 建筑不低于地形阈值 |
| road_faces | 道路无开放面、无异常大面片、无过多顶点面 |
| road_terrain_fit | 道路不低于地形阈值 |

通过标准：

```text
Reports/model_qa/latest.json: no fail checks
status = pass 可作为基准候选；status = warn 需要人工审核后再决定是否晋级
```

---

## 3. Houdini 人工视口 QA

Model QA 通过后仍需人工看 `OUT_city`：

| 检查项 | 通过标准 |
|---|---|
| 道路贴地 | 山地/丘陵区域无明显埋地、悬空、断裂 |
| 道路面片 | 无大块错误道路面、异常三角扇或长条飞面 |
| 道路交叉口 | 没有严重重叠、缝隙、尖角 |
| 建筑贴地 | 坡地建筑不明显埋入地形 |
| 建筑裙边 | 裙边与 body 对齐、同色、无反面黑块 |
| 建筑倒角 | 只出现在合理外角，不制造奇怪斜面或短边 |
| 地形密度 | 俯视角和斜视角下无过强阶梯感 |
| 城市关系 | 道路宽度、建筑密度、地形比例可信 |

---

## 4. 完整流程 QA

当用户要求“重新测试 / 从头测试 / 全流程测试”时，必须走：

```text
area_picker.py 网页入口
    ↓
set_area.py
    ↓
refine_data.py
    ↓
_recook_new_area.py
    ↓
houdini_model_qa.py
```

完成定义：

- `Config/houdini_build_status.json` 中当前 `area_id` 为 `completed`
- `Reports/model_qa/latest.json` 中当前 `area_id` 一致且无 `fail`；`warn` 需要人工审核

网页是否自动关闭不是成功标准。

---

## 5. UE5 QA（暂缓）

当前 UE5 导出导入不属于默认全流程测试。只有 Houdini 视口审核通过后，再运行：

```bash
cd Scripts
uv run python export_and_import.py
```

UE5 侧后续仍需检查：

- 比例正确。
- Static Mesh / Data Layer 命名正确。
- Bake 后可脱离 Houdini 查看。
- Play 模式无严重报错。
