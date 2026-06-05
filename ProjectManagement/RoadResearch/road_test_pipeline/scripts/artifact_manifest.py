#!/usr/bin/env python3
"""Small helpers for recording pipeline artifact identity.

The road pipeline publishes many generated JSON/GeoJSON/OBJ artifacts.  A
package should say exactly which source artifacts it was built from so stale
mixed-stage outputs are visible during review.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def artifact_record(path: Path, *, root: Path) -> dict[str, Any]:
    exists = path.exists()
    record: dict[str, Any] = {
        "path": rel(path, root),
        "exists": exists,
    }
    if not exists:
        return record
    stat = path.stat()
    record.update({
        "size_bytes": stat.st_size,
        "mtime_utc": stat.st_mtime,
        "sha256": sha256_file(path),
    })
    return record


def artifact_records(paths: dict[str, Path], *, root: Path) -> dict[str, dict[str, Any]]:
    return {
        name: artifact_record(path, root=root)
        for name, path in paths.items()
    }


def missing_artifacts(records: dict[str, dict[str, Any]]) -> list[str]:
    return [
        name
        for name, record in records.items()
        if not bool(record.get("exists"))
    ]


def newest_mtime(records: dict[str, dict[str, Any]]) -> float:
    mtimes = [
        float(record.get("mtime_utc") or 0.0)
        for record in records.values()
        if bool(record.get("exists"))
    ]
    return max(mtimes) if mtimes else 0.0
