#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge 内蔵 docs のメタデータ一覧を JSON で出力する。

docs ディレクトリ内の Markdown ファイルから、タイトル・トピック・
内容種別（content_type）・内部フラグを抽出する。
分類判定は行わない。AI が taxonomy.md に従って判定する。

Usage:
    python3 list_forge_docs.py <docs_dir>
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# forge 内部仕様（ターゲットプロジェクトの rules と比較する意味がないもの）
INTERNAL_DOCS = {
    'session_format.md',
    'doc_structure_format.md',
    'context_gathering_spec.md',
    'task_execution_spec.md',
}

# ファイル名サフィックスから content_type を推定するマッピング
SUFFIX_TO_CONTENT_TYPE = {
    '_format.md': 'format',
    '_principles_spec.md': 'constraint',
    '_criteria_spec.md': 'constraint',
    '_spec.md': 'reference',
}


def extract_metadata(filepath):
    """Markdown ファイルからメタデータを抽出する。

    Args:
        filepath: ファイルの絶対パス

    Returns:
        dict: title, topics, content_type を含む辞書
    """
    try:
        content = Path(filepath).read_text(encoding='utf-8')
    except (IOError, OSError):
        return None

    title = ''
    topics = []

    for line in content.split('\n'):
        stripped = line.strip()
        # 最初の # 行をタイトルとして取得
        if not title and stripped.startswith('# ') and not stripped.startswith('## '):
            title = stripped[2:].strip()
        # ## 行をトピックとして収集
        elif stripped.startswith('## ') and not stripped.startswith('### '):
            topic = stripped[3:].strip()
            # [MANDATORY] 等のタグを除去
            topic = re.sub(r'\s*\[.*?\]\s*$', '', topic)
            if topic:
                topics.append(topic)

    # ファイル名から content_type を推定
    filename = os.path.basename(filepath)
    content_type = 'unknown'
    for suffix, ctype in SUFFIX_TO_CONTENT_TYPE.items():
        if filename.endswith(suffix):
            content_type = ctype
            break

    return {
        'title': title,
        'topics': topics,
        'content_type': content_type,
    }


def list_forge_docs(docs_dir):
    """forge docs ディレクトリをスキャンし、メタデータ一覧を返す。

    Args:
        docs_dir: forge の docs ディレクトリパス

    Returns:
        dict: status と docs リストを含む辞書
    """
    docs_path = Path(docs_dir)
    if not docs_path.is_dir():
        return {
            'status': 'error',
            'error': f'ディレクトリが存在しません: {docs_dir}',
        }

    docs = []
    for md_file in sorted(docs_path.glob('*.md')):
        if not md_file.is_file():
            continue

        metadata = extract_metadata(str(md_file))
        if metadata is None:
            continue

        filename = md_file.name
        docs.append({
            'path': filename,
            'full_path': str(md_file),
            'title': metadata['title'],
            'topics': metadata['topics'],
            'content_type': metadata['content_type'],
            'internal': filename in INTERNAL_DOCS,
        })

    return {
        'status': 'ok',
        'docs': docs,
    }


def main():
    parser = argparse.ArgumentParser(
        description='forge 内蔵 docs のメタデータ一覧を JSON で出力する'
    )
    parser.add_argument('docs_dir', help='forge の docs ディレクトリパス')
    args = parser.parse_args()

    result = list_forge_docs(args.docs_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result.get('status') == 'error':
        sys.exit(1)


if __name__ == '__main__':
    main()
