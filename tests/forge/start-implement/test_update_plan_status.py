#!/usr/bin/env python3
"""update_plan_status.py の契約テスト。"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    REPO_ROOT
    / "plugins"
    / "forge"
    / "skills"
    / "start-implement"
    / "scripts"
    / "update_plan_status.py"
)

_SPEC = importlib.util.spec_from_file_location("update_plan_status", SCRIPT)
update_plan_status_module = importlib.util.module_from_spec(_SPEC)
sys.modules["update_plan_status"] = update_plan_status_module
_SPEC.loader.exec_module(update_plan_status_module)


def _task(task_id, status="pending"):
    return {
        "task_id": task_id,
        "title": task_id,
        "priority": 50,
        "status": status,
        "design_id": None,
        "depends_on": [],
        "group_id": None,
        "build_check": "per_task",
        "description": ["x"],
        "acceptance_criteria": None,
        "required_reading": [],
    }


class UpdatePlanStatusFunctionTest(unittest.TestCase):
    def test_marks_specified_tasks_completed(self):
        plan = {
            "requirements_traceability": [],
            "design_traceability": [],
            "tasks": [_task("TASK-001"), _task("TASK-002")],
            "revision_history": [],
        }
        updated, errors, count = update_plan_status_module.update_plan_status(
            plan, ["TASK-001"]
        )
        self.assertEqual(errors, [])
        self.assertEqual(count, 1)
        self.assertEqual(updated["tasks"][0]["status"], "completed")
        self.assertEqual(updated["tasks"][1]["status"], "pending")

    def test_unknown_task_id_is_rejected(self):
        plan = {"tasks": [_task("TASK-001")]}
        updated, errors, count = update_plan_status_module.update_plan_status(
            plan, ["TASK-999"]
        )
        self.assertIsNone(updated)
        self.assertTrue(any("TASK-999" in e for e in errors))

    def test_requirement_marked_completed_when_all_linked_tasks_done(self):
        plan = {
            "requirements_traceability": [
                {"requirement_id": "REQ-001", "title": "x", "design_id": "DES-001", "status": "pending"}
            ],
            "design_traceability": [
                {"design_id": "DES-001", "title": "x", "requirement_ids": ["REQ-001"], "task_ids": ["TASK-001", "TASK-002"]}
            ],
            "tasks": [_task("TASK-001"), _task("TASK-002", status="completed")],
            "revision_history": [],
        }
        updated, errors, count = update_plan_status_module.update_plan_status(
            plan, ["TASK-001"]
        )
        self.assertEqual(errors, [])
        self.assertEqual(updated["requirements_traceability"][0]["status"], "completed")

    def test_requirement_stays_pending_when_some_linked_task_incomplete(self):
        plan = {
            "requirements_traceability": [
                {"requirement_id": "REQ-001", "title": "x", "design_id": "DES-001", "status": "pending"}
            ],
            "design_traceability": [
                {"design_id": "DES-001", "title": "x", "requirement_ids": ["REQ-001"], "task_ids": ["TASK-001", "TASK-002"]}
            ],
            "tasks": [_task("TASK-001"), _task("TASK-002")],
            "revision_history": [],
        }
        updated, errors, count = update_plan_status_module.update_plan_status(
            plan, ["TASK-001"]
        )
        self.assertEqual(errors, [])
        self.assertEqual(updated["requirements_traceability"][0]["status"], "pending")

    def test_already_completed_task_is_not_double_counted(self):
        plan = {
            "requirements_traceability": [],
            "design_traceability": [],
            "tasks": [_task("TASK-001", status="completed")],
            "revision_history": [],
        }
        updated, errors, count = update_plan_status_module.update_plan_status(
            plan, ["TASK-001"]
        )
        self.assertEqual(errors, [])
        self.assertEqual(count, 0)


class RunCliTest(unittest.TestCase):
    def _run(self, plan_path, task_arg):
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--plan-path",
                str(plan_path),
                "--task",
                task_arg,
            ],
            capture_output=True,
            text=True,
        )

    def test_success_writes_back_updated_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "foo_plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "requirements_traceability": [],
                        "design_traceability": [],
                        "tasks": [_task("TASK-001")],
                        "revision_history": [],
                    }
                ),
                encoding="utf-8",
            )
            result = self._run(plan_path, "TASK-001")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["updated_count"], 1)
            written = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(written["tasks"][0]["status"], "completed")

    def test_missing_plan_file_is_error(self):
        result = self._run(Path("/nonexistent/plan.json"), "TASK-001")
        self.assertEqual(result.returncode, 20)


if __name__ == "__main__":
    unittest.main()
