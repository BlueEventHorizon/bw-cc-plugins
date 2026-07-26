#!/usr/bin/env python3
"""msg-sys 実験用: OS 通知ヘルパー（macOS osascript 経由）。

往復上限到達時に、bash hook（hooks/codex-check-inbox.sh /
hooks/claude-check-inbox.sh）から呼び出される。`osascript` はシェル文字列展開・
eval を経由せず `subprocess.run(["osascript", "-e", script], ...)` の引数配列
形式で呼び出し、通知本文はプログラム側で AppleScript 文字列リテラルとして
安全にエスケープしてから埋め込む（DES-034 §8「通知内容の安全な受け渡し」）。

CLI エントリポイント（bash hook から呼べる。終了コードのみで成否を示す。
標準出力への出力は行わない。inbox.py/send.py の出力契約とは無関係）:

    python3 lib/notify.py \\
        --recipient <name> --message-id <id> --sender <sender> \\
        --body <body> --ack-hint "<ack コマンド例文字列>"

終了コード: 0 = 通知成功, 非0 = 通知失敗
"""

import argparse
import subprocess
import sys


def _escape_applescript_string(value: str) -> str:
    """AppleScript の文字列リテラル（`"..."`）内で安全な形にエスケープする。

    バックスラッシュを先にエスケープしないとダブルクォートのエスケープで
    生成した `\\"` が二重にエスケープされてしまうため、この順序を守る。
    """
    escaped = value.replace("\\", "\\\\")
    escaped = escaped.replace('"', '\\"')
    return escaped


def build_notification_script(title: str, message: str) -> str:
    """`display notification` 用の AppleScript 文字列を安全に組み立てる。"""
    safe_message = _escape_applescript_string(message)
    safe_title = _escape_applescript_string(title)
    return f'display notification "{safe_message}" with title "{safe_title}"'


def send_notification(
    recipient: str,
    message_id: str,
    sender: str,
    body: str,
    ack_hint: str,
) -> bool:
    """通知内容を組み立て、osascript を引数配列形式で呼び出す。

    成功時 True、失敗時（osascript の非ゼロ終了・実行不能等）は False を返す。
    呼び出し元（bash hook）に対しては例外を投げず、bool のみで成否を伝える。
    """
    title = f"msg-sys: {recipient} 宛メッセージが往復上限に到達"
    message = (
        f"id={message_id} sender={sender}\n"
        f"body: {body}\n"
        f"手動 ack: {ack_hint}"
    )
    script = build_notification_script(title, message)

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            check=False,
        )
    except OSError:
        return False

    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="msg-sys OS 通知ヘルパー（往復上限到達時の人間通知）",
    )
    parser.add_argument("--recipient", required=True)
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--sender", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--ack-hint", required=True)

    args = parser.parse_args()

    ok = send_notification(
        recipient=args.recipient,
        message_id=args.message_id,
        sender=args.sender,
        body=args.body,
        ack_hint=args.ack_hint,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
