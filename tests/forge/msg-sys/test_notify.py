#!/usr/bin/env python3
"""
notify.py のテスト

osascript の呼び出しが引数配列形式（shell=True を経由しない）であること、
AppleScript 文字列リテラルへの安全なエスケープ、subprocess.run 失敗時の
戻り値伝播、CLI エントリポイントの終了コードを検証する。
標準ライブラリのみ使用する。

実行:
  python3 -m unittest tests.forge.msg-sys.test_notify -v
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

_LIB_DIR = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "scripts" / "msg-sys" / "lib"
)
_NOTIFY_PATH = _LIB_DIR / "notify.py"

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("msg_sys_notify", _NOTIFY_PATH)
notify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(notify)


class SendNotificationArgvFormTest(unittest.TestCase):
    """osascript がシェル文字列展開を経由せず引数配列形式で呼ばれることを検証する。"""

    def test_subprocess_run_called_with_argv_list_not_shell(self):
        with mock.patch.object(notify.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0
            )
            notify.send_notification(
                recipient="claude",
                message_id="m1",
                sender="codex",
                body="hello",
                ack_hint="inbox.py claude --ack m1",
            )

        mock_run.assert_called_once()
        call_args, call_kwargs = mock_run.call_args
        argv = call_args[0]

        self.assertIsInstance(argv, list)
        self.assertEqual(argv[0], "osascript")
        self.assertEqual(argv[1], "-e")
        self.assertEqual(len(argv), 3)
        self.assertIsInstance(argv[2], str)
        # shell=True（シェル文字列展開経由）が使われていないこと
        self.assertNotIn("shell", call_kwargs)


class EscapeAppleScriptStringTest(unittest.TestCase):
    """引用符・バックスラッシュを含む本文が安全にエスケープされることを検証する。"""

    def test_escape_handles_double_quote(self):
        escaped = notify._escape_applescript_string('say "hi"')
        self.assertEqual(escaped, 'say \\"hi\\"')

    def test_escape_handles_backslash(self):
        escaped = notify._escape_applescript_string("C:\\path\\to\\file")
        self.assertEqual(escaped, "C:\\\\path\\\\to\\\\file")

    def test_escape_handles_backslash_before_quote_without_double_escaping(self):
        # バックスラッシュを先にエスケープしないと、ダブルクォートのエスケープで
        # 生成した \" が二重にエスケープされてしまう（notify.py 冒頭コメント参照）。
        value = 'literal \\" already escaped'
        escaped = notify._escape_applescript_string(value)
        # 元のバックスラッシュ1文字 → \\、続く " → \" となり、
        # \\\" （4文字）にはならないことを確認する。
        self.assertEqual(escaped, 'literal \\\\\\" already escaped')

    def test_build_notification_script_embeds_escaped_values_without_breaking_syntax(
        self,
    ):
        message = 'body with "quotes" and \\backslash\\'
        script = notify.build_notification_script("title", message)

        # スクリプト全体が display notification "..." with title "..." の
        # 構文を保ったまま、エスケープ済みの値が埋め込まれていること。
        self.assertTrue(script.startswith('display notification "'))
        self.assertIn('with title "title"', script)

        safe_message = notify._escape_applescript_string(message)
        self.assertIn(f'"{safe_message}"', script)

        # エスケープ後の文字列中で、エスケープされていない生の " が
        # リテラル境界を破っていないこと（\" 以外に " が出現しないこと）を確認する。
        # \\" のペアをすべて取り除いた残りに " が無ければ構文破綻していない。
        without_escaped_quotes = safe_message.replace('\\"', "")
        self.assertNotIn('"', without_escaped_quotes)

    def test_send_notification_with_quotes_and_backslashes_calls_osascript_once(self):
        tricky_body = 'result: "failed" because C:\\temp\\log said so'
        with mock.patch.object(notify.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0
            )
            ok = notify.send_notification(
                recipient="claude",
                message_id="m2",
                sender="codex",
                body=tricky_body,
                ack_hint="inbox.py claude --ack m2",
            )

        self.assertTrue(ok)
        mock_run.assert_called_once()
        script = mock_run.call_args[0][0][2]
        self.assertIsInstance(script, str)
        # 生成された script は AppleScript の display notification 構文を保つ
        self.assertTrue(script.startswith("display notification "))


class SendNotificationFailurePropagationTest(unittest.TestCase):
    """subprocess.run の非0終了・実行不能が呼び出し元に正しく伝わることを検証する。"""

    def test_returns_false_when_osascript_exits_nonzero(self):
        with mock.patch.object(notify.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1
            )
            ok = notify.send_notification(
                recipient="claude",
                message_id="m3",
                sender="codex",
                body="body",
                ack_hint="ack hint",
            )

        self.assertFalse(ok)

    def test_returns_true_when_osascript_exits_zero(self):
        with mock.patch.object(notify.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0
            )
            ok = notify.send_notification(
                recipient="claude",
                message_id="m4",
                sender="codex",
                body="body",
                ack_hint="ack hint",
            )

        self.assertTrue(ok)

    def test_returns_false_when_osascript_not_executable(self):
        with mock.patch.object(notify.subprocess, "run") as mock_run:
            mock_run.side_effect = OSError("osascript not found")
            ok = notify.send_notification(
                recipient="claude",
                message_id="m5",
                sender="codex",
                body="body",
                ack_hint="ack hint",
            )

        self.assertFalse(ok)


class MainCliTest(unittest.TestCase):
    """CLI エントリポイント（argparse 経由）を実際にサブプロセス起動し検証する。"""

    def _run_cli(self, extra_args, mock_osascript_returncode):
        """notify.py を実サブプロセスとして起動する。

        osascript 自体は CI 環境等で使えないことを想定し、実行対象コード側に
        subprocess.run をモック差し替えする薄いラッパースクリプトを介して
        起動する（osascript は実行しない）。
        """
        wrapper = f"""
import sys
import subprocess
from unittest import mock

sys.path.insert(0, {str(_LIB_DIR)!r})
import importlib.util

spec = importlib.util.spec_from_file_location("msg_sys_notify_cli", {str(_NOTIFY_PATH)!r})
notify_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notify_mod)

with mock.patch.object(notify_mod.subprocess, "run") as mock_run:
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode={mock_osascript_returncode}
    )
    sys.exit(notify_mod.main())
"""
        return subprocess.run(
            [sys.executable, "-c", wrapper, *extra_args],
            capture_output=True,
            text=True,
        )

    def test_cli_returns_exit_code_0_on_success(self):
        result = self._run_cli(
            [
                "--recipient", "claude",
                "--message-id", "m1",
                "--sender", "codex",
                "--body", "some body",
                "--ack-hint", "inbox.py claude --ack m1",
            ],
            mock_osascript_returncode=0,
        )
        self.assertEqual(result.returncode, 0)

    def test_cli_returns_exit_code_1_on_failure(self):
        result = self._run_cli(
            [
                "--recipient", "claude",
                "--message-id", "m1",
                "--sender", "codex",
                "--body", "some body",
                "--ack-hint", "inbox.py claude --ack m1",
            ],
            mock_osascript_returncode=1,
        )
        self.assertEqual(result.returncode, 1)

    def test_cli_missing_required_argument_fails(self):
        # --sender を欠落させ、argparse の必須引数エラー（終了コード2）を確認する
        result = self._run_cli(
            [
                "--recipient", "claude",
                "--message-id", "m1",
                "--body", "some body",
                "--ack-hint", "inbox.py claude --ack m1",
            ],
            mock_osascript_returncode=0,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
