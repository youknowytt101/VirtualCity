"""Read-only Houdini model fingerprint for behaviour-preserving refactors.

Connects to the running Houdini RPYC server (localhost:18811), samples the final
OUT_city output, and writes a deterministic JSON fingerprint. Diffing two
fingerprints (before/after a refactor) proves the model output is unchanged.

This script NEVER writes parameters or edits nodes. Reading geometry does force
a cook of the sampled node, which is the only side effect.

Usage:
    uv run python houdini_build/model_fingerprint.py [--out PATH] [--node PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import rpyc


DEFAULT_NODE = "/obj/pattaya_osm/OUT_city"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "RawData" / "_model_fingerprint.json"


def _round(value, ndigits=4):
    try:
        return round(float(value), ndigits)
    except (TypeError, ValueError):
        return value


def _attrib_summary(geo, attribs, hou):
    """Per-attribute stats: presence, size, and float min/max/mean when numeric."""
    summary = {}
    for attrib in attribs:
        name = attrib.name()
        entry = {
            "size": attrib.size(),
            "type": str(attrib.dataType()),
        }
        try:
            data_type = attrib.dataType()
            if data_type in (hou.attribData.Float, hou.attribData.Int) and attrib.size() == 1:
                vals = geo.pointFloatAttribValues(name) if attrib.type() == hou.attribType.Point else None
                if vals:
                    n = len(vals)
                    entry["count"] = n
                    entry["min"] = _round(min(vals))
                    entry["max"] = _round(max(vals))
                    entry["mean"] = _round(sum(vals) / n) if n else 0.0
        except Exception:
            pass
        summary[name] = entry
    return summary


def fingerprint(node_path: str) -> dict:
    conn = rpyc.classic.connect("localhost", 18811)
    conn._config["sync_request_timeout"] = 600
    hou = conn.modules.hou

    node = hou.node(node_path)
    if node is None:
        raise SystemExit(f"node not found: {node_path}")

    geo = node.geometry()
    if geo is None:
        raise SystemExit(f"node has no geometry: {node_path}")

    bbox = geo.boundingBox()
    fp = {
        "node": node_path,
        "hip": hou.hipFile.path(),
        "hou_version": hou.applicationVersionString(),
        "counts": {
            "points": len(geo.iterPoints()),
            "prims": len(geo.iterPrims()),
            "vertices": geo.intrinsicValue("vertexcount"),
        },
        "bbox": {
            "min": [_round(bbox.minvec()[i], 3) for i in range(3)],
            "max": [_round(bbox.maxvec()[i], 3) for i in range(3)],
        },
        "attribs": {
            "point": _attrib_summary(geo, geo.pointAttribs(), hou),
            "prim": _attrib_summary(geo, geo.primAttribs(), hou),
            "detail": _attrib_summary(geo, geo.globalAttribs(), hou),
            "vertex": sorted(a.name() for a in geo.vertexAttribs()),
        },
    }
    return fp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", default=DEFAULT_NODE)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    fp = fingerprint(args.node)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(fp, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[fingerprint] node={fp['node']}")
    print(f"  points={fp['counts']['points']} prims={fp['counts']['prims']} "
          f"vertices={fp['counts']['vertices']}")
    print(f"  bbox min={fp['bbox']['min']} max={fp['bbox']['max']}")
    print(f"  point_attribs={sorted(fp['attribs']['point'])}")
    print(f"  prim_attribs={sorted(fp['attribs']['prim'])}")
    print(f"  → {out_path}")


if __name__ == "__main__":
    main()