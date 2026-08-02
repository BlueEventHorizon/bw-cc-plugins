#!/usr/bin/env python3
"""
update-db-rules/scripts/sync_documents.py のテスト

sync_docdb.py を category=rules 固定で透過呼び出しするラッパーを検証する
（DES-057 §9.2: category 固定値・引数透過・stdout/stderr/exit code 透過・
--start / --status <job_id> の両操作の透過・利用者入力を要求しないこと）。

実行:
  python3 -m unittest discover -s tests -p 'test_sync_documents.py' -v
"""

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helpers = _load(
    REPO_ROOT / "tests" / "forge" / "wrapper_helpers.py",
    "_wrapper_helpers_update_db_rules_sync",
)

SKILL = "update-db-rules"
EXPECTED_CATEGORY = "rules"
EXPECTED_LOW_LEVEL = (
    REPO_ROOT / "plugins" / "forge" / "scripts" / "doc_backend" / "sync_docdb.py"
)


class TestSyncDocumentsWrapper(unittest.TestCase):
    """sync_documents.py が sync_docdb.py を category=rules で透過的に呼ぶ"""

    def setUp(self):
        self.wrapper = helpers.load_wrapper(
            helpers.wrapper_path(SKILL, "sync_documents.py"),
            "_sync_documents_update_db_rules",
        )

    def test_category_hardcoded(self):
        """CATEGORY 定数が rules にハードコードされている"""
        self.assertEqual(self.wrapper.CATEGORY, EXPECTED_CATEGORY)

    def test_low_level_path_points_sync_docdb(self):
        """LOW_LEVEL パスが scripts/doc_backend/sync_docdb.py を指す"""
        helpers.assert_low_level(self, self.wrapper, EXPECTED_LOW_LEVEL)

    def test_start_operation_transparent(self):
        """--start が category 前置で低レベル CLI へそのまま渡る"""
        rc, mock_run = helpers.invoke_with_mocked_run(
            self.wrapper, argv=["sync_documents.py", "--start"]
        )
        self.assertEqual(rc, 0)
        cmd = helpers.command_from_mock(mock_run)
        self.assertEqual(
            cmd,
            [
                sys.executable,
                str(self.wrapper.LOW_LEVEL),
                EXPECTED_CATEGORY,
                "--start",
            ],
        )
        helpers.assert_transparent_subprocess_kwargs(self, mock_run)

    def test_status_operation_transparent(self):
        """--status <job_id> が category 前置で低レベル CLI へそのまま渡る"""
        rc, mock_run = helpers.invoke_with_mocked_run(
            self.wrapper, argv=["sync_documents.py", "--status", "job-123"]
        )
        self.assertEqual(rc, 0)
        cmd = helpers.command_from_mock(mock_run)
        self.assertEqual(
            cmd,
            [
                sys.executable,
                str(self.wrapper.LOW_LEVEL),
                EXPECTED_CATEGORY,
                "--status",
                "job-123",
            ],
        )
        helpers.assert_transparent_subprocess_kwargs(self, mock_run)

    def test_no_user_input_required(self):
        """update wrapper は利用者入力（追加の位置引数）を要求しない"""
        rc, mock_run = helpers.invoke_with_mocked_run(
            self.wrapper, argv=["sync_documents.py"]
        )
        self.assertEqual(rc, 0)
        cmd = helpers.command_from_mock(mock_run)
        self.assertEqual(
            cmd, [sys.executable, str(self.wrapper.LOW_LEVEL), EXPECTED_CATEGORY]
        )

    def test_exit_code_transparent(self):
        """低レベル CLI の exit code をそのまま返す"""
        helpers.assert_exit_code_transparent(
            self, self.wrapper, lambda: ["sync_documents.py", "--start"]
        )

    def test_stdout_stderr_not_captured(self):
        """stdout / stderr を capture せず透過する"""
        _rc, mock_run = helpers.invoke_with_mocked_run(
            self.wrapper, argv=["sync_documents.py", "--start"]
        )
        helpers.assert_transparent_subprocess_kwargs(self, mock_run)


if __name__ == "__main__":
    unittest.main()
