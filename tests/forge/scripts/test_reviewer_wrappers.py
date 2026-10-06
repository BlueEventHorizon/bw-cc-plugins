#!/usr/bin/env python3
"""reviewer のラッパー 4 本（reviewer_*）の契約テスト。

DES-084 §6.6・§7 の観点を確かめる。

- ラッパーは固定したオプションで基本の script を呼び、標準出力と終了コードをそのまま返す
- reviewer が所見以外を書けない（固定したオプションを上書きする口が無い）
- 依頼の公開から、所見の書き出しと封緘、読み出しまでが、ラッパー経由で成立する
- target_unreadable で終えたとき、書き出さずに終えたとき、resolve_review_path.py が失敗する
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = REPO_ROOT / "plugins" / "forge" / "scripts" / "review"
PUBLISH = SCRIPT_DIR / "publish_request.py"
RESOLVE = SCRIPT_DIR / "resolve_review_path.py"
W_RESOLVE_REQUEST = SCRIPT_DIR / "reviewer_resolve_request.py"
W_ADD_FINDING = SCRIPT_DIR / "reviewer_add_finding.py"
W_FINISH = SCRIPT_DIR / "reviewer_finish.py"
W_ABORT = SCRIPT_DIR / "reviewer_abort.py"


def _run(script, *args, stdin="", cwd=None):
    completed = subprocess.run(
        [sys.executable, str(script), *args],
        input=stdin.encode("utf-8"),
        capture_output=True,
        cwd=cwd,
    )
    stdout = completed.stdout.decode("utf-8")
    payload = json.loads(stdout) if stdout.strip() else None
    return completed.returncode, payload


class _Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        target = self.root / "a.md"
        target.write_text("# a\n", encoding="utf-8")
        self.target = target
        code, payload = _run(PUBLISH, str(self.root), "--paths", str(target))
        self.assertEqual(code, 0, payload)
        self.review_id = payload["review_id"]

    def ids(self, n=1):
        return str(self.root), self.review_id, str(n)

    def resolve_findings(self, n=1):
        return _run(RESOLVE, *self.ids(n), "--kind", "findings")

    def add(self, body, *locations, n=1):
        return _run(W_ADD_FINDING, *self.ids(n), "--location", *locations, stdin=body)


class ResolveRequestTest(_Fixture):
    def test_returns_the_same_path_as_the_base_script(self):
        code, payload = _run(W_RESOLVE_REQUEST, *self.ids())
        expected = _run(RESOLVE, *self.ids(), "--kind", "request")
        self.assertEqual((code, payload), expected)
        self.assertEqual(code, 0)
        self.assertTrue(Path(payload["path"]).is_absolute())

    def test_failure_is_returned_as_is(self):
        code, payload = _run(W_RESOLVE_REQUEST, str(self.root), "0" * 32, "1")
        self.assertEqual(code, 1)
        self.assertTrue(payload["errors"])

    def test_cannot_resolve_the_findings(self):
        """reviewer が結果の読み出し（--kind findings）を口にできない。"""
        code, _ = _run(W_RESOLVE_REQUEST, *self.ids(), "--kind", "findings")
        self.assertEqual(code, 2)


class AddFindingTest(_Fixture):
    def test_appends_findings_with_serial_ids_and_unchanged_body(self):
        body = '改行\nと "引用符" と `バッククォート` と 非 ASCII\n'
        code, payload = self.add(body, str(self.target) + ":1")
        self.assertEqual((code, payload), (0, {"finding_id": 1}))
        code, payload = self.add("二件目", str(self.target) + ":2-3", "位置未確定")
        self.assertEqual((code, payload), (0, {"finding_id": 2}))

        self.assertEqual(_run(W_FINISH, *self.ids())[0], 0)
        code, payload = self.resolve_findings()
        self.assertEqual(code, 0)
        result = json.loads(Path(payload["path"]).read_text(encoding="utf-8"))
        self.assertEqual(result["exit"], "0")
        self.assertEqual([f["finding_id"] for f in result["findings"]], [1, 2])
        self.assertEqual(result["findings"][0]["body"], body)
        self.assertEqual(result["findings"][1]["location"], [str(self.target) + ":2-3", "位置未確定"])

    def test_writes_nothing_but_findings(self):
        """書かれるのは所見だけである（severity・評価の欄を持たない）。"""
        self.add("本文", str(self.target) + ":1")
        _run(W_FINISH, *self.ids())
        _, payload = self.resolve_findings()
        result = json.loads(Path(payload["path"]).read_text(encoding="utf-8"))
        self.assertEqual(set(result), {"findings", "exit"})
        self.assertEqual(set(result["findings"][0]), {"finding_id", "location", "body"})

    def test_kind_cannot_be_overridden(self):
        code, _ = _run(W_ADD_FINDING, *self.ids(), "--kind", "evaluations", "--location", "位置未確定", stdin="x")
        self.assertEqual(code, 2)

    def test_location_is_required(self):
        code, _ = _run(W_ADD_FINDING, *self.ids(), stdin="x")
        self.assertEqual(code, 2)

    def test_failure_is_returned_as_is(self):
        code, payload = self.add("   ", "位置未確定")
        self.assertEqual(code, 1)
        self.assertTrue(payload["errors"])

    def test_cannot_append_after_sealing(self):
        _run(W_FINISH, *self.ids())
        code, payload = self.add("本文", "位置未確定")
        self.assertEqual(code, 1)
        self.assertTrue(payload["errors"])


class FinishTest(_Fixture):
    def test_zero_findings_is_a_normal_exit(self):
        code, payload = _run(W_FINISH, *self.ids())
        self.assertEqual((code, payload), (0, {}))
        code, payload = self.resolve_findings()
        self.assertEqual(code, 0)
        result = json.loads(Path(payload["path"]).read_text(encoding="utf-8"))
        self.assertEqual(result, {"findings": [], "exit": "0"})

    def test_exit_value_cannot_be_given(self):
        code, _ = _run(W_FINISH, *self.ids(), "--exit", "target_unreadable")
        self.assertEqual(code, 2)

    def test_kind_cannot_be_given(self):
        code, _ = _run(W_FINISH, *self.ids(), "--kind", "evaluations")
        self.assertEqual(code, 2)

    def test_second_seal_fails(self):
        _run(W_FINISH, *self.ids())
        code, payload = _run(W_FINISH, *self.ids())
        self.assertEqual(code, 1)
        self.assertTrue(payload["errors"])


class AbortTest(_Fixture):
    def test_target_unreadable_makes_the_findings_unreadable(self):
        code, payload = _run(W_ABORT, *self.ids())
        self.assertEqual((code, payload), (0, {}))
        code, payload = self.resolve_findings()
        self.assertEqual(code, 1)
        self.assertIn("target_unreadable", " ".join(payload["errors"]))

    def test_exit_value_cannot_be_given(self):
        code, _ = _run(W_ABORT, *self.ids(), "--exit", "0")
        self.assertEqual(code, 2)


class NoResultTest(_Fixture):
    def test_ending_without_writing_makes_the_findings_unreadable(self):
        code, payload = self.resolve_findings()
        self.assertEqual(code, 1)
        self.assertTrue(payload["errors"])

    def test_ending_without_sealing_makes_the_findings_unreadable(self):
        self.add("本文", "位置未確定")
        code, payload = self.resolve_findings()
        self.assertEqual(code, 1)
        self.assertTrue(payload["errors"])


class WorkingDirectoryTest(_Fixture):
    def test_same_result_from_another_working_directory(self):
        with tempfile.TemporaryDirectory() as other:
            code, payload = _run(W_RESOLVE_REQUEST, *self.ids(), cwd=other)
        self.assertEqual(code, 0)
        self.assertEqual(payload, _run(W_RESOLVE_REQUEST, *self.ids())[1])


if __name__ == "__main__":
    unittest.main()
