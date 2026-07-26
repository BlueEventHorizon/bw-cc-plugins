#!/usr/bin/env python3
"""
update-version/scripts/update_main_version.py のテスト

`update_version_files.py {file} {cur} {new} --version-path {version_path}` を
呼び出し、成功時は stdout を対象ファイルへ書き戻す writer ラッパーを検証する
(Issue #139)。

実行:
  python3 -m unittest tests.forge.update-version.test_update_main_version -v
"""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
WRAPPER_PATH = (REPO_ROOT / 'plugins' / 'forge' / 'skills'
                / 'update-version' / 'scripts' / 'update_main_version.py')
EXPECTED_LOW_LEVEL = (REPO_ROOT / 'plugins' / 'forge' / 'skills'
                      / 'update-version' / 'scripts' / 'update_version_files.py')


def _load_wrapper():
    spec = importlib.util.spec_from_file_location(
        "_update_main_version", WRAPPER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestUpdateMainVersionWrapper(unittest.TestCase):
    """update_main_version.py が update_version_files.py --version-path を
    呼び出し、成功時は stdout を対象ファイルへ書き戻すことを検証"""

    def setUp(self):
        self.wrapper = _load_wrapper()

    def test_low_level_path_points_update_version_files(self):
        """LOW_LEVEL パスが update_version_files.py を指す"""
        self.assertEqual(self.wrapper.LOW_LEVEL.resolve(),
                         EXPECTED_LOW_LEVEL.resolve())

    def test_subprocess_called_with_version_path(self):
        """subprocess.run が --version-path 付きで呼ばれる"""
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr="")
            argv = ["update_main_version.py",
                    "plugin.json", "1.0.0", "1.0.1", "$.version"]
            with mock.patch.object(sys, "argv", argv):
                rc = self.wrapper.main()
        self.assertEqual(rc, 0)
        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(Path(cmd[1]).resolve(), EXPECTED_LOW_LEVEL.resolve())
        self.assertEqual(cmd[2], "plugin.json")
        self.assertEqual(cmd[3], "1.0.0")
        self.assertEqual(cmd[4], "1.0.1")
        self.assertIn("--version-path", cmd)
        idx = cmd.index("--version-path")
        self.assertEqual(cmd[idx + 1], "$.version")
        self.assertFalse(mock_run.call_args.kwargs.get("check", True))

    def test_captures_stdout(self):
        """書き戻しのため stdout を capture する (Issue #139 fix)"""
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr="")
            with mock.patch.object(sys, "argv",
                                   ["w", "f", "1.0.0", "1.0.1", "$.v"]):
                self.wrapper.main()
        kw = mock_run.call_args.kwargs
        self.assertTrue(kw.get("capture_output"))
        self.assertTrue(kw.get("text"))

    def test_exit_code_transparent_zero(self):
        """低レベル return 0 → ラッパー return 0"""
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr="")
            with mock.patch.object(sys, "argv",
                                   ["w", "f", "1.0.0", "1.0.1", "$.v"]):
                rc = self.wrapper.main()
        self.assertEqual(rc, 0)

    def test_exit_code_transparent_nonzero(self):
        """低レベル return 非0 → ラッパー同じ非0"""
        for code in (1, 2, 42):
            with self.subTest(code=code):
                with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
                    mock_run.return_value = subprocess.CompletedProcess(
                        args=[], returncode=code, stdout="", stderr="")
                    with mock.patch.object(sys, "argv",
                                           ["w", "f", "1.0.0", "1.0.1", "$.v"]):
                        rc = self.wrapper.main()
                self.assertEqual(rc, code)

    def test_writes_back_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "plugin.json"
            target.write_text('{"version": "0.1.0"}\n')
            updated_text = '{"version": "0.1.1"}\n'
            with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0,
                    stdout=updated_text,
                    stderr='{"status": "ok"}')
                with mock.patch.object(sys, "argv",
                                       ["w", str(target), "0.1.0", "0.1.1", "version"]):
                    rc = self.wrapper.main()
            self.assertEqual(rc, 0)
            self.assertEqual(target.read_text(), updated_text)

    def test_error_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "plugin.json"
            original = '{"version": "0.1.0"}\n'
            target.write_text(original)
            with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=1,
                    stdout='partial',
                    stderr='{"status": "error"}')
                with mock.patch.object(sys, "argv",
                                       ["w", str(target), "0.1.0", "0.1.1", "version"]):
                    rc = self.wrapper.main()
            self.assertEqual(rc, 1)
            self.assertEqual(target.read_text(), original)


if __name__ == "__main__":
    unittest.main()
