#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""コードインデックスのコアモジュール。

ファイルスキャン・差分検出・インデックス構築・永続化を担当する。
言語固有のメタデータ抽出は subagent（SKILL.md）に委譲し、
本モジュールは言語非依存のロジックのみを扱う。

設計根拠: DES-007 §3.1-3.3, §5.4, §6.2-6.3
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# toc_utils.py の共通関数を再利用（DES-007 §3.2）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from toc_utils import (
    calculate_file_hash,
    load_checksums,
    log,
    normalize_path,
    rglob_follow_symlinks,
    write_checksums_yaml,
)

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

# 除外ディレクトリ（REQ-004 FR-01-3, DES-007 §6.1）
DEFAULT_EXCLUDE_DIRS = frozenset({
    '.git', '.build', 'DerivedData', 'Pods',
    'node_modules', '__pycache__', 'dist', 'build', 'vendor',
})

# 拡張子→言語マッピングテーブル（DES-007 §3.3）
DEFAULT_EXTENSION_MAP: dict[str, str] = {
    '.swift': 'swift',
    '.py': 'python',
    '.ts': 'typescript',
    '.js': 'javascript',
    '.kt': 'kotlin',
    '.java': 'java',
    '.go': 'go',
    '.rs': 'rust',
}

# インデックスのスキーマバージョン（DES-007 §5.4）
SCHEMA_VERSION = '1.0'


# ---------------------------------------------------------------------------
# ファイルスキャン（DES-007 §6.1）
# ---------------------------------------------------------------------------

def scan_files(project_root, extensions=None, exclude_dirs=None):
    """プロジェクトルート配下のソースコードファイルを再帰スキャンする。

    rglob_follow_symlinks() でファイル一覧を取得し、
    除外ディレクトリと拡張子でフィルタリングする。

    Args:
        project_root: プロジェクトルートのパス (str or Path)
        extensions: 対象拡張子のセット (例: {'.swift', '.py'})。
                    None の場合は DEFAULT_EXTENSION_MAP のキーを使用
        exclude_dirs: 除外ディレクトリ名のセット。
                      None の場合は DEFAULT_EXCLUDE_DIRS を使用

    Returns:
        list[str]: プロジェクトルート相対パスのリスト（NFC 正規化済み）
    """
    project_root = Path(project_root)
    if extensions is None:
        extensions = set(DEFAULT_EXTENSION_MAP.keys())
    if exclude_dirs is None:
        exclude_dirs = DEFAULT_EXCLUDE_DIRS

    result: list[str] = []
    for filepath in rglob_follow_symlinks(project_root, '**/*'):
        # 除外ディレクトリチェック
        rel = filepath.relative_to(project_root)
        parts = rel.parts
        if any(part in exclude_dirs for part in parts):
            continue

        # 拡張子フィルタ
        if filepath.suffix not in extensions:
            continue

        result.append(normalize_path(str(rel)))

    return sorted(result)


# ---------------------------------------------------------------------------
# 言語判定（DES-007 §3.3）
# ---------------------------------------------------------------------------

def detect_language(file_path, extension_map=None):
    """ファイルの拡張子から言語を判定する。

    Args:
        file_path: ファイルパス（拡張子が取得できれば相対・絶対どちらでも可）
        extension_map: 拡張子→言語の辞書。None の場合は DEFAULT_EXTENSION_MAP を使用

    Returns:
        str: 言語名。未対応拡張子の場合は 'unknown'
    """
    if extension_map is None:
        extension_map = DEFAULT_EXTENSION_MAP
    ext = os.path.splitext(str(file_path))[1].lower()
    return extension_map.get(ext, 'unknown')


# ---------------------------------------------------------------------------
# 差分検出（DES-007 §6.2）
# ---------------------------------------------------------------------------

def detect_changes(project_root, files, checksums_path):
    """ファイルの変更状態を検出する。

    calculate_file_hash() で各ファイルのハッシュを計算し、
    load_checksums() で前回のチェックサムと比較して
    new / modified / deleted / unchanged に分類する。

    前提条件:
        files は scan_files() の結果（ディスク上に存在するファイルの完全なリスト）を
        渡すこと。部分リストを渡した場合、リストに含まれないファイルが deleted と
        誤判定される（DES-007 §6.2: 削除 = ディスクに存在しない）。

    Args:
        project_root: プロジェクトルートのパス (str or Path)
        files: scan_files() が返すプロジェクトルート相対パスのリスト
        checksums_path: チェックサムファイルのパス (str or Path)

    Returns:
        dict: {
            'new': [str, ...],
            'modified': [str, ...],
            'deleted': [str, ...],
            'unchanged': [str, ...],
            'current_checksums': {path: hash, ...}  # 書き込み用
        }
    """
    project_root = Path(project_root)
    old_checksums = load_checksums(checksums_path)

    new: list[str] = []
    modified: list[str] = []
    unchanged: list[str] = []
    current_checksums: dict[str, str] = {}

    for rel_path in files:
        abs_path = project_root / rel_path
        file_hash = calculate_file_hash(abs_path)
        if file_hash is None:
            # ファイル読み込みエラーはスキップ
            continue
        current_checksums[rel_path] = file_hash

        old_hash = old_checksums.get(rel_path)
        if old_hash is None:
            new.append(rel_path)
        elif old_hash != file_hash:
            modified.append(rel_path)
        else:
            unchanged.append(rel_path)

    # 削除: 前回チェックサムに存在するが今回スキャンに含まれないファイル
    current_set = set(files)
    deleted = [p for p in old_checksums if p not in current_set]

    return {
        'new': new,
        'modified': modified,
        'deleted': deleted,
        'unchanged': unchanged,
        'current_checksums': current_checksums,
    }


# ---------------------------------------------------------------------------
# インデックス構築（DES-007 §6.3）
# ---------------------------------------------------------------------------

def _count_lines(project_root, rel_path):
    """ファイルの行数を返す。読み込みエラー時は 0。"""
    try:
        with open(Path(project_root) / rel_path, 'r', encoding='utf-8', errors='replace') as f:
            return sum(1 for _ in f)
    except (IOError, OSError):
        return 0


def merge_subagent_results(existing_index, subagent_entries, project_root,
                           deleted_files=None):
    """subagent JSON の結果を既存インデックスに統合する。

    subagent が出力した imports/exports を取り込み、
    lines（行数）と language を付加する。
    deleted ファイルはインデックスから除去する。

    Args:
        existing_index: 既存のインデックス dict（entries キー含む）。
                        空の場合は新規作成
        subagent_entries: subagent が出力した dict。
                         キー=相対パス、値={imports, exports, sections}
        project_root: プロジェクトルートのパス (str or Path)
        deleted_files: 削除されたファイルパスのリスト

    Returns:
        dict: 更新されたインデックス（entries キー）
    """
    entries = existing_index.get('entries', {})

    # deleted ファイルを除去
    if deleted_files:
        for f in deleted_files:
            entries.pop(f, None)

    # subagent 結果を統合
    for rel_path, data in subagent_entries.items():
        lang = detect_language(rel_path)
        lines = _count_lines(project_root, rel_path)
        entry = {
            'language': lang,
            'lines': lines,
            'imports': data.get('imports', []),
            'exports': data.get('exports', []),
            'sections': data.get('sections', []),
        }
        entries[rel_path] = entry

    existing_index['entries'] = entries
    return existing_index


# ---------------------------------------------------------------------------
# インデックス書き込み（DES-007 §6.3 アトミック書き込み）
# ---------------------------------------------------------------------------

def write_index(index_data, index_path):
    """インデックスを JSON ファイルにアトミック書き込みする。

    metadata.schema_version = "1.0" を付加し、
    tempfile + os.replace でアトミック性を保証する。

    Args:
        index_data: インデックス dict（entries キー含む）
        index_path: 出力ファイルパス (str or Path)

    Raises:
        OSError: 書き込みに失敗した場合
    """
    index_path = Path(index_path)
    entries = index_data.get('entries', {})

    # metadata を構築（DES-007 §5.4）
    languages: dict[str, int] = {}
    for entry in entries.values():
        lang = entry.get('language', 'unknown')
        languages[lang] = languages.get(lang, 0) + 1

    output = {
        'metadata': {
            'schema_version': SCHEMA_VERSION,
            'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'file_count': len(entries),
            'languages': languages,
        },
        'entries': entries,
    }

    # アトミック書き込み: tempfile + os.replace
    index_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(index_path.parent),
        suffix='.tmp',
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(tmp_path, str(index_path))
    except Exception:
        # 一時ファイルのクリーンアップ
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# チェックサム書き込み（DES-007 §6.3）
# ---------------------------------------------------------------------------

def write_checksums(checksums, checksums_path):
    """チェックサムファイルを書き込む。

    toc_utils.py の write_checksums_yaml() を再利用する。
    書き込み順序: write_index → write_checksums（冪等性保証）。

    Args:
        checksums: {相対パス: ハッシュ値} の dict
        checksums_path: 出力ファイルパス (str or Path)

    Returns:
        bool: 成功時 True、失敗時 False
    """
    checksums_path = Path(checksums_path)
    checksums_path.parent.mkdir(parents=True, exist_ok=True)
    return write_checksums_yaml(
        checksums, checksums_path,
        header_comment='Code index checksum file',
    )


# ---------------------------------------------------------------------------
# インデックス読み込み・スキーマバージョン検証（DES-007 §5.4）
# ---------------------------------------------------------------------------

def load_index(index_path):
    """インデックス JSON を読み込み、スキーマバージョンを検証する。

    schema_version が "1.0" でない場合は ValueError を送出し、
    --full での再構築を案内する。

    Args:
        index_path: インデックスファイルのパス (str or Path)

    Returns:
        dict: インデックスデータ

    Raises:
        FileNotFoundError: ファイルが存在しない場合
        ValueError: スキーマバージョンが不一致の場合
        json.JSONDecodeError: JSON パースに失敗した場合
    """
    index_path = Path(index_path)
    with open(index_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    metadata = data.get('metadata', {})
    version = metadata.get('schema_version')

    if version != SCHEMA_VERSION:
        raise ValueError(
            f"スキーマバージョン不一致: 期待={SCHEMA_VERSION}, 実際={version}。"
            f" --full で再構築してください。"
        )

    return data
