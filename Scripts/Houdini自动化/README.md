# Houdini 自动化

> 当前 Houdini 自动化已经进入主流程，不再只是预留位。
> 主要实现仍位于 `Scripts/` 根目录，本文用于说明职责边界。

---

## 当前入口

完整用户级流程由 `area_picker.py` 触发，Houdini 阶段由：

```text
Scripts/_recook_new_area.py
```

负责。

模型 QA 由：

```text
Scripts/houdini_model_qa.py
```

负责。

---

## 当前 Houdini 自动化职责

- 连接 Houdini RPYC server（默认端口 `18811`）。
- 确认 master hip 已加载。
- 动态 patch 关键 Python SOP / VEX 片段。
- 重建或修复道路、建筑、地形链路。
- 按当前 `active_area.json` recook。
- 保存 `VC_master_citygen_v001.hip`。
- 按区域归档 `VC_{area_id}_citygen_v001.hip`。
- 调用 `houdini_model_qa.py --mode quick`。
- 写入 `Config/houdini_build_status.json`。

---

## 当前质量重点

- 道路：路口、异常大面片、坡地全顶点贴地。
- 地形：`dem_subdivide` 作为所有吸附目标。
- 建筑：坡地贴地、foundation/skirt、footprint bevel、法线。
- QA：所有大几何统计在 Houdini 进程内部完成。

---

## 暂不做

- 暂不做 PDG / TOPs 批处理。
- 暂不做大规模 tile 分块。
- 暂不默认触发 UE5 导入。
- 暂不把当前快速实验逻辑封装为正式 HDA。

这些等 Houdini 输出质量稳定后再推进。
