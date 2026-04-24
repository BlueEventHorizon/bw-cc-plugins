#!/usr/bin/env python3
"""
review/scripts/init_session.py のテスト

session_manager.py init を透過的に呼び出すラッパーを検証する。
位置引数 {review_type} {engine} {auto_count} →
--review-type / --engine / --auto-count へのマッピング、
--current-cycle 0 のハードコード、ハードコード --skill、
exit code 透過を確認。
"""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
WRAPPER_PATH = (REPO_ROOT / 'plugins' / 'forge' / 'skills'
                / 'review' / 'scripts' / 'init_session.py')
EXPECTED_SKILL = "review"
EXPECTED_LOW_LEVEL = (REPO_ROOT / 'plugins' / 'forge' / 'scripts'
                      / 'session_manager.py')


def _load_wrapper():
    spec = importlib.util.spec_from_file_location(
        "_init_session_review", WRAPPER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestInitSessionWrapper(unittest.TestCase):
    def setUp(self):
        self.wrapper = _load_wrapper()

    def test_skill_hardcoded(self):
        self.assertEqual(self.wrapper.SKILL, EXPECTED_SKILL)

    def test_low_level_path_points_session_manager(self):
        self.assertEqual(self.wrapper.LOW_LEVEL.resolve(),
                         EXPECTED_LOW_LEVEL.resolve())

    def test_positional_args_mapped_to_flags(self):
        """位置引数 {review_type} {engine} {auto_count} が正しく flag に変換される"""
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            argv = ["init_session.py", "code", "codex", "3"]
            with mock.patch.object(sys, "argv", argv):
                rc = self.wrapper.main()
        self.assertEqual(rc, 0)
        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(Path(cmd[1]).resolve(), EXPECTED_LOW_LEVEL.resolve())
        self.assertEqual(cmd[2], "init")
        self.assertEqual(cmd[cmd.index("--skill") + 1], EXPECTED_SKILL)
        self.assertIn("--review-type", cmd)
        self.assertEqual(cmd[cmd.index("--review-type") + 1], "code")
        self.assertIn("--engine", cmd)
        self.assertEqual(cmd[cmd.index("--engine") + 1], "codex")
        self.assertIn("--auto-count", cmd)
        self.assertEqual(cmd[cmd.index("--auto-count") + 1], "3")
        self.assertFalse(mock_run.call_args.kwargs.get("check", True))

    def test_current_cycle_hardcoded_zero(self):
        """review ラッパーは --current-cycle 0 を内部でハードコードする"""
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            argv = ["init_session.py", "code", "codex", "3"]
            with mock.patch.object(sys, "argv", argv):
                self.wrapper.main()
        cmd = mock_run.call_args.args[0]
        self.assertIn("--current-cycle", cmd)
        self.assertEqual(cmd[cmd.index("--current-cycle") + 1], "0")

    def test_exit_code_transparent(self):
        for code in (0, 1, 2, 42):
            with self.subTest(code=code):
                with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
                    mock_run.return_value = subprocess.CompletedProcess(
                        args=[], returncode=code)
                    argv = ["init_session.py", "code", "codex", "3"]
                    with mock.patch.object(sys, "argv", argv):
                        rc = self.wrapper.main()
                self.assertEqual(rc, code)

    def test_stdout_stderr_not_captured_by_wrapper(self):
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            argv = ["init_session.py", "code", "codex", "3"]
            with mock.patch.object(sys, "argv", argv):
                self.wrapper.main()
        kw = mock_run.call_args.kwargs
        self.assertNotIn("capture_output", kw)
        self.assertNotIn("stdout", kw)
        self.assertNotIn("stderr", kw)


if __name__ == "__main__":
    unittest.main()
