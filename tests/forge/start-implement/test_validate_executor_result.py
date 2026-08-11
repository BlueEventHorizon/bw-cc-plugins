#!/usr/bin/env python3
"""validate_executor_result.py の契約テスト。"""

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
    / "validate_executor_result.py"
)
RECEIVE_SCRIPT = SCRIPT.with_name("receive_executor_result.py")

sys.path.insert(0, str(SCRIPT.parent))
from executor_result_contract import (
    EXECUTOR_RESULT_TEMPLATE,
    failure_result,
    validate_result,
)


def valid_result(**overrides):
    result = {
        "task_id": "TASK-001",
        "status": "SUCCESS",
        "files_modified": ["src/foo.py"],
        "summary": "foo を実装",
        "verification": {
            "build": "success",
            "build_reason": None,
            "tests": "skipped",
            "tests_reason": "検証要件でスキップ",
        },
        "pre_mortem": {
            "actualized_risks": [],
            "implementation_adjustments": ["既存実装を先に確認"],
        },
        "notes": [],
        "error": None,
    }
    result.update(overrides)
    return result


class ValidateResultTest(unittest.TestCase):
    def test_external_template_matches_contract_fields(self):
        self.assertEqual(set(EXECUTOR_RESULT_TEMPLATE), set(valid_result()))
        self.assertEqual(
            set(EXECUTOR_RESULT_TEMPLATE["verification"]),
            set(valid_result()["verification"]),
        )
        self.assertEqual(
            set(EXECUTOR_RESULT_TEMPLATE["pre_mortem"]),
            set(valid_result()["pre_mortem"]),
        )

    def test_valid_result_is_normalized(self):
        raw = valid_result(
            task_id=" TASK-001 ",
            files_modified=[" src/foo.py "],
            summary=" foo を実装 ",
        )
        normalized, errors = validate_result(raw, "TASK-001")
        self.assertEqual(errors, [])
        self.assertEqual(normalized["task_id"], "TASK-001")
        self.assertEqual(normalized["files_modified"], ["src/foo.py"])
        self.assertEqual(normalized["summary"], "foo を実装")

    def test_requires_exact_top_level_fields(self):
        raw = valid_result()
        del raw["pre_mortem"]
        raw["unexpected"] = True
        normalized, errors = validate_result(raw, "TASK-001")
        self.assertIsNone(normalized)
        self.assertTrue(any("必須フィールド" in error for error in errors))
        self.assertTrue(any("未知フィールド" in error for error in errors))

    def test_task_id_must_match_invocation(self):
        normalized, errors = validate_result(valid_result(), "TASK-999")
        self.assertIsNone(normalized)
        self.assertTrue(any("起動対象と一致しません" in error for error in errors))

    def test_success_requires_null_error(self):
        normalized, errors = validate_result(
            valid_result(error="成功なのにエラー"),
            "TASK-001",
        )
        self.assertIsNone(normalized)
        self.assertIn("error は SUCCESS 時は null です", errors)

    def test_failure_requires_nonempty_error(self):
        normalized, errors = validate_result(
            valid_result(status="FAILURE", error=None),
            "TASK-001",
        )
        self.assertIsNone(normalized)
        self.assertTrue(any("error は空でない文字列" in error for error in errors))

    def test_verification_reason_matches_state(self):
        raw = valid_result()
        raw["verification"]["tests_reason"] = None
        normalized, errors = validate_result(raw, "TASK-001")
        self.assertIsNone(normalized)
        self.assertTrue(
            any("verification.tests_reason は空でない文字列" in error for error in errors)
        )

    def test_success_rejects_failed_verification(self):
        raw = valid_result()
        raw["verification"]["tests"] = "failed"
        raw["verification"]["tests_reason"] = "テスト失敗"
        normalized, errors = validate_result(raw, "TASK-001")
        self.assertIsNone(normalized)
        self.assertIn(
            "status が SUCCESS の場合、verification を failed にできません",
            errors,
        )

    def test_success_rejects_skipped_required_verification(self):
        raw = valid_result()
        raw["verification"]["build"] = "skipped"
        raw["verification"]["build_reason"] = "未実行"
        normalized, errors = validate_result(
            raw,
            "TASK-001",
            expected_build="required",
            expected_tests="optional",
        )
        self.assertIsNone(normalized)
        self.assertIn(
            "必須の build 検証は SUCCESS 時に success である必要があります",
            errors,
        )

    def test_success_accepts_skipped_optional_tests(self):
        normalized, errors = validate_result(
            valid_result(),
            "TASK-001",
            expected_build="required",
            expected_tests="optional",
        )
        self.assertEqual(errors, [])
        self.assertEqual(normalized["verification"]["tests"], "skipped")

    def test_success_requires_skipped_state_when_verification_is_skipped(self):
        raw = valid_result()
        raw["verification"]["build"] = "success"
        normalized, errors = validate_result(
            raw,
            "TASK-001",
            expected_build="skipped",
            expected_tests="optional",
        )
        self.assertIsNone(normalized)
        self.assertIn(
            "スキップ指定の build 検証は skipped である必要があります",
            errors,
        )

    def test_failure_also_requires_skipped_state_when_verification_is_skipped(self):
        raw = valid_result(status="FAILURE", error="実装失敗")
        raw["verification"]["tests"] = "success"
        raw["verification"]["tests_reason"] = None
        normalized, errors = validate_result(
            raw,
            "TASK-001",
            expected_build="skipped",
            expected_tests="skipped",
        )
        self.assertIsNone(normalized)
        self.assertIn(
            "スキップ指定の build 検証は skipped である必要があります",
            errors,
        )
        self.assertIn(
            "スキップ指定の tests 検証は skipped である必要があります",
            errors,
        )

    def test_summary_is_limited_to_two_lines(self):
        normalized, errors = validate_result(
            valid_result(summary="one\ntwo\nthree"),
            "TASK-001",
        )
        self.assertIsNone(normalized)
        self.assertIn("summary は 1〜2 行である必要があります", errors)

    def test_pre_mortem_arrays_are_limited_to_five_items(self):
        raw = valid_result()
        raw["pre_mortem"]["actualized_risks"] = [f"risk-{index}" for index in range(6)]
        normalized, errors = validate_result(raw, "TASK-001")
        self.assertIsNone(normalized)
        self.assertIn("pre_mortem.actualized_risks は最大 5 件です", errors)

    def test_rejects_absolute_parent_and_duplicate_paths(self):
        raw = valid_result(
            files_modified=["/tmp/a.py", "../b.py", "src/foo.py", "src/foo.py"]
        )
        normalized, errors = validate_result(raw, "TASK-001")
        self.assertIsNone(normalized)
        self.assertEqual(
            sum("プロジェクトルート相対パス" in error for error in errors),
            2,
        )
        self.assertTrue(any("重複" in error for error in errors))

    def test_rejects_nul_in_path(self):
        normalized, errors = validate_result(
            valid_result(files_modified=["src/\0foo.py"]),
            "TASK-001",
        )
        self.assertIsNone(normalized)
        self.assertTrue(any("NUL 文字" in error for error in errors))

    def test_pre_mortem_fields_are_string_arrays(self):
        raw = valid_result(
            pre_mortem={
                "actualized_risks": "risk",
                "implementation_adjustments": [""],
            }
        )
        normalized, errors = validate_result(raw, "TASK-001")
        self.assertIsNone(normalized)
        self.assertTrue(any("actualized_risks は配列" in error for error in errors))
        self.assertTrue(
            any("implementation_adjustments[0]" in error for error in errors)
        )

    def test_non_hashable_status_and_verification_states_return_errors(self):
        raw = valid_result(status=[])
        raw["verification"]["build"] = []
        raw["verification"]["tests"] = {}
        normalized, errors = validate_result(raw, "TASK-001")
        self.assertIsNone(normalized)
        self.assertIn("status は SUCCESS / FAILURE のいずれかです", errors)
        self.assertTrue(any("verification.build は" in error for error in errors))
        self.assertTrue(any("verification.tests は" in error for error in errors))


class FailureResultTest(unittest.TestCase):
    def test_failure_result_conforms_to_schema(self):
        result = failure_result("TASK-001", ["bad result"])
        normalized, errors = validate_result(result, "TASK-001")
        self.assertEqual(errors, [])
        self.assertEqual(normalized["status"], "FAILURE")
        self.assertEqual(normalized["notes"], ["bad result"])

    def test_failure_result_respects_skipped_expectations(self):
        result = failure_result(
            "TASK-001",
            ["bad result"],
            expected_build="skipped",
            expected_tests="skipped",
        )
        normalized, errors = validate_result(
            result,
            "TASK-001",
            expected_build="skipped",
            expected_tests="skipped",
        )
        self.assertEqual(errors, [])
        self.assertEqual(normalized["verification"]["build"], "skipped")
        self.assertEqual(normalized["verification"]["tests"], "skipped")


class CliTest(unittest.TestCase):
    def run_cli(self, payload, script=SCRIPT):
        temp_dir = REPO_ROOT / ".claude" / ".temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            dir=temp_dir,
            delete=False,
        ) as handle:
            handle.write(payload)
            input_file = Path(handle.name)
        relative_input = input_file.relative_to(REPO_ROOT)
        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                "--input-file",
                str(relative_input),
                "--expected-task-id",
                "TASK-001",
                "--expected-build",
                "required",
                "--expected-tests",
                "optional",
            ],
            text=True,
            capture_output=True,
            check=False,
            cwd=REPO_ROOT,
        )
        self.assertFalse(input_file.exists(), "wrapper は入力ファイルを削除すること")
        return completed

    def test_valid_input_outputs_normalized_result(self):
        completed = self.run_cli(json.dumps(valid_result()))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["task_id"], "TASK-001")

    def test_invalid_input_returns_errors_and_exit_20(self):
        completed = self.run_cli("not-json")
        self.assertEqual(completed.returncode, 20)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "error")
        self.assertTrue(result["errors"])

    def test_failure_on_error_outputs_valid_failure_result(self):
        completed = self.run_cli("not-json", script=RECEIVE_SCRIPT)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["task_id"], "TASK-001")
        self.assertEqual(result["status"], "FAILURE")
        normalized, errors = validate_result(result, "TASK-001")
        self.assertEqual(errors, [])
        self.assertEqual(normalized, result)

    def test_missing_input_file_returns_errors(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--input-file",
                ".claude/.temp/nonexistent-result.json",
                "--expected-task-id",
                "TASK-001",
                "--expected-build",
                "required",
                "--expected-tests",
                "optional",
            ],
            text=True,
            capture_output=True,
            check=False,
            cwd=REPO_ROOT,
        )
        self.assertEqual(completed.returncode, 20)
        self.assertEqual(json.loads(completed.stdout)["status"], "error")


if __name__ == "__main__":
    unittest.main()
