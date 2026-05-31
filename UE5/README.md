# UE5

> 本目录存放 VirtualCity 的 Unreal Engine 5 项目。  
> AI 判断 UE5 阶段是否开始时，优先检查这里是否存在 `.uproject` 文件。

---

## 推荐目录结构

```text
UE5/
└── VirtualCityUE/
    ├── VirtualCityUE.uproject
    └── Content/
        └── VirtualCity/
            ├── Maps/
            ├── Houdini/
            ├── Meshes/
            ├── Materials/
            ├── PCG/
            ├── Blueprints/
            └── DataLayers/
```

---

## MVP 阶段目标

第一版 UE5 只需要完成：

- 启用 Houdini Engine for Unreal。
- 导入 `VC_{area_id}_cityblock_v001.hda`。
- 在 Level 中生成城市小区块。
- Bake 为 Static Mesh / Landscape。
- 开启基础 Lumen / Nanite 设置。
- 添加简单材质和 3～5 个展示视角。

---

## 推荐 Data Layers

| Data Layer | 内容 |
|---|---|
| `DL_Terrain` | Landscape / 地形 |
| `DL_Roads` | 道路、人行道、路缘 |
| `DL_Buildings` | 建筑体量 |
| `DL_Foliage` | PCG 植被 |
| `DL_Props` | 路灯、垃圾桶、长椅 |
| `DL_Debug` | bbox、参考线、调试对象 |

---

## 推荐命名

```text
LV_{area_id}_MVP
SM_{area_id}_Buildings
SM_{area_id}_Roads
MI_{area_id}_Building_Base
PCG_{area_id}_StreetProps
```

---

## 当前状态

已创建 `VirtualCityUE` 预览项目。当前阶段用于临时导入 Houdini 静态导出文件，检查地形、道路、建筑密度和俯视效果；正式 UE5 管线仍在 Houdini 资产质量迭代完成后再推进。

本机 UE 5.7 的 ZenLocal 服务无法通过 IPv6 loopback `http://[::1]:8558` 完成健康检查。请用以下脚本启动项目，直接使用 G 盘文件缓存：

```text
UE5/Launch_VirtualCityUE.cmd
```
