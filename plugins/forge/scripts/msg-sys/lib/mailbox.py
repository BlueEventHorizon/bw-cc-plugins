"""msg-sys 実験用の最小 mailbox 実装。

標準ライブラリのみ（sqlite3）。WAL モード + busy_timeout でロック代わりにする。
メッセージは追記専用（削除しない）。既読は read_at カラムで管理する。
"""

import os
import sqlite3
import time
import uuid
from pathlib import Path


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            body TEXT NOT NULL,
            sent_at REAL NOT NULL,
            read_at REAL,
            in_reply_to TEXT REFERENCES messages (id),
            limit_notified_at REAL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_recipient_unread "
        "ON messages (recipient, read_at)"
    )
    return conn


def resolve_db_path(explicit: str | None) -> Path:
    """DB パスを fail-closed な優先順位で解決する。

    (1) explicit が指定されていればそれを使う
    (2) 無ければ環境変数 FORGE_MSG_PROJECT_ROOT から
        ${FORGE_MSG_PROJECT_ROOT}/.claude/.temp/msg-sys/messages.db を導出する
    (3) どちらも無ければ例外を送出する（プロジェクト間共有の既定パスへのフォールバックはしない）
    """
    if explicit:
        return Path(explicit)

    project_root = os.environ.get("FORGE_MSG_PROJECT_ROOT")
    if project_root:
        return Path(project_root) / ".claude" / ".temp" / "msg-sys" / "messages.db"

    raise RuntimeError(
        "DB path could not be resolved: neither --db-path nor "
        "FORGE_MSG_PROJECT_ROOT is set (fail closed, DES-034 §7)"
    )


def send(
    sender: str,
    recipient: str,
    body: str,
    *,
    db_path: Path,
    in_reply_to: str | None = None,
) -> str:
    """メッセージを1件送信し、message id を返す。

    in_reply_to を指定すると、当該メッセージへの返信として自己参照する
    （人間が送る新規メッセージは in_reply_to を付けない。DES-034 §3.2）。
    """
    message_id = str(uuid.uuid4())
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO messages (id, sender, recipient, body, sent_at, read_at, in_reply_to) "
            "VALUES (?, ?, ?, ?, ?, NULL, ?)",
            (message_id, sender, recipient, body, time.time(), in_reply_to),
        )
        conn.commit()
    finally:
        conn.close()
    return message_id


def inbox(recipient: str, *, db_path: Path) -> list[dict]:
    """recipient 宛の未読メッセージを取得する（既読化しない、取得と既読化は分離する。

    既読化は ack() の責務であり、inbox() 自体に既読化オプションは持たせない
    （INT-001/INT-004、DES-034 §4.2「配信単位は常に1メッセージ」）。
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, sender, recipient, body, sent_at FROM messages "
            "WHERE recipient = ? AND read_at IS NULL ORDER BY sent_at ASC",
            (recipient,),
        ).fetchall()
        return [
            {"id": r[0], "sender": r[1], "recipient": r[2], "body": r[3], "sent_at": r[4]}
            for r in rows
        ]
    finally:
        conn.close()


def history(agent_a: str, agent_b: str, *, db_path: Path) -> list[dict]:
    """agent_a と agent_b 間の全メッセージ履歴を送信順で返す（監査用、既読状態は変更しない）。

    `in_reply_to` を含む（review の filter_review_history.py が review_id ヘッダの
    自由記述への依存を減らし、この構造化フィールドで返信連鎖を辿れるようにするため。
    実 Codex レビューで発見: ヘッダ行が返信本文から欠落すると review_id ベースの
    追跡が静かに失敗する不具合があった）。
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, sender, recipient, body, sent_at, read_at, in_reply_to FROM messages "
            "WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?) "
            "ORDER BY sent_at ASC",
            (agent_a, agent_b, agent_b, agent_a),
        ).fetchall()
        return [
            {
                "id": r[0],
                "sender": r[1],
                "recipient": r[2],
                "body": r[3],
                "sent_at": r[4],
                "read_at": r[5],
                "in_reply_to": r[6],
            }
            for r in rows
        ]
    finally:
        conn.close()


def reply_chain_length(message_id: str, db_path: Path) -> int:
    """message_id から in_reply_to を遡って連続する返信件数を返す。

    message_id 自身が返信（in_reply_to が設定されている）でなければ 0 を返す。
    チェーンを遡る途中で in_reply_to が NULL のメッセージ（人間が送った新規メッセージ）
    に到達したら、そこで数えるのを止める（そのメッセージ自体はカウントしない）。
    存在しない message_id や欠落した参照に到達した場合もそこで打ち切る。
    """
    conn = _connect(db_path)
    try:
        count = 0
        current_id: str | None = message_id
        while current_id is not None:
            row = conn.execute(
                "SELECT in_reply_to FROM messages WHERE id = ?",
                (current_id,),
            ).fetchone()
            if row is None:
                break
            parent_id = row[0]
            if parent_id is None:
                break
            count += 1
            current_id = parent_id
        return count
    finally:
        conn.close()


def ack(message_id: str, db_path: Path) -> bool:
    """指定した単一 message_id のみを既読化する（inbox() の全件既読化とは別関数、DES-034 §4.2）。

    `WHERE read_at IS NULL` の条件付き UPDATE が実際に1行を更新できた場合のみ
    True を返す。既に他プロセスが先に既読化していた場合（同一未読メッセージへの
    並行アクセス時のレース）は False を返す。呼び出し側はこの戻り値を「自分が
    このメッセージの配信権を得たか」の判定に使うこと（True の場合のみ配信して
    よい）。rowcount を検証せず常に成功扱いにすると、複数プロセスが同一メッセージを
    二重配信し得る。
    """
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            "UPDATE messages SET read_at = ? WHERE id = ? AND read_at IS NULL",
            (time.time(), message_id),
        )
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()


def mark_limit_notified(message_id: str, db_path: Path) -> None:
    """指定した message_id の limit_notified_at に現在時刻を設定する（read_at は変更しない、DES-034 §8）。"""
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE messages SET limit_notified_at = ? WHERE id = ?",
            (time.time(), message_id),
        )
        conn.commit()
    finally:
        conn.close()


def select_next_actionable(recipient: str, db_path: Path) -> dict | None:
    """recipient 宛の未読のうち、往復上限で保留中でない最古の1件を選ぶ。

    limit_notified_at IS NULL（＝まだ往復上限に到達していない）の未読のうち sent_at が
    最小の1件を選び、reply_chain_length を算出して返す。該当なしは None を返す。
    選定・往復回数判定ロジックはこの関数に閉じ込め、呼び出し側（CLI・hook）に判断を漏らさない。
    """
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, sender, body FROM messages "
            "WHERE recipient = ? AND read_at IS NULL AND limit_notified_at IS NULL "
            "ORDER BY sent_at ASC LIMIT 1",
            (recipient,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    message_id, sender, body = row
    chain_length = reply_chain_length(message_id, db_path=db_path)
    return {"id": message_id, "sender": sender, "body": body, "chain_length": chain_length}
