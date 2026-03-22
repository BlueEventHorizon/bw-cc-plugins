#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
バージョンファイル検出スクリプト（.version-config.yaml 生成用）

プロジェクト内のバージョン管理ファイル・README・CHANGELOG を発見し、
メタデータを JSON で出力する。
設定の生成判断は行わない。AI が SKILL.md 内のルールに従って判定する。

Usage:
    python3 scan_version_targets.py [project_root]
    python3 scan_version_targets.py [project_root] --depth 5
"""

import sys
import os
import json
import argparse
import re
from pathlib import Path


# スキップするディレクトリ
SKIP_DIRS = {
    '.git', '.claude', '.github', '.vscode', '.idea',
    'node_modules', '__pycache__', '.tox', '.mypy_cache',
    'venv', '.venv', 'env', '.env',
    'dist', 'build', 'target', 'out',
    '.next', '.nuxt', '.svelte-kit',
    'vendor', 'Pods', '.gradle',
    '.bundle',
}

# バージョンファイルのファイル名パターン
VERSION_FILE_NAMES = {
    'plugin.json',
    'package.json',
    'Cargo.toml',
    'pyproject.toml',
}

# CHANGELOG として認識するファイル名（ルート限定）
CHANGELOG_NAMES = {
    'CHANGELOG.md', 'CHANGELOG', 'CHANGELOG.rst',
    'HISTORY.md', 'HISTORY', 'HISTORY.rst',
    'CHANGES.md', 'CHANGES', 'RELEASES.md',
}

# バージョンファイル読み込み時の最大バイト数（64KB）
MAX_READ_SIZE = 65536

# keep-a-changelog の判定パターン
KEEP_A_CHANGELOG_PATTERN = re.compile(
    r'^##\s+\[', re.MULTILINE
)


def get_project_root(path=None):
    """.git ディレクトリを探索してプロジェクトルートを特定する。"""
    start = Path(path) if path else Path.cwd()
    current = start.resolve()
    while current != current.parent:
        if (current / '.git').exists():
            return str(current)
        current = current.parent
    return str(start.resolve())


def parse_args():
    """コマンドライン引数をパースする。"""
    parser = argparse.ArgumentParser(
        description='プロジェクトのバージョンファイルをスキャンし、メタデータを JSON で出力する'
    )
    parser.add_argument('project_root', nargs='?', default=None,
                        help='Project root directory (default: auto-detect from .git)')
    parser.add_argument('--depth', type=int, default=6,
                        help='Maximum directory scan depth (default: 6)')
    return parser.parse_args()


def extract_version_from_json(filepath):
    """
    JSON ファイルから name と version を抽出する。

    Returns:
        dict: 'name' と 'version' キーを持つ辞書（値は None の場合あり）
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read(MAX_READ_SIZE)
        data = json.loads(content)
        if not isinstance(data, dict):
            return {'name': None, 'version': None}
        return {
            'name': data.get('name') if isinstance(data.get('name'), str) else None,
            'version': data.get('version') if isinstance(data.get('version'), str) else None,
        }
    except (IOError, OSError, json.JSONDecodeError) as e:
        print(f"警告: JSON パースエラー ({filepath}): {e}", file=sys.stderr)
        return {'name': None, 'version': None}


def extract_version_from_toml(filepath):
    """
    TOML ファイルから name と version を抽出する（標準ライブラリのみ）。

    [package] または [project] セクション内の name と version を正規表現で取得する。

    Returns:
        dict: 'name' と 'version' キーを持つ辞書（値は None の場合あり）
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read(MAX_READ_SIZE)
    except (IOError, OSError, UnicodeDecodeError) as e:
        print(f"警告: TOML 読み込みエラー ({filepath}): {e}", file=sys.stderr)
        return {'name': None, 'version': None}

    # [package] または [project] セクションを抽出（最初にマッチした方を使用）
    package_match = re.search(r'^\[(?:package|project)\](.*?)(?=^\[|\Z)', content,
                               re.MULTILINE | re.DOTALL)
    if not package_match:
        return {'name': None, 'version': None}

    section = package_match.group(1)

    # version = "X.Y.Z" または version = 'X.Y.Z'
    version_match = re.search(r'''^\s*version\s*=\s*["']([^"']+)["']''', section, re.MULTILINE)
    name_match = re.search(r'''^\s*name\s*=\s*["']([^"']+)["']''', section, re.MULTILINE)

    return {
        'name': name_match.group(1) if name_match else None,
        'version': version_match.group(1) if version_match else None,
    }


def get_version_file_type(filename):
    """ファイル名からバージョンファイルの種別を返す。"""
    mapping = {
        'plugin.json': 'plugin.json',
        'package.json': 'package.json',
        'Cargo.toml': 'Cargo.toml',
        'pyproject.toml': 'pyproject.toml',
    }
    return mapping.get(filename)


def scan_version_files(project_root, max_depth=6):
    """
    プロジェクト内のバージョンファイルを走査する。

    Returns:
        list[dict]: バージョンファイルのメタデータ
    """
    results = []
    root = Path(project_root)
    visited_real = set()

    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        current = Path(dirpath)
        real_path = current.resolve()

        # シンボリックリンクの循環検出
        if real_path in visited_real:
            dirnames[:] = []
            continue
        visited_real.add(real_path)

        # 深さ制限
        rel = current.relative_to(root)
        depth = len(rel.parts)
        if depth > max_depth:
            dirnames[:] = []
            continue

        # スキップディレクトリを除外（SKIP_DIRS に含まれるもののみ）
        # .claude-plugin/ のようなバージョンファイルを含む隠しディレクトリは除外しない
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS
        ]

        for filename in filenames:
            file_type = get_version_file_type(filename)
            if file_type is None:
                continue

            filepath = current / filename
            rel_path = str(filepath.relative_to(root))

            # ファイル種別に応じてメタデータを抽出
            if filename.endswith('.toml'):
                meta = extract_version_from_toml(filepath)
            else:
                meta = extract_version_from_json(filepath)

            # version と name の両方が None の場合スキップ
            if meta['version'] is None and meta['name'] is None:
                continue

            results.append({
                'path': rel_path,
                'type': file_type,
                'detected_name': meta['name'],
                'current_version': meta['version'],
            })

    return results


def scan_catalog_files(project_root):
    """
    ルートのカタログファイル（marketplace.json 等）を検出する。

    Returns:
        list[dict]: カタログファイルのメタデータ
    """
    root = Path(project_root)
    results = []

    catalog_patterns = [
        '.claude-plugin/marketplace.json',
        'marketplace.json',
    ]

    for pattern in catalog_patterns:
        filepath = root / pattern
        if filepath.exists() and filepath.is_file():
            results.append({
                'path': pattern,
                'type': filepath.name,
            })

    return results


def scan_readme_files(project_root):
    """
    ルートの README ファイルを検出する（深い階層は対象外）。

    Returns:
        list[str]: README ファイルのパス（相対）
    """
    root = Path(project_root)
    results = []

    for f in sorted(root.iterdir()):
        if f.is_file() and f.suffix.lower() in ('.md', '.rst', '.txt'):
            name_lower = f.name.lower()
            if name_lower.startswith('readme'):
                results.append(f.name)

    return results


# version_ref_files で除外するファイル（他のカテゴリで検出済み、またはスキャン不要）
VERSION_REF_SKIP_FILES = set(CHANGELOG_NAMES)

# テキストファイルとして扱う拡張子
TEXT_EXTENSIONS = {'.md', '.rst', '.txt', '.yaml', '.yml', '.json', '.toml'}


def scan_version_ref_files(project_root, version_files, readme_files=None,
                           catalog_files=None):
    """
    プロジェクトルートの全テキストファイルからバージョン参照を検出する。

    他のカテゴリ（version_files, readme_files, catalog_files, changelog）で
    既に検出されたファイルは除外する。

    Args:
        project_root: プロジェクトルートパス
        version_files: scan_version_files の結果
        readme_files: scan_readme_files の結果（除外用）
        catalog_files: scan_catalog_files の結果（除外用）

    Returns:
        list[dict]: バージョン参照を持つファイルのメタデータ
            [{"path": "CLAUDE.md", "references": [{"name": "forge", "version": "0.0.23"}]}]
    """
    root = Path(project_root)
    results = []

    # バージョン検索用の辞書を構築
    version_map = {}
    for vf in version_files:
        if vf.get('current_version') and vf.get('detected_name'):
            version_map[vf['detected_name']] = vf['current_version']

    if not version_map:
        return results

    # 他カテゴリで検出済みのファイル名を収集（除外用）
    skip_files = set(VERSION_REF_SKIP_FILES)
    if readme_files:
        skip_files.update(readme_files)
    if catalog_files:
        for cf in catalog_files:
            skip_files.add(Path(cf['path']).name)
    for vf in version_files:
        skip_files.add(Path(vf['path']).name)

    # ルートの全テキストファイルを走査
    for filepath in sorted(root.iterdir()):
        if not filepath.is_file():
            continue
        if filepath.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        if filepath.name in skip_files:
            continue

        try:
            content = filepath.read_text(encoding='utf-8')
        except (IOError, OSError, UnicodeDecodeError):
            continue

        references = []
        for name, version in version_map.items():
            if version in content:
                references.append({'name': name, 'version': version})

        if references:
            results.append({
                'path': filepath.name,
                'references': references,
            })

    return results


def detect_changelog_format(filepath):
    """
    CHANGELOG ファイルの形式を判定する。

    Returns:
        'keep-a-changelog' | 'simple' | 'unknown'
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read(4096)
    except (IOError, OSError, UnicodeDecodeError):
        return 'unknown'

    if KEEP_A_CHANGELOG_PATTERN.search(content):
        return 'keep-a-changelog'

    # シンプルな ## vX.Y.Z パターン
    if re.search(r'^##\s+v?\d+\.\d+', content, re.MULTILINE):
        return 'simple'

    return 'unknown'


def scan_changelog(project_root):
    """
    ルートの CHANGELOG ファイルを検出し、形式を判定する。

    Returns:
        dict | None
    """
    root = Path(project_root)

    for name in CHANGELOG_NAMES:
        filepath = root / name
        if filepath.exists() and filepath.is_file():
            fmt = detect_changelog_format(filepath)
            return {
                'file': name,
                'format': fmt,
            }

    return None


def output_scan(project_root, version_files, catalog_files, readme_files,
                changelog, version_ref_files=None):
    """スキャン結果を JSON で出力する。"""
    output = {
        'project_root': project_root,
        'version_files': version_files,
        'catalog_files': catalog_files,
        'readme_files': readme_files,
        'version_ref_files': version_ref_files or [],
        'changelog': changelog,
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))


def main():
    args = parse_args()
    project_root = get_project_root(args.project_root)
    max_depth = args.depth

    version_files = scan_version_files(project_root, max_depth)
    catalog_files = scan_catalog_files(project_root)
    readme_files = scan_readme_files(project_root)
    version_ref_files = scan_version_ref_files(
        project_root, version_files,
        readme_files=readme_files, catalog_files=catalog_files)
    changelog = scan_changelog(project_root)

    output_scan(project_root, version_files, catalog_files, readme_files,
                changelog, version_ref_files)
    return 0


if __name__ == '__main__':
    sys.exit(main())
