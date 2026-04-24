#!/usr/bin/env python3
"""
start-uxui-design/scripts/init_session.py のテスト

session_manager.py init を透過的に呼び出すラッパーを検証する。
位置引数 {feature} {mode} {output_dir} → --feature / --mode / --output-dir への
マッピング、ハードコード --skill、exit code 透過を確認。
"""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
WRAPPER_PATH = (REPO_ROOT / 'plugins' / 'forge' / 'skills'
                / 'start-uxui-design' / 'scripts' / 'init_session.py')
EXPECTED_SKILL = "start-uxui-design"
EXPECTED_LOW_LEVEL = (REPO_ROOT / 'plugins' / 'forge' / 'scripts'
                      / 'session_manager.py')


def _load_wrapper():
    spec = importlib.util.spec_from_file_location(
        "_init_session_start_uxui_design", WRAPPER_PATH
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
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            argv = ["init_session.py", "my_feature", "ios", "/tmp/out"]
            with mock.patch.object(sys, "argv", argv):
                rc = self.wrapper.main()
        self.assertEqual(rc, 0)
        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(Path(cmd[1]).resolve(), EXPECTED_LOW_LEVEL.resolve())
        self.assertEqual(cmd[2], "init")
        self.assertEqual(cmd[cmd.index("--skill") + 1], EXPECTED_SKILL)
        self.assertEqual(cmd[cmd.index("--feature") + 1], "my_feature")
        self.assertEqual(cmd[cmd.index("--mode") + 1], "ios")
        self.assertEqual(cmd[cmd.index("--output-dir") + 1], "/tmp/out")
        self.assertFalse(mock_run.call_args.kwargs.get("check", True))

    def test_exit_code_transparent(self):
        for code in (0, 1, 2, 42):
            with self.subTest(code=code):
                with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
                    mock_run.return_value = subprocess.CompletedProcess(
                        args=[], returncode=code)
                    argv = ["init_session.py", "f", "ios", "/tmp/out"]
                    with mock.patch.object(sys, "argv", argv):
                        rc = self.wrapper.main()
                self.assertEqual(rc, code)

    def test_stdout_stderr_not_captured_by_wrapper(self):
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            argv = ["init_session.py", "f", "ios", "/tmp/out"]
            with mock.patch.object(sys, "argv", argv):
                self.wrapper.main()
        kw = mock_run.call_args.kwargs
        self.assertNotIn("capture_output", kw)
        self.assertNotIn("stdout", kw)
        self.assertNotIn("stderr", kw)


if __name__ == "__main__":
    unittest.main()
