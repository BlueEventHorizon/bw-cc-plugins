#!/usr/bin/env python3
"""msg-sys 実験用 CLI: 2エージェント間の全メッセージ履歴取得（監査用）。

使い方:
    python3 history.py <agent_a> <agent_b> [--db-path <path>]

既読状態は変更しない。--db-path 未指定時は環境変数 FORGE_MSG_PROJECT_ROOT から
自動導出する。どちらも無い場合はエラー終了する（fail closed、DES-034 §7）。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import mailbox  # noqa: E402

USAGE = "usage: history.py <agent_a> <agent_b> [--db-path <path>]"


def main() -> int:
    args = sys.argv[1:]
    positional = []
    db_path_arg = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--db-path":
            if i + 1 >= len(args):
                print(USAGE, file=sys.stderr)
                return 1
            db_path_arg = args[i + 1]
            i += 2
            continue
        positional.append(arg)
        i += 1

    if len(positional) != 2:
        print(USAGE, file=sys.stderr)
        return 1

    agent_a, agent_b = positional

    db_path = mailbox.resolve_db_path(db_path_arg)
    messages = mailbox.history(agent_a, agent_b, db_path=db_path)
    print(json.dumps(messages, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
