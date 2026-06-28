import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))


class FakeConn:
    def __init__(self):
        self.executed = []

    def execute(self, code):
        self.executed.append(code)


class FakeHou:
    class _HipFile:
        @staticmethod
        def path():
            return "E:/VirtualCity/Houdini/Hip/VC_area_citygen_v001.hip"

    hipFile = _HipFile()

    def node(self, path):
        return object() if path == "/obj/city_gen" else None


class FakeQA:
    created = []

    def __init__(self, conn, hou, obj_path, mode):
        self.conn = conn
        self.hou = hou
        self.obj_path = obj_path
        self.mode = mode
        self.checks = []
        self.metrics = {}
        FakeQA.created.append(self)

    def run(self):
        self.checks.append({"name": "smoke", "status": "pass"})


class TestModelQaRunner(unittest.TestCase):
    def test_run_model_qa_reuses_existing_houdini_connection(self):
        from houdini_build import model_qa_runner

        reports = []

        def write_report(report):
            reports.append(report)
            report["report_path"] = "Reports/model_qa/area_latest.json"
            return ROOT / "Reports" / "model_qa" / "area_latest.json"

        fake_model_qa = types.SimpleNamespace(
            FAIL="fail",
            PASS="pass",
            WARN="warn",
            REMOTE_HELPERS="helpers",
            QA=FakeQA,
            now_stamp=lambda: "20260627_120000",
            overall_status=lambda checks: "pass",
            write_report=write_report,
            print_summary=lambda report, path: None,
        )
        old_model_qa = model_qa_runner.model_qa
        model_qa_runner.model_qa = fake_model_qa
        try:
            conn = FakeConn()
            hou = FakeHou()
            result = model_qa_runner.run_model_qa(
                conn,
                hou,
                "/obj/city_gen",
                "quick",
                {"area_id": "area", "run_id": "run"},
            )
        finally:
            model_qa_runner.model_qa = old_model_qa
            created = list(FakeQA.created)
            FakeQA.created.clear()

        self.assertEqual(conn.executed, ["import hou", "helpers"])
        self.assertEqual(len(created), 1)
        self.assertIs(created[0].conn, conn)
        self.assertIs(created[0].hou, hou)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["report_path"], "Reports/model_qa/area_latest.json")
        self.assertEqual(reports[0]["area_id"], "area")
        self.assertEqual(reports[0]["run_id"], "run")
        self.assertEqual(reports[0]["obj_path"], "/obj/city_gen")
        self.assertEqual(reports[0]["hip_path"], "E:/VirtualCity/Houdini/Hip/VC_area_citygen_v001.hip")


if __name__ == "__main__":
    unittest.main()
