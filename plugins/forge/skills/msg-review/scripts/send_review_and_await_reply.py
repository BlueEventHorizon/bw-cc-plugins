#!/usr/bin/env python3
"""msg-review のワイヤ本文構築と共通送信処理への委譲を 1 回に畳む。"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wire_body

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_COMMON_SEND = _PLUGIN_ROOT / "scripts" / "msg-sys" / "send_and_await_reply.py"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="msg-review のヘッダ付加・送信・起床・応答待機",
    )
    parser.add_argument("sender")
    parser.add_argument("recipient")
    parser.add_argument("--review-type", required=True)
    parser.add_argument("--review-id", required=True)
    parser.add_argument("--round", required=True, type=int, dest="round_no")
    parser.add_argument("--body-file", required=True)
    parser.add_argument("--header-regex", required=True)
    parser.add_argument("--in-reply-to")
    parser.add_argument("--project-root")
    parser.add_argument("--db-path")
    parser.add_argument("--max-seconds", type=float)
    parser.add_argument("--progress-interval", type=float)
    parser.add_argument("--initial-interval", type=float)
    parser.add_argument("--backoff-factor", type=float)
    parser.add_argument("--max-interval", type=float)
    parser.add_argument("--no-wake", action="store_true")
    return parser.parse_args(argv)


def _delegate_command(args, wire_path: Path) -> list[str]:
    """共通 CLI へ安全に委譲する argv 配列を構築する。"""
    command = [
        sys.executable,
        str(_COMMON_SEND),
        args.sender,
        args.recipient,
        "--body-file",
        str(wire_path),
        "--header-regex",
        args.header_regex,
        "--thread-id",
        args.review_id,
    ]
    for flag, value in (
        ("--in-reply-to", args.in_reply_to),
        ("--project-root", args.project_root),
        ("--db-path", args.db_path),
        ("--max-seconds", args.max_seconds),
        ("--progress-interval", args.progress_interval),
        ("--initial-interval", args.initial_interval),
        ("--backoff-factor", args.backoff_factor),
        ("--max-interval", args.max_interval),
    ):
        if value is not None:
            command.extend((flag, str(value)))
    if args.no_wake:
        command.append("--no-wake")
    return command


def run(args, *, runner=subprocess.run) -> int:
    """wire 本文を一時生成し、共通 CLI の終了コードをそのまま返す。"""
    common_body = Path(args.body_file).read_text(encoding="utf-8")
    wire_text = wire_body.add_header(
        common_body,
        args.review_type,
        args.review_id,
        args.round_no,
    )

    wire_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="msg-review-wire-",
            suffix=".txt",
            delete=False,
        ) as handle:
            handle.write(wire_text)
            wire_path = Path(handle.name)
        completed = runner(_delegate_command(args, wire_path))
        return completed.returncode
    finally:
        if wire_path is not None:
            wire_path.unlink(missing_ok=True)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
