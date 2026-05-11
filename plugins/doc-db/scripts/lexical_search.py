#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lexical 検索（語彙一致 + ID 完全一致ブースト）。"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Tuple

ID_RE = re.compile(r"[A-Z]+-\d+")
# [^\W\d_A-Za-z]+ : CJK 等の非 ASCII・非数字 Unicode 単語文字
# \d+             : 数字（CJK との境界で分割するため独立させる）
# [A-Za-z0-9_]+  : ASCII 英数字・アンダースコア
# [A-Za-z]+-\d+  : 英数字 ID (例: FNC-001)
TOKEN_RE = re.compile(r"[A-Za-z]+-\d+|[A-Za-z0-9_]+|[^\W\d_A-Za-z]+|\d+", re.UNICODE)

# 英語フレーズ → カタカナ / カタカナ → 英語フレーズ の同義語辞書（小文字キー）
# body.count() で部分文字列マッチするため、フレーズ単位で定義する
PHRASE_SYNONYMS: List[Tuple[str, str]] = [
    ("golden set", "ゴールデンセット"),
    ("golden dataset", "ゴールデンデータセット"),
    ("embedding", "エンベディング"),
    ("lexical search", "語彙検索"),
    ("hybrid search", "ハイブリッド検索"),
    ("rerank", "リランク"),
    ("chunk", "チャンク"),
    ("pipeline", "パイプライン"),
    ("migration", "マイグレーション"),
    ("workflow", "ワークフロー"),
    ("orchestrator", "オーケストレータ"),
    ("skill", "スキル"),
    ("plugin", "プラグイン"),
]


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def tokenize(text: str) -> List[str]:
    return [t for t in TOKEN_RE.findall(normalize_text(text)) if t]


def score_chunks(query: str, chunks: List[Dict]) -> List[Dict]:
    query_norm = normalize_text(query)
    query_tokens = tokenize(query_norm)
    id_tokens = [t.lower() for t in ID_RE.findall(unicodedata.normalize("NFKC", query).upper())]

    # クエリに含まれるフレーズの同義語を収集
    synonym_expansions: List[str] = []
    for en_phrase, ja_phrase in PHRASE_SYNONYMS:
        en_norm = normalize_text(en_phrase)
        ja_norm = normalize_text(ja_phrase)
        if en_norm in query_norm and ja_norm not in query_norm:
            synonym_expansions.append(ja_norm)
        elif ja_norm in query_norm and en_norm not in query_norm:
            synonym_expansions.append(en_norm)

    results: List[Dict] = []

    for chunk in chunks:
        body = normalize_text(chunk.get("body", ""))
        score = 0.0

        for token in query_tokens:
            if not token:
                continue
            score += body.count(token)

        for id_token in id_tokens:
            if id_token in body:
                score += 10.0

        if query_norm.strip() and query_norm in body:
            score += 2.0

        for synonym in synonym_expansions:
            score += body.count(synonym)

        if score > 0:
            results.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "path": chunk.get("path", ""),
                    "heading_path": chunk.get("heading_path", []),
                    "lex_score": float(score),
                    "body": chunk.get("body", ""),
                }
            )

    results.sort(key=lambda x: (-x["lex_score"], x["chunk_id"]))
    return results
