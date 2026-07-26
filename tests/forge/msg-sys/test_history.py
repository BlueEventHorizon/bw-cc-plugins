#!/usr/bin/env python3
"""
history.py のテスト

CLI 層の引数パース・--db-path の解決順序・引数不足時の usage 表示・
fail-closed 挙動をテストする。mailbox.history() 自体のロジック
（送信順の取得・既読状態不変）は tests/forge/msg-sys/test_mailbox.py で
既にカバーされているため、ここでは CLI 層（引数パース・resolve_db_path
経由・出力フォーマット）のみを検証する。
標準ライブラリのみ使用。

実行:
  python3 -m unittest tests.forge.msg-sys.test_history -v
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

_spec = importlib.util.spec_from_file_location("msg_sys_history", _SCRIPT_DIR / "history.py")
history = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(history)


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "messages.db"

    def tearDown(self):
        self._tmpdir.cleanup()

    # --- 既読・未読混在での全履歴取得（送信順） ---

    def test_all_history_is_returned_in_sent_order_regardless_of_read_state(self):
        history.mailbox.send("claude", "codex", "first", db_path=self.db_path)
        history.mailbox.send("codex", "claude", "second", db_path=self.db_path)
        history.mailbox.send("claude", "codex", "third", db_path=self.db_path)
        # claude 宛のみ既読化し、既読・未読が混在した状態を作る
        claude_unread = history.mailbox.inbox("claude", db_path=self.db_path)
        history.mailbox.ack(claude_unread[0]["id"], db_path=self.db_path)

        argv = ["claude", "codex", "--db-path", str(self.db_path)]
        stdout = io.StringIO()
        with mock.patch.object(history.sys, "argv", ["history.py"] + argv):
            with mock.patch.object(history.sys, "stdout", stdout):
                exit_code = history.main()

        self.assertEqual(exit_code, 0)
        records = json.loads(stdout.getvalue())
        self.assertEqual([r["body"] for r in records], ["first", "second", "third"])
        self.assertIsNone(records[0]["read_at"])  # codex 宛は未読のまま
        self.assertIsNotNone(records[1]["read_at"])  # claude 宛は既読化済み
        self.assertIsNone(records[2]["read_at"])  # codex 宛は未読のまま

    # --- --db-path ---

    def test_db_path_option_is_resolved_via_resolve_db_path(self):
        with mock.patch.object(
            history.mailbox, "resolve_db_path", wraps=history.mailbox.resolve_db_path
        ) as mock_resolve, mock.patch.object(history.mailbox, "history") as mock_history:
            mock_history.return_value = []
            argv = ["claude", "codex", "--db-path", str(self.db_path)]
            with mock.patch.object(history.sys, "argv", ["history.py"] + argv):
                exit_code = history.main()

        self.assertEqual(exit_code, 0)
        mock_resolve.assert_called_once_with(str(self.db_path))
        _, kwargs = mock_history.call_args
        self.assertEqual(kwargs["db_path"], Path(str(self.db_path)))

    # --- 環境変数からの自動導出 ---

    def test_db_path_derives_from_env_var_when_not_explicit(self):
        with mock.patch.dict(
            os.environ, {"FORGE_MSG_PROJECT_ROOT": str(self._tmpdir.name)}
        ):
            with mock.patch.object(history.mailbox, "history") as mock_history:
                mock_history.return_value = []
                argv = ["claude", "codex"]
                with mock.patch.object(history.sys, "argv", ["history.py"] + argv):
                    exit_code = history.main()

        self.assertEqual(exit_code, 0)
        _, kwargs = mock_history.call_args
        expected_path = Path(self._tmpdir.name) / ".claude" / ".temp" / "msg-sys" / "messages.db"
        self.assertEqual(kwargs["db_path"], expected_path)

    # --- fail closed ---

    def test_missing_db_path_and_env_fails_closed(self):
        env_backup = os.environ.pop("FORGE_MSG_PROJECT_ROOT", None)
        try:
            argv = ["claude", "codex"]
            with mock.patch.object(history.sys, "argv", ["history.py"] + argv):
                with self.assertRaises(RuntimeError):
                    history.main()
        finally:
            if env_backup is not None:
                os.environ["FORGE_MSG_PROJECT_ROOT"] = env_backup

    # --- 引数不足 ---

    def test_insufficient_arguments_prints_usage_and_returns_nonzero(self):
        with mock.patch.object(history.sys, "argv", ["history.py", "claude"]):
            with mock.patch.object(history.sys, "stderr", io.StringIO()) as mock_stderr:
                exit_code = history.main()

        self.assertNotEqual(exit_code, 0)
        self.assertIn("usage", mock_stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
