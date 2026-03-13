#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
.doc_structure.yaml から参考文書を解決するスクリプト。

rules / specs カテゴリのパスを読み込み、glob 展開・exclude 適用後に
.md ファイルの一覧を JSON で出力する。

DocAdvisor（/query-rules, /query-specs）が利用不可の場合のフォールバックとして使用する。

使用例:
    python3 resolve_doc_references.py --type rules
    python3 resolve_doc_references.py --type specs
    python3 resolve_doc_references.py --type all
    python3 resolve_doc_references.py --type rules --project-root /path/to/project
"""

import argparse
import glob
import json
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# プロジェクトルートの自動検出
# ---------------------------------------------------------------------------

def find_project_root(start_path=None):
    """.git ディレクトリを遡って探索してプロジェクトルートを特定する。

    見つからない場合はカレントディレクトリを返す。
    """
    start = Path(start_path).resolve() if start_path else Path.cwd().resolve()
    current = start

    while current != current.parent:
        if (current / '.git').exists():
            return str(current)
        current = current.parent

    return str(start)


# ---------------------------------------------------------------------------
# .doc_structure.yaml の行ベースパーサー
# ---------------------------------------------------------------------------

def parse_doc_structure(yaml_path):
    """.doc_structure.yaml を標準ライブラリのみで行ベースパースする。

    PyYAML 非使用。以下の構造のみを対象とする:
      - トップレベルキー: specs / rules
      - 各 doc_type の paths / exclude / description

    Returns:
        dict: {'specs': {doc_type: {'paths': [...], 'exclude': [...]}}, 'rules': {...}}

    Raises:
        FileNotFoundError: yaml_path が存在しない場合
        ValueError: パース失敗時
    """
    if not os.path.isfile(yaml_path):
        raise FileNotFoundError(f".doc_structure.yaml が見つかりません: {yaml_path}")

    with open(yaml_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    result = {'specs': {}, 'rules': {}}

    # パーサーの状態管理
    current_category = None   # 'specs' または 'rules'
    current_doc_type = None   # 'requirement', 'design' 等
    current_field = None      # 'paths' または 'exclude'（配列中の場合）

    for raw_line in lines:
        line = raw_line.rstrip('\n')
        stripped = line.strip()

        # コメント行・空行をスキップ
        if not stripped or stripped.startswith('#'):
            current_field = None  # 配列コンテキストをリセット
            continue

        # インデントレベルを計算（スペース数）
        indent = len(line) - len(line.lstrip(' '))

        # トップレベルのキー（version: / specs: / rules:）
        if indent == 0:
            current_field = None
            if stripped == 'specs:' or stripped.startswith('specs:'):
                current_category = 'specs'
                current_doc_type = None
            elif stripped == 'rules:' or stripped.startswith('rules:'):
                current_category = 'rules'
                current_doc_type = None
            else:
                current_category = None
                current_doc_type = None
            continue

        # カテゴリ外はスキップ
        if current_category is None:
            continue

        # doc_type レベル（インデント 2）
        if indent == 2 and not stripped.startswith('-'):
            current_field = None
            if ':' in stripped:
                key = stripped.split(':')[0].strip()
                if key and key != 'version':
                    current_doc_type = key
                    if current_doc_type not in result[current_category]:
                        result[current_category][current_doc_type] = {
                            'paths': [],
                            'exclude': [],
                        }
            continue

        # doc_type が確定していない場合はスキップ
        if current_doc_type is None:
            continue

        # フィールドレベル（インデント 4）
        if indent == 4 and not stripped.startswith('-'):
            key_part = stripped.split(':')[0].strip()
            value_part = stripped[len(key_part) + 1:].strip() if ':' in stripped else ''

            if key_part in ('paths', 'exclude'):
                current_field = key_part
                # インライン配列: paths: [val1, val2]
                if value_part.startswith('[') and value_part.endswith(']'):
                    items = _parse_inline_array(value_part)
                    result[current_category][current_doc_type][key_part].extend(items)
                    current_field = None  # インライン配列は完結
            else:
                current_field = None
            continue

        # 配列要素レベル（インデント 4 または 6、先頭 '-'）
        if stripped.startswith('- ') and current_field in ('paths', 'exclude'):
            item = stripped[2:].strip().strip('"\'')
            if item:
                result[current_category][current_doc_type][current_field].append(item)
            continue

    return result


def _parse_inline_array(value):
    """YAML インライン配列 [item1, item2] をパースする。

    クォート除去と空白トリムを行う。
    """
    inner = value.strip()[1:-1]  # '[' と ']' を除去
    items = []
    for item in inner.split(','):
        item = item.strip().strip('"\'')
        if item:
            items.append(item)
    return items


# ---------------------------------------------------------------------------
# パス解決（glob 展開 + exclude 適用）
# ---------------------------------------------------------------------------

def resolve_paths(project_root, category_data):
    """カテゴリデータからファイルパスを解決する。

    Args:
        project_root: プロジェクトルートの絶対パス
        category_data: {'doc_type': {'paths': [...], 'exclude': [...]}} 形式の dict

    Returns:
        list[str]: project_root からの相対パス（.md ファイルのみ）
    """
    resolved = []
    seen = set()  # 重複除外

    for doc_type, entry in category_data.items():
        paths = entry.get('paths', [])
        excludes = entry.get('exclude', [])

        for path_pattern in paths:
            # 末尾スラッシュを正規化
            path_pattern = path_pattern.rstrip('/')

            # glob 展開が必要かどうか判定
            if '*' in path_pattern:
                # ディレクトリの glob 展開（再帰対応）
                full_pattern = os.path.join(project_root, path_pattern)
                matched_dirs = glob.glob(full_pattern, recursive=('**' in path_pattern))

                for matched_dir in sorted(matched_dirs):
                    # 展開結果がディレクトリの場合、その中の .md を収集
                    if os.path.isdir(matched_dir):
                        md_files = _collect_md_files(matched_dir, excludes, project_root)
                        for f in md_files:
                            if f not in seen:
                                seen.add(f)
                                resolved.append(f)
                    elif matched_dir.endswith('.md'):
                        # glob がファイルを直接マッチした場合
                        rel = os.path.relpath(matched_dir, project_root)
                        if not _is_excluded(rel, excludes) and rel not in seen:
                            seen.add(rel)
                            resolved.append(rel)
            else:
                # リテラルパス
                full_path = os.path.join(project_root, path_pattern)
                if os.path.isdir(full_path):
                    md_files = _collect_md_files(full_path, excludes, project_root)
                    for f in md_files:
                        if f not in seen:
                            seen.add(f)
                            resolved.append(f)
                elif os.path.isfile(full_path) and full_path.endswith('.md'):
                    rel = os.path.relpath(full_path, project_root)
                    if not _is_excluded(rel, excludes) and rel not in seen:
                        seen.add(rel)
                        resolved.append(rel)
                # 存在しないパスはスキップ（エラーにしない）

    return resolved


def _collect_md_files(directory, excludes, project_root):
    """.md ファイルをディレクトリ以下から再帰的に収集する。

    exclude リストに含まれるパスコンポーネントを持つものは除外する。

    Returns:
        list[str]: project_root からの相対パス
    """
    pattern = os.path.join(directory, '**', '*.md')
    md_files = glob.glob(pattern, recursive=True)

    result = []
    for f in sorted(md_files):
        if not os.path.isfile(f):
            continue
        rel = os.path.relpath(f, project_root)
        if not _is_excluded(rel, excludes):
            result.append(rel)
    return result


def _is_excluded(rel_path, excludes):
    """パスのいずれかのコンポーネントが exclude リストに含まれるか判定する。

    Args:
        rel_path: project_root からの相対パス（例: 'specs/archived/req.md'）
        excludes: 除外するディレクトリ名のリスト（例: ['archived', '_template']）

    Returns:
        bool: 除外すべき場合 True
    """
    if not excludes:
        return False
    parts = set(Path(rel_path).parts)
    return bool(parts & set(excludes))


# ---------------------------------------------------------------------------
# メインロジック
# ---------------------------------------------------------------------------

def resolve_references(resolve_type, project_root, doc_structure_path=None):
    """参考文書を解決して結果 dict を返す。

    Args:
        resolve_type: 'rules' / 'specs' / 'all'
        project_root: プロジェクトルートの絶対パス
        doc_structure_path: .doc_structure.yaml のパス（省略時は自動決定）

    Returns:
        dict: JSON 出力用の結果 dict
    """
    if doc_structure_path is None:
        doc_structure_path = os.path.join(project_root, '.doc_structure.yaml')

    try:
        structure = parse_doc_structure(doc_structure_path)
    except FileNotFoundError as e:
        return {
            'status': 'error',
            'message': str(e),
        }
    except Exception as e:
        return {
            'status': 'error',
            'message': f".doc_structure.yaml のパースに失敗しました: {e}",
        }

    result = {
        'status': 'resolved',
        'project_root': project_root,
    }

    if resolve_type in ('rules', 'all'):
        rules_data = structure.get('rules', {})
        result['rules'] = resolve_paths(project_root, rules_data)

    if resolve_type in ('specs', 'all'):
        specs_data = structure.get('specs', {})
        result['specs'] = resolve_paths(project_root, specs_data)

    return result


# ---------------------------------------------------------------------------
# CLI エントリポイント
# ---------------------------------------------------------------------------

def parse_args():
    """コマンドライン引数をパースする。"""
    parser = argparse.ArgumentParser(
        description='.doc_structure.yaml から参考文書パスを解決して JSON で出力する'
    )
    parser.add_argument(
        '--type',
        required=True,
        choices=['rules', 'specs', 'all'],
        help='解決対象カテゴリ: rules / specs / all',
    )
    parser.add_argument(
        '--project-root',
        default=None,
        help='プロジェクトルートのパス（省略時: .git を遡って自動検出）',
    )
    parser.add_argument(
        '--doc-structure',
        default=None,
        help='.doc_structure.yaml のパス（省略時: project_root/.doc_structure.yaml）',
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # プロジェクトルートの決定
    project_root = args.project_root
    if project_root:
        project_root = os.path.abspath(project_root)
    else:
        project_root = find_project_root()

    # .doc_structure.yaml パスの決定
    doc_structure_path = args.doc_structure
    if doc_structure_path:
        doc_structure_path = os.path.abspath(doc_structure_path)

    result = resolve_references(args.type, project_root, doc_structure_path)

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if result.get('status') == 'error':
        sys.exit(1)

    return 0


if __name__ == '__main__':
    sys.exit(main())
