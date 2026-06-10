"""Human-readable build history derived from pipeline run records.

`pipeline_state` already writes a machine status file per run
(`Reports/pipeline_runs/{run_id}.json`) consumed by the UI and export gate.
This module is its read-only companion: it turns that event timeline into a
per-run Markdown archive under `Reports/build_history/` that highlights
per-stage durations, so a human can see where each run spent its time and why
it failed without subtracting timestamps by hand.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from shared import vc_paths

HISTORY_DIR = vc_paths.ROOT / "Reports" / "build_history"

# 三大模块的边界 phase：管线顺序执行，用这些 phase 的进入时刻切分墙钟耗时。
_MODULE_BOUNDARIES = [
    ("数据获取", "created", "refine_data"),
    ("数据清洗", "refine_data", "houdini_recook"),
    ("Houdini 构建", "houdini_recook", None),
]

_STATUS_TAG = {"completed": "[OK]", "failed": "[FAIL]", "running": "[..]"}


def _parse(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}m{secs:02d}s"


def _event_durations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate each event with elapsed seconds since the previous event."""
    rows: list[dict[str, Any]] = []
    prev: datetime | None = None
    for ev in events:
        when = _parse(str(ev.get("time") or ""))
        delta = (when - prev).total_seconds() if (when and prev) else None
        rows.append({
            "time": str(ev.get("time") or ""),
            "phase": str(ev.get("phase") or ""),
            "status": str(ev.get("status") or ""),
            "message": str(ev.get("message") or ""),
            "delta": delta,
        })
        if when:
            prev = when
    return rows


def _phase_first_time(events: list[dict[str, Any]], phase: str) -> datetime | None:
    for ev in events:
        if str(ev.get("phase") or "") == phase:
            return _parse(str(ev.get("time") or ""))
    return None


def _module_breakdown(events: list[dict[str, Any]],
                      finished: datetime | None) -> list[dict[str, Any]]:
    """Split wall-clock time across the three pipeline modules by phase entry."""
    rows: list[dict[str, Any]] = []
    for label, start_phase, end_phase in _MODULE_BOUNDARIES:
        start = _phase_first_time(events, start_phase)
        end = _phase_first_time(events, end_phase) if end_phase else finished
        seconds = (end - start).total_seconds() if (start and end) else None
        rows.append({"label": label, "seconds": seconds})
    return rows


def render_markdown(run: dict[str, Any]) -> str:
    """Render a single run record into a human-readable Markdown archive."""
    run_id = str(run.get("run_id") or "unknown")
    area_id = str(run.get("area_id") or "")
    status = str(run.get("status") or "")
    phase = str(run.get("phase") or "")
    created = _parse(str(run.get("created") or ""))
    updated = _parse(str(run.get("updated") or ""))
    total = (updated - created).total_seconds() if (created and updated) else None
    events = run.get("events") if isinstance(run.get("events"), list) else []
    tag = _STATUS_TAG.get(status, status)

    lines: list[str] = []
    lines.append(f"# 构建历史 {tag} {run_id}")
    lines.append("")
    lines.append(f"- 区域: `{area_id}`")
    lines.append(f"- 最终状态: **{status}** (phase: `{phase}`)")
    lines.append(f"- 开始: {run.get('created', '')}")
    lines.append(f"- 结束: {run.get('updated', '')}")
    lines.append(f"- 总耗时: **{_fmt_duration(total)}**")
    lines.append(f"- 来源: {run.get('source', '')}")
    bbox = run.get("bbox")
    if isinstance(bbox, list):
        lines.append(f"- bbox: {bbox}")
    qa_status = str(run.get("qa_status") or "")
    if qa_status:
        lines.append(f"- Model QA: {qa_status}")
    hip = run.get("hip_path")
    if hip:
        lines.append(f"- HIP 产物: `{hip}`")
    lines.append("")

    lines.append("## 模块耗时分解")
    lines.append("")
    lines.append("| 模块 | 耗时 | 占比 |")
    lines.append("| --- | --- | --- |")
    for row in _module_breakdown(events, updated):
        secs = row["seconds"]
        pct = f"{secs / total * 100:.0f}%" if (secs is not None and total) else "—"
        lines.append(f"| {row['label']} | {_fmt_duration(secs)} | {pct} |")
    lines.append("")

    if status == "failed":
        last = events[-1] if events else {}
        lines.append("## 失败原因")
        lines.append("")
        lines.append(f"- 阶段: `{phase}`")
        lines.append(f"- 信息: {last.get('message', '') if isinstance(last, dict) else ''}")
        lines.append("")

    lines.append("## 事件耗时明细")
    lines.append("")
    lines.append("| 时间 | 距上一步 | 阶段 | 状态 | 信息 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for ev in _event_durations(events):
        msg = ev["message"].replace("|", "\\|")
        lines.append(
            f"| {ev['time']} | {_fmt_duration(ev['delta'])} "
            f"| `{ev['phase']}` | {ev['status']} | {msg} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_history(run: dict[str, Any], *, history_dir: Path | None = None) -> Path:
    """Write a per-run Markdown archive and return its path.

    Never raises into the caller: build history is an observability nicety, not
    part of the build contract, so any failure is swallowed and reported via the
    returned path being unwritten.
    """
    base = history_dir or HISTORY_DIR
    run_id = str(run.get("run_id") or "unknown")
    base.mkdir(parents=True, exist_ok=True)
    target = base / f"{run_id}.md"
    target.write_text(render_markdown(run), encoding="utf-8", newline="\n")
    return target


def write_history_for_run(run_id: str) -> Path | None:
    """Load a run record by id and archive it; swallow errors."""
    try:
        import pipeline_state
    except ImportError:
        from orchestration import pipeline_state  # type: ignore
    try:
        run = pipeline_state.load_run(run_id)
    except Exception:
        return None
    try:
        return write_history(run)
    except Exception:
        return None