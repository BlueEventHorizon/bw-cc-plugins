#!/usr/bin/env python3
"""msg-sys 実験用 CLI: 未読メッセージ取得（既読化しない、取得と既読化は分離する）。

使い方:
    python3 inbox.py <recipient>
    python3 inbox.py <recipient> --ack <id>                # 指定した単一メッセージのみ既読化（標準出力なし）
    python3 inbox.py <recipient> --mark-notified <id>       # 往復上限到達を記録する
    python3 inbox.py <recipient> --next                     # 処理対象1件を選定して返す（既読化しない）
    python3 inbox.py <recipient> ... --db-path <path>       # DB パスを明示指定

--db-path 未指定時は環境変数 FORGE_MSG_PROJECT_ROOT から自動導出する。
どちらも無い場合はエラー終了する（fail closed、DES-034 §7）。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import mailbox  # noqa: E402

USAGE = (
    "usage: inbox.py <recipient> [--ack <id>] "
    "[--mark-notified <id>] [--next] [--db-path <path>]"
)


def _extract_option_value(args: list[str], flag: str) -> str | None:
    """args から `flag <value>` の value を取り出す。未指定なら None。"""
    if flag not in args:
        return None
    index = args.index(flag)
    return args[index + 1]


def _valid_options(args: list[str]) -> bool:
    value_flags = {"--ack", "--mark-notified", "--db-path"}
    standalone_flags = {"--next"}
    operation_flags = {"--ack", "--mark-notified", "--next"}
    seen: set[str] = set()
    index = 0
    while index < len(args):
        flag = args[index]
        if flag in seen:
            return False
        seen.add(flag)
        if flag in standalone_flags:
            index += 1
            continue
        if flag not in value_flags or index + 1 >= len(args):
            return False
        value = args[index + 1]
        if not value or value.startswith("--"):
            return False
        index += 2
    return len(seen & operation_flags) <= 1


def main() -> int:
    if len(sys.argv) < 2:
        print(USAGE, file=sys.stderr)
        return 1

    recipient = sys.argv[1]
    options = sys.argv[2:]

    if not _valid_options(options):
        print(USAGE, file=sys.stderr)
        return 1

    explicit_db_path = _extract_option_value(options, "--db-path")
    db_path = mailbox.resolve_db_path(explicit_db_path)

    ack_id = _extract_option_value(options, "--ack")
    if ack_id is not None:
        # ack() が False を返すのは、他プロセスが同一メッセージを先に既読化した
        # 場合（並行 Stop hook 実行時のレース）。呼び出し側（check_inbox.py）は
        # 非ゼロ終了を「配信権を得られなかった」と解釈し、continue:true にフォール
        # バックする（二重配信防止）。
        acked = mailbox.ack(ack_id, db_path)
        return 0 if acked else 1

    mark_notified_id = _extract_option_value(options, "--mark-notified")
    if mark_notified_id is not None:
        mailbox.mark_limit_notified(mark_notified_id, db_path)
        return 0

    if "--next" in options:
        result = mailbox.select_next_actionable(recipient, db_path)
        print(json.dumps(result, ensure_ascii=False))
        return 0

    messages = mailbox.inbox(recipient, db_path=db_path)
    print(json.dumps(messages, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
