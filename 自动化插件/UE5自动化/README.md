# UE5 自动化

用于预留 UE5 侧的非官方 Editor Utility、Python 脚本和资产整理工具位置。

## MVP 阶段结论

第一阶段不建议先开发 UE5 自动化工具。

更现实的做法：

- 手动导入 HDA 或 Houdini 导出的静态资产。
- 手动 Bake。
- 手动整理少量 Static Mesh、Material 和关卡 Actor。
- 手动开启必要的 Nanite / Lumen 设置。
- PCG、Data Layer、World Partition 暂时只做最小验证。

## 后续何时需要脚本

只有出现以下情况，才考虑开发：

| 触发条件 | 再考虑的工具 |
|---|---|
| 单次导入资产超过几十到上百个 | 资产导入整理脚本 |
| Bake 后命名混乱 | 命名整理工具 |
| Actor 数量大且分层复杂 | Data Layer 自动分配 |
| Static Mesh 数量很多 | Nanite 批量启用工具 |
| 点位散布规则稳定 | PCG 点位转散布工具 |

当前目录先只作为预留位。
