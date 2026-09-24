#!/usr/bin/env python3
"""strategy_exchange.py の契約テスト。

start-plan と plan-strategist の受け渡しが、識別値（出力先ディレクトリと feature 名）だけで
成立すること、成否が終了の値で判定されること、片付けが成否にかかわらず行われることを検証する。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    REPO_ROOT
    / "plugins"
    / "forge"
    / "skills"
    / "start-plan"
    / "scripts"
    / "strategy_exchange.py"
)


def run(*args, cwd=None):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    payload = json.loads(completed.stdout) if completed.stdout.strip() else None
    return completed.returncode, payload


class StrategyExchangeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.plan_dir = self.root / "specs" / "foo" / "plan"
        self.req = self.root / "specs" / "foo" / "requirements" / "REQ-001_foo_spec.md"
        self.des = self.root / "specs" / "foo" / "design" / "DES-001_foo_design.md"
        for p in (self.req, self.des):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# doc\n", encoding="utf-8")
        self.identity = ["--output-dir", str(self.plan_dir), "--feature", "foo"]

    def tearDown(self):
        self._tmp.cleanup()

    def _open(self, *extra):
        return run(
            "open", *self.identity,
            "--requirement-doc", str(self.req),
            "--design-doc", str(self.des),
            *extra,
        )

    def _request(self):
        return json.loads((self.plan_dir / "foo_strategy_request.json").read_text(encoding="utf-8"))

    def _write_strategy(self, text="# foo 実装戦略\n"):
        (self.plan_dir / "foo_strategy.md").write_text(text, encoding="utf-8")

    # --- open ---------------------------------------------------------------

    def test_open_creates_plan_dir_and_publishes_request(self):
        code, payload = self._open()
        self.assertEqual(code, 0)
        self.assertEqual(payload, {"status": "ok"})
        request = self._request()
        self.assertEqual(request["feature"], "foo")
        self.assertEqual(request["requirement_docs"], [str(self.req.resolve())])
        self.assertEqual(request["design_docs"], [str(self.des.resolve())])
        self.assertEqual(request["rules_docs"], [])
        self.assertIsNone(request["existing_strategy"])
        self.assertEqual(
            request["strategy_path"], str((self.plan_dir / "foo_strategy.md").resolve())
        )

    def test_open_stdout_does_not_carry_request_body(self):
        """依頼の中身を標準出力に載せない（運ぶのは識別値だけ）。"""
        _, payload = self._open()
        self.assertNotIn("requirement_docs", payload)
        self.assertNotIn("path", payload)

    def test_open_keeps_order_of_multiple_docs(self):
        other = self.des.parent / "DES-002_bar_design.md"
        other.write_text("# bar\n", encoding="utf-8")
        run(
            "open", *self.identity,
            "--requirement-doc", str(self.req),
            "--design-doc", str(other),
            "--design-doc", str(self.des),
        )
        self.assertEqual(
            self._request()["design_docs"], [str(other.resolve()), str(self.des.resolve())]
        )

    def test_open_converts_relative_paths_to_absolute(self):
        rel_req = self.req.relative_to(self.root)
        rel_des = self.des.relative_to(self.root)
        run(
            "open", "--output-dir", str(self.plan_dir.relative_to(self.root)), "--feature", "foo",
            "--requirement-doc", str(rel_req), "--design-doc", str(rel_des),
            cwd=str(self.root),
        )
        request = self._request()
        self.assertEqual(request["requirement_docs"], [str(self.req.resolve())])
        self.assertTrue(Path(request["strategy_path"]).is_absolute())

    def test_open_reports_existing_strategy(self):
        self.plan_dir.mkdir(parents=True)
        self._write_strategy("# 設計フェーズで書いた戦略\n")
        self._open()
        self.assertEqual(
            self._request()["existing_strategy"],
            str((self.plan_dir / "foo_strategy.md").resolve()),
        )

    def test_open_removes_stale_result(self):
        """前回の終了の値が残っていても、今回の策定を成功と誤判定しない。"""
        self.plan_dir.mkdir(parents=True)
        (self.plan_dir / "foo_strategy_result.json").write_text('{"exit": "0"}', encoding="utf-8")
        self._open()
        self.assertFalse((self.plan_dir / "foo_strategy_result.json").exists())

    def test_open_preserves_non_ascii_values(self):
        req = self.req.parent / "REQ-002_検索履歴_spec.md"
        req.write_text("# 検索履歴\n", encoding="utf-8")
        run(
            "open", "--output-dir", str(self.plan_dir), "--feature", "検索",
            "--requirement-doc", str(req), "--design-doc", str(self.des),
        )
        request = json.loads(
            (self.plan_dir / "検索_strategy_request.json").read_text(encoding="utf-8")
        )
        self.assertEqual(request["feature"], "検索")
        self.assertEqual(request["requirement_docs"], [str(req.resolve())])

    def test_open_requires_requirement_and_design_docs(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "open", *self.identity, "--design-doc", str(self.des)],
            capture_output=True, text=True,
        )
        self.assertNotEqual(completed.returncode, 0)

    # --- request-path -------------------------------------------------------

    def test_request_path_before_open_fails(self):
        code, payload = run("request-path", *self.identity)
        self.assertEqual(code, 20)
        self.assertEqual(payload["status"], "error")
        self.assertNotIn("path", payload)

    def test_request_path_returns_absolute_path_only(self):
        self._open()
        code, payload = run("request-path", *self.identity)
        self.assertEqual(code, 0)
        self.assertEqual(set(payload), {"status", "path"})
        self.assertEqual(payload["path"], str((self.plan_dir / "foo_strategy_request.json").resolve()))

    # --- finish -------------------------------------------------------------

    def test_finish_without_strategy_records_nothing(self):
        self._open()
        code, _ = run("finish", *self.identity)
        self.assertEqual(code, 20)
        self.assertFalse((self.plan_dir / "foo_strategy_result.json").exists())

    def test_finish_with_empty_strategy_records_nothing(self):
        self._open()
        self._write_strategy("")
        code, _ = run("finish", *self.identity)
        self.assertEqual(code, 20)
        self.assertFalse((self.plan_dir / "foo_strategy_result.json").exists())

    def test_finish_records_exit_zero(self):
        self._open()
        self._write_strategy()
        code, _ = run("finish", *self.identity)
        self.assertEqual(code, 0)
        result = json.loads((self.plan_dir / "foo_strategy_result.json").read_text(encoding="utf-8"))
        self.assertEqual(result, {"exit": "0"})

    def test_finish_does_not_overwrite(self):
        self._open()
        self._write_strategy()
        run("finish", *self.identity)
        code, _ = run("finish", *self.identity)
        self.assertEqual(code, 20)

    # --- check --------------------------------------------------------------

    def test_check_success_cleans_up_and_keeps_strategy(self):
        self._open()
        self._write_strategy()
        run("finish", *self.identity)
        code, payload = run("check", *self.identity)
        self.assertEqual(code, 0)
        self.assertEqual(payload["strategy_path"], str((self.plan_dir / "foo_strategy.md").resolve()))
        self.assertFalse((self.plan_dir / "foo_strategy_request.json").exists())
        self.assertFalse((self.plan_dir / "foo_strategy_result.json").exists())
        self.assertTrue((self.plan_dir / "foo_strategy.md").exists())

    def test_check_without_exit_value_fails_and_cleans_up(self):
        """終了の値が取れない（落ちた・書き忘れた）ことを異常として扱う。"""
        self._open()
        self._write_strategy()
        code, payload = run("check", *self.identity)
        self.assertEqual(code, 20)
        self.assertEqual(payload["status"], "error")
        self.assertNotIn("strategy_path", payload)
        self.assertFalse((self.plan_dir / "foo_strategy_request.json").exists())

    def test_check_with_unknown_exit_value_fails(self):
        """定義に無い値は正常として通さない。"""
        self._open()
        (self.plan_dir / "foo_strategy_result.json").write_text('{"exit": "1"}', encoding="utf-8")
        code, _ = run("check", *self.identity)
        self.assertEqual(code, 20)

    def test_check_with_broken_result_fails(self):
        self._open()
        (self.plan_dir / "foo_strategy_result.json").write_text("not json", encoding="utf-8")
        code, _ = run("check", *self.identity)
        self.assertEqual(code, 20)


if __name__ == "__main__":
    unittest.main()
