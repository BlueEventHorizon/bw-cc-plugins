#!/usr/bin/env python3
"""advance_round.py の契約テスト。

- 所見と評価がどちらも正常に封緘されていれば、次のラウンドの置き場だけを作る
- どちらかが正常でなければ失敗し、理由をすべて errors に入れ、何も作らない
- 次のラウンドの置き場が既にあれば失敗し、中身を上書きしない
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "plugins" / "forge" / "scripts" / "review" / "advance_round.py"


def run(*args):
    completed = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    payload = json.loads(completed.stdout) if completed.stdout.strip() else None
    return completed.returncode, payload


class AdvanceRoundTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.review = self.root / ".temp" / "review" / "rid"
        self.round = self.review / "1"
        self.round.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, array, **extra):
        (self.round / name).write_text(json.dumps({array: [], **extra}), encoding="utf-8")

    def _seal_both(self):
        self._write("review_result.json", "findings", exit="0")
        self._write("evaluate_result.json", "evaluations", exit="0")

    def _advance(self, number="1"):
        return run(str(self.root), "rid", number)

    def _names(self):
        return sorted(p.name for p in self.review.iterdir())

    def test_creates_next_round_only(self):
        self._seal_both()
        self.assertEqual(self._advance(), (0, {"round_number": 2}))
        self.assertEqual(self._names(), ["1", "2"])
        self.assertEqual(list((self.review / "2").iterdir()), [])

    def test_fails_when_next_round_exists_and_keeps_it(self):
        self._seal_both()
        (self.review / "2").mkdir()
        (self.review / "2" / "keep.txt").write_text("x", encoding="utf-8")
        code, payload = self._advance()
        self.assertEqual(code, 1)
        self.assertIn("既にあります", payload["errors"][0])
        self.assertEqual((self.review / "2" / "keep.txt").read_text(encoding="utf-8"), "x")

    def test_fails_when_evaluation_missing(self):
        self._write("review_result.json", "findings", exit="0")
        code, payload = self._advance()
        self.assertEqual(code, 1)
        self.assertIn("評価の結果がありません", payload["errors"][0])
        self.assertEqual(self._names(), ["1"])

    def test_fails_when_findings_missing(self):
        self._write("evaluate_result.json", "evaluations", exit="0")
        code, payload = self._advance()
        self.assertEqual(code, 1)
        self.assertIn("所見の結果がありません", payload["errors"][0])
        self.assertEqual(self._names(), ["1"])

    def test_fails_when_evaluation_not_sealed(self):
        self._write("review_result.json", "findings", exit="0")
        self._write("evaluate_result.json", "evaluations")
        code, payload = self._advance()
        self.assertEqual(code, 1)
        self.assertIn("封緘されていません", payload["errors"][0])
        self.assertEqual(self._names(), ["1"])

    def test_fails_when_findings_error_exit(self):
        self._write("review_result.json", "findings", exit="target_unreadable")
        self._write("evaluate_result.json", "evaluations", exit="0")
        code, payload = self._advance()
        self.assertEqual(code, 1)
        self.assertIn("エラーで終えています", payload["errors"][0])
        self.assertEqual(self._names(), ["1"])

    def test_reports_both_reasons(self):
        code, payload = self._advance()
        self.assertEqual(code, 1)
        self.assertEqual(len(payload["errors"]), 2)

    def test_fails_when_round_missing(self):
        code, payload = self._advance("5")
        self.assertEqual(code, 1)
        self.assertIn("ラウンドの置き場がありません", payload["errors"][0])
        self.assertEqual(self._names(), ["1"])

    def test_does_not_create_request(self):
        self._seal_both()
        self._advance()
        self.assertFalse((self.review / "review_request.json").exists())


if __name__ == "__main__":
    unittest.main()
