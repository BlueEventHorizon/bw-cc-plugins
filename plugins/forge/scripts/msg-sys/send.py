#!/usr/bin/env python3
"""msg-sys 実験用 CLI: メッセージ送信。

使い方:
    python3 send.py <sender> <recipient> <body> [--in-reply-to <id>] [--db-path <path>]
    echo "本文" | python3 send.py <sender> <recipient> - [--in-reply-to <id>] [--db-path <path>]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import mailbox  # noqa: E402

USAGE = (
    "usage: send.py <sender> <recipient> <body|-> "
    "[--in-reply-to <id>] [--db-path <path>]"
)


def main() -> int:
    args = sys.argv[1:]
    positional = []
    in_reply_to = None
    db_path_arg = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--in-reply-to":
            if i + 1 >= len(args):
                print(USAGE, file=sys.stderr)
                return 1
            in_reply_to = args[i + 1]
            i += 2
            continue
        if arg == "--db-path":
            if i + 1 >= len(args):
                print(USAGE, file=sys.stderr)
                return 1
            db_path_arg = args[i + 1]
            i += 2
            continue
        positional.append(arg)
        i += 1

    if len(positional) != 3:
        print(USAGE, file=sys.stderr)
        return 1

    sender, recipient, body = positional
    if body == "-":
        body = sys.stdin.read()

    db_path = mailbox.resolve_db_path(db_path_arg)
    message_id = mailbox.send(sender, recipient, body, in_reply_to=in_reply_to, db_path=db_path)
    print(message_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
