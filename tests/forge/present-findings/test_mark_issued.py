#!/usr/bin/env python3
"""mark_issued.py のテスト。

実行:
    python3 -m unittest tests.forge.present-findings.test_mark_issued -v
"""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
WRAPPER_PATH = (
    REPO_ROOT / "plugins" / "forge" / "skills" / "present-findings"
    / "scripts" / "mark_issued.py"
)
EXPECTED_LOW_LEVEL = (
    REPO_ROOT / "plugins" / "forge" / "scripts" / "session" / "update_plan.py"
)


def _load_wrapper():
    spec = importlib.util.spec_from_file_location("_mark_issued", WRAPPER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMarkIssuedWrapper(unittest.TestCase):
    def setUp(self):
        self.wrapper = _load_wrapper()

    def test_low_level_path_points_update_plan(self):
        self.assertEqual(self.wrapper.LOW_LEVEL.resolve(), EXPECTED_LOW_LEVEL.resolve())

    def test_constructs_correct_flags(self):
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run, \
             mock.patch.object(self.wrapper.sys, "argv",
                               ["mark_issued.py", ".claude/.temp/s", "7", "42"]):
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            self.wrapper.main()
            args = mock_run.call_args.args[0]
            self.assertIn(".claude/.temp/s", args)
            self.assertIn("--id", args)
            self.assertIn("7", args)
            self.assertIn("--status", args)
            self.assertIn("skipped", args)
            self.assertIn("--recommendation", args)
            self.assertIn("create_issue", args)
            self.assertIn("--skip-reason", args)
            self.assertIn("Issue 化済み: #42", args)

    def test_returns_low_level_exit_code(self):
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run, \
             mock.patch.object(self.wrapper.sys, "argv",
                               ["mark_issued.py", "x", "1", "1"]):
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=3)
            self.assertEqual(self.wrapper.main(), 3)

    def test_rejects_wrong_arg_count(self):
        with mock.patch.object(self.wrapper.sys, "argv", ["mark_issued.py", "only_one"]):
            self.assertEqual(self.wrapper.main(), 2)


if __name__ == "__main__":
    unittest.main()
