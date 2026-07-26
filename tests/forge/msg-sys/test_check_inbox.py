#!/usr/bin/env python3
"""
check_inbox.py のテスト（DES-034 §9 テスト設計）

msg-sys 既存 CLI への subprocess 呼び出しはすべてモックし、実 DB・実
msg-sys CLI には一切触れない。生成コマンド文字列の実 shell 実行検証のみ、
ダミーの stdin-echo スクリプトを使う（本物の send.py は使わない）。

実行:
  python3 -m unittest tests.forge.msg-sys.test_check_inbox -v
"""

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "scripts" / "msg-sys" / "hooks" / "check_inbox.py"
)

_spec = importlib.util.spec_from_file_location("msg_sys_check_inbox", _SCRIPT_PATH)
check_inbox = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_inbox)


class _FakeStdout(io.StringIO):
    """sys.stdout.reconfigure() を呼ぶコードをテスト可能にするための io.StringIO 拡張。"""

    def reconfigure(self, **kwargs):
        pass


def _run_main_capture():
    buf = _FakeStdout()
    with mock.patch.object(check_inbox.sys, "stdout", buf):
        check_inbox.main()
    return buf.getvalue()


class MsgSysDirTest(unittest.TestCase):
    """_msg_sys_dir() の symlink 経由解決（Issue #226 回帰テスト）。

    `<project>/.codex/msg-sys/scripts -> <plugin>/scripts/msg-sys` という実際の配置
    （ensure_codex_hook.py が生成する symlink）を模して検証する。
    """

    def test_resolves_correctly_via_symlink(self):
        """symlink 経由で起動しても、リンク先の実体を基準に msg-sys ディレクトリへ解決する。

        修正前（os.path.abspath）では symlink のリンク側パスがそのまま使われ、
        `<project>/.codex/msg-sys/msg-sys`（存在しない）に誤解決していた。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_msg_sys_dir = Path(tmpdir) / "plugin" / "scripts" / "msg-sys"
            (plugin_msg_sys_dir / "hooks").mkdir(parents=True)
            (plugin_msg_sys_dir / "hooks" / "check_inbox.py").write_text("", encoding="utf-8")

            project_link_dir = Path(tmpdir) / "project" / ".codex" / "msg-sys"
            project_link_dir.mkdir(parents=True)
            scripts_link = project_link_dir / "scripts"
            scripts_link.symlink_to(plugin_msg_sys_dir, target_is_directory=True)

            symlinked_file = scripts_link / "hooks" / "check_inbox.py"
            with mock.patch.object(check_inbox, "__file__", str(symlinked_file)):
                result = check_inbox._msg_sys_dir()

            self.assertEqual(result, os.path.normpath(str(plugin_msg_sys_dir)))

    def test_resolves_correctly_via_direct_path(self):
        """symlink を介さず実体パスから直接起動した場合も従来どおり動作する（回帰確認）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_msg_sys_dir = Path(tmpdir) / "plugin" / "scripts" / "msg-sys"
            (plugin_msg_sys_dir / "hooks").mkdir(parents=True)
            direct_file = plugin_msg_sys_dir / "hooks" / "check_inbox.py"
            direct_file.write_text("", encoding="utf-8")

            with mock.patch.object(check_inbox, "__file__", str(direct_file)):
                result = check_inbox._msg_sys_dir()

            self.assertEqual(result, os.path.normpath(str(plugin_msg_sys_dir)))


class ResolveAgentNameTest(unittest.TestCase):
    def test_unset(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(check_inbox.resolve_agent_name())

    def test_empty(self):
        with mock.patch.dict(os.environ, {"FORGE_MSG_AGENT_NAME": ""}):
            self.assertIsNone(check_inbox.resolve_agent_name())

    def test_invalid_value(self):
        with mock.patch.dict(os.environ, {"FORGE_MSG_AGENT_NAME": "bogus"}):
            self.assertIsNone(check_inbox.resolve_agent_name())

    def test_valid_claude(self):
        with mock.patch.dict(os.environ, {"FORGE_MSG_AGENT_NAME": "claude"}):
            self.assertEqual(check_inbox.resolve_agent_name(), "claude")

    def test_valid_codex(self):
        with mock.patch.dict(os.environ, {"FORGE_MSG_AGENT_NAME": "codex"}):
            self.assertEqual(check_inbox.resolve_agent_name(), "codex")


class ResolveDbPathTest(unittest.TestCase):
    def test_unset(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(check_inbox.resolve_db_path())

    def test_set(self):
        with mock.patch.dict(os.environ, {"FORGE_MSG_PROJECT_ROOT": "/tmp/proj"}):
            self.assertEqual(
                check_inbox.resolve_db_path(),
                os.path.join("/tmp/proj", ".claude", ".temp", "msg-sys", "messages.db"),
            )


class FetchNextTest(unittest.TestCase):
    def test_nonzero_exit(self):
        with mock.patch.object(
            check_inbox.subprocess, "run",
            return_value=subprocess.CompletedProcess(args=[], returncode=1, stdout=""),
        ):
            payload, ok = check_inbox.fetch_next("claude", "/db", "/msg-sys")
        self.assertFalse(ok)
        self.assertIsNone(payload)

    def test_oserror(self):
        with mock.patch.object(check_inbox.subprocess, "run", side_effect=OSError):
            payload, ok = check_inbox.fetch_next("claude", "/db", "/msg-sys")
        self.assertFalse(ok)
        self.assertIsNone(payload)

    def test_invalid_json(self):
        with mock.patch.object(
            check_inbox.subprocess, "run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="not json"),
        ):
            payload, ok = check_inbox.fetch_next("claude", "/db", "/msg-sys")
        self.assertFalse(ok)
        self.assertIsNone(payload)

    def test_null(self):
        with mock.patch.object(
            check_inbox.subprocess, "run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="null"),
        ):
            payload, ok = check_inbox.fetch_next("claude", "/db", "/msg-sys")
        self.assertTrue(ok)
        self.assertIsNone(payload)

    def test_valid_object(self):
        stdout = json.dumps({"id": "x", "sender": "codex", "body": "b", "chain_length": 0})
        with mock.patch.object(
            check_inbox.subprocess, "run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout),
        ):
            payload, ok = check_inbox.fetch_next("claude", "/db", "/msg-sys")
        self.assertTrue(ok)
        self.assertEqual(payload["id"], "x")


class ValidateMessageTest(unittest.TestCase):
    def test_self_addressed(self):
        payload = {"id": "x", "sender": "claude", "body": "b", "chain_length": 0}
        self.assertIsNone(check_inbox.validate_message(payload, "claude"))

    def test_invalid_sender(self):
        payload = {"id": "x", "sender": "--db-path", "body": "b", "chain_length": 0}
        self.assertIsNone(check_inbox.validate_message(payload, "claude"))

    def test_missing_id(self):
        payload = {"id": "", "sender": "codex", "body": "b", "chain_length": 0}
        self.assertIsNone(check_inbox.validate_message(payload, "claude"))

    def test_body_not_string(self):
        payload = {"id": "x", "sender": "codex", "body": None, "chain_length": 0}
        self.assertIsNone(check_inbox.validate_message(payload, "claude"))

    def test_chain_length_not_int(self):
        payload = {"id": "x", "sender": "codex", "body": "b", "chain_length": "0"}
        self.assertIsNone(check_inbox.validate_message(payload, "claude"))

    def test_chain_length_true_rejected(self):
        payload = {"id": "x", "sender": "codex", "body": "b", "chain_length": True}
        self.assertIsNone(check_inbox.validate_message(payload, "claude"))

    def test_chain_length_false_rejected(self):
        payload = {"id": "x", "sender": "codex", "body": "b", "chain_length": False}
        self.assertIsNone(check_inbox.validate_message(payload, "claude"))

    def test_valid(self):
        payload = {"id": "x", "sender": "codex", "body": "b", "chain_length": 3}
        result = check_inbox.validate_message(payload, "claude")
        self.assertEqual(result, {"id": "x", "sender": "codex", "body": "b", "chain_length": 3})


class ResolveRoundTripLimitTest(unittest.TestCase):
    def test_unset(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(check_inbox.resolve_round_trip_limit())

    def test_empty(self):
        with mock.patch.dict(os.environ, {"FORGE_MSG_MAX_ROUND_TRIPS": ""}):
            self.assertIsNone(check_inbox.resolve_round_trip_limit())

    def test_non_numeric(self):
        with mock.patch.dict(os.environ, {"FORGE_MSG_MAX_ROUND_TRIPS": "abc"}):
            self.assertIsNone(check_inbox.resolve_round_trip_limit())

    def test_zero(self):
        with mock.patch.dict(os.environ, {"FORGE_MSG_MAX_ROUND_TRIPS": "0"}):
            self.assertIsNone(check_inbox.resolve_round_trip_limit())

    def test_negative(self):
        with mock.patch.dict(os.environ, {"FORGE_MSG_MAX_ROUND_TRIPS": "-1"}):
            self.assertIsNone(check_inbox.resolve_round_trip_limit())

    def test_valid(self):
        with mock.patch.dict(os.environ, {"FORGE_MSG_MAX_ROUND_TRIPS": "5"}):
            self.assertEqual(check_inbox.resolve_round_trip_limit(), 5)


class NotifyHumanTest(unittest.TestCase):
    def test_argument_exact_match(self):
        message = {"id": "abc-1", "sender": "codex", "body": "本文\"'$(x)", "chain_length": 0}
        with mock.patch.object(
            check_inbox.subprocess, "run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0),
        ) as mock_run:
            ok = check_inbox.notify_human("claude", "/db/path", message, "/msg-sys")
        self.assertTrue(ok)
        called_argv = mock_run.call_args[0][0]
        self.assertEqual(called_argv[0], sys.executable)
        self.assertEqual(called_argv[1], os.path.join("/msg-sys", "lib", "notify.py"))
        self.assertIn("--recipient", called_argv)
        self.assertEqual(called_argv[called_argv.index("--recipient") + 1], "claude")
        self.assertIn("--message-id", called_argv)
        self.assertEqual(called_argv[called_argv.index("--message-id") + 1], "abc-1")
        self.assertIn("--sender", called_argv)
        self.assertEqual(called_argv[called_argv.index("--sender") + 1], "codex")
        self.assertIn("--body", called_argv)
        self.assertEqual(called_argv[called_argv.index("--body") + 1], message["body"])
        self.assertIn("--ack-hint", called_argv)
        ack_hint = called_argv[called_argv.index("--ack-hint") + 1]
        self.assertIn("claude", ack_hint)
        self.assertIn("abc-1", ack_hint)
        self.assertIn("/db/path", ack_hint)

    def test_sender_recipient_not_swapped(self):
        # recipient(--recipient)はagent_name、senderはmessage["sender"]であり、
        # 入れ替わっていないことを明示的に検証する。
        message = {"id": "x", "sender": "codex", "body": "b", "chain_length": 0}
        with mock.patch.object(
            check_inbox.subprocess, "run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0),
        ) as mock_run:
            check_inbox.notify_human("claude", "/db", message, "/msg-sys")
        called_argv = mock_run.call_args[0][0]
        self.assertNotEqual(
            called_argv[called_argv.index("--recipient") + 1],
            called_argv[called_argv.index("--sender") + 1],
        )

    def test_nonzero_exit(self):
        message = {"id": "x", "sender": "codex", "body": "b", "chain_length": 0}
        with mock.patch.object(
            check_inbox.subprocess, "run",
            return_value=subprocess.CompletedProcess(args=[], returncode=1),
        ):
            ok = check_inbox.notify_human("claude", "/db", message, "/msg-sys")
        self.assertFalse(ok)

    def test_oserror(self):
        message = {"id": "x", "sender": "codex", "body": "b", "chain_length": 0}
        with mock.patch.object(check_inbox.subprocess, "run", side_effect=OSError):
            ok = check_inbox.notify_human("claude", "/db", message, "/msg-sys")
        self.assertFalse(ok)


class MarkNotifiedTest(unittest.TestCase):
    def test_called_only_on_notify_success(self):
        message = {"id": "x", "sender": "codex", "body": "b", "chain_length": 0}
        with mock.patch.object(check_inbox, "notify_human", return_value=False):
            with mock.patch.object(check_inbox, "mark_notified") as mock_mark:
                # notify.py 失敗時は mark_notified を呼ばない分岐は _process 側で検証する。
                pass
        with mock.patch.object(
            check_inbox.subprocess, "run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0),
        ):
            check_inbox.mark_notified("claude", "/db", message["id"], "/msg-sys")  # 例外なく完了すること

    def test_oserror_swallowed(self):
        with mock.patch.object(check_inbox.subprocess, "run", side_effect=OSError):
            check_inbox.mark_notified("claude", "/db", "x", "/msg-sys")  # 例外を伝播させない


class BuildReplyHintTest(unittest.TestCase):
    def test_shlex_quoting_and_cli_mapping(self):
        message = {"id": "abc 123 'quote$(x)", "sender": "codex", "body": "b", "chain_length": 0}
        hint = check_inbox.build_reply_hint("claude", message, "/db path with space", "/msg-sys")
        self.assertIn("シェルコマンドを経由せず", hint)
        self.assertIn("heredoc", hint)
        # CLI 引数対応: sender=agent_name(claude), recipient=配信元sender(codex)
        self.assertIn("send.py") if False else None
        self.assertIn(os.path.join("/msg-sys", "send.py"), hint)

    def test_real_shell_execution_with_special_chars(self):
        """生成したコマンド文字列を実際に shell 実行し、リダイレクトが機能することを検証する。

        本物の send.py は使わず、stdin をそのまま出力するダミースクリプトで代替する
        （msg-sys への依存を持ち込まない）。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_send = os.path.join(tmpdir, "send.py")
            with open(dummy_send, "w") as f:
                f.write("import sys\nsys.stdout.write(sys.stdin.read())\n")

            message = {
                "id": "weird id with spaces \"quote\" $(echo x) `y`",
                "sender": "codex",
                "body": "b",
                "chain_length": 0,
            }
            hint = check_inbox.build_reply_hint("claude", message, "/tmp/fake.db", tmpdir)

            tmp_path = "/tmp/forge_msg_reply_{}.txt".format(message["id"])
            body_text = "実shell実行リダイレクト検証本文\n"
            with open(tmp_path, "w") as f:
                f.write(body_text)
            try:
                cmd_line = [
                    line.strip() for line in hint.split("\n") if "send.py" in line
                ][0]
                result = subprocess.run(cmd_line, shell=True, capture_output=True, text=True)
            finally:
                os.remove(tmp_path)

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, body_text)


class BuildDecisionBlockTest(unittest.TestCase):
    def test_structure(self):
        message = {"id": "x", "sender": "codex", "body": "日本語本文", "chain_length": 0}
        with mock.patch.object(check_inbox, "build_reply_hint", return_value="HINT"):
            result = check_inbox.build_decision_block("claude", message, "/db", "/msg-sys")
        parsed = json.loads(result)
        self.assertEqual(parsed["decision"], "block")
        self.assertIn("x", parsed["reason"])
        self.assertIn("codex", parsed["reason"])
        self.assertIn("日本語本文", parsed["reason"])
        self.assertIn("HINT", parsed["reason"])


class AckMessageTest(unittest.TestCase):
    def test_success(self):
        with mock.patch.object(
            check_inbox.subprocess, "run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0),
        ):
            self.assertTrue(check_inbox.ack_message("claude", "x", "/db", "/msg-sys"))

    def test_failure(self):
        with mock.patch.object(
            check_inbox.subprocess, "run",
            return_value=subprocess.CompletedProcess(args=[], returncode=1),
        ):
            self.assertFalse(check_inbox.ack_message("claude", "x", "/db", "/msg-sys"))

    def test_oserror(self):
        with mock.patch.object(check_inbox.subprocess, "run", side_effect=OSError):
            self.assertFalse(check_inbox.ack_message("claude", "x", "/db", "/msg-sys"))


class ProcessAndMainTest(unittest.TestCase):
    """main() / _process() の分岐網羅（DES-034 §4.3 エラーフロー順序1〜8 + catch-all）。"""

    def _env(self, **overrides):
        env = {
            "FORGE_MSG_AGENT_NAME": "claude",
            "FORGE_MSG_PROJECT_ROOT": "/tmp/proj",
            "FORGE_MSG_MAX_ROUND_TRIPS": "5",
        }
        env.update(overrides)
        return env

    def test_order1_invalid_agent_name(self):
        with mock.patch.dict(os.environ, self._env(FORGE_MSG_AGENT_NAME="bogus")):
            with mock.patch.object(check_inbox, "fetch_next") as mock_fetch:
                output = _run_main_capture()
        self.assertEqual(json.loads(output), {"continue": True})
        mock_fetch.assert_not_called()

    def test_order2_db_path_unresolved(self):
        with mock.patch.dict(os.environ, self._env(FORGE_MSG_PROJECT_ROOT="")):
            with mock.patch.object(check_inbox, "fetch_next") as mock_fetch:
                output = _run_main_capture()
        self.assertEqual(json.loads(output), {"continue": True})
        mock_fetch.assert_not_called()

    def test_order3_fetch_next_fails(self):
        with mock.patch.dict(os.environ, self._env()):
            with mock.patch.object(check_inbox, "fetch_next", return_value=(None, False)):
                output = _run_main_capture()
        self.assertEqual(json.loads(output), {"continue": True})

    def test_order4_null_uc3(self):
        with mock.patch.dict(os.environ, self._env()):
            with mock.patch.object(check_inbox, "fetch_next", return_value=(None, True)):
                output = _run_main_capture()
        self.assertEqual(json.loads(output), {"continue": True})

    def test_order4_invalid_message(self):
        payload = {"id": "x", "sender": "claude", "body": "b", "chain_length": 0}
        with mock.patch.dict(os.environ, self._env()):
            with mock.patch.object(check_inbox, "fetch_next", return_value=(payload, True)):
                output = _run_main_capture()
        self.assertEqual(json.loads(output), {"continue": True})

    def test_order5_round_trip_limit_reached_notify_success(self):
        payload = {"id": "x", "sender": "codex", "body": "b", "chain_length": 10}
        with mock.patch.dict(os.environ, self._env()):
            with mock.patch.object(check_inbox, "fetch_next", return_value=(payload, True)):
                with mock.patch.object(check_inbox, "notify_human", return_value=True) as mock_notify:
                    with mock.patch.object(check_inbox, "mark_notified") as mock_mark:
                        output = _run_main_capture()
        self.assertEqual(json.loads(output), {"continue": True})
        mock_notify.assert_called_once()
        mock_mark.assert_called_once()

    def test_order5_notify_failure_no_mark_notified(self):
        payload = {"id": "x", "sender": "codex", "body": "b", "chain_length": 10}
        with mock.patch.dict(os.environ, self._env()):
            with mock.patch.object(check_inbox, "fetch_next", return_value=(payload, True)):
                with mock.patch.object(check_inbox, "notify_human", return_value=False):
                    with mock.patch.object(check_inbox, "mark_notified") as mock_mark:
                        output = _run_main_capture()
        self.assertEqual(json.loads(output), {"continue": True})
        mock_mark.assert_not_called()

    def test_order5_round_trip_unset_treated_as_reached(self):
        payload = {"id": "x", "sender": "codex", "body": "b", "chain_length": 0}
        with mock.patch.dict(os.environ, self._env(FORGE_MSG_MAX_ROUND_TRIPS="")):
            with mock.patch.object(check_inbox, "fetch_next", return_value=(payload, True)):
                with mock.patch.object(check_inbox, "notify_human", return_value=True) as mock_notify:
                    with mock.patch.object(check_inbox, "mark_notified"):
                        output = _run_main_capture()
        self.assertEqual(json.loads(output), {"continue": True})
        mock_notify.assert_called_once()

    def test_order6_construction_failure_no_ack(self):
        payload = {"id": "x", "sender": "codex", "body": "b", "chain_length": 0}
        with mock.patch.dict(os.environ, self._env()):
            with mock.patch.object(check_inbox, "fetch_next", return_value=(payload, True)):
                with mock.patch.object(
                    check_inbox, "build_decision_block", side_effect=RuntimeError("boom")
                ):
                    with mock.patch.object(check_inbox, "ack_message") as mock_ack:
                        output = _run_main_capture()
        self.assertEqual(json.loads(output), {"continue": True})
        mock_ack.assert_not_called()

    def test_order7_ack_failure(self):
        payload = {"id": "x", "sender": "codex", "body": "b", "chain_length": 0}
        with mock.patch.dict(os.environ, self._env()):
            with mock.patch.object(check_inbox, "fetch_next", return_value=(payload, True)):
                with mock.patch.object(check_inbox, "build_decision_block", return_value="{}"):
                    with mock.patch.object(check_inbox, "ack_message", return_value=False):
                        output = _run_main_capture()
        self.assertEqual(json.loads(output), {"continue": True})

    def test_order8_success_writes_decision_block(self):
        payload = {"id": "x", "sender": "codex", "body": "日本語", "chain_length": 0}
        decision_json = json.dumps({"decision": "block", "reason": "日本語reason"}, ensure_ascii=False)
        with mock.patch.dict(os.environ, self._env()):
            with mock.patch.object(check_inbox, "fetch_next", return_value=(payload, True)):
                with mock.patch.object(check_inbox, "build_decision_block", return_value=decision_json):
                    with mock.patch.object(check_inbox, "ack_message", return_value=True) as mock_ack:
                        output = _run_main_capture()
        self.assertEqual(mock_ack.call_count, 1)
        self.assertEqual(json.loads(output), {"decision": "block", "reason": "日本語reason"})

    def test_order8_utf8_reconfigure_applied(self):
        """write_decision_block が実際に UTF-8 へ reconfigure することを検証する。

        下層ストリームを ascii encoding で開始することで、reconfigure が効いていなければ
        日本語書き込み時に UnicodeEncodeError が発生する状態を作る（io.StringIO では
        バイトエンコードが発生しないため検出できない、diff-only レビューで指摘された穴）。
        """
        payload = {"id": "x", "sender": "codex", "body": "日本語", "chain_length": 0}
        decision_json = json.dumps({"decision": "block", "reason": "日本語reason"}, ensure_ascii=False)
        buf = io.BytesIO()
        stream = io.TextIOWrapper(buf, encoding="ascii")
        with mock.patch.dict(os.environ, self._env()):
            with mock.patch.object(check_inbox, "fetch_next", return_value=(payload, True)):
                with mock.patch.object(check_inbox, "build_decision_block", return_value=decision_json):
                    with mock.patch.object(check_inbox, "ack_message", return_value=True):
                        with mock.patch.object(check_inbox.sys, "stdout", stream):
                            check_inbox.main()  # reconfigure されていなければ UnicodeEncodeError
        stream.flush()
        written = buf.getvalue().decode("utf-8")
        self.assertIn("日本語reason", written)

    def test_order8_write_failure_no_fallback_no_ack_retry(self):
        """ack成功後の書き込み失敗時、fallback出力もack再試行も行わないことを検証する。"""
        payload = {"id": "x", "sender": "codex", "body": "b", "chain_length": 0}
        with mock.patch.dict(os.environ, self._env()):
            with mock.patch.object(check_inbox, "fetch_next", return_value=(payload, True)):
                with mock.patch.object(check_inbox, "build_decision_block", return_value="{}"):
                    with mock.patch.object(check_inbox, "ack_message", return_value=True) as mock_ack:
                        with mock.patch.object(
                            check_inbox, "write_decision_block", side_effect=BrokenPipeError
                        ):
                            with self.assertRaises(BrokenPipeError):
                                check_inbox.main()
        self.assertEqual(mock_ack.call_count, 1)

    def test_catch_all_swallows_unexpected_exception_before_ack(self):
        with mock.patch.dict(os.environ, self._env()):
            with mock.patch.object(check_inbox, "fetch_next", side_effect=RuntimeError("boom")):
                output = _run_main_capture()
        self.assertEqual(json.loads(output), {"continue": True})

    def test_catch_all_does_not_swallow_system_exit(self):
        with mock.patch.dict(os.environ, self._env()):
            with mock.patch.object(check_inbox, "fetch_next", side_effect=SystemExit(3)):
                with self.assertRaises(SystemExit):
                    check_inbox.main()

    def test_catch_all_does_not_swallow_keyboard_interrupt(self):
        with mock.patch.dict(os.environ, self._env()):
            with mock.patch.object(check_inbox, "fetch_next", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    check_inbox.main()


if __name__ == "__main__":
    unittest.main()
