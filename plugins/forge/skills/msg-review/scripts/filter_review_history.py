#!/usr/bin/env python3
"""review: review_id による往復履歴の絞り込み CLI。

`history.py <agent_a> <agent_b> [--db-path <path>]` を subprocess で呼び、
Claude/Codex 間の全メッセージ履歴を取得したうえで、指定した `review_id` に属する
メッセージのみを `sent_at` 昇順で抽出する。

**スレッド判定は `in_reply_to`（DB の構造化フィールド）の連鎖を主とし、body 先頭行の
プロトコルヘッダ（`[msg-review] <種別> review_id=<review_id> round=<n>`）
のパースは「連鎖の起点（root）をどのメッセージから始めるか」の特定にのみ使う（実 Codex
レビューで発見の不具合対応）。ヘッダは AI が自由記述本文の一部として手で書く自己申告値
であり、書き忘れ・省略に対して無防備だった（実際に Codex の返信でヘッダ行が丸ごと欠落し、
`wait_for_reply.py` がその返信を検知できずフルの待機時間を浪費する事故が発生した）。
一方 `in_reply_to` は `send.py --in-reply-to` が機械的に設定する構造化フィールドであり、
本文のテキスト内容に依存しない。したがって「ヘッダが一致する」または「`in_reply_to` を
辿って既にスレッドに含まれるメッセージへ到達する」のいずれかを満たすメッセージをスレッドに
含める（両方の判定を OR で合成する fixed-point 探索）。決定論的な列挙・抽出・集計は
スクリプトで実装し、AI の手作業へ委ねない。

**履歴取得・スレッド判定の汎用部分は `plugins/forge/scripts/msg-sys/thread_filter.py` に
委譲する**（talk-to-codex 等、レビュー以外のプロトコルでも同じ判定ロジックを再利用
できるようにするための共通化）。本ファイルは review プロトコル固有のヘッダ正規表現・
`REVIEW_RESULT` 完了宣言行の判定・round/resolved の算出のみを担う。

使い方:
    python3 filter_review_history.py <agent_a> <agent_b> <review_id> \
        [--project-root <path>] [--db-path <path>]

`--project-root` は DB パスの導出起点であり、review スキルの他スクリプト
（`analyze_branch_point.py` / `resolve_targets.py` / `scan_secrets.py` /
`collect_modified_files.py`）と同じ引数名で統一している。渡せば
`FORGE_MSG_PROJECT_ROOT` をシェルで前置する必要はない。
"""

import argparse
import json
import re
import sys
from pathlib import Path

# plugins/forge/skills/msg-review/scripts/filter_review_history.py から見て
# plugins/forge/scripts/msg-sys/ へのパス。parents[0]=scripts, [1]=msg-review, [2]=skills, [3]=forge
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "msg-sys"))
import thread_filter  # noqa: E402

# body 先頭行のみを対象にし、本文中の別箇所の偶然の一致を拾わない。
REVIEW_ID_RE = re.compile(r"^\[msg-review\]\s+\S+\s+review_id=(\S+)\s+round=\d+\s*$")
APPROVED_LINE = "REVIEW_RESULT: approved"
FINDINGS_LINE = "REVIEW_RESULT: findings"
COMPLETION_LINES = (APPROVED_LINE, FINDINGS_LINE)


def filter_by_review_id(messages: list[dict], review_id: str) -> list[dict]:
    """指定した review_id のスレッドに属するメッセージのみを sent_at 昇順で抽出する。

    汎用のスレッド判定（ヘッダ一致 または in_reply_to 連鎖）は
    `thread_filter.filter_by_thread` に委譲する。
    """
    return thread_filter.filter_by_thread(messages, REVIEW_ID_RE, review_id)


def compute_round(messages: list[dict]) -> int:
    return len(messages)


def compute_resolved(messages: list[dict], reviewer: str) -> bool:
    """review_id 一致メッセージのうち `reviewer`（レビュー実施者）発の完了宣言行のみから判定する。

    明示的な履歴復元では、依頼メッセージ自身が返信形式の説明として
    `REVIEW_RESULT: approved` という部分文字列を含むため、
    単純な部分一致では依頼側（reviewer 以外の送信者）のメッセージも承認済みと
    誤判定してしまう（Codex レビュー review_id=043e2823... で発見）。前後の空白を
    除去した上で行全体が完全一致する行のみを完了宣言行の候補とし、reviewer 発の
    メッセージのみを対象にする。候補が複数あれば sent_at 昇順の中で最後に
    出現したものを採用する（返信の末尾に近いほど最終判断を反映するため）。
    """
    last_line: str | None = None
    for msg in messages:
        if msg.get("sender") != reviewer:
            continue
        for raw_line in msg.get("body", "").splitlines():
            line = raw_line.strip()
            if line in COMPLETION_LINES:
                last_line = line
    return last_line == APPROVED_LINE


def fetch_history(
    agent_a: str,
    agent_b: str,
    db_path: str | None,
    project_root: str | None = None,
) -> list[dict]:
    """history.py を subprocess として呼び、全履歴 JSON を取得する（thread_filter に委譲）。"""
    return thread_filter.fetch_history(agent_a, agent_b, db_path, project_root)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="review_id による msg-sys 往復履歴の絞り込み CLI",
    )
    parser.add_argument("agent_a")
    parser.add_argument("agent_b")
    parser.add_argument("review_id")
    parser.add_argument(
        "--db-path",
        default=None,
        help="messages.db のパス（省略時は history.py 側の導出規則に従う）",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help=(
            "プロジェクトルート（DB パスの導出起点）。"
            "指定すると FORGE_MSG_PROJECT_ROOT の前置が不要になる"
        ),
    )
    args = parser.parse_args()

    try:
        all_messages = fetch_history(
            args.agent_a, args.agent_b, args.db_path, args.project_root
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    filtered = filter_by_review_id(all_messages, args.review_id)

    if not filtered:
        output = {
            "status": "not_found",
            "review_id": args.review_id,
            "reason": f"review_id={args.review_id} に一致する履歴がありません",
        }
    else:
        output = {
            "status": "ok",
            "review_id": args.review_id,
            "messages": filtered,
            "round": compute_round(filtered),
            "resolved": compute_resolved(filtered, args.agent_b),
        }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
