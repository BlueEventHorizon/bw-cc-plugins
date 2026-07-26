#!/usr/bin/env python3
"""capture_syntax_baseline.py のテスト（DES-047 §3.2 テスト設計）。

実行:
  python3 -m unittest tests.forge.review.test_capture_syntax_baseline -v
"""

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "skills" / "review" / "scripts" / "capture_syntax_baseline.py"
)

_spec = importlib.util.spec_from_file_location("msg_review_capture_syntax_baseline", _SCRIPT_PATH)
baseline_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(baseline_mod)


def _completed(returncode, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class CaptureBaselineTest(unittest.TestCase):
    """capture_baseline(): dprint exit code の解釈と未インストール時の fail-safe。"""

    def test_dprint_not_available_returns_empty_baseline(self):
        with mock.patch.object(baseline_mod, "_dprint_available", return_value=False):
            result = baseline_mod.capture_baseline(["a.md", "b.py"])
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["tool"])
        self.assertEqual(result["files"]["a.md"], {"has_violations": False, "exit_code": None})
        self.assertEqual(result["files"]["b.py"], {"has_violations": False, "exit_code": None})

    def test_exit_code_20_is_violation(self):
        with mock.patch.object(baseline_mod, "_dprint_available", return_value=True), \
             mock.patch.object(baseline_mod, "_dprint_version", return_value="0.50.0"), \
             mock.patch("subprocess.run", return_value=_completed(20)):
            result = baseline_mod.capture_baseline(["a.md"])
        self.assertTrue(result["files"]["a.md"]["has_violations"])
        self.assertEqual(result["files"]["a.md"]["exit_code"], 20)

    def test_exit_code_0_is_no_violation(self):
        with mock.patch.object(baseline_mod, "_dprint_available", return_value=True), \
             mock.patch.object(baseline_mod, "_dprint_version", return_value="0.50.0"), \
             mock.patch("subprocess.run", return_value=_completed(0)):
            result = baseline_mod.capture_baseline(["a.md"])
        self.assertFalse(result["files"]["a.md"]["has_violations"])
        self.assertEqual(result["files"]["a.md"]["exit_code"], 0)

    def test_exit_code_14_is_out_of_scope_not_violation(self):
        """dprint.jsonc の includes 対象外 (exit 14) は違反ではない。"""
        with mock.patch.object(baseline_mod, "_dprint_available", return_value=True), \
             mock.patch.object(baseline_mod, "_dprint_version", return_value="0.50.0"), \
             mock.patch("subprocess.run", return_value=_completed(14)):
            result = baseline_mod.capture_baseline(["a.py"])
        self.assertFalse(result["files"]["a.py"]["has_violations"])
        self.assertEqual(result["files"]["a.py"]["exit_code"], 14)

    def test_unexpected_exit_code_treated_as_no_violation_fail_safe(self):
        with mock.patch.object(baseline_mod, "_dprint_available", return_value=True), \
             mock.patch.object(baseline_mod, "_dprint_version", return_value="0.50.0"), \
             mock.patch("subprocess.run", return_value=_completed(1)):
            result = baseline_mod.capture_baseline(["a.md"])
        self.assertFalse(result["files"]["a.md"]["has_violations"])
        self.assertEqual(result["files"]["a.md"]["exit_code"], 1)

    def test_timeout_treated_as_no_violation(self):
        with mock.patch.object(baseline_mod, "_dprint_available", return_value=True), \
             mock.patch.object(baseline_mod, "_dprint_version", return_value="0.50.0"), \
             mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="dprint", timeout=30)):
            result = baseline_mod.capture_baseline(["a.md"])
        self.assertFalse(result["files"]["a.md"]["has_violations"])
        self.assertIsNone(result["files"]["a.md"]["exit_code"])


class MainTest(unittest.TestCase):
    """main(): --files-json 読み込み・単一 JSON 出力。"""

    def test_cli_outputs_single_json(self):
        """dprint の有無に関わらず、well-formed な単一 JSON が返ること（存在確認のみ）。"""
        result = subprocess.run(
            ["python3", str(_SCRIPT_PATH), "--files-json", '["nonexistent_a1b2c3.md"]'],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertIn("nonexistent_a1b2c3.md", payload["files"])

    def test_cli_rejects_invalid_json(self):
        result = subprocess.run(
            ["python3", str(_SCRIPT_PATH), "--files-json", "not-json"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "error")


if __name__ == "__main__":
    unittest.main()
