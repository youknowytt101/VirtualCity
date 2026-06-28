"""Maintenance guardrails for module boundaries and status contracts."""
from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "Scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _import_required(module_name: str):
    spec = importlib.util.find_spec(module_name)
    assert spec is not None, f"{module_name} module is required"
    return importlib.import_module(module_name)


def test_boundary_guard_allows_current_physical_module_imports():
    guard = _import_required("maintenance.boundary_guard")

    rules = [
        guard.BoundaryRule(
            name="acquisition",
            root=SCRIPTS / "acquisition",
            forbidden_prefixes=("cleaning", "houdini_build"),
        ),
        guard.BoundaryRule(
            name="cleaning",
            root=SCRIPTS / "cleaning",
            forbidden_prefixes=("acquisition", "houdini_build", "orchestration"),
        ),
        guard.BoundaryRule(
            name="houdini_build",
            root=SCRIPTS / "houdini_build",
            forbidden_prefixes=("acquisition", "cleaning", "set_area", "refine_data"),
        ),
    ]

    violations = guard.find_import_violations(rules)

    assert violations == []


def test_boundary_guard_reports_exact_file_line_for_violation(tmp_path):
    guard = _import_required("maintenance.boundary_guard")
    source = tmp_path / "acquisition" / "bad_imports.py"
    source.parent.mkdir()
    source.write_text(
        "from houdini_build.status import write_build_status\n"
        "import cleaning.refine_data\n",
        encoding="utf-8",
    )

    violations = guard.find_import_violations([
        guard.BoundaryRule(
            name="acquisition",
            root=source.parent,
            forbidden_prefixes=("cleaning", "houdini_build"),
        )
    ])

    assert [(v.file.name, v.line, v.imported) for v in violations] == [
        ("bad_imports.py", 1, "houdini_build.status"),
        ("bad_imports.py", 2, "cleaning.refine_data"),
    ]
    assert "bad_imports.py:1 imports houdini_build.status" in guard.format_violations(violations)


def test_build_status_contract_serializes_optional_fields():
    contracts = _import_required("shared.vc_contracts")

    payload = contracts.BuildStatus(
        area_id="area_a",
        run_id="run_a",
        status="completed",
        hip_path="Houdini/Hip/test.hip",
        message="done",
        timestamp="2026-06-28 12:00:00",
        qa_status="pass",
        qa_report="Reports/model_qa/report.json",
        whitebox_path="Houdini/Export/whitebox.glb",
    ).to_json_dict()

    assert payload == {
        "area_id": "area_a",
        "run_id": "run_a",
        "status": "completed",
        "hip_path": "Houdini/Hip/test.hip",
        "message": "done",
        "timestamp": "2026-06-28 12:00:00",
        "qa_status": "pass",
        "qa_report": "Reports/model_qa/report.json",
        "whitebox_path": "Houdini/Export/whitebox.glb",
    }


def test_build_status_contract_rejects_missing_identity_and_unknown_status():
    contracts = _import_required("shared.vc_contracts")

    with pytest.raises(ValueError, match="area_id"):
        contracts.BuildStatus(area_id="", run_id="run_a", status="completed")

    with pytest.raises(ValueError, match="status"):
        contracts.BuildStatus(area_id="area_a", run_id="run_a", status="surprised")


def test_houdini_status_writer_rejects_unknown_status(tmp_path, monkeypatch):
    writer = _import_required("houdini_build.status")
    monkeypatch.setattr(writer, "ROOT", tmp_path)

    with pytest.raises(ValueError, match="status"):
        writer.write_build_status("area_a", "surprised", run_id="run_a")

    assert not (tmp_path / "Config" / "houdini_build_status.json").exists()


def test_model_qa_contract_projects_run_qa_facts():
    contracts = _import_required("shared.vc_contracts")

    report = contracts.ModelQaReport.from_json_dict({
        "area_id": "area_a",
        "run_id": "run_a",
        "status": "pass",
        "summary": {"pass": 13, "warn": 0, "fail": 0},
    })

    assert report.passed is True
    assert report.to_run_qa(report="Reports/model_qa/latest.json") == {
        "status": "pass",
        "report": "Reports/model_qa/latest.json",
        "passed": True,
    }


def test_model_qa_contract_rejects_missing_run_id():
    contracts = _import_required("shared.vc_contracts")

    with pytest.raises(ValueError, match="run_id"):
        contracts.ModelQaReport.from_json_dict({
            "area_id": "area_a",
            "run_id": "",
            "status": "pass",
            "summary": {"pass": 1, "warn": 0, "fail": 0},
        })


def test_pipeline_state_rejects_unknown_qa_status(tmp_path, monkeypatch):
    pipeline_state = _import_required("orchestration.pipeline_state")
    runs = tmp_path / "pipeline_runs"
    monkeypatch.setattr(pipeline_state, "RUNS_DIR", runs)
    monkeypatch.setattr(pipeline_state, "LATEST_RUN", runs / "latest.json")
    pipeline_state.create_run({"area_id": "area_a"}, source="unit-test", run_id="run_a")

    with pytest.raises(ValueError, match="status"):
        pipeline_state.set_qa("run_a", status="surprised", report="bad")

    run = pipeline_state.load_run("run_a")
    assert run["qa"] == {}


def test_verify_cli_can_run_import_boundary_guard_only():
    verify = SCRIPTS / "verify.py"
    assert verify.exists(), "Scripts/verify.py is required"

    result = subprocess.run(
        [sys.executable, str(verify), "--boundaries-only"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "import-boundaries: OK" in result.stdout
