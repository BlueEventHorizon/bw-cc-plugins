#!/usr/bin/env python3
"""
mailbox.py のテスト

send / inbox（非破壊取得）/ ack（既読化）/ history の送受信ロジックをテストする。
標準ライブラリのみ使用。

実行:
  python3 -m unittest tests.forge.msg-sys.test_mailbox -v
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_LIB_DIR = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "scripts" / "msg-sys" / "lib"
)

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("msg_sys_mailbox", _LIB_DIR / "mailbox.py")
mailbox = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mailbox)


class MailboxTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "messages.db"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_send_returns_message_id(self):
        message_id = mailbox.send("claude", "codex", "hello", db_path=self.db_path)
        self.assertTrue(message_id)

    def test_inbox_returns_unread_without_marking_read(self):
        """inbox() は取得のみを行い既読化しない（INT-001/INT-004、既読化は ack() の責務）。"""
        mailbox.send("claude", "codex", "review this diff", db_path=self.db_path)

        first = mailbox.inbox("codex", db_path=self.db_path)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["sender"], "claude")
        self.assertEqual(first[0]["body"], "review this diff")

        second = mailbox.inbox("codex", db_path=self.db_path)
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["body"], "review this diff")

    def test_inbox_repeated_calls_are_non_destructive(self):
        mailbox.send("claude", "codex", "peek me", db_path=self.db_path)

        peeked = mailbox.inbox("codex", db_path=self.db_path)
        self.assertEqual(len(peeked), 1)

        peeked_again = mailbox.inbox("codex", db_path=self.db_path)
        self.assertEqual(len(peeked_again), 1)

        # ack() で明示的に既読化した後のみ、inbox() から除外される
        mailbox.ack(peeked[0]["id"], db_path=self.db_path)
        self.assertEqual(mailbox.inbox("codex", db_path=self.db_path), [])

    def test_inbox_only_returns_messages_for_recipient(self):
        mailbox.send("claude", "codex", "for codex", db_path=self.db_path)
        mailbox.send("claude", "someone-else", "not for codex", db_path=self.db_path)

        messages = mailbox.inbox("codex", db_path=self.db_path)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["body"], "for codex")

    def test_inbox_orders_by_sent_at_ascending(self):
        mailbox.send("claude", "codex", "first", db_path=self.db_path)
        mailbox.send("claude", "codex", "second", db_path=self.db_path)

        messages = mailbox.inbox("codex", db_path=self.db_path)
        self.assertEqual([m["body"] for m in messages], ["first", "second"])

    def test_history_includes_read_and_unread_both_directions(self):
        mailbox.send("claude", "codex", "from claude", db_path=self.db_path)
        mailbox.send("codex", "claude", "from codex", db_path=self.db_path)
        # 片方だけ既読化する（既読化は ack() の責務、inbox() は既読化しない）
        claude_unread = mailbox.inbox("claude", db_path=self.db_path)
        mailbox.ack(claude_unread[0]["id"], db_path=self.db_path)

        records = mailbox.history("claude", "codex", db_path=self.db_path)
        self.assertEqual(len(records), 2)
        self.assertEqual([r["body"] for r in records], ["from claude", "from codex"])
        self.assertIsNotNone(records[1]["read_at"])  # claude 宛は既読化済み
        self.assertIsNone(records[0]["read_at"])  # codex 宛は未読のまま

    def test_history_does_not_mutate_read_state(self):
        mailbox.send("claude", "codex", "hello", db_path=self.db_path)

        mailbox.history("claude", "codex", db_path=self.db_path)

        unread = mailbox.inbox("codex", db_path=self.db_path)
        self.assertEqual(len(unread), 1)

    # --- in_reply_to の保存 ---

    def test_send_with_in_reply_to_is_persisted(self):
        original_id = mailbox.send("codex", "claude", "finding", db_path=self.db_path)
        reply_id = mailbox.send(
            "claude", "codex", "fixed", in_reply_to=original_id, db_path=self.db_path
        )

        records = mailbox.history("claude", "codex", db_path=self.db_path)
        reply_record = next(r for r in records if r["id"] == reply_id)
        # history() は in_reply_to を返す（msg-review の filter_review_history.py が
        # 返信連鎖を辿るため。実 Codex レビューで発見の不具合対応）。
        self.assertEqual(reply_record["in_reply_to"], original_id)
        self.assertEqual(mailbox.reply_chain_length(reply_id, db_path=self.db_path), 1)
        self.assertEqual(reply_record["body"], "fixed")

    # --- reply_chain_length ---

    def test_reply_chain_length_zero_for_new_message(self):
        message_id = mailbox.send("claude", "codex", "new message", db_path=self.db_path)

        self.assertEqual(mailbox.reply_chain_length(message_id, db_path=self.db_path), 0)

    def test_reply_chain_length_multiple(self):
        m1 = mailbox.send("codex", "claude", "finding 1", db_path=self.db_path)
        m2 = mailbox.send("claude", "codex", "fix 1", in_reply_to=m1, db_path=self.db_path)
        m3 = mailbox.send("codex", "claude", "finding 2", in_reply_to=m2, db_path=self.db_path)

        self.assertEqual(mailbox.reply_chain_length(m1, db_path=self.db_path), 0)
        self.assertEqual(mailbox.reply_chain_length(m2, db_path=self.db_path), 1)
        self.assertEqual(mailbox.reply_chain_length(m3, db_path=self.db_path), 2)

    def test_reply_chain_length_stops_at_new_message_in_middle(self):
        m1 = mailbox.send("codex", "claude", "finding 1", db_path=self.db_path)
        m2 = mailbox.send("claude", "codex", "fix 1", in_reply_to=m1, db_path=self.db_path)
        # human が新規メッセージ（in_reply_to なし）を割り込ませる
        m3 = mailbox.send("codex", "claude", "human new message", db_path=self.db_path)
        m4 = mailbox.send("claude", "codex", "fix 2", in_reply_to=m3, db_path=self.db_path)

        self.assertEqual(mailbox.reply_chain_length(m2, db_path=self.db_path), 1)
        self.assertEqual(mailbox.reply_chain_length(m3, db_path=self.db_path), 0)
        self.assertEqual(mailbox.reply_chain_length(m4, db_path=self.db_path), 1)

    # --- select_next_actionable ---

    def test_select_next_actionable_picks_oldest_null_notified(self):
        m1 = mailbox.send("claude", "codex", "first", db_path=self.db_path)
        mailbox.send("claude", "codex", "second", db_path=self.db_path)

        selected = mailbox.select_next_actionable("codex", db_path=self.db_path)

        self.assertIsNotNone(selected)
        self.assertEqual(selected["id"], m1)
        self.assertEqual(selected["body"], "first")
        self.assertEqual(selected["chain_length"], 0)

    def test_select_next_actionable_excludes_pending_notified(self):
        m1 = mailbox.send("claude", "codex", "pending", db_path=self.db_path)
        m2 = mailbox.send("claude", "codex", "next up", db_path=self.db_path)
        mailbox.mark_limit_notified(m1, db_path=self.db_path)

        selected = mailbox.select_next_actionable("codex", db_path=self.db_path)

        self.assertIsNotNone(selected)
        self.assertEqual(selected["id"], m2)
        self.assertEqual(selected["body"], "next up")

    def test_select_next_actionable_returns_none_when_no_candidate(self):
        selected = mailbox.select_next_actionable("codex", db_path=self.db_path)
        self.assertIsNone(selected)

        # 唯一のメッセージが保留中（limit_notified_at 設定済み）の場合も該当なし
        m1 = mailbox.send("claude", "codex", "pending only", db_path=self.db_path)
        mailbox.mark_limit_notified(m1, db_path=self.db_path)
        self.assertIsNone(mailbox.select_next_actionable("codex", db_path=self.db_path))

    def test_select_next_actionable_reports_nonzero_chain_length_for_reply(self):
        m1 = mailbox.send("codex", "claude", "first", db_path=self.db_path)
        m2 = mailbox.send(
            "claude", "codex", "reply", in_reply_to=m1, db_path=self.db_path
        )

        selected = mailbox.select_next_actionable("codex", db_path=self.db_path)

        self.assertIsNotNone(selected)
        self.assertEqual(selected["id"], m2)
        self.assertEqual(selected["chain_length"], 1)

    # --- ack ---

    def test_ack_marks_only_specified_message_as_read(self):
        m1 = mailbox.send("claude", "codex", "first", db_path=self.db_path)
        m2 = mailbox.send("claude", "codex", "second", db_path=self.db_path)

        mailbox.ack(m1, db_path=self.db_path)

        records = mailbox.history("claude", "codex", db_path=self.db_path)
        record_by_id = {r["id"]: r for r in records}
        self.assertIsNotNone(record_by_id[m1]["read_at"])
        self.assertIsNone(record_by_id[m2]["read_at"])

        remaining_unread = mailbox.inbox("codex", db_path=self.db_path)
        self.assertEqual(len(remaining_unread), 1)
        self.assertEqual(remaining_unread[0]["id"], m2)

    def test_ack_returns_true_when_it_wins_the_race(self):
        m1 = mailbox.send("claude", "codex", "first", db_path=self.db_path)

        self.assertTrue(mailbox.ack(m1, db_path=self.db_path))

    def test_ack_returns_false_when_already_read_by_another_process(self):
        """並行する2つの Stop hook が同一未読を検知した場合の想定シナリオ。

        1回目の ack（先着プロセス）は行を更新できるため True。2回目の ack
        （後着プロセス、同一 message_id）は既に read_at が設定済みのため
        UPDATE の対象行が無く False を返す。呼び出し側はこの False を
        「配信権を得られなかった」と解釈し、continue:true にフォールバック
        しなければならない（二重配信防止、レビュー指摘の再発防止）。
        """
        m1 = mailbox.send("claude", "codex", "first", db_path=self.db_path)

        first_caller_won = mailbox.ack(m1, db_path=self.db_path)
        second_caller_won = mailbox.ack(m1, db_path=self.db_path)

        self.assertTrue(first_caller_won)
        self.assertFalse(second_caller_won)

    def test_ack_returns_false_for_nonexistent_message_id(self):
        self.assertFalse(mailbox.ack("does-not-exist", db_path=self.db_path))

    # --- mark_limit_notified ---

    def test_mark_limit_notified_does_not_mark_message_read(self):
        message_id = mailbox.send("claude", "codex", "held up", db_path=self.db_path)

        mailbox.mark_limit_notified(message_id, db_path=self.db_path)

        records = mailbox.history("claude", "codex", db_path=self.db_path)
        self.assertIsNone(records[0]["read_at"])

        # inbox() は既読化しないため、limit_notified_at のみが設定された未読も取得できる
        peeked = mailbox.inbox("codex", db_path=self.db_path)
        self.assertEqual(len(peeked), 1)
        self.assertEqual(peeked[0]["id"], message_id)

    # --- resolve_db_path ---

    def test_resolve_db_path_prefers_explicit_argument(self):
        with mock.patch.dict(os.environ, {"FORGE_MSG_PROJECT_ROOT": "/should/not/be/used"}):
            resolved = mailbox.resolve_db_path("/explicit/path/messages.db")
        self.assertEqual(resolved, Path("/explicit/path/messages.db"))

    def test_resolve_db_path_derives_from_env_var_when_no_explicit(self):
        env_backup = os.environ.pop("FORGE_MSG_PROJECT_ROOT", None)
        try:
            os.environ["FORGE_MSG_PROJECT_ROOT"] = "/project/root"
            resolved = mailbox.resolve_db_path(None)
        finally:
            if env_backup is None:
                os.environ.pop("FORGE_MSG_PROJECT_ROOT", None)
            else:
                os.environ["FORGE_MSG_PROJECT_ROOT"] = env_backup

        self.assertEqual(
            resolved, Path("/project/root") / ".claude" / ".temp" / "msg-sys" / "messages.db"
        )

    def test_resolve_db_path_raises_when_neither_explicit_nor_env_set(self):
        env_backup = os.environ.pop("FORGE_MSG_PROJECT_ROOT", None)
        try:
            with self.assertRaises(RuntimeError):
                mailbox.resolve_db_path(None)
        finally:
            if env_backup is not None:
                os.environ["FORGE_MSG_PROJECT_ROOT"] = env_backup


if __name__ == "__main__":
    unittest.main()
