#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""コードインデックス検索 CLI。

2つのモードを提供する:
  --query: キーワード検索（Stage 1 — 機械的絞り込み）
  --affected-by: import グラフによる影響範囲検索

設計根拠: DES-007 §5.1-5.3
"""

import argparse
import json
import os
import sys

# 同一パッケージからの import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from code_index.core import load_index
from code_index.graph import ImportGraph
from toc_utils import validate_path_within_base

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

# インデックスファイルの相対パス（プロジェクトルートからの位置）
INDEX_REL_PATH = os.path.join('.claude', 'doc-advisor', 'code_index', 'code_index.json')

# 検索結果の上限件数（DES-007 §5.1）
MAX_RESULTS = 100

# 出力サイズ上限（バイト）— Stage 2 に渡すメタデータ量の制約（DES-007 §5.1, FR-06-4）
MAX_OUTPUT_BYTES = 30 * 1024  # 30KB

# スコアリング重み（タスク指示準拠）
WEIGHT_PATH = 1
WEIGHT_EXPORT = 3
WEIGHT_DOC = 1
WEIGHT_IMPORT = 2


# ---------------------------------------------------------------------------
# キーワード検索（DES-007 §5.1）
# ---------------------------------------------------------------------------

def score_entry(rel_path, entry, keywords):
    """エントリに対してキーワードマッチングを行いスコアを算出する。

    Args:
        rel_path: ファイルの相対パス
        entry: インデックスエントリ dict
        keywords: 検索キーワードのリスト（小文字化済み）

    Returns:
        tuple[int, list[str]]: (スコア, マッチしたキーワードリスト)
    """
    score = 0
    matched = set()
    path_lower = rel_path.lower()
    imports = entry.get('imports', [])
    exports = entry.get('exports', [])

    for kw in keywords:
        kw_matched = False

        # パス名マッチ（部分一致、大文字小文字無視）
        if kw in path_lower:
            score += WEIGHT_PATH
            kw_matched = True

        # export 名マッチ（部分一致、大文字小文字無視）
        for exp in exports:
            name = exp.get('name', '')
            if kw in name.lower():
                score += WEIGHT_EXPORT
                kw_matched = True
                break  # 1キーワードにつき1回のみ加算

        # doc マッチ（部分一致、大文字小文字無視）
        for exp in exports:
            doc = exp.get('doc') or ''
            if kw in doc.lower():
                score += WEIGHT_DOC
                kw_matched = True
                break  # 1キーワードにつき1回のみ加算

        # import 名マッチ（完全一致、大文字小文字無視）DES-007 §5.1 準拠
        for imp in imports:
            if kw == imp.lower():
                score += WEIGHT_IMPORT
                kw_matched = True
                break  # 1キーワードにつき1回のみ加算

        if kw_matched:
            matched.add(kw)

    return score, sorted(matched)


def search_query(index_data, query_string):
    """キーワード検索を実行する。

    Args:
        index_data: load_index() で読み込んだインデックスデータ
        query_string: 検索クエリ文字列

    Returns:
        dict: JSON 出力用の結果辞書
    """
    keywords = [kw.lower() for kw in query_string.split() if kw.strip()]
    if not keywords:
        return {'status': 'error', 'message': 'クエリが空です'}

    entries = index_data.get('entries', {})
    scored_results = []

    for rel_path, entry in entries.items():
        score, matched_keywords = score_entry(rel_path, entry, keywords)
        if score > 0:
            result = {
                'path': rel_path,
                'language': entry.get('language', 'unknown'),
                'lines': entry.get('lines', 0),
                'score': score,
                'matched_keywords': matched_keywords,
                'exports': entry.get('exports', []),
            }
            scored_results.append(result)

    # スコア降順でソート（同スコアの場合はパス名昇順で安定化）
    scored_results.sort(key=lambda r: (-r['score'], r['path']))

    # 上限件数で切り詰め
    truncated = len(scored_results) > MAX_RESULTS
    scored_results = scored_results[:MAX_RESULTS]

    # 30KB 出力制限: JSON サイズを確認し、超過する場合は件数を削減
    scored_results, truncated = _enforce_size_limit(scored_results, truncated)

    return {
        'status': 'ok',
        'results': scored_results,
        'count': len(scored_results),
        'truncated': truncated,
    }


def _enforce_size_limit(results, already_truncated):
    """JSON 出力が MAX_OUTPUT_BYTES を超えないよう件数を削減する。

    Args:
        results: 結果リスト
        already_truncated: 既に件数上限で切り詰められたか

    Returns:
        tuple[list, bool]: (調整後の結果リスト, truncated フラグ)
    """
    output = {
        'status': 'ok',
        'results': results,
        'count': len(results),
        'truncated': already_truncated,
    }
    serialized = json.dumps(output, ensure_ascii=False)

    if len(serialized.encode('utf-8')) <= MAX_OUTPUT_BYTES:
        return results, already_truncated

    # バイナリサーチで収まる件数を探す
    lo, hi = 0, len(results)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        output['results'] = results[:mid]
        output['count'] = mid
        output['truncated'] = True
        test_json = json.dumps(output, ensure_ascii=False)
        if len(test_json.encode('utf-8')) <= MAX_OUTPUT_BYTES:
            lo = mid
        else:
            hi = mid - 1

    return results[:lo], True


# ---------------------------------------------------------------------------
# 影響範囲検索（DES-007 §5.2）
# ---------------------------------------------------------------------------

def search_affected_by(index_data, file_path, project_root, hops=1):
    """影響範囲検索を実行する。

    Args:
        index_data: load_index() で読み込んだインデックスデータ
        file_path: 起点ファイルパス（プロジェクトルート相対）
        project_root: プロジェクトルートの絶対パス
        hops: 探索ホップ数

    Returns:
        dict: JSON 出力用の結果辞書
    """
    # パス検証（パストラバーサル防止）
    try:
        validate_path_within_base(file_path, project_root)
    except ValueError as e:
        return {'status': 'error', 'message': str(e)}

    entries = index_data.get('entries', {})

    # パスの正規化: バックスラッシュをスラッシュに統一
    normalized_path = file_path.replace('\\', '/')

    # ファイルがインデックスに存在するか確認
    if normalized_path not in entries:
        return {
            'status': 'error',
            'message': f'ファイルがインデックスに存在しません: {normalized_path}',
        }

    # ImportGraph を構築して影響範囲を探索
    graph_entries = []
    for path, entry in entries.items():
        graph_entries.append({
            'file': path,
            'imports': entry.get('imports', []),
        })

    graph = ImportGraph()
    graph.build(graph_entries)
    affected = graph.affected_files(normalized_path, hops=hops)

    return {
        'status': 'ok',
        'affected_files': sorted(affected),
        'count': len(affected),
    }


# ---------------------------------------------------------------------------
# CLI エントリポイント
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='コードインデックス検索 CLI（DES-007 §5.1-5.3）',
    )
    # 2つの排他的モード
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        '--query',
        metavar='KEYWORDS',
        help='キーワード検索（空白区切りで複数キーワード指定可能）',
    )
    group.add_argument(
        '--affected-by',
        metavar='FILE_PATH',
        help='影響範囲検索（指定ファイルに依存するファイルを列挙）',
    )

    parser.add_argument(
        'project_root',
        help='プロジェクトルートのパス',
    )
    parser.add_argument(
        '--hops',
        type=int,
        default=1,
        help='影響範囲検索のホップ数（デフォルト: 1）',
    )

    args = parser.parse_args()

    # インデックスファイルのパスを構築
    index_path = os.path.join(args.project_root, INDEX_REL_PATH)

    # インデックス読み込み
    try:
        index_data = load_index(index_path)
    except FileNotFoundError:
        result = {
            'status': 'error',
            'message': f'インデックスが見つかりません: {index_path}。'
                       f' build_code_index.py で構築してください。',
        }
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1)
    except (ValueError, json.JSONDecodeError) as e:
        result = {
            'status': 'error',
            'message': f'インデックスの読み込みに失敗しました: {e}',
        }
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1)

    # モード別実行
    if args.query is not None:
        result = search_query(index_data, args.query)
    else:
        result = search_affected_by(
            index_data, args.affected_by, args.project_root, hops=args.hops,
        )

    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result['status'] == 'ok' else 1)


if __name__ == '__main__':
    main()
