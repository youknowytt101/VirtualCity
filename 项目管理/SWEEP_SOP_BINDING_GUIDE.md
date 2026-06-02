# Houdini Sweep SOP 属性绑定指南（Milestone 3）

## 目标
将 `road_profile_apply.py` 注入的截面属性绑定到 Sweep SOP，实现属性驱动的道路截面生成。

---

## 属性列表

| 属性名 | 类型 | 范围 | 说明 |
|--------|------|------|------|
| `lane_num` | int | 1-6 | 车道数 |
| `lane_width_m` | float | 2.5-3.5 | 单条车道宽度（米） |
| `sidewalk_left_m` | float | 1.5-3.0 | 左侧人行道宽度 |
| `sidewalk_right_m` | float | 1.5-3.0 | 右侧人行道宽度 |
| `curb_height_m` | float | 0.10-0.20 | 路缘石高度 |
| `median_width_m` | float | 0-3.0 | 中央分隔带宽度（可选） |

---

## 操作步骤

### 第 1 步：打开 Houdini HIP 文件
```
Houdini/Hip/VC_z47n_e703000_n1429000_w1000_h1000_s1000_citygen_v001.hip
```

### 第 2 步：定位 Sweep SOP
在 `/obj/geo1` 或类似的 geo 容器中找到 **Sweep** 节点。

**路径示例**：
```
/obj/geo1/sweep
```

### 第 3 步：配置 Sweep 的 Profile 参数

#### 3a. 打开 Sweep 参数面板
- 右键点击 Sweep 节点 → **Edit Parameters**
- 或双击 Sweep 节点

#### 3b. 找到 "Profile" 标签页
- 展开 **Profile** 部分
- 查看 **Profile Curve** 参数

#### 3c. 配置车道数绑定
在 Sweep 的参数中添加表达式绑定：

**参数**：`Profile Scale` 或 `Scale`
**表达式**：
```python
ch("../road_profile_apply/lane_num") * 3.0
```

这会根据 `lane_num` 属性动态调整 Profile 的缩放。

---

### 第 4 步：配置人行道宽度绑定

#### 4a. 如果使用 Sweep 的 "Sides" 参数
**参数**：`Side 1 Scale` 或 `Left Width`
**表达式**：
```python
ch("../road_profile_apply/sidewalk_left_m") / 2.0
```

**参数**：`Side 2 Scale` 或 `Right Width`
**表达式**：
```python
ch("../road_profile_apply/sidewalk_right_m") / 2.0
```

#### 4b. 如果使用 Sweep 的 "Divisions" 参数
- 设置 **Divisions** = `ch("../road_profile_apply/lane_num")`
- 每个 Division 的宽度 = `lane_width_m`

---

### 第 5 步：配置路缘石高度绑定

#### 5a. 在 Sweep 之后添加 Extrude SOP
- 创建新的 Extrude 节点
- 输入：Sweep 的输出
- **参数**：`Distance`
**表达式**：
```python
ch("../road_profile_apply/curb_height_m")
```

#### 5b. 或在 Sweep 的 Profile 中直接编辑
- 编辑 Profile 曲线，使其高度为 `curb_height_m`
- 在 Profile SOP 中添加表达式：
```python
ch("../road_profile_apply/curb_height_m")
```

---

### 第 6 步：验证绑定

#### 6a. 检查属性是否正确传播
```python
# 在 Houdini Python Shell 中执行：
n = hou.node('/obj/geo1/road_profile_apply')
g = n.geometry()
for prim in g.prims()[:5]:  # 检查前 5 个 primitive
    print(f"lane_num: {prim.attribValue('lane_num')}")
    print(f"sidewalk_left_m: {prim.attribValue('sidewalk_left_m')}")
    print(f"curb_height_m: {prim.attribValue('curb_height_m')}")
```

#### 6b. 在 Sweep 中验证表达式
- 点击 Sweep 参数中的表达式字段
- 应该看到绿色的表达式指示符
- 数值应该随着属性变化而变化

#### 6c. 视觉验证
- 在 Houdini 视口中查看 Sweep 的输出
- 道路截面应该根据属性动态变化
- 不同宽度的道路应该有不同的车道数和人行道宽度

---

## 常见问题

### Q1：表达式无法找到属性
**原因**：属性名称拼写错误或属性未被注入
**解决**：
1. 检查 `road_profile_apply.py` 的输出属性
2. 在 Geometry Spreadsheet 中验证属性是否存在
3. 确保 `apply_road_profiles: true` 在 active_area.json 中

### Q2：Sweep 输出为空
**原因**：Profile 曲线配置错误或表达式语法错误
**解决**：
1. 检查 Profile 曲线是否有效
2. 在 Python Shell 中测试表达式：`ch("../road_profile_apply/lane_num")`
3. 查看 Sweep 节点的错误信息

### Q3：属性值不合理
**原因**：Config/road_profiles.json 中的参数设置不当
**解决**：
1. 检查 Config/road_profiles.json 中的参数范围
2. 调整 `lane_width_m`、`sidewalk_*_m`、`curb_height_m` 的值
3. 重新运行 refine_data.py 和 _recook_new_area.py

---

## 配置文件参考

### Config/road_profiles.json 示例
```json
{
  "motorway": {
    "lane_num": 4,
    "lane_width_m": 3.5,
    "sidewalk_left_m": 0.0,
    "sidewalk_right_m": 0.0,
    "curb_height_m": 0.15,
    "median_width_m": 2.0
  },
  "primary": {
    "lane_num": 2,
    "lane_width_m": 3.2,
    "sidewalk_left_m": 2.0,
    "sidewalk_right_m": 2.0,
    "curb_height_m": 0.12,
    "median_width_m": 0.0
  },
  "residential": {
    "lane_num": 1,
    "lane_width_m": 3.0,
    "sidewalk_left_m": 1.5,
    "sidewalk_right_m": 1.5,
    "curb_height_m": 0.10,
    "median_width_m": 0.0
  }
}
```

---

## 完成检查清单

- [ ] Sweep SOP 参数面板已打开
- [ ] Profile Scale 表达式已配置
- [ ] Side Width 表达式已配置
- [ ] Extrude 高度表达式已配置
- [ ] 属性在 Geometry Spreadsheet 中可见
- [ ] Sweep 输出有效（非空）
- [ ] 视觉效果符合预期（车道数、人行道宽度、路缘石高度）
- [ ] 不同道路类型显示不同截面

---

## 下一步

完成 Sweep 绑定后：
1. ✅ Milestone 3 完成
2. ⏳ Milestone 4 已启用（blocks.geojson 生成）
3. 📋 后续：性能优化与 LOD 控制（Milestone 5）

---

**最后更新**：2026-06-02 03:57 UTC+08:00
