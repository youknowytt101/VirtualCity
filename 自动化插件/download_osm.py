"""
VirtualCity - OSM 数据自动下载脚本
=====================================
通过 Overpass API 下载指定区域的 OSM 数据，保存为 .osm 文件。

用法:
    uv run python download_osm.py [area_name]
    uv run python download_osm.py pattaya_sai6_mvp_v2
"""

import sys, os, urllib.request, urllib.parse, time

AREAS = {
    "pattaya_sai6_mvp": {
        "bbox": (12.922, 100.866, 12.938, 100.882),  # s,w,n,e (Overpass 格式)
        "output": r"F:\VirtualCity\原始数据\OSM\pattaya_sai6_mvp_osm_v001.osm",
    },
    "pattaya_sai6_mvp_v2": {
        "bbox": (12.916, 100.860, 12.944, 100.888),  # 3km × 3km
        "output": r"F:\VirtualCity\原始数据\OSM\pattaya_sai6_mvp_v2_osm_v001.osm",
    },
}

OVERPASS_SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

def build_query(bbox):
    s, w, n, e = bbox
    return f"""
[out:xml][timeout:120];
(
  way["building"]({s},{w},{n},{e});
  way["highway"]({s},{w},{n},{e});
  relation["building"]({s},{w},{n},{e});
);
out body;
>;
out skel qt;
""".strip()


def download(area_name):
    cfg = AREAS.get(area_name)
    if not cfg:
        print(f"未知区域: {area_name}")
        print(f"可用区域: {list(AREAS.keys())}")
        sys.exit(1)

    query = build_query(cfg["bbox"])
    os.makedirs(os.path.dirname(cfg["output"]), exist_ok=True)

    for server in OVERPASS_SERVERS:
        print(f"尝试服务器: {server}")
        try:
            data = urllib.parse.urlencode({"data": query}).encode()
            req = urllib.request.Request(server, data=data,
                                         headers={"User-Agent": "VirtualCity/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                content = resp.read()

            with open(cfg["output"], "wb") as f:
                f.write(content)

            size_kb = len(content) / 1024
            print(f"已保存: {cfg['output']} ({size_kb:.0f} KB)")
            return
        except Exception as e:
            print(f"  失败: {e}")
            time.sleep(2)

    print("所有服务器均失败，请检查网络或稍后重试")
    sys.exit(1)


if __name__ == "__main__":
    area = sys.argv[1] if len(sys.argv) > 1 else "pattaya_sai6_mvp_v2"
    print(f"[VirtualCity] 下载 OSM 数据: {area}")
    download(area)
    print("完成 ✅")
