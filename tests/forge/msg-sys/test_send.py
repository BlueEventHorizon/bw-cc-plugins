#!/usr/bin/env python3
"""
send.py のテスト

CLI 層の引数パース・--in-reply-to・--db-path の解決順序・
引数不足時の usage 表示・fail-closed 挙動をテストする。
標準ライブラリのみ使用。

実行:
  python3 -m unittest tests.forge.msg-sys.test_send -v
"""

import io
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

_spec = importlib.util.spec_from_file_location("msg_sys_send", _SCRIPT_DIR / "send.py")
send = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(send)


class SendTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "messages.db"

    def tearDown(self):
        self._tmpdir.cleanup()

    # --- --in-reply-to ---

    def test_in_reply_to_is_forwarded_to_mailbox_send(self):
        with mock.patch.object(send.mailbox, "send") as mock_send:
            mock_send.return_value = "fake-message-id"
            argv = [
                "codex",
                "claude",
                "fixed",
                "--in-reply-to",
                "original-id",
                "--db-path",
                str(self.db_path),
            ]
            with mock.patch.object(send.sys, "argv", ["send.py"] + argv):
                exit_code = send.main()

        self.assertEqual(exit_code, 0)
        mock_send.assert_called_once_with(
            "codex", "claude", "fixed",
            in_reply_to="original-id",
            db_path=Path(str(self.db_path)),
        )

    # --- --db-path ---

    def test_db_path_option_is_resolved_via_resolve_db_path(self):
        with mock.patch.object(
            send.mailbox, "resolve_db_path", wraps=send.mailbox.resolve_db_path
        ) as mock_resolve, mock.patch.object(send.mailbox, "send") as mock_send:
            mock_send.return_value = "fake-message-id"
            argv = [
                "claude",
                "codex",
                "hello",
                "--db-path",
                str(self.db_path),
            ]
            with mock.patch.object(send.sys, "argv", ["send.py"] + argv):
                exit_code = send.main()

        self.assertEqual(exit_code, 0)
        mock_resolve.assert_called_once_with(str(self.db_path))
        _, kwargs = mock_send.call_args
        self.assertEqual(kwargs["db_path"], Path(str(self.db_path)))

    # --- 引数不足 ---

    def test_insufficient_arguments_prints_usage_and_returns_nonzero(self):
        with mock.patch.object(send.sys, "argv", ["send.py", "claude", "codex"]):
            with mock.patch.object(send.sys, "stderr", io.StringIO()) as mock_stderr:
                exit_code = send.main()

        self.assertNotEqual(exit_code, 0)
        self.assertIn("usage", mock_stderr.getvalue())

    def test_db_path_derives_from_env_var_when_not_explicit(self):
        with mock.patch.dict(
            os.environ, {"FORGE_MSG_PROJECT_ROOT": str(self._tmpdir.name)}
        ):
            with mock.patch.object(send.mailbox, "send") as mock_send:
                mock_send.return_value = "fake-message-id"
                argv = ["claude", "codex", "hello"]
                with mock.patch.object(send.sys, "argv", ["send.py"] + argv):
                    exit_code = send.main()

        self.assertEqual(exit_code, 0)
        _, kwargs = mock_send.call_args
        expected_path = Path(self._tmpdir.name) / ".claude" / ".temp" / "msg-sys" / "messages.db"
        self.assertEqual(kwargs["db_path"], expected_path)

    # --- fail closed ---

    def test_missing_db_path_and_env_fails_closed(self):
        env_backup = os.environ.pop("FORGE_MSG_PROJECT_ROOT", None)
        try:
            argv = ["claude", "codex", "hello"]
            with mock.patch.object(send.sys, "argv", ["send.py"] + argv):
                with self.assertRaises(RuntimeError):
                    send.main()
        finally:
            if env_backup is not None:
                os.environ["FORGE_MSG_PROJECT_ROOT"] = env_backup


if __name__ == "__main__":
    unittest.main()
