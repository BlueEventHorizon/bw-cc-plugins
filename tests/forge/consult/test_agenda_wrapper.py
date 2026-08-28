#!/usr/bin/env python3
"""agenda_wrapper.py（起点から置き場・config を解決し agenda_store.py へ委譲する CLI）のテスト。

実行:
  python3 -m unittest tests.forge.consult.test_agenda_wrapper -v
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "forge"
    / "skills"
    / "consult"
    / "scripts"
    / "agenda_wrapper.py"
)
_SPEC = importlib.util.spec_from_file_location("agenda_wrapper", _MODULE_PATH)
agenda_wrapper = importlib.util.module_from_spec(_SPEC)
sys.modules["agenda_wrapper"] = agenda_wrapper
_SPEC.loader.exec_module(agenda_wrapper)


class ResolveTargetTest(unittest.TestCase):

    def test_review_origin_resolves_fixed_path_and_severity_config(self):
        path, config, error = agenda_wrapper.resolve_target("review", None)
        self.assertIsNone(error)
        self.assertEqual(path, ".claude/.temp/review/agenda.json")
        self.assertEqual(config, {"item_fields": ["severity"], "severity_field": "severity"})

    def test_consult_origin_resolves_session_scoped_path(self):
        path, config, error = agenda_wrapper.resolve_target("consult", "sess-1")
        self.assertIsNone(error)
        self.assertEqual(path, ".claude/.temp/consult/sess-1/agenda.json")
        self.assertEqual(config, {"item_fields": [], "severity_field": None})

    def test_consult_origin_without_session_id_errors(self):
        path, config, error = agenda_wrapper.resolve_target("consult", None)
        self.assertIsNone(path)
        self.assertIsNotNone(error)

    def test_unknown_origin_errors(self):
        path, config, error = agenda_wrapper.resolve_target("bogus", None)
        self.assertIsNotNone(error)


class RunTestCase(unittest.TestCase):
    """`run()` を通した end-to-end 検証（一時ディレクトリ配下に実ファイルを書く）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._orig_cwd = Path.cwd()
        import os

        os.chdir(self._tmp.name)
        self.addCleanup(os.chdir, str(self._orig_cwd))
        self._candidate_counter = 0

    def _write(self, obj) -> str:
        self._candidate_counter += 1
        path = Path(self._tmp.name) / f"candidate-{self._candidate_counter}.json"
        path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def _run(self, argv):
        parser = agenda_wrapper.build_parser()
        args = parser.parse_args(argv)
        return agenda_wrapper.run(args)


class PendingBeforeStartTest(RunTestCase):

    def test_review_pending_on_missing_file_reports_not_exists(self):
        result = self._run(["--origin", "review", "pending"])
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["exists"])
        self.assertEqual(result["remaining_count"], 0)
        self.assertEqual(result["path"], ".claude/.temp/review/agenda.json")

    def test_consult_pending_on_missing_file_reports_not_exists(self):
        result = self._run(["--origin", "consult", "--session-id", "sess-1", "pending"])
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["exists"])


class StartInjectsResolvedConfigTest(RunTestCase):

    def test_review_start_injects_severity_config_without_caller_specifying_it(self):
        # 呼び出し元は config を含めない（structural_judgment・items のみ）。
        candidate_path = self._write(
            {
                "structural_judgment": {"note": "同型の指摘は無い"},
                "items": [{"id": "01", "title": "所見1", "fields": {"severity": "major"}}],
            }
        )
        result = self._run(["--origin", "review", "start", "--input-file", candidate_path])
        self.assertEqual(result["status"], "ok")

        record = json.loads(Path(".claude/.temp/review/agenda.json").read_text(encoding="utf-8"))
        self.assertEqual(record["config"]["item_fields"], ["severity"])
        self.assertEqual(record["config"]["severity_field"], "severity")
        self.assertEqual(record["config"]["identity"], "review")

    def test_consult_start_injects_empty_config(self):
        candidate_path = self._write(
            {
                "structural_judgment": {"note": "初期判定"},
                "items": [{"id": "01", "title": "論点1"}],
            }
        )
        result = self._run(
            ["--origin", "consult", "--session-id", "sess-1", "start", "--input-file", candidate_path]
        )
        self.assertEqual(result["status"], "ok")

        record = json.loads(
            Path(".claude/.temp/consult/sess-1/agenda.json").read_text(encoding="utf-8")
        )
        self.assertEqual(record["config"]["item_fields"], [])
        self.assertIsNone(record["config"]["severity_field"])
        self.assertEqual(record["config"]["identity"], "sess-1")

    def test_caller_supplied_config_is_overridden_by_resolved_value(self):
        # 呼び出し元が誤って config を含めても、起点から解決した値で上書きされる。
        candidate_path = self._write(
            {
                "structural_judgment": {"note": "初期判定"},
                "config": {"item_fields": ["something_else"], "severity_field": "bogus"},
                "items": [{"id": "01", "title": "論点1"}],
            }
        )
        result = self._run(["--origin", "review", "start", "--input-file", candidate_path])
        self.assertEqual(result["status"], "ok")
        record = json.loads(Path(".claude/.temp/review/agenda.json").read_text(encoding="utf-8"))
        self.assertEqual(record["config"]["item_fields"], ["severity"])
        self.assertEqual(record["config"]["severity_field"], "severity")

    def test_missing_input_file_is_reported_as_error(self):
        result = self._run(["--origin", "review", "start", "--input-file", "/no/such/file.json"])
        self.assertEqual(result["status"], "error")


class RecordNextFinishDelegationTest(RunTestCase):

    def setUp(self):
        super().setUp()
        candidate_path = self._write(
            {
                "structural_judgment": {"note": "同型の指摘は無い"},
                "items": [{"id": "01", "title": "論点1"}],
            }
        )
        self._run(["--origin", "review", "start", "--input-file", candidate_path])

    def test_record_delegates_with_resolved_path(self):
        patch_path = self._write({"background": "背景", "essence": "本質"})
        result = self._run(
            ["--origin", "review", "record", "--item-id", "01", "--input-file", patch_path]
        )
        self.assertEqual(result["status"], "ok")

    def test_next_returns_pending_item(self):
        result = self._run(["--origin", "review", "next"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["item_id"], "01")

    def test_finish_reports_remaining_when_not_all_decided(self):
        result = self._run(["--origin", "review", "finish"])
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["deleted"])
        self.assertEqual(result["remaining_count"], 1)


class ErrorPropagationTest(RunTestCase):

    def test_consult_without_session_id_errors_before_touching_agenda_store(self):
        result = self._run(["--origin", "consult", "pending"])
        self.assertEqual(result["status"], "error")


class MainExitCodeTest(RunTestCase):

    def test_main_returns_zero_on_ok(self):
        self.assertEqual(agenda_wrapper.main(["--origin", "review", "pending"]), 0)

    def test_main_returns_one_on_error(self):
        self.assertEqual(agenda_wrapper.main(["--origin", "consult", "pending"]), 1)


if __name__ == "__main__":
    unittest.main()
