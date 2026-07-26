#!/usr/bin/env python3
"""
filter_review_history.py のテスト（DES-045 §3.6 / §7 テスト設計）

history.py への subprocess 呼び出しはモックし、複数 review_id が混在する履歴から
指定 review_id のみを sent_at 昇順で抽出する挙動・round/resolved の算出・一致 0 件時の
フォールバックを検証する（`tests/forge/review/test_resolve_targets.py` の
importlib 直接ロード・`tests/forge/msg-sys/test_check_setup.py` の
subprocess.run モック・main() 契約テストパターンを踏襲）。

実行:
  python3 -m unittest tests.forge.review.test_filter_review_history -v
"""

import importlib.util
import io
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "skills" / "review" / "scripts" / "filter_review_history.py"
)

_spec = importlib.util.spec_from_file_location(
    "msg_review_filter_review_history", _SCRIPT_PATH
)
filter_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(filter_mod)


def _msg(review_id, sender, recipient, sent_at, extra_body="", msg_id="id", in_reply_to=None):
    """review_id ヘッダを先頭行に持つメッセージ dict を組み立てる。"""
    header = f"[msg-review] code review_id={review_id} round=1"
    body = header if not extra_body else f"{header}\n{extra_body}"
    return {
        "id": msg_id,
        "sender": sender,
        "recipient": recipient,
        "body": body,
        "sent_at": sent_at,
        "in_reply_to": in_reply_to,
    }


def _msg_no_header(sender, recipient, sent_at, body, msg_id, in_reply_to=None):
    """ヘッダ行を持たないメッセージ dict を組み立てる（ヘッダ欠落の回帰テスト用）。"""
    return {
        "id": msg_id,
        "sender": sender,
        "recipient": recipient,
        "body": body,
        "sent_at": sent_at,
        "in_reply_to": in_reply_to,
    }


class ParseReviewIdTest(unittest.TestCase):
    """parse_review_id: body 先頭行からの review_id 抽出（DES-045 §3.6）。"""

    def test_extracts_review_id_from_first_line(self):
        body = "[msg-review] code review_id=abc123 round=1\n本文..."
        self.assertEqual(filter_mod.parse_review_id(body), "abc123")

    def test_does_not_pick_up_review_id_outside_first_line(self):
        """先頭行以外に review_id= らしき文字列が出現しても拾わない（境界）。"""
        body = "本文1行目\n[msg-review] code review_id=abc123 round=1"
        self.assertIsNone(filter_mod.parse_review_id(body))

    def test_missing_round_returns_none(self):
        body = "[msg-review] code review_id=abc123\n本文"
        self.assertIsNone(filter_mod.parse_review_id(body))

    def test_malformed_header_returns_none(self):
        body = "review_id=abc123 round=1"
        self.assertIsNone(filter_mod.parse_review_id(body))

    def test_empty_body_returns_none(self):
        self.assertIsNone(filter_mod.parse_review_id(""))

    def test_unrelated_header_without_review_id_returns_none(self):
        body = "[msg-review] code round=1\n本文"
        self.assertIsNone(filter_mod.parse_review_id(body))


class FilterByReviewIdTest(unittest.TestCase):
    """filter_by_review_id: 複数 review_id 混在履歴からの絞り込み・sent_at 昇順（DES-045 §3.6）。"""

    def test_filters_only_matching_review_id_in_sent_at_order(self):
        messages = [
            _msg("rev-A", "claude", "codex", sent_at=1.0, msg_id="m1"),
            _msg("rev-B", "claude", "codex", sent_at=2.0, msg_id="m2"),
            _msg("rev-A", "codex", "claude", sent_at=3.0, msg_id="m3"),
            _msg("rev-B", "codex", "claude", sent_at=4.0, msg_id="m4"),
            _msg("rev-A", "claude", "codex", sent_at=5.0, msg_id="m5"),
        ]

        result = filter_mod.filter_by_review_id(messages, "rev-A")

        self.assertEqual([m["id"] for m in result], ["m1", "m3", "m5"])

    def test_no_match_returns_empty_list(self):
        messages = [_msg("rev-A", "claude", "codex", sent_at=1.0)]
        result = filter_mod.filter_by_review_id(messages, "rev-does-not-exist")
        self.assertEqual(result, [])

    def test_preserves_input_order_when_already_sent_at_ascending(self):
        """history.py の出力は既に sent_at 昇順のため、フィルタのみで順序が保たれる。"""
        messages = [
            _msg("rev-A", "claude", "codex", sent_at=10.0, msg_id="first"),
            _msg("rev-A", "codex", "claude", sent_at=20.0, msg_id="second"),
            _msg("rev-A", "claude", "codex", sent_at=30.0, msg_id="third"),
        ]
        result = filter_mod.filter_by_review_id(messages, "rev-A")
        self.assertEqual([m["sent_at"] for m in result], [10.0, 20.0, 30.0])

    def test_includes_reply_via_in_reply_to_chain_even_without_header(self):
        """実 Codex レビューで発見の回帰: ヘッダ行が欠落した返信でも in_reply_to の連鎖で拾う。

        root（ヘッダあり）-> codex 返信（ヘッダなし・in_reply_to=root）という
        実際に起きた事故を再現する。
        """
        messages = [
            _msg("rev-A", "claude", "codex", sent_at=1.0, msg_id="root"),
            _msg_no_header(
                "codex", "claude", sent_at=2.0,
                body="🔴 critical 所見\n\nREVIEW_RESULT: findings",
                msg_id="reply-no-header", in_reply_to="root",
            ),
        ]
        result = filter_mod.filter_by_review_id(messages, "rev-A")
        self.assertEqual([m["id"] for m in result], ["root", "reply-no-header"])

    def test_includes_multi_hop_chain_without_header_on_intermediate_message(self):
        """root -> ヘッダなし返信A -> ヘッダなし返信B と連鎖が続いても全件拾う。"""
        messages = [
            _msg("rev-A", "claude", "codex", sent_at=1.0, msg_id="root"),
            _msg_no_header(
                "codex", "claude", sent_at=2.0, body="所見A", msg_id="reply-a", in_reply_to="root",
            ),
            _msg_no_header(
                "claude", "codex", sent_at=3.0, body="対応した", msg_id="reply-b", in_reply_to="reply-a",
            ),
        ]
        result = filter_mod.filter_by_review_id(messages, "rev-A")
        self.assertEqual([m["id"] for m in result], ["root", "reply-a", "reply-b"])

    def test_does_not_leak_unrelated_thread_via_in_reply_to(self):
        """別 review_id のスレッドは in_reply_to 連鎖の起点が異なるため混入しない。"""
        messages = [
            _msg("rev-A", "claude", "codex", sent_at=1.0, msg_id="root-a"),
            _msg("rev-B", "claude", "codex", sent_at=2.0, msg_id="root-b"),
            _msg_no_header(
                "codex", "claude", sent_at=3.0, body="rev-B への返信",
                msg_id="reply-b", in_reply_to="root-b",
            ),
        ]
        result = filter_mod.filter_by_review_id(messages, "rev-A")
        self.assertEqual([m["id"] for m in result], ["root-a"])

    def test_missing_in_reply_to_field_falls_back_to_header_only(self):
        """in_reply_to キー自体が無い履歴（後方互換）でもヘッダ一致だけで動作する。"""
        messages = [
            {"id": "m1", "sender": "claude", "recipient": "codex", "sent_at": 1.0,
             "body": "[msg-review] code review_id=rev-A round=1"},
        ]
        result = filter_mod.filter_by_review_id(messages, "rev-A")
        self.assertEqual([m["id"] for m in result], ["m1"])


class ComputeRoundTest(unittest.TestCase):
    """compute_round: 抽出後件数の算出（DES-045 §3.6）。"""

    def test_counts_filtered_messages(self):
        messages = [
            _msg("rev-A", "claude", "codex", sent_at=1.0),
            _msg("rev-A", "codex", "claude", sent_at=2.0),
            _msg("rev-A", "claude", "codex", sent_at=3.0),
        ]
        self.assertEqual(filter_mod.compute_round(messages), 3)

    def test_zero_for_empty_list(self):
        self.assertEqual(filter_mod.compute_round([]), 0)


class ComputeResolvedTest(unittest.TestCase):
    """compute_resolved: reviewer 発の完了宣言行（行全体一致）のみで判定する（DES-045 §3.6）。

    実 Codex レビュー（review_id=043e2823...）で発見された回帰:
    依頼メッセージ自身が返信形式の説明として `REVIEW_RESULT: approved` という
    部分文字列を含むため、reviewer 以外のメッセージも対象にする・部分一致で
    判定すると、Codex が一度も返信していない時点で誤って承認済みと判定される。
    """

    def test_true_when_approved_marker_present(self):
        messages = [
            _msg("rev-A", "claude", "codex", sent_at=1.0),
            _msg(
                "rev-A", "codex", "claude", sent_at=2.0,
                extra_body="所見なし\nREVIEW_RESULT: approved",
            ),
        ]
        self.assertTrue(filter_mod.compute_resolved(messages, "codex"))

    def test_false_when_only_findings_marker_present(self):
        messages = [
            _msg(
                "rev-A", "codex", "claude", sent_at=1.0,
                extra_body="🔴 critical 所見あり\nREVIEW_RESULT: findings",
            ),
        ]
        self.assertFalse(filter_mod.compute_resolved(messages, "codex"))

    def test_false_for_empty_list(self):
        self.assertFalse(filter_mod.compute_resolved([], "codex"))

    def test_false_when_only_initial_request_present(self):
        """初回依頼のみ（Codex 未返信）では resolved は false（実 Codex レビューで発見の回帰）。

        build_review_request.py が組み立てる依頼本文は、返信形式の説明として
        `REVIEW_RESULT: approved` という文字列を含む（例示のため）。
        """
        messages = [
            _msg(
                "rev-A", "claude", "codex", sent_at=1.0,
                extra_body=(
                    "返信の最終行には、次のいずれかの完了宣言行を必ず1行だけ置いてください:\n"
                    "- REVIEW_RESULT: approved（指摘なし・承認）\n"
                    "- REVIEW_RESULT: findings（指摘あり）"
                ),
            ),
        ]
        self.assertFalse(filter_mod.compute_resolved(messages, "codex"))

    def test_ignores_completion_line_from_non_reviewer_sender(self):
        """reviewer（agent_b）以外が送った、行全体一致の完了宣言行は対象外。"""
        messages = [
            _msg(
                "rev-A", "claude", "codex", sent_at=1.0,
                extra_body="REVIEW_RESULT: approved",
            ),
        ]
        self.assertFalse(filter_mod.compute_resolved(messages, "codex"))

    def test_last_occurrence_wins_across_multiple_reviewer_messages(self):
        """reviewer の完了宣言行が複数回にわたる場合、最後の宣言を採用する。"""
        messages = [
            _msg(
                "rev-A", "codex", "claude", sent_at=1.0, msg_id="m1",
                extra_body="所見あり\nREVIEW_RESULT: findings",
            ),
            _msg(
                "rev-A", "claude", "codex", sent_at=2.0, msg_id="m2",
                extra_body="対応しました",
            ),
            _msg(
                "rev-A", "codex", "claude", sent_at=3.0, msg_id="m3",
                extra_body="再レビュー結果、問題なし\nREVIEW_RESULT: approved",
            ),
        ]
        self.assertTrue(filter_mod.compute_resolved(messages, "codex"))


class ZeroMatchTest(unittest.TestCase):
    """一致 0 件時に messages: [] / round: 0 / resolved: false を返しエラーにしない（DES-045 §3.6）。"""

    def test_zero_match_end_to_end_via_fetch_and_filter(self):
        all_messages = [
            _msg("rev-other-1", "claude", "codex", sent_at=1.0),
            _msg("rev-other-2", "codex", "claude", sent_at=2.0),
        ]
        filtered = filter_mod.filter_by_review_id(all_messages, "rev-nonexistent")
        self.assertEqual(filtered, [])
        self.assertEqual(filter_mod.compute_round(filtered), 0)
        self.assertFalse(filter_mod.compute_resolved(filtered, "codex"))


class FetchHistoryTest(unittest.TestCase):
    """fetch_history: history.py の subprocess モック・3 種のエラーパス（DES-045 §3.6）。"""

    def test_returns_parsed_list_on_success(self):
        messages = [_msg("rev-A", "claude", "codex", sent_at=1.0)]
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(messages), stderr=""
        )
        with mock.patch.object(filter_mod.thread_filter.subprocess, "run", return_value=completed) as run_mock:
            result = filter_mod.fetch_history("claude", "codex", None)
        self.assertEqual(result, messages)
        called_cmd = run_mock.call_args[0][0]
        self.assertIn("claude", called_cmd)
        self.assertIn("codex", called_cmd)
        self.assertNotIn("--db-path", called_cmd)

    def test_passes_db_path_when_given(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="[]", stderr="")
        with mock.patch.object(filter_mod.thread_filter.subprocess, "run", return_value=completed) as run_mock:
            filter_mod.fetch_history("claude", "codex", "/tmp/messages.db")
        called_cmd = run_mock.call_args[0][0]
        self.assertIn("--db-path", called_cmd)
        self.assertIn("/tmp/messages.db", called_cmd)

    def test_raises_runtime_error_on_nonzero_exit(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="boom"
        )
        with mock.patch.object(filter_mod.thread_filter.subprocess, "run", return_value=completed):
            with self.assertRaises(RuntimeError) as ctx:
                filter_mod.fetch_history("claude", "codex", None)
        self.assertIn("非ゼロ終了", str(ctx.exception))

    def test_raises_runtime_error_on_json_decode_failure(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="not json", stderr=""
        )
        with mock.patch.object(filter_mod.thread_filter.subprocess, "run", return_value=completed):
            with self.assertRaises(RuntimeError) as ctx:
                filter_mod.fetch_history("claude", "codex", None)
        self.assertIn("パースできません", str(ctx.exception))

    def test_raises_runtime_error_when_output_is_not_a_list(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps({"not": "a list"}), stderr=""
        )
        with mock.patch.object(filter_mod.thread_filter.subprocess, "run", return_value=completed):
            with self.assertRaises(RuntimeError) as ctx:
                filter_mod.fetch_history("claude", "codex", None)
        self.assertIn("配列ではありません", str(ctx.exception))


class _FakeStdout(io.StringIO):
    """sys.stdout.reconfigure() を呼ぶコードをテスト可能にするための io.StringIO 拡張。"""

    def reconfigure(self, **kwargs):
        pass


def _run_main_capture(argv):
    """filter_mod.main() を実行し、標準出力への書き込みを文字列として返す。"""
    buf = _FakeStdout()
    with mock.patch.object(filter_mod.sys, "argv", argv):
        with mock.patch.object(filter_mod.sys, "stdout", buf):
            exit_code = filter_mod.main()
    return buf.getvalue(), exit_code


class MainTest(unittest.TestCase):
    """main(): CLI 引数(agent_a, agent_b, review_id, --db-path)処理・単一 JSON 出力・終了コード（DES-045 §3.6）。"""

    def test_cli_args_processed_and_single_json_output_on_success(self):
        all_messages = [
            _msg("rev-A", "claude", "codex", sent_at=1.0, msg_id="m1"),
            _msg("rev-B", "codex", "claude", sent_at=2.0, msg_id="m2"),
            _msg(
                "rev-A", "codex", "claude", sent_at=3.0, msg_id="m3",
                extra_body="REVIEW_RESULT: approved",
            ),
        ]
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(all_messages), stderr=""
        )
        argv = [
            "filter_review_history.py",
            "claude", "codex", "rev-A",
            "--db-path", "/tmp/messages.db",
        ]
        with mock.patch.object(filter_mod.thread_filter.subprocess, "run", return_value=completed) as run_mock:
            stdout, exit_code = _run_main_capture(argv)

        self.assertEqual(exit_code, 0)
        lines = [line for line in stdout.splitlines() if line.strip()]
        # 単一 JSON 出力（indent 付きでも json.loads で 1 オブジェクトとして読めること）
        payload = json.loads("\n".join(lines))
        self.assertEqual(payload["review_id"], "rev-A")
        self.assertEqual([m["id"] for m in payload["messages"]], ["m1", "m3"])
        self.assertEqual(payload["round"], 2)
        self.assertTrue(payload["resolved"])

        called_cmd = run_mock.call_args[0][0]
        self.assertIn("claude", called_cmd)
        self.assertIn("codex", called_cmd)
        self.assertIn("--db-path", called_cmd)
        self.assertIn("/tmp/messages.db", called_cmd)

    def test_no_db_path_arg_is_optional(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="[]", stderr="")
        argv = ["filter_review_history.py", "claude", "codex", "rev-X"]
        with mock.patch.object(filter_mod.thread_filter.subprocess, "run", return_value=completed):
            stdout, exit_code = _run_main_capture(argv)

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["review_id"], "rev-X")
        self.assertEqual(payload["messages"], [])
        self.assertEqual(payload["round"], 0)
        self.assertFalse(payload["resolved"])

    def test_exit_code_1_and_no_json_when_history_fails(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="db not found"
        )
        argv = ["filter_review_history.py", "claude", "codex", "rev-X"]
        with mock.patch.object(filter_mod.thread_filter.subprocess, "run", return_value=completed):
            stdout, exit_code = _run_main_capture(argv)

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")


if __name__ == "__main__":
    unittest.main()
