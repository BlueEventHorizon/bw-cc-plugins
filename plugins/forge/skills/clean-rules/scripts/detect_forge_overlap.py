#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
forge docs とプロジェクト rules のセクション単位の重複を検出する。

各ファイルを ## 見出しでセクション分割し、OpenAI Embedding API で
ベクトル化してコサイン類似度を算出する。閾値超えのペアを JSON で出力。

Usage:
    python3 detect_forge_overlap.py \
        --project-rules docs/rules/a.md docs/rules/b.md \
        --forge-docs plugins/forge/docs/x.md plugins/forge/docs/y.md \
        [--threshold 0.5]

標準ライブラリ + embedding_api.py（doc-advisor）のみ使用。
"""

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

# doc-advisor の embedding_api を import
_DOC_ADVISOR_SCRIPTS = str(
    Path(__file__).resolve().parents[4] / "doc-advisor" / "scripts"
)
if _DOC_ADVISOR_SCRIPTS not in sys.path:
    sys.path.insert(0, _DOC_ADVISOR_SCRIPTS)

from embedding_api import EMBEDDING_BATCH_SIZE, call_embedding_api


# ---------------------------------------------------------------------------
# セクション分割
# ---------------------------------------------------------------------------

def split_sections(content, filepath=""):
    """Markdown ファイルを ## 見出しでセクション分割する。

    ## より上位の見出し（#）はファイルタイトルとして扱い、
    最初のセクションの先頭に含める。

    Args:
        content: ファイル内容（文字列）
        filepath: ログ用のファイルパス

    Returns:
        list[dict]: [{"heading": "## 見出し", "text": "本文", "line": 行番号}, ...]
        セクションが見つからない場合はファイル全体を1セクションとして返す。
    """
    lines = content.split("\n")
    sections = []
    current_heading = None
    current_lines = []
    current_line_num = 1

    for i, line in enumerate(lines, start=1):
        if re.match(r"^##\s+", line) and not re.match(r"^###", line):
            if current_heading is not None or current_lines:
                text = "\n".join(current_lines).strip()
                if text:
                    heading = current_heading or f"(file header: {filepath})"
                    sections.append({
                        "heading": heading,
                        "text": text,
                        "line": current_line_num,
                    })
            current_heading = line.strip()
            current_lines = []
            current_line_num = i
        else:
            current_lines.append(line)

    if current_heading is not None or current_lines:
        text = "\n".join(current_lines).strip()
        if text:
            heading = current_heading or f"(file header: {filepath})"
            sections.append({
                "heading": heading,
                "text": text,
                "line": current_line_num,
            })

    if not sections and content.strip():
        sections.append({
            "heading": f"(entire file: {filepath})",
            "text": content.strip(),
            "line": 1,
        })

    return sections


# ---------------------------------------------------------------------------
# コサイン類似度
# ---------------------------------------------------------------------------

def cosine_similarity(vec_a, vec_b):
    """コサイン類似度を計算する。

    Args:
        vec_a: ベクトル A (list[float])
        vec_b: ベクトル B (list[float])

    Returns:
        float: コサイン類似度 (-1.0 ~ 1.0)
    """
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# ファイル読み込み + セクション収集
# ---------------------------------------------------------------------------

def collect_sections(file_paths, label=""):
    """複数ファイルからセクションを収集する。

    Args:
        file_paths: ファイルパスのリスト
        label: ログ用ラベル

    Returns:
        list[dict]: [{"file": path, "heading": ..., "text": ..., "line": ...}, ...]
    """
    all_sections = []
    for fpath in file_paths:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError) as e:
            _log(f"  Warning: {fpath} を読み込めません: {e}")
            continue

        sections = split_sections(content, filepath=fpath)
        for sec in sections:
            all_sections.append({
                "file": str(fpath),
                "heading": sec["heading"],
                "text": sec["text"],
                "line": sec["line"],
            })

    return all_sections


# ---------------------------------------------------------------------------
# Embedding + 類似度計算
# ---------------------------------------------------------------------------

def embed_sections(sections, api_key):
    """セクションリストを Embedding ベクトル化する。

    Args:
        sections: collect_sections() の戻り値
        api_key: OpenAI API キー

    Returns:
        list[list[float]]: 各セクションの Embedding ベクトル
    """
    texts = [s["text"][:8000] for s in sections]

    all_embeddings = []
    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[i:i + EMBEDDING_BATCH_SIZE]
        embeddings = call_embedding_api(batch, api_key)
        all_embeddings.extend(embeddings)

    return all_embeddings


def find_overlaps(project_sections, project_embeddings,
                  forge_sections, forge_embeddings,
                  threshold):
    """プロジェクト sections と forge sections のコサイン類似度を総当たりで算出し、
    閾値超えのペアを返す。

    Returns:
        list[dict]: 重複候補のリスト（similarity 降順）
    """
    overlaps = []

    for i, p_sec in enumerate(project_sections):
        best_score = 0.0
        best_match = None

        for j, f_sec in enumerate(forge_sections):
            score = cosine_similarity(project_embeddings[i], forge_embeddings[j])
            if score > best_score:
                best_score = score
                best_match = {
                    "project_file": p_sec["file"],
                    "project_section": p_sec["heading"],
                    "project_line": p_sec["line"],
                    "forge_file": f_sec["file"],
                    "forge_section": f_sec["heading"],
                    "similarity": round(score, 6),
                }

        if best_match and best_score >= threshold:
            overlaps.append(best_match)

    overlaps.sort(key=lambda x: x["similarity"], reverse=True)
    return overlaps


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _log(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    print(*args, **kwargs)


def parse_args():
    parser = argparse.ArgumentParser(
        description="forge docs とプロジェクト rules のセクション重複を Embedding で検出する"
    )
    parser.add_argument(
        "--project-rules",
        nargs="+",
        required=True,
        help="プロジェクト rules のファイルパス",
    )
    parser.add_argument(
        "--forge-docs",
        nargs="+",
        required=True,
        help="forge docs のファイルパス",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="類似度閾値（デフォルト: 0.5）",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print(json.dumps({
            "status": "error",
            "error": "OPENAI_API_KEY not set. Set it with: export OPENAI_API_KEY=sk-...",
        }))
        sys.exit(1)

    _log("Phase 1: セクション分割...")
    project_sections = collect_sections(args.project_rules, label="project")
    forge_sections = collect_sections(args.forge_docs, label="forge")

    if not project_sections:
        print(json.dumps({
            "status": "ok",
            "overlaps": [],
            "message": "プロジェクト rules にセクションが見つかりません",
        }, ensure_ascii=False))
        return 0

    if not forge_sections:
        print(json.dumps({
            "status": "ok",
            "overlaps": [],
            "message": "forge docs にセクションが見つかりません",
        }, ensure_ascii=False))
        return 0

    _log(f"  プロジェクト: {len(project_sections)} セクション")
    _log(f"  forge:       {len(forge_sections)} セクション")

    _log("Phase 2: Embedding 生成...")
    try:
        project_embeddings = embed_sections(project_sections, api_key)
        forge_embeddings = embed_sections(forge_sections, api_key)
    except RuntimeError as e:
        print(json.dumps({
            "status": "error",
            "error": f"Embedding API エラー: {e}",
        }, ensure_ascii=False))
        sys.exit(1)

    _log("Phase 3: 類似度算出...")
    overlaps = find_overlaps(
        project_sections, project_embeddings,
        forge_sections, forge_embeddings,
        threshold=args.threshold,
    )

    _log(f"  重複候補: {len(overlaps)} 件（閾値 {args.threshold}）")

    print(json.dumps({
        "status": "ok",
        "threshold": args.threshold,
        "project_section_count": len(project_sections),
        "forge_section_count": len(forge_sections),
        "overlaps": overlaps,
    }, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
