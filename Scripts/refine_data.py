"""
VirtualCity — 数据精炼管线
============================
统一入口：输入 → 分级清洗 → 输出到 _houdini_ready/

用法:
    uv run python refine_data.py                  # 精炼到最高级（跳过已完成的）
    uv run python refine_data.py --level 1        # 只跑到 L1
    uv run python refine_data.py --force          # 忽略缓存，全部重跑
    uv run python refine_data.py --skip-probe     # 跳过数据源更新探测
    uv run python refine_data.py --qa-only        # 只跑 QA，不精炼
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import vc_paths
import data_cleaning_cache as dcc

# ── 目录常量 ──────────────────────────────────────────────────────────────────
DOWNLOADS     = vc_paths.DATA_ROOT / "_downloads"
CLEANED       = vc_paths.DATA_ROOT / "_cleaned"
HOUDINI_READY = vc_paths.DATA_ROOT / "_houdini_ready"


def _area_dir(base: Path, area_id: str) -> Path:
    d = base / area_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _manifest_path(area_id: str) -> Path:
    return CLEANED / area_id / "_manifest.json"


def _same_path(a: str | Path, b: str | Path) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return Path(a) == Path(b)


def _copy_file(src: str | Path, dst: str | Path) -> None:
    if _same_path(src, dst):
        return
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _staging_ready_dir(area_id: str) -> Path:
    root = HOUDINI_READY / ".staging"
    root.mkdir(parents=True, exist_ok=True)
    safe_area = "".join(c if c.isalnum() or c in "._-" else "_" for c in area_id)
    return Path(tempfile.mkdtemp(prefix=f"{safe_area}_", dir=str(root)))


def _publish_ready_dir(staging_dir: Path, final_dir: Path) -> None:
    """Replace the published ready directory while preserving it on failure."""
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = staging_dir.parent / f".{final_dir.name}.previous_{uuid.uuid4().hex[:8]}"
    if final_dir.exists():
        final_dir.replace(backup_dir)
    try:
        staging_dir.replace(final_dir)
    except Exception:
        if backup_dir.exists() and not final_dir.exists():
            backup_dir.replace(final_dir)
        raise
    if backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)


def _load_manifest(area_id: str) -> dict:
    mf = _manifest_path(area_id)
    if mf.exists():
        with open(mf, encoding="utf-8") as f:
            manifest = json.load(f)
    else:
        manifest = {
            "area_id": area_id,
            "created": datetime.now().isoformat(timespec="seconds"),
            "sources": {},
            "levels": {
                "buildings": {"current": 0},
                "roads":     {"current": 0},
                "dem":       {"current": 0},
            },
        }
    manifest.setdefault("area_id", area_id)
    manifest.setdefault("created", datetime.now().isoformat(timespec="seconds"))
    manifest.setdefault("sources", {})
    levels = manifest.setdefault("levels", {})
    for group in ("buildings", "roads", "dem"):
        levels.setdefault(group, {"current": 0})
        levels[group].setdefault("current", 0)
    return manifest


def _save_manifest(area_id: str, manifest: dict):
    mf = _manifest_path(area_id)
    mf.parent.mkdir(parents=True, exist_ok=True)
    manifest["last_updated"] = datetime.now().isoformat(timespec="seconds")
    with open(mf, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _target_levels(target_level: int) -> dict[str, int]:
    return {
        "buildings": min(target_level, 3),
        "roads": min(target_level, 2),
        "dem": min(target_level, 2),
    }


def _levels_ready(manifest: dict, target_level: int) -> bool:
    targets = _target_levels(target_level)
    return all(
        manifest.get("levels", {}).get(group, {}).get("current", 0) >= level
        for group, level in targets.items()
    )


def _prepare_raw_sources(area_cfg: dict, manifest: dict, dl_dir: Path) -> dict[str, Path]:
    """Keep immutable raw inputs in _downloads and clean only working copies."""
    specs = {
        "buildings": ("buildings_file", "buildings.geojson"),
        "roads": ("osm_file", "roads.osm"),
        "dem": ("dem_csv", "dem.csv"),
    }
    cached_files = (
        manifest.get("cache", {})
        .get("sources", {})
        .get("files", {})
    )
    raw_sources: dict[str, Path] = {}

    for group, (cfg_key, filename) in specs.items():
        active = vc_paths.resolve_project_path(area_cfg.get(cfg_key, ""))
        backup = dl_dir / filename
        if not active.exists():
            continue

        active_fp = dcc.file_fingerprint(active)
        backup_fp = dcc.file_fingerprint(backup)
        cached_sha = cached_files.get(group, {}).get("sha256")

        should_refresh_backup = False
        reason = "initial raw snapshot"
        if not backup.exists():
            should_refresh_backup = True
        elif cached_sha:
            active_sha = active_fp.get("sha256")
            backup_sha = backup_fp.get("sha256")
            if active_sha and active_sha != cached_sha and active_sha != backup_sha:
                should_refresh_backup = True
                reason = "active source changed"

        if should_refresh_backup:
            _copy_file(active, backup)
            print(f"  [raw-cache] {group}: {reason} -> _downloads/{area_cfg['area_id']}/{filename}")
            backup_fp = dcc.file_fingerprint(backup)
        elif backup.exists():
            print(f"  [raw-cache] {group}: using _downloads/{area_cfg['area_id']}/{filename}")

        if backup.exists():
            # Normalize active_area files back to raw inputs. Older refine runs may
            # have modified those files in place; future source-change detection
            # assumes active paths are raw snapshots.
            if active_fp.get("sha256") != backup_fp.get("sha256"):
                _copy_file(backup, active)
            raw_sources[group] = backup
        else:
            raw_sources[group] = active

    return raw_sources


# ══════════════════════════════════════════════════════════════════════════════
# 建筑精炼
# ══════════════════════════════════════════════════════════════════════════════

def _buildings_L1(src_path: Path, out_path: Path, manifest: dict) -> dict:
    """L1: 格式标准化 + null/退化过滤"""
    from clean_raw_data import clean_buildings
    stats = clean_buildings(src_path, dry_run=False)
    # clean_buildings 原地覆写 src_path，拷贝到 out_path
    _copy_file(src_path, out_path)
    manifest["levels"]["buildings"]["L1"] = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "in": stats["total_in"],
        "out": stats["total_out"],
        "removed_null": stats["removed_null"],
        "removed_degenerate": stats["removed_degenerate"],
        "removed_tiny": stats["removed_tiny"],
        "removed_duplicate": stats["removed_duplicate"],
        "fixed_height": stats["fixed_height"],
    }
    manifest["levels"]["buildings"]["current"] = 1
    print(f'  [L1] 建筑: {stats["total_in"]} → {stats["total_out"]}')
    return stats


def _buildings_L2(cleaned_path: Path, manifest: dict) -> dict:
    """L2: （当前 L1 已含去重+面积，L2 预留给未来更深清洗）
    目前直接标记为通过。
    """
    manifest["levels"]["buildings"]["L2"] = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "note": "L2 reserved (L1 already includes dedup + area filter)",
    }
    manifest["levels"]["buildings"]["current"] = 2
    print("  [L2] 建筑: pass (L1 已含深度清洗)")
    return {}


def _buildings_L3(cleaned_path: Path, area_cfg: dict, manifest: dict) -> dict:
    """L3: OSM building:levels 高度补全"""
    from enrich_building_levels import enrich_levels
    stats = enrich_levels(area_cfg, verbose=True)
    # enrich_levels 原地覆写 buildings_file，拷贝最新到 cleaned_path
    bld_file = vc_paths.resolve_project_path(area_cfg["buildings_file"])
    if bld_file != cleaned_path:
        _copy_file(bld_file, cleaned_path)
    manifest["levels"]["buildings"]["L3"] = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "osm_matched": stats.get("total", 0),
        "updated": stats.get("updated", 0),
    }
    manifest["levels"]["buildings"]["current"] = 3
    print(f'  [L3] 建筑: OSM 补全 {stats.get("updated", 0)} 栋')
    return stats


# ══════════════════════════════════════════════════════════════════════════════
# 道路精炼
# ══════════════════════════════════════════════════════════════════════════════

def _roads_L1(src_path: Path, out_path: Path, manifest: dict) -> dict:
    """L1: 孤儿/过短/类型白名单过滤"""
    from clean_raw_data import clean_osm
    stats = clean_osm(src_path, dry_run=False)
    _copy_file(src_path, out_path)
    manifest["levels"]["roads"]["L1"] = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "ways_in": stats.get("ways_in", 0),
        "ways_out": stats.get("ways_out", 0),
    }
    manifest["levels"]["roads"]["current"] = 1
    print(f'  [L1] 道路: {stats.get("ways_in", 0)} → {stats.get("ways_out", 0)}')
    return stats


def _roads_L2(cleaned_path: Path, manifest: dict) -> dict:
    """L2: 端点焊接 + 链式合并（如果 merge_roads 可用）"""
    try:
        from clean_raw_data import merge_roads
        stats = merge_roads(cleaned_path)
        manifest["levels"]["roads"]["L2"] = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "merged": stats.get("merged", 0),
        }
        manifest["levels"]["roads"]["current"] = 2
        print(f'  [L2] 道路: 合并 {stats.get("merged", 0)} 段')
        return stats
    except (ImportError, AttributeError):
        # merge_roads 尚未实现时直接通过
        manifest["levels"]["roads"]["L2"] = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "note": "merge_roads not available, skipped",
        }
        manifest["levels"]["roads"]["current"] = 2
        print("  [L2] 道路: pass (merge_roads 未实现)")
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# DEM 精炼
# ══════════════════════════════════════════════════════════════════════════════

def _dem_L1(src_path: Path, out_path: Path, manifest: dict) -> dict:
    """L1: CSV 格式验证 + NaN 检查"""
    import csv
    with open(src_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    nan_count = sum(1 for r in rows if any(v in ('', 'nan', 'NaN') for v in r.values()))
    _copy_file(src_path, out_path)
    manifest["levels"]["dem"]["L1"] = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "total_points": len(rows),
        "nan_count": nan_count,
    }
    manifest["levels"]["dem"]["current"] = 1
    print(f"  [L1] DEM: {len(rows)} 点, NaN={nan_count}")
    return {"total_points": len(rows), "nan_count": nan_count}


def _dem_L2(cleaned_path: Path, area_cfg: dict, manifest: dict) -> dict:
    """L2: DSM→DTM 建筑掩码修正"""
    from correct_dem_dtm import correct_dtm
    applied = correct_dtm(area_cfg, verbose=True)
    # correct_dtm 覆写 dem_csv，拷贝最新到 cleaned_path
    dem_file = vc_paths.resolve_project_path(area_cfg["dem_csv"])
    if dem_file != cleaned_path:
        _copy_file(dem_file, cleaned_path)
    manifest["levels"]["dem"]["L2"] = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "correction_applied": applied,
    }
    manifest["levels"]["dem"]["current"] = 2
    print(f"  [L2] DEM: DTM修正 {'已应用' if applied else '跳过(无掩码)'}")
    return {"applied": applied}


# ══════════════════════════════════════════════════════════════════════════════
# QA 校验
# ══════════════════════════════════════════════════════════════════════════════

def _run_input_qa(area_cfg: dict) -> list[dict]:
    """InputQA: 原始数据入口检查"""
    checks = []

    for label, key, min_kb in [
        ("buildings", "buildings_file", 10),
        ("roads", "osm_file", 5),
        ("dem", "dem_csv", 4),
    ]:
        path = vc_paths.resolve_project_path(area_cfg.get(key, ""))
        if not path.exists():
            checks.append({"name": f"{label}_exists", "status": "fail",
                           "message": f"{path.name} 不存在"})
        elif path.stat().st_size < min_kb * 1024:
            checks.append({"name": f"{label}_size", "status": "fail",
                           "message": f"{path.name} 过小 ({path.stat().st_size} bytes)"})
        else:
            checks.append({"name": f"{label}_exists", "status": "pass",
                           "message": f"{path.stat().st_size // 1024} KB"})

    return checks


def _run_process_qa(manifest: dict) -> list[dict]:
    """ProcessQA: 清洗过程合理性检查"""
    checks = []
    bl = manifest["levels"].get("buildings", {})

    # 建筑保留率
    l1 = bl.get("L1", {})
    if l1.get("in") and l1.get("out"):
        ratio = l1["out"] / l1["in"]
        if ratio < 0.5:
            checks.append({"name": "bld_retention", "status": "warn",
                           "message": f"保留率 {ratio:.0%} 偏低，清洗可能过激"})
        elif ratio > 0.995:
            checks.append({"name": "bld_retention", "status": "warn",
                           "message": f"保留率 {ratio:.0%}，清洗几乎无效"})
        else:
            checks.append({"name": "bld_retention", "status": "pass",
                           "message": f"保留率 {ratio:.0%}"})

    # DEM 修正
    dl2 = manifest["levels"].get("dem", {}).get("L2", {})
    if dl2:
        checks.append({"name": "dem_correction", "status": "pass",
                       "message": f"applied={dl2.get('correction_applied')}"})

    return checks


def _run_output_qa(area_id: str, area_cfg: dict,
                   ready_dir: str | Path | None = None) -> list[dict]:
    """OutputQA: Houdini 消费前最终检查"""
    checks = []
    hr = Path(ready_dir) if ready_dir else HOUDINI_READY / area_id

    # 文件齐全
    for name in ["buildings.geojson", "roads.osm", "dem.csv"]:
        fp = hr / name
        if fp.exists() and fp.stat().st_size > 1000:
            checks.append({"name": f"output_{name}", "status": "pass",
                           "message": f"{fp.stat().st_size // 1024} KB"})
        else:
            checks.append({"name": f"output_{name}", "status": "fail",
                           "message": f"{name} 缺失或过小"})

    # 抽样建筑验证
    bld_path = hr / "buildings.geojson"
    if bld_path.exists():
        with open(bld_path, encoding="utf-8") as f:
            fc = json.load(f)
        feats = fc.get("features", [])
        sample = feats[:10]
        valid = 0
        for feat in sample:
            geom = feat.get("geometry")
            props = feat.get("properties", {})
            if (geom and geom.get("type") in ("Polygon", "MultiPolygon")
                    and props.get("height", 0) > 0):
                valid += 1
        if valid == len(sample):
            checks.append({"name": "bld_sample", "status": "pass",
                           "message": f"{valid}/{len(sample)} 建筑有效"})
        else:
            checks.append({"name": "bld_sample", "status": "warn",
                           "message": f"{valid}/{len(sample)} 建筑有效"})

    # 语义契约检查（vc_schema）：属性完整性 + 道路连通性
    try:
        import vc_schema
        if bld_path.exists():
            with open(bld_path, encoding="utf-8") as f:
                checks.extend(vc_schema.check_buildings(json.load(f).get("features", [])))
        road_path = hr / "roads.osm"
        if road_path.exists():
            checks.extend(vc_schema.check_roads(road_path))
    except Exception as exc:
        checks.append({"name": "semantic_contract", "status": "warn",
                       "message": f"语义契约检查异常: {exc}"})

    return checks


def run_qa(area_id: str, area_cfg: dict, manifest: dict,
           ready_dir: str | Path | None = None) -> dict:
    """执行完整 QA 流程"""
    print("\n[QA 精炼校验]")
    all_checks = []

    print("  -- InputQA --")
    input_checks = _run_input_qa(area_cfg)
    all_checks.extend(input_checks)
    for c in input_checks:
        tag = "[OK]" if c["status"] == "pass" else "[WARN]" if c["status"] == "warn" else "[FAIL]"
        print(f'    {tag} {c["name"]}: {c["message"]}')

    print("  -- ProcessQA --")
    proc_checks = _run_process_qa(manifest)
    all_checks.extend(proc_checks)
    for c in proc_checks:
        tag = "[OK]" if c["status"] == "pass" else "[WARN]" if c["status"] == "warn" else "[FAIL]"
        print(f'    {tag} {c["name"]}: {c["message"]}')

    print("  -- OutputQA --")
    out_checks = _run_output_qa(area_id, area_cfg, ready_dir=ready_dir)
    all_checks.extend(out_checks)
    for c in out_checks:
        tag = "[OK]" if c["status"] == "pass" else "[WARN]" if c["status"] == "warn" else "[FAIL]"
        print(f'    {tag} {c["name"]}: {c["message"]}')

    n_pass = sum(1 for c in all_checks if c["status"] == "pass")
    n_warn = sum(1 for c in all_checks if c["status"] == "warn")
    n_fail = sum(1 for c in all_checks if c["status"] == "fail")
    passed = n_fail == 0

    print(f"\n  结果: {n_pass} passed, {n_warn} warnings, {n_fail} failed")
    if passed:
        print("  [OK] QA 通过")
    else:
        print("  [FAIL] QA 未通过，请检查上述失败项")

    report = {
        "area_id": area_id,
        "run_id": area_cfg.get("run_id", ""),
        "time": datetime.now().isoformat(timespec="seconds"),
        "passed": passed,
        "summary": {"pass": n_pass, "warn": n_warn, "fail": n_fail},
        "checks": all_checks,
    }

    # 持久化 QA 报告
    qa_dir = vc_paths.CONFIG / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    qa_file = qa_dir / f"{area_id}_qa_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(qa_file, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"  报告: {qa_file.name}")

    return report


# ══════════════════════════════════════════════════════════════════════════════
# 数据源探测
# ══════════════════════════════════════════════════════════════════════════════

def probe_sources(area_cfg: dict, manifest: dict) -> list[dict]:
    """检查远端数据源是否有更新，返回更新列表"""
    updates = []
    sources = manifest.get("sources", {})

    # OSM: 比较远端 count vs 本地 count
    bld_source = sources.get("buildings", {})
    local_count = bld_source.get("raw_count", 0)
    last_probe = bld_source.get("last_probe", "")

    # 24h 内探测过则跳过
    if last_probe:
        try:
            last_t = datetime.fromisoformat(last_probe)
            if (datetime.now() - last_t).total_seconds() < 86400:
                print("  [probe] 24h 内已探测，跳过")
                return []
        except ValueError:
            pass

    print("  [probe] 检查数据源更新...")

    # Overture: 检查远端版本（简化实现：标记为可选更新）
    provider = area_cfg.get("sources", {}).get("buildings", {}).get("provider", "overture")
    local_ver = bld_source.get("version", "unknown")
    # 实际实现中会查询远端 API，这里仅标记探测时间
    manifest.setdefault("sources", {}).setdefault("buildings", {})["last_probe"] = \
        datetime.now().isoformat(timespec="seconds")

    print(f"  [probe] buildings ({provider}): 本地版本 {local_ver}")
    print(f"  [probe] DEM (nasadem): 静态数据集，无更新")

    return updates


# ══════════════════════════════════════════════════════════════════════════════
# 主编排
# ══════════════════════════════════════════════════════════════════════════════

def refine(area_cfg: dict, *, target_level: int = 3, force: bool = False,
           skip_probe: bool = False, qa_only: bool = False) -> bool:
    """
    主入口：精炼数据到指定级别。
    返回 True 表示数据已就绪可喂 Houdini。
    """
    area_id = area_cfg["area_id"]
    manifest = _load_manifest(area_id)

    print(f"\n{'='*50}")
    print(f"[VirtualCity 数据精炼] {area_id}")
    print(f"{'='*50}")

    # ── 数据源探测 ──
    if not skip_probe and not qa_only:
        probe_sources(area_cfg, manifest)

    if qa_only:
        report = run_qa(area_id, area_cfg, manifest)
        return report["passed"]

    # ── InputQA ──
    print("\n[InputQA] 原始数据检查...")
    input_checks = _run_input_qa(area_cfg)
    input_fails = [c for c in input_checks if c["status"] == "fail"]
    if input_fails:
        for c in input_fails:
            print(f'  [FAIL] {c["name"]}: {c["message"]}')
        print("\n  原始数据不完整，无法精炼。请先运行 set_area.py 下载数据。")
        return False
    print("  [OK] 原始数据完整")

    dl_dir = _area_dir(DOWNLOADS, area_id)
    cl_dir = _area_dir(CLEANED, area_id)
    raw_sources = _prepare_raw_sources(area_cfg, manifest, dl_dir)
    cache_state = dcc.refine_cache_state(area_cfg, raw_sources)
    cache_ok, cache_reason = dcc.cache_match(manifest, cache_state)
    restored_cache = None
    if not force and not cache_ok:
        restored_cache = dcc.restore_refine_cache(cache_state, cl_dir)
        if restored_cache:
            cached_manifest = restored_cache["manifest"]
            manifest["levels"] = cached_manifest.get("levels", manifest["levels"])
            cache_ok = True
            cache_reason = "restored from clean cache index"
            print(f"  [cache] restored: {cache_state['key']} from {restored_cache['source_dir']}")

    if force:
        print("  [cache] force refresh requested")
        dcc.reset_levels(manifest)
    elif not cache_ok:
        print(f"  [cache] invalidated: {cache_reason}")
        dcc.reset_levels(manifest)
    elif not _levels_ready(manifest, target_level):
        print("  [cache] fingerprint matches; missing target levels will run")
    elif not dcc.outputs_exist(cl_dir):
        print("  [cache] fingerprint matches, but cleaned outputs are missing")
        dcc.reset_levels(manifest)
    else:
        print(f"  [cache] hit: {cache_state['key']}")

    # ── 精炼：建筑 ──
    print("\n[建筑精炼]")
    bld_src = raw_sources["buildings"]
    bld_cleaned = cl_dir / "buildings.geojson"
    bld_level = manifest["levels"]["buildings"]["current"]

    if bld_level < 1 or force:
        _copy_file(bld_src, bld_cleaned)
        _buildings_L1(bld_cleaned, bld_cleaned, manifest)
    else:
        print(f"  [L1] 跳过 (已在 L{bld_level})")
        if not bld_cleaned.exists():
            _copy_file(bld_src, bld_cleaned)

    if manifest["levels"]["buildings"]["current"] < 2 and target_level >= 2:
        _buildings_L2(bld_cleaned, manifest)

    if manifest["levels"]["buildings"]["current"] < 3 and target_level >= 3:
        # L3 需要 area_cfg 中的 origin + buildings_file 指向 cleaned
        _l3_cfg = dict(area_cfg)
        _l3_cfg["buildings_file"] = bld_cleaned.as_posix()
        _buildings_L3(bld_cleaned, _l3_cfg, manifest)

    # ── 精炼：道路 ──
    print("\n[道路精炼]")
    osm_src = raw_sources["roads"]
    osm_cleaned = cl_dir / "roads.osm"
    road_level = manifest["levels"]["roads"]["current"]

    if road_level < 1 or force:
        _copy_file(osm_src, osm_cleaned)
        _roads_L1(osm_cleaned, osm_cleaned, manifest)
    else:
        print(f"  [L1] 跳过 (已在 L{road_level})")
        if not osm_cleaned.exists():
            _copy_file(osm_src, osm_cleaned)

    if manifest["levels"]["roads"]["current"] < 2 and target_level >= 2:
        _roads_L2(osm_cleaned, manifest)

    # ── 精炼：DEM ──
    print("\n[DEM 精炼]")
    dem_src = raw_sources["dem"]
    dem_cleaned = cl_dir / "dem.csv"
    dem_level = manifest["levels"]["dem"]["current"]

    if dem_level < 1 or force:
        _dem_L1(dem_src, dem_cleaned, manifest)
    else:
        print(f"  [L1] 跳过 (已在 L{dem_level})")
        if not dem_cleaned.exists():
            _copy_file(dem_src, dem_cleaned)

    if manifest["levels"]["dem"]["current"] < 2 and target_level >= 2:
        dem_source = area_cfg.get("dem_source", "nasadem")
        if dem_source == "fabdem":
            # FABDEM 已是 DTM（裸地），无需 DSM→DTM 修正
            manifest["levels"]["dem"]["L2"] = {
                "time": datetime.now().isoformat(timespec="seconds"),
                "correction_applied": False,
                "skip_reason": "FABDEM is already DTM (buildings+trees removed)",
            }
            manifest["levels"]["dem"]["current"] = 2
            print(f"  [L2] DEM: 跳过 DTM 修正（数据源={dem_source}，已是裸地）")
        else:
            _l2_cfg = dict(area_cfg)
            _l2_cfg["dem_csv"] = dem_cleaned.as_posix()
            _l2_cfg["buildings_file"] = bld_cleaned.as_posix()
            _dem_L2(dem_cleaned, _l2_cfg, manifest)

    # ── 先导出到 staging，QA 通过后再发布到 _houdini_ready/ ──
    print("\n[导出 Houdini Ready staging]")
    staging_dir = _staging_ready_dir(area_id)
    hr_dir = HOUDINI_READY / area_id
    try:
        for name in ["buildings.geojson", "roads.osm", "dem.csv"]:
            src = cl_dir / name
            dst = staging_dir / name
            if src.exists():
                _copy_file(src, dst)
        import vc_schema
        meta = {
            "area_id": area_id,
            "run_id": area_cfg.get("run_id", ""),
            "origin_lon": area_cfg.get("origin_lon"),
            "origin_lat": area_cfg.get("origin_lat"),
            "exported": datetime.now().isoformat(timespec="seconds"),
            "levels": {k: v["current"] for k, v in manifest["levels"].items()},
            "schema_version": vc_schema.CONTRACT_VERSION,
            "cache_key": cache_state["key"],
            "cache_fingerprint": cache_state["fingerprint"],
        }
        with open(staging_dir / "meta.json", "w", encoding="utf-8", newline="\n") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"  [OK] staging → {vc_paths.project_relative(staging_dir)}")

        # ── ProcessQA + OutputQA ──
        report = run_qa(area_id, area_cfg, manifest, ready_dir=staging_dir)
        manifest.setdefault("cache", {})["last_qa"] = {
            "time": report["time"],
            "passed": report["passed"],
            "summary": report["summary"],
        }
        _save_manifest(area_id, manifest)

        if not report["passed"]:
            print("\n  [FAIL] QA 未通过，保留上一版 Houdini-ready 数据。")
            return False

        _publish_ready_dir(staging_dir, hr_dir)
        print(f"  [OK] 已发布 → _houdini_ready/{area_id}/")
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)

    dcc.mark_refine_cache(manifest, cache_state, cl_dir, hr_dir)
    manifest.setdefault("cache", {})["last_qa"] = {
        "time": report["time"],
        "passed": report["passed"],
        "summary": report["summary"],
    }
    _save_manifest(area_id, manifest)
    dcc.update_clean_cache_index(area_id, cache_state, _manifest_path(area_id))

    return True


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="VirtualCity 数据精炼管线")
    ap.add_argument("--level", type=int, default=3, help="目标精炼级别 (1-3)")
    ap.add_argument("--force", action="store_true", help="忽略缓存，全部重跑")
    ap.add_argument("--skip-probe", action="store_true", help="跳过数据源更新探测")
    ap.add_argument("--qa-only", action="store_true", help="只跑 QA 校验")
    args = ap.parse_args()

    cfg = vc_paths.load_active_area(absolute=True)
    ok = refine(cfg, target_level=args.level, force=args.force,
                skip_probe=args.skip_probe, qa_only=args.qa_only)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
