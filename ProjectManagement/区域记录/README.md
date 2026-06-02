# 区域记录

> 本目录用于记录每一个测试区域或生产区域的 bbox、数据来源、参数、输出和问题。  
> 每做一个新区域，复制下面模板创建一个新的 Markdown 文件。

---

## 文件命名

```text
{area_id}.md
```

示例：

```text
mvp_area.md
shanghai_test_001.md
campus_block_001.md
```

---

## 区域记录模板

```markdown
# 区域记录：{area_id}

## 1. 基本信息

| 项 | 内容 |
|---|---|
| 区域 ID | {area_id} |
| 城市 / 地点 |  |
| 目标用途 | MVP / 1km² 测试 / 正式区块 |
| 创建日期 |  |
| 负责人 |  |

## 2. bbox

| 方向 | 经纬度 |
|---|---:|
| west |  |
| south |  |
| east |  |
| north |  |

## 3. 坐标系

| 项 | 内容 |
|---|---|
| 原始坐标系 | WGS84 / GCJ-02 / BD-09 / CGCS2000 / 未确认 |
| Houdini 坐标 | 局部米制 / UTM / 其他 |
| UE5 坐标 | cm，局部世界坐标 |
| 原点策略 | bbox 中心 / 西南角 / 自定义点 |

## 4. 数据文件

| 数据 | 路径 | 来源 | 下载时间 |
|---|---|---|---|
| OSM |  |  |  |
| DEM |  |  |  |
| 参考截图 |  |  |  |
| 处理后 GIS |  |  |  |

## 5. Houdini 参数

| 参数 | 值 |
|---|---:|
| building_height_multiplier |  |
| default_floor_height |  |
| default_levels_min |  |
| default_levels_max |  |
| road_width_multiplier |  |
| terrain_resolution |  |
| random_seed |  |

## 6. 输出文件

| 类型 | 路径 |
|---|---|
| .hip |  |
| .hda |  |
| .fbx |  |
| heightmap |  |
| UE5 map |  |

## 7. QA 结果

| 检查项 | 结果 | 备注 |
|---|---|---|
| 道路连续性 | 未检查 / 通过 / 不通过 |  |
| 建筑位置 | 未检查 / 通过 / 不通过 |  |
| 地形对齐 | 未检查 / 通过 / 不通过 |  |
| UE 比例 | 未检查 / 通过 / 不通过 |  |
| Bake 结果 | 未检查 / 通过 / 不通过 |  |
| 性能 | 未检查 / 通过 / 不通过 |  |

## 8. 问题记录

- 

## 9. 下一步

- 
```
