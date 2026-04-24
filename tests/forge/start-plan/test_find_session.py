#!/usr/bin/env python3
"""
start-plan/scripts/find_session.py のテスト

session_manager.py find --skill start-plan を透過的に呼び出すラッパーを検証する。

実行:
  python3 -m unittest tests.forge.start-plan.test_find_session -v
  # もしくは discover 経由:
  python3 -m unittest discover -s tests -p 'test_*.py'
"""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
WRAPPER_PATH = (REPO_ROOT / 'plugins' / 'forge' / 'skills'
                / 'start-plan' / 'scripts' / 'find_session.py')
EXPECTED_SKILL = "start-plan"
EXPECTED_LOW_LEVEL = (REPO_ROOT / 'plugins' / 'forge' / 'scripts'
                      / 'session_manager.py')


def _load_wrapper():
    """ハイフン付きディレクトリ配下のラッパーモジュールを importlib で読み込む。"""
    spec = importlib.util.spec_from_file_location(
        "_find_session_start_plan", WRAPPER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestFindSessionWrapper(unittest.TestCase):
    """find_session.py が session_manager.py find を透過的に呼ぶことを検証"""

    def setUp(self):
        self.wrapper = _load_wrapper()

    def test_skill_hardcoded(self):
        """SKILL 定数が start-plan にハードコードされている"""
        self.assertEqual(self.wrapper.SKILL, EXPECTED_SKILL)

    def test_low_level_path_points_session_manager(self):
        """LOW_LEVEL パスが plugins/forge/scripts/session_manager.py を指す"""
        self.assertEqual(self.wrapper.LOW_LEVEL.resolve(),
                         EXPECTED_LOW_LEVEL.resolve())

    def test_subprocess_called_with_find_skill(self):
        """subprocess.run が find --skill {skill} で呼ばれる"""
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            with mock.patch.object(sys, "argv", ["find_session.py"]):
                rc = self.wrapper.main()
        self.assertEqual(rc, 0)
        self.assertEqual(mock_run.call_count, 1)
        call_args = mock_run.call_args
        cmd = call_args.args[0] if call_args.args else call_args.kwargs["args"]
        # cmd = [python, LOW_LEVEL, "find", "--skill", "start-plan"]
        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(Path(cmd[1]).resolve(), EXPECTED_LOW_LEVEL.resolve())
        self.assertEqual(cmd[2], "find")
        self.assertIn("--skill", cmd)
        skill_idx = cmd.index("--skill")
        self.assertEqual(cmd[skill_idx + 1], EXPECTED_SKILL)
        # check=False を指定している（exit code 透過のため）
        self.assertFalse(call_args.kwargs.get("check", True))

    def test_exit_code_transparent_zero(self):
        """低レベル return 0 → ラッパー return 0"""
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            with mock.patch.object(sys, "argv", ["find_session.py"]):
                rc = self.wrapper.main()
        self.assertEqual(rc, 0)

    def test_exit_code_transparent_nonzero(self):
        """低レベル return 非0 → ラッパー同じ非0"""
        for code in (1, 2, 42):
            with self.subTest(code=code):
                with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
                    mock_run.return_value = subprocess.CompletedProcess(
                        args=[], returncode=code)
                    with mock.patch.object(sys, "argv", ["find_session.py"]):
                        rc = self.wrapper.main()
                self.assertEqual(rc, code)

    def test_extra_argv_passed_through(self):
        """ラッパーに渡された追加引数は低レベルに透過される"""
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            with mock.patch.object(sys, "argv", ["find_session.py", "--extra", "v"]):
                self.wrapper.main()
        cmd = mock_run.call_args.args[0]
        self.assertIn("--extra", cmd)
        self.assertIn("v", cmd)

    def test_stdout_stderr_not_captured_by_wrapper(self):
        """ラッパーは stdout/stderr を capture しない（透過のため）"""
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            with mock.patch.object(sys, "argv", ["find_session.py"]):
                self.wrapper.main()
        kw = mock_run.call_args.kwargs
        # capture_output / stdout / stderr は指定されない（透過される）
        self.assertNotIn("capture_output", kw)
        self.assertNotIn("stdout", kw)
        self.assertNotIn("stderr", kw)


if __name__ == "__main__":
    unittest.main()
