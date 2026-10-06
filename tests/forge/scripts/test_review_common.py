"""review_common.py（review の受け渡し script が共通で使う部品）の単体テスト。

DES-084 §6.1「共通の部品」と §7 の観点を確かめる。部品の使い手（publish_request.py など）が
その部品に期待する振る舞いを、ここで 1 回だけ確かめる。
"""

import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE = REPO_ROOT / "plugins" / "forge" / "scripts" / "review" / "review_common.py"

_spec = importlib.util.spec_from_file_location("review_common", MODULE)
common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(common)


class EmitTest(unittest.TestCase):
    def _emit(self, payload):
        out = io.StringIO()
        with redirect_stdout(out):
            common.emit(payload)
        return out.getvalue()

    def test_writes_one_json_object_on_one_line(self):
        text = self._emit({"b": 1, "a": 2})
        self.assertEqual(text.count("\n"), 1)
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(json.loads(text), {"a": 2, "b": 1})

    def test_keeps_non_ascii_as_is(self):
        text = self._emit({"理由": "日本語"})
        self.assertIn("日本語", text)
        self.assertNotIn("\\u", text)

    def test_keys_are_sorted(self):
        text = self._emit({"b": 1, "a": 2})
        self.assertLess(text.index('"a"'), text.index('"b"'))


class ErrorTest(unittest.TestCase):
    def test_returns_exit_code_1_and_prints_errors_array(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = common.error("理由 1", "理由 2")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue()), {"errors": ["理由 1", "理由 2"]})


class PublishJsonTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_publishes_utf8_json_and_leaves_no_temporary_file(self):
        target = self.dir / "out.json"
        common.publish_json(target, {"本文": "日本語\n改行"})
        self.assertEqual(json.loads(target.read_bytes().decode("utf-8")), {"本文": "日本語\n改行"})
        self.assertEqual([p.name for p in self.dir.iterdir()], ["out.json"])

    def test_target_name_does_not_exist_until_the_single_replace(self):
        target = self.dir / "out.json"
        real_replace = os.replace
        seen = {}

        def spy(src, dst):
            seen["target_existed"] = Path(dst).exists()
            seen["draft_is_complete_json"] = json.loads(Path(src).read_text(encoding="utf-8")) == {"k": "v"}
            seen["same_directory"] = Path(src).parent == Path(dst).parent
            real_replace(src, dst)

        with mock.patch.object(os, "replace", side_effect=spy):
            common.publish_json(target, {"k": "v"})
        self.assertEqual(seen, {"target_existed": False, "draft_is_complete_json": True, "same_directory": True})

    def test_failure_removes_the_temporary_file_and_does_not_create_the_target(self):
        target = self.dir / "out.json"
        with mock.patch.object(os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                common.publish_json(target, {"k": "v"})
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_unserializable_payload_removes_the_temporary_file(self):
        target = self.dir / "out.json"
        with self.assertRaises(TypeError):
            common.publish_json(target, {"k": object()})
        self.assertEqual(list(self.dir.iterdir()), [])


class NonAbsoluteTest(unittest.TestCase):
    def test_returns_only_the_values_that_are_not_absolute_in_given_order(self):
        self.assertEqual(common.non_absolute(["/a", "b/c", "/d", "./e"]), ["b/c", "./e"])

    def test_returns_empty_for_absolute_only_and_for_empty(self):
        self.assertEqual(common.non_absolute(["/a", "/b"]), [])
        self.assertEqual(common.non_absolute([]), [])


class ResultLocationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def test_review_dir_and_round_dir_are_resolved_from_the_project_root(self):
        self.assertEqual(common.review_dir(self.root, "r"), self.root / ".temp" / "review" / "r")
        self.assertEqual(common.round_dir(self.root, "r", 2), self.root / ".temp" / "review" / "r" / "2")

    def test_file_names_of_request_and_result(self):
        self.assertEqual(common.REQUEST_FILE, "review_request.json")
        self.assertEqual(common.RESULT_FILE, "review_result.json")
        self.assertEqual(common.EVALUATION_FILE, "evaluate_result.json")

    def test_load_result_returns_none_when_the_file_is_absent(self):
        self.assertIsNone(common.load_result(self.root))

    def test_load_result_reads_utf8_json(self):
        (self.root / common.RESULT_FILE).write_bytes(
            json.dumps({"findings": [{"body": "日本語"}]}, ensure_ascii=False).encode("utf-8")
        )
        self.assertEqual(common.load_result(self.root), {"findings": [{"body": "日本語"}]})

    def test_load_result_reads_the_named_file(self):
        (self.root / common.EVALUATION_FILE).write_text('{"evaluations": []}', encoding="utf-8")
        self.assertIsNone(common.load_result(self.root))
        self.assertEqual(common.load_result(self.root, common.EVALUATION_FILE), {"evaluations": []})

    def test_load_result_rejects_a_result_without_its_array(self):
        for file_name, text in (
            (common.RESULT_FILE, "{}"),
            (common.RESULT_FILE, '{"findings": {}}'),
            (common.RESULT_FILE, "[]"),
            (common.RESULT_FILE, "{壊れた JSON"),
            (common.EVALUATION_FILE, '{"findings": []}'),
            (common.EVALUATION_FILE, '{"evaluations": null}'),
        ):
            (self.root / file_name).write_text(text, encoding="utf-8")
            with self.assertRaises(ValueError, msg=(file_name, text)):
                common.load_result(self.root, file_name)

    def test_result_problem_reports_a_result_without_its_array_instead_of_raising(self):
        (self.root / common.EVALUATION_FILE).write_text('{"exit": "0"}', encoding="utf-8")
        self.assertIn("評価の結果を読めません", common.result_problem(self.root, common.EVALUATION_FILE, "評価の結果", 1))

    def test_missing_round_reports_missing_review_and_missing_round_and_none_when_present(self):
        self.assertIn("保持されていません", common.missing_round(self.root, "r", 1))
        common.round_dir(self.root, "r", 1).mkdir(parents=True)
        self.assertIsNone(common.missing_round(self.root, "r", 1))
        reason = common.missing_round(self.root, "r", 2)
        self.assertIn("ラウンドの置き場がありません", reason)
        self.assertIn("round_number=2", reason)

    def test_result_problem_judges_the_four_states(self):
        def problem():
            return common.result_problem(self.root, common.EVALUATION_FILE, "評価の結果", 1)

        self.assertIn("結果がありません", problem())
        path = self.root / common.EVALUATION_FILE
        path.write_text('{"evaluations": []}', encoding="utf-8")
        self.assertIn("封緘", problem())
        path.write_text('{"evaluations": [], "exit": "x"}', encoding="utf-8")
        self.assertIn('"x"', problem())
        path.write_text('{"evaluations": [], "exit": "0"}', encoding="utf-8")
        self.assertIsNone(problem())
        path.write_text("{not json", encoding="utf-8")
        self.assertIn("読めません", problem())

    def test_is_sealed_means_having_exit(self):
        self.assertFalse(common.is_sealed({"findings": []}))
        self.assertTrue(common.is_sealed({"findings": [], "exit": "0"}))
        self.assertTrue(common.is_sealed({"findings": [], "exit": "target_unreadable"}))


if __name__ == "__main__":
    unittest.main()
