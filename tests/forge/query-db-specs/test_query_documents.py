#!/usr/bin/env python3
"""
query-db-specs/scripts/query_documents.py のテスト

query_docdb.py を category=specs 固定で透過呼び出しするラッパーを検証する
（DES-057 §9.2: category 固定値・位置引数の透過・stdout/stderr/exit code 透過・
query wrapper が task を 1 つの位置引数として渡すこと・
exit 30 index_missing を含む全 exit code の透過）。

実行:
  python3 -m unittest discover -s tests -p 'test_query_documents.py' -v
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
    "_wrapper_helpers_query_db_specs_query",
)

SKILL = "query-db-specs"
EXPECTED_CATEGORY = "specs"
EXPECTED_LOW_LEVEL = (
    REPO_ROOT / "plugins" / "forge" / "scripts" / "doc_backend" / "query_docdb.py"
)


class TestQueryDocumentsWrapper(unittest.TestCase):
    """query_documents.py が query_docdb.py を category=specs で透過的に呼ぶ"""

    def setUp(self):
        self.wrapper = helpers.load_wrapper(
            helpers.wrapper_path(SKILL, "query_documents.py"),
            "_query_documents_query_db_specs",
        )

    def test_category_hardcoded(self):
        """CATEGORY 定数が specs にハードコードされている"""
        self.assertEqual(self.wrapper.CATEGORY, EXPECTED_CATEGORY)

    def test_low_level_path_points_query_docdb(self):
        """LOW_LEVEL パスが scripts/doc_backend/query_docdb.py を指す"""
        helpers.assert_low_level(self, self.wrapper, EXPECTED_LOW_LEVEL)

    def test_task_passed_as_single_positional(self):
        """空白を含む task が 1 つの位置引数として category 前置で渡る"""
        task = "review 手順のルールを探す"
        rc, mock_run = helpers.invoke_with_mocked_run(
            self.wrapper, argv=["query_documents.py", task]
        )
        self.assertEqual(rc, 0)
        cmd = helpers.command_from_mock(mock_run)
        self.assertEqual(
            cmd,
            [
                sys.executable,
                str(self.wrapper.LOW_LEVEL),
                EXPECTED_CATEGORY,
                task,
            ],
        )
        helpers.assert_transparent_subprocess_kwargs(self, mock_run)

    def test_exit_code_transparent(self):
        """低レベル CLI の exit code をそのまま返す"""
        helpers.assert_exit_code_transparent(
            self, self.wrapper, lambda: ["query_documents.py", "task"]
        )

    def test_contract_exit_codes_transparent(self):
        """契約 exit code（10 unavailable / 20 operation_error / 30 index_missing）を透過する"""
        for code in (10, 20, 30):
            with self.subTest(code=code):
                rc, _mock_run = helpers.invoke_with_mocked_run(
                    self.wrapper,
                    argv=["query_documents.py", "task"],
                    returncode=code,
                )
                self.assertEqual(rc, code)

    def test_stdout_stderr_not_captured(self):
        """stdout / stderr を capture せず透過する"""
        _rc, mock_run = helpers.invoke_with_mocked_run(
            self.wrapper, argv=["query_documents.py", "task"]
        )
        helpers.assert_transparent_subprocess_kwargs(self, mock_run)

    def test_rejects_missing_or_extra_task_without_calling_low_level(self):
        """検索タスクは空でない 1 位置引数だけを公開する"""
        for argv in (
            ["query_documents.py"],
            ["query_documents.py", ""],
            ["query_documents.py", "task", "extra"],
            ["query_documents.py", "--mode", "all"],
        ):
            with self.subTest(argv=argv):
                rc, mock_run = helpers.invoke_with_mocked_run(
                    self.wrapper, argv=argv
                )
                self.assertEqual(rc, 20)
                mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
