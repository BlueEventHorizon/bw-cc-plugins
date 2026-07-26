#!/usr/bin/env python3
"""JSON/TOML ファイルのバージョンフィールドを更新する。

元ファイルは書き換えない（NFR-01）。更新後の内容を stdout に出力する。
**ファイルへの書き戻しは呼び出し側ラッパー (update_main_version.py / update_*_filtered.py /
update_*_dependent.py) の責務である**（DES-024 §2.3.1 writer 例外類型 / Issue #139）。
本スクリプトを単独で使用する場合は、呼び出し側が stdout を必ずファイルへリダイレクト・Write すること。

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


class FilterNotFoundError(ValueError):
    """filter_pattern がファイル内に一度も出現しなかった場合（対象外）。"""


class VersionDriftError(ValueError):
    """バージョンフィールド（filter ブロックまたは version_path のフィールド）は
    見つかったが、その中に old_version が見つからなかった場合
    （ドリフト：バージョン不一致が蓄積している）。
    """


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
        # version_path の引用符を normalize（Issue #115 提案2）。
        # .version-config.yaml に version_path: "version" と書かれていても、
        # YAML パースを経ずに生文字列が渡る経路があるため防御する。
        version_path = version_path.strip().strip('\'"')
        if version_path == 'changelog_header':
            # CHANGELOG を canonical version source とするケース（Issue #115 提案3）
            return _update_changelog_header(content, old_version, new_version)
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


def _update_changelog_header(content, old_version, new_version):
    """CHANGELOG の最初の version 見出しを更新する（version_path: changelog_header）。

    `## [v?]X.Y.Z` / `## v?X.Y.Z`（keep-a-changelog / simple 双方）の最初の
    ヘッダ行にある version を置換する。先頭 `v` や角括弧 `[]` は保持する。

    Args:
        content: CHANGELOG テキスト
        old_version: 置換元バージョン（`v` 有無いずれも可）
        new_version: 置換先バージョン（数値 X.Y.Z 想定）

    Returns:
        str: 更新後のテキスト

    Raises:
        ValueError: 該当する version 見出しが見つからない
    """
    old_norm = old_version.strip().lstrip('vV')
    # group(1): 見出し接頭辞（"## [v" / "## v" / "## " 等）、group(2): 角括弧閉じ "]" 任意
    # `(?![\d.])`: version 末尾に境界を設け、`0.6.1` が `## [0.6.10]` を前方一致で
    # 破壊しないようにする（数字・ドットが続く場合はマッチさせない）。
    pattern = re.compile(
        r'^(##\s+\[?[vV]?)' + re.escape(old_norm) + r'(?![\d.])(\]?)',
        re.MULTILINE,
    )
    result, count = pattern.subn(
        lambda m: m.group(1) + new_version + m.group(2), content, count=1
    )
    if count == 0:
        raise ValueError(
            f"CHANGELOG ヘッダにバージョン '{old_version}' が見つかりません"
        )
    return result


def _update_with_path(content, old_version, new_version, version_path):
    """ネストパスを使ってバージョンフィールドを特定し置換する。

    version_path が "version" なら "version" キーの行を、
    "package.version" なら "package" ブロック内の "version" キーの行を特定する。
    """
    # 直接呼び出し経路でも引用符を normalize する（Issue #115 提案2）
    version_path = version_path.strip().strip('\'"')
    parts = version_path.split('.')
    field_name = parts[-1]  # 最終キー名

    # フィールド名を含む行を検索して置換。
    # `(?![\d.])`: version 末尾に境界を設け、old=`0.6.1` が `"0.6.10"` を前方一致で
    # 破壊しないようにする（数字・ドットが続く場合はマッチさせない）。
    # `\b`: field_name 直前に語境界を設け、"other_version" のような無関係なキーが
    # "version" にマッチしないようにする（単独修正レビューで検出）。
    pattern = re.compile(
        r'([\"\']?\b' + re.escape(field_name) + r'[\"\']?\s*[:=]\s*)[\"\']?'
        + re.escape(old_version) + r'(?![\d.])[\"\']?'
    )
    # フィールドの存在自体（値を問わない）を検出するパターン。
    # old_version 側のマッチに失敗した際、「フィールド自体が無い」（対象外）と
    # 「フィールドはあるが値が old_version と不一致」（ドリフト）を区別するために使う（Issue #175）。
    field_pattern = re.compile(
        r'[\"\']?\b' + re.escape(field_name) + r'[\"\']?\s*[:=]\s*[\"\']?[^\s\"\',}]+'
    )

    if len(parts) == 1:
        # トップレベルフィールド
        result, count = pattern.subn(lambda m: m.group(1) + f'"{new_version}"', content, count=1)
        if count == 0:
            if field_pattern.search(content):
                raise VersionDriftError(
                    f"フィールド '{version_path}' は存在しますが、バージョン '{old_version}' と"
                    "一致しません（ドリフト: 既存の値が現行バージョンと異なる可能性）"
                )
            raise ValueError(f"フィールド '{version_path}' にバージョン '{old_version}' が見つかりません")
        return result

    # ネストフィールド: 親キーチェーン（parts[:-1]）を先頭から順にたどり、
    # 各親キーの直後に開く `{` の対応 `}` までをスコープとして検索範囲を制限する。
    # 開始位置の前進だけではスコープ境界を見ないため、`b.package.version` が
    # 存在しなくても `b` より後方の別スコープ `package.version` を誤更新できてしまう
    # （Issue #180）。親キーの値がオブジェクトでない・境界を特定できない場合は
    # 書き換えずエラーに倒す。置換自体はテキスト操作のまま。
    start, end = 0, len(content)
    for parent_key in parts[:-1]:
        parent_pattern = re.compile(r'[\"\']?\b' + re.escape(parent_key) + r'[\"\']?\s*[:=]?\s*\{')
        parent_match = parent_pattern.search(content, start, end)
        if not parent_match:
            raise ValueError(
                f"親キー '{parent_key}' のオブジェクトブロックが見つかりません"
                f"（version_path: '{version_path}'）"
            )
        open_pos = parent_match.end() - 1
        close_pos = _find_matching_brace(content, open_pos)
        if close_pos is None or close_pos > end:
            raise ValueError(
                f"親キー '{parent_key}' のブロック境界を特定できません"
                f"（version_path: '{version_path}'）"
            )
        start, end = parent_match.end(), close_pos

    sub_content = content[start:end]
    result, count = pattern.subn(lambda m: m.group(1) + f'"{new_version}"', sub_content, count=1)

    if count == 0:
        if field_pattern.search(sub_content):
            raise VersionDriftError(
                f"フィールド '{version_path}' は存在しますが、バージョン '{old_version}' と"
                "一致しません（ドリフト: 既存の値が現行バージョンと異なる可能性）"
            )
        raise ValueError(f"フィールド '{version_path}' にバージョン '{old_version}' が見つかりません")

    return content[:start] + result + content[end:]


def _find_matching_brace(content, open_pos):
    """open_pos の `{` に対応する `}` の位置を返す。見つからなければ None。

    ダブルクォート文字列内の波括弧はネストとして数えない
    （JSON / TOML basic string の `\\"` エスケープを考慮する）。
    """
    depth = 0
    in_string = False
    i = open_pos
    n = len(content)
    while i < n:
        c = content[i]
        if in_string:
            if c == '\\':
                i += 2
                continue
            if c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


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
    filter_found = False

    for line in lines:
        if filter_pattern in line:
            # 新しい filter マッチ: カウンタをリセットしてブロック開始
            in_block = True
            filter_found = True
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
        if not filter_found:
            raise FilterNotFoundError(
                f"フィルタ '{filter_pattern}' がファイル内に見つかりません（対象外）"
            )
        raise VersionDriftError(
            f"フィルタ '{filter_pattern}' のブロック内にバージョン '{old_version}' が"
            f"見つかりません（ドリフト: 既存の値が現行バージョンと異なる可能性）"
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
        if args.optional:
            # optional モード: ファイル不在は対象外（DES-023 §5.2 「sync_file 不在 + optional: true → スキップ」）
            warning = {"status": "skipped", "file": args.file_path, "reason": f"File not found: {args.file_path}"}
            print(json.dumps(warning, ensure_ascii=False, indent=2), file=sys.stderr)
            sys.exit(0)
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
    except VersionDriftError as e:
        # ドリフト（フィルタは見つかったがバージョン不一致）: optional でも
        # status: skipped と区別し、呼び出し元が気付けるよう明示する
        warning = {"status": "drift", "file": args.file_path, "reason": str(e)}
        print(json.dumps(warning, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(0 if args.optional else 1)
    except FilterNotFoundError as e:
        if args.optional:
            # optional モード: 対象外（フィルタ自体が無い）は従来通り skipped
            warning = {"status": "skipped", "file": args.file_path, "reason": str(e)}
            print(json.dumps(warning, ensure_ascii=False, indent=2), file=sys.stderr)
            sys.exit(0)
        error = {"status": "error", "error": str(e)}
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        if args.optional:
            # optional モード: その他のパターン未マッチは警告扱いで exit 0
            warning = {"status": "skipped", "file": args.file_path, "reason": str(e)}
            print(json.dumps(warning, ensure_ascii=False, indent=2), file=sys.stderr)
            sys.exit(0)
        error = {"status": "error", "error": str(e)}
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
