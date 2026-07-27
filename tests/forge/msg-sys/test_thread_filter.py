#!/usr/bin/env python3
"""thread_filter.py の単体テスト（DES-045 §3.6 の汎用化）。

`filter_review_history.py`（旧・review_id 専用実装）から切り出したプロトコル非依存の
履歴取得・スレッド判定ロジックを、msg-review 以外のプロトコル（`[msg-talk] topic_id=...`
ヘッダ等）でも動くことを含めて検証する。
"""

import importlib.util
import json
import re
import subprocess
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "scripts" / "msg-sys" / "thread_filter.py"
)

_spec = importlib.util.spec_from_file_location("msg_sys_thread_filter", _SCRIPT_PATH)
thread_filter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(thread_filter)

REVIEW_ID_RE = re.compile(r"^\[msg-review\]\s+\S+\s+review_id=(\S+)\s+round=\d+\s*$")
TALK_TOPIC_RE = re.compile(r"^\[msg-talk\]\s+topic_id=(\S+)\s*$")


def _review_msg(review_id, sender, recipient, sent_at, msg_id, in_reply_to=None):
    return {
        "id": msg_id, "sender": sender, "recipient": recipient, "sent_at": sent_at,
        "body": f"[msg-review] code review_id={review_id} round=1",
        "in_reply_to": in_reply_to,
    }


def _talk_msg(topic_id, sender, recipient, sent_at, msg_id, in_reply_to=None):
    return {
        "id": msg_id, "sender": sender, "recipient": recipient, "sent_at": sent_at,
        "body": f"[msg-talk] topic_id={topic_id}\n本文",
        "in_reply_to": in_reply_to,
    }


class ParseThreadIdTest(unittest.TestCase):
    def test_raises_value_error_when_header_regex_has_no_capture_group(self):
        """capture group の無い正規表現は IndexError で落とさず ValueError にする
        （実 Codex レビューで発見: 呼び出し元 CLI を経由しない直接 import での契約違反対策）。
        """
        no_group_regex = re.compile(r"^\[msg-talk\]")
        with self.assertRaises(ValueError):
            thread_filter.parse_thread_id("[msg-talk] topic_id=x", no_group_regex)

    def test_extracts_thread_id_with_review_pattern(self):
        body = "[msg-review] code review_id=abc123 round=1\n本文"
        self.assertEqual(thread_filter.parse_thread_id(body, REVIEW_ID_RE), "abc123")

    def test_extracts_thread_id_with_talk_pattern(self):
        body = "[msg-talk] topic_id=xyz789\n本文"
        self.assertEqual(thread_filter.parse_thread_id(body, TALK_TOPIC_RE), "xyz789")

    def test_returns_none_when_pattern_does_not_match(self):
        body = "無関係な本文"
        self.assertIsNone(thread_filter.parse_thread_id(body, TALK_TOPIC_RE))

    def test_empty_body_returns_none(self):
        self.assertIsNone(thread_filter.parse_thread_id("", REVIEW_ID_RE))


class FilterByThreadTest(unittest.TestCase):
    def test_filters_only_matching_thread_in_sent_at_order(self):
        messages = [
            _review_msg("rev-A", "claude", "codex", sent_at=1.0, msg_id="m1"),
            _review_msg("rev-B", "claude", "codex", sent_at=2.0, msg_id="m2"),
            _review_msg("rev-A", "codex", "claude", sent_at=3.0, msg_id="m3"),
        ]
        result = thread_filter.filter_by_thread(messages, REVIEW_ID_RE, "rev-A")
        self.assertEqual([m["id"] for m in result], ["m1", "m3"])

    def test_works_with_a_different_protocol_header(self):
        """talk 用の別ヘッダ正規表現でも同じロジックが動くこと（汎用化の主目的）。"""
        messages = [
            _talk_msg("topic-1", "claude", "codex", sent_at=1.0, msg_id="t1"),
            _talk_msg("topic-2", "claude", "codex", sent_at=2.0, msg_id="t2"),
            {
                "id": "t3", "sender": "codex", "recipient": "claude", "sent_at": 3.0,
                "body": "ヘッダなしの返信", "in_reply_to": "t1",
            },
        ]
        result = thread_filter.filter_by_thread(messages, TALK_TOPIC_RE, "topic-1")
        self.assertEqual([m["id"] for m in result], ["t1", "t3"])

    def test_includes_reply_via_in_reply_to_chain_even_without_header(self):
        messages = [
            _review_msg("rev-A", "claude", "codex", sent_at=1.0, msg_id="root"),
            {
                "id": "reply", "sender": "codex", "recipient": "claude", "sent_at": 2.0,
                "body": "ヘッダなし", "in_reply_to": "root",
            },
        ]
        result = thread_filter.filter_by_thread(messages, REVIEW_ID_RE, "rev-A")
        self.assertEqual([m["id"] for m in result], ["root", "reply"])

    def test_no_match_returns_empty_list(self):
        messages = [_review_msg("rev-A", "claude", "codex", sent_at=1.0, msg_id="m1")]
        result = thread_filter.filter_by_thread(messages, REVIEW_ID_RE, "rev-nonexistent")
        self.assertEqual(result, [])


class SkillIsolationTest(unittest.TestCase):
    """msg-review と talk-to-codex（msg-talk）がスレッド判定を相互に汚染しないことの
    回帰テスト（Codex とのディスカッションで提起された改善提案への対応）。

    両プロトコルは同一の claude<->codex メッセージ履歴（同じ sender/recipient ペア・
    同じ DB）を共有するため、ヘッダ正規表現による root 特定が正しく分離されている
    ことが安全性の前提になる。
    """

    def test_review_and_talk_threads_do_not_leak_into_each_other_when_interleaved(self):
        messages = [
            _review_msg("rev-X", "claude", "codex", sent_at=1.0, msg_id="review-root"),
            _talk_msg("topic-X", "claude", "codex", sent_at=2.0, msg_id="talk-root"),
            {
                "id": "review-reply", "sender": "codex", "recipient": "claude", "sent_at": 3.0,
                "body": "🟡 major 所見\n\nREVIEW_RESULT: findings", "in_reply_to": "review-root",
            },
            {
                "id": "talk-reply", "sender": "codex", "recipient": "claude", "sent_at": 4.0,
                "body": "自由記述の返信", "in_reply_to": "talk-root",
            },
        ]

        review_thread = thread_filter.filter_by_thread(messages, REVIEW_ID_RE, "rev-X")
        talk_thread = thread_filter.filter_by_thread(messages, TALK_TOPIC_RE, "topic-X")

        self.assertEqual([m["id"] for m in review_thread], ["review-root", "review-reply"])
        self.assertEqual([m["id"] for m in talk_thread], ["talk-root", "talk-reply"])
        # 相互に混入していないこと（review 側に talk のメッセージが無い、その逆も無い）。
        self.assertNotIn("talk-root", [m["id"] for m in review_thread])
        self.assertNotIn("talk-reply", [m["id"] for m in review_thread])
        self.assertNotIn("review-root", [m["id"] for m in talk_thread])
        self.assertNotIn("review-reply", [m["id"] for m in talk_thread])

    def test_identical_id_value_across_protocols_does_not_cross_match(self):
        """review_id と topic_id が偶然同じ文字列値でも、ヘッダの構文が異なるため
        クロスマッチしない（id 空間はプロトコルごとに独立に生成されるため、値の
        衝突自体は現実的にはほぼ起きないが、ヘッダ構文による分離が値に依存しない
        ことを保証する回帰）。
        """
        shared_id = "abc123"
        messages = [
            _review_msg(shared_id, "claude", "codex", sent_at=1.0, msg_id="review-root"),
            _talk_msg(shared_id, "claude", "codex", sent_at=2.0, msg_id="talk-root"),
        ]

        review_thread = thread_filter.filter_by_thread(messages, REVIEW_ID_RE, shared_id)
        talk_thread = thread_filter.filter_by_thread(messages, TALK_TOPIC_RE, shared_id)

        self.assertEqual([m["id"] for m in review_thread], ["review-root"])
        self.assertEqual([m["id"] for m in talk_thread], ["talk-root"])


class FetchHistoryTest(unittest.TestCase):
    def test_returns_parsed_list_on_success(self):
        messages = [_review_msg("rev-A", "claude", "codex", sent_at=1.0, msg_id="m1")]
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(messages), stderr=""
        )
        with mock.patch.object(thread_filter.subprocess, "run", return_value=completed) as run_mock:
            result = thread_filter.fetch_history("claude", "codex", None)
        self.assertEqual(result, messages)
        self.assertIn("claude", run_mock.call_args[0][0])

    def test_raises_runtime_error_on_nonzero_exit(self):
        completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
        with mock.patch.object(thread_filter.subprocess, "run", return_value=completed):
            with self.assertRaises(RuntimeError):
                thread_filter.fetch_history("claude", "codex", None)

    def test_raises_runtime_error_on_json_decode_failure(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="not json", stderr="")
        with mock.patch.object(thread_filter.subprocess, "run", return_value=completed):
            with self.assertRaises(RuntimeError):
                thread_filter.fetch_history("claude", "codex", None)

    def test_raises_runtime_error_when_output_is_not_a_list(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps({"not": "a list"}), stderr=""
        )
        with mock.patch.object(thread_filter.subprocess, "run", return_value=completed):
            with self.assertRaises(RuntimeError):
                thread_filter.fetch_history("claude", "codex", None)


class FetchHistoryProjectRootTest(unittest.TestCase):
    """`project_root` から DB パス解決用の環境変数を設定すること。

    history.py は `--db-path` か `FORGE_MSG_PROJECT_ROOT` が無ければ fail closed で
    終了する（DES-034 §7）。前置を呼び出し側の記憶に委ねると繰り返し忘れられるため、
    引数で受け取って本関数が設定する。
    """

    def _run_with(self, **kwargs):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps([]), stderr=""
        )
        with mock.patch.object(
            thread_filter.subprocess, "run", return_value=completed
        ) as run_mock:
            thread_filter.fetch_history("claude", "codex", None, **kwargs)
        return run_mock.call_args

    def test_project_root_is_passed_as_env(self):
        call_args = self._run_with(project_root="/repo/root")
        env = call_args.kwargs["env"]
        self.assertEqual(env[thread_filter.PROJECT_ROOT_ENV], "/repo/root")

    def test_existing_environment_is_preserved(self):
        """既存の環境変数を捨てないこと（PATH 等が消えると subprocess が壊れる）。"""
        with mock.patch.dict(thread_filter.os.environ, {"CUSTOM_VAR": "kept"}):
            call_args = self._run_with(project_root="/repo/root")
        self.assertEqual(call_args.kwargs["env"]["CUSTOM_VAR"], "kept")

    def test_env_is_none_when_project_root_omitted(self):
        """未指定時は環境を差し替えない（従来どおり呼び出し元の env を継承する）。"""
        call_args = self._run_with()
        self.assertIsNone(call_args.kwargs["env"])


if __name__ == "__main__":
    unittest.main()
