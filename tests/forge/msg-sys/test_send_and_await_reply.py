#!/usr/bin/env python3
"""
send_and_await_reply.py のテスト（送信 → push型起床 → ブロッキング待機の複合 CLI）

このスクリプトの存在理由は「返信を期待する送信で 3 手順が必ず揃うこと」を構造的に
保証することなので、テストの主眼は**手順が欠けないこと**と**順序が守られること**に置く。

- 送信が成功したときだけ起床・待機に進む（送信失敗で待機予算を浪費しない）
- 起床が失敗しても待機は続く（起床は待機時間の短縮手段であり、待機の前提ではない）
- 起床の結果が最終 JSON に必ず残る（沈黙した見送りを作らない）
- DB パスが `--project-root` から解決される（`FORGE_MSG_PROJECT_ROOT` の前置を要求しない）

実行:
  python3 -m unittest tests.forge.msg-sys.test_send_and_await_reply -v
"""

import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "scripts" / "msg-sys" / "send_and_await_reply.py"
)

_spec = importlib.util.spec_from_file_location("msg_sys_send_and_await_reply", _SCRIPT_PATH)
composite = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(composite)

_HEADER_RE = r"^\[msg-review\]\s+\S+\s+review_id=(\S+)\s+round=\d+\s*$"

_REPLIED = {
    "status": "replied",
    "messages": [{"id": "m2", "sender": "codex"}],
    "delivered_ids": ["m2"],
}
_TIMEOUT = {
    "status": "timeout",
    "elapsed_seconds": 600,
    "last_observed_request_read_by_agent_b": False,
}


class _FakeStdout(io.StringIO):
    """`sys.stdout.reconfigure()` を呼ぶコードをテスト可能にする io.StringIO 拡張。

    `tests/forge/review/test_resolve_targets.py` と同じパターン。
    """

    def reconfigure(self, **kwargs):
        pass


class _Harness:
    """`main()` を実時間・実 DB・実 cmux なしで走らせるための差し替え束。"""

    def __init__(self, *, send_result="mid-1", wake=None, wait_result=None):
        self.send_result = send_result
        self.wake = wake if wake is not None else {"status": "sent", "reason": ""}
        self.wait_result = wait_result if wait_result is not None else _REPLIED
        self.calls: list[str] = []
        self.send_kwargs = {}
        self.wait_kwargs = {}

    def _send(self, sender, recipient, body, *, db_path, in_reply_to=None):
        self.calls.append("send")
        self.send_kwargs = {
            "sender": sender,
            "recipient": recipient,
            "body": body,
            "db_path": db_path,
            "in_reply_to": in_reply_to,
        }
        if isinstance(self.send_result, Exception):
            raise self.send_result
        return self.send_result

    def _wake(self, project_root, **_kwargs):
        self.calls.append("wake")
        return self.wake

    def _wait(self, sender, recipient, header_regex, thread_id, **kwargs):
        self.calls.append("wait")
        self.wait_kwargs = {"thread_id": thread_id, **kwargs}
        if isinstance(self.wait_result, Exception):
            raise self.wait_result
        return self.wait_result


def _run(harness, extra_argv=None, *, body="[msg-review] diff review_id=rid round=1\n"):
    """`main()` を実行し (returncode, 最終行の JSON) を返す。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        body_file = Path(tmpdir) / "body.md"
        body_file.write_text(body, encoding="utf-8")
        argv = [
            "claude", "codex",
            "--body-file", str(body_file),
            "--header-regex", _HEADER_RE,
            "--thread-id", "rid",
            "--project-root", tmpdir,
        ] + (extra_argv or [])

        buf = _FakeStdout()
        with mock.patch.object(composite, "do_send", harness._send), \
             mock.patch.object(composite, "do_wake", harness._wake), \
             mock.patch.object(composite.waiter, "wait_for_reply", harness._wait), \
             mock.patch.object(composite.sys, "stdout", buf):
            code = composite.main(argv)

    lines = [line for line in buf.getvalue().splitlines() if line.strip()]
    return code, json.loads(lines[-1])


class StepOrderTest(unittest.TestCase):
    """3 手順が揃い、順序が守られること（このスクリプトの存在理由）。"""

    def test_all_three_steps_run_in_order(self):
        h = _Harness()
        code, payload = _run(h)

        self.assertEqual(code, 0)
        self.assertEqual(h.calls, ["send", "wake", "wait"])
        self.assertEqual(payload["status"], "replied")

    def test_wait_result_fields_are_at_top_level(self):
        """`wait_for_reply.py` 単体呼び出しと同じ位置に結果を置くこと。

        呼び出し側（SKILL）が `status` / `messages` / `delivered_ids` を同じ場所から
        読めることを契約として固定する（複合化で読み替えが必要になると移行漏れを招く）。
        """
        h = _Harness()
        _, payload = _run(h)

        self.assertEqual(payload["delivered_ids"], ["m2"])
        self.assertEqual(payload["messages"], [{"id": "m2", "sender": "codex"}])

    def test_sent_message_id_is_reported(self):
        h = _Harness(send_result="mid-42")
        _, payload = _run(h)

        self.assertEqual(payload["sent_message_id"], "mid-42")


class SendFailureTest(unittest.TestCase):
    """送信が失敗したら起床・待機に進まない（来ない返信を待たない）。"""

    def test_send_failure_skips_wake_and_wait(self):
        h = _Harness(send_result=RuntimeError("DB locked"))
        code, payload = _run(h)

        self.assertEqual(code, 1)
        self.assertEqual(h.calls, ["send"])
        self.assertEqual(payload["status"], "send_failed")
        self.assertIn("DB locked", payload["error"])

    def test_missing_body_file_is_error(self):
        h = _Harness()
        with mock.patch.object(composite, "do_send", h._send):
            code = composite.main([
                "claude", "codex",
                "--body-file", "/nonexistent/body.md",
                "--header-regex", _HEADER_RE,
                "--thread-id", "rid",
                "--db-path", "/tmp/x.db",
            ])
        self.assertEqual(code, 1)
        self.assertEqual(h.calls, [])


class WakeIsBestEffortTest(unittest.TestCase):
    """起床は best-effort。失敗しても待機は続き、結果は必ず残る。"""

    def test_wake_failure_does_not_stop_waiting(self):
        h = _Harness(wake={"status": "failed", "reason": "cmux send が失敗"})
        code, payload = _run(h)

        self.assertEqual(code, 0)
        self.assertEqual(h.calls, ["send", "wake", "wait"])
        self.assertEqual(payload["wake"]["status"], "failed")

    def test_wake_result_is_always_present(self):
        """`skipped` でも最終 JSON に残す（沈黙した見送りを作らない）。"""
        h = _Harness(wake={"status": "skipped", "reason": "cmux なし"})
        _, payload = _run(h)

        self.assertEqual(payload["wake"], {"status": "skipped", "reason": "cmux なし"})

    def test_no_wake_flag_skips_wake_but_still_waits(self):
        h = _Harness()
        code, payload = _run(h, ["--no-wake"])

        self.assertEqual(code, 0)
        self.assertEqual(h.calls, ["send", "wait"])
        self.assertEqual(payload["wake"]["status"], "skipped")


class TimeoutTest(unittest.TestCase):
    """タイムアウトは確定した失敗として非ゼロ終了する（フォールバックしない）。"""

    def test_timeout_returns_nonzero_with_diagnostics(self):
        h = _Harness(wait_result=_TIMEOUT)
        code, payload = _run(h)

        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "timeout")
        self.assertEqual(payload["last_observed_request_read_by_agent_b"], False)
        # タイムアウト診断のために起床結果が必要（cmux が整っているのに起床が
        # 壊れているのかを切り分けるため）
        self.assertIn("wake", payload)


class WaitDefaultsTest(unittest.TestCase):
    """待機方針値は wait_for_reply.py の定義をそのまま使う。"""

    def test_omitted_wait_options_use_waiter_defaults(self):
        h = _Harness()
        _run(h)

        self.assertEqual(h.wait_kwargs["max_seconds"], composite.waiter.DEFAULT_MAX_SECONDS)
        self.assertEqual(
            h.wait_kwargs["progress_interval"],
            composite.waiter.DEFAULT_PROGRESS_INTERVAL,
        )
        self.assertEqual(
            h.wait_kwargs["initial_interval"],
            composite.waiter.DEFAULT_INITIAL_INTERVAL,
        )
        self.assertEqual(
            h.wait_kwargs["backoff_factor"],
            composite.waiter.DEFAULT_BACKOFF_FACTOR,
        )
        self.assertEqual(
            h.wait_kwargs["max_interval"],
            composite.waiter.DEFAULT_MAX_INTERVAL,
        )


class DbPathResolutionTest(unittest.TestCase):
    """DB パスは `--project-root` から解決する（env 前置を要求しない）。"""

    def test_project_root_derives_db_path_without_env(self):
        h = _Harness()
        with tempfile.TemporaryDirectory() as tmpdir:
            body_file = Path(tmpdir) / "body.md"
            body_file.write_text("x\n", encoding="utf-8")
            argv = [
                "claude", "codex",
                "--body-file", str(body_file),
                "--header-regex", _HEADER_RE,
                "--thread-id", "rid",
                "--project-root", tmpdir,
            ]
            buf = _FakeStdout()
            # FORGE_MSG_PROJECT_ROOT を明示的に空にしても解決できること
            with mock.patch.dict(composite.mailbox.os.environ, {}, clear=True), \
                 mock.patch.object(composite, "do_send", h._send), \
                 mock.patch.object(composite, "do_wake", h._wake), \
                 mock.patch.object(composite.waiter, "wait_for_reply", h._wait), \
                 mock.patch.object(composite.sys, "stdout", buf):
                code = composite.main(argv)

            expected = Path(tmpdir) / ".claude" / ".temp" / "msg-sys" / "messages.db"

        self.assertEqual(code, 0)
        self.assertEqual(Path(h.send_kwargs["db_path"]), expected)
        # 待機側も同じ DB を見ること（送信先と待機先がずれると永久に返信を見つけられない）
        self.assertEqual(Path(h.wait_kwargs["db_path"]), expected)

    def test_db_path_alone_is_used_as_is(self):
        """`--db-path` 単独指定はそのまま使う（msg-sys 一族の標準的な脱出口）。"""
        h = _Harness()
        with tempfile.TemporaryDirectory() as tmpdir:
            body_file = Path(tmpdir) / "body.md"
            body_file.write_text("x\n", encoding="utf-8")
            buf = _FakeStdout()
            with mock.patch.object(composite, "do_send", h._send), \
                 mock.patch.object(composite, "do_wake", h._wake), \
                 mock.patch.object(composite.waiter, "wait_for_reply", h._wait), \
                 mock.patch.object(composite.sys, "stdout", buf):
                code = composite.main([
                    "claude", "codex",
                    "--body-file", str(body_file),
                    "--header-regex", _HEADER_RE,
                    "--thread-id", "rid",
                    "--db-path", "/tmp/explicit.db",
                ])

        self.assertEqual(code, 0)
        self.assertEqual(str(h.send_kwargs["db_path"]), "/tmp/explicit.db")

    def test_neither_project_root_nor_db_path_is_fail_closed(self):
        h = _Harness()
        with tempfile.TemporaryDirectory() as tmpdir:
            body_file = Path(tmpdir) / "body.md"
            body_file.write_text("x\n", encoding="utf-8")
            with mock.patch.dict(composite.mailbox.os.environ, {}, clear=True), \
                 mock.patch.object(composite, "do_send", h._send):
                code = composite.main([
                    "claude", "codex",
                    "--body-file", str(body_file),
                    "--header-regex", _HEADER_RE,
                    "--thread-id", "rid",
                ])
        self.assertEqual(code, 1)
        self.assertEqual(h.calls, [])


class DbPathProjectRootConsistencyTest(unittest.TestCase):
    """DB と相手セッションは独立した軸ではない [MANDATORY]。

    相手側エージェントは project root から DB を解決するため、`--db-path` がそれと食い違う
    DB を指した状態では返信が原理的に成立しない（送信は別 DB へ入り、起床した相手は自分の
    DB を見て何も見つけられず、待機は別 DB を待機予算いっぱいポーリングする）。どちらを
    優先するかを推定して解決できる矛盾ではないため、送信前にエラー終了する。
    """

    def test_conflicting_db_path_and_project_root_is_rejected_before_sending(self):
        h = _Harness()
        with tempfile.TemporaryDirectory() as tmpdir:
            body_file = Path(tmpdir) / "body.md"
            body_file.write_text("x\n", encoding="utf-8")
            with mock.patch.object(composite, "do_send", h._send), \
                 mock.patch.object(composite, "do_wake", h._wake):
                code = composite.main([
                    "claude", "codex",
                    "--body-file", str(body_file),
                    "--header-regex", _HEADER_RE,
                    "--thread-id", "rid",
                    "--project-root", tmpdir,
                    "--db-path", "/tmp/somewhere-else.db",
                ])

        self.assertEqual(code, 1)
        # 送信も起床もしていないこと（タイムアウトまで待たせず起動直後に失敗する）
        self.assertEqual(h.calls, [])

    def test_matching_db_path_and_project_root_is_allowed(self):
        """一致している場合は許容する（同じことを明示しているだけ）。"""
        h = _Harness()
        with tempfile.TemporaryDirectory() as tmpdir:
            body_file = Path(tmpdir) / "body.md"
            body_file.write_text("x\n", encoding="utf-8")
            derived = composite.derived_db_path(tmpdir)
            buf = _FakeStdout()
            with mock.patch.object(composite, "do_send", h._send), \
                 mock.patch.object(composite, "do_wake", h._wake), \
                 mock.patch.object(composite.waiter, "wait_for_reply", h._wait), \
                 mock.patch.object(composite.sys, "stdout", buf):
                code = composite.main([
                    "claude", "codex",
                    "--body-file", str(body_file),
                    "--header-regex", _HEADER_RE,
                    "--thread-id", "rid",
                    "--project-root", tmpdir,
                    "--db-path", str(derived),
                ])

        self.assertEqual(code, 0)
        self.assertEqual(h.calls, ["send", "wake", "wait"])

    def test_resolver_rejects_conflict(self):
        with self.assertRaises(ValueError) as ctx:
            composite.resolve_consistent_db_path("/tmp/proj", "/tmp/other.db")
        self.assertIn("返信が届きません", str(ctx.exception))

    def test_resolver_accepts_match(self):
        derived = composite.derived_db_path("/tmp/proj")
        self.assertEqual(
            composite.resolve_consistent_db_path("/tmp/proj", str(derived)), derived
        )

    def test_wake_is_not_suppressed_by_db_path(self):
        """`--db-path` は起床抑制の手段ではない（抑制は `--no-wake` の役割）。

        一致した DB を明示しただけで起床が止まると、抑制手段が 2 系統になり
        「なぜ起床しなかったか」が読み取れなくなる。
        """
        h = _Harness()
        with tempfile.TemporaryDirectory() as tmpdir:
            body_file = Path(tmpdir) / "body.md"
            body_file.write_text("x\n", encoding="utf-8")
            buf = _FakeStdout()
            with mock.patch.object(composite, "do_send", h._send), \
                 mock.patch.object(composite, "do_wake", h._wake), \
                 mock.patch.object(composite.waiter, "wait_for_reply", h._wait), \
                 mock.patch.object(composite.sys, "stdout", buf):
                composite.main([
                    "claude", "codex",
                    "--body-file", str(body_file),
                    "--header-regex", _HEADER_RE,
                    "--thread-id", "rid",
                    "--project-root", tmpdir,
                    "--db-path", str(composite.derived_db_path(tmpdir)),
                ])

        self.assertIn("wake", h.calls)


class InReplyToTest(unittest.TestCase):
    """`--in-reply-to` がそのまま送信へ渡ること（スレッド連鎖の判定に必須）。"""

    def test_in_reply_to_is_passed_through(self):
        h = _Harness()
        _run(h, ["--in-reply-to", "prev-id"])
        self.assertEqual(h.send_kwargs["in_reply_to"], "prev-id")

    def test_absent_in_reply_to_is_none(self):
        h = _Harness()
        _run(h)
        self.assertIsNone(h.send_kwargs["in_reply_to"])


class HeaderRegexValidationTest(unittest.TestCase):
    """capture group の無い正規表現を起動時に弾く（待機中の IndexError を防ぐ）。"""

    def test_regex_without_capture_group_is_rejected(self):
        with self.assertRaises(ValueError):
            composite.compile_header_regex(r"^\[msg-review\]")

    def test_regex_with_capture_group_is_accepted(self):
        self.assertIsNotNone(composite.compile_header_regex(_HEADER_RE))

    def test_main_rejects_bad_regex_before_sending(self):
        h = _Harness()
        with tempfile.TemporaryDirectory() as tmpdir:
            body_file = Path(tmpdir) / "body.md"
            body_file.write_text("x\n", encoding="utf-8")
            with mock.patch.object(composite, "do_send", h._send):
                code = composite.main([
                    "claude", "codex",
                    "--body-file", str(body_file),
                    "--header-regex", r"^\[msg-review\]",
                    "--thread-id", "rid",
                    "--db-path", "/tmp/x.db",
                ])
        self.assertEqual(code, 1)
        self.assertEqual(h.calls, [])


class WakeOutputParsingTest(unittest.TestCase):
    """`do_wake` が起床スクリプトの出力を解析する（解析不能を skipped に畳まない）。"""

    def test_valid_json_is_passed_through(self):
        def runner(cmd, **_kwargs):
            return mock.Mock(stdout='{"status": "sent", "reason": ""}\n', returncode=0)

        result = composite.do_wake("/tmp/proj", runner=runner)
        self.assertEqual(result["status"], "sent")

    def test_unparsable_output_is_failed_not_skipped(self):
        def runner(cmd, **_kwargs):
            return mock.Mock(stdout="not json\n", returncode=0)

        result = composite.do_wake("/tmp/proj", runner=runner)
        self.assertEqual(result["status"], "failed")

    def test_missing_project_root_is_skipped(self):
        result = composite.do_wake(None)
        self.assertEqual(result["status"], "skipped")


class CliContractTest(unittest.TestCase):
    """CLI に本文の標準入力経路を持たせない（シェル経由の本文組み立てを防ぐ）。"""

    def test_body_file_is_required(self):
        with self.assertRaises(SystemExit):
            composite.parse_args([
                "claude", "codex",
                "--header-regex", _HEADER_RE,
                "--thread-id", "rid",
            ])

    def test_no_stdin_body_option_exists(self):
        text = _SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertNotIn("sys.stdin.read()", text)


if __name__ == "__main__":
    unittest.main()
