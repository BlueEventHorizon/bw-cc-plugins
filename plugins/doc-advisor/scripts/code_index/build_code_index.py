#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""コードインデックス CLI エントリポイント。

core.py の薄い CLI ラッパー。3モード:
  --diff PROJECT_ROOT    : 変更ファイルリストを JSON で出力
  --mcp-data PROJECT_ROOT: stdin から subagent JSON を読み取りインデックス更新
  --check PROJECT_ROOT   : インデックスの鮮度を判定（fresh/stale）

全モードの出力は JSON（status: ok/error/fresh/stale）。

設計根拠: DES-007 §6.4-6.5, §3.1
"""

import argparse
import json
import sys
from pathlib import Path

from core import (
    detect_changes,
    load_index,
    merge_subagent_results,
    scan_files,
    write_checksums,
    write_index,
)


# ---------------------------------------------------------------------------
# パス定数
# ---------------------------------------------------------------------------

def _index_path(project_root):
    """インデックスファイルのパスを返す。"""
    return Path(project_root) / '.claude' / 'doc-advisor' / 'code_index' / 'code_index.json'


def _checksums_path(project_root):
    """チェックサムファイルのパスを返す。"""
    return Path(project_root) / '.claude' / 'doc-advisor' / 'code_index' / '.code_checksums.yaml'


# ---------------------------------------------------------------------------
# JSON 出力ヘルパー
# ---------------------------------------------------------------------------

def _output_json(data):
    """JSON を stdout に出力する。"""
    json.dump(data, sys.stdout, ensure_ascii=False)
    sys.stdout.write('\n')


def _output_error(message):
    """エラー JSON を stdout に出力し、終了コード 1 で終了する。"""
    _output_json({'status': 'error', 'message': message})
    sys.exit(1)


# ---------------------------------------------------------------------------
# --diff モード（DES-007 §6.5）
# ---------------------------------------------------------------------------

def cmd_diff(project_root):
    """変更ファイルリストを JSON で出力する。

    インデックスを変更せず、差分のみを報告する。
    """
    project_root = Path(project_root).resolve()
    checksums = _checksums_path(project_root)

    files = scan_files(project_root)
    changes = detect_changes(project_root, files, checksums)

    new = changes['new']
    modified = changes['modified']
    deleted = changes['deleted']

    if not new and not modified and not deleted:
        _output_json({
            'status': 'fresh',
            'new': [],
            'modified': [],
            'deleted': [],
        })
    else:
        _output_json({
            'status': 'stale',
            'new': new,
            'modified': modified,
            'deleted': deleted,
        })


# ---------------------------------------------------------------------------
# --mcp-data モード（DES-007 §7.1 ステップ4）
# ---------------------------------------------------------------------------

def _validate_subagent_json(data):
    """subagent 出力 JSON のスキーマ検証を行う。

    必須キー imports/exports の存在と型（list）をチェックする。

    Args:
        data: subagent が出力した dict（キー=相対パス、値=メタデータ）

    Raises:
        ValueError: スキーマ不正の場合
    """
    if not isinstance(data, dict):
        raise ValueError('subagent JSON はオブジェクト（dict）である必要があります')

    for rel_path, entry in data.items():
        if not isinstance(entry, dict):
            raise ValueError(
                f'{rel_path}: エントリはオブジェクト（dict）である必要があります'
            )
        # imports 必須キー・型チェック
        if 'imports' not in entry:
            raise ValueError(f'{rel_path}: 必須キー "imports" がありません')
        if not isinstance(entry['imports'], list):
            raise ValueError(f'{rel_path}: "imports" は配列である必要があります')
        # exports 必須キー・型チェック
        if 'exports' not in entry:
            raise ValueError(f'{rel_path}: 必須キー "exports" がありません')
        if not isinstance(entry['exports'], list):
            raise ValueError(f'{rel_path}: "exports" は配列である必要があります')


def cmd_mcp_data(project_root):
    """stdin から subagent JSON を読み取り、インデックスを更新する。"""
    project_root = Path(project_root).resolve()
    index_path = _index_path(project_root)
    checksums_path = _checksums_path(project_root)

    # stdin から JSON を読み取る
    try:
        raw = sys.stdin.read()
        subagent_data = json.loads(raw)
    except json.JSONDecodeError:
        _output_error('Invalid JSON input')

    # subagent JSON 出力のスキーマ検証
    try:
        _validate_subagent_json(subagent_data)
    except ValueError as e:
        _output_error(str(e))

    # 既存インデックスの読み込み（存在しない場合は空で初期化）
    try:
        existing_index = load_index(index_path)
    except FileNotFoundError:
        existing_index = {'entries': {}}
    except (ValueError, json.JSONDecodeError):
        # 破損・バージョン不一致の場合は空で再構築
        existing_index = {'entries': {}}

    # 差分検出（deleted ファイルの特定用）
    files = scan_files(project_root)
    changes = detect_changes(project_root, files, checksums_path)

    # subagent 結果を統合
    updated_index = merge_subagent_results(
        existing_index, subagent_data, project_root,
        deleted_files=changes['deleted'],
    )

    # インデックス書き込み → チェックサム書き込み（書き込み順序: DES-007 §6.3）
    write_index(updated_index, index_path)
    write_checksums(changes['current_checksums'], checksums_path)

    # 統計情報を出力（DES-007 §6.3）
    _output_json({
        'status': 'ok',
        'file_count': len(updated_index.get('entries', {})),
        'new': len(changes['new']),
        'modified': len(changes['modified']),
        'deleted': len(changes['deleted']),
        'skipped': len(changes['unchanged']),
        'failed': 0,
    })


# ---------------------------------------------------------------------------
# --check モード（DES-007 §6.4）
# ---------------------------------------------------------------------------

def cmd_check(project_root):
    """インデックスの鮮度を判定する（fresh/stale）。"""
    project_root = Path(project_root).resolve()
    index_path = _index_path(project_root)
    checksums_path = _checksums_path(project_root)

    # インデックスの存在確認
    try:
        load_index(index_path)
    except FileNotFoundError:
        _output_error('Index not found. Run build_code_index.py first.')
    except (ValueError, json.JSONDecodeError) as e:
        _output_error(str(e))

    # 差分検出
    files = scan_files(project_root)
    changes = detect_changes(project_root, files, checksums_path)

    new = changes['new']
    modified = changes['modified']
    deleted = changes['deleted']

    if not new and not modified and not deleted:
        _output_json({'status': 'fresh'})
    else:
        parts = []
        if new:
            parts.append(f'{len(new)} new')
        if modified:
            parts.append(f'{len(modified)} modified')
        if deleted:
            parts.append(f'{len(deleted)} deleted')
        reason = ', '.join(parts)
        _output_json({'status': 'stale', 'reason': reason})


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='コードインデックス CLI（DES-007 §6.4-6.5）',
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--diff', metavar='PROJECT_ROOT',
                       help='変更ファイルリストを JSON で出力')
    group.add_argument('--mcp-data', metavar='PROJECT_ROOT',
                       help='stdin から subagent JSON を読み取りインデックス更新')
    group.add_argument('--check', metavar='PROJECT_ROOT',
                       help='インデックスの鮮度を判定（fresh/stale）')

    args = parser.parse_args()

    if args.diff:
        cmd_diff(args.diff)
    elif args.mcp_data:
        cmd_mcp_data(args.mcp_data)
    elif args.check:
        cmd_check(args.check)


if __name__ == '__main__':
    main()
