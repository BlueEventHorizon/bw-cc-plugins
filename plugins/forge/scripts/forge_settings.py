#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`.claude/.forge.yaml`（forge プロジェクト設定ファイル）の共有読み取りモジュール。

forge の挙動をプロジェクト単位で調整する任意の設定ファイルを読む。
各 script が独自に `.forge.yaml` をパースせず、読み取りは本モジュールへ一元化する。

## 公開 I/F（これ以外は非公開）

| 関数                          | 返り値                                                               |
| ----------------------------- | -------------------------------------------------------------------- |
| `load(project_root)`          | ファイル全体の dict（不在なら空 dict）。解析不能なら `SettingsError` |
| `section(project_root, name)` | 当該セクションの dict（不在・ファイル不在なら空 dict）。同上         |

## 対応する構文（制約付き YAML サブセット）

- ネストした mapping（スペースインデント）
- スカラー（文字列・整数・真偽値。それ以外は文字列のまま返す）
- 文字列リスト（`- item` 形式のブロックスタイルのみ）
- コメント行・行内コメント（`#`）・空行

アンカー・エイリアス（`&` / `*`）、複数行文字列（`|` / `>`）、flow style
（`[...]` / `{...}`）は対象外であり、出現した場合はファイル全体を解析不能として扱う。

## エラーの扱い

- **ファイル不在は正常**（設定なし＝既定動作）。エラーにも警告にもしない。
- **解析不能は `SettingsError`**。読めない設定を黙って無視して既定動作へ落ちると、
  利用者が意図した調整と異なる挙動で静かに動き続けるためである。
  エラーメッセージには「何行目付近が解析できないか」を含め、設定本文は含めない
  （設定値そのものをエラー経路へ流さない）。
- **値域の検証は行わない**。本モジュールは構文だけを扱い、各セクションの
  キー・許容値・既定値・不正値時の挙動は、そのセクションを所有する利用側が定める。

## 依存

Python 標準ライブラリのみ。
"""

from __future__ import annotations

from pathlib import Path

# --- 定数 ---------------------------------------------------------------------

#: project root からの設定ファイルの相対位置
SETTINGS_RELATIVE_PATH = Path(".claude") / ".forge.yaml"

#: エラーメッセージに使うファイルの表示名（本文・絶対パスは載せない）
_DISPLAY_NAME = ".claude/.forge.yaml"

#: quote されていない値の先頭に現れたら対象外構文とみなす文字
_UNSUPPORTED_VALUE_PREFIXES = (
    ("&", "アンカー"),
    ("*", "エイリアス"),
    ("|", "複数行文字列"),
    (">", "複数行文字列"),
    ("[", "flow style"),
    ("{", "flow style"),
)


# --- 例外 ---------------------------------------------------------------------


class SettingsError(Exception):
    """`.claude/.forge.yaml` を解析できなかった。

    ファイル不在は本例外ではない（不在は正常であり空 dict を返す）。
    メッセージには行位置と理由だけを含め、設定本文は含めない。
    """


# --- 公開 I/F -----------------------------------------------------------------


def load(project_root) -> dict:
    """設定ファイル全体を dict で返す。

    ファイルが存在しない場合は空 dict を返す（エラー・警告なし）。
    解析不能な場合は `SettingsError` を送出する。
    """
    settings_path = Path(project_root) / SETTINGS_RELATIVE_PATH
    try:
        content = settings_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except UnicodeDecodeError:
        raise SettingsError(
            f"{_DISPLAY_NAME} を UTF-8 テキストとして読み取れません"
        ) from None
    except OSError as exc:
        # 不在以外の読取失敗（権限不備・ディレクトリである等）を未捕捉のまま
        # 漏らさない。利用側は SettingsError だけを設定不正として扱う契約のため、
        # ここで正規化する。メッセージには例外種別のみ載せ、本文・絶対パスは
        # 含めない
        raise SettingsError(
            f"{_DISPLAY_NAME} を読み取れません（{type(exc).__name__}）"
        ) from None
    return _parse(content)


def section(project_root, name: str) -> dict:
    """指定セクションの dict を返す。

    セクション不在・ファイル不在は空 dict を返す。
    ファイルが解析不能な場合は `SettingsError` を送出する。
    セクションが mapping 以外（リスト・スカラー）で書かれている場合も
    `SettingsError` とする。dict を返す契約を満たせない形を黙って空 dict へ
    丸めると、利用者の設定が静かに無視されるためである。
    """
    data = load(project_root)
    value = data.get(name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SettingsError(
            f"{_DISPLAY_NAME} のセクション '{name}' が mapping として書かれていません"
        )
    return value


# --- パーサ内部 -----------------------------------------------------------------


class _Frame:
    """解析中のコンテナ 1 つ（mapping または list）。

    `indent` はコンテナ直下の要素行のインデント幅。最初の要素行で確定する
    （None は未確定）。以降の要素は同じ幅でなければならない。
    """

    __slots__ = ("indent", "container")

    def __init__(self, container):
        self.indent = None
        self.container = container


def _error(lineno: int, reason: str) -> SettingsError:
    """行位置つきの解析エラーを組み立てる。設定本文は含めない。"""
    return SettingsError(
        f"{_DISPLAY_NAME} の {lineno} 行目付近を解析できません: {reason}"
    )


def _parse(content: str) -> dict:
    """制約付き YAML サブセットを行ベースで解析して dict を返す。"""
    root = {}
    root_frame = _Frame(root)
    root_frame.indent = 0
    stack = [root_frame]
    # 値が未確定の `key:` 行。(行番号, インデント, キー, 親 dict)
    pending = None

    for lineno, raw_line in enumerate(content.split("\n"), start=1):
        line = raw_line.rstrip()
        stripped = line.strip()

        # コメント行・空行は無視する
        if not stripped or stripped.startswith("#"):
            continue

        leading = line[: len(line) - len(line.lstrip())]
        if "\t" in leading:
            raise _error(lineno, "インデントにタブは使えません")
        indent = len(leading)

        # 未確定の `key:` に子ブロックが続くかを確定する
        if pending is not None:
            p_lineno, p_indent, p_key, p_parent = pending
            if indent > p_indent:
                # この行が子ブロックの最初の要素。list か mapping かをここで決める
                container = [] if _is_list_item(stripped) else {}
                p_parent[p_key] = container
                frame = _Frame(container)
                frame.indent = indent
                stack.append(frame)
            else:
                # 子を持たない `key:` は空値とする
                p_parent[p_key] = None
            pending = None

        # デデント: 現在のインデントに一致するフレームまで戻る
        while len(stack) > 1 and indent < stack[-1].indent:
            stack.pop()
        frame = stack[-1]
        if indent != frame.indent:
            raise _error(lineno, "インデントの幅が周囲の構造と一致しません")

        if isinstance(frame.container, list):
            if not _is_list_item(stripped):
                raise _error(
                    lineno, "リストの中に mapping の行が混在しています"
                )
            frame.container.append(_parse_list_item(stripped, lineno))
        else:
            if _is_list_item(stripped):
                raise _error(
                    lineno, "mapping の中にリスト要素の行が混在しています"
                )
            key, value_text = _split_key_value(stripped, lineno)
            if value_text is None:
                pending = (lineno, indent, key, frame.container)
            else:
                frame.container[key] = _parse_scalar(value_text, lineno)

    # EOF: 子を持たなかった `key:` は空値とする
    if pending is not None:
        _, _, p_key, p_parent = pending
        p_parent[p_key] = None

    return root


def _is_list_item(stripped: str) -> bool:
    """行がリスト要素（`- item`）か判定する。"""
    return stripped == "-" or stripped.startswith("- ")


def _parse_list_item(stripped: str, lineno: int) -> str:
    """リスト要素の行を文字列として解析する。

    本サブセットのリストは**文字列リスト**に限る。要素が mapping の形
    （`- key: value`）やネストを要求する形（`-` 単独）は対象外とする。
    数値・真偽値に見える要素も文字列のまま返す（文字列リストの契約を保つ）。
    """
    if stripped == "-":
        raise _error(
            lineno, "値のないリスト要素（ネストしたリスト・mapping）は対象外です"
        )
    item_text = stripped[2:].strip()
    if not item_text or item_text.startswith("#"):
        raise _error(
            lineno, "値のないリスト要素（ネストしたリスト・mapping）は対象外です"
        )
    if item_text[0] in ('"', "'"):
        return _parse_quoted(item_text, lineno)
    text = _strip_inline_comment(item_text)
    for prefix, syntax_name in _UNSUPPORTED_VALUE_PREFIXES:
        if text.startswith(prefix):
            raise _error(lineno, f"対象外の構文（{syntax_name}）は解析できません")
    if text.endswith(":") or ": " in text:
        raise _error(lineno, "mapping をリスト要素にする構文は対象外です")
    return text


def _split_key_value(stripped: str, lineno: int):
    """mapping の行を `(key, 値テキスト | None)` に分解する。

    値テキスト None は「値なし（子ブロックまたは空値）」を表す。
    quote された値の中身を壊さないため、コメント除去は行全体では行わず、
    分解後の値側（`_parse_scalar`）に委ねる。
    """
    key_text, sep, rest = stripped.partition(": ")
    if sep:
        value_text = rest.strip()
        if not value_text or value_text.startswith("#"):
            # `key:  # comment` のように値がコメントだけの行は値なしと同じ
            value_text = None
    elif stripped.endswith(":"):
        key_text = stripped[:-1]
        value_text = None
    else:
        raise _error(
            lineno,
            "mapping の行（`key: value` または `key:`）として解析できません",
        )
    key = key_text.strip().strip("\"'")
    if not key:
        raise _error(lineno, "キーが空です")
    if any(key.startswith(prefix) for prefix, _ in _UNSUPPORTED_VALUE_PREFIXES):
        raise _error(lineno, "対象外の構文がキーに使われています")
    return key, value_text


def _parse_scalar(value_text: str, lineno: int):
    """スカラー値を解析する（文字列・整数・真偽値）。

    quote されていない値の先頭がアンカー・エイリアス・複数行文字列・
    flow style を示す場合は対象外構文として解析不能にする。
    """
    value_text = value_text.strip()

    if value_text.startswith('"') or value_text.startswith("'"):
        return _parse_quoted(value_text, lineno)

    value_text = _strip_inline_comment(value_text)

    for prefix, syntax_name in _UNSUPPORTED_VALUE_PREFIXES:
        if value_text.startswith(prefix):
            raise _error(lineno, f"対象外の構文（{syntax_name}）は解析できません")

    if value_text.lower() == "true":
        return True
    if value_text.lower() == "false":
        return False
    try:
        return int(value_text)
    except ValueError:
        pass
    return value_text


def _parse_quoted(value_text: str, lineno: int) -> str:
    """quote された値を解析する。quote 後に許すのはコメントだけ。"""
    quote = value_text[0]
    closing = value_text.find(quote, 1)
    if closing < 0:
        raise _error(lineno, "引用符が閉じていません")
    rest = value_text[closing + 1 :].strip()
    if rest and not rest.startswith("#"):
        raise _error(lineno, "引用符の後に解析できない文字列が続いています")
    return value_text[1:closing]


def _strip_inline_comment(text: str) -> str:
    """行内コメント（空白に続く `#`）を除去する。

    quote で始まる値は `_parse_quoted` 側で扱うため、ここへは来ない前提で
    単純に「空白 + `#`」以降を切り落とす。値の途中に空白なしで現れる `#` は
    値の一部として保持する。
    """
    for i, ch in enumerate(text):
        if ch == "#" and i > 0 and text[i - 1] in (" ", "\t"):
            return text[:i].rstrip()
    return text.strip()
