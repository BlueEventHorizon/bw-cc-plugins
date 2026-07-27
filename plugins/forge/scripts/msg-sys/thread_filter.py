#!/usr/bin/env python3
"""msg-sys: プロトコル非依存のスレッド絞り込み共通ロジック（DES-045 §3.6 の汎用化）。

`history.py <agent_a> <agent_b>` が返す全履歴から、特定の「スレッド」に属する
メッセージのみを抽出する。スレッドの起点特定には呼び出し側が渡す正規表現
（body 先頭行から thread_id を1個の capture group で取り出す）を使い、以後は
`in_reply_to`（DB の構造化フィールド）の連鎖を辿って同じスレッドに属するメッセージを
fixed-point まで追加する。

もともと msg-review 専用の `filter_review_history.py`（`[msg-review] ... review_id=...`
ヘッダ・`REVIEW_RESULT` 完了宣言行の判定を含む）に実装されていたロジックのうち、
プロトコルに依存しない部分（履歴取得・スレッド判定）だけをここに切り出した。
review プロトコル固有の completion 判定（`compute_resolved` 等）はここでは扱わない
（`filter_review_history.py` 側に残る）。同じロジックを talk-to-codex 等の別プロトコルの
スキルからも再利用できるようにするための共通化（実 Codex レビューでの
`find_codex_pane.py` 切り出しと同じ動機）。

使い方（他スクリプトからの import 専用。CLI エントリポイントは持たない）:
    import thread_filter
    messages = thread_filter.fetch_history(agent_a, agent_b, db_path, project_root)
    filtered = thread_filter.filter_by_thread(messages, header_regex, thread_id)
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from re import Pattern

HISTORY_SCRIPT = Path(__file__).resolve().parent / "history.py"

PROJECT_ROOT_ENV = "FORGE_MSG_PROJECT_ROOT"


def fetch_history(
    agent_a: str,
    agent_b: str,
    db_path: str | None,
    project_root: str | None = None,
) -> list[dict]:
    """history.py を subprocess として呼び、全履歴 JSON を取得する。

    `history.py` は DB パスを `--db-path` か環境変数 `FORGE_MSG_PROJECT_ROOT` から解決し、
    どちらも無ければ fail closed で終了する（DES-034 §7）。`project_root` を渡すと本関数が
    その環境変数を subprocess へ設定するため、**呼び出し側がシェルで環境変数を前置する
    必要がなくなる**。

    引数で受け取れるようにしたのは、環境変数の前置が呼び出し側の記憶に依存し、実運用で
    繰り返し忘れられたためである（`RuntimeError: DB path could not be resolved` になる）。
    review スキルの他スクリプトはいずれも `--project-root` を持つのに、履歴系だけが
    env 前置を要求していたという不整合が原因だった。
    """
    cmd = [sys.executable, str(HISTORY_SCRIPT), agent_a, agent_b]
    if db_path:
        cmd += ["--db-path", db_path]

    env = None
    if project_root:
        env = {**os.environ, PROJECT_ROOT_ENV: project_root}

    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(
            f"history.py が非ゼロ終了しました (code={result.returncode}): "
            f"{result.stderr.strip()}"
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"history.py の出力が JSON としてパースできません: {exc}") from exc

    if not isinstance(data, list):
        raise RuntimeError("history.py の出力が配列ではありません")

    return data


def parse_thread_id(body: str, header_regex: Pattern[str]) -> str | None:
    """body 先頭行を header_regex に照合し、capture group 1 を thread_id として返す。

    `header_regex` は capture group を1つ以上持つ契約（thread_id を取り出すため）。
    呼び出し元の CLI（wait_for_reply.py）は起動時にこれを検証するが、将来他のスキル
    （talk-to-codex 等）が本関数を CLI を経由せず直接 import して呼ぶ可能性があるため、
    ここでも契約違反を明確なエラーとして検出する（実 Codex レビューで発見: capture
    group の無い正規表現は `match.group(1)` が素の IndexError で落ちてしまう）。
    """
    if header_regex.groups < 1:
        raise ValueError(
            "header_regex には thread_id を取り出す capture group が"
            "少なくとも1つ必要です"
        )
    if not body:
        return None
    first_line = body.splitlines()[0]
    match = header_regex.search(first_line)
    if match is None:
        return None
    return match.group(1)


def filter_by_thread(
    messages: list[dict], header_regex: Pattern[str], thread_id: str
) -> list[dict]:
    """指定した thread_id のスレッドに属するメッセージのみを sent_at 昇順で抽出する。

    判定: (a) body 先頭行のヘッダが thread_id に一致する（root の特定に使う）、
    または (b) `in_reply_to` を辿って (a) または既にスレッドに含まれる別のメッセージへ
    到達できる、のいずれかを満たすメッセージを含める（実 Codex レビューで発見:
    body 先頭行のヘッダのみに頼ると、返信本文からヘッダ行が欠落した場合に静かに
    スレッドから漏れる）。

    history.py の出力は既に sent_at 昇順で返るため、フィルタ後に改めて並べ替える。
    """
    included_ids: set[str] = {
        msg["id"]
        for msg in messages
        if msg.get("id") and parse_thread_id(msg.get("body", ""), header_regex) == thread_id
    }

    # in_reply_to の連鎖（親 -> 子）を辿り、fixed-point に達するまで含めるメッセージを増やす。
    # メッセージ数は小規模（1スレッドの往復履歴）であるため、単純な反復で十分。
    children_by_parent: dict[str, list[str]] = {}
    for msg in messages:
        parent_id = msg.get("in_reply_to")
        msg_id = msg.get("id")
        if parent_id and msg_id:
            children_by_parent.setdefault(parent_id, []).append(msg_id)

    queue = list(included_ids)
    while queue:
        current_id = queue.pop()
        for child_id in children_by_parent.get(current_id, []):
            if child_id not in included_ids:
                included_ids.add(child_id)
                queue.append(child_id)

    result = [msg for msg in messages if msg.get("id") in included_ids]
    result.sort(key=lambda msg: msg["sent_at"])
    return result
