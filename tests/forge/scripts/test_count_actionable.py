#!/usr/bin/env python3
"""count_actionable.py の契約テスト。

- valid と flawed_premise だけを数え、invalid・misunderstanding・out_of_scope は数えない
- 評価の結果が無い、封緘されていない、エラー値で終えている、置き場が無いときは失敗する
- 何も書かない
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "plugins" / "forge" / "scripts" / "review" / "count_actionable.py"


def run(*args):
    completed = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    payload = json.loads(completed.stdout) if completed.stdout.strip() else None
    return completed.returncode, payload


class CountActionableTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.round = self.root / ".temp" / "review" / "rid" / "1"
        self.round.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, dispositions, **extra):
        result = {"evaluations": [{"disposition": d} for d in dispositions], **extra}
        (self.round / "evaluate_result.json").write_text(json.dumps(result), encoding="utf-8")

    def _count(self):
        return run(str(self.root), "rid", "1")

    def test_counts_only_valid_and_flawed_premise(self):
        self._write(
            ["valid", "flawed_premise", "invalid", "misunderstanding", "out_of_scope", "valid"], exit="0"
        )
        self.assertEqual(self._count(), (0, {"actionable": 3}))

    def test_zero_when_none_actionable(self):
        self._write(["invalid", "out_of_scope"], exit="0")
        self.assertEqual(self._count(), (0, {"actionable": 0}))

    def test_zero_evaluations(self):
        self._write([], exit="0")
        self.assertEqual(self._count(), (0, {"actionable": 0}))

    def test_writes_nothing(self):
        self._write(["valid"], exit="0")
        before = sorted(p.name for p in self.round.iterdir())
        content = (self.round / "evaluate_result.json").read_bytes()
        self._count()
        self.assertEqual(sorted(p.name for p in self.round.iterdir()), before)
        self.assertEqual((self.round / "evaluate_result.json").read_bytes(), content)

    def test_fails_when_not_sealed(self):
        self._write(["valid"])
        code, payload = self._count()
        self.assertEqual(code, 1)
        self.assertIn("封緘されていません", payload["errors"][0])

    def test_fails_when_error_exit(self):
        self._write(["valid"], exit="boom")
        code, payload = self._count()
        self.assertEqual(code, 1)
        self.assertIn("エラーで終えています", payload["errors"][0])

    def test_fails_when_no_evaluation_result(self):
        code, payload = self._count()
        self.assertEqual(code, 1)
        self.assertIn("評価の結果がありません", payload["errors"][0])

    def test_fails_when_unreadable_result(self):
        (self.round / "evaluate_result.json").write_text("not json", encoding="utf-8")
        code, payload = self._count()
        self.assertEqual(code, 1)
        self.assertIn("評価の結果を読めません", payload["errors"][0])

    def test_fails_when_round_missing(self):
        code, payload = run(str(self.root), "rid", "2")
        self.assertEqual(code, 1)
        self.assertIn("ラウンドの置き場がありません", payload["errors"][0])

    def test_fails_when_review_missing(self):
        code, payload = run(str(self.root), "nope", "1")
        self.assertEqual(code, 1)
        self.assertIn("保持されていません", payload["errors"][0])


if __name__ == "__main__":
    unittest.main()
