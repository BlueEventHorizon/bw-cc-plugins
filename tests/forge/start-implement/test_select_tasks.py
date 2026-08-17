#!/usr/bin/env python3
"""select_tasks.py の契約テスト。"""

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
    / "select_tasks.py"
)

_SPEC = importlib.util.spec_from_file_location("select_tasks", SCRIPT)
select_tasks_module = importlib.util.module_from_spec(_SPEC)
sys.modules["select_tasks"] = select_tasks_module
_SPEC.loader.exec_module(select_tasks_module)


def _task(task_id, priority=50, status="pending", depends_on=None, group_id=None):
    return {
        "task_id": task_id,
        "title": task_id,
        "priority": priority,
        "status": status,
        "design_id": None,
        "depends_on": depends_on or [],
        "group_id": group_id,
        "build_check": "per_task",
        "description": ["x"],
        "acceptance_criteria": None,
        "required_reading": [],
    }


class SelectTasksFunctionTest(unittest.TestCase):
    def test_default_selects_single_highest_priority_pending(self):
        plan = {"tasks": [_task("TASK-001", priority=10), _task("TASK-002", priority=90)]}
        result, errors = select_tasks_module.select_tasks(plan)
        self.assertEqual(errors, [])
        self.assertEqual(result["selected_task_ids"], ["TASK-002"])

    def test_completed_tasks_are_excluded(self):
        plan = {"tasks": [_task("TASK-001", priority=90, status="completed"), _task("TASK-002", priority=50)]}
        result, errors = select_tasks_module.select_tasks(plan)
        self.assertEqual(errors, [])
        self.assertEqual(result["selected_task_ids"], ["TASK-002"])

    def test_count_selects_top_n_by_priority(self):
        plan = {
            "tasks": [
                _task("TASK-001", priority=10),
                _task("TASK-002", priority=90),
                _task("TASK-003", priority=50),
            ]
        }
        result, errors = select_tasks_module.select_tasks(plan, count=2)
        self.assertEqual(errors, [])
        self.assertEqual(result["selected_task_ids"], ["TASK-002", "TASK-003"])

    def test_group_atomic_selection_pulls_in_other_pending_members(self):
        plan = {
            "tasks": [
                _task("TASK-001", priority=90, group_id="GROUP-001 (1/2)"),
                _task("TASK-002", priority=10, group_id="GROUP-001 (2/2)"),
            ]
        }
        result, errors = select_tasks_module.select_tasks(plan, count=1)
        self.assertEqual(errors, [])
        self.assertEqual(set(result["selected_task_ids"]), {"TASK-001", "TASK-002"})

    def test_explicit_task_ids_are_selected_verbatim(self):
        plan = {"tasks": [_task("TASK-001"), _task("TASK-002")]}
        result, errors = select_tasks_module.select_tasks(plan, task_ids=["TASK-002"])
        self.assertEqual(errors, [])
        self.assertEqual(result["selected_task_ids"], ["TASK-002"])

    def test_unknown_task_id_is_rejected(self):
        plan = {"tasks": [_task("TASK-001")]}
        result, errors = select_tasks_module.select_tasks(plan, task_ids=["TASK-999"])
        self.assertIsNone(result)
        self.assertTrue(any("TASK-999" in e for e in errors))

    def test_mutual_dependency_in_explicit_selection_is_rejected(self):
        plan = {
            "tasks": [
                _task("TASK-001", depends_on=["TASK-002"]),
                _task("TASK-002"),
            ]
        }
        result, errors = select_tasks_module.select_tasks(
            plan, task_ids=["TASK-001", "TASK-002"]
        )
        self.assertIsNone(result)
        self.assertTrue(any("TASK-001" in e for e in errors))

    def test_incomplete_dependency_outside_selection_is_rejected(self):
        plan = {
            "tasks": [
                _task("TASK-001", depends_on=["TASK-002"]),
                _task("TASK-002", status="pending"),
            ]
        }
        result, errors = select_tasks_module.select_tasks(plan, count=1)
        self.assertIsNone(result)
        self.assertTrue(errors)

    def test_no_pending_tasks_returns_empty_selection(self):
        plan = {"tasks": [_task("TASK-001", status="completed")]}
        result, errors = select_tasks_module.select_tasks(plan)
        self.assertEqual(errors, [])
        self.assertEqual(result["selected_task_ids"], [])

    def test_selected_tasks_contain_full_task_data(self):
        plan = {"tasks": [_task("TASK-001", priority=99)]}
        result, errors = select_tasks_module.select_tasks(plan)
        self.assertEqual(errors, [])
        self.assertEqual(result["selected_tasks"], [_task("TASK-001", priority=99)])

    def test_waiting_group_when_dependency_incomplete_within_selection(self):
        plan = {
            "tasks": [
                _task("TASK-001", priority=90),
                _task("TASK-002", priority=80, depends_on=["TASK-001"]),
            ]
        }
        result, errors = select_tasks_module.select_tasks(plan, count=2)
        self.assertEqual(errors, [])
        self.assertEqual(result["executable_task_ids"], ["TASK-001"])
        self.assertEqual(result["waiting_task_ids"], ["TASK-002"])


class RunCliTest(unittest.TestCase):
    def _run(self, plan_path, extra_args=None):
        args = [sys.executable, str(SCRIPT), "--plan-path", str(plan_path)]
        args.extend(extra_args or [])
        return subprocess.run(args, capture_output=True, text=True)

    def test_success_exit_code_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "foo_plan.json"
            plan_path.write_text(
                json.dumps({"tasks": [_task("TASK-001", priority=99)]}), encoding="utf-8"
            )
            result = self._run(plan_path)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["selected_task_ids"], ["TASK-001"])

    def test_task_and_count_together_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "foo_plan.json"
            plan_path.write_text(json.dumps({"tasks": []}), encoding="utf-8")
            result = self._run(plan_path, ["--task", "TASK-001", "--count", "1"])
            self.assertEqual(result.returncode, 20)

    def test_missing_plan_file_is_error(self):
        result = self._run(Path("/nonexistent/plan.json"))
        self.assertEqual(result.returncode, 20)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "error")


if __name__ == "__main__":
    unittest.main()
