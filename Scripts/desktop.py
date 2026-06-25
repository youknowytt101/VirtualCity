"""WorldBuilder 操作台桌面外壳：原生窗口 + 同进程内嵌 HTTP 服务。

单进程模型：HTTP 服务跑在守护线程里，pywebview 开一个原生窗口指向它。
关掉窗口 -> webview.start() 返回 -> 进程退出 -> 守护线程随之消亡。
不开浏览器、不依赖网页心跳自杀（VC_AREA_PICKER_SHUTDOWN_WITH_PAGE），
进程生命周期就是唯一的开关，因此也根除了后台节流导致的"自动关闭"。

    uv run python desktop.py
"""
from __future__ import annotations

import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

# 必须在导入 server 之前设好：服务端在模块加载时读取这两个环境变量。
os.environ["VC_AREA_PICKER_NO_BROWSER"] = "1"
os.environ.pop("VC_AREA_PICKER_SHUTDOWN_WITH_PAGE", None)

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import webview  # pywebview，Windows 上走自带的 Edge WebView2 内核

from app.area_picker import server


def _wait_ready(url: str, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    health = url + "/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health, timeout=2.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def main() -> int:
    url = f"http://{server.PICKER_HOST}:{server.PORT}"
    threading.Thread(target=server.main, daemon=True).start()
    if not _wait_ready(url):
        print("[desktop] 服务未在限定时间内就绪，已退出")
        return 1
    webview.create_window("WorldBuilder", url, width=1440, height=900)
    webview.start()  # 阻塞直到窗口关闭
    srv = server._server_ref[0]
    if srv is not None:
        srv.shutdown()  # 优雅释放 8765 端口
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
