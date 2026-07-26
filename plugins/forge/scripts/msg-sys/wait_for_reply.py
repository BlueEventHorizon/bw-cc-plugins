#!/usr/bin/env python3
"""msg-sys: 依頼直後のブロッキング待機 CLI（DES-045 §3.7 の汎用化）。

`/forge:review` の codex エンジン呼び出し（`codex exec` サブプロセス）は Bash subprocess の
終了を待つことで同期的に見える。本スクリプトは、Claude 側 Stop フック（`check_inbox.py`）が
Stop イベント1回につき受信箱を1度だけ確認して即座に返す（待機・リトライを行わない）ことに
代わって、送信直後から read-only な履歴確認を直接繰り返すことで、依頼を送った側が同一ターン内で
完了まで進めるようにする。

停止条件は完了宣言行の有無ではなく、対象スレッドの往復に `sender=<agent_b>` のメッセージが
1件でも増えたことである（review では `findings`（指摘あり）の返信でも後続処理に進める
必要があるのと同様、本スクリプトはプロトコルの完了判定そのものには関与しない）。

**プロトコル非依存化（レビュー専用実装からの汎用化）**: スレッド判定は
`thread_filter.py`（同ディレクトリ）に委譲し、呼び出し側が渡す `--header-regex`
（body 先頭行から thread_id を1個の capture group で取り出す正規表現）と `--thread-id` の
組み合わせで、どのプロトコル（review の `review_id` ヘッダ・talk-to-codex の
`topic_id` ヘッダ等）にも対応できるようにしてある。

検知したメッセージは、返す前に自ら `inbox.py <agent_a> --ack <id>` で既読化する。Stop フック
経由の受信（`check_inbox.py` の ack）を経由しないため、既読化しないまま残すと、後で無関係な
別ターンで Stop フックが同じメッセージを未読として再検知し、二重に差し戻してしまう。

使い方:
    python3 wait_for_reply.py <agent_a> <agent_b> --header-regex "<正規表現>" --thread-id <id> \
        [--max-seconds 600] [--progress-interval 10] \
        [--initial-interval 1] [--backoff-factor 2] [--max-interval 10] \
        [--db-path <path>]
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import thread_filter  # noqa: E402

INBOX_SCRIPT = Path(__file__).resolve().parent / "inbox.py"


def ack_message(agent_name: str, message_id: str, db_path: str | None) -> bool:
    """`inbox.py <agent_name> --ack <message_id>` を呼び、配信権を得られたかを返す。

    `inbox.py --ack` は mailbox.ack() の条件付き UPDATE（`WHERE read_at IS NULL`）の
    結果をそのまま終了コードで返す（成功=0、他プロセスが先に既読化済み=非0）。
    戻り値を捨てると、Stop フック等の別経路が同じメッセージを先に ack した場合でも
    このプロセスが「配信を受け取った」と誤認し、同一メッセージを二重に処理・返信
    しうる（実 Codex レビューで指摘）。呼び出し側はこの戻り値で配信権の有無を判定する。
    """
    cmd = [sys.executable, str(INBOX_SCRIPT), agent_name, "--ack", message_id]
    if db_path:
        cmd += ["--db-path", db_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def find_new_reply(messages: list[dict], agent_b: str) -> list[dict]:
    """対象スレッドの履歴の中から agent_b 発のメッセージを抽出する（停止条件の判定材料）。"""
    return [msg for msg in messages if msg.get("sender") == agent_b]


def _most_recent_message_from(messages: list[dict], sender: str) -> dict | None:
    """指定 sender 発のメッセージのうち sent_at が最大のものを返す（無ければ None）。"""
    candidates = [msg for msg in messages if msg.get("sender") == sender]
    if not candidates:
        return None
    return max(candidates, key=lambda msg: msg["sent_at"])


def wait_for_reply(
    agent_a: str,
    agent_b: str,
    header_regex: re.Pattern[str],
    thread_id: str,
    *,
    max_seconds: float,
    progress_interval: float,
    initial_interval: float,
    backoff_factor: float,
    max_interval: float,
    db_path: str | None,
    sleep=time.sleep,
    now=time.monotonic,
    emit=print,
) -> dict:
    """ポーリングを実行し、最終結果の dict を返す（呼び出し側が JSON へシリアライズする）。

    `sleep`/`now`/`emit` はテストで差し替えるための注入ポイント。
    """
    start = now()
    last_progress = start
    interval = initial_interval
    # 直前のポーリングで取得済みのスレッド（timeout 診断用。Codex とのディスカッション
    # で提起された「タイムアウト時に既読/未読を区別して再開しやすくする」改善提案への
    # 対応）。ループ先頭の timeout チェック時点では今回分の fetch を行っていないため、
    # 1つ前のポーリング結果を使う（timeout 判定のためだけに追加の fetch は行わない）。
    last_filtered: list[dict] = []

    while True:
        elapsed = now() - start
        if elapsed >= max_seconds:
            # この値は最後に完了したポーリング時点の観測結果であり、タイムアウト宣言の
            # 瞬間の状態ではない（実 Codex レビューで発見: 最終 sleep 中に agent_b が
            # ちょうど ack した場合でも、最大 1 ポーリング間隔（既定上限10秒）分古い
            # `False` を返しうる）。タイムアウト診断のためだけに追加の fetch は行わない
            # （待機時間を延ばしてしまう）ため、フィールド名に `last_observed_` を付け、
            # 「最後に確認した時点では」という限定を常に明示する契約にする。
            last_request = _most_recent_message_from(last_filtered, agent_a)
            last_observed_request_read_by_agent_b = (
                None if last_request is None else last_request.get("read_at") is not None
            )
            return {
                "status": "timeout",
                "elapsed_seconds": int(elapsed),
                "last_observed_request_read_by_agent_b": last_observed_request_read_by_agent_b,
            }

        messages = thread_filter.fetch_history(agent_a, agent_b, db_path)
        filtered = thread_filter.filter_by_thread(messages, header_regex, thread_id)
        last_filtered = filtered
        replies = find_new_reply(filtered, agent_b)
        if replies:
            # 配信権（ack 成功）を得られたメッセージが1件でもあれば replied とする。
            # 全件が他プロセス（Stop フック等）に先を越されていた場合、このプロセスは
            # 配信を受け取っていないため replied とせずポーリングを継続する
            # （二重処理防止。実 Codex レビューで指摘）。
            # `any(... for ...)` は最初の True で短絡するため、同一 poll で複数の
            # 未読返信が見つかった場合、先頭以外は ack されないまま `filtered` に
            # 含まれて返ってしまう（実 Codex レビューで発見の回帰: 未 ack のまま
            # 返却された返信を呼び出し元が処理した後、Stop フックが未読として
            # 再配信し二重処理になる）。リスト内包表記で全候補を必ず ack してから
            # 判定する。
            ack_results = [ack_message(agent_a, msg["id"], db_path) for msg in replies]
            # `messages`（スレッド全体、文脈用）と、実際にこの呼び出しで配信権を
            # 得られた返信の id 一覧（`delivered_ids`）を分離して返す。全候補への
            # ack 試行だけでは不十分で、ack の成否が返信ごとに異なりうる（同一 poll
            # 内で古い返信の ack は成功し、より新しい返信の ack は Stop フック等の
            # 別プロセスに先を越されて失敗する等）。呼び出し側が「直近の Codex 発
            # メッセージ」を `messages` の sent_at 最大値だけで選ぶと、ack に負けた
            # （＝別プロセスが既に配信を受けている）メッセージを誤って選び、二重
            # 処理を招く（実 Codex レビューで発見）。`delivered_ids` に含まれる
            # メッセージのみが、この呼び出しが安全に処理してよい新規返信である。
            delivered_ids = [
                msg["id"] for msg, acked in zip(replies, ack_results) if acked
            ]
            if delivered_ids:
                return {
                    "status": "replied",
                    "messages": filtered,
                    "delivered_ids": delivered_ids,
                }

        t = now()
        if t - last_progress >= progress_interval:
            emit(f"経過{int(t - start)}秒、まだ返信なし")
            last_progress = t

        remaining = max_seconds - (now() - start)
        if remaining <= 0:
            continue
        sleep(min(interval, remaining))
        interval = min(interval * backoff_factor, max_interval)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="依頼直後のブロッキング待機 CLI（DES-045 §3.7 の汎用化）",
    )
    parser.add_argument("agent_a")
    parser.add_argument("agent_b")
    parser.add_argument(
        "--header-regex",
        required=True,
        help="body 先頭行から thread_id を抽出する正規表現（capture group 1 が thread_id）",
    )
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--max-seconds", type=float, default=600.0)
    parser.add_argument("--progress-interval", type=float, default=10.0)
    parser.add_argument("--initial-interval", type=float, default=1.0)
    parser.add_argument("--backoff-factor", type=float, default=2.0)
    parser.add_argument("--max-interval", type=float, default=10.0)
    parser.add_argument(
        "--db-path",
        default=None,
        help="messages.db のパス（省略時は history.py 側の導出規則に従う）",
    )
    args = parser.parse_args()

    try:
        header_regex = re.compile(args.header_regex)
    except re.error as exc:
        print(f"--header-regex が不正な正規表現です: {exc}", file=sys.stderr)
        return 1
    if header_regex.groups < 1:
        # compile 自体は成功するが capture group が無い正規表現（thread_id を
        # 取り出せない契約違反）を許すと、`parse_thread_id` 内の `match.group(1)`
        # が IndexError で落ち、この main() の RuntimeError ハンドラも通らず
        # traceback で終了する（実 Codex レビューで発見）。起動時に検証し、
        # 利用者向けの分かりやすいエラーメッセージへ変換する。
        print(
            "--header-regex には thread_id を取り出す capture group が"
            "少なくとも1つ必要です（例: '(\\S+)'）",
            file=sys.stderr,
        )
        return 1

    try:
        result = wait_for_reply(
            args.agent_a,
            args.agent_b,
            header_regex,
            args.thread_id,
            max_seconds=args.max_seconds,
            progress_interval=args.progress_interval,
            initial_interval=args.initial_interval,
            backoff_factor=args.backoff_factor,
            max_interval=args.max_interval,
            db_path=args.db_path,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") == "replied" else 1


if __name__ == "__main__":
    raise SystemExit(main())
