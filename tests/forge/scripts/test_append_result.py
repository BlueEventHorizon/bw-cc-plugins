#!/usr/bin/env python3
"""append_result.py / seal_result.py の契約テスト（--kind findings と --kind evaluations）。

DES-084 §6.3・§6.4・§7 と DES-083 §6.2・§6.3・§7 の観点を確かめる。

--kind findings:

- finding_id が 1 つのレビューで連番になる（第 2 ラウンド以降、0 件のラウンドを挟んだ場合を含む）
- 封緘後の追記を拒む。--exit は "0" と target_unreadable だけで、定義外は終了コード 2
- 結果が無くても封緘でき、空配列の結果が作られる
- 本文は標準入力から加工せずに保持する。location は 1 個以上が必須で、渡された順に保持する

--kind evaluations:

- DES-083 §6.2 のエラー表の各条件が、1 つ 1 つ終了コード 1 で拒まれ、何も書かれない
- evaluator が前ラウンドで採った番号を含めて finding_id が連番になる
- seal は、引かれていない所見が残るとき失敗し、その finding_id をすべて返す。exit は "0" だけ
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = REPO_ROOT / "plugins" / "forge" / "scripts" / "review"
APPEND = SCRIPT_DIR / "append_result.py"
SEAL = SCRIPT_DIR / "seal_result.py"

TRICKY_TEXT = "1 行目\n\"二重引用符\" と '単一引用符'\n`バッククォート` と ```fence```\n日本語・絵文字 \U0001F600\n$HOME $(x) \\n 末尾改行\n"


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


class _ReviewFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.review_id = "a" * 32
        self.loc = str(self.root / "docs" / "a.md") + ":1"
        self.make_round(1)

    def make_round(self, n):
        (self.root / ".temp" / "review" / self.review_id / str(n)).mkdir(parents=True, exist_ok=True)

    def result_path(self, n):
        return self.root / ".temp" / "review" / self.review_id / str(n) / "review_result.json"

    def result(self, n):
        return json.loads(self.result_path(n).read_text(encoding="utf-8"))

    def append(self, n, body="本文", locations=None, cwd=None):
        locations = locations or [self.loc]
        return _run(
            APPEND, str(self.root), self.review_id, str(n), "--kind", "findings",
            "--location", *locations, stdin=body, cwd=cwd,
        )

    def seal(self, n, *extra, cwd=None):
        return _run(SEAL, str(self.root), self.review_id, str(n), "--kind", "findings", *extra, cwd=cwd)


class AppendResultTest(_ReviewFixture):
    def test_first_finding_is_numbered_one_and_written(self):
        code, payload = self.append(1, body="本文 A")
        self.assertEqual((code, payload), (0, {"finding_id": 1}))
        self.assertEqual(
            self.result(1), {"findings": [{"finding_id": 1, "location": [self.loc], "body": "本文 A"}]}
        )

    def test_numbers_are_consecutive_within_a_round(self):
        ids = [self.append(1)[1]["finding_id"] for _ in range(3)]
        self.assertEqual(ids, [1, 2, 3])
        self.assertEqual([f["finding_id"] for f in self.result(1)["findings"]], [1, 2, 3])

    def test_numbering_continues_in_later_rounds(self):
        self.append(1)
        self.append(1)
        self.seal(1)
        self.make_round(2)
        self.assertEqual(self.append(2)[1], {"finding_id": 3})
        self.assertEqual(self.append(2)[1], {"finding_id": 4})
        self.assertEqual([f["finding_id"] for f in self.result(2)["findings"]], [3, 4])

    def test_numbering_skips_over_a_round_with_no_findings(self):
        self.append(1)
        self.seal(1)
        self.make_round(2)
        self.seal(2)  # reviewer が 0 件のラウンド
        self.make_round(3)
        self.assertEqual(self.append(3)[1], {"finding_id": 2})

    def test_numbering_after_empty_first_round_starts_at_one(self):
        self.seal(1)
        self.make_round(2)
        self.assertEqual(self.append(2)[1], {"finding_id": 1})

    def test_numbering_uses_the_maximum_across_all_rounds_not_the_count(self):
        self.append(1)
        self.append(1)
        self.seal(1)
        self.make_round(2)
        self.seal(2)
        self.make_round(3)
        self.append(3)
        self.seal(3)
        self.make_round(4)
        self.assertEqual(self.append(4)[1], {"finding_id": 4})

    def test_other_reviews_are_not_counted(self):
        self.append(1)
        other = self.root / ".temp" / "review" / ("b" * 32) / "1"
        other.mkdir(parents=True)
        code, payload = _run(
            APPEND, str(self.root), "b" * 32, "1", "--kind", "findings", "--location", self.loc, stdin="x"
        )
        self.assertEqual((code, payload), (0, {"finding_id": 1}))

    def test_append_to_sealed_result_is_rejected_with_exit_1(self):
        self.append(1)
        self.seal(1)
        before = self.result_path(1).read_bytes()
        code, payload = self.append(1)
        self.assertEqual(code, 1)
        self.assertIsInstance(payload["errors"], list)
        self.assertEqual(self.result_path(1).read_bytes(), before)

    def test_append_to_sealed_empty_result_is_rejected(self):
        self.seal(1)
        code, payload = self.append(1)
        self.assertEqual(code, 1)
        self.assertEqual(self.result(1), {"findings": [], "exit": "0"})

    def test_missing_round_directory_fails(self):
        code, payload = self.append(9)
        self.assertEqual(code, 1)
        self.assertIsInstance(payload["errors"], list)

    def test_missing_review_fails_without_creating_anything(self):
        code, payload = _run(
            APPEND, str(self.root), "c" * 32, "1", "--kind", "findings", "--location", self.loc, stdin="x"
        )
        self.assertEqual(code, 1)
        self.assertFalse((self.root / ".temp" / "review" / ("c" * 32)).exists())

    def test_empty_body_fails_and_writes_nothing(self):
        for body in ("", "  \n"):
            code, payload = self.append(1, body=body)
            self.assertEqual(code, 1)
            self.assertIsInstance(payload["errors"], list)
        self.assertFalse(self.result_path(1).exists())

    def test_non_utf8_body_fails(self):
        completed = subprocess.run(
            [sys.executable, str(APPEND), str(self.root), self.review_id, "1", "--kind", "findings",
             "--location", self.loc],
            input=b"\xff\xfe\x00bad", capture_output=True,
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("errors", json.loads(completed.stdout))

    def test_body_is_kept_identically_from_stdin(self):
        self.append(1, body=TRICKY_TEXT)
        self.assertEqual(self.result(1)["findings"][0]["body"], TRICKY_TEXT)

    def test_crlf_body_is_not_translated(self):
        self.append(1, body="a\r\nb\r\n")
        self.assertEqual(self.result(1)["findings"][0]["body"], "a\r\nb\r\n")

    def test_locations_are_kept_in_given_order(self):
        locations = [str(self.root / "b.md") + ":9", str(self.root / "a.md") + ":1-3", str(self.root / "b.md") + ":2"]
        self.append(1, locations=locations)
        self.assertEqual(self.result(1)["findings"][0]["location"], locations)

    def test_unknown_location_marker_is_accepted_as_is(self):
        code, _ = self.append(1, locations=["位置未確定"])
        self.assertEqual(code, 0)
        self.assertEqual(self.result(1)["findings"][0]["location"], ["位置未確定"])

    def test_relative_location_is_rejected(self):
        code, payload = self.append(1, locations=[self.loc, "docs/b.md:3"])
        self.assertEqual(code, 1)
        self.assertIsInstance(payload["errors"], list)
        self.assertFalse(self.result_path(1).exists())

    def test_missing_location_is_an_argument_error(self):
        code, _ = _run(APPEND, str(self.root), self.review_id, "1", "--kind", "findings", stdin="x")
        self.assertEqual(code, 2)

    def test_kind_is_required_and_only_findings_and_evaluations_are_accepted(self):
        code, _ = _run(APPEND, str(self.root), self.review_id, "1", "--location", self.loc, stdin="x")
        self.assertEqual(code, 2)
        code, _ = _run(
            APPEND, str(self.root), self.review_id, "1", "--kind", "other", "--location", self.loc, stdin="x"
        )
        self.assertEqual(code, 2)

    def test_findings_kind_does_not_accept_evaluation_arguments(self):
        code, _ = _run(
            APPEND, str(self.root), self.review_id, "1", "--kind", "findings", "--location", self.loc,
            "--disposition", "valid", stdin="x",
        )
        self.assertEqual(code, 2)
        self.assertFalse(self.result_path(1).exists())

    def test_non_integer_round_number_is_an_argument_error(self):
        code, _ = _run(APPEND, str(self.root), self.review_id, "x", "--kind", "findings", "--location", self.loc)
        self.assertEqual(code, 2)

    def test_stdout_is_json_object_without_body(self):
        _, payload = self.append(1, body="秘密の本文")
        self.assertEqual(set(payload), {"finding_id"})

    def test_error_output_is_json_with_errors_array_only(self):
        _, payload = self.append(9)
        self.assertEqual(set(payload), {"errors"})
        self.assertTrue(all(isinstance(e, str) for e in payload["errors"]))

    def test_same_result_regardless_of_working_directory(self):
        other = self.root / "docs"
        other.mkdir()
        self.append(1, cwd=str(other))
        self.assertTrue(self.result_path(1).is_file())
        self.assertFalse((other / ".temp").exists())

    def test_no_draft_file_remains(self):
        self.append(1)
        names = [p.name for p in self.result_path(1).parent.iterdir()]
        self.assertEqual(names, ["review_result.json"])

    def test_corrupt_result_of_the_round_fails_as_json_errors_and_writes_nothing(self):
        self.result_path(1).write_text("{壊れた JSON", encoding="utf-8")
        code, payload = self.append(1)
        self.assertEqual(code, 1)
        self.assertEqual(set(payload), {"errors"})
        self.assertEqual(self.result_path(1).read_text(encoding="utf-8"), "{壊れた JSON")

    def test_result_without_findings_array_fails_as_json_errors_and_keeps_the_file(self):
        self.result_path(1).write_text("{}", encoding="utf-8")
        code, payload = self.append(1)
        self.assertEqual(code, 1)
        self.assertEqual(set(payload), {"errors"})
        self.assertEqual(self.result_path(1).read_text(encoding="utf-8"), "{}")

    def test_seal_of_result_without_findings_array_fails_as_json_errors_and_keeps_the_file(self):
        self.result_path(1).write_text("{}", encoding="utf-8")
        code, payload = self.seal(1)
        self.assertEqual(code, 1)
        self.assertEqual(set(payload), {"errors"})
        self.assertEqual(self.result_path(1).read_text(encoding="utf-8"), "{}")

    def test_corrupt_result_of_another_round_fails_as_json_errors_and_writes_nothing(self):
        self.make_round(2)
        self.result_path(2).write_text('{"findings": [{"body": "finding_id が無い"}]}', encoding="utf-8")
        code, payload = self.append(1)
        self.assertEqual(code, 1)
        self.assertEqual(set(payload), {"errors"})
        self.assertFalse(self.result_path(1).exists())


class SealResultTest(_ReviewFixture):
    def test_seal_default_exit_is_zero_string(self):
        self.append(1)
        code, payload = self.seal(1)
        self.assertEqual((code, payload), (0, {}))
        result = self.result(1)
        self.assertEqual(result["exit"], "0")
        self.assertEqual([f["finding_id"] for f in result["findings"]], [1])

    def test_seal_creates_empty_findings_when_no_result(self):
        self.assertFalse(self.result_path(1).exists())
        code, _ = self.seal(1)
        self.assertEqual(code, 0)
        self.assertEqual(self.result(1), {"findings": [], "exit": "0"})

    def test_seal_with_target_unreadable(self):
        code, _ = self.seal(1, "--exit", "target_unreadable")
        self.assertEqual(code, 0)
        self.assertEqual(self.result(1), {"findings": [], "exit": "target_unreadable"})

    def test_explicit_zero_exit_is_accepted(self):
        code, _ = self.seal(1, "--exit", "0")
        self.assertEqual(code, 0)
        self.assertEqual(self.result(1)["exit"], "0")

    def test_undefined_exit_value_is_an_argument_error_and_writes_nothing(self):
        for value in ("1", "other", "", "TARGET_UNREADABLE"):
            code, _ = self.seal(1, "--exit", value)
            self.assertEqual(code, 2, value)
        self.assertFalse(self.result_path(1).exists())

    def test_second_seal_fails_and_keeps_first_exit(self):
        self.seal(1, "--exit", "target_unreadable")
        code, payload = self.seal(1)
        self.assertEqual(code, 1)
        self.assertIsInstance(payload["errors"], list)
        self.assertEqual(self.result(1)["exit"], "target_unreadable")

    def test_missing_round_directory_fails(self):
        code, payload = self.seal(9)
        self.assertEqual(code, 1)
        self.assertIsInstance(payload["errors"], list)

    def test_kind_is_required_and_only_findings_and_evaluations_are_accepted(self):
        code, _ = _run(SEAL, str(self.root), self.review_id, "1")
        self.assertEqual(code, 2)
        code, _ = _run(SEAL, str(self.root), self.review_id, "1", "--kind", "other")
        self.assertEqual(code, 2)

    def test_same_result_regardless_of_working_directory(self):
        other = self.root / "docs"
        other.mkdir()
        self.seal(1, cwd=str(other))
        self.assertTrue(self.result_path(1).is_file())
        self.assertFalse((other / ".temp").exists())

    def test_sealed_result_keeps_key_order_findings_then_exit(self):
        self.append(1)
        self.seal(1)
        self.assertEqual(list(self.result(1)), ["findings", "exit"])



class _EvaluationFixture(_ReviewFixture):
    """所見を 2 件（finding_id 1・2）書いて封緘した第 1 ラウンドを用意する。"""

    def setUp(self):
        super().setUp()
        self.append(1, body="所見 1")
        self.append(1, body="所見 2")
        self.seal(1)
        self.new_loc = str(self.root / "docs" / "b.md") + ":7"

    def eval_path(self, n):
        return self.root / ".temp" / "review" / self.review_id / str(n) / "evaluate_result.json"

    def evaluations(self, n):
        return json.loads(self.eval_path(n).read_text(encoding="utf-8"))

    def evaluate(self, n=1, *args, reason="根拠", cwd=None):
        return _run(
            APPEND, str(self.root), self.review_id, str(n), "--kind", "evaluations", *args, stdin=reason, cwd=cwd
        )

    def valid(self, n=1, *findings, extra=(), reason="根拠"):
        args = ["--disposition", "valid", "--severity", "major", "--confidence", "confirmed",
                "--fix-confident", "true"]
        if findings:
            args += ["--findings", *map(str, findings)]
        return self.evaluate(n, *args, *extra, reason=reason)

    def seal_evaluations(self, n=1, *extra, cwd=None):
        return _run(SEAL, str(self.root), self.review_id, str(n), "--kind", "evaluations", *extra, cwd=cwd)

    def assert_rejected_and_nothing_written(self, outcome, snapshot=None):
        code, payload = outcome
        self.assertEqual(code, 1)
        self.assertEqual(set(payload), {"errors"})
        self.assertTrue(payload["errors"])
        if snapshot is None:
            self.assertFalse(self.eval_path(1).exists())
        else:
            self.assertEqual(self.eval_path(1).read_bytes(), snapshot)
        return payload["errors"]


class AppendEvaluationsTest(_EvaluationFixture):
    def test_valid_evaluation_is_written_in_the_documented_shape(self):
        code, payload = self.valid(1, 1, reason="根拠 A")
        self.assertEqual((code, payload), (0, {}))
        self.assertEqual(
            self.evaluations(1),
            {"evaluations": [{
                "finding_ids": [1], "disposition": "valid", "severity": "major", "reason": "根拠 A",
                "confidence": "confirmed", "fix_confident": True,
            }]},
        )
        self.assertEqual(
            list(self.evaluations(1)["evaluations"][0]),
            ["finding_ids", "disposition", "severity", "reason", "confidence", "fix_confident"],
        )

    def test_one_evaluation_may_bundle_several_findings_in_given_order(self):
        self.valid(1, 2, 1)
        self.assertEqual(self.evaluations(1)["evaluations"][0]["finding_ids"], [2, 1])

    def test_a_finding_may_be_referenced_by_several_evaluations(self):
        self.valid(1, 1)
        self.valid(1, 1)
        self.assertEqual(len(self.evaluations(1)["evaluations"]), 2)

    def test_non_valid_evaluation_has_neither_confidence_nor_fix_confident(self):
        code, _ = self.evaluate(1, "--disposition", "invalid", "--severity", "minor", "--findings", "1", reason="退ける根拠")
        self.assertEqual(code, 0)
        evaluation = self.evaluations(1)["evaluations"][0]
        self.assertEqual(set(evaluation), {"finding_ids", "disposition", "severity", "reason"})

    def test_every_non_valid_disposition_is_accepted(self):
        for disposition in ("invalid", "misunderstanding", "out_of_scope", "flawed_premise"):
            code, _ = self.evaluate(1, "--disposition", disposition, "--severity", "minor", "--findings", "1")
            self.assertEqual(code, 0, disposition)

    def test_fix_confident_false_does_not_require_confirmed(self):
        code, _ = self.evaluate(
            1, "--disposition", "valid", "--severity", "minor", "--confidence", "unverified",
            "--fix-confident", "false", "--findings", "1",
        )
        self.assertEqual(code, 0)
        evaluation = self.evaluations(1)["evaluations"][0]
        self.assertEqual((evaluation["confidence"], evaluation["fix_confident"]), ("unverified", False))

    def test_reason_is_kept_identically_from_stdin(self):
        self.valid(1, 1, reason=TRICKY_TEXT)
        self.assertEqual(self.evaluations(1)["evaluations"][0]["reason"], TRICKY_TEXT)

    def test_stdout_is_an_empty_object_without_new(self):
        self.assertEqual(self.valid(1, 1), (0, {}))

    # --new と採番

    def test_evaluation_result_without_evaluations_array_fails_as_json_errors_and_keeps_the_file(self):
        self.eval_path(1).write_text("{}", encoding="utf-8")
        self.assert_rejected_and_nothing_written(self.valid(1, 1), snapshot=b"{}")
        self.assert_rejected_and_nothing_written(self.seal_evaluations(1), snapshot=b"{}")

    def test_new_with_corrupt_result_of_another_round_fails_as_json_errors_and_writes_nothing(self):
        self.make_round(2)
        self.result_path(2).write_text("{壊れた JSON", encoding="utf-8")
        outcome = self.valid(1, extra=["--new", "--location", self.new_loc])
        self.assert_rejected_and_nothing_written(outcome)

    def test_new_takes_the_next_number_after_the_reviewers_and_returns_it(self):
        code, payload = self.valid(1, extra=["--new", "--location", self.new_loc])
        self.assertEqual((code, payload), (0, {"finding_id": 3}))
        evaluation = self.evaluations(1)["evaluations"][0]
        self.assertEqual(evaluation["finding_ids"], [3])
        self.assertEqual(evaluation["location"], [self.new_loc])

    def test_new_with_findings_bundles_the_reviewers_findings_and_puts_new_last(self):
        code, payload = self.valid(1, 2, 1, extra=["--new", "--location", self.new_loc])
        self.assertEqual((code, payload), (0, {"finding_id": 3}))
        self.assertEqual(self.evaluations(1)["evaluations"][0]["finding_ids"], [2, 1, 3])

    def test_two_new_evaluations_get_consecutive_numbers(self):
        self.valid(1, extra=["--new", "--location", self.new_loc])
        code, payload = self.valid(1, extra=["--new", "--location", self.new_loc])
        self.assertEqual((code, payload), (0, {"finding_id": 4}))

    def test_numbering_with_no_reviewer_findings_starts_at_one(self):
        self.make_round(2)
        self.seal(2)
        code, payload = self.valid(2, extra=["--new", "--location", self.new_loc])
        self.assertEqual((code, payload), (0, {"finding_id": 3}))

    def test_numbers_are_consecutive_across_rounds_including_the_evaluators_own(self):
        self.valid(1, 1)
        self.valid(1, 2, extra=["--new", "--location", self.new_loc])  # 3 を evaluator が採る
        self.seal_evaluations(1)
        self.make_round(2)
        # 第 2 ラウンドの reviewer は、前ラウンドで evaluator が採った 3 を踏まえて 4 を採る
        self.assertEqual(self.append(2)[1], {"finding_id": 4})
        self.seal(2)
        self.assertEqual(self.valid(2, extra=["--new", "--location", self.new_loc])[1], {"finding_id": 5})

    def test_evaluator_new_number_is_seen_by_the_reviewer_numbering_in_a_later_round(self):
        self.valid(1, 1, 2)
        self.valid(1, extra=["--new", "--location", self.new_loc])
        self.seal_evaluations(1)
        self.make_round(2)
        self.assertEqual(self.append(2)[1], {"finding_id": 4})

    def test_findings_numbering_in_the_same_round_is_unaffected_by_evaluations_of_that_round(self):
        # 所見は評価より先に書かれる。評価が無い通常の連番は従来どおり
        self.make_round(2)
        self.assertEqual([self.append(2)[1]["finding_id"] for _ in range(2)], [3, 4])

    def test_a_new_number_can_be_bundled_by_a_later_evaluation_with_location(self):
        self.valid(1, extra=["--new", "--location", self.new_loc])  # 3
        code, _ = self.valid(1, 3, extra=["--location", self.new_loc])
        self.assertEqual(code, 0)
        self.assertEqual(self.evaluations(1)["evaluations"][1]["finding_ids"], [3])
        self.assertEqual(self.evaluations(1)["evaluations"][1]["location"], [self.new_loc])

    def test_unknown_location_marker_is_accepted_for_a_new_finding(self):
        code, _ = self.valid(1, extra=["--new", "--location", "位置未確定"])
        self.assertEqual(code, 0)
        self.assertEqual(self.evaluations(1)["evaluations"][0]["location"], ["位置未確定"])

    # §6.2 のエラー表: 1 つ 1 つ終了コード 1 で拒み、何も書かない

    def test_error_findings_result_is_not_sealed(self):
        self.make_round(2)
        self.append(2)  # 所見は書いたが封緘していない
        self.assert_rejected_and_nothing_written_in(2, self.valid(2, 3))

    def assert_rejected_and_nothing_written_in(self, n, outcome):
        code, payload = outcome
        self.assertEqual(code, 1)
        self.assertTrue(payload["errors"])
        self.assertFalse(self.eval_path(n).exists())

    def test_error_findings_result_is_missing(self):
        self.make_round(2)
        self.assert_rejected_and_nothing_written_in(2, self.valid(2, 1))

    def test_error_findings_result_ended_with_an_error_value(self):
        self.make_round(2)
        self.seal(2, "--exit", "target_unreadable")
        self.assert_rejected_and_nothing_written_in(2, self.valid(2, 1))

    def test_error_evaluations_already_sealed(self):
        self.valid(1, 1)
        self.valid(1, 2)
        self.seal_evaluations(1)
        before = self.eval_path(1).read_bytes()
        self.assert_rejected_and_nothing_written(self.valid(1, 1), before)

    def test_error_neither_findings_nor_new(self):
        outcome = self.evaluate(
            1, "--disposition", "valid", "--severity", "major", "--confidence", "confirmed", "--fix-confident", "true"
        )
        self.assert_rejected_and_nothing_written(outcome)

    def test_error_referencing_a_number_that_does_not_exist_puts_the_number_in_errors(self):
        errors = self.assert_rejected_and_nothing_written(self.valid(1, 1, 9))
        self.assertTrue(any("9" in e for e in errors))

    def test_error_referencing_a_new_number_that_has_not_been_taken_yet(self):
        self.assert_rejected_and_nothing_written(self.valid(1, 3, extra=["--location", self.new_loc]))

    def test_error_a_number_from_another_round_is_not_referenceable(self):
        self.valid(1, 1)
        self.valid(1, 2, extra=["--new", "--location", self.new_loc])  # 3
        self.seal_evaluations(1)
        self.make_round(2)
        self.append(2)  # 4
        self.seal(2)
        self.assert_rejected_and_nothing_written_in(2, self.valid(2, 1))
        self.assert_rejected_and_nothing_written_in(2, self.valid(2, 3, extra=["--location", self.new_loc]))

    def test_error_new_without_location(self):
        self.assert_rejected_and_nothing_written(self.valid(1, extra=["--new"]))

    def test_error_bundling_an_existing_new_number_without_location(self):
        self.valid(1, extra=["--new", "--location", self.new_loc])  # 3
        snapshot = self.eval_path(1).read_bytes()
        self.assert_rejected_and_nothing_written(self.valid(1, 3), snapshot)

    def test_error_location_without_a_new_number(self):
        self.assert_rejected_and_nothing_written(self.valid(1, 1, extra=["--location", self.new_loc]))

    def test_error_relative_location(self):
        self.assert_rejected_and_nothing_written(self.valid(1, extra=["--new", "--location", "docs/b.md:7"]))

    def test_error_new_with_a_disposition_other_than_valid(self):
        outcome = self.evaluate(
            1, "--disposition", "invalid", "--severity", "minor", "--new", "--location", self.new_loc
        )
        self.assert_rejected_and_nothing_written(outcome)

    def test_error_valid_without_confidence(self):
        outcome = self.evaluate(
            1, "--disposition", "valid", "--severity", "major", "--fix-confident", "false", "--findings", "1"
        )
        self.assert_rejected_and_nothing_written(outcome)

    def test_error_valid_without_fix_confident(self):
        outcome = self.evaluate(
            1, "--disposition", "valid", "--severity", "major", "--confidence", "confirmed", "--findings", "1"
        )
        self.assert_rejected_and_nothing_written(outcome)

    def test_error_non_valid_with_confidence_or_fix_confident(self):
        for extra in (["--confidence", "confirmed"], ["--fix-confident", "false"]):
            outcome = self.evaluate(
                1, "--disposition", "invalid", "--severity", "minor", "--findings", "1", *extra
            )
            self.assert_rejected_and_nothing_written(outcome)

    def test_error_fix_confident_true_without_confirmed(self):
        for confidence in ("inferred", "unverified"):
            outcome = self.evaluate(
                1, "--disposition", "valid", "--severity", "major", "--confidence", confidence,
                "--fix-confident", "true", "--findings", "1",
            )
            self.assert_rejected_and_nothing_written(outcome)

    def test_error_empty_reason(self):
        for reason in ("", "  \n"):
            self.assert_rejected_and_nothing_written(self.valid(1, 1, reason=reason))

    def test_error_non_utf8_reason(self):
        completed = subprocess.run(
            [sys.executable, str(APPEND), str(self.root), self.review_id, "1", "--kind", "evaluations",
             "--disposition", "invalid", "--severity", "minor", "--findings", "1"],
            input=b"\xff\xfe\x00bad", capture_output=True,
        )
        self.assertEqual(completed.returncode, 1)
        self.assertFalse(self.eval_path(1).exists())

    def test_error_missing_round_directory(self):
        self.assert_rejected_and_nothing_written_in(9, self.valid(9, 1))

    def test_a_rejected_append_leaves_earlier_evaluations_untouched(self):
        self.valid(1, 1)
        before = self.eval_path(1).read_bytes()
        self.assert_rejected_and_nothing_written(self.valid(1, 9), before)

    # 引数の誤り（終了コード 2）

    def test_argument_errors_are_exit_code_2(self):
        base = [APPEND, str(self.root), self.review_id, "1", "--kind", "evaluations"]
        cases = {
            "disposition 無し": ["--severity", "major", "--findings", "1"],
            "severity 無し": ["--disposition", "invalid", "--findings", "1"],
            "定義外の disposition": ["--disposition", "x", "--severity", "major", "--findings", "1"],
            "定義外の severity": ["--disposition", "invalid", "--severity", "x", "--findings", "1"],
            "定義外の confidence": ["--disposition", "valid", "--severity", "major", "--confidence", "x",
                                    "--fix-confident", "false", "--findings", "1"],
            "定義外の fix-confident": ["--disposition", "valid", "--severity", "major", "--confidence",
                                       "confirmed", "--fix-confident", "yes", "--findings", "1"],
            "整数でない番号": ["--disposition", "invalid", "--severity", "major", "--findings", "a"],
        }
        for name, args in cases.items():
            code, _ = _run(*base, *args, stdin="根拠")
            self.assertEqual(code, 2, name)
        self.assertFalse(self.eval_path(1).exists())

    def test_findings_result_is_not_touched(self):
        before = self.result_path(1).read_bytes()
        self.valid(1, 1)
        self.assertEqual(self.result_path(1).read_bytes(), before)

    def test_no_draft_file_remains(self):
        self.valid(1, 1)
        names = sorted(p.name for p in self.eval_path(1).parent.iterdir())
        self.assertEqual(names, ["evaluate_result.json", "review_result.json"])

    def test_same_result_regardless_of_working_directory(self):
        other = self.root / "docs"
        other.mkdir()
        self.evaluate(1, "--disposition", "invalid", "--severity", "minor", "--findings", "1", cwd=str(other))
        self.assertTrue(self.eval_path(1).is_file())
        self.assertFalse((other / ".temp").exists())


class SealEvaluationsTest(_EvaluationFixture):
    def test_seal_writes_exit_zero_after_all_findings_are_referenced(self):
        self.valid(1, 1)
        self.valid(1, 2)
        code, payload = self.seal_evaluations(1)
        self.assertEqual((code, payload), (0, {}))
        result = self.evaluations(1)
        self.assertEqual(result["exit"], "0")
        self.assertEqual(list(result), ["evaluations", "exit"])

    def test_one_evaluation_bundling_all_findings_is_enough(self):
        self.valid(1, 1, 2)
        self.assertEqual(self.seal_evaluations(1)[0], 0)

    def test_unreferenced_findings_fail_and_all_numbers_are_returned_and_nothing_is_written(self):
        code, payload = self.seal_evaluations(1)
        self.assertEqual(code, 1)
        self.assertEqual(set(payload), {"errors"})
        text = "\n".join(payload["errors"])
        self.assertIn("finding_id=1", text)
        self.assertIn("finding_id=2", text)
        self.assertFalse(self.eval_path(1).exists())

    def test_partially_referenced_returns_only_the_remaining_numbers(self):
        self.valid(1, 2)
        before = self.eval_path(1).read_bytes()
        code, payload = self.seal_evaluations(1)
        self.assertEqual(code, 1)
        self.assertEqual(len(payload["errors"]), 1)
        self.assertIn("finding_id=1", payload["errors"][0])
        self.assertEqual(self.eval_path(1).read_bytes(), before)

    def test_adding_the_missing_evaluation_then_sealing_succeeds(self):
        self.valid(1, 1)
        self.assertEqual(self.seal_evaluations(1)[0], 1)
        self.valid(1, 2)
        self.assertEqual(self.seal_evaluations(1)[0], 0)

    def test_a_new_finding_alone_does_not_cover_the_reviewers_findings(self):
        self.valid(1, extra=["--new", "--location", self.new_loc])
        code, payload = self.seal_evaluations(1)
        self.assertEqual(code, 1)
        self.assertEqual(len(payload["errors"]), 2)

    def test_zero_findings_creates_an_empty_result_with_exit_zero(self):
        self.make_round(2)
        self.seal(2)
        code, _ = self.seal_evaluations(2)
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(self.eval_path(2).read_text(encoding="utf-8")), {"evaluations": [], "exit": "0"}
        )

    def test_zero_findings_with_only_a_new_finding_can_be_sealed(self):
        self.make_round(2)
        self.seal(2)
        self.valid(2, extra=["--new", "--location", self.new_loc])
        self.assertEqual(self.seal_evaluations(2)[0], 0)

    def test_exit_must_be_zero_only(self):
        for value in ("target_unreadable", "1", "other", ""):
            code, _ = self.seal_evaluations(1, "--exit", value)
            self.assertEqual(code, 2, value)
        self.assertFalse(self.eval_path(1).exists())

    def test_explicit_zero_exit_is_accepted(self):
        self.valid(1, 1, 2)
        self.assertEqual(self.seal_evaluations(1, "--exit", "0")[0], 0)

    def test_error_findings_result_is_not_sealed_or_missing_or_an_error(self):
        self.make_round(2)
        self.assertEqual(self.seal_evaluations(2)[0], 1)  # 所見の結果が無い
        self.append(2)
        self.assertEqual(self.seal_evaluations(2)[0], 1)  # 封緘されていない
        self.seal(2, "--exit", "target_unreadable")
        self.assertEqual(self.seal_evaluations(2)[0], 1)  # エラー値
        self.assertFalse(self.eval_path(2).exists())

    def test_error_second_seal_keeps_the_first(self):
        self.valid(1, 1, 2)
        self.seal_evaluations(1)
        before = self.eval_path(1).read_bytes()
        code, payload = self.seal_evaluations(1)
        self.assertEqual(code, 1)
        self.assertIsInstance(payload["errors"], list)
        self.assertEqual(self.eval_path(1).read_bytes(), before)

    def test_error_missing_round_directory(self):
        self.assertEqual(self.seal_evaluations(9)[0], 1)

    def test_after_sealing_append_is_rejected(self):
        self.valid(1, 1, 2)
        self.seal_evaluations(1)
        self.assertEqual(self.valid(1, 1)[0], 1)

    def test_a_later_round_does_not_need_the_earlier_rounds_findings_to_be_referenced(self):
        self.valid(1, 1, 2)
        self.seal_evaluations(1)
        self.make_round(2)
        self.append(2)  # 3
        self.seal(2)
        self.assertEqual(self.seal_evaluations(2)[0], 1)
        self.valid(2, 3)
        self.assertEqual(self.seal_evaluations(2)[0], 0)

    def test_same_result_regardless_of_working_directory(self):
        self.valid(1, 1, 2)
        other = self.root / "docs"
        other.mkdir()
        self.seal_evaluations(1, cwd=str(other))
        self.assertTrue(self.eval_path(1).is_file())
        self.assertFalse((other / ".temp").exists())


if __name__ == "__main__":
    unittest.main()
