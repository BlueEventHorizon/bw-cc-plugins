#!/usr/bin/env python3
"""evaluator のラッパー 3 本（evaluator_*）の契約テスト。

DES-083 §6.1・§7 の観点を確かめる。

- ラッパーは固定したオプションで基本の script を呼び、標準出力と終了コードをそのまま返す
- evaluator が評価以外に書けない（固定したオプションを上書きする口が無い）
- 依頼の公開と所見の封緘から、評価の書き出しと封緘、読み出しまでが、ラッパー経由で成立する
- 引かれていない所見が残るとき evaluator_finish が失敗し、評価を足してから書き終えられる
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
W_RESOLVE_INPUTS = SCRIPT_DIR / "evaluator_resolve_inputs.py"
W_ADD_EVALUATION = SCRIPT_DIR / "evaluator_add_evaluation.py"
W_FINISH = SCRIPT_DIR / "evaluator_finish.py"


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
    """依頼を公開し、reviewer が所見を 2 件書いて封緘した状態から始める。"""

    findings_to_write = 2

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
        for i in range(self.findings_to_write):
            code, _ = _run(
                R_ADD_FINDING, *self.ids(), "--location", f"{target}:{i + 1}", stdin=f"所見 {i + 1}\n"
            )
            self.assertEqual(code, 0)
        self.assertEqual(_run(R_FINISH, *self.ids())[0], 0)

    def ids(self, n=1):
        return str(self.root), self.review_id, str(n)

    def resolve_evaluations(self, n=1):
        return _run(RESOLVE, *self.ids(n), "--kind", "evaluations")

    def read_evaluations(self):
        code, payload = self.resolve_evaluations()
        self.assertEqual(code, 0, payload)
        return json.loads(Path(payload["path"]).read_text(encoding="utf-8"))

    def add(self, reason, *options, n=1):
        return _run(W_ADD_EVALUATION, *self.ids(n), *options, stdin=reason)

    def add_valid(self, reason, *findings):
        return self.add(
            reason, "--disposition", "valid", "--severity", "major",
            "--findings", *[str(n) for n in findings],
            "--confidence", "confirmed", "--fix-confident", "true",
        )


class ResolveInputsTest(_Fixture):
    def test_returns_the_same_paths_as_the_base_script(self):
        code, payload = _run(W_RESOLVE_INPUTS, *self.ids())
        expected = _run(RESOLVE, *self.ids(), "--kind", "inputs")
        self.assertEqual((code, payload), expected)
        self.assertEqual(code, 0)
        self.assertEqual(set(payload), {"request", "findings"})
        self.assertTrue(Path(payload["request"]).is_absolute())
        self.assertTrue(Path(payload["findings"]).is_absolute())

    def test_failure_is_returned_as_is(self):
        code, payload = _run(W_RESOLVE_INPUTS, str(self.root), "0" * 32, "1")
        self.assertEqual(code, 1)
        self.assertTrue(payload["errors"])

    def test_kind_cannot_be_overridden(self):
        code, _ = _run(W_RESOLVE_INPUTS, *self.ids(), "--kind", "findings")
        self.assertEqual(code, 2)


class ResolveInputsWithoutFindingsTest(unittest.TestCase):
    """所見が正常に終えていなければ、どちらのパスも返らず、評価に入れない。"""

    def _setup(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        target = root / "a.md"
        target.write_text("# a\n", encoding="utf-8")
        _, payload = _run(PUBLISH, str(root), "--paths", str(target))
        return str(root), payload["review_id"], "1"

    def test_reviewer_target_unreadable_makes_inputs_unreadable(self):
        ids = self._setup()
        self.assertEqual(_run(R_ABORT, *ids)[0], 0)
        code, payload = _run(W_RESOLVE_INPUTS, *ids)
        self.assertEqual(code, 1)
        self.assertNotIn("request", payload)
        self.assertNotIn("findings", payload)
        self.assertIn("target_unreadable", " ".join(payload["errors"]))

    def test_reviewer_ending_without_writing_makes_inputs_unreadable(self):
        code, payload = _run(W_RESOLVE_INPUTS, *self._setup())
        self.assertEqual(code, 1)
        self.assertTrue(payload["errors"])


class AddEvaluationTest(_Fixture):
    def test_appends_evaluations_and_keeps_the_reason_unchanged(self):
        reason = '改行\nと "引用符" と `バッククォート` と 非 ASCII\n'
        self.assertEqual(self.add_valid(reason, 1), (0, {}))
        code, payload = self.add(
            "退ける", "--disposition", "invalid", "--severity", "minor", "--findings", "2"
        )
        self.assertEqual((code, payload), (0, {}))
        self.assertEqual(_run(W_FINISH, *self.ids())[0], 0)

        result = self.read_evaluations()
        self.assertEqual(result["exit"], "0")
        first, second = result["evaluations"]
        self.assertEqual(first["reason"], reason)
        self.assertEqual(first["finding_ids"], [1])
        self.assertEqual(first["confidence"], "confirmed")
        self.assertIs(first["fix_confident"], True)
        self.assertEqual(second["disposition"], "invalid")
        self.assertNotIn("confidence", second)

    def test_one_evaluation_can_bundle_findings(self):
        self.assertEqual(self.add_valid("共通の原因", 1, 2), (0, {}))
        self.assertEqual(_run(W_FINISH, *self.ids())[0], 0)
        self.assertEqual(self.read_evaluations()["evaluations"][0]["finding_ids"], [1, 2])

    def test_new_finding_takes_the_next_number_and_requires_location(self):
        code, payload = self.add(
            "新規", "--disposition", "valid", "--severity", "minor", "--new",
            "--confidence", "inferred", "--fix-confident", "false",
        )
        self.assertEqual(code, 1)
        self.assertTrue(payload["errors"])

        code, payload = self.add(
            "新規", "--disposition", "valid", "--severity", "minor", "--new",
            "--location", f"{self.target}:9",
            "--confidence", "inferred", "--fix-confident", "false",
        )
        self.assertEqual((code, payload), (0, {"finding_id": 3}))
        self.assertEqual(self.add_valid("束ねる", 1, 2)[0], 0)
        self.assertEqual(_run(W_FINISH, *self.ids())[0], 0)
        new = self.read_evaluations()["evaluations"][0]
        self.assertEqual(new["finding_ids"], [3])
        self.assertEqual(new["location"], [f"{self.target}:9"])

    def test_disposition_and_severity_are_required(self):
        self.assertEqual(self.add("x", "--severity", "minor", "--findings", "1")[0], 2)
        self.assertEqual(self.add("x", "--disposition", "invalid", "--findings", "1")[0], 2)

    def test_values_outside_the_vocabulary_are_rejected(self):
        code, _ = self.add("x", "--disposition", "bogus", "--severity", "minor", "--findings", "1")
        self.assertEqual(code, 2)

    def test_failure_is_returned_as_is_and_writes_nothing(self):
        code, payload = self.add(
            "x", "--disposition", "invalid", "--severity", "minor", "--findings", "99"
        )
        self.assertEqual(code, 1)
        self.assertTrue(payload["errors"])
        self.assertEqual(self.resolve_evaluations()[0], 1)

    def test_empty_reason_is_rejected(self):
        code, payload = self.add("  ", "--disposition", "invalid", "--severity", "minor", "--findings", "1")
        self.assertEqual(code, 1)
        self.assertTrue(payload["errors"])

    def test_cannot_append_after_sealing(self):
        self.add_valid("1", 1)
        self.add_valid("2", 2)
        _run(W_FINISH, *self.ids())
        code, payload = self.add_valid("遅れた評価", 1)
        self.assertEqual(code, 1)
        self.assertTrue(payload["errors"])


class CannotWriteFindingsTest(_Fixture):
    """evaluator_* では所見を書けない。"""

    def test_kind_cannot_be_overridden(self):
        code, _ = self.add(
            "x", "--kind", "findings", "--disposition", "invalid", "--severity", "minor", "--findings", "1"
        )
        self.assertEqual(code, 2)

    def test_findings_file_is_untouched_by_the_wrappers(self):
        _, payload = _run(RESOLVE, *self.ids(), "--kind", "findings")
        path = Path(payload["path"])
        before = path.read_text(encoding="utf-8")
        self.add_valid("1", 1)
        self.add_valid("2", 2)
        _run(W_FINISH, *self.ids())
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_written_file_has_only_evaluations_and_exit(self):
        self.add_valid("1", 1, 2)
        _run(W_FINISH, *self.ids())
        result = self.read_evaluations()
        self.assertEqual(set(result), {"evaluations", "exit"})
        self.assertEqual(
            set(result["evaluations"][0]),
            {"finding_ids", "disposition", "severity", "reason", "confidence", "fix_confident"},
        )


class FinishTest(_Fixture):
    def test_unreferenced_finding_fails_and_its_number_is_returned(self):
        self.add_valid("1 だけ", 1)
        code, payload = _run(W_FINISH, *self.ids())
        self.assertEqual(code, 1)
        self.assertIn("finding_id=2", " ".join(payload["errors"]))
        self.assertEqual(self.resolve_evaluations()[0], 1)

    def test_all_unreferenced_numbers_are_listed(self):
        code, payload = _run(W_FINISH, *self.ids())
        self.assertEqual(code, 1)
        joined = " ".join(payload["errors"])
        self.assertIn("finding_id=1", joined)
        self.assertIn("finding_id=2", joined)

    def test_evaluations_can_be_added_after_a_failed_finish(self):
        self.add_valid("1", 1)
        self.assertEqual(_run(W_FINISH, *self.ids())[0], 1)
        self.assertEqual(self.add_valid("2", 2)[0], 0)
        self.assertEqual(_run(W_FINISH, *self.ids()), (0, {}))
        self.assertEqual(self.read_evaluations()["exit"], "0")

    def test_exit_value_and_kind_cannot_be_given(self):
        self.assertEqual(_run(W_FINISH, *self.ids(), "--exit", "target_unreadable")[0], 2)
        self.assertEqual(_run(W_FINISH, *self.ids(), "--exit", "0")[0], 2)
        self.assertEqual(_run(W_FINISH, *self.ids(), "--kind", "findings")[0], 2)

    def test_second_seal_fails(self):
        self.add_valid("1", 1, 2)
        _run(W_FINISH, *self.ids())
        code, payload = _run(W_FINISH, *self.ids())
        self.assertEqual(code, 1)
        self.assertTrue(payload["errors"])


class ZeroFindingsTest(_Fixture):
    findings_to_write = 0

    def test_zero_findings_and_zero_evaluations_is_a_normal_exit(self):
        code, payload = _run(W_FINISH, *self.ids())
        self.assertEqual((code, payload), (0, {}))
        self.assertEqual(self.read_evaluations(), {"evaluations": [], "exit": "0"})

    def test_a_new_finding_can_be_given_without_findings(self):
        code, payload = self.add(
            "新規", "--disposition", "valid", "--severity", "major", "--new",
            "--location", f"{self.target}:1",
            "--confidence", "confirmed", "--fix-confident", "true",
        )
        self.assertEqual((code, payload), (0, {"finding_id": 1}))
        self.assertEqual(_run(W_FINISH, *self.ids())[0], 0)


class NoEvaluationsTest(_Fixture):
    def test_ending_without_writing_makes_the_evaluations_unreadable(self):
        code, payload = self.resolve_evaluations()
        self.assertEqual(code, 1)
        self.assertTrue(payload["errors"])

    def test_ending_without_sealing_makes_the_evaluations_unreadable(self):
        self.add_valid("1", 1)
        code, payload = self.resolve_evaluations()
        self.assertEqual(code, 1)
        self.assertTrue(payload["errors"])


class WorkingDirectoryTest(_Fixture):
    def test_same_result_from_another_working_directory(self):
        with tempfile.TemporaryDirectory() as other:
            code, payload = _run(W_RESOLVE_INPUTS, *self.ids(), cwd=other)
        self.assertEqual(code, 0)
        self.assertEqual(payload, _run(W_RESOLVE_INPUTS, *self.ids())[1])


if __name__ == "__main__":
    unittest.main()
