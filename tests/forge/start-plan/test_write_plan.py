#!/usr/bin/env python3
"""write_plan.py の契約テスト。"""

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
    / "start-plan"
    / "scripts"
    / "write_plan.py"
)


def valid_plan_candidate(**overrides):
    candidate = {
        "requirements_traceability": [
            {"requirement_id": "REQ-001", "title": "Foo", "design_id": "DES-001", "status": "pending"}
        ],
        "design_traceability": [
            {"design_id": "DES-001", "title": "Foo", "requirement_ids": ["REQ-001"], "task_ids": ["TASK-001"]}
        ],
        "tasks": [
            {
                "task_id": "TASK-001",
                "title": "Foo を実装する",
                "priority": 70,
                "status": "pending",
                "design_id": "DES-001",
                "depends_on": [],
                "group_id": None,
                "build_check": "per_task",
                "description": ["Foo を作る"],
                "acceptance_criteria": None,
                "required_reading": [],
            }
        ],
        "revision_history": [],
    }
    candidate.update(overrides)
    return candidate


class RunCliTest(unittest.TestCase):
    def _run(self, input_rel_path, output_path):
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--input-file",
                input_rel_path,
                "--output-path",
                str(output_path),
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )

    def _write_input(self, name, data):
        temp_dir = REPO_ROOT / ".claude" / ".temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        input_path = temp_dir / name
        input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return input_path

    def test_success_writes_plan_and_deletes_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "foo_plan.json"
            input_path = self._write_input(
                "test_write_plan_success.json", valid_plan_candidate()
            )
            try:
                result = self._run(str(input_path.relative_to(REPO_ROOT)), output_path)
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["status"], "ok")
                self.assertFalse(input_path.exists())
                self.assertTrue(output_path.exists())
                written = json.loads(output_path.read_text(encoding="utf-8"))
                self.assertEqual(written["tasks"][0]["task_id"], "TASK-001")
            finally:
                input_path.unlink(missing_ok=True)

    def test_invalid_schema_still_deletes_input_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "foo_plan.json"
            broken = valid_plan_candidate()
            del broken["revision_history"]
            input_path = self._write_input("test_write_plan_invalid.json", broken)
            try:
                result = self._run(str(input_path.relative_to(REPO_ROOT)), output_path)
                self.assertEqual(result.returncode, 20)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["status"], "error")
                self.assertFalse(input_path.exists())
                self.assertFalse(output_path.exists())
            finally:
                input_path.unlink(missing_ok=True)

    def test_feature_meta_key_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "foo_plan.json"
            candidate = valid_plan_candidate(
                _feature_meta={"type": "temporary-feature-plan", "notes": ["x"]}
            )
            input_path = self._write_input(
                "test_write_plan_feature_meta.json", candidate
            )
            try:
                result = self._run(str(input_path.relative_to(REPO_ROOT)), output_path)
                self.assertEqual(result.returncode, 0, result.stderr)
                written = json.loads(output_path.read_text(encoding="utf-8"))
                self.assertIn("_feature_meta", written)
            finally:
                input_path.unlink(missing_ok=True)

    def test_rejects_input_file_outside_temp_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside_path = Path(tmp) / "outside.json"
            outside_path.write_text(
                json.dumps(valid_plan_candidate(), ensure_ascii=False), encoding="utf-8"
            )
            output_path = Path(tmp) / "foo_plan.json"
            result = self._run(str(outside_path), output_path)
            self.assertEqual(result.returncode, 20)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "error")
            self.assertTrue(outside_path.exists())


if __name__ == "__main__":
    unittest.main()
