#!/usr/bin/env python3
"""adr_exchange.py の契約テスト。

write-adr（SKILL）と adr-writer（Agent）の受け渡しが、識別値（出力先ディレクトリと request_id）
だけで成立すること、記載先が feature の ADR ファイル 1 つに決まること、判定が閉じた 3 値で
記録されること、判定と ADR ファイルの状態の対応が検査されること、片付けが成否にかかわらず
行われることを検証する。
"""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "plugins" / "forge" / "scripts" / "adr" / "adr_exchange.py"


def run(*args, cwd=None):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    payload = json.loads(completed.stdout) if completed.stdout.strip() else None
    return completed.returncode, payload


class AdrExchangeTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.adr_dir = self.root / "docs" / "specs" / "foo" / "adr"
        self.adr_file = self.adr_dir / "ADR-001_foo.md"
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.related = self.root / "docs" / "specs" / "foo" / "design" / "DES-001_foo_design.md"
        self.related.parent.mkdir(parents=True)
        self.related.write_text("# doc\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _input(self, name, text):
        path = self.inputs / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def _open(self, kind="judgement", *extra, decision="決定の内容\n", feature="foo", adr_id="ADR-001"):
        args = ["open", "--kind", kind, "--feature", feature, "--adr-dir", str(self.adr_dir)]
        if adr_id:
            args += ["--adr-id", adr_id]
        if kind == "update":
            args += ["--change-file", self._input("change.md", decision)]
        else:
            args += ["--decision-file", self._input("decision.md", decision)]
        return run(*args, *extra)

    def _identity(self, request_id):
        return ["--adr-dir", str(self.adr_dir), "--request-id", request_id]

    def _request(self, request_id):
        return json.loads(
            (self.adr_dir / f"adr_request_{request_id}.json").read_text(encoding="utf-8")
        )

    def _opened(self, kind="judgement", *extra, **kw):
        code, payload = self._open(kind, *extra, **kw)
        self.assertEqual(code, 0, payload)
        return payload["request_id"]

    def _existing_adr(self, text="# ADR-001 foo\n\n## 1. 既存の決定\n"):
        self.adr_dir.mkdir(parents=True, exist_ok=True)
        self.adr_file.write_text(text, encoding="utf-8")
        return self.adr_file


class OpenTest(AdrExchangeTestBase):
    def test_open_creates_adr_dir_and_publishes_request(self):
        code, payload = self._open()
        self.assertEqual(code, 0)
        self.assertEqual(set(payload), {"status", "request_id"})
        self.assertEqual(payload["status"], "ok")
        request = self._request(payload["request_id"])
        self.assertEqual(request["kind"], "judgement")
        self.assertEqual(request["feature"], "foo")
        self.assertEqual(request["request_id"], payload["request_id"])
        self.assertEqual(request["adr_dir"], str(self.adr_dir.resolve()))
        self.assertEqual(request["adr_path"], str(self.adr_file.resolve()))
        self.assertIsNone(request["baseline_sha256"])
        self.assertEqual(request["decision"], "決定の内容\n")
        for key in ("context", "alternatives", "approval_quote", "change"):
            self.assertIsNone(request[key])
        self.assertEqual(request["related_docs"], [])

    def test_open_derives_file_name_from_feature(self):
        """feature 名の `-` は `_` に直して、ファイル名にする。"""
        code, payload = self._open(feature="adr-writer")
        self.assertEqual(code, 0)
        request = self._request(payload["request_id"])
        self.assertEqual(
            request["adr_path"], str((self.adr_dir / "ADR-001_adr_writer.md").resolve())
        )

    def test_open_fails_when_feature_cannot_make_a_file_name(self):
        code, payload = self._open(feature="Foo Bar")
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "error")

    def test_open_generates_distinct_request_ids(self):
        first = self._opened()
        second = self._opened()
        self.assertNotEqual(first, second)

    def test_open_stdout_does_not_carry_request_body(self):
        """依頼の中身を標準出力に載せない（運ぶのは識別値だけ）。"""
        _, payload = self._open()
        self.assertNotIn("decision", payload)
        self.assertNotIn("adr_path", payload)

    def test_open_preserves_free_text_verbatim(self):
        """改行・引用符・バッククォート・非 ASCII が、変形せずに依頼へ届く。"""
        text = '決定: "A" を採る\n`code` と \'quote\' と $VAR と 日本語\n\n末尾の空行を含む\n'
        request_id = self._opened(decision=text)
        self.assertEqual(self._request(request_id)["decision"], text)

    def test_open_reads_all_optional_inputs(self):
        request_id = self._opened(
            "approval-record",
            "--context-file", self._input("context.md", "文脈\n"),
            "--alternatives-file", self._input("alt.md", "代替案\n"),
            "--approval-quote-file", self._input("quote.md", "「これで進めて」\n"),
            "--related-doc", str(self.related),
        )
        request = self._request(request_id)
        self.assertEqual(request["kind"], "approval-record")
        self.assertEqual(request["context"], "文脈\n")
        self.assertEqual(request["alternatives"], "代替案\n")
        self.assertEqual(request["approval_quote"], "「これで進めて」\n")
        self.assertEqual(request["related_docs"], [str(self.related.resolve())])

    def test_update_reads_change_instead_of_decision(self):
        self._existing_adr()
        request_id = self._opened("update", decision="変更の内容\n", adr_id=None)
        request = self._request(request_id)
        self.assertEqual(request["kind"], "update")
        self.assertEqual(request["change"], "変更の内容\n")
        self.assertIsNone(request["decision"])

    def test_open_deletes_input_files(self):
        self._opened()
        self.assertFalse((self.inputs / "decision.md").exists())

    def test_open_deletes_input_files_even_when_it_fails(self):
        """ADR ファイルが 2 つあって失敗しても、入力ファイルは残さない。"""
        self._existing_adr()
        (self.adr_dir / "ADR-002_bar.md").write_text("# x\n", encoding="utf-8")
        code, _ = self._open()
        self.assertEqual(code, 1)
        self.assertFalse((self.inputs / "decision.md").exists())

    def test_open_fails_when_input_file_is_missing(self):
        code, payload = run(
            "open", "--kind", "judgement", "--feature", "foo", "--adr-dir", str(self.adr_dir),
            "--adr-id", "ADR-001", "--decision-file", str(self.inputs / "missing.md"),
        )
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "error")

    def test_open_rejects_unknown_kind(self):
        code, payload = self._open("other")
        self.assertEqual(code, 2)
        self.assertIsNone(payload)

    def test_open_rejects_bad_adr_id(self):
        for bad in ("adr-001", "ADR-1", "ADR-001x", "DES-001"):
            with self.subTest(adr_id=bad):
                code, _ = self._open(adr_id=bad)
                self.assertEqual(code, 2)

    def test_open_requires_decision_for_creating_kinds_and_change_for_update(self):
        for kind in ("approval-record", "judgement", "update"):
            with self.subTest(kind=kind):
                code, _ = run(
                    "open", "--kind", kind, "--feature", "foo", "--adr-dir", str(self.adr_dir),
                    "--adr-id", "ADR-001",
                )
                self.assertEqual(code, 2)

    def test_open_reports_write_failure_as_errors(self):
        """置き場を作れないとき、traceback ではなく errors で理由を返す。"""
        blocker = self.root / "blocker"
        blocker.write_text("", encoding="utf-8")
        code, payload = run(
            "open", "--kind", "judgement", "--feature", "foo", "--adr-dir", str(blocker / "adr"),
            "--adr-id", "ADR-001", "--decision-file", self._input("decision.md", "x\n"),
        )
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "error")
        self.assertIsInstance(payload["errors"], list)

    def test_open_converts_relative_paths_to_absolute(self):
        rel_dir = self.adr_dir.relative_to(self.root)
        rel_related = self.related.relative_to(self.root)
        code, payload = run(
            "open", "--kind", "judgement", "--feature", "foo", "--adr-dir", str(rel_dir),
            "--adr-id", "ADR-001", "--decision-file", self._input("decision.md", "x\n"),
            "--related-doc", str(rel_related),
            cwd=str(self.root),
        )
        self.assertEqual(code, 0)
        request = self._request(payload["request_id"])
        self.assertTrue(Path(request["adr_path"]).is_absolute())
        self.assertEqual(request["related_docs"], [str(self.related.resolve())])


class OpenExistingFileTest(AdrExchangeTestBase):
    """同じ feature の ADR は、すべて 1 つの ADR ファイルへ書く。"""

    def test_existing_adr_file_becomes_the_target_with_baseline(self):
        adr = self._existing_adr()
        request_id = self._opened(adr_id=None)
        request = self._request(request_id)
        self.assertEqual(request["adr_path"], str(adr.resolve()))
        self.assertEqual(request["baseline_sha256"], hashlib.sha256(adr.read_bytes()).hexdigest())

    def test_adr_id_is_ignored_when_a_file_exists(self):
        """新しい ADR ファイルを作るのは、まだ無いときだけである。"""
        adr = self._existing_adr()
        request_id = self._opened(adr_id="ADR-009")
        self.assertEqual(self._request(request_id)["adr_path"], str(adr.resolve()))
        self.assertEqual([p.name for p in self.adr_dir.glob("ADR-*.md")], [adr.name])

    def test_two_or_more_adr_files_fail(self):
        """どれに書くかを推測しない。"""
        self._existing_adr()
        (self.adr_dir / "ADR-002_bar.md").write_text("# x\n", encoding="utf-8")
        code, payload = self._open(adr_id=None)
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "error")
        self.assertIsInstance(payload["errors"], list)

    def test_missing_file_and_missing_adr_id_fails(self):
        code, payload = self._open(adr_id=None)
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "error")


class RequestPathTest(AdrExchangeTestBase):
    def test_request_path_before_open_fails(self):
        code, payload = run("request-path", *self._identity("0123456789ab"))
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "error")
        self.assertNotIn("path", payload)

    def test_error_carries_errors_as_array(self):
        """エラーの理由は常に配列で返す（1 件でも配列）。"""
        _, payload = run("request-path", *self._identity("0123456789ab"))
        self.assertIsInstance(payload["errors"], list)
        self.assertEqual(len(payload["errors"]), 1)
        self.assertNotIn("message", payload)

    def test_request_path_returns_absolute_path_only(self):
        request_id = self._opened()
        code, payload = run("request-path", *self._identity(request_id))
        self.assertEqual(code, 0)
        self.assertEqual(set(payload), {"status", "path"})
        self.assertEqual(
            payload["path"], str((self.adr_dir / f"adr_request_{request_id}.json").resolve())
        )

    def test_request_id_must_be_a_generated_token(self):
        """パスの組み立てに使うため、生成された形以外の値は受理しない。"""
        for bad in ("../x", "abc", "0123456789AB", "0123456789abc"):
            with self.subTest(request_id=bad):
                code, _ = run("request-path", *self._identity(bad))
                self.assertEqual(code, 2)


class FinishNewFileTest(AdrExchangeTestBase):
    """open 時点で ADR ファイルが無かった場合。"""

    def _result(self, request_id):
        return self.adr_dir / f"adr_result_{request_id}.json"

    def _write_adr(self, text="# ADR-001 foo\n"):
        self.adr_dir.mkdir(parents=True, exist_ok=True)
        self.adr_file.write_text(text, encoding="utf-8")

    def test_created_requires_written_adr(self):
        request_id = self._opened()
        code, payload = run("finish", *self._identity(request_id), "--verdict", "created")
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "error")
        self.assertFalse(self._result(request_id).exists())

    def test_created_rejects_empty_adr(self):
        request_id = self._opened()
        self._write_adr("")
        code, _ = run("finish", *self._identity(request_id), "--verdict", "created")
        self.assertEqual(code, 1)
        self.assertFalse(self._result(request_id).exists())

    def test_created_records_exit_and_verdict(self):
        request_id = self._opened()
        self._write_adr()
        code, _ = run("finish", *self._identity(request_id), "--verdict", "created")
        self.assertEqual(code, 0)
        result = json.loads(self._result(request_id).read_text(encoding="utf-8"))
        self.assertEqual(result, {"exit": "0", "verdict": "created"})

    def test_rejected_and_insufficient_require_no_adr(self):
        for verdict in ("rejected", "insufficient"):
            with self.subTest(verdict=verdict):
                request_id = self._opened()
                code, _ = run("finish", *self._identity(request_id), "--verdict", verdict)
                self.assertEqual(code, 0)
                result = json.loads(self._result(request_id).read_text(encoding="utf-8"))
                self.assertEqual(result, {"exit": "0", "verdict": verdict})

    def test_rejected_fails_when_adr_was_written(self):
        """棄却したのに ADR ファイルが残っている状態は、判定と状態が合わない。"""
        request_id = self._opened()
        self._write_adr()
        code, _ = run("finish", *self._identity(request_id), "--verdict", "rejected")
        self.assertEqual(code, 1)
        self.assertFalse(self._result(request_id).exists())

    def test_rejects_unknown_verdict(self):
        request_id = self._opened()
        code, _ = run("finish", *self._identity(request_id), "--verdict", "approved")
        self.assertEqual(code, 2)

    def test_does_not_overwrite(self):
        request_id = self._opened()
        run("finish", *self._identity(request_id), "--verdict", "rejected")
        code, _ = run("finish", *self._identity(request_id), "--verdict", "rejected")
        self.assertEqual(code, 1)

    def test_without_request_fails(self):
        code, payload = run("finish", *self._identity("0123456789ab"), "--verdict", "rejected")
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "error")

    def test_reports_write_failure_as_errors(self):
        """判定を書けないとき、traceback ではなく errors で理由を返す。"""
        request_id = self._opened()
        self.adr_dir.chmod(0o500)
        try:
            code, payload = run("finish", *self._identity(request_id), "--verdict", "rejected")
        finally:
            self.adr_dir.chmod(0o700)
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "error")
        self.assertIsInstance(payload["errors"], list)


class FinishExistingFileTest(AdrExchangeTestBase):
    """open 時点で ADR ファイルが既にあった場合（決定の追加・同じ節の書き直し）。"""

    def setUp(self):
        super().setUp()
        self.adr = self._existing_adr("# ADR-001 foo\n\n## 1. 既存の決定\n\n既存の内容\n")
        self.request_id = self._opened(adr_id=None)

    def test_created_requires_changed_content(self):
        code, _ = run("finish", *self._identity(self.request_id), "--verdict", "created")
        self.assertEqual(code, 1)

    def test_created_succeeds_when_content_changed(self):
        self.adr.write_text(self.adr.read_text(encoding="utf-8") + "\n## 2. 新しい決定\n", encoding="utf-8")
        code, _ = run("finish", *self._identity(self.request_id), "--verdict", "created")
        self.assertEqual(code, 0)

    def test_rejected_requires_unchanged_content(self):
        self.adr.write_text("# ADR-001 foo\n\n書き換えた\n", encoding="utf-8")
        code, _ = run("finish", *self._identity(self.request_id), "--verdict", "rejected")
        self.assertEqual(code, 1)

    def test_rejected_and_insufficient_succeed_when_content_unchanged(self):
        code, _ = run("finish", *self._identity(self.request_id), "--verdict", "rejected")
        self.assertEqual(code, 0)

    def test_deleted_adr_file_is_reported_as_error(self):
        self.adr.unlink()
        code, payload = run("finish", *self._identity(self.request_id), "--verdict", "rejected")
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "error")


class CheckTest(AdrExchangeTestBase):
    def _paths(self, request_id):
        return (
            self.adr_dir / f"adr_request_{request_id}.json",
            self.adr_dir / f"adr_result_{request_id}.json",
        )

    def test_check_created_returns_only_the_verdict_and_cleans_up(self):
        """「作成」は何も添えない（記載先は呼び出し元が出力先から知っている）。"""
        request_id = self._opened()
        self.adr_dir.joinpath("ADR-001_foo.md").write_text("# ADR-001 foo\n", encoding="utf-8")
        run("finish", *self._identity(request_id), "--verdict", "created")
        code, payload = run("check", *self._identity(request_id))
        self.assertEqual(code, 0)
        self.assertEqual(payload, {"status": "ok", "verdict": "created"})
        for path in self._paths(request_id):
            self.assertFalse(path.exists())
        self.assertTrue(self.adr_file.exists())

    def test_check_rejected_and_insufficient_return_only_the_verdict(self):
        for verdict in ("rejected", "insufficient"):
            with self.subTest(verdict=verdict):
                request_id = self._opened()
                run("finish", *self._identity(request_id), "--verdict", verdict)
                code, payload = run("check", *self._identity(request_id))
                self.assertEqual(code, 0)
                self.assertEqual(payload, {"status": "ok", "verdict": verdict})

    def test_check_without_result_fails_and_cleans_up(self):
        """判定が取れない（落ちた・書き忘れた）ことを異常として扱う。"""
        request_id = self._opened()
        code, payload = run("check", *self._identity(request_id))
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "error")
        self.assertNotIn("verdict", payload)
        for path in self._paths(request_id):
            self.assertFalse(path.exists())

    def test_check_with_unknown_verdict_fails(self):
        """定義に無い値は正常として通さない。"""
        request_id = self._opened()
        self._paths(request_id)[1].write_text(
            '{"exit": "0", "verdict": "approved"}', encoding="utf-8"
        )
        code, _ = run("check", *self._identity(request_id))
        self.assertEqual(code, 1)

    def test_check_with_unknown_exit_value_fails(self):
        request_id = self._opened()
        self._paths(request_id)[1].write_text(
            '{"exit": "1", "verdict": "rejected"}', encoding="utf-8"
        )
        code, _ = run("check", *self._identity(request_id))
        self.assertEqual(code, 1)

    def test_check_with_broken_result_fails(self):
        request_id = self._opened()
        self._paths(request_id)[1].write_text("not json", encoding="utf-8")
        code, _ = run("check", *self._identity(request_id))
        self.assertEqual(code, 1)


class ContractTest(unittest.TestCase):
    def test_module_docstring_declares_exit_codes_only_0_1_2(self):
        """3 以上を返さない script は、0 / 1 / 2 だけを宣言する。"""
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("## 終了コード", text)
        for code in ("| 0 ", "| 1 ", "| 2 "):
            self.assertIn(code, text)

    def test_no_blanket_exception_catch(self):
        """内部バグを握りつぶさない（COMMON-REQ-002）。"""
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("except Exception", text)
        self.assertNotIn("except:", text)


if __name__ == "__main__":
    unittest.main()
