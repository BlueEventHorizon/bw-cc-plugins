#!/usr/bin/env python3
"""本体のラッパー 2 本（body_resolve_*）の契約テスト。

DES-083 §6.8 の観点を確かめる。

- ラッパーは固定したオプションで基本の script を呼び、標準出力と終了コードをそのまま返す
- 固定したオプションを上書きする口が無い
- 余計な引数は終了コード 2 になる
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
R_ADD_FINDING = SCRIPT_DIR / "reviewer_add_finding.py"
R_FINISH = SCRIPT_DIR / "reviewer_finish.py"
R_ABORT = SCRIPT_DIR / "reviewer_abort.py"
E_ADD_EVALUATION = SCRIPT_DIR / "evaluator_add_evaluation.py"
E_FINISH = SCRIPT_DIR / "evaluator_finish.py"
B_FINDINGS = SCRIPT_DIR / "body_resolve_findings.py"
B_EVALUATIONS = SCRIPT_DIR / "body_resolve_evaluations.py"

WRAPPERS = (("findings", B_FINDINGS), ("evaluations", B_EVALUATIONS))


def _run(script, *args, stdin="", cwd=None):
    completed = subprocess.run(
        [sys.executable, str(script), *args],
        input=stdin.encode("utf-8"),
        capture_output=True,
        cwd=cwd,
    )
    return completed.returncode, completed.stdout.decode("utf-8")


class _Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.target = self.root / "a.md"
        self.target.write_text("# a\n", encoding="utf-8")
        code, out = _run(PUBLISH, str(self.root), "--paths", str(self.target))
        self.assertEqual(code, 0, out)
        self.review_id = json.loads(out)["review_id"]

    def ids(self, n=1):
        return str(self.root), self.review_id, str(n)

    def write_findings(self):
        code, _ = _run(R_ADD_FINDING, *self.ids(), "--location", f"{self.target}:1", stdin="所見\n")
        self.assertEqual(code, 0)
        self.assertEqual(_run(R_FINISH, *self.ids())[0], 0)

    def write_evaluations(self):
        code, out = _run(
            E_ADD_EVALUATION, *self.ids(),
            "--disposition", "valid", "--severity", "major", "--findings", "1",
            "--confidence", "confirmed", "--fix-confident", "true",
            stdin="妥当\n",
        )
        self.assertEqual(code, 0, out)
        self.assertEqual(_run(E_FINISH, *self.ids())[0], 0)

    def assert_same_as_base(self, kind, wrapper, *args):
        actual = _run(wrapper, *args)
        expected = _run(RESOLVE, *args, "--kind", kind)
        self.assertEqual(actual, expected)
        return actual


class MatchesBaseScriptTest(_Fixture):
    def test_normal(self):
        self.write_findings()
        self.write_evaluations()
        for kind, wrapper in WRAPPERS:
            with self.subTest(kind=kind):
                code, out = self.assert_same_as_base(kind, wrapper, *self.ids())
                self.assertEqual(code, 0)
                path = Path(json.loads(out)["path"])
                self.assertTrue(path.is_absolute())
                self.assertTrue(path.is_file())

    def test_no_result(self):
        for kind, wrapper in WRAPPERS:
            with self.subTest(kind=kind):
                code, out = self.assert_same_as_base(kind, wrapper, *self.ids())
                self.assertEqual(code, 1)
                self.assertTrue(json.loads(out)["errors"])

    def test_not_sealed(self):
        _run(R_ADD_FINDING, *self.ids(), "--location", f"{self.target}:1", stdin="所見\n")
        _run(E_ADD_EVALUATION, *self.ids(), "--disposition", "invalid", "--severity", "minor",
             "--findings", "1", stdin="x\n")
        for kind, wrapper in WRAPPERS:
            with self.subTest(kind=kind):
                code, _ = self.assert_same_as_base(kind, wrapper, *self.ids())
                self.assertEqual(code, 1)

    def test_error_value(self):
        self.assertEqual(_run(R_ABORT, *self.ids())[0], 0)
        code, out = self.assert_same_as_base("findings", B_FINDINGS, *self.ids())
        self.assertEqual(code, 1)
        self.assertIn("target_unreadable", " ".join(json.loads(out)["errors"]))

    def test_missing_round(self):
        for kind, wrapper in WRAPPERS:
            with self.subTest(kind=kind):
                code, out = self.assert_same_as_base(kind, wrapper, str(self.root), self.review_id, "9")
                self.assertEqual(code, 1)
                self.assertTrue(json.loads(out)["errors"])

    def test_unknown_review_id(self):
        for kind, wrapper in WRAPPERS:
            with self.subTest(kind=kind):
                code, _ = self.assert_same_as_base(kind, wrapper, str(self.root), "0" * 32, "1")
                self.assertEqual(code, 1)


class ArgumentsTest(_Fixture):
    def test_kind_cannot_be_overridden(self):
        for _, wrapper in WRAPPERS:
            for kind in ("findings", "evaluations", "request"):
                with self.subTest(wrapper=wrapper.name, kind=kind):
                    self.assertEqual(_run(wrapper, *self.ids(), "--kind", kind)[0], 2)

    def test_extra_arguments_exit_with_2(self):
        for _, wrapper in WRAPPERS:
            with self.subTest(wrapper=wrapper.name):
                self.assertEqual(_run(wrapper, *self.ids(), "extra")[0], 2)
                self.assertEqual(_run(wrapper, *self.ids(), "--bogus")[0], 2)
                self.assertEqual(_run(wrapper, str(self.root), self.review_id)[0], 2)


class WorkingDirectoryTest(_Fixture):
    def test_same_result_from_another_working_directory(self):
        self.write_findings()
        with tempfile.TemporaryDirectory() as other:
            code, out = _run(B_FINDINGS, *self.ids(), cwd=other)
        self.assertEqual(code, 0)
        self.assertEqual(out, _run(B_FINDINGS, *self.ids())[1])


if __name__ == "__main__":
    unittest.main()
