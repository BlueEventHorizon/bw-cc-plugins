#!/usr/bin/env python3
"""
finalize_review.py のテスト（ADR-066 §2.4 / ADR-065 の終了通知）

本テストの主眼は **終端経路の網羅** である。終了通知の発行漏れは、資源を
持たないバックエンド（msg-review）では何も起きず、資源を自前で持つ
バックエンドを接続して初めてリークとして現れる。露見が遅れるため、
「どの終端経路でも通知が出る」ことをテストで固定する。

実行:
  python3 -m unittest tests.forge.review.test_finalize_review -v
"""

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "skills" / "review" / "scripts" / "finalize_review.py"
)

_spec = importlib.util.spec_from_file_location("review_finalize_review", _SCRIPT_PATH)
finalize_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(finalize_mod)

_REVIEW_ID = "3823ebe9e14d4e80"
_BACKEND = "msg-review"


def _decide(judgment, confirmed_fix_count=None):
    return finalize_mod.decide(judgment, _REVIEW_ID, _BACKEND, confirmed_fix_count)


class TerminalPathCoverageTest(unittest.TestCase):
    """全終端経路で終了通知が発行されること（本テストファイルの主眼）。"""

    # (judgment, confirmed_fix_count, 期待する path)
    TERMINAL_CASES = [
        ("approved", None, "approved"),
        ("findings", 0, "halted_with_open_findings"),
        ("failure", None, "failure"),
        ("interrupted", None, "interrupted"),
    ]

    def test_every_terminal_path_requires_notification(self):
        """承認・打ち切り・失敗確定・中止のいずれでも notify_backend が返る。"""
        for judgment, count, expected_path in self.TERMINAL_CASES:
            with self.subTest(judgment=judgment, confirmed_fix_count=count):
                result = _decide(judgment, count)
                self.assertTrue(result["terminal"])
                self.assertEqual(result["path"], expected_path)
                self.assertEqual(
                    result["notify_backend"],
                    {"backend": _BACKEND, "review_id": _REVIEW_ID},
                )

    def test_terminal_cases_cover_all_judgments(self):
        """判定値を追加したらテストの網羅も追随させる（取りこぼし防止）。

        `findings` は件数で終端かどうかが変わるため両方をここで数える。
        """
        covered = {judgment for judgment, _, _ in self.TERMINAL_CASES}
        declared = set(finalize_mod.TERMINAL_PATHS) | {"findings"}
        self.assertEqual(covered, declared)


class ContinuationTest(unittest.TestCase):
    """修正すべき所見が残っている間は終端にしない。"""

    def test_findings_with_confirmed_fixes_continues(self):
        result = _decide("findings", 1)
        self.assertFalse(result["terminal"])
        self.assertEqual(result["path"], "continue")
        self.assertIsNone(result["notify_backend"])

    def test_findings_with_many_confirmed_fixes_continues(self):
        result = _decide("findings", 7)
        self.assertFalse(result["terminal"])
        self.assertIsNone(result["notify_backend"])

    def test_findings_with_zero_confirmed_fixes_is_not_approved(self):
        """打ち切りは承認と別経路である（要約報告で混同させないため）。"""
        halted = _decide("findings", 0)
        approved = _decide("approved")
        self.assertNotEqual(halted["path"], approved["path"])


class FailClosedTest(unittest.TestCase):
    """判定できない入力を既定値で埋めない。"""

    def test_findings_without_count_raises(self):
        """件数の渡し忘れが「終端」「継続」のどちらかへ黙って倒れないこと。"""
        with self.assertRaises(ValueError):
            _decide("findings", None)

    def test_negative_count_raises(self):
        with self.assertRaises(ValueError):
            _decide("findings", -1)

    def test_count_is_ignored_for_non_findings_judgments(self):
        """findings 以外では件数の有無が終端判定を変えない。"""
        for judgment in ("approved", "failure", "interrupted"):
            with self.subTest(judgment=judgment):
                self.assertEqual(_decide(judgment, None), _decide(judgment, 3))


class NotificationTargetTest(unittest.TestCase):
    """通知の宛先が入力どおりに載ること。"""

    def test_notification_carries_review_id_and_backend(self):
        result = finalize_mod.decide("approved", "other-review", "codex-appserver", None)
        self.assertEqual(
            result["notify_backend"],
            {"backend": "codex-appserver", "review_id": "other-review"},
        )


class CliTest(unittest.TestCase):
    """CLI としての入出力。"""

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
        )

    def test_cli_outputs_json_for_terminal_judgment(self):
        proc = self._run("--judgment", "approved", "--review-id", _REVIEW_ID, "--backend", _BACKEND)
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["terminal"])
        self.assertEqual(payload["notify_backend"]["review_id"], _REVIEW_ID)

    def test_cli_reports_error_for_findings_without_count(self):
        proc = self._run("--judgment", "findings", "--review-id", _REVIEW_ID, "--backend", _BACKEND)
        self.assertEqual(proc.returncode, 1)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "error")

    def test_cli_rejects_unknown_judgment(self):
        proc = self._run("--judgment", "cancelled", "--review-id", _REVIEW_ID, "--backend", _BACKEND)
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
