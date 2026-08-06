#!/usr/bin/env python3
"""
wait_for_reply.py のテスト（DES-045 §3.7 の汎用化 / §7 テスト設計）

`history.py`/`inbox.py` への subprocess 呼び出しはモックし、実時間には依存しない
フェイク時計（`now`/`sleep` の注入）で、停止条件（sender=agent_b の増加。resolved
未達=findings でも停止する）・既読化・タイムアウト・指数バックオフ・進捗表示を検証する
（`tests/forge/msg-review/test_filter_review_history.py` の importlib 直接ロード・
subprocess.run モックのパターンを踏襲）。

msg-review 専用の `review_id` 固定 CLI から `--header-regex`/`--thread-id` の
プロトコル非依存 CLI への汎用化に伴い、テストも `[msg-review] ... review_id=(\\S+) ...`
相当の正規表現を明示的に渡す形へ更新した。

実行:
  python3 -m unittest tests.forge.msg-sys.test_wait_for_reply -v
"""

import importlib.util
import re
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "scripts" / "msg-sys" / "wait_for_reply.py"
)

_spec = importlib.util.spec_from_file_location("msg_sys_wait_for_reply", _SCRIPT_PATH)
wait_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wait_mod)

# msg-review のヘッダ正規表現と同型（テスト専用。実運用の正規表現は filter_review_history.py 側）。
REVIEW_ID_RE = re.compile(r"^\[msg-review\]\s+\S+\s+review_id=(\S+)\s+round=\d+\s*$")


def _msg(review_id, sender, recipient, sent_at, msg_id, extra_body="", read_at=None):
    header = f"[msg-review] code review_id={review_id} round=1"
    body = header if not extra_body else f"{header}\n{extra_body}"
    return {
        "id": msg_id,
        "sender": sender,
        "recipient": recipient,
        "body": body,
        "sent_at": sent_at,
        "read_at": read_at,
    }


class _FakeClock:
    """`now`/`sleep` を差し替えるためのフェイク時計。sleep するたびに時刻を進める。"""

    def __init__(self):
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


class WaitForReplyTest(unittest.TestCase):
    """wait_for_reply(): 停止条件・既読化・タイムアウト・バックオフ・進捗表示（DES-045 §3.7）。"""

    def test_stops_when_sender_b_message_appears_even_if_findings_not_approved(self):
        """resolved（approved）未達=findings でも、agent_b 発メッセージの増加だけで停止する。"""
        clock = _FakeClock()
        request_only = [_msg("rev-A", "claude", "codex", sent_at=1.0, msg_id="m1")]
        with_findings = request_only + [
            _msg(
                "rev-A", "codex", "claude", sent_at=2.0, msg_id="m2",
                extra_body="🔴 critical 所見あり\nREVIEW_RESULT: findings",
            ),
        ]
        fetch_mock = mock.Mock(side_effect=[request_only, with_findings])
        ack_mock = mock.Mock()
        with mock.patch.object(wait_mod.thread_filter, "fetch_history", fetch_mock):
            with mock.patch.object(wait_mod, "ack_message", ack_mock):
                result = wait_mod.wait_for_reply(
                    "claude", "codex", REVIEW_ID_RE, "rev-A",
                    max_seconds=1000, progress_interval=10,
                    initial_interval=1, backoff_factor=2, max_interval=10,
                    db_path=None, sleep=clock.sleep, now=clock.now, emit=lambda _: None,
                )

        self.assertEqual(result["status"], "replied")
        self.assertEqual([m["id"] for m in result["messages"]], ["m1", "m2"])
        self.assertEqual(result["delivered_ids"], ["m2"])

    def test_acks_detected_reply_before_returning(self):
        clock = _FakeClock()
        with_reply = [
            _msg("rev-A", "claude", "codex", sent_at=1.0, msg_id="m1"),
            _msg("rev-A", "codex", "claude", sent_at=2.0, msg_id="m2"),
        ]
        fetch_mock = mock.Mock(return_value=with_reply)
        ack_mock = mock.Mock()
        with mock.patch.object(wait_mod.thread_filter, "fetch_history", fetch_mock):
            with mock.patch.object(wait_mod, "ack_message", ack_mock):
                wait_mod.wait_for_reply(
                    "claude", "codex", REVIEW_ID_RE, "rev-A",
                    max_seconds=1000, progress_interval=10,
                    initial_interval=1, backoff_factor=2, max_interval=10,
                    db_path="/tmp/messages.db", sleep=clock.sleep, now=clock.now,
                    emit=lambda _: None,
                )

        ack_mock.assert_called_once_with("claude", "m2", "/tmp/messages.db")

    def test_acks_every_reply_even_when_multiple_arrive_in_the_same_poll(self):
        """同一 poll で複数の未読返信が見つかった場合、全件に ack を試行する。

        実 Codex レビューで発見の回帰: `any(ack_message(...) for msg in replies)` は
        最初の ack 成功で短絡し、後続の返信が未 ack のまま `messages` に含まれて
        返っていた。呼び出し元が未 ack の返信を処理した後、Stop フックがそれを
        未読として再配信し二重処理になる。全候補への ack 試行を検証する。
        """
        clock = _FakeClock()
        with_two_replies = [
            _msg("rev-A", "claude", "codex", sent_at=1.0, msg_id="m1"),
            _msg("rev-A", "codex", "claude", sent_at=2.0, msg_id="m2"),
            _msg("rev-A", "codex", "claude", sent_at=3.0, msg_id="m3"),
        ]
        fetch_mock = mock.Mock(return_value=with_two_replies)
        ack_mock = mock.Mock(return_value=True)
        with mock.patch.object(wait_mod.thread_filter, "fetch_history", fetch_mock):
            with mock.patch.object(wait_mod, "ack_message", ack_mock):
                result = wait_mod.wait_for_reply(
                    "claude", "codex", REVIEW_ID_RE, "rev-A",
                    max_seconds=1000, progress_interval=10,
                    initial_interval=1, backoff_factor=2, max_interval=10,
                    db_path=None, sleep=clock.sleep, now=clock.now, emit=lambda _: None,
                )

        self.assertEqual(result["status"], "replied")
        acked_ids = [call.args[1] for call in ack_mock.call_args_list]
        self.assertEqual(acked_ids, ["m2", "m3"])
        self.assertEqual(result["delivered_ids"], ["m2", "m3"])

    def test_delivered_ids_excludes_replies_that_lost_the_ack_race(self):
        """同一 poll 内で ack の成否が返信ごとに異なる場合、`delivered_ids` には
        ack に成功した返信の id のみを含める（`messages` 全体ではない）。

        実 Codex レビューで発見の回帰: 古い返信（m2）の ack は成功し、より新しい
        返信（m3）の ack は Stop フック等の別プロセスに先を越されて失敗するケースで、
        呼び出し元が `messages` を `sent_at` 最大値だけで走査すると m3（他プロセスが
        既に配信を受けている）を誤って新規返信として処理し、二重処理になる。
        """
        clock = _FakeClock()
        with_two_replies = [
            _msg("rev-A", "claude", "codex", sent_at=1.0, msg_id="m1"),
            _msg("rev-A", "codex", "claude", sent_at=2.0, msg_id="m2"),
            _msg("rev-A", "codex", "claude", sent_at=3.0, msg_id="m3"),
        ]
        fetch_mock = mock.Mock(return_value=with_two_replies)
        # m2（古い）の ack は成功、m3（新しい）の ack は他プロセスに先を越されて失敗。
        ack_mock = mock.Mock(side_effect=lambda agent, msg_id, db_path: msg_id == "m2")
        with mock.patch.object(wait_mod.thread_filter, "fetch_history", fetch_mock):
            with mock.patch.object(wait_mod, "ack_message", ack_mock):
                result = wait_mod.wait_for_reply(
                    "claude", "codex", REVIEW_ID_RE, "rev-A",
                    max_seconds=1000, progress_interval=10,
                    initial_interval=1, backoff_factor=2, max_interval=10,
                    db_path=None, sleep=clock.sleep, now=clock.now, emit=lambda _: None,
                )

        self.assertEqual(result["status"], "replied")
        self.assertEqual([m["id"] for m in result["messages"]], ["m1", "m2", "m3"])
        # delivered_ids は ack に成功した m2 のみ。m3 は他プロセスが処理中のため含めない。
        self.assertEqual(result["delivered_ids"], ["m2"])

    def test_does_not_report_replied_when_ack_loses_the_race(self):
        """全件が他プロセス（Stop フック等）に先を越された場合、replied にせず継続する。

        実 Codex レビューで指摘された回帰: ack の戻り値（配信権の有無）を無視すると、
        Stop フックが先に処理済みの返信を二重に評価・修正・返信してしまう。
        """
        clock = _FakeClock()
        with_reply = [
            _msg("rev-A", "claude", "codex", sent_at=1.0, msg_id="m1"),
            _msg("rev-A", "codex", "claude", sent_at=2.0, msg_id="m2"),
        ]
        fetch_mock = mock.Mock(return_value=with_reply)
        # 常に配信権を得られない（他プロセスが先に ack 済み）を模擬する。
        ack_mock = mock.Mock(return_value=False)
        with mock.patch.object(wait_mod.thread_filter, "fetch_history", fetch_mock):
            with mock.patch.object(wait_mod, "ack_message", ack_mock):
                result = wait_mod.wait_for_reply(
                    "claude", "codex", REVIEW_ID_RE, "rev-A",
                    max_seconds=5, progress_interval=100,
                    initial_interval=1, backoff_factor=2, max_interval=10,
                    db_path=None, sleep=clock.sleep, now=clock.now, emit=lambda _: None,
                )

        self.assertEqual(result["status"], "timeout")
        self.assertGreater(ack_mock.call_count, 1)

    def test_reports_replied_once_a_later_poll_wins_the_ack_race(self):
        """先に検知した返信の ack に負けても、後続ポーリングで新規返信の ack に勝てば replied にする。"""
        clock = _FakeClock()
        first_reply_only = [
            _msg("rev-A", "claude", "codex", sent_at=1.0, msg_id="m1"),
            _msg("rev-A", "codex", "claude", sent_at=2.0, msg_id="m2"),
        ]
        second_reply_added = first_reply_only + [
            _msg("rev-A", "codex", "claude", sent_at=3.0, msg_id="m3"),
        ]
        fetch_mock = mock.Mock(side_effect=[first_reply_only, second_reply_added])
        # m2 は他プロセスに先を越され（False）、m3 は自分が配信権を得る（True）。
        ack_mock = mock.Mock(side_effect=lambda agent, msg_id, db_path: msg_id == "m3")
        with mock.patch.object(wait_mod.thread_filter, "fetch_history", fetch_mock):
            with mock.patch.object(wait_mod, "ack_message", ack_mock):
                result = wait_mod.wait_for_reply(
                    "claude", "codex", REVIEW_ID_RE, "rev-A",
                    max_seconds=1000, progress_interval=10,
                    initial_interval=1, backoff_factor=2, max_interval=10,
                    db_path=None, sleep=clock.sleep, now=clock.now, emit=lambda _: None,
                )

        self.assertEqual(result["status"], "replied")
        self.assertEqual([m["id"] for m in result["messages"]], ["m1", "m2", "m3"])

    def test_returns_timeout_status_when_max_seconds_reached(self):
        clock = _FakeClock()
        no_reply = [_msg("rev-A", "claude", "codex", sent_at=1.0, msg_id="m1", read_at=None)]
        fetch_mock = mock.Mock(return_value=no_reply)
        with mock.patch.object(wait_mod.thread_filter, "fetch_history", fetch_mock):
            result = wait_mod.wait_for_reply(
                "claude", "codex", REVIEW_ID_RE, "rev-A",
                max_seconds=5, progress_interval=100,
                initial_interval=1, backoff_factor=2, max_interval=10,
                db_path=None, sleep=clock.sleep, now=clock.now, emit=lambda _: None,
            )

        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["elapsed_seconds"], 5)
        # agent_a（claude）発の依頼が、最後に確認した時点では未読のまま（read_at=None）
        # であったことを診断情報として返す（実装ミス防止: Codex がまだ依頼を見ていない
        # ＝常駐していない可能性の signal）。フィールド名に `last_observed_` を付け、
        # タイムアウト宣言の瞬間の状態ではなく最後のポーリング時点の観測値であることを
        # 明示する（実 Codex レビューで発見: 最終 sleep 中に ack された場合、最大1ポーリング
        # 間隔分古い値になりうる）。
        self.assertFalse(result["last_observed_request_read_by_agent_b"])

    def test_timeout_reports_last_observed_request_read_by_agent_b_true_when_read_but_not_replied(self):
        """依頼を agent_b が既読（read_at 設定済み）だが未返信のままタイムアウトした場合、
        `last_observed_request_read_by_agent_b: true` を返す（既読/未読を区別する Codex との
        ディスカッションで提起された改善提案への対応）。
        """
        clock = _FakeClock()
        read_but_no_reply = [
            _msg("rev-A", "claude", "codex", sent_at=1.0, msg_id="m1", read_at=2.0),
        ]
        fetch_mock = mock.Mock(return_value=read_but_no_reply)
        with mock.patch.object(wait_mod.thread_filter, "fetch_history", fetch_mock):
            result = wait_mod.wait_for_reply(
                "claude", "codex", REVIEW_ID_RE, "rev-A",
                max_seconds=5, progress_interval=100,
                initial_interval=1, backoff_factor=2, max_interval=10,
                db_path=None, sleep=clock.sleep, now=clock.now, emit=lambda _: None,
            )

        self.assertEqual(result["status"], "timeout")
        self.assertTrue(result["last_observed_request_read_by_agent_b"])

    def test_timeout_reports_none_when_no_own_message_found_in_thread(self):
        """対象スレッドに agent_a 発のメッセージが1件も見つからない場合、
        既読/未読を判定できないため `last_observed_request_read_by_agent_b: None` を返す。
        """
        clock = _FakeClock()
        fetch_mock = mock.Mock(return_value=[])
        with mock.patch.object(wait_mod.thread_filter, "fetch_history", fetch_mock):
            result = wait_mod.wait_for_reply(
                "claude", "codex", REVIEW_ID_RE, "rev-A",
                max_seconds=5, progress_interval=100,
                initial_interval=1, backoff_factor=2, max_interval=10,
                db_path=None, sleep=clock.sleep, now=clock.now, emit=lambda _: None,
            )

        self.assertEqual(result["status"], "timeout")
        self.assertIsNone(result["last_observed_request_read_by_agent_b"])

    def test_poll_interval_grows_with_backoff_capped_at_max_interval(self):
        clock = _FakeClock()
        no_reply = [_msg("rev-A", "claude", "codex", sent_at=1.0, msg_id="m1")]
        fetch_mock = mock.Mock(return_value=no_reply)
        with mock.patch.object(wait_mod.thread_filter, "fetch_history", fetch_mock):
            wait_mod.wait_for_reply(
                "claude", "codex", REVIEW_ID_RE, "rev-A",
                max_seconds=30, progress_interval=1000,
                initial_interval=1, backoff_factor=2, max_interval=10,
                db_path=None, sleep=clock.sleep, now=clock.now, emit=lambda _: None,
            )

        # 1, 2, 4, 8, 10(=cap), 10, ... の順で増加し、10 を超えない
        self.assertEqual(clock.sleeps[:5], [1, 2, 4, 8, 10])
        self.assertTrue(all(s <= 10 for s in clock.sleeps))

    def test_progress_emitted_at_progress_interval(self):
        clock = _FakeClock()
        no_reply = [_msg("rev-A", "claude", "codex", sent_at=1.0, msg_id="m1")]
        fetch_mock = mock.Mock(return_value=no_reply)
        emitted = []
        with mock.patch.object(wait_mod.thread_filter, "fetch_history", fetch_mock):
            wait_mod.wait_for_reply(
                "claude", "codex", REVIEW_ID_RE, "rev-A",
                max_seconds=25, progress_interval=10,
                initial_interval=1, backoff_factor=2, max_interval=10,
                db_path=None, sleep=clock.sleep, now=clock.now, emit=emitted.append,
            )

        # 1,2,4,8(=15s経過) の後に progress が出て、以後 10 秒おきに継続する
        self.assertTrue(any("経過" in line and "秒" in line for line in emitted))
        self.assertGreaterEqual(len(emitted), 1)


class MainSmokeTest(unittest.TestCase):
    """main(): CLI 引数処理・単一 JSON 出力・終了コード契約（DES-045 §3.7 の汎用化）。"""

    def test_returns_exit_code_1_and_timeout_json_when_no_reply(self):
        no_reply = [_msg("rev-A", "claude", "codex", sent_at=1.0, msg_id="m1")]
        argv = [
            "wait_for_reply.py", "claude", "codex",
            "--header-regex", REVIEW_ID_RE.pattern, "--thread-id", "rev-A",
            "--max-seconds", "0", "--progress-interval", "100",
        ]
        with mock.patch.object(wait_mod.thread_filter, "fetch_history", return_value=no_reply):
            with mock.patch.object(wait_mod.sys, "argv", argv):
                with mock.patch.object(wait_mod.time, "sleep", lambda *_: None):
                    exit_code = wait_mod.main()
        self.assertEqual(exit_code, 1)

    def test_omitted_wait_options_use_module_defaults(self):
        captured = {}

        def fake_wait(*_args, **kwargs):
            captured.update(kwargs)
            return {"status": "timeout"}

        argv = [
            "wait_for_reply.py", "claude", "codex",
            "--header-regex", REVIEW_ID_RE.pattern, "--thread-id", "rev-A",
            "--db-path", "/tmp/messages.db",
        ]
        with mock.patch.object(wait_mod, "wait_for_reply", side_effect=fake_wait):
            with mock.patch.object(wait_mod.sys, "argv", argv):
                exit_code = wait_mod.main()

        self.assertEqual(exit_code, 1)
        self.assertEqual(captured["max_seconds"], wait_mod.DEFAULT_MAX_SECONDS)
        self.assertEqual(
            captured["progress_interval"], wait_mod.DEFAULT_PROGRESS_INTERVAL
        )
        self.assertEqual(
            captured["initial_interval"], wait_mod.DEFAULT_INITIAL_INTERVAL
        )
        self.assertEqual(
            captured["backoff_factor"], wait_mod.DEFAULT_BACKOFF_FACTOR
        )
        self.assertEqual(captured["max_interval"], wait_mod.DEFAULT_MAX_INTERVAL)

    def test_invalid_header_regex_returns_exit_code_1(self):
        argv = [
            "wait_for_reply.py", "claude", "codex",
            "--header-regex", "(unbalanced", "--thread-id", "rev-A",
        ]
        with mock.patch.object(wait_mod.sys, "argv", argv):
            exit_code = wait_mod.main()
        self.assertEqual(exit_code, 1)

    def test_header_regex_without_capture_group_returns_exit_code_1(self):
        """compile 自体は成功するが capture group を持たない正規表現は起動時に拒否する
        （実 Codex レビューで発見: 検証なしだと parse_thread_id 内の match.group(1) が
        IndexError で落ち、RuntimeError ハンドラも通らず traceback で終了していた）。
        """
        argv = [
            "wait_for_reply.py", "claude", "codex",
            "--header-regex", r"^\[msg-talk\]", "--thread-id", "rev-A",
        ]
        with mock.patch.object(wait_mod.sys, "argv", argv):
            exit_code = wait_mod.main()
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
