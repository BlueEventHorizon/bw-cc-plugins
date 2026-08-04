#!/usr/bin/env python3
"""
update-db-specs/scripts/prepare_advisor_index.py のテスト

低レベル CLI prepare_advisor_index.py を category=specs 固定で透過呼び出しする
ラッパーを検証する（DES-057 §9.2: category 固定値・引数透過・
stdout/stderr/exit code 透過・利用者入力を要求しないこと）。

実行:
  python3 -m unittest discover -s tests -p 'test_prepare_advisor_index.py' -v
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
    "_wrapper_helpers_update_db_specs_prepare",
)

SKILL = "update-db-specs"
EXPECTED_CATEGORY = "specs"
EXPECTED_LOW_LEVEL = (
    REPO_ROOT
    / "plugins"
    / "forge"
    / "scripts"
    / "doc_backend"
    / "prepare_advisor_index.py"
)


class TestPrepareAdvisorIndexWrapper(unittest.TestCase):
    """prepare_advisor_index.py が同名の低レベル CLI を category=specs で透過的に呼ぶ"""

    def setUp(self):
        self.wrapper = helpers.load_wrapper(
            helpers.wrapper_path(SKILL, "prepare_advisor_index.py"),
            "_prepare_advisor_index_update_db_specs",
        )

    def test_category_hardcoded(self):
        """CATEGORY 定数が specs にハードコードされている"""
        self.assertEqual(self.wrapper.CATEGORY, EXPECTED_CATEGORY)

    def test_low_level_path_points_prepare_advisor_index(self):
        """LOW_LEVEL パスが scripts/doc_backend/prepare_advisor_index.py を指す"""
        helpers.assert_low_level(self, self.wrapper, EXPECTED_LOW_LEVEL)

    def test_no_user_input_required(self):
        """update wrapper は利用者入力（追加の位置引数）を要求しない"""
        rc, mock_run = helpers.invoke_with_mocked_run(
            self.wrapper, argv=["prepare_advisor_index.py"]
        )
        self.assertEqual(rc, 0)
        cmd = helpers.command_from_mock(mock_run)
        self.assertEqual(
            cmd, [sys.executable, str(self.wrapper.LOW_LEVEL), EXPECTED_CATEGORY]
        )
        helpers.assert_transparent_subprocess_kwargs(self, mock_run)

    def test_extra_args_transparent(self):
        """残りの引数が category 前置で低レベル CLI へそのまま渡る"""
        rc, mock_run = helpers.invoke_with_mocked_run(
            self.wrapper,
            argv=["prepare_advisor_index.py", "--project-root", "/tmp/project"],
        )
        self.assertEqual(rc, 0)
        cmd = helpers.command_from_mock(mock_run)
        self.assertEqual(
            cmd,
            [
                sys.executable,
                str(self.wrapper.LOW_LEVEL),
                EXPECTED_CATEGORY,
                "--project-root",
                "/tmp/project",
            ],
        )
        helpers.assert_transparent_subprocess_kwargs(self, mock_run)

    def test_exit_code_transparent(self):
        """低レベル CLI の exit code をそのまま返す"""
        helpers.assert_exit_code_transparent(
            self, self.wrapper, lambda: ["prepare_advisor_index.py"]
        )


if __name__ == "__main__":
    unittest.main()
