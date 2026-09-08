#!/usr/bin/env python3
"""agenda_wrapper.py（agenda への唯一の入力経路）のテスト。

DES-075 §9 の観点: 呼び出し元の作業ディレクトリを変えても同じ絶対パスが返ること /
git 管理下でない場所からの呼び出しがエラーになること / 停止した起点を渡すと
エラーで停止し記録が作られないこと / `start` が標準入力の結合出力（`combined`）から
入れ物を組み立てること / `text` が `problem` にも置かれること / 一時ファイルを
書かないこと / `record` の本文（構造判断を含む）を標準入力から受け取ること /
AI が書く文章を受け取る引数を持たないこと。

実行:
  python3 -m unittest tests.forge.agenda.test_agenda_wrapper -v
"""

import argparse
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "forge"
    / "scripts"
    / "agenda"
    / "agenda_wrapper.py"
)
_SPEC = importlib.util.spec_from_file_location("agenda_wrapper", _MODULE_PATH)
agenda_wrapper = importlib.util.module_from_spec(_SPEC)
sys.modules["agenda_wrapper"] = agenda_wrapper
_SPEC.loader.exec_module(agenda_wrapper)

_COMBINED = {
    "status": "ok",
    "combined": [
        {
            "text": "所見1の本文",
            "severity": "major",
            "index": 0,
            "disposition": "fix",
            "confidence": "high",
        },
        {"text": "所見2の本文", "severity": "minor", "index": 1, "disposition": "fix"},
    ],
}


class WrapperTestCase(unittest.TestCase):
    """一時ディレクトリに git リポジトリを作り、その中から wrapper を呼ぶ。"""

    def setUp(self):
        if shutil.which("git") is None:
            self.skipTest("git が無い環境のため置き場の解決を検証できない")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name).resolve()
        subprocess.run(
            ["git", "init", "-q", str(self.repo)], check=True, capture_output=True
        )
        self._orig_cwd = Path.cwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, str(self._orig_cwd))
        self.agenda_path = str(self.repo / ".claude" / ".temp" / "review" / "agenda.json")

    def _run(self, argv, stdin_text=""):
        args = agenda_wrapper.build_parser().parse_args(argv)
        return agenda_wrapper.run(args, io.StringIO(stdin_text))

    def _start(self, payload=None):
        return self._run(
            ["--origin", "review", "start"],
            json.dumps(payload if payload is not None else _COMBINED, ensure_ascii=False),
        )

    def _record_structural(self, note="同型の指摘は無い"):
        return self._run(["--origin", "review", "record", "--structural"], note)

    def _load_record(self):
        return json.loads(Path(self.agenda_path).read_text(encoding="utf-8"))


class PathResolutionTest(WrapperTestCase):

    def test_same_absolute_path_regardless_of_working_directory(self):
        from_root = self._run(["--origin", "review", "pending"])
        nested = self.repo / "a" / "b"
        nested.mkdir(parents=True)
        os.chdir(nested)
        from_nested = self._run(["--origin", "review", "pending"])

        self.assertEqual(from_root["path"], self.agenda_path)
        self.assertEqual(from_nested["path"], from_root["path"])
        self.assertTrue(Path(from_nested["path"]).is_absolute())

    def test_start_writes_to_the_resolved_path_from_a_subdirectory(self):
        nested = self.repo / "sub"
        nested.mkdir()
        os.chdir(nested)
        result = self._start()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["path"], self.agenda_path)
        self.assertTrue(Path(self.agenda_path).is_file())

    def test_outside_git_repository_is_an_error(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        os.chdir(outside.name)
        probe = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True
        )
        if probe.returncode == 0:
            self.skipTest("一時ディレクトリ自体が git 管理下にある環境")

        result = self._run(["--origin", "review", "pending"])
        self.assertEqual(result["status"], "error")


class StoppedOriginTest(WrapperTestCase):

    def test_consult_origin_is_rejected_and_leaves_no_record(self):
        with self.assertRaises(SystemExit):
            agenda_wrapper.build_parser().parse_args(["--origin", "consult", "start"])
        self.assertFalse(Path(self.agenda_path).exists())


class StartTest(WrapperTestCase):

    def test_start_builds_config_and_items_from_stdin_combined(self):
        result = self._start()
        self.assertEqual(result["status"], "ok")

        record = self._load_record()
        self.assertEqual(record["config"]["item_fields"], [])
        self.assertEqual(record["config"]["severity_field"], "severity")
        self.assertEqual(record["config"]["identity"], "review")
        self.assertEqual(len(record["items"]), 2)
        self.assertEqual([item["id"] for item in record["items"]], ["01", "02"])
        self.assertFalse(record["structural_judgment"]["recorded"])

    def test_text_is_also_placed_into_problem_and_kept(self):
        self._start()
        item = self._load_record()["items"][0]
        self.assertEqual(item["problem"], "所見1の本文")
        self.assertEqual(item["text"], "所見1の本文")

    def test_keys_agenda_does_not_know_are_saved_as_is(self):
        self._start()
        item = self._load_record()["items"][0]
        self.assertEqual(item["severity"], "major")
        self.assertEqual(item["disposition"], "fix")
        self.assertEqual(item["confidence"], "high")

    def test_stdin_without_combined_is_an_error(self):
        result = self._start({"status": "error", "message": "件数が一致しません"})
        self.assertEqual(result["status"], "error")
        self.assertFalse(Path(self.agenda_path).exists())


class NoTemporaryFileTest(WrapperTestCase):

    def test_only_the_record_directory_receives_files(self):
        self._start()
        self._record_structural()
        self._run(
            ["--origin", "review", "record", "--item-id", "01", "--field", "background"],
            "背景",
        )

        written = {
            str(p.relative_to(self.repo))
            for p in self.repo.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(self.repo).parts
        }
        self.assertEqual(
            written,
            {
                ".claude/.temp/review/agenda.json",
                ".claude/.temp/review/agenda.html",
                ".claude/.temp/review/agenda_state.js",
            },
        )

    def test_module_does_not_use_tempfile(self):
        self.assertFalse(hasattr(agenda_wrapper, "tempfile"))


class RecordTest(WrapperTestCase):

    def setUp(self):
        super().setUp()
        self._start()

    def test_structural_judgment_body_comes_from_stdin(self):
        result = self._record_structural("同型の指摘は無い。個別の食い違いに留まる")
        self.assertEqual(result["status"], "ok")

        judgment = self._load_record()["structural_judgment"]
        self.assertTrue(judgment["recorded"])
        self.assertEqual(judgment["note"], "同型の指摘は無い。個別の食い違いに留まる")

    def test_item_value_body_comes_from_stdin(self):
        self._record_structural()
        body = '複数行の本文\n"引用符" と $記号 を含む'
        result = self._run(
            ["--origin", "review", "record", "--item-id", "01", "--field", "background"],
            body,
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self._load_record()["items"][0]["background"], body)

    def test_dotted_field_merges_without_dropping_earlier_values(self):
        self._record_structural()
        for field in ("background", "essence"):
            self._run(
                ["--origin", "review", "record", "--item-id", "01", "--field", field],
                field,
            )
        for field, value in (("decision.by", "human"), ("decision.outcome", "adopt")):
            self._run(
                ["--origin", "review", "record", "--item-id", "01", "--field", field],
                value,
            )
        decision = self._load_record()["items"][0]["decision"]
        self.assertEqual(decision, {"by": "human", "outcome": "adopt"})

    def test_new_item_takes_structural_judgment_from_stdin_and_returns_id(self):
        result = self._run(["--origin", "review", "record", "--new"], "追加後もなお誤りは無い")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["id"], "03")
        self.assertNotIn("item_id", result)
        self.assertEqual(result["path"], self.agenda_path)

        record = self._load_record()
        self.assertEqual(record["items"][-1]["id"], "03")
        self.assertEqual(record["structural_judgment"]["note"], "追加後もなお誤りは無い")

    def test_item_id_without_field_is_an_error(self):
        self._record_structural()
        result = self._run(["--origin", "review", "record", "--item-id", "01"], "背景")
        self.assertEqual(result["status"], "error")

    def test_record_forms_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            agenda_wrapper.build_parser().parse_args(
                ["--origin", "review", "record", "--structural", "--new"]
            )

    def test_record_requires_one_of_the_three_forms(self):
        with self.assertRaises(SystemExit):
            agenda_wrapper.build_parser().parse_args(["--origin", "review", "record"])

    def test_field_with_structural_is_an_error(self):
        """使われない `--field` を黙って捨てず、指定が効かないことを表に出す。"""
        result = self._run(
            ["--origin", "review", "record", "--structural", "--field", "background"], "判断"
        )
        self.assertEqual(result["status"], "error")

    def test_field_with_new_is_an_error(self):
        self._record_structural()
        result = self._run(
            ["--origin", "review", "record", "--new", "--field", "background"], "再判断"
        )
        self.assertEqual(result["status"], "error")


class NextPendingFinishTest(WrapperTestCase):

    def setUp(self):
        super().setUp()
        self._start()

    def test_pending_before_start_reports_not_exists(self):
        Path(self.agenda_path).unlink()
        result = self._run(["--origin", "review", "pending"])
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["exists"])
        self.assertEqual(result["remaining_count"], 0)

    def test_next_returns_first_pending_item(self):
        result = self._run(["--origin", "review", "next"])
        self.assertEqual(result["item_id"], "01")

    def test_finish_reports_remaining_when_not_all_settled(self):
        result = self._run(["--origin", "review", "finish"])
        self.assertFalse(result["deleted"])
        self.assertEqual(result["remaining_count"], 2)
        self.assertEqual(result["path"], self.agenda_path)


class ParserSurfaceTest(WrapperTestCase):
    """AI が書く文章を受け取る引数を持たないこと（DES-075 §6・§6.1・§9）。"""

    def _option_strings(self):
        parser = agenda_wrapper.build_parser()
        options = set()
        stack = [parser]
        while stack:
            current = stack.pop()
            for action in current._actions:
                if isinstance(action, argparse._SubParsersAction):
                    stack.extend(action.choices.values())
                    continue
                options.update(action.option_strings)
        return options

    def test_parser_exposes_only_selector_arguments(self):
        self.assertEqual(
            self._option_strings(),
            {"-h", "--help", "--origin", "--structural", "--new", "--item-id", "--field"},
        )



class MainExitCodeTest(WrapperTestCase):

    def test_main_returns_zero_on_ok(self):
        self.assertEqual(agenda_wrapper.main(["--origin", "review", "pending"]), 0)

    def test_main_returns_one_on_error(self):
        os.chdir(self._orig_cwd)
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        os.chdir(outside.name)
        probe = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True
        )
        if probe.returncode == 0:
            self.skipTest("一時ディレクトリ自体が git 管理下にある環境")
        self.assertEqual(agenda_wrapper.main(["--origin", "review", "pending"]), 1)


if __name__ == "__main__":
    unittest.main()
