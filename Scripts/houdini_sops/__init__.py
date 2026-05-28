"""
houdini_sops — Houdini SOP 源码文本仓库 + 加载器
================================================
把原本以多行字符串内嵌在 `_recook_new_area.py` 里的 Python SOP / VEX snippet
外置成独立文本文件，使节点逻辑可以被 git diff / code review / 回滚，
而不再被锁死在二进制 .hip 或脆弱的字符串补丁里。

约定:
  * 文件名 `.py`  = Houdini Python SOP 的 `python` parm 源码
  * 文件名 `.vex` = attribwrangle 的 `snippet` 源码
  * 占位符统一用 `__NAME__` 形式，由调用方在注入前 substitute（在本地 Python 完成，
    不在 Houdini 内完成）。例如 `__ROOT__` / `__CFG__` / `__XMIN__`。

用法:
    import houdini_sops
    code = houdini_sops.load('dem_import.py', ROOT=root_str, CFG=cfg_file)
    node.parm('python').set(code)
"""
from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).resolve().parent


def load(name: str, **subs) -> str:
    """读取 SOP 源码文本并替换 `__KEY__` 占位符。

    subs 中每个 key=value 会把文本里的 `__KEY__` 替换为 str(value)。
    替换后若仍残留任何未替换的 `__XXX__` 占位符（仅限已知 key），不报错；
    调用方应自行确保传入了所有需要的占位符。
    """
    text = (_DIR / name).read_text(encoding="utf-8")
    for key, value in subs.items():
        text = text.replace(f"__{key}__", str(value))
    return text
