"""
VirtualCity — UE5 Python 初始化脚本
=====================================
UE5 启动时自动执行（放在 Content/Python/ 目录下即可）。
轮询触发文件，外部脚本写入触发文件后自动执行导入。

触发文件路径：F:/VirtualCity/.ue5_trigger
文件内容：要执行的 Python 脚本绝对路径
"""
import unreal, os

TRIGGER_FILE = r"F:/VirtualCity/.ue5_trigger"

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

# 用低频定时器检查触发文件（每 3 秒一次，不影响帧率）
def _start_timer():
    _check_trigger()
    unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)  # keep alive
    unreal.call_later(3.0, _start_timer)

unreal.call_later(3.0, _start_timer)
unreal.log("[VirtualCity] 触发文件监听已启动，路径: " + TRIGGER_FILE)
