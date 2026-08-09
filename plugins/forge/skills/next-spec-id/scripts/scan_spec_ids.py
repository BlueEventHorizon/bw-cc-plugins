#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全ブランチ（ローカル + リモート）から指定プレフィックスの仕様書 ID をスキャンし、
次の連番 ID を JSON で返す。

.doc_structure.yaml から specs の root_dirs を取得してスキャン対象パスを
動的に決定する。.doc_structure.yaml が存在しない場合は specs/ をフォールバックとして使用。

使用例:
    python3 scan_spec_ids.py SCR
    python3 scan_spec_ids.py DES
    python3 scan_spec_ids.py --project-root /path/to/project TASK
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# resolve_doc_structure.py を import
_SCRIPT_DIR = Path(__file__).resolve().parent
_DOC_STRUCTURE_SCRIPTS = _SCRIPT_DIR.parents[2] / 'scripts' / 'doc_structure'
sys.path.insert(0, str(_DOC_STRUCTURE_SCRIPTS))

from resolve_doc_structure import (
    find_project_root,
    load_doc_structure,
)

FALLBACK_SPECS_DIRS = ['specs/']


def _run_git(*args, cwd=None):
    """git コマンドを実行して stdout を返す。失敗時は空文字列。"""
    try:
        result = subprocess.run(
            ['git'] + list(args),
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=30,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ''


def get_specs_root_dirs(project_root, doc_structure_path=None):
    """specs の root_dirs を取得する。glob パターンのまま返す。"""
    try:
        config, _ = load_doc_structure(project_root, doc_structure_path)
        specs = config.get('specs', {})
        root_dirs = specs.get('root_dirs', [])
        if root_dirs:
            return [d.rstrip('/') + '/' for d in root_dirs]
    except (FileNotFoundError, Exception):
        pass
    return FALLBACK_SPECS_DIRS


def _normalize_glob_to_prefix(pattern):
    """glob パターンを git ls-tree 用のプレフィックスに変換する。

    'docs/specs/**/design/' → 'docs/specs/'
    'docs/specs/*/requirements/' → 'docs/specs/'
    'specs/' → 'specs/'
    """
    parts = pattern.rstrip('/').split('/')
    prefix_parts = []
    for part in parts:
        if '*' in part or '?' in part:
            break
        prefix_parts.append(part)
    if prefix_parts:
        return '/'.join(prefix_parts) + '/'
    return ''


def detect_base_branch(cwd=None):
    """ベースブランチ（develop or main）を特定する。"""
    for ref in [
        'refs/heads/develop',
        'refs/remotes/origin/develop',
        'refs/heads/main',
        'refs/remotes/origin/main',
    ]:
        try:
            proc = subprocess.run(
                ['git', 'show-ref', '--verify', '--quiet', ref],
                capture_output=True,
                cwd=cwd,
                timeout=10,
            )
            if proc.returncode == 0:
                if ref.startswith('refs/remotes/'):
                    return ref.split('refs/remotes/')[-1]
                return ref.split('refs/heads/')[-1]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
    return 'main'


def get_scan_branches(base_branch, cwd=None):
    """ローカル + リモートの全ブランチを取得する。

    ID 衝突検出の目的では「base に追従しているか」は無関係であり、むしろ
    base から分岐したまま追従していないブランチほど衝突リスクが高い
    そのため is-ancestor によるフィルタは行わず、
    refs/heads/ + refs/remotes/origin/ から取得した全ブランチを無条件で
    スキャン対象にする。
    """
    output = _run_git(
        'for-each-ref', '--format=%(refname:short)',
        'refs/heads/', 'refs/remotes/origin/',
        cwd=cwd,
    )
    if not output:
        return [base_branch]

    all_branches = [
        b for b in output.split('\n')
        if b and 'HEAD' not in b
    ]
    all_branches = sorted(set(all_branches))

    return all_branches if all_branches else [base_branch]


def scan_ids_in_branch(branch, prefix, scan_dirs, cwd=None):
    """1つのブランチから指定プレフィックスの ID を抽出する。

    Returns:
        list[tuple[str, str, str]]: (id_string, branch_name, file_path) のリスト
    """
    # `(?<![A-Za-z0-9-])`: prefix の直前に境界を設け、`COMMON-DES-001` のような
    # 別名前空間の ID を `DES-001` として誤抽出しない
    pattern = re.compile(r'(?<![A-Za-z0-9-])' + re.escape(prefix) + r'-(\d+)')
    results = []

    unique_prefixes = sorted(set(
        _normalize_glob_to_prefix(d) for d in scan_dirs
    ))
    unique_prefixes = [p for p in unique_prefixes if p]
    if not unique_prefixes:
        unique_prefixes = ['specs/']

    for dir_prefix in unique_prefixes:
        output = _run_git(
            'ls-tree', '-r', '--name-only', branch, '--', dir_prefix,
            cwd=cwd,
        )
        if not output:
            continue

        for filepath in output.split('\n'):
            if not filepath:
                continue
            match = pattern.search(filepath)
            if match:
                id_str = '{}-{}'.format(prefix, match.group(1))
                results.append((id_str, branch, filepath))

    return results


def find_duplicates(id_entries, shared_numbering=False):
    """異なる文書が同じ ID（共有採番モードでは同じ番号）を主張しているケースを検出する。

    同一ファイルパスが複数ブランチに存在するのは同じコミット履歴に由来する
    正常な状態であり、重複として扱わない。重複と見なすのは、
    同じ番号キーを **異なるファイルパス** が主張している場合のみ。

    Args:
        id_entries: (id_str, branch, file_path) のリスト
        shared_numbering: True の場合、prefix を無視して番号のみをキーに衝突を見る
            （--share-prefixes 指定時。`ADR-007` と `DES-007` は共有番号 007 の衝突として報告する）

    Returns:
        list[dict]: 各要素は {'ids', 'branches', 'paths'}。
            'ids' は衝突に関与する全 ID。
    """
    id_num_pattern = re.compile(r'^(.+)-(\d+)$')
    groups = {}
    for id_str, branch, path in id_entries:
        m = id_num_pattern.match(id_str)
        if not m:
            continue
        prefix, num = m.group(1), int(m.group(2))
        key = num if shared_numbering else (prefix, num)
        group = groups.setdefault(key, {'ids': set(), 'branches': set(), 'paths': set()})
        group['ids'].add(id_str)
        group['branches'].add(branch)
        group['paths'].add(path)

    duplicates = []
    for key in sorted(groups):
        group = groups[key]
        if len(group['paths']) > 1:
            ids = sorted(group['ids'])
            duplicates.append({
                'ids': ids,
                'branches': sorted(group['branches']),
                'paths': sorted(group['paths']),
            })
    return duplicates


def scan_spec_ids(prefix, project_root, doc_structure_path=None, cwd=None, share_prefixes=None):
    """メインロジック: 全ブランチスキャンで次の ID を返す。

    Args:
        share_prefixes: 通し番号を共有する prefix のリスト（`prefix` 自身を含めても含めなくてもよい）。
            指定された場合、これらすべての prefix のファイルを横断スキャンして最大番号を計算し、
            `prefix` の次番号として返す（例: ADR と DES が同一ディレクトリで番号を共有する運用）。
    """
    if cwd is None:
        cwd = project_root

    scan_dirs = get_specs_root_dirs(project_root, doc_structure_path)

    # リモートをフェッチ（--prune: 削除済み remote branch の stale ref を除去。
    # 全ブランチ無条件スキャン方式では、stale ref が残ると存在しないブランチの
    # 高番 ID が永久に next_id を押し上げてしまうため必須）
    _run_git('fetch', '--quiet', '--prune', cwd=cwd)

    base_branch = detect_base_branch(cwd=cwd)
    branches = get_scan_branches(base_branch, cwd=cwd)

    scan_prefixes = list(share_prefixes) if share_prefixes else [prefix]
    if prefix not in scan_prefixes:
        scan_prefixes = [prefix] + scan_prefixes

    all_pairs = []
    for branch in branches:
        for scan_prefix in scan_prefixes:
            pairs = scan_ids_in_branch(branch, scan_prefix, scan_dirs, cwd=cwd)
            all_pairs.extend(pairs)

    # 最大番号を算出（scan_prefixes 全体の横断最大値）
    number_pattern = re.compile(
        '(?:' + '|'.join(re.escape(p) for p in scan_prefixes) + r')-(\d+)'
    )
    max_number = 0
    unique_ids = set()

    for id_str, _, _ in all_pairs:
        unique_ids.add(id_str)
        m = number_pattern.match(id_str)
        if m:
            num = int(m.group(1))
            if num > max_number:
                max_number = num

    next_number = max_number + 1
    next_id = '{}-{:03d}'.format(prefix, next_number)

    duplicates = find_duplicates(all_pairs, shared_numbering=bool(share_prefixes))

    result = {
        'status': 'ok',
        'next_id': next_id,
        'prefix': prefix,
        'max_number': max_number,
        'base_branch': base_branch,
        'branches_scanned': len(branches),
        'ids_found': len(unique_ids),
        'duplicates': duplicates,
    }
    if share_prefixes:
        result['shared_with'] = [p for p in scan_prefixes if p != prefix]
    return result


def parse_args():
    parser = argparse.ArgumentParser(
        description='全ブランチスキャンで仕様書 ID の次の連番を取得する'
    )
    parser.add_argument(
        'prefix',
        help='ID プレフィックス（例: SCR, DES, TASK）',
    )
    parser.add_argument(
        '--project-root',
        default=None,
        help='プロジェクトルートのパス（省略時: cwd）',
    )
    parser.add_argument(
        '--doc-structure',
        default=None,
        help='.doc_structure.yaml のパス（省略時: project_root/.doc_structure.yaml）',
    )
    parser.add_argument(
        '--share-prefixes',
        default=None,
        help='通し番号を共有する prefix のカンマ区切りリスト（例: ADR,DES）。'
             '指定した prefix を含む全ファイルの最大番号を横断計算する',
    )
    return parser.parse_args()


def main():
    args = parse_args()

    project_root = args.project_root
    if project_root:
        project_root = os.path.abspath(project_root)
    else:
        project_root = find_project_root()

    doc_structure_path = args.doc_structure
    if doc_structure_path:
        doc_structure_path = os.path.abspath(doc_structure_path)

    share_prefixes = None
    if args.share_prefixes:
        share_prefixes = [p.strip() for p in args.share_prefixes.split(',') if p.strip()]

    try:
        result = scan_spec_ids(
            args.prefix,
            project_root,
            doc_structure_path,
            share_prefixes=share_prefixes,
        )
    except Exception as e:
        result = {
            'status': 'error',
            'message': str(e),
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
