#!/usr/bin/env python3
"""
inbox.py のテスト

CLI 層の --ack / --mark-notified / --next / --db-path の挙動をテストする。
標準ライブラリのみ使用。

実行:
  python3 -m unittest tests.forge.msg-sys.test_inbox -v
"""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT_DIR = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "scripts" / "msg-sys"
)

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("msg_sys_inbox", _SCRIPT_DIR / "inbox.py")
inbox = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inbox)

mailbox = inbox.mailbox


class InboxTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "messages.db"

    def tearDown(self):
        self._tmpdir.cleanup()

    def _run_main(self, argv):
        """inbox.main() を argv で実行し、標準出力の文字列を返す。"""
        stdout = io.StringIO()
        with mock.patch.object(inbox.sys, "argv", ["inbox.py"] + argv):
            with mock.patch.object(inbox.sys, "stdout", stdout):
                exit_code = inbox.main()
        return exit_code, stdout.getvalue()

    # --- bare form（フラグなし） ---

    def test_bare_form_does_not_mark_read(self):
        """inbox.py <recipient> は既読化しない（INT-001/INT-004）。"""
        mailbox.send("claude", "codex", "review this diff", db_path=self.db_path)

        exit_code, output = self._run_main(["codex", "--db-path", str(self.db_path)])
        self.assertEqual(exit_code, 0)
        first = json.loads(output)
        self.assertEqual(len(first), 1)

        exit_code, output = self._run_main(["codex", "--db-path", str(self.db_path)])
        self.assertEqual(exit_code, 0)
        second = json.loads(output)
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["body"], "review this diff")

    # --- --ack ---

    def test_ack_prints_nothing_to_stdout(self):
        message_id = mailbox.send("claude", "codex", "finding", db_path=self.db_path)

        exit_code, output = self._run_main(
            ["codex", "--ack", message_id, "--db-path", str(self.db_path)]
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(output, "")

    def test_ack_marks_only_target_message_as_read(self):
        m1 = mailbox.send("claude", "codex", "first", db_path=self.db_path)
        m2 = mailbox.send("claude", "codex", "second", db_path=self.db_path)

        self._run_main(["codex", "--ack", m1, "--db-path", str(self.db_path)])

        remaining_unread = mailbox.inbox("codex", db_path=self.db_path)
        self.assertEqual(len(remaining_unread), 1)
        self.assertEqual(remaining_unread[0]["id"], m2)

        records = {r["id"]: r for r in mailbox.history("claude", "codex", db_path=self.db_path)}
        self.assertIsNotNone(records[m1]["read_at"])
        self.assertIsNone(records[m2]["read_at"])

    def test_ack_exit_code_reflects_race_outcome(self):
        """同一 message_id への2回目の --ack は非ゼロ終了する（並行 Stop hook のレース想定）。

        check_inbox.py の ack_message() は終了コードのみで配信権の有無を判定するため、
        1回目（勝者）は exit 0、2回目（敗者、既に既読化済み）は非ゼロで区別できる
        ことを CLI 層で保証する。
        """
        message_id = mailbox.send("claude", "codex", "finding", db_path=self.db_path)

        first_exit_code, _ = self._run_main(
            ["codex", "--ack", message_id, "--db-path", str(self.db_path)]
        )
        second_exit_code, _ = self._run_main(
            ["codex", "--ack", message_id, "--db-path", str(self.db_path)]
        )

        self.assertEqual(first_exit_code, 0)
        self.assertNotEqual(second_exit_code, 0)

    # --- --mark-notified ---

    def test_mark_notified_sets_limit_notified_at(self):
        message_id = mailbox.send("claude", "codex", "held up", db_path=self.db_path)

        exit_code, _ = self._run_main(
            ["codex", "--mark-notified", message_id, "--db-path", str(self.db_path)]
        )
        self.assertEqual(exit_code, 0)

        # limit_notified_at が設定されたことを、select_next_actionable からの
        # 除外（DES-034 §4.2 の選定規則）で検証する。read_at は変更されない。
        selected = mailbox.select_next_actionable("codex", db_path=self.db_path)
        self.assertIsNone(selected)

        records = mailbox.history("claude", "codex", db_path=self.db_path)
        self.assertIsNone(records[0]["read_at"])

    # --- --next ---

    def test_next_matches_select_next_actionable_and_does_not_mark_read(self):
        m1 = mailbox.send("codex", "claude", "finding 1", db_path=self.db_path)
        mailbox.send(
            "claude", "codex", "reply", in_reply_to=m1, db_path=self.db_path
        )

        expected = mailbox.select_next_actionable("claude", db_path=self.db_path)
        exit_code, output = self._run_main(
            ["claude", "--next", "--db-path", str(self.db_path)]
        )

        self.assertEqual(exit_code, 0)
        actual = json.loads(output)
        self.assertEqual(actual, expected)
        self.assertEqual(actual["id"], m1)
        self.assertEqual(actual["chain_length"], 0)

        # --next は既読化せず、副作用がない
        unread = mailbox.inbox("claude", db_path=self.db_path)
        self.assertEqual(len(unread), 1)
        self.assertEqual(unread[0]["id"], m1)

    def test_next_returns_null_json_when_no_candidate(self):
        exit_code, output = self._run_main(
            ["codex", "--next", "--db-path", str(self.db_path)]
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(output.strip(), "null")
        self.assertIsNone(mailbox.select_next_actionable("codex", db_path=self.db_path))

    # --- --db-path ---

    def test_db_path_option_is_resolved_via_resolve_db_path(self):
        mailbox.send("claude", "codex", "via explicit path", db_path=self.db_path)

        with mock.patch.object(
            inbox.mailbox, "resolve_db_path", wraps=inbox.mailbox.resolve_db_path
        ) as mock_resolve:
            exit_code, output = self._run_main(
                ["codex", "--db-path", str(self.db_path)]
            )

        self.assertEqual(exit_code, 0)
        mock_resolve.assert_called_once_with(str(self.db_path))
        messages = json.loads(output)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["body"], "via explicit path")

    def test_db_path_derives_from_env_var_when_not_explicit(self):
        derived_path = (
            Path(self._tmpdir.name) / ".claude" / ".temp" / "msg-sys" / "messages.db"
        )
        mailbox.send("claude", "codex", "via env root", db_path=derived_path)

        with mock.patch.dict(
            os.environ, {"FORGE_MSG_PROJECT_ROOT": str(self._tmpdir.name)}
        ):
            with mock.patch.object(
                inbox.mailbox, "resolve_db_path", wraps=inbox.mailbox.resolve_db_path
            ) as mock_resolve:
                exit_code, output = self._run_main(["codex"])

        self.assertEqual(exit_code, 0)
        mock_resolve.assert_called_once_with(None)
        messages = json.loads(output)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["body"], "via env root")

    # --- fail closed ---

    def test_missing_db_path_and_env_fails_closed(self):
        env_backup = os.environ.pop("FORGE_MSG_PROJECT_ROOT", None)
        try:
            with mock.patch.object(inbox.sys, "argv", ["inbox.py", "codex"]):
                with self.assertRaises(RuntimeError):
                    inbox.main()
        finally:
            if env_backup is not None:
                os.environ["FORGE_MSG_PROJECT_ROOT"] = env_backup

    def test_removed_peek_option_is_rejected(self):
        exit_code, output = self._run_main(
            ["codex", "--peek", "--db-path", str(self.db_path)]
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(output, "")

    def test_malformed_options_are_rejected(self):
        for argv in (
            ["codex", "--unknown"],
            ["codex", "--ack"],
            ["codex", "--db-path", "--next"],
            ["codex", "--next", "--next"],
            ["codex", "--ack", "m1", "--next"],
            ["codex", "--ack", "m1", "--mark-notified", "m2"],
            ["codex", "--mark-notified", "m1", "--next"],
        ):
            with self.subTest(argv=argv):
                exit_code, output = self._run_main(argv)
                self.assertEqual(exit_code, 1)
                self.assertEqual(output, "")


if __name__ == "__main__":
    unittest.main()
