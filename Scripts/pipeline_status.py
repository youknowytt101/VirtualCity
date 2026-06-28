"""Current-run status aggregation for the WorldBuilder pipeline.

This module is intentionally read-only.  It gives UI and export scripts one
place to answer: "does this artifact belong to the active area/run?"
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import manual_review
import vc_paths


MANUAL_REVIEW_QA = {"warn", "manual_review_required", "fail"}

# phase 是真相源里的事实，把它翻译成人能看懂的中文标签属于读层职责，
# 这里是唯一来源；server 的失败摘要也复用它，避免两处各维护一份。
PHASE_LABELS = {
    "created": "创建运行记录",
    "download_area_prepared": "准备下载区域",
    "active_area_written": "写入 active_area",
    "acquire_osm": "获取道路数据",
    "acquire_dem": "获取地形数据",
    "acquire_buildings": "获取建筑数据",
    "raw_data_acquired": "原始数据获取完成",
    "data_download_completed": "数据下载完成",
    "refine_data": "数据清洗",
    "refine_data_completed": "数据清洗完成",
    "houdini_preflight": "Houdini 输入预检",
    "houdini_recook": "Houdini 重算",
    "houdini_completed": "Houdini 完成",
    "pipeline_completed": "管线完成",
    "aborted": "流程中止",
}

# 数据获取/清洗阶段没有结构化的 step/total，按 phase 给固定锚点推进进度条；
# Houdini 段则用真相源里的 progress.step/total 在 75~99 区间细分。
_PHASE_PCT = {
    "created": 2,
    "download_area_prepared": 5,
    "active_area_written": 6,
    "acquire_osm": 20,
    "acquire_dem": 38,
    "acquire_buildings": 55,
    "raw_data_acquired": 62,
    "data_download_completed": 100,
    "refine_data": 66,
    "refine_data_completed": 74,
    "houdini_completed": 100,
    "pipeline_completed": 100,
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _resolve(root: Path, value: str | Path | None) -> Path:
    if not value:
        return root
    raw = str(value).replace("\\", "/")
    path = Path(raw)
    if path.is_absolute():
        return path
    lowered = raw.lower()
    for marker in ("/worldbuilder/", "/virtualcity/"):
        idx = lowered.find(marker)
        if idx >= 0:
            return root / raw[idx + len(marker):]
    return root / raw


def _project_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _same_identity(payload: dict[str, Any], area_id: str, run_id: str) -> bool:
    if not payload:
        return False
    if payload.get("area_id") != area_id:
        return False
    payload_run = str(payload.get("run_id") or "")
    return not run_id or payload_run == run_id


def load_active(root: Path | None = None) -> dict[str, Any]:
    base = root or vc_paths.ROOT
    return _read_json(base / "Config" / "active_area.json")


def load_run(root: Path, run_id: str) -> dict[str, Any]:
    if not run_id:
        return {}
    return _read_json(root / "Reports" / "pipeline_runs" / f"{run_id}.json")


def load_houdini_status(root: Path, area_id: str, run_id: str) -> dict[str, Any]:
    path = root / "Config" / "houdini_build_status.json"
    payload = _read_json(path)
    if not payload:
        return {"available": False, "path": _project_path(root, path), "message": "status file missing"}
    same = _same_identity(payload, area_id, run_id)
    out = dict(payload)
    out.update({
        "available": same,
        "same_identity": same,
        "path": _project_path(root, path),
    })
    if not same:
        out["message"] = (
            f"stale houdini status: {payload.get('area_id', '')}/{payload.get('run_id', '')} "
            f"!= {area_id}/{run_id}"
        )
    return out


def load_model_qa(root: Path, area_id: str, run_id: str,
                  houdini_status: dict[str, Any] | None = None) -> dict[str, Any]:
    candidates: list[Path] = []
    report_value = (houdini_status or {}).get("qa_report")
    if report_value:
        candidates.append(_resolve(root, report_value))
    candidates.extend([
        root / "Reports" / "model_qa" / f"{area_id}_latest.json",
        root / "Reports" / "model_qa" / "latest.json",
    ])
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        payload = _read_json(path)
        if not payload:
            continue
        if _same_identity(payload, area_id, run_id):
            out = dict(payload)
            out.update({
                "available": True,
                "same_identity": True,
                "path": _project_path(root, path),
            })
            return out
    return {"available": False, "same_identity": False, "message": "current model QA report missing"}


def progress_view(run: dict[str, Any]) -> dict[str, Any]:
    """把 run 文件里的 phase/progress/status 投影成 UI 进度，纯函数无副作用。

    进度是真相源里的结构化事实，不再靠解析 stdout 日志推断：
    - status 终态优先决定 pct（completed=100，failed 保留最后进度）。
    - Houdini 段用 progress.step/total 在 75~99 区间细分。
    - 其余阶段按 phase 锚点取固定 pct。
    label 直接采用真相源写入的 progress.label；缺失时回退到 phase 中文标签。
    """
    phase = str(run.get("phase") or "")
    status = str(run.get("status") or "")
    progress = run.get("progress") if isinstance(run.get("progress"), dict) else {}
    step = int(progress.get("step") or 0)
    total = int(progress.get("total") or 0)
    label = str(progress.get("label") or "")
    phase_label = PHASE_LABELS.get(phase, phase or "管线执行")

    if status == "completed":
        pct = 100
    elif phase in ("houdini_recook", "houdini_preflight"):
        # 进入 Houdini 段即锚定 75 起点；拿到 step/total 后在 75~99 区间细分，
        # 避免 recook 刚启动、progress 尚未写入（total=0）时 pct 掉回 0。
        pct = 75 if total <= 0 else min(99, 75 + int(step / total * 23))
    else:
        pct = _PHASE_PCT.get(phase, 0)

    return {
        "phase": phase,
        "phase_label": phase_label,
        "status": status,
        "step": step,
        "total": total,
        "label": label or phase_label,
        "pct": pct,
    }


def current_status(root: Path | None = None,
                   active_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    base = root or vc_paths.ROOT
    active = active_cfg or load_active(base)
    area_id = str(active.get("area_id") or "")
    run_id = str(active.get("run_id") or "")
    run = load_run(base, run_id)
    houdini = load_houdini_status(base, area_id, run_id)
    model_qa = load_model_qa(base, area_id, run_id, houdini)
    review = manual_review.load_review(area_id, run_id, root=base)
    return {
        "area_id": area_id,
        "run_id": run_id,
        "active_area": active,
        "run": run,
        "houdini": houdini,
        "model_qa": model_qa,
        "manual_review": review,
    }


def export_gate(root: Path | None = None,
                active_cfg: dict[str, Any] | None = None,
                live_model_ready: bool | None = None) -> dict[str, Any]:
    base = root or vc_paths.ROOT
    status = current_status(base, active_cfg)
    area_id = status["area_id"]
    run_id = status["run_id"]
    reasons: list[str] = []
    warnings: list[str] = []
    requires_review = False

    if not area_id or not run_id:
        reasons.append("active area/run_id is missing")

    houdini = status["houdini"]
    if not houdini.get("available"):
        reasons.append(str(houdini.get("message") or "current Houdini build status is missing"))
    elif str(houdini.get("status") or "").lower() != "completed":
        reasons.append(f"Houdini status is {houdini.get('status') or 'unknown'}")

    qa = status["model_qa"]
    # 优先采信 run 文件里的 qa（单一真相源），回退到独立 model_qa 报告与
    # houdini_build_status 的 qa_status，保证旧产物在过渡期仍可被判读。
    run_qa = status["run"].get("qa") if isinstance(status["run"].get("qa"), dict) else {}
    qa_status = str(run_qa.get("status") or qa.get("status") or houdini.get("qa_status") or "").lower()
    qa_available = bool(qa.get("available")) or bool(run_qa.get("status"))
    if not qa_available:
        reasons.append(str(qa.get("message") or "current Model QA report is missing"))
    elif qa_status in MANUAL_REVIEW_QA:
        # QA 是非阻断体检：fail/warn 都不直接拦死导出，而是要求人工复核确认。
        # 几何已成功产出，质量评分由人决定是否放行，而不是机器一刀切。
        requires_review = True
        warnings.append(f"Model QA status is {qa_status}")

    if live_model_ready is False:
        reasons.append("Houdini OUT_city is not live/exportable")

    review_ok = manual_review.review_approves_export(area_id, run_id, root=base)
    if requires_review and not review_ok:
        reasons.append("manual review approval is required for this area/run")

    return {
        "allowed": not reasons,
        "requires_manual_review": requires_review,
        "manual_review_approved": review_ok,
        "reasons": reasons,
        "warnings": warnings,
        "primary_reason": reasons[0] if reasons else "",
        "status": status,
    }
