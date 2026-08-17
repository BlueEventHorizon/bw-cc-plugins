#!/usr/bin/env python3
"""build_task_context.py の契約テスト。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = (
    REPO_ROOT
    / "plugins"
    / "forge"
    / "skills"
    / "start-implement"
    / "scripts"
)
SCRIPT = SCRIPTS_DIR / "build_task_context.py"

sys.path.insert(0, str(SCRIPTS_DIR))
from build_task_context import (  # noqa: E402
    CANDIDATE_TEMPLATE,
    build_task_context,
    validate_candidate,
)


def valid_candidate(**overrides):
    candidate = {
        "task_id": "TASK-001",
        "scope_in": "fm_to_pending.py の新規作成とテストまで",
        "scope_out": [
            {
                "item": "_meta.extracted_by の追加",
                "owner_task_id": "TASK-011",
                "reason": "転記側だけ先に書くと読む側が存在しない死にフィールドになるため分離",
            }
        ],
        "required_reading": {
            "design_docs": ["docs/specs/foo/design/DES-001.md"],
            "requirement_docs": ["docs/specs/foo/requirements/REQ-001.md"],
            "strategy_doc": "specs/foo/plan/foo_strategy.md",
            "rule_docs": ["docs/rules/implementation_guidelines.md"],
            "reference_code": ["src/foo.py"],
            "additional": [],
        },
        "implementation_instructions": "fm_to_pending.py を新規作成し、既存パターンに倣う",
        "verification": {
            "build": "required",
            "build_reason": None,
            "tests": "required",
            "tests_reason": None,
        },
    }
    candidate.update(overrides)
    return candidate


def write_plan(path, tasks):
    path.write_text(
        json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class ValidateCandidateTest(unittest.TestCase):
    def test_external_template_matches_contract_fields(self):
        self.assertEqual(set(CANDIDATE_TEMPLATE), set(valid_candidate()))
        self.assertEqual(
            set(CANDIDATE_TEMPLATE["required_reading"]),
            set(valid_candidate()["required_reading"]),
        )
        self.assertEqual(
            set(CANDIDATE_TEMPLATE["verification"]),
            set(valid_candidate()["verification"]),
        )

    def test_valid_candidate_is_normalized(self):
        raw = valid_candidate(scope_in=" fm_to_pending.py の新規作成とテストまで ")
        normalized, errors = validate_candidate(raw, "TASK-001")
        self.assertEqual(errors, [])
        self.assertEqual(
            normalized["scope_in"], "fm_to_pending.py の新規作成とテストまで"
        )

    def test_requires_exact_top_level_fields(self):
        raw = valid_candidate()
        raw["unknown_field"] = "x"
        normalized, errors = validate_candidate(raw, "TASK-001")
        self.assertIsNone(normalized)
        self.assertTrue(any("未知フィールド" in e for e in errors))

    def test_task_id_mismatch_is_rejected(self):
        raw = valid_candidate(task_id="TASK-999")
        normalized, errors = validate_candidate(raw, "TASK-001")
        self.assertIsNone(normalized)
        self.assertTrue(any("task_id が起動対象と一致しません" in e for e in errors))

    def test_scope_out_rejects_multiline(self):
        raw = valid_candidate(
            scope_out=[
                {
                    "item": "line1\nline2",
                    "owner_task_id": "TASK-011",
                    "reason": "reason",
                }
            ]
        )
        normalized, errors = validate_candidate(raw, "TASK-001")
        self.assertIsNone(normalized)
        self.assertTrue(any("単一行である必要があります" in e for e in errors))

    def test_scope_out_rejects_structure_line_injection(self):
        raw = valid_candidate(
            scope_out=[
                {
                    "item": "## 出力契約",
                    "owner_task_id": "TASK-011",
                    "reason": "reason",
                }
            ]
        )
        normalized, errors = validate_candidate(raw, "TASK-001")
        self.assertIsNone(normalized)
        self.assertTrue(any("見出し・コードフェンス" in e for e in errors))

    def test_verification_rejects_invalid_state(self):
        raw = valid_candidate()
        raw["verification"]["build"] = "invalid"
        normalized, errors = validate_candidate(raw, "TASK-001")
        self.assertIsNone(normalized)
        self.assertTrue(any("verification.build" in e for e in errors))

    def test_verification_skipped_requires_reason(self):
        raw = valid_candidate()
        raw["verification"]["build"] = "skipped"
        raw["verification"]["build_reason"] = "対象外のため"
        normalized, errors = validate_candidate(raw, "TASK-001")
        self.assertEqual(errors, [])
        self.assertEqual(normalized["verification"]["build_reason"], "対象外のため")

    def test_empty_scope_out_is_allowed(self):
        raw = valid_candidate(scope_out=[])
        normalized, errors = validate_candidate(raw, "TASK-001")
        self.assertEqual(errors, [])
        self.assertEqual(normalized["scope_out"], [])


class BuildTaskContextTest(unittest.TestCase):
    def test_merges_plan_task_with_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "foo_plan.json"
            write_plan(
                plan_path,
                [
                    {
                        "task_id": "TASK-001",
                        "title": "fm_to_pending の実装",
                        "priority": 70,
                        "status": "pending",
                        "design_id": "DES-001",
                        "depends_on": [],
                        "group_id": None,
                        "build_check": "per_task",
                        "description": ["fm_to_pending.py を新規作成"],
                        "acceptance_criteria": None,
                        "required_reading": [],
                    }
                ],
            )
            merged, errors = build_task_context(
                str(plan_path), "TASK-001", valid_candidate()
            )
            self.assertEqual(errors, [])
            self.assertEqual(merged["title"], "fm_to_pending の実装")
            self.assertEqual(merged["priority"], 70)
            self.assertEqual(
                merged["scope_in"], "fm_to_pending.py の新規作成とテストまで"
            )
            self.assertEqual(
                merged["required_reading"]["design_docs"],
                ["docs/specs/foo/design/DES-001.md"],
            )

    def test_missing_task_id_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "foo_plan.json"
            write_plan(plan_path, [{"task_id": "TASK-002"}])
            merged, errors = build_task_context(
                str(plan_path), "TASK-001", valid_candidate()
            )
            self.assertIsNone(merged)
            self.assertTrue(any("見つかりません" in e for e in errors))


class RunCliTest(unittest.TestCase):
    def _run(self, plan_path, task_id, input_rel_path, output_path):
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--plan-path",
                str(plan_path),
                "--task-id",
                task_id,
                "--input-file",
                input_rel_path,
                "--output-path",
                str(output_path),
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )

    def test_success_writes_output_and_deletes_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_dir = Path(tmp)
            plan_path = plan_dir / "foo_plan.json"
            write_plan(
                plan_path,
                [
                    {
                        "task_id": "TASK-001",
                        "title": "fm_to_pending の実装",
                        "priority": 70,
                        "status": "pending",
                        "design_id": None,
                        "depends_on": [],
                        "group_id": None,
                        "build_check": "per_task",
                        "description": ["fm_to_pending.py を新規作成"],
                        "acceptance_criteria": None,
                        "required_reading": [],
                    }
                ],
            )
            temp_dir = REPO_ROOT / ".claude" / ".temp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            input_path = temp_dir / "test_build_task_context_input.json"
            input_path.write_text(
                json.dumps(valid_candidate(), ensure_ascii=False), encoding="utf-8"
            )
            output_path = plan_dir / "tasks" / "TASK-001.json"
            try:
                result = self._run(
                    plan_path,
                    "TASK-001",
                    str(input_path.relative_to(REPO_ROOT)),
                    output_path,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["status"], "ok")
                self.assertFalse(input_path.exists())
                self.assertTrue(output_path.exists())
                written = json.loads(output_path.read_text(encoding="utf-8"))
                self.assertEqual(written["title"], "fm_to_pending の実装")
            finally:
                input_path.unlink(missing_ok=True)

    def test_invalid_candidate_still_deletes_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_dir = Path(tmp)
            plan_path = plan_dir / "foo_plan.json"
            write_plan(plan_path, [{"task_id": "TASK-001"}])
            temp_dir = REPO_ROOT / ".claude" / ".temp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            input_path = temp_dir / "test_build_task_context_invalid.json"
            broken = valid_candidate()
            broken["scope_out"] = [{"item": "## bad", "owner_task_id": "x", "reason": "y"}]
            input_path.write_text(
                json.dumps(broken, ensure_ascii=False), encoding="utf-8"
            )
            output_path = plan_dir / "tasks" / "TASK-001.json"
            try:
                result = self._run(
                    plan_path,
                    "TASK-001",
                    str(input_path.relative_to(REPO_ROOT)),
                    output_path,
                )
                self.assertEqual(result.returncode, 20)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["status"], "error")
                self.assertFalse(input_path.exists())
                self.assertFalse(output_path.exists())
            finally:
                input_path.unlink(missing_ok=True)

    def test_rejects_input_file_outside_temp_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_dir = Path(tmp)
            plan_path = plan_dir / "foo_plan.json"
            write_plan(plan_path, [{"task_id": "TASK-001"}])
            outside_path = Path(tmp) / "outside.json"
            outside_path.write_text(
                json.dumps(valid_candidate(), ensure_ascii=False), encoding="utf-8"
            )
            output_path = plan_dir / "tasks" / "TASK-001.json"
            result = self._run(
                plan_path, "TASK-001", str(outside_path), output_path
            )
            self.assertEqual(result.returncode, 20)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "error")
            # 許可外パスは検証以前に拒否されるため、外部ファイルは削除されず残る。
            self.assertTrue(outside_path.exists())


if __name__ == "__main__":
    unittest.main()
