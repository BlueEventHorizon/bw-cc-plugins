#!/usr/bin/env python3
"""publish_request.py の契約テスト。

review 本体が依頼を組み立てて公開する script が、次を満たすことを検証する。

- targets の 3 形（paths / base_branch / diff）を、渡した順に並べる。paths は展開しない
- references の重複を除く。focus / scope は変形せずに保持し、成功時に入力ファイルを削除する
- 絶対パスでない --paths / --references を拒む。失敗時に作りかけを残さず、入力ファイルを消さない
- 標準出力は識別値だけで、依頼の本文を載せない
- 依頼は 1 回の操作で公開し、公開後に書き換えない
"""

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "plugins" / "forge" / "scripts" / "review" / "publish_request.py"

_spec = importlib.util.spec_from_file_location("publish_request", SCRIPT)
publish_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(publish_mod)

TRICKY_TEXT = "1 行目\n\"二重引用符\" と '単一引用符'\n`バッククォート` と ```fence```\n日本語・絵文字 \U0001F600\n$HOME $(x) \\n 末尾改行\n"


def run(*args, cwd=None):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    payload = json.loads(completed.stdout) if completed.stdout.strip() else None
    return completed.returncode, payload


class PublishRequestTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.docs = self.root / "docs"
        self.docs.mkdir()
        self.doc_a = self.docs / "a.md"
        self.doc_b = self.docs / "b.md"
        for p in (self.doc_a, self.doc_b):
            p.write_text("# doc\n", encoding="utf-8")
        self.input_dir = self.root / ".claude" / ".temp"
        self.input_dir.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _publish(self, *extra, cwd=None):
        return run(str(self.root), *extra, cwd=cwd)

    def _review_dirs(self):
        base = self.root / ".temp" / "review"
        return sorted(p for p in base.iterdir()) if base.is_dir() else []

    def _request(self, review_id):
        path = self.root / ".temp" / "review" / review_id / "review_request.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_input(self, name, text):
        path = self.input_dir / name
        path.write_bytes(text.encode("utf-8"))
        return path

    # --- 出力と置き場 ---------------------------------------------------------

    def test_stdout_is_only_identifiers(self):
        code, payload = self._publish("--paths", str(self.doc_a))
        self.assertEqual(code, 0)
        self.assertEqual(set(payload), {"review_id", "round_number"})
        self.assertEqual(payload["round_number"], 1)

    def test_stdout_does_not_carry_request_body(self):
        focus = self._write_input("review_focus.txt", "重点")
        _, payload = self._publish(
            "--paths", str(self.doc_a), "--references", str(self.doc_b), "--focus-file", str(focus)
        )
        for key in ("targets", "focus", "scope", "references", "path"):
            self.assertNotIn(key, payload)

    def test_review_id_is_opaque_hex_and_unique(self):
        ids = set()
        for _ in range(3):
            _, payload = self._publish("--diff")
            self.assertRegex(payload["review_id"], r"^[0-9a-f]{32}$")
            ids.add(payload["review_id"])
        self.assertEqual(len(ids), 3)

    def test_creates_request_and_round_one_directory(self):
        _, payload = self._publish("--diff")
        base = self.root / ".temp" / "review" / payload["review_id"]
        self.assertTrue((base / "review_request.json").is_file())
        self.assertTrue((base / "1").is_dir())
        self.assertEqual(sorted(p.name for p in base.iterdir()), ["1", "review_request.json"])

    def test_same_paths_regardless_of_working_directory(self):
        other = self.root / "docs"
        _, payload = self._publish("--diff", cwd=str(other))
        self.assertTrue((self.root / ".temp" / "review" / payload["review_id"]).is_dir())
        self.assertFalse((other / ".temp").exists())

    # --- targets --------------------------------------------------------------

    def test_three_target_forms(self):
        _, payload = self._publish(
            "--paths", str(self.doc_a), str(self.doc_b), "--base-branch", "develop", "--diff"
        )
        self.assertEqual(
            self._request(payload["review_id"])["targets"],
            [
                {"paths": [str(self.doc_a), str(self.doc_b)]},
                {"base_branch": "develop"},
                {"diff": {}},
            ],
        )

    def test_targets_keep_given_order_across_kinds(self):
        _, payload = self._publish(
            "--diff", "--paths", str(self.doc_a), "--base-branch", "main", "--paths", str(self.doc_b)
        )
        self.assertEqual(
            self._request(payload["review_id"])["targets"],
            [
                {"diff": {}},
                {"paths": [str(self.doc_a)]},
                {"base_branch": "main"},
                {"paths": [str(self.doc_b)]},
            ],
        )

    def test_paths_directory_is_not_expanded(self):
        _, payload = self._publish("--paths", str(self.docs))
        self.assertEqual(
            self._request(payload["review_id"])["targets"], [{"paths": [str(self.docs)]}]
        )

    def test_no_target_fails(self):
        code, payload = self._publish("--references", str(self.doc_a))
        self.assertEqual(code, 1)
        self.assertIsInstance(payload["errors"], list)
        self.assertEqual(self._review_dirs(), [])

    # --- references -----------------------------------------------------------

    def test_references_are_deduplicated_keeping_first_order(self):
        _, payload = self._publish(
            "--diff", "--references",
            str(self.doc_b), str(self.doc_a), str(self.doc_b), str(self.docs / ".." / "docs" / "a.md"),
        )
        self.assertEqual(
            self._request(payload["review_id"])["references"], [str(self.doc_b), str(self.doc_a)]
        )

    def test_optional_keys_are_absent_when_not_given(self):
        _, payload = self._publish("--diff")
        self.assertEqual(set(self._request(payload["review_id"])), {"targets"})

    # --- focus / scope --------------------------------------------------------

    def test_focus_and_scope_are_kept_identically(self):
        focus = self._write_input("review_focus.txt", TRICKY_TEXT)
        scope = self._write_input("review_scope.txt", TRICKY_TEXT[::-1])
        _, payload = self._publish(
            "--diff", "--focus-file", str(focus), "--scope-file", str(scope)
        )
        request = self._request(payload["review_id"])
        self.assertEqual(request["focus"], TRICKY_TEXT)
        self.assertEqual(request["scope"], TRICKY_TEXT[::-1])

    def test_crlf_is_not_translated(self):
        focus = self._write_input("review_focus.txt", "a\r\nb\r\n")
        _, payload = self._publish("--diff", "--focus-file", str(focus))
        self.assertEqual(self._request(payload["review_id"])["focus"], "a\r\nb\r\n")

    def test_only_given_one_of_focus_or_scope(self):
        focus = self._write_input("review_focus.txt", "重点")
        _, payload = self._publish("--diff", "--focus-file", str(focus))
        request = self._request(payload["review_id"])
        self.assertEqual(request["focus"], "重点")
        self.assertNotIn("scope", request)

    def test_input_files_are_deleted_on_success(self):
        focus = self._write_input("review_focus.txt", "重点")
        scope = self._write_input("review_scope.txt", "目標")
        self._publish("--diff", "--focus-file", str(focus), "--scope-file", str(scope))
        self.assertFalse(focus.exists())
        self.assertFalse(scope.exists())

    def test_unreadable_focus_file_fails_without_leftovers(self):
        scope = self._write_input("review_scope.txt", "目標")
        code, payload = self._publish(
            "--diff", "--focus-file", str(self.input_dir / "missing.txt"), "--scope-file", str(scope)
        )
        self.assertEqual(code, 1)
        self.assertIsInstance(payload["errors"], list)
        self.assertEqual(self._review_dirs(), [])
        self.assertTrue(scope.exists())

    def test_non_utf8_input_fails(self):
        bad = self.input_dir / "review_focus.txt"
        bad.write_bytes(b"\xff\xfe\x00bad")
        code, payload = self._publish("--diff", "--focus-file", str(bad))
        self.assertEqual(code, 1)
        self.assertIsInstance(payload["errors"], list)
        self.assertTrue(bad.exists())

    # --- 絶対パス -------------------------------------------------------------

    def test_relative_paths_are_rejected(self):
        focus = self._write_input("review_focus.txt", "重点")
        code, payload = self._publish(
            "--paths", str(self.doc_a), "docs/b.md", "--focus-file", str(focus)
        )
        self.assertEqual(code, 1)
        self.assertIsInstance(payload["errors"], list)
        self.assertEqual(self._review_dirs(), [])
        self.assertTrue(focus.exists())

    def test_relative_references_are_rejected(self):
        code, payload = self._publish("--diff", "--references", str(self.doc_a), "docs/b.md")
        self.assertEqual(code, 1)
        self.assertIsInstance(payload["errors"], list)
        self.assertEqual(self._review_dirs(), [])

    def test_error_output_is_json_with_errors_array_only(self):
        _, payload = self._publish("--paths", "relative.md")
        self.assertEqual(set(payload), {"errors"})
        self.assertTrue(all(isinstance(e, str) for e in payload["errors"]))

    def test_argument_error_exits_with_2(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT)], capture_output=True, text=True
        )
        self.assertEqual(completed.returncode, 2)

    # --- 失敗時の片付け -------------------------------------------------------

    def test_write_failure_reports_errors(self):
        """置き場を作れないとき、traceback ではなく errors で理由を返す。"""
        (self.root / ".temp").write_text("", encoding="utf-8")
        focus = self._write_input("review_focus.txt", "重点")
        code, payload = self._publish("--diff", "--focus-file", str(focus))
        self.assertEqual(code, 1)
        self.assertIsInstance(payload["errors"], list)
        self.assertTrue(focus.exists())

    def test_failure_after_directory_creation_leaves_no_review_dir_and_keeps_inputs(self):
        focus = self._write_input("review_focus.txt", "重点")
        scope = self._write_input("review_scope.txt", "目標")
        with mock.patch.object(publish_mod.review_common, "publish_json", side_effect=OSError("disk full")):
            out = io.StringIO()
            with redirect_stdout(out):
                code = publish_mod.run_cli(
                    [str(self.root), "--diff", "--focus-file", str(focus), "--scope-file", str(scope)]
                )
        self.assertEqual(code, 1)
        self.assertIn("errors", json.loads(out.getvalue()))
        self.assertEqual(self._review_dirs(), [])
        self.assertTrue(focus.exists())
        self.assertTrue(scope.exists())

    def test_failure_when_round_directory_cannot_be_made_leaves_no_review_dir(self):
        real_mkdir = Path.mkdir

        def fake(self_path, *a, **kw):
            if self_path.name == "1":
                raise OSError("denied")
            return real_mkdir(self_path, *a, **kw)

        with mock.patch.object(Path, "mkdir", autospec=True, side_effect=fake):
            out = io.StringIO()
            with redirect_stdout(out):
                code = publish_mod.run_cli([str(self.root), "--diff"])
        self.assertEqual(code, 1)
        self.assertEqual(self._review_dirs(), [])

    # --- 公開 -----------------------------------------------------------------

    def test_request_is_unreadable_before_publication(self):
        """公開前（下書きの間）は、公開名の依頼が存在しない。公開は 1 回の置き換えである。"""
        observed = {}
        real_replace = os.replace

        def spy(src, dst):
            observed["dst_exists_before"] = Path(dst).exists()
            observed["src_name"] = Path(src).name
            observed["src_is_complete_json"] = isinstance(
                json.loads(Path(src).read_text(encoding="utf-8")), dict
            )
            observed["same_dir"] = Path(src).parent == Path(dst).parent
            return real_replace(src, dst)

        out = io.StringIO()
        with mock.patch.object(os, "replace", side_effect=spy), redirect_stdout(out):
            code = publish_mod.run_cli([str(self.root), "--diff"])
        self.assertEqual(code, 0)
        self.assertFalse(observed["dst_exists_before"])
        self.assertNotEqual(observed["src_name"], "review_request.json")
        self.assertTrue(observed["src_is_complete_json"])
        self.assertTrue(observed["same_dir"])

    def test_no_draft_file_remains_after_publication(self):
        _, payload = self._publish("--diff")
        base = self.root / ".temp" / "review" / payload["review_id"]
        self.assertFalse([p for p in base.iterdir() if p.name.endswith(".tmp")])

    def test_published_request_is_not_rewritten_by_later_publication(self):
        _, first = self._publish("--paths", str(self.doc_a))
        path = self.root / ".temp" / "review" / first["review_id"] / "review_request.json"
        before = path.read_bytes()
        self._publish("--paths", str(self.doc_b))
        self.assertEqual(path.read_bytes(), before)

    def test_review_id_collision_is_retried_with_another_value(self):
        base = self.root / ".temp" / "review"
        base.mkdir(parents=True)
        (base / ("a" * 32)).mkdir()
        ids = iter([mock.Mock(hex="a" * 32), mock.Mock(hex="b" * 32)])
        out = io.StringIO()
        with mock.patch.object(publish_mod.uuid, "uuid4", side_effect=lambda: next(ids)), redirect_stdout(out):
            code = publish_mod.run_cli([str(self.root), "--diff"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["review_id"], "b" * 32)
        self.assertEqual(list((base / ("a" * 32)).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
