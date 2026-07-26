#!/usr/bin/env python3
"""
update-version/scripts/update_optional_filtered.py のテスト

`update_version_files.py {file} {cur} {new} --filter {filter} --optional` を
呼び出し、成功時は stdout を対象ファイルへ書き戻す writer ラッパーを検証する
(Issue #139)。

実行:
  python3 -m unittest tests.forge.update-version.test_update_optional_filtered -v
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
                / 'update-version' / 'scripts' / 'update_optional_filtered.py')
EXPECTED_LOW_LEVEL = (REPO_ROOT / 'plugins' / 'forge' / 'skills'
                      / 'update-version' / 'scripts' / 'update_version_files.py')


def _load_wrapper():
    spec = importlib.util.spec_from_file_location(
        "_update_optional_filtered", WRAPPER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestUpdateOptionalFilteredWrapper(unittest.TestCase):

    def setUp(self):
        self.wrapper = _load_wrapper()

    def test_low_level_path(self):
        self.assertEqual(self.wrapper.LOW_LEVEL.resolve(),
                         EXPECTED_LOW_LEVEL.resolve())

    def test_filter_and_optional_hardcoded(self):
        """--filter と --optional の両方がある"""
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr="")
            with mock.patch.object(sys, "argv",
                                   ["w", "f.json", "1.0.0", "1.0.1", "forge"]):
                self.wrapper.main()
        cmd = mock_run.call_args.args[0]
        self.assertIn("--filter", cmd)
        idx = cmd.index("--filter")
        self.assertEqual(cmd[idx + 1], "forge")
        self.assertIn("--optional", cmd)

    def test_captures_stdout(self):
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr="")
            with mock.patch.object(sys, "argv",
                                   ["w", "f", "1.0.0", "1.0.1", "pat"]):
                self.wrapper.main()
        kw = mock_run.call_args.kwargs
        self.assertTrue(kw.get("capture_output"))
        self.assertTrue(kw.get("text"))

    def test_exit_code_transparent(self):
        for code in (0, 1, 42):
            with self.subTest(code=code):
                with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
                    mock_run.return_value = subprocess.CompletedProcess(
                        args=[], returncode=code, stdout="", stderr="")
                    with mock.patch.object(sys, "argv",
                                           ["w", "f", "1.0.0", "1.0.1", "pat"]):
                        rc = self.wrapper.main()
                self.assertEqual(rc, code)

    def test_writes_back_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "f.json"
            target.write_text('{"version": "0.1.0"}\n')
            updated_text = '{"version": "0.1.1"}\n'
            with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0,
                    stdout=updated_text,
                    stderr='{"status": "ok"}')
                with mock.patch.object(sys, "argv",
                                       ["w", str(target), "0.1.0", "0.1.1", "pat"]):
                    rc = self.wrapper.main()
            self.assertEqual(rc, 0)
            self.assertEqual(target.read_text(), updated_text)

    def test_skipped_does_not_write(self):
        """optional skipped (rc=0 + stdout 空) は書き戻さない"""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "f.json"
            original = '{"name": "other"}\n'
            target.write_text(original)
            with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="",
                    stderr='{"status": "skipped"}')
                with mock.patch.object(sys, "argv",
                                       ["w", str(target), "0.1.0", "0.1.1", "pat"]):
                    rc = self.wrapper.main()
            self.assertEqual(rc, 0)
            self.assertEqual(target.read_text(), original)

    def test_error_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "f.json"
            original = '{"version": "0.1.0"}\n'
            target.write_text(original)
            with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=1,
                    stdout='partial',
                    stderr='{"status": "error"}')
                with mock.patch.object(sys, "argv",
                                       ["w", str(target), "0.1.0", "0.1.1", "pat"]):
                    rc = self.wrapper.main()
            self.assertEqual(rc, 1)
            self.assertEqual(target.read_text(), original)


if __name__ == "__main__":
    unittest.main()
