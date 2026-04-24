#!/usr/bin/env python3
"""
review/scripts/skip_all_unprocessed.py のテスト

複合ラッパー（DES-024 §2.1.0 例外層の唯一案件）。内部で 3 段階:
  1. summarize_plan.py で unprocessed_ids を取得
  2. updates JSON を組み立て
  3. update_plan.py --batch に stdin JSON を流す

各 stage の失敗時に stderr 先頭行 `stage={識別子} exit={code}` が出ることと、
正常時の透過・呼び出し順序・stdin 渡し方を検証する。
"""

import importlib.util
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
WRAPPER_PATH = (REPO_ROOT / 'plugins' / 'forge' / 'skills'
                / 'review' / 'scripts' / 'skip_all_unprocessed.py')
EXPECTED_SUMMARIZE = (REPO_ROOT / 'plugins' / 'forge' / 'scripts'
                      / 'session' / 'summarize_plan.py')
EXPECTED_UPDATE = (REPO_ROOT / 'plugins' / 'forge' / 'scripts'
                   / 'session' / 'update_plan.py')


def _load_wrapper():
    spec = importlib.util.spec_from_file_location(
        "_skip_all_unprocessed_review", WRAPPER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cp(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestLowLevelPaths(unittest.TestCase):
    def setUp(self):
        self.wrapper = _load_wrapper()

    def test_summarize_plan_path(self):
        self.assertEqual(self.wrapper.SUMMARIZE_PLAN.resolve(),
                         EXPECTED_SUMMARIZE.resolve())

    def test_update_plan_path(self):
        self.assertEqual(self.wrapper.UPDATE_PLAN.resolve(),
                         EXPECTED_UPDATE.resolve())

    def test_skip_reason_hardcoded(self):
        self.assertEqual(self.wrapper.SKIP_REASON,
                         "ユーザー判断: 全件対応しない")


class TestHappyPath(unittest.TestCase):
    """全段正常 — unprocessed_ids → updates → --batch 呼び出しの連鎖"""

    def setUp(self):
        self.wrapper = _load_wrapper()

    def test_full_chain_calls_both_low_levels_in_order(self):
        summary = {"unprocessed_ids": [1, 3, 7]}
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.side_effect = [
                _cp(0, stdout=json.dumps(summary), stderr=""),
                _cp(0, stdout='{"status":"ok","updated":[1,3,7]}\n', stderr=""),
            ]
            argv = ["skip_all_unprocessed.py", "/tmp/session"]
            with mock.patch.object(sys, "argv", argv):
                with mock.patch.object(sys, "stdout", new_callable=io.StringIO) as out:
                    rc = self.wrapper.main()
        self.assertEqual(rc, 0)
        self.assertEqual(mock_run.call_count, 2)

        # 1st call: summarize_plan
        args1 = mock_run.call_args_list[0].args[0]
        self.assertEqual(args1[0], sys.executable)
        self.assertEqual(Path(args1[1]).resolve(), EXPECTED_SUMMARIZE.resolve())
        self.assertEqual(args1[2], "/tmp/session")

        # 2nd call: update_plan --batch with stdin JSON
        call2 = mock_run.call_args_list[1]
        args2 = call2.args[0]
        self.assertEqual(args2[0], sys.executable)
        self.assertEqual(Path(args2[1]).resolve(), EXPECTED_UPDATE.resolve())
        self.assertEqual(args2[2], "/tmp/session")
        self.assertIn("--batch", args2)

        stdin_json = call2.kwargs["input"]
        payload = json.loads(stdin_json)
        self.assertEqual(
            payload,
            {"updates": [
                {"id": 1, "status": "skipped", "skip_reason": "ユーザー判断: 全件対応しない"},
                {"id": 3, "status": "skipped", "skip_reason": "ユーザー判断: 全件対応しない"},
                {"id": 7, "status": "skipped", "skip_reason": "ユーザー判断: 全件対応しない"},
            ]},
        )

        # update_plan stdout は親 stdout に透過
        self.assertEqual(out.getvalue(), '{"status":"ok","updated":[1,3,7]}\n')

    def test_empty_unprocessed_ids_still_calls_update_plan(self):
        """unprocessed_ids が空でもラッパーは判断せず低レベルに透過（呼び出し元前提）"""
        summary = {"unprocessed_ids": []}
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.side_effect = [
                _cp(0, stdout=json.dumps(summary)),
                _cp(1, stdout="",
                    stderr='{"status":"error","error":"updates が空です"}'),
            ]
            argv = ["skip_all_unprocessed.py", "/tmp/session"]
            with mock.patch.object(sys, "argv", argv):
                with mock.patch.object(sys, "stderr", new_callable=io.StringIO) as err:
                    rc = self.wrapper.main()
        # update_plan の非 0 を透過 + stage 識別子付与
        self.assertEqual(rc, 1)
        self.assertTrue(err.getvalue().startswith("stage=update_plan exit=1\n"))


class TestStageSummarizePlan(unittest.TestCase):
    """手順 1 失敗時の stderr 契約"""

    def setUp(self):
        self.wrapper = _load_wrapper()

    def test_summarize_plan_failure_prefixes_stage_identifier(self):
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.return_value = _cp(
                2,
                stdout="",
                stderr='{"status":"error","error":"plan.yaml が見つかりません"}\n',
            )
            argv = ["skip_all_unprocessed.py", "/tmp/session"]
            with mock.patch.object(sys, "argv", argv):
                with mock.patch.object(sys, "stderr", new_callable=io.StringIO) as err:
                    rc = self.wrapper.main()
        self.assertEqual(rc, 2)
        first_line = err.getvalue().split("\n", 1)[0]
        self.assertEqual(first_line, "stage=summarize_plan exit=2")
        # 子 stderr が後続に透過
        self.assertIn("plan.yaml が見つかりません", err.getvalue())
        # update_plan は呼ばれていない
        self.assertEqual(mock_run.call_count, 1)


class TestStageJsonBuild(unittest.TestCase):
    """手順 2 失敗時の stderr 契約（exit=-1）"""

    def setUp(self):
        self.wrapper = _load_wrapper()

    def test_json_decode_error_prefixes_stage_identifier(self):
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.return_value = _cp(0, stdout="not a json at all", stderr="")
            argv = ["skip_all_unprocessed.py", "/tmp/session"]
            with mock.patch.object(sys, "argv", argv):
                with mock.patch.object(sys, "stderr", new_callable=io.StringIO) as err:
                    rc = self.wrapper.main()
        self.assertNotEqual(rc, 0)
        first_line = err.getvalue().split("\n", 1)[0]
        self.assertEqual(first_line, "stage=json_build exit=-1")
        self.assertIn("JSONDecodeError", err.getvalue())

    def test_missing_unprocessed_ids_key_prefixes_stage_identifier(self):
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.return_value = _cp(0, stdout='{"total": 5}', stderr="")
            argv = ["skip_all_unprocessed.py", "/tmp/session"]
            with mock.patch.object(sys, "argv", argv):
                with mock.patch.object(sys, "stderr", new_callable=io.StringIO) as err:
                    rc = self.wrapper.main()
        self.assertNotEqual(rc, 0)
        first_line = err.getvalue().split("\n", 1)[0]
        self.assertEqual(first_line, "stage=json_build exit=-1")
        self.assertIn("KeyError", err.getvalue())


class TestStageUpdatePlan(unittest.TestCase):
    """手順 3 失敗時の stderr 契約"""

    def setUp(self):
        self.wrapper = _load_wrapper()

    def test_update_plan_failure_prefixes_stage_identifier(self):
        summary = {"unprocessed_ids": [1, 2]}
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.side_effect = [
                _cp(0, stdout=json.dumps(summary)),
                _cp(3, stdout="",
                    stderr='{"status":"error","error":"id=1 が見つかりません"}'),
            ]
            argv = ["skip_all_unprocessed.py", "/tmp/session"]
            with mock.patch.object(sys, "argv", argv):
                with mock.patch.object(sys, "stderr", new_callable=io.StringIO) as err:
                    rc = self.wrapper.main()
        self.assertEqual(rc, 3)
        first_line = err.getvalue().split("\n", 1)[0]
        self.assertEqual(first_line, "stage=update_plan exit=3")
        self.assertIn("id=1 が見つかりません", err.getvalue())


class TestStderrSilentOnSuccess(unittest.TestCase):
    """正常時は stage 識別子を付けない（§2.1.1 共通原則）"""

    def setUp(self):
        self.wrapper = _load_wrapper()

    def test_no_stage_identifier_in_stderr_on_success(self):
        summary = {"unprocessed_ids": [5]}
        with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
            mock_run.side_effect = [
                _cp(0, stdout=json.dumps(summary), stderr=""),
                _cp(0, stdout='{"status":"ok","updated":[5]}\n', stderr=""),
            ]
            argv = ["skip_all_unprocessed.py", "/tmp/session"]
            with mock.patch.object(sys, "argv", argv):
                with mock.patch.object(sys, "stderr", new_callable=io.StringIO) as err:
                    rc = self.wrapper.main()
        self.assertEqual(rc, 0)
        self.assertNotIn("stage=", err.getvalue())


if __name__ == "__main__":
    unittest.main()
