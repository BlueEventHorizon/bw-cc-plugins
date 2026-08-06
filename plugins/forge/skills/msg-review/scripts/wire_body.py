#!/usr/bin/env python3
"""msg-review 固有のワイヤヘッダを依頼本文へ付加、または応答本文から除去する。"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

HEADER_RE = re.compile(
    r"^\[msg-review\]\s+(?P<pattern>\S+)\s+"
    r"review_id=(?P<review_id>\S+)\s+round=(?P<round>\d+)\s*$"
)


def _validate_header_values(pattern: str, review_id: str, round_no: int) -> None:
    for label, value in (("pattern", pattern), ("review_id", review_id)):
        if not value or "\n" in value or "\r" in value or any(ch.isspace() for ch in value):
            raise ValueError(f"{label} は空白・改行を含まない値である必要があります")
    if round_no < 1:
        raise ValueError("round は 1 以上である必要があります")


def add_header(body: str, pattern: str, review_id: str, round_no: int) -> str:
    """純粋な共通本文の先頭へ msg-review ワイヤヘッダを 1 行付加する。"""
    _validate_header_values(pattern, review_id, round_no)
    if any(HEADER_RE.fullmatch(line.strip()) for line in body.splitlines()):
        raise ValueError("依頼本文に msg-review ヘッダが既に含まれています")
    header = f"[msg-review] {pattern} review_id={review_id} round={round_no}"
    return f"{header}\n{body}"


def strip_header(
    body: str,
    pattern: str,
    review_id: str,
    round_no: int,
) -> str:
    """先頭に期待値と一致する msg-review ワイヤヘッダがあれば除去する。

    返信は `in_reply_to` で依頼スレッドへ結び付くため、ヘッダを繰り返す義務を
    持たない。レビュアーが依頼ヘッダを応答へ再掲した場合だけ共通本文から除く。
    """
    _validate_header_values(pattern, review_id, round_no)
    first, separator, rest = body.partition("\n")
    stripped = first.strip()
    match = HEADER_RE.fullmatch(stripped)
    if match is not None:
        actual = (
            match.group("pattern"),
            match.group("review_id"),
            int(match.group("round")),
        )
        expected = (pattern, review_id, round_no)
        if actual != expected:
            raise ValueError(
                "応答本文先頭の msg-review ヘッダが現在のラウンドと一致しません"
            )
        return rest if separator else ""
    if stripped.startswith("[msg-review]"):
        raise ValueError("応答本文先頭の msg-review ヘッダが不正です")
    return body


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="msg-review ワイヤ本文の構築・分離")
    parser.add_argument("--mode", required=True, choices=("add", "strip"))
    parser.add_argument("--body-file", required=True)
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--pattern")
    parser.add_argument("--review-id")
    parser.add_argument("--round", type=int, dest="round_no")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    body = Path(args.body_file).read_text(encoding="utf-8")
    try:
        if args.mode == "add":
            if args.pattern is None or args.review_id is None or args.round_no is None:
                raise ValueError("add には pattern、review-id、round が必要です")
            result = add_header(body, args.pattern, args.review_id, args.round_no)
        else:
            if args.pattern is None or args.review_id is None or args.round_no is None:
                raise ValueError("strip には pattern、review-id、round が必要です")
            result = strip_header(body, args.pattern, args.review_id, args.round_no)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    Path(args.output_file).write_text(result, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
