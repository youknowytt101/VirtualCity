"""VirtualCity full pipeline orchestrator.

This is the explicit boundary between the three major modules:

1. acquisition: acquisition/set_area.py --acquire-only
2. cleaning: cleaning/refine_data.py
3. Houdini build: houdini_build/recook_new_area.py

The legacy `set_area.py <bbox>` path is kept for compatibility, but the web UI
and new automation should use this orchestrator for full builds.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from orchestration import pipeline_state
from orchestration import state_machine as sm
from shared import vc_paths


def _run(cmd: list[str], *, phase: str, run_id: str | None = None) -> int:
    if run_id:
        pipeline_state.update_run(run_id, phase=phase, message=f"{phase} started")
    print(f"\n[{phase}] {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=str(SCRIPTS), capture_output=False)
    return result.returncode


def _load_current_run() -> tuple[dict, str]:
    cfg = vc_paths.load_active_area(absolute=True)
    run_id = str(cfg.get("run_id") or "")
    if not run_id:
        raise RuntimeError("active_area.json missing run_id after acquisition")
    return cfg, run_id


def _parse_args(argv: list[str]) -> tuple[list[str], bool, bool, str]:
    area_args: list[str] = []
    force_refine = False
    skip_probe = True
    tile_ids = ""
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--force-refine":
            force_refine = True
        elif arg == "--no-skip-probe":
            skip_probe = False
        elif arg == "--tile-ids":
            if i + 1 >= len(argv):
                raise ValueError("--tile-ids requires a comma-separated value")
            tile_ids = argv[i + 1]
            i += 1
        else:
            area_args.append(arg)
        i += 1
    return area_args, force_refine, skip_probe, tile_ids


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        area_args, force_refine, skip_probe, tile_ids = _parse_args(argv)
    except ValueError as exc:
        print(f"[FAIL] {exc}")
        return 1

    if not area_args:
        print(__doc__)
        print("Usage: uv run python orchestration/run_pipeline.py <west> <south> <east> <north> [area_name]")
        print("       uv run python orchestration/run_pipeline.py --center <lon> <lat> <radius_km> [area_name]")
        print("       uv run python orchestration/run_pipeline.py --url <google_maps_url> [area_name]")
        print("       optional: --tile-ids <tile_id[,tile_id...]>, --force-refine, --no-skip-probe")
        return 1

    python = sys.executable
    acquire_cmd = [
        python,
        "-u",
        str(SCRIPTS / "acquisition" / "set_area.py"),
        "--acquire-only",
        *area_args,
    ]

    print("\n" + "=" * 50)
    print("[VirtualCity] Full pipeline orchestrator")
    print("=" * 50)

    # Step 1 creates the run_id and switches active_area.
    acquire_result = subprocess.run(
        acquire_cmd,
        cwd=str(SCRIPTS),
        capture_output=False,
        env={
            **dict(os.environ),
            "VC_PIPELINE_SOURCE": "run_pipeline",
            "VC_PIPELINE_TILE_IDS": tile_ids,
        },
    )
    if acquire_result.returncode != 0:
        return acquire_result.returncode

    try:
        cfg, run_id = _load_current_run()
    except Exception as exc:
        print(f"[FAIL] acquisition completed but active run could not be loaded: {exc}")
        return 1

    area_id = cfg.get("area_id", "")
    print(f"\n[RUN] area_id={area_id} run_id={run_id}")

    # 显式状态机只做时序守卫：每次推进做一次纯函数转移，非法时序（如 acquire
    # 未完成就 cook、或终态后再推进）会在 transition 处抛错。phase 的落盘仍由
    # 下面既有的 update_run/_run/complete_run 负责，落盘契约不变。
    state = sm.QUEUED
    state = sm.transition(state, sm.START)      # -> ACQUIRING
    state = sm.transition(state, sm.ACQUIRED)   # -> REFINING（acquisition 已在上面跑完）

    refine_cmd = [python, str(SCRIPTS / "cleaning" / "refine_data.py")]
    if skip_probe:
        refine_cmd.append("--skip-probe")
    if force_refine:
        refine_cmd.append("--force")

    if _run(refine_cmd, phase="refine_data", run_id=run_id) != 0:
        sm.transition(state, sm.FAIL)
        pipeline_state.fail_run(run_id, phase="refine_data",
                                message="data refinement failed")
        print("[FAIL] 数据精炼未通过，中止流程")
        return 1
    state = sm.transition(state, sm.REFINED)    # -> COOKING
    pipeline_state.update_run(run_id, phase="refine_data_completed",
                              message="data refinement completed")

    recook_cmd = [python, "-u", str(SCRIPTS / "houdini_build" / "recook_new_area.py")]
    if _run(recook_cmd, phase="houdini_recook", run_id=run_id) != 0:
        sm.transition(state, sm.FAIL)
        pipeline_state.fail_run(run_id, phase="houdini_recook",
                                message="Houdini recook failed")
        print("[FAIL] Houdini 重算失败，中止流程")
        return 1
    state = sm.transition(state, sm.COOKED)     # -> QA
    state = sm.transition(state, sm.QA_PASSED)  # -> DONE

    pipeline_state.complete_run(
        run_id,
        phase="pipeline_completed",
        message="data acquisition, refinement, and Houdini recook completed",
    )
    print("\n" + "=" * 50)
    print(f"[OK] 完整管线完成: {area_id}")
    print("=" * 50)
    print("下一步：在 Houdini 视口审核 OUT_city，通过后再导出 FBX。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
