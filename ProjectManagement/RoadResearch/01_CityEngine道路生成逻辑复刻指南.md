# CityEngine 道路生成逻辑复刻指南

> 目标：把 CityEngine / Parish & Müller 风格的程序化道路生成逻辑整理成一套独立道路模块的可复刻实现说明。
>
> 本文重点是道路中心线从零生长、图约束、路口清理、街区/地块切分，以及如何把道路图交给任意几何后端生成道路面片。

## 0. 与 OSM 管线的关系和当前优先级

当前 WorldBuilder 的近期目标是 **路线 A：真实 OSM 数据驱动**，也就是先把免费 API / 缓存数据跑通，进入 Houdini 生成干净道路素模；管线成熟后再替换 TomTom、HERE、Mapbox 等付费数据源。

本文描述的是 **路线 B：程序化道路生成**，偏 CityEngine / Parish & Müller 风格，用规则、人口密度、边界和障碍从零生长道路。它是另一个产品方向，不是 OSM 真实城市建模 MVP 的前置条件。

两条路线的关系应该这样拆：

```text
路线 A：真实数据驱动
DataProvider -> roads_raw.geojson -> clean_pipeline.py -> road_graph.json

路线 B：程序化生成
Priority Queue + Global Goals + Local Constraints -> road_graph.json

共用后端
road_graph.json -> road_surface_builder -> Houdini roads / curbs / sidewalks
```

因此，如果当前里程碑是“OSM -> Houdini 精致素模”，可以暂时不实现本文的 Priority Queue 生长逻辑。本文最有价值的可复用部分是：事务式 `local_constraints` 思想、平面图 cleanup、block/lot 提取、以及 road graph 到 mesh 的后半段约束。

## 1. 总体结论

CityEngine 的道路生成不是简单随机画线，而是一个分阶段的图生成系统：

1. 用全局目标决定道路想往哪里长。
2. 用局部约束决定道路能不能落地、是否吸附、是否截断、是否避障。
3. 先生成主路网络，再用次级道路细分主路围出的 quarter。
4. 把道路中心线图清理成平面图。
5. 从平面图提取 block / lot。
6. 根据道路等级生成宽度、路口、路面和人行道几何。

最小可复刻版本可以先只做 2D XZ 平面的道路中心线图，暂时不管高程、桥、隧道和地块建筑。等道路图稳定后，再接入 Houdini、Blender、Unity、Unreal 或自研 mesh 生成器。

如果项目只需要真实城市素模，最小可跑版本应优先采用 `02_OSM到Houdini道路素模工作流.md` 的路线 A；本文的最小可跑版本只在需要“无真实数据、从零生成街网”时启动。

## 2. CityEngine 道路生成的核心模型

CityEngine 的经典思想来自 Parish & Müller 2001 的程序化城市论文。它把城市生长分成两类规则：

- Global Goals：全局目标。决定候选道路的方向、长度、模式，例如向人口密度高的地方生长、遵循网格、径向扩散、沿地形或避开水体。
- Local Constraints：局部约束。检查候选道路和当前道路图、障碍、地形、最小角度、吸附距离是否冲突，并对候选道路做裁剪、吸附、旋转或拒绝。

Esri 现代 CityEngine 的 Grow Streets 工具仍然延续这个结构，并显式分成 major streets 和 minor streets：

- Major streets：先生成主路网络，主路围出的大片区域叫 quarter。
- Minor streets：在 quarter 内部继续生成次级路，把 quarter 切成更小 block。
- Street patterns：支持 organic、raster、radial 等模式，并允许混合。
- Cleanup：道路生成后需要 intersect、snap、merge、resolve conflicts。

### 2.1 论文算法与现代 CityEngine 的映射

Parish & Müller 论文里常用 highway / street 两层表达：

- highway：宏观道路，连接人口密度峰值、城市中心、外部入口等主要区域。
- street：微观道路，填充 highway 围出的区域，形成局部街区。

现代 CityEngine 文档中更常见的是 major / minor streets：

- major streets 基本对应论文里的 highway 层，但不一定都是高速路，可以是城市主路或主干路。
- minor streets 基本对应论文里的 street 层，用于细分 quarter / block。

复刻时建议在代码里用 `major: bool` 表示生成层级，用 `road_class` 表示真实道路等级。不要把 `major=True` 和 `motorway` 强绑定，否则城市主干路会被错误当成高速路处理。

### 2.2 方案评审结论

一个可复刻方案应该保留以下关键点：

1. Priority Queue：候选道路用时间 `t` 或优先级排序，模拟 L-System 的延迟生长。
2. Local Constraints：每条候选道路落地前都必须经过边界、障碍、坡度、相交、吸附、最小角检查。
3. Global Goals：接受一条道路后，再根据人口密度、模式图、道路层级生成后继候选。
4. Highway / Street 分层：主路先形成大结构，支路再填充内部街区。
5. Geometry 分离：道路中心线生长和道路面/CGA/材质生成应分开实现。

同时需要修正几个容易误导实现的地方：

- `local_constraints` 不应在检查中直接永久修改 `road_graph`。例如 `split_at()` 应先记录成操作计划，候选道路最终接受后再提交。
- 只采样候选终点的人口密度可以作为最小版，但论文风格更接近沿多条射线积分采样，并加入距离衰减。
- CGA 不是道路网络生成算法本身，而是道路图和街区 shape 生成后的几何/材质规则层。
- 两条垂直 seed road 是可用的最小初始化，但真实系统通常允许从外部入口、已有道路、城市中心、边界点或多中心 seed 同时生长。

## 3. 最小数据结构

建议先定义以下数据结构。Python 里可以先用 dataclass 或 dict，等逻辑稳定后再拆成模块。

```python
class Node:
    id: str
    x: float
    z: float
    y: float = 0.0
    edges: list[str]
    kind: str  # normal, crossing, dead_end, seed


class Edge:
    id: str
    from_node: str
    to_node: str
    points: list[tuple[float, float]]  # XZ polyline
    road_class: str  # motorway, primary, secondary, residential...
    major: bool
    width: float
    lanes: int
    pattern: str  # organic, raster, radial


class Candidate:
    start_node: str
    angle: float
    length: float
    t: float
    major: bool
    road_class: str
    priority: float
    pattern: str
    parent_edge: str | None
    generation: int
    metadata: dict
```

图对象至少需要：

```python
class RoadGraph:
    nodes: dict[str, Node]
    edges: dict[str, Edge]
    spatial_node_index: SpatialIndex
    spatial_edge_index: SpatialIndex
    faces: list[Face]
```

空间索引用 grid hash 就够：

```python
cell = int(x // cell_size), int(z // cell_size)
```

道路级别建议使用通用道路等级配置：

- motorway / trunk：高速或城市快速路。
- primary / secondary：主干路。
- tertiary：次干路。
- residential / service：街区内部道路。
- footway / pedestrian：步行道路。

宽度、车道、人行道等参数应独立放在配置文件里，例如：

```text
road_profiles.json
```

这样道路算法不会依赖任何具体工程的脚本路径。

## 4. 输入图层

复刻 CityEngine 的道路生长，建议准备以下输入图层。

### 4.1 边界

城市生成区域 polygon 或 bbox：

```python
bounds = Polygon(...)
```

所有候选道路必须落在边界内，超出边界时裁剪或拒绝。

### 4.2 障碍图

障碍可以是水体、铁路、已保护地块、陡坡、不可建设区域：

```python
obstacle_map.contains(segment)
obstacle_map.intersects(segment)
```

最小版可以用 polygon list。

### 4.3 人口密度 / 吸引力图

CityEngine 原始论文里，高级道路会朝人口密度高的地方生长。最小版可以用热力点：

```python
attractors = [
    {"x": 100, "z": 200, "weight": 1.0},
    {"x": 600, "z": 350, "weight": 0.6},
]
```

方向评分：

```python
score(direction) = sum(weight / (distance_to_ray + 1.0))
```

### 4.4 模式图

模式图决定某个区域倾向于 organic、raster 还是 radial。

```python
def pattern_at(x, z):
    if inside_old_town(x, z):
        return "organic"
    if inside_new_district(x, z):
        return "raster"
    if near_city_center(x, z):
        return "radial"
```

### 4.5 地形图

最小版可以忽略地形。第二阶段再加入：

- 道路尽量避免过大坡度。
- 端点高度从 DEM 采样。
- 跨越水体或沟壑时可标记 bridge / tunnel。

## 5. 主生成循环

整体伪代码：

```python
def grow_city_streets(seed_graph, params):
    graph = seed_graph
    frontier = init_frontier(graph, params)

    while frontier and graph.edge_count < params.max_edges:
        current = frontier.pop_highest_priority()

        major = choose_major_or_minor(graph, params)
        candidate = propose_candidate(current, graph, major, params)

        if candidate is None:
            continue

        result = apply_local_constraints(candidate, graph, params)

        if not result.accepted:
            continue

        edge, new_node = graph.insert_edge(result)
        graph.cleanup_incremental(edge)

        if should_expand_from(new_node, graph, params):
            frontier.push(make_frontier(new_node, edge, params))

        if major:
            update_quarters(graph)
        else:
            update_blocks(graph)

    return graph
```

关键点：

- 不是一次生成整张网，而是每次只接受一条候选道路。
- 每条候选道路都要经过局部约束。
- 每次插入道路后，都要更新图的拓扑关系。
- major 和 minor 的生成策略不同。

### 5.1 Priority Queue 生长引擎

原始论文风格的道路生成更像一个带延迟的 L-System / Agent 生长系统。每个候选道路段都有一个时间 `t`，主循环每次取出 `t` 最小的候选段处理。这样可以表达“主路先长、支路延迟出现、局部区域逐渐填充”的效果。

推荐最小结构：

```python
import heapq


def generate_roads(config, population_map, elevation_map):
    graph = RoadGraph()
    pq = []
    serial = 0

    for seed in make_seed_segments(config):
        heapq.heappush(pq, (seed.t, serial, seed))
        serial += 1

    while pq and graph.edge_count < config.max_segments:
        _t, _serial, candidate = heapq.heappop(pq)

        plan = local_constraints(candidate, graph, elevation_map, config)
        if not plan.accepted:
            continue

        edge_id, end_node_id = graph.commit(plan)

        successors = global_goals(
            accepted_edge=graph.edges[edge_id],
            end_node=graph.nodes[end_node_id],
            graph=graph,
            population_map=population_map,
            config=config,
        )

        for nxt in successors:
            heapq.heappush(pq, (nxt.t, serial, nxt))
            serial += 1

    cleanup_graph(graph, config)
    return graph
```

这里的 `serial` 是稳定排序用的。如果两个候选段 `t` 相同，Python 的 heap 不需要比较 Candidate 对象本身。

### 5.2 Seed 初始化策略

最小实现可以从城市中心放两条互相垂直的主路：

```python
seed_a = Candidate(center, angle=0, length=major_len, t=0, major=True)
seed_b = Candidate(center, angle=pi / 2, length=major_len, t=0, major=True)
```

更稳的实现建议支持多种 seed：

- city_center：从城市中心向外长。
- boundary_gate：从边界入口向内长，适合接外部道路。
- existing_roads：以已有 OSM 道路端点作为 seed。
- attractor_pair：在两个吸引点之间先放一条主路。
- multi_center：多个中心同时生长，适合多组团城市。

### 5.3 Delay Time 设计

`t` 不一定是真实时间，它是调度优先级：

```python
straight_successor.t = current.t + 1
branch_successor.t = current.t + branch_delay
minor_successor.t = current.t + minor_delay
```

推荐：

```python
major_straight_delay = 1
major_branch_delay = 8
minor_straight_delay = 1
minor_branch_delay = 4
```

效果：

- 主方向会先连续长出去。
- 支路会晚几步出现。
- dense 区域可降低 branch_delay，让街网更快填充。

### 5.4 Branch 元数据

候选段最好保留来源信息，方便调试和后处理：

```python
metadata = {
    "source": "population_gradient",
    "parent_edge": edge_id,
    "turn_angle_deg": 15,
    "density_score": 0.72,
    "constraint_result": "snapped_to_node",
}
```

输出到 GeoJSON 时也保留这些属性，后面可以在 Houdini 或调试视图里给不同来源的道路上色。

## 6. Major / Minor 生成策略

CityEngine 的 major street 先围出 quarter，minor street 再细分 quarter。

可以这样实现：

```python
def choose_major_or_minor(graph, params):
    if graph.major_edge_count < params.min_major_edges:
        return True

    if not graph.has_enough_quarters():
        return True

    ratio = graph.major_valence2_node_count / max(1, graph.major_crossing_node_count)
    if ratio < params.major_street_to_crossing_ratio:
        return True

    return False
```

其中：

- valence2 node：度数为 2 的道路中间节点。
- crossing node：度数大于 2 的路口节点。
- street_to_crossing_ratio 越高，主路之间距离越长，quarter 越大。
- street_to_crossing_ratio 越低，主路网络越密。

Minor road 应该在 quarter 内生长：

```python
quarter = pick_quarter_face(graph)
candidate = propose_inside_polygon(start_node, quarter)
```

候选道路如果穿出 quarter，则裁剪到 quarter 边界或拒绝。

## 7. Global Goals：候选道路提案

Global Goals 只负责提出候选道路，不负责最终接受。

### 7.1 Organic 模式

Organic 适合老城区、自然生长街区。

特征：

- 方向延续上一条路，但允许随机弯曲。
- 路段长度较短。
- 路口角度不严格正交。
- 更容易受障碍、地形、已有道路影响。

伪代码：

```python
def propose_organic(node, prev_edge, params):
    base_angle = angle_of(prev_edge, at_node=node)
    angle = base_angle + random_uniform(-params.organic_bend, params.organic_bend)
    length = random_uniform(params.organic_min_len, params.organic_max_len)
    return make_segment(node, angle, length)
```

推荐参数：

```python
organic_bend = radians(35)
organic_min_len = 40
organic_max_len = 120
```

### 7.2 Raster / Grid 模式

Raster 适合规则网格街区。

特征：

- 道路方向贴近两个主轴。
- 路口接近 90 度。
- 路段长度较稳定。

伪代码：

```python
def propose_raster(node, prev_edge, params):
    grid_angle = local_grid_angle(node.x, node.z)
    candidates = [
        grid_angle,
        grid_angle + pi / 2,
        grid_angle + pi,
        grid_angle + 3 * pi / 2,
    ]

    if prev_edge:
        candidates = remove_backtracking(candidates, prev_edge)

    angle = choose_best_by_density_and_spacing(candidates)
    length = random_uniform(params.grid_min_len, params.grid_max_len)
    return make_segment(node, angle, length)
```

推荐参数：

```python
grid_min_len = 80
grid_max_len = 180
grid_angle_noise = radians(3)
```

### 7.3 Radial 模式

Radial 适合围绕中心扩散的城市结构。

特征：

- 一类道路从中心向外放射。
- 一类道路绕中心形成环路或切向路。
- 常用于广场、环岛、中心商务区周边。

伪代码：

```python
def propose_radial(node, center, prev_edge, params):
    radial = atan2(node.z - center.z, node.x - center.x)
    tangent = radial + pi / 2

    if random() < params.radial_outward_probability:
        angle = radial
    else:
        angle = tangent

    angle += random_uniform(-params.radial_noise, params.radial_noise)
    length = random_uniform(params.radial_min_len, params.radial_max_len)
    return make_segment(node, angle, length)
```

推荐参数：

```python
radial_outward_probability = 0.55
radial_noise = radians(8)
radial_min_len = 70
radial_max_len = 180
```

### 7.4 人口密度驱动主路

原始 CityEngine 论文里，主路会朝人口密度高的地方生长。可以用射线采样复刻：

```python
def propose_population_driven(node, prev_edge, density_map, params):
    base = angle_of(prev_edge, at_node=node) if prev_edge else 0
    best = None

    for delta in linspace(-params.max_turn, params.max_turn, params.ray_count):
        angle = base + delta
        score = 0

        for d in range(params.sample_step, params.lookahead, params.sample_step):
            p = node.position + direction(angle) * d
            score += density_map.sample(p) * exp(-d / params.distance_decay)

        score -= abs(delta) * params.turn_penalty

        if best is None or score > best.score:
            best = (angle, score)

    length = params.major_segment_length
    return make_segment(node, best.angle, length)
```

推荐参数：

```python
max_turn = radians(60)
ray_count = 9
lookahead = 600
sample_step = 50
distance_decay = 350
turn_penalty = 0.2
major_segment_length = 180
```

## 8. Local Constraints：局部约束

Local Constraints 是复刻质量的关键。

处理顺序建议固定：

1. 边界裁剪。
2. 障碍检测。
3. 与已有边相交检测。
4. 端点吸附到附近节点。
5. 端点吸附到附近边，并切分该边。
6. 最小角度检查。
7. 最小长度检查。
8. 最终接受或拒绝。

### 8.1 事务式约束计划

实现时不要让 `local_constraints()` 一边检查一边直接修改 `road_graph`。例如候选道路在第 4 步发现相交时，如果马上 `split_edge()`，但第 6 步最小角检查失败，图就已经被污染了。

推荐返回一个 `ConstraintPlan`：

```python
class ConstraintPlan:
    accepted: bool
    reason: str
    candidate: Candidate | None
    final_start: tuple[float, float] | None
    final_end: tuple[float, float] | None
    end_node_id: str | None
    operations: list[GraphOperation]
    metadata: dict


class GraphOperation:
    kind: str  # split_edge, merge_node, create_node, add_edge
    payload: dict
```

`local_constraints()` 只做检测并生成计划：

```python
plan.operations.append({
    "kind": "split_edge",
    "payload": {"edge_id": hit.edge_id, "point": hit.point}
})
```

真正修改图放在：

```python
edge_id, end_node_id = graph.commit(plan)
```

这样可以保证：

- 候选段被拒绝时，图完全不变。
- 每次接受道路的拓扑操作可记录到日志。
- 单元测试可以直接检查 plan 是否合理。

### 8.2 局部约束完整伪代码

最小版也应返回 `ConstraintPlan`，不要直接修改 graph：

```python
def local_constraints(candidate, graph, params):
    plan = ConstraintPlan(accepted=False, reason="", candidate=candidate)
    seg = candidate.segment

    seg = clip_to_bounds(seg, params.bounds)
    if seg is None:
        plan.reason = "outside_bounds"
        return plan

    if intersects_obstacle(seg, params.obstacles):
        seg = try_avoid_obstacle(seg, params)
        if seg is None:
            plan.reason = "obstacle"
            return plan

    hit = first_intersection(seg, graph.edges)
    if hit:
        seg.end = hit.point
        plan.operations.append(GraphOperation("split_edge", {
            "edge_id": hit.edge_id,
            "point": hit.point,
        }))
        plan.operations.append(GraphOperation("create_or_reuse_node", {
            "point": hit.point,
            "kind": "crossing",
        }))
        plan.reason = "intersect_existing"
        plan.final_start = seg.start
        plan.final_end = seg.end
        plan.accepted = True
        return plan

    near_node = graph.find_node_near(seg.end, params.snap_node_distance)
    if near_node:
        seg.end = near_node.position
        plan.end_node_id = near_node.id
        plan.reason = "snap_node"
    else:
        near_edge = graph.find_edge_near(seg.end, params.snap_edge_distance)
        if near_edge:
            snap_point = project_point_to_edge(seg.end, near_edge)
            seg.end = snap_point
            plan.operations.append(GraphOperation("split_edge", {
                "edge_id": near_edge.id,
                "point": snap_point,
            }))
            plan.reason = "snap_edge"
        else:
            plan.operations.append(GraphOperation("create_node", {
                "point": seg.end,
                "kind": "normal",
            }))
            plan.reason = "new_node"

    if violates_min_angle(seg, graph, plan, params.min_intersection_angle):
        plan.accepted = False
        plan.reason = "bad_angle"
        plan.operations.clear()
        return plan

    if length(seg) < params.min_segment_length:
        plan.accepted = False
        plan.reason = "too_short"
        plan.operations.clear()
        return plan

    plan.operations.append(GraphOperation("add_edge", {
        "start": seg.start,
        "end": seg.end,
        "candidate": candidate,
    }))
    plan.final_start = seg.start
    plan.final_end = seg.end
    plan.accepted = True
    return plan
```

增强版建议改成事务式：

```python
def local_constraints(candidate, graph, elevation_map, params):
    plan = ConstraintPlan(accepted=False, reason="", candidate=candidate)
    seg = candidate.to_segment()

    clipped = clip_to_bounds(seg, params.bounds)
    if clipped is None:
        plan.reason = "outside_bounds"
        return plan
    seg = clipped

    water_hit = params.water_mask.intersects(seg) if params.water_mask else False
    if water_hit and not candidate.major:
        plan.reason = "water"
        return plan

    if elevation_map and not candidate.major:
        slope = elevation_map.slope_between(seg.start, seg.end)
        if slope > params.max_slope:
            rotated = find_rotated_low_slope_segment(seg, elevation_map, params)
            if rotated is None:
                plan.reason = "slope"
                return plan
            seg = rotated

    hit = graph.first_intersection(seg)
    if hit:
        seg.end = hit.point
        plan.operations.append(GraphOperation("split_edge", {
            "edge_id": hit.edge_id,
            "point": hit.point,
        }))
        plan.operations.append(GraphOperation("create_or_reuse_node", {
            "point": hit.point,
            "kind": "crossing",
        }))
        plan.accepted = validate_final_segment(seg, graph, params)
        plan.final_start = seg.start
        plan.final_end = seg.end
        plan.reason = "intersect_existing"
        return plan

    near_node = graph.find_node_near(seg.end, params.snap_node_distance)
    if near_node:
        seg.end = near_node.position
        plan.end_node_id = near_node.id
        plan.reason = "snap_node"
    else:
        near_edge = graph.find_edge_near(seg.end, params.snap_edge_distance)
        if near_edge:
            snap_point = project_point_to_edge(seg.end, near_edge)
            seg.end = snap_point
            plan.operations.append(GraphOperation("split_edge", {
                "edge_id": near_edge.id,
                "point": snap_point,
            }))
            plan.reason = "snap_edge"
        else:
            plan.operations.append(GraphOperation("create_node", {
                "point": seg.end,
                "kind": "normal",
            }))
            plan.reason = "new_node"

    if violates_min_angle(seg, graph, plan, params.min_intersection_angle):
        return ConstraintPlan(accepted=False, reason="bad_angle")

    if length(seg) < params.min_segment_length:
        return ConstraintPlan(accepted=False, reason="too_short")

    plan.operations.append(GraphOperation("add_edge", {
        "start": seg.start,
        "end": seg.end,
        "candidate": candidate,
    }))
    plan.accepted = True
    plan.final_start = seg.start
    plan.final_end = seg.end
    return plan
```

### 8.3 相交检测

所有道路中心线在 XZ 平面做 2D segment intersection：

```python
def segment_intersection(a, b, c, d):
    # 返回交点或 None
```

如果新道路穿过已有道路：

- 把新道路终点截断到交点。
- 把已有道路在交点处切成两条边。
- 交点变成 crossing node。

### 8.4 吸附节点

如果候选终点距离已有节点很近，直接连接到该节点：

```python
if distance(candidate.end, node.position) < snap_node_distance:
    candidate.end = node.position
```

推荐参数：

```python
snap_node_distance = 15
```

### 8.5 吸附边

如果终点靠近一条已有道路但没有相交，把终点投影到那条道路上，并切分旧边：

```python
projection = closest_point_on_polyline(candidate.end, edge.points)
if distance(candidate.end, projection) < snap_edge_distance:
    split_edge(edge, projection)
```

推荐参数：

```python
snap_edge_distance = 12
```

### 8.6 最小角度

避免产生很尖的路口：

```python
if angle_between(new_edge, incident_edge) < min_angle:
    reject
```

推荐参数：

```python
min_intersection_angle = radians(25)
```

### 8.7 障碍处理

最小版：

```python
if obstacle.intersects(seg):
    reject
```

增强版：

```python
for delta in [-30, -20, -10, 10, 20, 30]:
    rotated = rotate(seg, delta)
    if not obstacle.intersects(rotated):
        accept(rotated)
```

高速路可以允许桥或隧道：

```python
if candidate.major and obstacle_width < max_bridge_span:
    candidate.tags["bridge"] = True
    accept
```

## 9. 图清理

道路图生成后需要一次全局 cleanup。

步骤：

1. Intersect：所有交叉边补交点并切分。
2. Snap：近距离端点吸附到节点或边。
3. Merge：距离过近的节点合并。
4. Remove short edges：删除或折叠过短边。
5. Resolve conflicts：冲突道路形状折叠到中心线或合并。
6. Rebuild adjacency：重建 node.edges 和 edge endpoints。

最小伪代码：

```python
def cleanup_graph(graph, params):
    split_all_intersections(graph)
    snap_dangling_nodes(graph, params.snap_node_distance)
    snap_nodes_to_edges(graph, params.snap_edge_distance)
    merge_close_nodes(graph, params.merge_node_distance)
    collapse_short_edges(graph, params.min_segment_length)
    rebuild_adjacency(graph)
```

这些后处理应作为独立模块实现：

- `graph_cleanup`：相交切分、端点吸附、短边折叠、节点合并。
- `junction_solver`：路口分类、路口裁剪、冲突短边处理。
- `mesh_backend`：根据道路中心线和路口拓扑生成道路面片。

## 10. 从道路图提取 Quarter / Block

道路中心线图必须是平面图，才能提取面。

### 10.1 半边遍历

每条边生成两个 directed half-edge：

```python
HalfEdge = {
    edge_id,
    from_node,
    to_node,
    angle,
    visited
}
```

每个节点按角度排序出边：

```python
outgoing[node].sort(key=lambda he: he.angle)
```

遍历面：

```python
def trace_faces(graph):
    faces = []

    for he in all_half_edges:
        if he.visited:
            continue

        face = []
        cur = he

        while not cur.visited:
            cur.visited = True
            face.append(cur.from_node)

            rev = reverse_half_edge(cur)
            cur = previous_edge_ccw_at_node(rev.to_node, rev)

        if area(face) > min_area:
            faces.append(face)

    return faces
```

原则：

- 面积最大的外轮廓通常是外部面，要丢弃。
- major edges 围出的面是 quarter。
- 所有 edges 围出的面是 block。

### 10.2 Quarter 选择

Minor roads 应该选择一个未充分细分的 quarter：

```python
def pick_quarter(graph):
    candidates = [f for f in graph.faces if f.is_major_face]
    candidates = [f for f in candidates if f.area > min_quarter_area]
    return weighted_random(candidates, weight=lambda f: f.area)
```

### 10.3 Block 终止条件

一个 block 不再细分，当：

- 面积小于阈值。
- 宽度小于阈值。
- 已达到目标道路密度。
- 内部生成候选道路连续失败。

```python
if face.area < min_block_area:
    stop
```

## 11. 地块 Lot 切分

CityEngine 的 block 参数里常见三种切分方式：recursive subdivision、offset subdivision、skeleton subdivision。

### 11.1 Recursive Subdivision

最容易实现。

```python
def subdivide_recursive(poly):
    if area(poly) < min_lot_area:
        return [poly]

    obb = minimum_bounding_box(poly)
    split_axis = longer_axis(obb)
    line = split_line_through_center(poly, split_axis)
    a, b = split_polygon(poly, line)

    return subdivide_recursive(a) + subdivide_recursive(b)
```

优点：简单。  
缺点：不一定保证所有地块临街。

### 11.2 Offset Subdivision

更像 CityEngine 的常用地块结果。

```python
def subdivide_offset(block):
    street_edges = classify_street_edges(block)
    lots = []

    for edge in street_edges:
        strip = offset_inward_from_edge(edge, lot_depth)
        lots += split_strip_by_lot_width(strip)

    inner = remaining_core(block, lots)
    if area(inner) > min_lot_area:
        lots += subdivide_recursive(inner)

    return lots
```

优点：临街地块效果好。  
缺点：需要 polygon boolean / offset 库。

### 11.3 Skeleton Subdivision

效果最城市化，但实现最复杂。可以依赖第三方 geometry 库。

基本思想：

- 对 block polygon 计算 straight skeleton。
- 每条街边向内传播。
- skeleton 把 block 分成若干面，每个面归属最近街边。
- 每个面再按宽度切地块。

## 12. 道路宽度和路口几何

道路图生成的是中心线，最终要变成道路面。

### 12.1 道路宽度

宽度来源优先级建议：

1. 显式 width。
2. lanes * lane_width。
3. road_class 默认值。
4. 按区域或图重要性修正。

```python
def road_width(edge):
    if edge.width:
        return edge.width
    if edge.lanes:
        return edge.lanes * 3.2
    return default_width_by_class[edge.road_class]
```

建议用独立配置保存道路宽度规则：

```text
road_profiles.json
```

如果使用 Houdini 作为几何后端，再把这些配置转成 SOP/VEX/Python SOP 可读的属性。

### 12.2 中心线扩宽

每条 polyline 做左右 offset：

```python
left = offset_polyline(edge.points, +edge.width / 2)
right = offset_polyline(edge.points, -edge.width / 2)
road_polygon = left + reversed(right)
```

不要直接让所有道路 polygon 相互覆盖。需要在路口处裁剪。

### 12.3 路口分类

建议使用以下通用路口分类：

```python
def junction_style(incident_edges):
    if len(incident_edges) < 3:
        return "None"
    if any(e.road_class in ["motorway", "trunk"] for e in incident_edges):
        return "Freeway"
    widths = sorted([e.width for e in incident_edges], reverse=True)
    if widths[0] / widths[1] >= 1.5:
        return "Junction"
    return "Crossing"
```

### 12.4 路口裁剪距离

可使用以下通用裁剪公式：

```python
clip_margin = max_neighbor_half_width / (2 * sin(min_angle)) + junction_radius
```

推荐半径：

```python
Crossing: 6m
Junction: 5m
Freeway: 20m
Roundabout: 4m
```

### 12.5 路口面片

流程：

1. 对每条 incident road 在路口前裁剪。
2. 获取裁剪后的左右边界点。
3. 把所有边界点按绕路口中心的角度排序。
4. 生成 junction fan polygon。
5. 如果 polygon 自交，退化成三角扇。

这一部分应该归入独立的 `road_mesh_builder` 或 Houdini Python SOP 后端，而不是写死在道路生长算法里。

### 12.6 CGA / Shape Grammar 层的定位

CityEngine 的 CGA Shape Grammar 主要负责“已有 shape 如何变成几何”，不是道路中心线网络的生长核心。复刻时应把它放在后处理层：

```text
Road graph centerlines
  -> road width assignment
  -> road surface polygons
  -> sidewalk / lane / curb split
  -> materials / markings / props
```

一个可复刻的规则表达可以长这样：

```text
Street(width, sidewalk_l, sidewalk_r)
  -> split_width {
       sidewalk_l : Sidewalk
       ~1         : Carriageway
       sidewalk_r : Sidewalk
     }

Carriageway(lanes, lane_width)
  -> repeat(lane_width) { Lane }

Sidewalk
  -> curb + pavement + optional street_furniture

Intersection
  -> single intersection surface
  -> optional crosswalk markings
```

独立道路模块不一定要实现完整 CGA 解释器。更实用的路线是：

- Python 阶段输出 centerline + `road_class/width/lanes/sidewalk_l/sidewalk_r` 属性。
- 几何后端阶段用 Houdini SOP/VEX、Blender Geometry Nodes、Unity Mesh API 或自研 mesh builder 按属性切路面、人行道、路缘石。
- 渲染/游戏引擎阶段只消费已经生成好的 mesh、curve 或 actor。

这样比先写一个完整 CGA 语言解释器更稳，也更适合先验证道路算法。

### 12.7 几何层最小实现

最小版只需要：

```python
for edge in graph.edges:
    road_poly = offset_centerline(edge.points, edge.width / 2)
    emit_polygon(road_poly, kind="road")

for node in graph.nodes:
    if node.degree >= 3:
        junction_poly = build_junction_patch(node, graph)
        emit_polygon(junction_poly, kind="intersection")
```

增强版再拆：

```python
surface = split_width(road_poly, [
    ("sidewalk_l", sidewalk_l),
    ("carriageway", width - sidewalk_l - sidewalk_r),
    ("sidewalk_r", sidewalk_r),
])
```

车道线、材质、路缘石、护栏、路灯都应在道路拓扑稳定后再加。

## 13. 推荐参数表

```python
params = {
    "max_edges": 2000,
    "min_segment_length": 25,
    "snap_node_distance": 15,
    "snap_edge_distance": 12,
    "merge_node_distance": 3,
    "min_intersection_angle": radians(25),

    "major_segment_length": 180,
    "minor_segment_length": 90,
    "major_street_to_crossing_ratio": 4.0,

    "organic_bend": radians(35),
    "organic_min_len": 40,
    "organic_max_len": 120,

    "grid_min_len": 80,
    "grid_max_len": 180,
    "grid_angle_noise": radians(3),

    "radial_outward_probability": 0.55,
    "radial_noise": radians(8),
    "radial_min_len": 70,
    "radial_max_len": 180,

    "population_ray_count": 9,
    "population_lookahead": 600,
    "population_sample_step": 50,
    "population_distance_decay": 350,
}
```

### 13.1 城市风格 Preset

可以把参数组织成 preset，方便同一套算法生成不同城市形态。

```python
manhattan_config = {
    "pattern": "raster",
    "grid_angle_noise": radians(1),
    "minor_branch_probability": 0.85,
    "street_length": 80,
    "snap_node_distance": 18,
    "min_intersection_angle": radians(70),
}

organic_old_town_config = {
    "pattern": "organic",
    "organic_bend": radians(35),
    "minor_branch_probability": 0.45,
    "street_length": 70,
    "snap_node_distance": 12,
    "min_intersection_angle": radians(25),
}

radial_center_config = {
    "pattern": "radial",
    "radial_outward_probability": 0.55,
    "radial_noise": radians(8),
    "major_segment_length": 160,
    "minor_branch_probability": 0.55,
}

suburban_config = {
    "pattern": "organic",
    "major_segment_length": 220,
    "street_length": 160,
    "minor_branch_probability": 0.2,
    "snap_node_distance": 25,
}
```

注意：如果生成区域只有 1km 到 2km，`highway_length = 400-1000m` 会过大，容易几步就穿出边界。小区域 MVP 更建议：

```python
major_segment_length = 120-250
minor_segment_length = 50-120
snap_node_distance = 8-20
snap_edge_distance = 8-18
```

如果生成完整城市或 10km 级别区域，再把主路步长提高到 400m 以上。

## 14. 独立道路模块实现路线

道路模块应拆成“算法核心”和“适配层”两部分：

```text
road_module/
  core/
    growth.py
    local_constraints.py
    graph.py
    graph_cleanup.py
    faces.py
    lot_subdivision.py
  io/
    geojson_io.py
    osm_io.py
    config_io.py
  mesh/
    road_surface.py
    junction_mesh.py
    curb_sidewalk.py
  backends/
    houdini/
    blender/
    unreal/
  tests/
    test_growth.py
    test_constraints.py
    test_faces.py
```

核心层只处理道路图、几何约束、面提取和属性，不依赖任何具体工程目录，也不依赖 Houdini/UE/Blender。

这套结构可以和 OSM 管线共用后半段，但前半段入口不同：

- OSM 真实数据管线负责把 `roads_clean.geojson` 转成 `road_graph.json`。
- CityEngine 生长管线负责从 seed / bounds / density / obstacles 生成 `road_graph.json`。
- Houdini、Blender、Unreal 等几何后端只消费统一的 `road_graph.json`，不关心道路来自真实数据还是程序化生成。

### 14.1 第一阶段：只生成中心线

输入：

```text
growth_config.json
bounds.geojson
optional_density_map.tif / density_points.geojson
optional_obstacles.geojson
optional_seed_roads.geojson
```

输出：

```text
roads_generated.geojson
road_graph.json
growth_report.json
```

GeoJSON feature 属性：

```json
{
  "road_class": "residential",
  "major": false,
  "pattern": "raster",
  "width": 6.0,
  "lanes": 2
}
```

### 14.2 第二阶段：构建 road_graph

```python
graph = RoadGraph.from_geojson("roads_generated.geojson")
cleanup_graph(graph, params)
faces = trace_faces(graph)
graph.write_json("road_graph.json")
```

`road_graph.json` 是独立道路模块和所有几何后端之间的稳定契约。

### 14.3 第三阶段：选择几何后端

同一个 `road_graph.json` 可以喂给不同后端：

```text
road_graph.json
  -> Houdini SOP/Python SOP
  -> Blender Geometry Nodes / Python
  -> Unreal Procedural Mesh
  -> Unity Mesh API
  -> Three.js debug viewer
```

### 14.4 可选工程适配层

如果要接入某个既有工程，应新增适配层，而不是让核心道路模块直接引用工程脚本：

```text
adapters/
  virtual_city_adapter.py
  houdini_adapter.py
  unreal_adapter.py
```

适配层只负责路径、坐标约定、格式转换和现有节点/脚本调用。算法核心不应 import 工程专用模块。

## 15. 最小可跑版本伪代码

本节只适用于路线 B：程序化道路生成。如果当前目标是 OSM 真实城市素模，早期应跳过本节实现，直接推进 `DataProvider -> clean_pipeline.py -> road_surface_builder`。

```python
def run_minimal_cityengine(bounds, seed_points):
    graph = RoadGraph()
    frontier = []

    for p in seed_points:
        node = graph.add_node(p)
        frontier.append({"node": node.id, "prev_edge": None, "priority": 1.0})

    while frontier and len(graph.edges) < 500:
        f = pop_weighted(frontier)
        node = graph.nodes[f["node"]]

        major = len(graph.major_edges()) < 80
        pattern = pattern_at(node.x, node.z)

        if major:
            cand = propose_population_driven(node, f["prev_edge"], density_map, params)
            cand.road_class = "primary"
            cand.major = True
        elif pattern == "raster":
            cand = propose_raster(node, f["prev_edge"], params)
            cand.road_class = "residential"
        elif pattern == "radial":
            cand = propose_radial(node, city_center, f["prev_edge"], params)
            cand.road_class = "secondary"
        else:
            cand = propose_organic(node, f["prev_edge"], params)
            cand.road_class = "residential"

        result = apply_local_constraints(cand, graph, params)
        if not result.accepted:
            continue

        edge_id, end_node_id = graph.insert(result)

        if graph.nodes[end_node_id].degree < 4:
            frontier.append({
                "node": end_node_id,
                "prev_edge": edge_id,
                "priority": compute_priority(end_node_id, graph)
            })

    cleanup_graph(graph, params)
    faces = trace_faces(graph)
    return graph, faces
```

## 16. 实现检查清单

复刻时每完成一步，都应有对应测试。

### 16.1 图生长测试

- 给一个矩形 bbox 和一个 seed，能生成不少于 N 条道路。
- 所有边都在 bbox 内。
- 没有长度小于 min_segment_length 的边。
- 没有孤立 edge。

### 16.2 局部约束测试

- 新道路穿过旧道路时会创建 crossing node。
- 新道路终点接近旧节点时会 snap。
- 新道路终点接近旧边时会 split edge。
- 小于最小角度的道路会被拒绝。

### 16.3 面提取测试

- 一个简单四边形道路图能提取 1 个内部 face。
- 网格道路能提取多个 block。
- 外部无限面被丢弃。

### 16.4 几何输出测试

- 每条 edge 都有 road_class、width、major。
- 输出 GeoJSON 能被独立 road graph importer 读取。
- 至少一个几何后端能从 road_graph.json 生成非空道路面。

## 17. 风险和注意事项

1. 不要一开始就做完整 CityEngine。先做 2D centerline graph。
2. 相交、吸附、切边是最容易出错的部分，必须单元测试。
3. 道路面片不要在生长阶段生成，先保持中心线图干净。
4. block / lot 依赖平面图，生成前必须 cleanup。
5. 地形适配应放在后处理阶段，不要让高程逻辑污染 2D 图生长。
6. 若引入 polygon boolean / offset，优先使用成熟库，不要手写复杂几何布尔。
7. `local_constraints` 必须事务化，不能在候选段最终接受前永久修改图。
8. `major` 表示生成层级，不等于真实道路类型 `motorway`。
9. CGA/Shape Grammar 是几何生成层，不要把它和道路图生长引擎耦合。

## 18. 对当前方案的补充/修改建议

如果以“Priority Queue + Local Constraints + Global Goals + CGA 几何层”的方案为基础，文档需要补充的不是推翻，而是增强工程可落地性：

需要保留：

- `RoadSegment` / `RoadGraph` / `Priority Queue` 的主循环。
- highway / street 两层生成。
- 人口密度驱动 highway，street 负责街区填充。
- 边界、水域、坡度、相交、吸附等 Local Constraints。
- 输出道路图后再做几何生成。

需要修改：

- 如果当前目标是 OSM 真实数据驱动，本文的 Priority Queue 生长引擎可延后；优先把 `road_graph.json -> road_surface_builder -> Houdini mesh` 后端做成两条路线共用。
- `local_constraints()` 应返回 `ConstraintPlan`，不要直接调用 `road_graph.split_at()` 永久改图。
- highway 方向选择不应只看候选终点人口密度，增强版应沿多条射线积分采样。
- `highway` 命名在工程中建议改为 `major`，避免和真实高速公路混淆。
- CGA 规则可以作为概念模型，但第一版优先用可调试的几何后端实现路面、人行道、路缘石切分，例如 Houdini SOP/VEX、Blender Geometry Nodes 或 Python mesh builder。
- 参数值要按生成区域尺度调整。1-2km MVP 区域用 120-250m 主路步长更合适。

可以新增但不急：

- `networkx` 用于拓扑分析。
- `shapely` 用于相交、offset、polygon split。
- `rtree` 或 `shapely.STRtree` 用于空间索引。
- Three.js 调试视图，用于快速看 2D/3D 道路生长结果。

## 19. 参考资料

- Esri CityEngine Grow Streets 文档：`https://doc.arcgis.com/en/cityengine/latest/help/help-grow-a-street.htm`
- Esri CityEngine Cleanup Streets 文档：`https://doc.arcgis.com/en/cityengine/2022.1/help/help-cleanup-streets.htm`
- Esri CityEngine Block Parameters 文档：`https://doc.arcgis.com/en/cityengine/latest/help/help-layers-block-parameters.htm`
- Parish & Müller, Procedural Modeling of Cities, 2001：`https://people.eecs.berkeley.edu/~sequin/CS285/PAPERS/Parish_Muller01.pdf`
