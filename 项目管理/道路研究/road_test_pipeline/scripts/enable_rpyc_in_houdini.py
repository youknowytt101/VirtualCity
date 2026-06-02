"""Enable the Houdini RPYC classic service for the isolated road test pipeline.

Run this inside Houdini's Python Source Editor if port 18811 is not already
available. It starts a background RPYC server in the current Houdini process.
"""

from __future__ import annotations

import socket
import threading

import hou


HOST = "localhost"
PORT = 18811


def port_is_open(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


if port_is_open(HOST, PORT):
    print(f"[RoadTest] Houdini RPYC already available at {HOST}:{PORT}")
else:
    try:
        import rpyc
        from rpyc.utils.classic import ClassicService
        from rpyc.utils.server import ThreadedServer
    except Exception as exc:
        raise hou.NodeError(
            "RPYC is not importable in Houdini's Python environment. "
            "Install rpyc for Houdini Python or start Houdini from the VirtualCity launcher."
        ) from exc

    existing = getattr(hou.session, "_road_test_rpyc_server", None)
    if existing is not None:
        print("[RoadTest] RPYC server object already exists in hou.session.")
    else:
        server = ThreadedServer(
            ClassicService,
            hostname=HOST,
            port=PORT,
            protocol_config={
                "allow_public_attrs": True,
                "allow_pickle": True,
            },
        )
        thread = threading.Thread(target=server.start, name="road_test_rpyc_18811", daemon=True)
        thread.start()
        hou.session._road_test_rpyc_server = server
        hou.session._road_test_rpyc_thread = thread
        print(f"[RoadTest] Houdini RPYC server started at {HOST}:{PORT}")
