#!/usr/bin/env python3
"""verify_fix_safety.py のテスト（DES-047 §3.3 テスト設計）。

本スクリプトは検出・報告専用（ファイルを一切変更しない）。ロールバックの実行判断は
Claude 自身が行う設計（DES-047 §2 見直し）であり、本テストはロールバック実施の有無ではなく
allowlist 逸脱・構文検証結果の検出が正しいことのみを検証する。

構文検証対象の拡張子（dprint系/.py/.sh）は、実 Codex レビューで発見の「削除されたファイル」
判定（§2.1 追加）がファイルの実在確認に基づくため、各テストは実在するダミーファイルを
一時ディレクトリに作成したうえで `project_root` を渡す（存在しないパスは無条件で
`syntax_skipped_deleted` に振り分けられ、mock した subprocess の結果を経由しない）。

実行:
  python3 -m unittest tests.forge.review.test_verify_fix_safety -v
"""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "skills" / "review" / "scripts" / "verify_fix_safety.py"
)

_spec = importlib.util.spec_from_file_location("msg_review_verify_fix_safety", _SCRIPT_PATH)
verify_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_mod)


def _completed(returncode, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _touch(tmpdir: str, *names: str) -> None:
    for name in names:
        (Path(tmpdir) / name).write_text("dummy\n", encoding="utf-8")


class VerifyAllowlistTest(unittest.TestCase):
    """allowlist 逸脱の検出（構文検証は対象外の拡張子で無効化して分離検証）。"""

    def test_modified_file_outside_allowed_is_violation(self):
        result = verify_mod.verify(
            allowed_files=["a.md"],
            modified_files=["a.md", "c.unknownext"],
            baseline={"files": {}},
        )
        self.assertEqual(result["status"], "violations")
        self.assertEqual(result["allowlist_violations"], ["c.unknownext"])

    def test_all_modified_within_allowed_is_no_violation(self):
        result = verify_mod.verify(
            allowed_files=["a.md", "b.unknownext"],
            modified_files=["a.md", "b.unknownext"],
            baseline={"files": {}},
        )
        self.assertEqual(result["allowlist_violations"], [])

    def test_deleted_file_outside_allowed_is_still_an_allowlist_violation(self):
        """存在しない（削除された）ファイルでも allowlist 逸脱の判定は通常どおり行う。"""
        result = verify_mod.verify(
            allowed_files=["a.md"],
            modified_files=["a.md", "outside_deleted.py"],
            baseline={"files": {}},
        )
        self.assertEqual(result["allowlist_violations"], ["outside_deleted.py"])


class VerifySyntaxDprintTest(unittest.TestCase):
    """dprint 系拡張子 (.md/.json/.yaml/.yml/.toml) の baseline-aware 判定。"""

    def test_dprint_violation_not_in_baseline_is_new_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _touch(tmpdir, "a.md")
            with mock.patch("subprocess.run", return_value=_completed(20)):
                result = verify_mod.verify(
                    allowed_files=["a.md"],
                    modified_files=["a.md"],
                    baseline={"files": {"a.md": {"has_violations": False, "exit_code": 0}}},
                    project_root=tmpdir,
                )
        self.assertEqual(result["status"], "violations")
        self.assertIn("a.md", result["syntax_errors"])
        self.assertEqual(result["syntax_ok"], [])

    def test_dprint_violation_in_baseline_is_skipped_preexisting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _touch(tmpdir, "a.md")
            with mock.patch("subprocess.run", return_value=_completed(20)):
                result = verify_mod.verify(
                    allowed_files=["a.md"],
                    modified_files=["a.md"],
                    baseline={"files": {"a.md": {"has_violations": True, "exit_code": 20}}},
                    project_root=tmpdir,
                )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["syntax_skipped_preexisting"], ["a.md"])
        self.assertEqual(result["syntax_errors"], {})

    def test_dprint_violation_not_baseline_captured_defaults_to_new_error(self):
        """baseline 未取得（キーが存在しない）場合は安全側に倒し新規エラー扱いにする。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _touch(tmpdir, "new_file.md")
            with mock.patch("subprocess.run", return_value=_completed(20)):
                result = verify_mod.verify(
                    allowed_files=["new_file.md"],
                    modified_files=["new_file.md"],
                    baseline={"files": {}},
                    project_root=tmpdir,
                )
        self.assertIn("new_file.md", result["syntax_errors"])

    def test_dprint_exit_0_is_ok(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _touch(tmpdir, "a.json")
            with mock.patch("subprocess.run", return_value=_completed(0)):
                result = verify_mod.verify(
                    allowed_files=["a.json"],
                    modified_files=["a.json"],
                    baseline={"files": {}},
                    project_root=tmpdir,
                )
        self.assertEqual(result["syntax_ok"], ["a.json"])

    def test_dprint_exit_14_out_of_scope_is_ok(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _touch(tmpdir, "a.yaml")
            with mock.patch("subprocess.run", return_value=_completed(14)):
                result = verify_mod.verify(
                    allowed_files=["a.yaml"],
                    modified_files=["a.yaml"],
                    baseline={"files": {}},
                    project_root=tmpdir,
                )
        self.assertEqual(result["syntax_ok"], ["a.yaml"])
        self.assertEqual(result["syntax_errors"], {})


class VerifySyntaxNonBaselineTest(unittest.TestCase):
    """Python (ast.parse) / bash -n は baseline を参照しない (fixer.md §3.5.4 の判断を踏襲)。"""

    def test_python_syntax_error_is_error_even_if_baseline_has_violations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _touch(tmpdir, "a.py")
            with mock.patch("subprocess.run", return_value=_completed(1, stderr="SyntaxError")):
                result = verify_mod.verify(
                    allowed_files=["a.py"],
                    modified_files=["a.py"],
                    baseline={"files": {"a.py": {"has_violations": True, "exit_code": 20}}},
                    project_root=tmpdir,
                )
        self.assertIn("a.py", result["syntax_errors"])
        self.assertEqual(result["syntax_skipped_preexisting"], [])

    def test_python_syntax_ok_is_ok(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _touch(tmpdir, "a.py")
            with mock.patch("subprocess.run", return_value=_completed(0)):
                result = verify_mod.verify(
                    allowed_files=["a.py"],
                    modified_files=["a.py"],
                    baseline={"files": {}},
                    project_root=tmpdir,
                )
        self.assertEqual(result["syntax_ok"], ["a.py"])

    def test_bash_syntax_error_is_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _touch(tmpdir, "a.sh")
            with mock.patch("subprocess.run", return_value=_completed(2, stderr="syntax error")):
                result = verify_mod.verify(
                    allowed_files=["a.sh"],
                    modified_files=["a.sh"],
                    baseline={"files": {}},
                    project_root=tmpdir,
                )
        self.assertIn("a.sh", result["syntax_errors"])

    def test_python_syntax_check_does_not_create_pycache_directory(self):
        """Python 構文検証がバイトコードキャッシュを残さないこと（実 Codex レビューで発見の回帰）。

        本スクリプトは「ファイルを一切書き換えない」検出専用スクリプト（§2.1）。
        `python3 -m py_compile` は cfile 未指定時に __pycache__/*.pyc を常に書き込み
        この契約に反するため、ファイルを一切生成しない ast.parse ベースの検証に変更した。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "a.py"
            target.write_text("x = 1\n", encoding="utf-8")

            result = verify_mod.verify(
                allowed_files=["a.py"],
                modified_files=["a.py"],
                baseline={"files": {}},
                project_root=tmpdir,
            )

            self.assertEqual(result["syntax_ok"], ["a.py"])
            self.assertFalse((Path(tmpdir) / "__pycache__").exists())

    def test_real_python_syntax_error_is_detected_without_mocking(self):
        """モックなしで、実際に壊れた Python ファイルの構文エラーを検出できること。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "broken.py"
            target.write_text("def f(:\n    pass\n", encoding="utf-8")

            result = verify_mod.verify(
                allowed_files=["broken.py"],
                modified_files=["broken.py"],
                baseline={"files": {}},
                project_root=tmpdir,
            )

            self.assertIn("broken.py", result["syntax_errors"])
            self.assertFalse((Path(tmpdir) / "__pycache__").exists())


class VerifyDeletedFileTest(unittest.TestCase):
    """削除された（実在しない）ファイルの構文検証スキップ（実 Codex レビューで発見）。"""

    def test_deleted_python_file_is_skipped_not_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("subprocess.run") as mock_run:
                result = verify_mod.verify(
                    allowed_files=["deleted.py"],
                    modified_files=["deleted.py"],
                    baseline={"files": {}},
                    project_root=tmpdir,
                )
        self.assertEqual(result["syntax_skipped_deleted"], ["deleted.py"])
        self.assertEqual(result["syntax_errors"], {})
        self.assertEqual(result["status"], "ok")
        mock_run.assert_not_called()

    def test_deleted_markdown_file_is_skipped_not_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("subprocess.run") as mock_run:
                result = verify_mod.verify(
                    allowed_files=["deleted.md"],
                    modified_files=["deleted.md"],
                    baseline={"files": {}},
                    project_root=tmpdir,
                )
        self.assertEqual(result["syntax_skipped_deleted"], ["deleted.md"])
        mock_run.assert_not_called()

    def test_deleted_shell_file_is_skipped_not_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("subprocess.run") as mock_run:
                result = verify_mod.verify(
                    allowed_files=["deleted.sh"],
                    modified_files=["deleted.sh"],
                    baseline={"files": {}},
                    project_root=tmpdir,
                )
        self.assertEqual(result["syntax_skipped_deleted"], ["deleted.sh"])
        mock_run.assert_not_called()

    def test_existing_file_is_not_treated_as_deleted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _touch(tmpdir, "present.py")
            with mock.patch("subprocess.run", return_value=_completed(0)):
                result = verify_mod.verify(
                    allowed_files=["present.py"],
                    modified_files=["present.py"],
                    baseline={"files": {}},
                    project_root=tmpdir,
                )
        self.assertEqual(result["syntax_skipped_deleted"], [])
        self.assertEqual(result["syntax_ok"], ["present.py"])


class VerifyUnsupportedExtensionTest(unittest.TestCase):
    def test_unsupported_extension_is_skipped_not_error(self):
        result = verify_mod.verify(
            allowed_files=["a.swift"],
            modified_files=["a.swift"],
            baseline={"files": {}},
        )
        self.assertEqual(result["syntax_skipped_unsupported"], ["a.swift"])
        self.assertEqual(result["syntax_errors"], {})
        self.assertEqual(result["status"], "ok")

    def test_unsupported_extension_is_not_checked_for_existence(self):
        """未対応拡張子は実在確認より前に振り分けられ、`syntax_skipped_deleted` に入らない。"""
        result = verify_mod.verify(
            allowed_files=["nonexistent.swift"],
            modified_files=["nonexistent.swift"],
            baseline={"files": {}},
        )
        self.assertEqual(result["syntax_skipped_unsupported"], ["nonexistent.swift"])
        self.assertEqual(result["syntax_skipped_deleted"], [])


class VerifyCombinedTest(unittest.TestCase):
    def test_allowlist_violation_and_syntax_error_both_reported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _touch(tmpdir, "a.md", "outside.md")
            with mock.patch("subprocess.run", return_value=_completed(20)):
                result = verify_mod.verify(
                    allowed_files=["a.md"],
                    modified_files=["a.md", "outside.md"],
                    baseline={"files": {}},
                    project_root=tmpdir,
                )
        self.assertEqual(result["status"], "violations")
        self.assertEqual(result["allowlist_violations"], ["outside.md"])
        self.assertIn("a.md", result["syntax_errors"])
        self.assertIn("outside.md", result["syntax_errors"])

    def test_no_mutation_side_effect_only_subprocess_invoked(self):
        """本スクリプトはファイルを書き換えない（Write/Edit 相当の呼び出しを一切行わない）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _touch(tmpdir, "a.md")
            with mock.patch("subprocess.run", return_value=_completed(20)) as mock_run:
                verify_mod.verify(
                    allowed_files=["a.md"],
                    modified_files=["a.md"],
                    baseline={"files": {}},
                    project_root=tmpdir,
                )
        for call in mock_run.call_args_list:
            cmd = call.args[0] if call.args else call.kwargs.get("cmd")
            self.assertNotIn("--fix", cmd)


class MainTest(unittest.TestCase):
    def test_cli_reads_args_and_outputs_single_json(self):
        result = subprocess.run(
            [
                "python3", str(_SCRIPT_PATH),
                "--allowed-files-json", '["a.unknownext"]',
                "--modified-files-json", '["a.unknownext"]',
                "--baseline-json", "{}",
            ],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["syntax_skipped_unsupported"], ["a.unknownext"])

    def test_cli_rejects_invalid_json(self):
        result = subprocess.run(
            [
                "python3", str(_SCRIPT_PATH),
                "--allowed-files-json", "not-json",
                "--modified-files-json", "[]",
                "--baseline-json", "{}",
            ],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "error")


if __name__ == "__main__":
    unittest.main()
