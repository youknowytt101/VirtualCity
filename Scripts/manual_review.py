"""Manual review approvals for VirtualCity pipeline gates."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import vc_paths


REVIEW_SCHEMA_VERSION = 1
APPROVED_DECISIONS = {"approved", "accept", "accepted"}
SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_part(value: str) -> str:
    return SAFE_ID.sub("_", str(value)).strip("_.-") or "unknown"


def review_dir(root: Path | None = None) -> Path:
    base = root or vc_paths.ROOT
    return base / "Reports" / "manual_review"


def review_path(area_id: str, run_id: str, *, root: Path | None = None) -> Path:
    return review_dir(root) / f"{safe_part(area_id)}__{safe_part(run_id)}.json"


def load_review(area_id: str, run_id: str, *, root: Path | None = None) -> dict[str, Any]:
    path = review_path(area_id, run_id, root=root)
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def review_approves_export(area_id: str, run_id: str, *, root: Path | None = None) -> bool:
    data = load_review(area_id, run_id, root=root)
    if data.get("area_id") != area_id or data.get("run_id") != run_id:
        return False
    decision = str(data.get("decision") or data.get("status") or "").lower()
    return decision in APPROVED_DECISIONS


def write_review(area_id: str, run_id: str, *, decision: str = "approved",
                 reviewer: str = "manual", notes: str = "",
                 root: Path | None = None) -> Path:
    path = review_path(area_id, run_id, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": REVIEW_SCHEMA_VERSION,
        "area_id": area_id,
        "run_id": run_id,
        "decision": decision,
        "reviewer": reviewer,
        "notes": notes,
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    tmp = path.with_name(f".{path.name}.{datetime.now().timestamp():.6f}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Record a manual review decision for the active VirtualCity run.")
    parser.add_argument("decision", choices=sorted(APPROVED_DECISIONS | {"rejected"}), help="Review decision.")
    parser.add_argument("--area-id", default="", help="Area id. Defaults to Config/active_area.json.")
    parser.add_argument("--run-id", default="", help="Run id. Defaults to Config/active_area.json.")
    parser.add_argument("--reviewer", default="manual", help="Reviewer name or initials.")
    parser.add_argument("--notes", default="", help="Short review note.")
    args = parser.parse_args()

    cfg = vc_paths.load_active_area(absolute=False)
    area_id = args.area_id or str(cfg.get("area_id") or "")
    run_id = args.run_id or str(cfg.get("run_id") or "")
    if not area_id or not run_id:
        print("[FAIL] area_id/run_id is required")
        return 1
    path = write_review(area_id, run_id, decision=args.decision,
                        reviewer=args.reviewer, notes=args.notes)
    print(f"[OK] manual review recorded: {vc_paths.project_relative(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
