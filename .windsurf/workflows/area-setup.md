---
description: 创建和记录 VirtualCity MVP 测试区域
---

# Area Setup 工作流

当用户要求“创建测试区域”“记录 bbox”“选择 MVP 区域”“初始化区域配置”时，使用本工作流。

核心原则：**用户只负责在地图中框选区域并提供框选结果，AI 负责剩余整理、接入和记录工作。**

## 1. 必读文件

执行前读取：

1. `项目管理/project_manifest.json`
2. `项目管理/04_稳定流程规范.md`
3. `项目管理/区域记录/_template.md`
4. `配置/area_config.template.json`
5. `项目管理/02_当前状态与下一步.md`

## 2. 适用阶段

优先适用于：

- `mvp_preparation`
- `mvp_houdini`

如果当前已进入更大范围 Tile 或量产阶段，先确认是否仍按 MVP 区域规则执行。

## 3. 区域选择原则

MVP 区域应满足：

- 面积优先控制在 `200m x 200m` 到 `500m x 500m`。
- 有清晰道路网络。
- 有一定数量建筑轮廓。
- OSM 覆盖较完整。
- 不选择过大、过密、地形过复杂的区域作为第一轮。
- bbox 必须包含 `west / south / east / north`。

## 4. 用户输入契约

用户可以只提供以下任意一种输入：

1. `bbox: west,south,east,north`
2. GeoJSON Polygon / Feature
3. 地图工具复制出的 `min lon, min lat, max lon, max lat`
4. 地图截图 + 地点名称

AI 需要负责：

- 判断输入属于哪一种格式。
- 从 GeoJSON 中提取 bbox。
- 将 `min lon, min lat, max lon, max lat` 转为 `west/south/east/north`。
- 如果只有截图或地点名称，创建 `bbox_pending` 的区域记录和配置，不得伪造经纬度。
- 根据区域位置生成合理的 `area_id`，必要时询问用户确认。
- 将区域接入项目文件，而不是只给用户文字说明。

## 5. AI 必须完成的整理工作

收到框选结果后，AI 应尽可能直接完成以下工作：

1. 确认或生成区域信息：
   - area_id
   - 城市 / 区域名
   - bbox
   - 数据来源
   - 坐标系

2. 检查 bbox 是否满足 MVP 范围。

3. 在 `项目管理/区域记录/` 下创建或更新 `{area_id}.md`。

4. 从 `配置/area_config.template.json` 派生或更新真实区域配置：

```text
配置/{area_id}.area.json
```

5. 创建或更新 Overpass Turbo 查询模板：

```text
配置/{area_id}.overpass.txt
```

6. 写入推荐 OSM 保存路径：

```text
原始数据/OSM/{area_id}_osm_v001.osm
```

7. 更新：
   - `项目管理/02_当前状态与下一步.md`
   - `项目管理/03_迭代日志.md`
   - `项目管理/08_任务看板.md`
   - `项目管理/project_manifest.json`

8. 如果 bbox 已确认，将区域状态设为：

```text
ready_for_osm_download
```

9. 如果 bbox 未确认，将区域状态设为：

```text
bbox_pending
```

## 6. 禁止事项

- 不得伪造 bbox。
- 不得伪造坐标系。
- 不得删除 `原始数据/` 下任何文件。
- 不得覆盖已有区域记录，除非用户明确确认。
- 不得把过大区域直接作为第一轮 MVP。
- 不得把本应由 AI 完成的区域记录、配置、状态、日志整理工作再交给用户手动完成。

## 7. 输出格式

最终输出：

# 区域设置结果

## 区域信息

## bbox 检查

## 已创建或建议创建的文件

## 当前风险

## 下一步建议

## 是否需要用户确认

## 8. 执行后复盘

任务结束后检查：

1. 区域记录模板是否够用。
2. 是否需要补充新的区域字段。
3. 是否需要更新本 workflow。

如需修改本 workflow，应直接根据用户明确偏好更新，并在迭代日志中记录。
