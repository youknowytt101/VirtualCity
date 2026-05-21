# 06 路线一详细拆解：Houdini + UE5 城市管线

> 基于 Epic Games《黑客帝国：觉醒》/ City Sample 官方文档拆解  
> 这是目前 AAA 级虚拟城市制作的最高标准流程

---

## 整体数据流

```
设计师输入（轮廓线 + 主路径 + 分区）
         ↓
  ┌──────────────────────────────────┐
  │         HOUDINI（离线生成）        │
  │                                  │
  │  Stage 1  城市轮廓 & 道路骨架      │
  │  Stage 2  主干路网生成             │
  │  Stage 3  高架/快速路系统          │
  │  Stage 4  地块划分 & 人行道        │
  │  Stage 5  建筑体量 & 地面          │
  │  Stage 6  街道家具 & 贴花 & 音效点 │
  │                                  │
  │  输出 → Point Cloud Alembic(.pbc) │
  └──────────────┬───────────────────┘
                 │  Houdini Engine / 手动导入
  ┌──────────────▼───────────────────┐
  │         UNREAL ENGINE 5          │
  │                                  │
  │  Rule Processor（点云→实例）       │
  │  Nanite  /  Lumen  /  VSM        │
  │  World Partition + Data Layers   │
  │  PCG（植被/人群/垃圾）             │
  │  Mass AI（交通流/行人流）          │
  │  Chaos Vehicles                  │
  └──────────────────────────────────┘
```

---

## HOUDINI 侧：6 个生成阶段详解

### Stage 1｜城市轮廓定义（City Layout）

**核心节点：** `City Layout SOP`（City Sample 专用 HDA）

**输入：**
- `Curve` 节点 → 手绘城市岛屿轮廓（小城市 ~1km，大城市 ~5km）
- 动脉样条线 `Arterial Splines` → 定义主干道走向，将城市分成区域
- 分区多边形 `Zone Curves` → 定义各区域的建筑风格和高度范围

**输出：**
- 自动生成的路网骨架（街块尺寸、朝向、密度由参数控制）
- 实时预览可随时拖动 Curve 点，城市布局自动重算

**关键参数：**
```
Road Network Options
  ├── 街块尺寸（Block Size）
  ├── 道路长度最小值（避免过短路段影响交通流）
  ├── 路口合并阈值（Merge Intersections）
  └── 单行道控制（禁止死胡同）
```

---

### Stage 2｜主干路网（Roads）

- 从 Stage 1 道路骨架 → 生成实际路面几何体多边形
- 包括：车道线、路缘石（Curb）、十字路口处理
- 输出道路轮廓多边形 → 供 Stage 4 地块划分使用
- `Labs Road Generator SOP` 处理路面侧线 → 生成人行道边缘

---

### Stage 3｜高架快速路系统（Freeway）

- 独立设计高架路径（Curve 手绘）
- `City Processor` 节点负责将高架与地面路网对接
- 处理匝道（Ramp）插值、高度过渡、倾斜角（Banking）
- **关键约束**：建筑生成时会自动回避高架下方区域

**连接参数（connection_set）：**
```
Interpolation  → 匝道曲线插值方式
Elevation      → 离地高度
Banking        → 弯道倾斜角
```

---

### Stage 4｜地块划分 & 人行道（Lots & Sidewalks）

**核心节点：** `City_Lot_Processor SOP`

- 将街块内部按地块尺寸细分 → 每个地块是一栋建筑的基底
- 自动处理建筑退线（Setback）→ 控制建筑到路缘石的距离
- 生成人行道几何体（独立于建筑）

**LOTS 参数组：**
```
Lot Size               → 地块面积范围（min/max）
Freeway Removal Distance → 高架周边清空半径
Sidewalk Setback       → 人行道宽度
```

---

### Stage 5｜建筑体量 & 地面（Buildings & Ground）⭐核心阶段

这是整个管线最复杂的阶段。

#### 5.1 建筑体量生成

每个地块多边形 → 拉伸为建筑体量 Box

```
BUILDINGS 参数组：
  Style          → 建筑风格（现代/古典/工业/住宅...）
  Height         → 楼层高度范围
  Size           → 体量尺寸变化
  底层风格/顶层风格 → 同一栋建筑可分两段套不同规则
```

#### 5.2 形状语法（Shape Grammar）— 建筑装配核心

> 这是 City Sample 建筑生成的真正核心。

**原理：** 建筑体量被输入一套**规则语言（Shape Grammar / CGA）**，规则驱动建筑外立面的分割和模块装配。

```
建筑体量（Box）
    ↓ 水平切割（楼层分割）
每一层 = [底层规则] or [标准层规则] or [顶层规则]
    ↓ 垂直切割（开间分割）
每个开间 = [窗户模块] or [阳台模块] or [实墙模块]
    ↓ 细节层叠加
装饰线脚 / 空调机位 / 广告牌 / 顶层水箱 等
```

**每种建筑风格 = 一套独立规则集**，规则决定：
- 窗户尺寸和间距
- 阳台出现概率和形态
- 顶层收束/退台方式
- 立面材质分区

#### 5.3 模块库的作用

形状语法切割出来的每个"槽位"，会从**预制模块库**中选取对应构件实例化：

```
模块库结构（2000+ 模块）：
  底层  ├── 商业裙楼底层_A/B/C
        ├── 门洞模块_窄/宽
        └── 商铺橱窗_现代/古典

  标准层 ├── 窗户单元_单窗/双窗/转角
         ├── 阳台单元_内嵌/外挑
         └── 实墙单元_光滑/砖纹/混凝土

  顶层  ├── 平屋顶_含设备
        ├── 退台收束
        └── 坡屋顶_多变体
```

**关键：所有模块使用 Nanite + Instanced Static Mesh（ISM）**，7000 栋建筑本质上是 2000 多个模块的**数十万次实例**。

#### 5.4 PDG 并行处理（大城市必用）

大型城市建筑生成可能耗时数分钟到数十分钟，City Sample 使用 **PDG（Procedural Dependency Graph）** 并行化建筑生成：

```
City Processor
  ├── [PDG] Process City Base     ← 路网/地块
  ├── [PDG] PDG Process           ← 建筑体量并行生成（CPU 多核）
  └── [PDG] Process City Furniture ← 街道家具
```

---

### Stage 6｜街道家具 & 贴花 & 音效（Street Furniture）

- 路灯、长椅、垃圾桶、消防栓、邮箱、报刊亭 → 点位生成
- 路面贴花（裂缝、污渍、井盖、斑马线）→ Decal 点位
- 音效触发点（`MetaSounds` 系统）→ 城市声景程序化分布
- 植被点位（街道行道树、花坛）→ 导入 UE5 后由 PCG 填充

---

### Houdini 最终输出格式

> ⚠️ **不是 FBX！** City Sample 使用专用格式。

```
EXPORT ALL PBC（Point Cloud Alembic）
  ├── city_buildings.pbc    ← 建筑实例点云（含所有属性）
  ├── city_roads.pbc        ← 道路几何
  ├── city_furniture.pbc    ← 街道家具点云
  ├── city_decals.pbc       ← 贴花点云
  └── city_ground.abc       ← 地面几何（Alembic）
```

每个点云中的每个"点"携带大量属性：
```
unreal_instance    → 指向 UE5 中哪个 Static Mesh
位置/旋转/缩放      → Transform 信息
建筑风格标签        → 供 AI/材质系统使用
LOD 级别           → 距离相关 LOD 控制
traffic_zone       → 交通流仿真分区
pedestrian_density → 行人密度系数
```

---

## UNREAL ENGINE 5 侧：接收 & 渲染

### Rule Processor（规则处理器）— UE5 专用工具

> 这是 Epic 为 City Sample 专门开发的 UE5 工具（非公共 API）。

**作用：** 读取 `.pbc` 点云文件 → 根据每个点的属性 → 在场景中生成对应的 **ISM（Instanced Static Mesh）** 实例。

```
读入 city_buildings.pbc
    ↓
遍历每个点：
    point.unreal_instance → "SM_Building_ModuleA_Floor_01"
    position/rotation     → Actor Transform
    style_tag             → 选择对应材质变体
    ↓
批量创建 ISM 实例 → 数十万实例
```

### Nanite（虚拟化几何体）

- 所有建筑模块、街道家具、贴花 → **全部启用 Nanite**
- 无多边形预算限制，每个模块可以有数万面
- City Sample 极少使用自定义低面数 Mesh（只有碰撞体、高架桥面、非矩形屋顶除外）

### Lumen（全动态全局光照）

- 不需要预烘焙光照贴图
- 7000 栋建筑的窗户灯光、霓虹反射、阴影 → 全部实时
- 城市规模下配合 **Virtual Shadow Maps（VSM）** 使用

### World Partition + Data Layers（大世界管理）

```
World Partition
  ├── 自动将场景对象按空间位置分格
  ├── 按视距动态加载/卸载网格单元
  └── 无需手动划分子关卡

Data Layers（数据层）
  ├── Procedural_Buildings    ← 程序化建筑
  ├── Rooftop_Props           ← 屋顶道具
  ├── Freeway                 ← 高架系统
  ├── Street_Furniture        ← 街道家具
  └── Decals                  ← 贴花层

One File Per Actor（OFPA）
  └── 每个 Actor 独立文件 → 多人协同无冲突
```

### PCG（程序化内容生成）

City Sample 部分使用 PCG（UE5.2+ 正式集成）：
- 路边植被（行道树间距、碰撞检测）
- 垃圾/碎片散布（路面随机）
- 屋顶设备散布（水箱、空调外机）

### Mass AI（大规模 AI 仿真）

Houdini 输出的点云里包含 `traffic_zone`、`pedestrian_density` 等属性，UE5 的 **Mass Entity** 系统读取这些数据驱动：
- 车辆交通流（数千辆同屏）
- 行人人群（数千人同屏）
- **ZoneGraph**：道路网格数据直接来自 Houdini 的路网输出

---

## 关键数字参考（City Sample 实测）

| 指标 | 数值 |
|------|------|
| 小城市面积 | ~1 km² |
| 大城市面积 | ~5 km² |
| 建筑数量 | 7,000+ 栋 |
| 建筑模块数 | 2,000+ 个独立模块 |
| 停放车辆数 | 45,073 辆 |
| 几乎全部使用 | Nanite ISM 实例 |
| 自定义几何体占比 | 极少（碰撞/桥面/异形屋顶）|
| Houdini 生成时间 | 大城市约数十分钟（PDG 并行）|

---

## 团队分工参考

```
Houdini TD（技术美术）
  → 维护 City Layout / City Processor HDA
  → 制定建筑风格规则集（Shape Grammar）
  → 调参城市布局、密度、分区

建筑模块美术
  → 制作 2000+ 个模块资产（每个启用 Nanite）
  → 设计模块接缝规范（确保任意组合不穿插）
  → 制作材质（支持 Material Instance 变体）

UE5 关卡设计师
  → 定义 Data Layers 分层策略
  → 调试 World Partition 流送设置
  → Rule Processor 参数调整

AI/逻辑程序员
  → 配置 ZoneGraph（来自 Houdini 路网）
  → Mass AI 交通/人群参数
  → MetaSounds 音景配置
```

---

## 与"地图API框选数据"的对接点

如果在此管线中引入真实地图数据（OSM 框选），接入位置在 **Stage 1**：

```
真实世界 OSM 数据 (.osm)
    ↓ Labs OSM Import SOP
提取真实道路网络 → 替换掉 City Layout 的自动生成路网
    ↓
继续走 Stage 2~6 （建筑体量仍然程序化生成）
    ↓
结果 = 真实道路走向 + 程序化建筑填充
```

> 这是目前游戏行业"基于真实地图做虚拟城市"最规范的接入方式。  
> 完全精确复现真实建筑需要额外的建筑 LOD 数据（如 CityGML / BIM 数据），OSM 本身只有轮廓。

---

## 实时预览策略

### 三个预览层级

整条管线的预览方式分三个层级，越往后越"所见即所得"，响应速度也越慢。

#### 层级 1｜Houdini 视口预览（最快，纯 Houdini 内）

直接在 Houdini 内看，调一个参数，视口立刻更新。

```
City Layout 节点选中 → 拖动 Curve 控制点
    → 路网实时重算 → 视口立刻显示新布局（秒级响应）

City_Lot_Processor 参数调整
    → 地块/建筑体量实时更新（秒~分钟，取决于城市大小）
```

**局限**：没有材质、没有光照，看不到 Nanite/Lumen 效果，只能看几何形态。  
适合调**城市布局、路网、建筑体量**阶段。

---

#### 层级 2｜Houdini Engine Session Sync（推荐，双屏联动）⭐

在 Houdini 里改参数，UE5 视口同步更新，带完整 Lumen 光照效果。

**开启方式：**

```
Houdini 菜单 → Houdini Engine → Session Sync → Start Session Sync
    ↓
UE5 菜单 → Houdini Engine → Connect to Session Sync
    ↓
两个软件实时联通
```

**响应速度参考：**

| 改动类型 | 响应时间 |
|---------|---------|
| 单个建筑参数 | 2~10 秒 |
| 街块级重生成 | 10~60 秒 |
| 整城重算（PDG） | 数分钟 |

---

#### 层级 3｜UE5 内直接调参（HDA 作为 Actor）

把 HDA 拖入 UE5 场景，直接在 Details 面板调参数，无需打开 Houdini。适合关卡设计师不懂 Houdini、只需在 UE5 内微调参数的场景。

```
UE5 Content Browser → 双击 .hda → 拖入场景 → 生成 Houdini Asset Actor
    ↓
Details 面板 → 修改暴露参数 → Recook → UE5 内后台更新场景
```

---

### 实际工作推荐节奏

```
粗调阶段（确定城市形态）
    → 只用 Houdini 视口，快速迭代路网/分区/体量
    → 不需要开 UE5

中调阶段（确定视觉风格）
    → 开启 Session Sync
    → Houdini 调参，UE5 视口看 Lumen 光照效果

精调阶段（局部细节）
    → 直接在 UE5 的 Houdini Asset Actor Details 面板调
    → Bake 成静态 Mesh 后手动补细节
```

### 实用技巧：小范围代理测试

城市太大时 Session Sync 响应慢，先用小范围代理测试所有参数：

```
City Layout 轮廓 Curve → 先画 200m × 200m 的小块
    → 用这个小块调试所有参数（秒级响应）
    → 参数确定后换成完整 5km 城市轮廓 → 跑一次完整 PDG
```

> 这是 City Sample 工作流文档里明确推荐的做法。

---

## 参考链接

- City Sample 官方技术文档：  
  https://dev.epicgames.com/documentation/unreal-engine/city-sample-project-unreal-engine-demonstration

- City Sample + Houdini 快速入门（官方 Step-by-Step）：  
  https://dev.epicgames.com/documentation/en-us/unreal-engine/city-sample-quick-start-for-generating-a-city-and-freeway-using-houdini

- Matrix Awakens Houdini Breakdown（80.lv）：  
  https://80.lv/articles/breakdown-creating-the-matrix-awakens-in-houdini-unreal-engine-5

- City Sample 源文件下载（含 CitySample_HoudiniFiles.zip）：  
  https://www.unrealengine.com/marketplace/city-sample

- SideFX 程序化城市 Houdini 教程播放列表：  
  https://www.sidefx.com/tutorials/city-building-with-osm-data/
