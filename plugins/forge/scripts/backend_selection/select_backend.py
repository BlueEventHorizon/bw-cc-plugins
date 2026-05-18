#!/usr/bin/env python3
"""forge-query バックエンド選択スクリプト。

DES-001 §2.3 の分岐テーブル A/B と §1.5.1 の API キー判定式を Python に集約する。
4 つの抽象 SKILL (/forge:query-db-rules / query-db-specs / update-db-rules /
update-db-specs) は本スクリプトを Bash で呼び、stdout の JSON を解釈して
Skill ツールで該当バックエンドを起動する。

read-only: 環境変数の読取と stdout への JSON 出力のみ。ファイル書込・外部
プロセス起動・git 操作を一切行わない。Python 標準ライブラリのみで動作する。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# DES-001 §5.1 バックエンド不在時のエラーメッセージ全文。
# `error` フィールドは本文字列と完全一致させる契約 (§8.1)。
BACKEND_NOT_FOUND_ERROR = (
    "ERROR: 文書検索バックエンドが見つかりません\n"
    "       doc-db または doc-advisor のいずれかをインストールしてください\n"
    "\n"
    "       /plugin install doc-db@bw-cc-plugins\n"
    "       /plugin install doc-advisor@bw-cc-plugins"
)

# DES-001 §2.3 分岐テーブル B: backend × category × operation → skill 名。
# 値は `Skill` ツールに渡す plugin:skill 形式（スラッシュなし）。SKILL.md 側で
# スラッシュコマンド表記に整える場合は呼び出し側で `/` を付与する。
SKILL_TABLE = {
    ("doc-db", "rules", "query"): "doc-db:query",
    ("doc-db", "specs", "query"): "doc-db:query",
    ("doc-db", "rules", "update"): "doc-db:build-index",
    ("doc-db", "specs", "update"): "doc-db:build-index",
    ("doc-advisor", "rules", "query"): "doc-advisor:query-rules",
    ("doc-advisor", "specs", "query"): "doc-advisor:query-specs",
    ("doc-advisor", "rules", "update"): "doc-advisor:create-rules-toc",
    ("doc-advisor", "specs", "update"): "doc-advisor:create-specs-toc",
}


def parse_available(raw: str) -> set[str]:
    """`--available` の CSV を集合に展開する。空文字列は空集合。"""
    if not raw:
        return set()
    return {token.strip() for token in raw.split(",") if token.strip()}


def has_api_key(env: dict[str, str] | None = None) -> bool:
    """DES-001 §1.5.1 API キー判定式。

    `OPENAI_API_DOCDB_KEY` または `OPENAI_API_KEY` のいずれかが
    **空でない値で設定されている** ことを「API キーあり」と判定する。
    DES-007 のフォールバック順序に従う。
    """
    source = os.environ if env is None else env
    docdb = source.get("OPENAI_API_DOCDB_KEY", "")
    api = source.get("OPENAI_API_KEY", "")
    return bool(docdb) or bool(api)


def select_backend(available: set[str], api_key_present: bool) -> str | None:
    """DES-001 §2.3 分岐テーブル A: 採用バックエンド決定。

    None を返した場合はバックエンド不在 (両方未インストール) を意味する。
    """
    has_doc_db = "doc-db" in available
    has_doc_advisor = "doc-advisor" in available

    if has_doc_db and has_doc_advisor:
        return "doc-db" if api_key_present else "doc-advisor"
    if has_doc_db:
        return "doc-db"
    if has_doc_advisor:
        return "doc-advisor"
    return None


def build_result(
    available: set[str],
    category: str,
    operation: str,
    api_key_present: bool,
) -> dict:
    """分岐テーブル A/B を評価して JSON 出力用 dict を返す。"""
    backend = select_backend(available, api_key_present)
    if backend is None:
        return {"backend": None, "skill": None, "error": BACKEND_NOT_FOUND_ERROR}
    skill = SKILL_TABLE[(backend, category, operation)]
    return {"backend": backend, "skill": skill, "error": None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Select query/update backend for forge abstract skills.",
    )
    parser.add_argument(
        "--available",
        default="",
        help="Comma-separated list of available backend plugin names "
        "(e.g. 'doc-db,doc-advisor').",
    )
    parser.add_argument(
        "--category",
        choices=("rules", "specs"),
        required=True,
    )
    parser.add_argument(
        "--operation",
        choices=("query", "update"),
        required=True,
    )
    args = parser.parse_args(argv)

    available = parse_available(args.available)
    result = build_result(available, args.category, args.operation, has_api_key())
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
