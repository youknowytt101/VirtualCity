# 自动化插件

> 本目录是 VirtualCity 管线的自动化预留位，用于后续存放确有必要的自研脚本、非官方工具配置与接入说明。  
> 不存放 Houdini、SideFX Labs、Houdini Engine for Unreal、Cesium for Unreal、UE 官方插件等官方插件本体。

---

## 目录定位

真实项目里，MVP 阶段不建议先开发自研插件。更合理的顺序是先手动跑通流程，再把反复出现的步骤脚本化。

这套流程的主线是：

```text
地图数据 / OSM / DEM
        ↓
Houdini 手动导入 / 参数调整
        ↓
Houdini 批处理 / HDA Cook / 导出
        ↓
UE5 导入 / Bake / 手动整理
        ↓
展示关卡与可交付资产
```

本目录只作为后续自动化辅助层的预留位置：

- **MVP 阶段**：只记录流程、bbox、参数和踩坑，不开发插件。
- **重复生产阶段**：再考虑 OSM 下载、坐标检查、Houdini 批处理。
- **量产阶段**：再考虑 UE5 资产整理、Data Layer、World Partition、PDG。

---

## 推荐目录结构

```text
自动化插件/
├── README.md
├── 插件清单.md
├── manifest.json
├── 数据处理自动化/
│   └── README.md
├── Houdini自动化/
│   └── README.md
└── UE5自动化/
    └── README.md
```

---

## 不放入本目录的内容

以下属于官方插件或官方工具，不应复制到本目录：

- Houdini 安装目录。
- SideFX Labs。
- Houdini Engine for Unreal。
- Cesium for Unreal。
- Unreal Engine 官方插件。
- City Sample 官方 HDA 或官方资产包。

可以在文档中记录版本、安装位置和链接，但不要把插件本体提交进项目目录。

---

## 使用建议

第一阶段真实建议：

1. **不要先开发自研插件**。
2. **手动从 Overpass Turbo 导出 OSM**。
3. **手动在 Houdini 中导入和调参**。
4. **手动导入 UE5 并 Bake**。
5. **只保留区域配置、参数记录和问题记录**。

等 MVP 跑通、并且重复劳动明确出现后，再扩展脚本或工具。
