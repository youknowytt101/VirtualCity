# _archive/

历史探索脚本归档。这些脚本已被 `_recook_new_area.py` 或其他正式脚本吸收，保留仅供追溯。

## 目录

- **road_strips_iterations/** — 道路面片生成 v3~v7 实验版本 + 辅助工具
- **snap_vex_iterations/** — 建筑贴地 VEX 修复迭代 v1~v3
- **one_off_fixes/** — 各类一次性修复脚本（已内嵌进主管线）

## 仍在使用的 `_` 前缀脚本（保留在 Scripts/ 根目录）

| 文件 | 用途 | 引用方 |
|------|------|--------|
| `_recook_new_area.py` | 核心 Houdini 换区管线 | `set_area.py` |
| `_tile_cache.py` | 本地瓦片缓存 | `set_area.py`, `cache_city_data.py` |
| `_osm_import_canonical.py` | OSM→Houdini 标准导入代码 | `_recook_new_area.py` |
| `_road_strips_v2.py` | 当前使用的道路面片生成 | `_recook_new_area.py` |
