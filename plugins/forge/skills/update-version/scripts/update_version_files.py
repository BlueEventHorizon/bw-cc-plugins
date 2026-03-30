#!/usr/bin/env python3
"""JSON/TOML ファイルのバージョンフィールドを更新する。

元ファイルは書き換えない（NFR-01）。更新後の内容を stdout に出力する。

使用例:
    python3 update_version_files.py <file_path> <old_version> <new_version> [--version-path <path>] [--filter <pattern>]

出力:
    stdout: 更新後のファイル内容
    stderr: JSON ステータス {"status": "ok", "file": "...", "old": "...", "new": "..."}
"""

import json
import re
import sys
from pathlib import Path


def update_version_in_text(content, old_version, new_version, version_path=None, filter_pattern=None):
    """テキスト内のバージョン文字列を置換する。

    JSON/TOML のフォーマットを保持するため、テキスト操作で置換する。

    Args:
        content: ファイル内容（テキスト）
        old_version: 置換元バージョン文字列
        new_version: 置換先バージョン文字列
        version_path: バージョンフィールドのネストパス（例: "version", "package.version"）。
                      指定時はそのフィールド周辺のみ置換。省略時はファイル全体で最初のマッチを置換。
        filter_pattern: フィルタパターン。マッチするブロック内のみ置換する。

    Returns:
        str: 更新後のテキスト

    Raises:
        ValueError: バージョン文字列が見つからない
    """
    if not old_version:
        raise ValueError("old_version が空文字列です")
    if not new_version:
        raise ValueError("new_version が空文字列です")

    if filter_pattern:
        return _update_with_filter(content, old_version, new_version, filter_pattern)

    if version_path:
        return _update_with_path(content, old_version, new_version, version_path)

    # シンプルな置換（最初の出現のみ）
    return _replace_first(content, old_version, new_version)


def _replace_first(content, old_version, new_version):
    """最初に見つかったバージョン文字列を置換する。"""
    # クォート付きの置換を優先（JSON の "version": "X.Y.Z" パターン）
    quoted_old = f'"{old_version}"'
    quoted_new = f'"{new_version}"'

    if quoted_old in content:
        return content.replace(quoted_old, quoted_new, 1)

    # クォートなしの置換（TOML の version = "X.Y.Z" パターン）
    if old_version in content:
        return content.replace(old_version, new_version, 1)

    raise ValueError(f"バージョン '{old_version}' がファイル内に見つかりません")


def _update_with_path(content, old_version, new_version, version_path):
    """ネストパスを使ってバージョンフィールドを特定し置換する。

    version_path が "version" なら "version" キーの行を、
    "package.version" なら "package" ブロック内の "version" キーの行を特定する。
    """
    parts = version_path.split('.')
    field_name = parts[-1]  # 最終キー名

    # フィールド名を含む行を検索して置換
    pattern = re.compile(
        r'([\"\']?' + re.escape(field_name) + r'[\"\']?\s*[:=]\s*)[\"\']?'
        + re.escape(old_version) + r'[\"\']?'
    )

    if len(parts) == 1:
        # トップレベルフィールド
        result, count = pattern.subn(lambda m: m.group(1) + f'"{new_version}"', content, count=1)
        if count == 0:
            raise ValueError(f"フィールド '{version_path}' にバージョン '{old_version}' が見つかりません")
        return result

    # ネストフィールド: 親キーの後の最初のマッチを置換
    parent_key = parts[-2]
    parent_pattern = re.compile(r'[\"\']?' + re.escape(parent_key) + r'[\"\']?\s*[:={]')
    parent_match = parent_pattern.search(content)

    if not parent_match:
        raise ValueError(f"親キー '{parent_key}' が見つかりません")

    # 親キー以降で最初のフィールドマッチを置換
    start = parent_match.end()
    sub_content = content[start:]
    result, count = pattern.subn(lambda m: m.group(1) + f'"{new_version}"', sub_content, count=1)

    if count == 0:
        raise ValueError(f"フィールド '{version_path}' にバージョン '{old_version}' が見つかりません")

    return content[:start] + result


def _update_with_filter(content, old_version, new_version, filter_pattern,
                        max_distance=10):
    """フィルタパターンにマッチするブロック内のみ置換する。

    Args:
        content: ファイル内容
        old_version: 置換元バージョン
        new_version: 置換先バージョン
        filter_pattern: フィルタパターン
        max_distance: filter 行から version を探索する最大行数。
                      この行数以内に version が見つからなければブロックをリセットする。
    """
    lines = content.split('\n')
    in_block = False
    lines_since_filter = 0
    result_lines = []
    replaced = False

    for line in lines:
        if filter_pattern in line:
            # 新しい filter マッチ: カウンタをリセットしてブロック開始
            in_block = True
            lines_since_filter = 0
        elif in_block:
            lines_since_filter += 1
            if lines_since_filter > max_distance:
                # filter 行から一定行数以内に version が見つからなかった
                in_block = False

        if in_block and not replaced and old_version in line:
            line = line.replace(old_version, new_version, 1)
            replaced = True
            in_block = False

        result_lines.append(line)

    if not replaced:
        raise ValueError(
            f"フィルタ '{filter_pattern}' のブロック内にバージョン '{old_version}' が見つかりません"
        )

    return '\n'.join(result_lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='バージョンフィールドを更新する')
    parser.add_argument('file_path', help='対象ファイルパス')
    parser.add_argument('old_version', help='置換元バージョン')
    parser.add_argument('new_version', help='置換先バージョン')
    parser.add_argument('--version-path', help='バージョンフィールドのネストパス（例: version, package.version）')
    parser.add_argument('--filter', dest='filter_pattern', help='フィルタパターン（マッチするブロック内のみ置換）')
    parser.add_argument('--optional', action='store_true', help='パターン未マッチ時にエラーではなく警告で終了（exit 0）')

    args = parser.parse_args()

    try:
        content = Path(args.file_path).read_text(encoding='utf-8')
    except FileNotFoundError:
        error = {"status": "error", "error": f"File not found: {args.file_path}"}
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)

    try:
        updated = update_version_in_text(
            content, args.old_version, args.new_version,
            version_path=args.version_path,
            filter_pattern=args.filter_pattern,
        )
        # 更新後の内容を stdout に出力
        print(updated, end='')
        # ステータスを stderr に出力
        status = {
            "status": "ok",
            "file": args.file_path,
            "old": args.old_version,
            "new": args.new_version,
        }
        print(json.dumps(status, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(0)
    except ValueError as e:
        if args.optional:
            # optional モード: パターン未マッチは警告扱いで exit 0
            warning = {"status": "skipped", "file": args.file_path, "reason": str(e)}
            print(json.dumps(warning, ensure_ascii=False, indent=2), file=sys.stderr)
            sys.exit(0)
        error = {"status": "error", "error": str(e)}
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
