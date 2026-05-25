"""
VirtualCity — UE5 Python 初始化脚本
=====================================
UE5 启动时自动执行（放在 Content/Python/ 目录下即可）。
轮询触发文件，外部脚本写入触发文件后自动执行导入。

触发文件路径：自动从当前 UE5 工程向上查找 VirtualCity 根目录
文件内容：要执行的 Python 脚本绝对路径
"""
import unreal, os

def _find_virtualcity_root():
    project_dir = unreal.Paths.project_dir()
    current = os.path.abspath(project_dir)
    while True:
        if os.path.exists(os.path.join(current, "README.md")) and os.path.exists(os.path.join(current, "Scripts")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.abspath(os.path.join(project_dir, "..", ".."))
        current = parent

TRIGGER_FILE = os.path.join(_find_virtualcity_root(), ".ue5_trigger")

def _check_trigger():
    if not os.path.exists(TRIGGER_FILE):
        return
    try:
        with open(TRIGGER_FILE, encoding="utf-8") as f:
            script_path = f.read().strip()
        os.remove(TRIGGER_FILE)
        if script_path and os.path.exists(script_path):
            unreal.log(f"[VirtualCity] 执行触发脚本: {script_path}")
            import runpy
            runpy.run_path(script_path)
            unreal.log("[VirtualCity] 触发脚本执行完毕")
    except Exception as e:
        unreal.log_warning(f"[VirtualCity] 触发脚本执行失败: {e}")

import time as _time
_last_check = [0.0]

def _tick(dt):
    now = _time.time()
    if now - _last_check[0] >= 3.0:
        _last_check[0] = now
        _check_trigger()

_ticker_handle = unreal.register_slate_post_tick_callback(_tick)
unreal.log("[VirtualCity] 触发文件监听已启动，路径: " + TRIGGER_FILE)
