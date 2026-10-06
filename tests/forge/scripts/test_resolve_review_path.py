#!/usr/bin/env python3
"""resolve_review_path.py（--kind request / findings / evaluations / inputs）の契約テスト。

DES-084 §5.4・§6.5・§7 と DES-083 §5.1・§6.4・§7 の観点を確かめる。

- findings: 結果の有無と exit の 4 状態（正常 / エラー値 / exit が無い / 結果が無い）
- request: 公開前の依頼のパスは返さない。公開後は絶対パスを返す
- 標準出力に JSON 本文を含まない。作業ディレクトリを変えても同じ絶対パスが得られる
- evaluations: findings と同じ 4 状態を evaluate_result.json について判定する
- inputs: request と findings の両方を判定し、片方でも失敗すれば失敗して両方の理由を返す
- 実際の書き手（publish_request.py / append_result.py / seal_result.py）の出力を読めること
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = REPO_ROOT / "plugins" / "forge" / "scripts" / "review"
RESOLVE = SCRIPT_DIR / "resolve_review_path.py"
PUBLISH = SCRIPT_DIR / "publish_request.py"
APPEND = SCRIPT_DIR / "append_result.py"
SEAL = SCRIPT_DIR / "seal_result.py"


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
        self.review_id = "a" * 32
        self.review = self.root / ".temp" / "review" / self.review_id
        self.round1 = self.review / "1"
        self.round1.mkdir(parents=True)

    def resolve(self, kind, n=1, review_id=None, cwd=None):
        return _run(
            RESOLVE, str(self.root), review_id or self.review_id, str(n), "--kind", kind, cwd=cwd
        )

    def write_result(self, payload, n=1, file_name="review_result.json"):
        d = self.review / str(n)
        d.mkdir(parents=True, exist_ok=True)
        (d / file_name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def write_evaluations(self, payload, n=1):
        self.write_result(payload, n, "evaluate_result.json")

    def assert_failure(self, outcome):
        code, payload = outcome
        self.assertEqual(code, 1)
        self.assertEqual(set(payload), {"errors"})
        self.assertTrue(payload["errors"])
        self.assertTrue(all(isinstance(e, str) and e for e in payload["errors"]))
        return payload["errors"]


class FindingsStateTest(_Fixture):
    def test_normal_returns_the_absolute_path(self):
        self.write_result({"findings": [], "exit": "0"})
        code, payload = self.resolve("findings")
        self.assertEqual(code, 0)
        self.assertEqual(payload, {"path": str(self.round1 / "review_result.json")})
        self.assertTrue(Path(payload["path"]).is_absolute())

    def test_normal_with_findings_does_not_echo_the_body(self):
        self.write_result(
            {"findings": [{"finding_id": 1, "location": ["/x:1"], "body": "秘密の本文"}], "exit": "0"}
        )
        completed = subprocess.run(
            [sys.executable, str(RESOLVE), str(self.root), self.review_id, "1", "--kind", "findings"],
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertNotIn("秘密の本文".encode("utf-8"), completed.stdout)
        self.assertEqual(set(json.loads(completed.stdout)), {"path"})

    def test_error_value_fails_and_puts_the_value_in_errors(self):
        self.write_result({"findings": [], "exit": "target_unreadable"})
        errors = self.assert_failure(self.resolve("findings"))
        self.assertTrue(any("target_unreadable" in e for e in errors))

    def test_missing_exit_fails_and_says_it_is_not_sealed(self):
        self.write_result({"findings": [{"finding_id": 1, "location": ["/x:1"], "body": "b"}]})
        errors = self.assert_failure(self.resolve("findings"))
        self.assertTrue(any("封緘" in e for e in errors))

    def test_missing_result_fails_and_says_there_is_no_result(self):
        errors = self.assert_failure(self.resolve("findings"))
        self.assertTrue(any("結果がありません" in e for e in errors))

    def test_any_exit_other_than_zero_string_fails(self):
        for value in ("1", "", 0, None):
            self.write_result({"findings": [], "exit": value})
            self.assert_failure(self.resolve("findings"))

    def test_missing_round_and_unknown_review_fail(self):
        self.write_result({"findings": [], "exit": "0"})
        self.assert_failure(self.resolve("findings", n=9))
        self.assert_failure(self.resolve("findings", review_id="b" * 32))

    def test_a_round_does_not_read_another_rounds_result(self):
        self.write_result({"findings": [], "exit": "0"}, n=1)
        (self.review / "2").mkdir()
        self.assert_failure(self.resolve("findings", n=2))

    def test_unreadable_result_json_fails_with_errors(self):
        (self.round1 / "review_result.json").write_text("{not json", encoding="utf-8")
        self.assert_failure(self.resolve("findings"))


class EvaluationsStateTest(_Fixture):
    """evaluations は evaluate_result.json の状態を、所見の結果と同じ表で判定する（DES-083 §5.1・§6.4）。"""

    def test_normal_returns_the_absolute_path_of_evaluate_result(self):
        self.write_evaluations({"evaluations": [], "exit": "0"})
        code, payload = self.resolve("evaluations")
        self.assertEqual(code, 0)
        self.assertEqual(payload, {"path": str(self.round1 / "evaluate_result.json")})

    def test_normal_does_not_echo_the_reason(self):
        self.write_evaluations(
            {"evaluations": [{"finding_ids": [1], "disposition": "invalid", "severity": "minor",
                              "reason": "秘密の根拠"}], "exit": "0"}
        )
        completed = subprocess.run(
            [sys.executable, str(RESOLVE), str(self.root), self.review_id, "1", "--kind", "evaluations"],
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertNotIn("秘密の根拠".encode("utf-8"), completed.stdout)

    def test_error_value_fails_and_puts_the_value_in_errors(self):
        self.write_evaluations({"evaluations": [], "exit": "target_unreadable"})
        errors = self.assert_failure(self.resolve("evaluations"))
        self.assertTrue(any("target_unreadable" in e for e in errors))

    def test_missing_exit_fails_and_says_it_is_not_sealed(self):
        self.write_evaluations({"evaluations": []})
        errors = self.assert_failure(self.resolve("evaluations"))
        self.assertTrue(any("封緘" in e for e in errors))

    def test_missing_result_fails_and_says_there_is_no_result(self):
        errors = self.assert_failure(self.resolve("evaluations"))
        self.assertTrue(any("結果がありません" in e for e in errors))

    def test_any_exit_other_than_zero_string_fails(self):
        for value in ("1", "", 0, None):
            self.write_evaluations({"evaluations": [], "exit": value})
            self.assert_failure(self.resolve("evaluations"))

    def test_findings_result_alone_is_not_an_evaluation_result(self):
        self.write_result({"findings": [], "exit": "0"})
        self.assert_failure(self.resolve("evaluations"))

    def test_evaluation_result_alone_is_not_a_findings_result(self):
        self.write_evaluations({"evaluations": [], "exit": "0"})
        self.assert_failure(self.resolve("findings"))

    def test_missing_round_and_unknown_review_fail(self):
        self.write_evaluations({"evaluations": [], "exit": "0"})
        self.assert_failure(self.resolve("evaluations", n=9))
        self.assert_failure(self.resolve("evaluations", review_id="b" * 32))

    def test_unreadable_result_json_fails_with_errors(self):
        (self.round1 / "evaluate_result.json").write_text("{not json", encoding="utf-8")
        self.assert_failure(self.resolve("evaluations"))


class InputsStateTest(_Fixture):
    """inputs は request と findings の両方を判定し、片方でも失敗すれば失敗して両方の理由を返す（DES-083 §6.4）。"""

    def publish_request(self):
        (self.review / "review_request.json").write_text('{"targets": []}', encoding="utf-8")

    def test_both_normal_returns_both_absolute_paths(self):
        self.publish_request()
        self.write_result({"findings": [], "exit": "0"})
        code, payload = self.resolve("inputs")
        self.assertEqual(code, 0)
        self.assertEqual(
            payload,
            {"request": str(self.review / "review_request.json"), "findings": str(self.round1 / "review_result.json")},
        )

    def test_both_paths_equal_the_single_kind_results(self):
        self.publish_request()
        self.write_result({"findings": [], "exit": "0"})
        _, inputs = self.resolve("inputs")
        self.assertEqual(inputs["request"], self.resolve("request")[1]["path"])
        self.assertEqual(inputs["findings"], self.resolve("findings")[1]["path"])

    def test_findings_failure_fails_even_if_the_request_is_fine(self):
        self.publish_request()
        errors = self.assert_failure(self.resolve("inputs"))
        self.assertTrue(any("結果がありません" in e for e in errors))

    def test_request_failure_fails_even_if_the_findings_are_fine(self):
        self.write_result({"findings": [], "exit": "0"})
        errors = self.assert_failure(self.resolve("inputs"))
        self.assertTrue(any("公開されていません" in e for e in errors))

    def test_both_failing_puts_both_reasons_in_errors(self):
        errors = self.assert_failure(self.resolve("inputs"))
        self.assertTrue(any("公開されていません" in e for e in errors))
        self.assertTrue(any("結果がありません" in e for e in errors))

    def test_error_value_in_findings_is_reported_together_with_a_missing_request(self):
        self.write_result({"findings": [], "exit": "target_unreadable"})
        errors = self.assert_failure(self.resolve("inputs"))
        self.assertTrue(any("公開されていません" in e for e in errors))
        self.assertTrue(any("target_unreadable" in e for e in errors))

    def test_missing_round_fails_with_the_reason_once(self):
        errors = self.assert_failure(self.resolve("inputs", n=9))
        self.assertEqual(len(errors), 1)

    def test_no_body_is_echoed(self):
        (self.review / "review_request.json").write_text(
            json.dumps({"focus": "秘密の重点観点"}, ensure_ascii=False), encoding="utf-8"
        )
        self.write_result(
            {"findings": [{"finding_id": 1, "location": ["/x:1"], "body": "秘密の本文"}], "exit": "0"}
        )
        completed = subprocess.run(
            [sys.executable, str(RESOLVE), str(self.root), self.review_id, "1", "--kind", "inputs"],
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertNotIn("秘密".encode("utf-8"), completed.stdout)
        self.assertEqual(set(json.loads(completed.stdout)), {"request", "findings"})

    def test_same_paths_regardless_of_working_directory(self):
        self.publish_request()
        self.write_result({"findings": [], "exit": "0"})
        other = self.root / "docs"
        other.mkdir()
        self.assertEqual(self.resolve("inputs"), self.resolve("inputs", cwd=str(other)))

    def test_nothing_is_written(self):
        self.publish_request()
        self.write_result({"findings": [], "exit": "0"})
        before = sorted(p.name for p in self.round1.iterdir())
        self.resolve("inputs")
        self.assertEqual(sorted(p.name for p in self.round1.iterdir()), before)


class RequestStateTest(_Fixture):
    def test_unpublished_request_returns_no_path(self):
        errors = self.assert_failure(self.resolve("request"))
        self.assertTrue(any("公開されていません" in e for e in errors))

    def test_draft_file_is_not_a_published_request(self):
        (self.review / ".review_request.json.abc.tmp").write_text("{}", encoding="utf-8")
        self.assert_failure(self.resolve("request"))

    def test_published_request_returns_the_absolute_path(self):
        (self.review / "review_request.json").write_text('{"targets": []}', encoding="utf-8")
        code, payload = self.resolve("request")
        self.assertEqual((code, payload), (0, {"path": str(self.review / "review_request.json")}))

    def test_request_path_is_the_same_for_every_round(self):
        (self.review / "review_request.json").write_text("{}", encoding="utf-8")
        (self.review / "2").mkdir()
        self.assertEqual(self.resolve("request", n=1), self.resolve("request", n=2))

    def test_missing_round_fails_even_if_the_request_exists(self):
        (self.review / "review_request.json").write_text("{}", encoding="utf-8")
        self.assert_failure(self.resolve("request", n=9))

    def test_unknown_review_fails_without_creating_anything(self):
        self.assert_failure(self.resolve("request", review_id="c" * 32))
        self.assertFalse((self.root / ".temp" / "review" / ("c" * 32)).exists())

    def test_request_body_is_not_echoed(self):
        (self.review / "review_request.json").write_text(
            json.dumps({"focus": "秘密の重点観点"}, ensure_ascii=False), encoding="utf-8"
        )
        completed = subprocess.run(
            [sys.executable, str(RESOLVE), str(self.root), self.review_id, "1", "--kind", "request"],
            capture_output=True,
        )
        self.assertNotIn("秘密の重点観点".encode("utf-8"), completed.stdout)


class CommonBehaviorTest(_Fixture):
    def test_same_absolute_path_regardless_of_working_directory(self):
        self.write_result({"findings": [], "exit": "0"})
        (self.review / "review_request.json").write_text("{}", encoding="utf-8")
        other = self.root / "docs"
        other.mkdir()
        for kind in ("findings", "request"):
            self.assertEqual(self.resolve(kind), self.resolve(kind, cwd=str(other)))

    def test_relative_project_root_is_resolved_to_an_absolute_path(self):
        self.write_result({"findings": [], "exit": "0"})
        code, payload = _run(
            RESOLVE, ".", self.review_id, "1", "--kind", "findings", cwd=str(self.root)
        )
        self.assertEqual(code, 0)
        self.assertEqual(payload, {"path": str(self.round1 / "review_result.json")})

    def test_kind_is_required_and_only_the_four_kinds_are_accepted(self):
        code, _ = _run(RESOLVE, str(self.root), self.review_id, "1")
        self.assertEqual(code, 2)
        for kind in ("evaluation", "input", "other"):
            code, _ = _run(RESOLVE, str(self.root), self.review_id, "1", "--kind", kind)
            self.assertEqual(code, 2, kind)

    def test_non_integer_round_number_is_an_argument_error(self):
        code, _ = _run(RESOLVE, str(self.root), self.review_id, "x", "--kind", "request")
        self.assertEqual(code, 2)

    def test_nothing_is_written(self):
        self.write_result({"findings": [], "exit": "0"})
        before = sorted(p.name for p in self.round1.iterdir())
        self.resolve("findings")
        self.assertEqual(sorted(p.name for p in self.round1.iterdir()), before)


class WithRealWritersTest(unittest.TestCase):
    """実際の書き手が書いた状態を、本 script が §5.4 のとおり判定する。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.doc = self.root / "docs" / "a.md"
        code, payload = _run(PUBLISH, str(self.root), "--paths", str(self.doc))
        self.assertEqual(code, 0)
        self.review_id = payload["review_id"]

    def resolve(self, kind):
        return _run(RESOLVE, str(self.root), self.review_id, "1", "--kind", kind)

    def test_published_request_can_be_resolved_and_read(self):
        code, payload = self.resolve("request")
        self.assertEqual(code, 0)
        request = json.loads(Path(payload["path"]).read_text(encoding="utf-8"))
        self.assertEqual(request["targets"], [{"paths": [str(self.doc)]}])

    def test_four_states_through_the_real_writers(self):
        # 結果が無い
        self.assertEqual(self.resolve("findings")[0], 1)
        # exit が無い
        _run(APPEND, str(self.root), self.review_id, "1", "--kind", "findings",
             "--location", f"{self.doc}:1", stdin="本文")
        self.assertEqual(self.resolve("findings")[0], 1)
        # 正常
        _run(SEAL, str(self.root), self.review_id, "1", "--kind", "findings")
        code, payload = self.resolve("findings")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(Path(payload["path"]).read_text(encoding="utf-8"))["exit"], "0")

    def test_target_unreadable_through_the_real_writers(self):
        _run(SEAL, str(self.root), self.review_id, "1", "--kind", "findings", "--exit", "target_unreadable")
        code, payload = self.resolve("findings")
        self.assertEqual(code, 1)
        self.assertTrue(any("target_unreadable" in e for e in payload["errors"]))


class AllTargetShapesIntegrationTest(unittest.TestCase):
    """DES-084 §7 統合テスト: targets の 3 形（paths / base_branch / diff）すべてで一連が成立する。

    review_id の生成と依頼の公開 → パスの解決と JSON の直接読み出し → 所見の書き出しと封緘
    → 結果のパスの解決と JSON の直接読み出し、を subprocess で連鎖して確かめる。
    """

    W_RESOLVE_REQUEST = SCRIPT_DIR / "reviewer_resolve_request.py"
    W_ADD_FINDING = SCRIPT_DIR / "reviewer_add_finding.py"
    W_FINISH = SCRIPT_DIR / "reviewer_finish.py"
    W_ABORT = SCRIPT_DIR / "reviewer_abort.py"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.doc = self.root / "docs" / "a.md"
        # (名前, 公開の引数, 依頼の targets が持つべき形)
        self.shapes = [
            ("paths", ["--paths", str(self.doc)], [{"paths": [str(self.doc)]}]),
            ("base_branch", ["--base-branch", "main"], [{"base_branch": "main"}]),
            ("diff", ["--diff"], [{"diff": {}}]),
        ]

    def publish(self, args):
        code, payload = _run(PUBLISH, str(self.root), *args)
        self.assertEqual(code, 0, payload)
        self.assertEqual(set(payload), {"review_id", "round_number"})
        self.assertEqual(payload["round_number"], 1)
        return payload["review_id"]

    def ids(self, review_id):
        return str(self.root), review_id, "1"

    def read(self, outcome):
        code, payload = outcome
        self.assertEqual(code, 0, payload)
        return json.loads(Path(payload["path"]).read_text(encoding="utf-8"))

    def test_publish_to_sealed_findings_for_every_shape(self):
        for name, args, expected_targets in self.shapes:
            with self.subTest(shape=name):
                review_id = self.publish(args)

                # 依頼のパスを 2 経路（基本 script・reviewer ラッパー）で得て、同じ JSON を直接読む
                via_base = _run(RESOLVE, *self.ids(review_id), "--kind", "request")
                via_wrapper = _run(self.W_RESOLVE_REQUEST, *self.ids(review_id))
                self.assertEqual(via_base, via_wrapper)
                request = self.read(via_base)
                self.assertEqual(request["targets"], expected_targets)

                # 所見を書き、封緘する
                location = f"{self.doc}:1"
                code, payload = _run(
                    self.W_ADD_FINDING, *self.ids(review_id), "--location", location, stdin="本文 " + name
                )
                self.assertEqual((code, payload), (0, {"finding_id": 1}))
                self.assertEqual(_run(self.W_FINISH, *self.ids(review_id)), (0, {}))

                # 結果のパスを得て、所見と exit を直接読む
                result = self.read(_run(RESOLVE, *self.ids(review_id), "--kind", "findings"))
                self.assertEqual(result["exit"], "0")
                self.assertEqual(
                    result["findings"],
                    [{"finding_id": 1, "location": [location], "body": "本文 " + name}],
                )

    def test_target_unreadable_fails_for_every_shape(self):
        for name, args, _ in self.shapes:
            with self.subTest(shape=name):
                review_id = self.publish(args)
                self.assertEqual(_run(self.W_ABORT, *self.ids(review_id)), (0, {}))
                code, payload = _run(RESOLVE, *self.ids(review_id), "--kind", "findings")
                self.assertEqual(code, 1)
                self.assertTrue(any("target_unreadable" in e for e in payload["errors"]))

    def test_ending_without_writing_fails_for_every_shape(self):
        for name, args, _ in self.shapes:
            with self.subTest(shape=name):
                review_id = self.publish(args)
                code, payload = _run(RESOLVE, *self.ids(review_id), "--kind", "findings")
                self.assertEqual(code, 1)
                self.assertTrue(payload["errors"])


if __name__ == "__main__":
    unittest.main()
