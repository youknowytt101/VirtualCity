"""
VirtualCity - UE5 Remote Control 客户端
========================================
通过 UE5 Remote Control HTTP API 实时控制 Editor。
Editor 必须开着，端口 30010。
"""

import json, urllib.request, urllib.error

BASE_URL = "http://localhost:30010"


def _request(method, path, body=None):
    url = BASE_URL + path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def call(obj_path, func, params=None):
    return _request("PUT", "/remote/object/call", {
        "objectPath": obj_path,
        "functionName": func,
        "parameters": params or {},
        "generateTransaction": True,
    })


def get_prop(obj_path, prop):
    return _request("PUT", "/remote/object/property", {
        "objectPath": obj_path,
        "propertyName": prop,
        "access": "READ_ACCESS",
    })


def set_prop(obj_path, prop, value):
    return _request("PUT", "/remote/object/property", {
        "objectPath": obj_path,
        "propertyName": prop,
        "propertyValue": {prop: value},
        "access": "WRITE_ACCESS",
    })


def search_assets(query, cls_filter=None):
    body = {"query": query, "limit": 20}
    if cls_filter:
        body["filter"] = {"classNames": [cls_filter]}
    return _request("PUT", "/remote/search/assets", body)


def spawn_actor(asset_path, location=None, label=None):
    """将 Content Browser 资产放置到场景中"""
    loc = location or {"X": 0, "Y": 0, "Z": 0}
    params = {
        "Asset": asset_path,
        "Location": loc,
    }
    if label:
        params["ActorLabel"] = label
    return call("/Script/EditorActorSubsystem", "SpawnActorFromObject",
                {"WorldContextObject": "/Engine/Transient.UnrealEditorSubsystem_0",
                 "ObjectToUse": asset_path,
                 "SpawnLocation": loc})


def run_script(script_path):
    """在运行中的 UE5 Editor 里执行 Python 脚本文件。
    需要 DefaultEngine.ini 已开启 PythonScriptLibrary 白名单。
    """
    return _request("PUT", "/remote/object/call", {
        "objectPath": "/Script/PythonScriptPlugin.Default__PythonScriptLibrary",
        "functionName": "ExecutePythonCommandEx",
        "parameters": {
            "PythonCommand": script_path,
            "ExecutionMode": "ExecuteFile",
            "FileExecutionScope": "Private",
        },
        "generateTransaction": False,
    })


if __name__ == "__main__":
    # 快速测试：搜索已导入的资产
    print("=== 搜索建筑资产 ===")
    r = search_assets("SM_Buildings")
    print(json.dumps(r, indent=2, ensure_ascii=False))

    print("\n=== 搜索道路资产 ===")
    r = search_assets("SM_Roads")
    print(json.dumps(r, indent=2, ensure_ascii=False))
