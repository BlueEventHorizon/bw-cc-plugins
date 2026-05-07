#!/usr/bin/env python3
"""セッション YAML の読み書きユーティリティ。

フラット・ネスト（リスト+オブジェクト）両方の YAML を標準ライブラリのみで処理する。
session/ 配下の全スクリプトがこのモジュールを共有する。

PyYAML 等の外部依存は使用しない（NFR-02 準拠）。
"""

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# スカラー値のエスケープ
# ---------------------------------------------------------------------------

# クォートが必要な特殊文字
_SPECIAL_CHARS = frozenset(
    ": # { } [ ] , & * ? | - < > = ! % @ `".split()
)


def yaml_scalar(v):
    """Python 値を YAML 安全な文字列に変換する。

    Args:
        v: 変換対象の値（bool / int / str）

    Returns:
        str: YAML 表現
    """
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    s = str(v)
    needs_quote = any(c in s for c in _SPECIAL_CHARS)
    if needs_quote or " " in s:
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if not s:
        return '""'
    return s


# ---------------------------------------------------------------------------
# 書き込み: フラット YAML
# ---------------------------------------------------------------------------

def write_flat_yaml(path, data, field_order=None):
    """フラットな dict を YAML として書き出す。

    Args:
        path: 出力ファイルパス
        data: dict（値はスカラーのみ）
        field_order: 先頭に出力するフィールド順序（省略時はアルファベット順）
    """
    lines = []
    if field_order:
        ordered = [k for k in field_order if k in data]
        remaining = sorted(k for k in data if k not in field_order)
        ordered += remaining
    else:
        ordered = sorted(data.keys())
    for key in ordered:
        lines.append(f"{key}: {yaml_scalar(data[key])}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def atomic_write_text(path, content):
    """同一ディレクトリ内の一時ファイル経由でテキストを原子的に書く。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(target))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# 書き込み: ネスト YAML（リスト+オブジェクト対応）
# ---------------------------------------------------------------------------

def write_nested_yaml(path, sections):
    """ネスト構造を YAML として書き出す。

    Args:
        path: 出力ファイルパス
        sections: list[tuple[str, value]] — 順序付きキー・値ペア

    value の型で出力を切り替え:
      - str / int / bool → ``key: value``
      - list[str] → 文字列リスト
      - list[dict] → オブジェクトリスト（dict 内のキー順序は保持）
      - None / 空リスト → スキップ
    """
    lines = _build_nested_lines(sections)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_nested_yaml_text(sections):
    """ネスト構造を YAML テキストとして返す（ファイル書き出しなし）。

    Args:
        sections: list[tuple[str, value]]

    Returns:
        str: YAML テキスト
    """
    lines = _build_nested_lines(sections)
    return "\n".join(lines) + "\n"


def _build_nested_lines(sections):
    """sections から YAML 行リストを生成する。"""
    lines = []
    for key, value in sections:
        if value is None:
            continue
        if isinstance(value, list):
            if not value:
                continue
            lines.append(f"{key}:")
            if value and isinstance(value[0], dict):
                _append_object_list(lines, value)
            else:
                _append_string_list(lines, value)
        else:
            lines.append(f"{key}: {yaml_scalar(value)}")
        # セクション間に空行
        lines.append("")
    # 末尾の余分な空行を除去
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def _append_string_list(lines, items):
    """文字列リストを ``  - item`` 形式で追加する。"""
    for item in items:
        lines.append(f"  - {yaml_scalar(item)}")


def _append_object_list(lines, items):
    """オブジェクトリストを ``  - key: val`` 形式で追加する。

    dict 内の値が list の場合はインライン配列 ``[a, b, c]`` として出力する。
    """
    for item in items:
        first = True
        for k, v in item.items():
            if v is None or (isinstance(v, (list, str)) and not v):
                continue
            prefix = "  - " if first else "    "
            if isinstance(v, list):
                inline = "[" + ", ".join(yaml_scalar(x) for x in v) + "]"
                lines.append(f"{prefix}{k}: {inline}")
            else:
                lines.append(f"{prefix}{k}: {yaml_scalar(v)}")
            first = False


# ---------------------------------------------------------------------------
# 読み込み: 汎用 YAML パーサー（フラット+リスト自動判定）
# ---------------------------------------------------------------------------

def read_yaml(path):
    """YAML ファイルを読み込んで dict に変換する。

    フラット YAML もリスト付き YAML も統一的に扱う。

    Args:
        path: YAML ファイルパス

    Returns:
        dict: パース結果
    """
    content = Path(path).read_text(encoding="utf-8")
    return parse_yaml(content)


def parse_yaml(content):
    """YAML テキストをパースして dict に変換する。

    Args:
        content: YAML テキスト

    Returns:
        dict: パース結果
    """
    result = {}
    lines = content.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        indent = len(line) - len(line.lstrip())

        # トップレベルの key: value
        if indent == 0 and ":" in stripped and not stripped.startswith("- "):
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()

            if value:
                if value.startswith("[") and value.endswith("]"):
                    result[key] = _parse_inline_array(value)
                else:
                    result[key] = _parse_scalar(value)
                i += 1
            else:
                child_items, consumed = _parse_list_or_block(
                    lines, i + 1, parent_indent=0
                )
                result[key] = child_items
                i += 1 + consumed
        else:
            i += 1

    return result


# ---------------------------------------------------------------------------
# 読み込み: 内部パーサー
# ---------------------------------------------------------------------------

def _parse_list_or_block(lines, start_idx, parent_indent):
    """子要素がリストかブロックかを判定してパースする。

    空行・コメント行は読み飛ばして最初の有意行を見る。
    先読み範囲は子要素全体(ブロック終端まで)。固定の行数制限は設けない
    — 大量のコメント / 空行が子要素の先頭にあっても誤って空リスト扱いに
    しないため。
    """
    for j in range(start_idx, len(lines)):
        line = lines[j]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= parent_indent:
            return [], 0
        if stripped.startswith("- "):
            return _parse_list_items(lines, start_idx, parent_indent)
        else:
            return _parse_dict_block(lines, start_idx, parent_indent)
    return [], 0


def _parse_list_items(lines, start_idx, parent_indent):
    """リスト要素をパースする。"""
    items = []
    i = start_idx
    current_item = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        indent = len(line) - len(line.lstrip())

        if indent <= parent_indent:
            break

        if stripped.startswith("- "):
            item_content = stripped[2:].strip()

            if ":" in item_content and not _is_quoted_value(item_content):
                # オブジェクト要素の開始
                if current_item is not None:
                    items.append(current_item)
                current_item = {}
                k, _, v = item_content.partition(":")
                k = k.strip()
                v = v.strip()
                if v:
                    current_item[k] = _parse_scalar(v)
                else:
                    child, consumed = _parse_list_or_block(
                        lines, i + 1, indent
                    )
                    current_item[k] = child
                    i += 1 + consumed
                    continue
            else:
                # 文字列要素
                if current_item is not None:
                    items.append(current_item)
                    current_item = None
                items.append(_parse_scalar(item_content))
            i += 1
        elif indent > parent_indent and current_item is not None:
            # オブジェクトのフィールド継続行
            if ":" in stripped and not stripped.startswith("- "):
                k, _, v = stripped.partition(":")
                k = k.strip()
                v = v.strip()
                if v:
                    if v.startswith("[") and v.endswith("]"):
                        current_item[k] = _parse_inline_array(v)
                    else:
                        current_item[k] = _parse_scalar(v)
                else:
                    child, consumed = _parse_list_or_block(
                        lines, i + 1, indent
                    )
                    current_item[k] = child
                    i += 1 + consumed
                    continue
            i += 1
        else:
            break

    if current_item is not None:
        items.append(current_item)

    return items, i - start_idx


def _parse_dict_block(lines, start_idx, parent_indent):
    """辞書ブロックをパースする。"""
    result = {}
    i = start_idx

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        indent = len(line) - len(line.lstrip())
        if indent <= parent_indent:
            break

        if ":" in stripped and not stripped.startswith("- "):
            k, _, v = stripped.partition(":")
            k = k.strip()
            v = v.strip()
            if v:
                result[k] = _parse_scalar(v)
            else:
                child, consumed = _parse_list_or_block(
                    lines, i + 1, indent
                )
                result[k] = child
                i += 1 + consumed
                continue
        i += 1

    return result, i - start_idx


def _parse_inline_array(value):
    """インライン配列 [a, b, c] をパースする。"""
    inner = value[1:-1].strip()
    if not inner:
        return []
    return [_parse_scalar(item.strip()) for item in inner.split(",")]


def _parse_scalar(value):
    """スカラー値をパースする（文字列、数値、真偽値）。

    ダブルクォート文字列内のエスケープシーケンス (`\\\\` / `\\"`) は
    復元する(`yaml_scalar` のエスケープ対応)。シングルクォート文字列は
    YAML 規約の `''` → `'` のみ復元する。
    """
    if not value:
        return ""
    # クォート除去 + エスケープ復元
    if len(value) >= 2:
        if value[0] == '"' and value[-1] == '"':
            return _unescape_double_quoted(value[1:-1])
        if value[0] == "'" and value[-1] == "'":
            return value[1:-1].replace("''", "'")
    # 真偽値
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    # 整数
    if value.lstrip("-").isdigit():
        return int(value)
    return value


def _unescape_double_quoted(s):
    """ダブルクォート内の `\\\\` / `\\"` を元の文字に復元する。

    `yaml_scalar` が行う `\\` → `\\\\`, `"` → `\\"` の逆変換。
    1 文字ずつ走査し、バックスラッシュ直後の文字を解釈する(途中で
    現れる単独のバックスラッシュを別のエスケープと誤解しないため)。
    """
    result = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "\\":
                result.append("\\")
                i += 2
                continue
            if nxt == '"':
                result.append('"')
                i += 2
                continue
        result.append(ch)
        i += 1
    return "".join(result)


def _is_quoted_value(text):
    """テキスト全体がクォートされた値かどうか判定する。"""
    stripped = text.strip()
    if len(stripped) >= 2:
        if stripped[0] == '"' and stripped[-1] == '"':
            return True
        if stripped[0] == "'" and stripped[-1] == "'":
            return True
    return False


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def now_iso():
    """UTC ISO 8601 タイムスタンプを生成する（Z 表記）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
