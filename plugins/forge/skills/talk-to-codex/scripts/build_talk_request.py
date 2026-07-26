#!/usr/bin/env python3
"""talk-to-codex: 自由会話メッセージ組み立てスクリプト。

review の `build_review_request.py` 相当だが、レビューの4セクション構成・
所見重大度マーカー・`REVIEW_RESULT` 完了宣言行の契約を一切持たない。ヘッダ行
`[msg-talk] topic_id=<topic_id>` に続けて、利用者が渡した自由記述メッセージを
そのまま本文とする最小フォーマット（msg-sys の `thread_filter.py` がこのヘッダ
行から topic_id を抽出してスレッドを識別する）。

topic_id はスレッド識別用の不透明トークン。新規の会話では省略して uuid4 で
新規生成し、既存の会話を継続する場合は呼び出し側（SKILL.md）が保持している
既存の topic_id を `--topic-id` でそのまま渡す。

使い方:
    python3 build_talk_request.py --message "<自由記述本文>" [--topic-id <既存id>]

Output:
    標準出力に依頼本文（テキスト）を書く。1行目がプロトコルヘッダ。
"""

import argparse
import re
import sys
import uuid

TOPIC_ID_HEADER_RE_TEMPLATE = r"^\[msg-talk\]\s+topic_id=(\S+)\s*$"

# thread_filter.py 側のヘッダ正規表現は topic_id を `(\S+)` で1トークンとして
# 抽出する契約のため、topic_id 自体も空白（スペース・タブ）を一切含まない単一
# トークンでなければならない（実 Codex レビューで発見: 改行のみ拒否していたが、
# 空白を含む topic_id は `topic_id=(\S+)` にマッチする範囲が先頭空白手前までに
# 切り詰められ、継続会話のスレッド判定が静かに失敗する）。
_VALID_TOPIC_ID_RE = re.compile(r"^\S+$")


def _validate_topic_id(topic_id: str) -> None:
    """topic_id が `\\S+` に一致する単一トークンであることを検証する。

    空文字列・空白のみ・空白を含む値・改行を含む値のいずれも拒否する
    （`^\\S+$` は改行を含む文字列にもマッチしないため、この1つの検証で
    従来の改行拒否を包含する）。
    """
    if not _VALID_TOPIC_ID_RE.match(topic_id):
        raise ValueError(
            f"topic_id は空白・改行を含まない単一トークンである必要があります: {topic_id!r}"
        )


def build_body(message: str, topic_id: str) -> str:
    """依頼本文を組み立てて返す。

    ヘッダ行（`[msg-talk] topic_id=<topic_id>`）+ 空行 + 自由記述メッセージ本文。
    """
    _validate_topic_id(topic_id)
    return f"[msg-talk] topic_id={topic_id}\n\n{message}\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="talk-to-codex 依頼メッセージ本文の組み立て",
    )
    parser.add_argument("--message", required=True, help="Codex へ送る自由記述メッセージ")
    parser.add_argument(
        "--topic-id",
        default=None,
        help="既存スレッドを継続する場合の topic_id（省略時は新規に uuid4 で生成）",
    )
    args = parser.parse_args()

    if not args.message.strip():
        print("--message が空です", file=sys.stderr)
        return 1

    topic_id = args.topic_id or uuid.uuid4().hex

    try:
        body = build_body(args.message, topic_id)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
