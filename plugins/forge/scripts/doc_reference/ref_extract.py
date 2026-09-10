#!/usr/bin/env python3
"""正規化テキストから参照を、原本の位置つきで抽出する（REQ-023 FNC-002 / FNC-005）。

本モジュールの責務は**抽出だけ**である。参照先が実在するかの判定（索引の構築と突合）は
持たず、**参照として読まない範囲の除去も持たない**——それは前処理（`ref_normalize`）が
1 段で済ませている（DES-081 §3.1a）。ブロック構造の状態機械を本モジュールへ戻してはならない。
戻すと位置の対応を答えられるモジュールが無くなり、置換が文字列一致に落ちる。

扱うのは層 1（この記述は参照か）だけである。何が参照かの正本は CommonMark である。
**解決規則を持つかどうかは層 2 の事情であり、抽出段階で落とさない**（DES-081 §1.3）。

参照として抽出する形:

- インラインリンク `[表示名](destination)` / 画像 `![alt](destination)`（CommonMark §6.3 / §6.4）。
  destination は素の形・山括弧囲み・title 付き・釣り合った括弧を含む形のいずれでもよい
- autolink `<https://...>`（同 §6.5）
- 参照リンクの定義行 `[ラベル]: パス` と使用 `[表示名][ラベル]`（同 §4.7）
- 文書 ID の節参照（`find_spec_refs()`。CommonMark の範囲外）

**抽出した destination には原本の行内範囲を添える。** 置換はこの範囲だけを差し替える
（DES-081 §4.3.2）。範囲を持たずに文字列だけを渡すと、同一ファイル内で別の参照の部分
文字列に当たり、参照切れより有害な誤接続を作る。

`honor_fences=False` は参照元が Markdown でない場合（実装コード・テスト）に渡す。前処理へ
そのまま渡され、ブロック構造の解釈が行われない——コードのインデントをインデントコード
ブロックと解釈すると、コメント中の節参照が丸ごと落ちる（FNC-005 の見逃し）。
"""

from __future__ import annotations

import html
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ref_normalize  # noqa: E402

# 参照リンクの定義行と使用（CommonMark §4.7）
REF_DEF = re.compile(r"^ {0,3}\[((?:[^\[\]]|\\.)+)\]:\s*(<[^>]*>|\S+)")
REF_USE = re.compile(r"!?\[((?:[^\[\]]|\\.)*)\]\[((?:[^\[\]]|\\.)*)\]")
SPEC_REF = re.compile(
    r"(?<![A-Za-z0-9-])((?:[A-Z]+-)*[A-Z]+-\d+)\s*§\s*(\d+(?:\.\d+)*[a-z]?)"
)
# CLI 引数の並び（`[feature] [--mode a|b]`）を参照リンクの使用と誤認しないための除外。
# 参照リンクのラベルに `|` や先頭 `-` は現れない。
_NOT_A_LABEL = re.compile(r"[|]|^-")

# §6.5 Autolinks: scheme は英字始まり 2〜32 文字、内側に空白と山括弧を含まない
AUTOLINK = re.compile(r"<[A-Za-z][A-Za-z0-9+.\-]{1,31}:[^<>\x00-\x20]*>")


def _closing_bracket(s: str, start: int) -> int:
    """`s[start]` の `[` に対応する `]` の位置を返す（釣り合った角括弧を許す）。"""
    depth, i, n = 0, start, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _parse_destination(s: str, i: int):
    """`s[i]` の `(` から destination と title を読む（§6.3）。

    Returns:
        `(destination, 閉じ括弧の次の位置, destination の開始位置, destination の終了位置)`。
        リンクとして成立しない場合は `None`。位置は山括弧・エスケープを含む**原文上の範囲**
        であり、`destination` はエスケープを解いた値である。置換はこの範囲を差し替える。
    """
    n, j = len(s), i + 1
    while j < n and s[j] in " \t":
        j += 1
    if j < n and s[j] == "<":
        buf, k = [], j + 1
        span_start = j + 1
        while k < n and s[k] not in "><":
            if s[k] == "\\" and k + 1 < n:
                buf.append(s[k + 1])
                k += 2
                continue
            buf.append(s[k])
            k += 1
        if k >= n or s[k] != ">":
            return None
        dest, span_end, j = "".join(buf), k, k + 1
    else:
        buf, depth, k = [], 0, j
        span_start = j
        while k < n:
            c = s[k]
            if c == "\\" and k + 1 < n:
                buf.append(s[k + 1])
                k += 2
                continue
            if c in " \t":
                break
            if c == "(":
                depth += 1
            elif c == ")":
                if depth == 0:
                    break
                depth -= 1
            buf.append(c)
            k += 1
        if depth != 0:
            return None
        dest, span_end, j = "".join(buf), k, k
    while j < n and s[j] in " \t":
        j += 1
    if j < n and s[j] in "\"'(":
        close = {'"': '"', "'": "'", "(": ")"}[s[j]]
        k = j + 1
        while k < n and s[k] != close:
            k += 2 if s[k] == "\\" else 1
        if k >= n:
            return None
        j = k + 1
        while j < n and s[j] in " \t":
            j += 1
    if j < n and s[j] == ")":
        return dest, j + 1, span_start, span_end
    return None


def _scan_inline(line: str) -> list:
    """インラインリンク・画像・autolink の destination を出現順に返す。

    Returns:
        list: `(destination, 行内の開始位置, 行内の終了位置)`。位置は destination 自身の
        範囲であり、囲みの記号（`(` `)` や山括弧）を含まない。**置換はこの範囲だけを
        差し替える**（DES-081 §4.3.2）。
    """
    out: list = []
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c == "\\":
            i += 2
            continue
        if c == "<":
            m = AUTOLINK.match(line, i)
            if m:
                out.append((m.group(0)[1:-1], m.start() + 1, m.end() - 1))
                i = m.end()
                continue
            i += 1
            continue
        if c == "[" or (c == "!" and i + 1 < n and line[i + 1] == "["):
            b = i + 1 if c == "!" else i
            close = _closing_bracket(line, b)
            if close < 0:
                i = b + 1
                continue
            if close + 1 < n and line[close + 1] == "(":
                parsed = _parse_destination(line, close + 1)
                if parsed is not None:
                    dest, end, dest_start, dest_end = parsed
                    out.append((dest, dest_start, dest_end))
                    i = end
                    continue
            i = b + 1
            continue
        i += 1
    return out


def extract_links(text: str, *, honor_fences: bool = True) -> dict:
    """リンク参照を、**原本の位置つきで**抽出する（DES-081 §4.3.1）。

    参照として読まない範囲の除去は前処理（`ref_normalize`）が済ませている。本関数は
    正規化テキストだけを見て、抽出した範囲を前処理の位置写像で原本の桁へ戻す。**変換は
    ここで 1 度だけ行う**——2 か所で変換すると二重変換か変換漏れが必ず起きる。

    Returns:
        dict: `inline`（`(行番号, destination, 原本の開始桁, 原本の終了桁)`）/
        `ref_defs`（`(行番号, ラベル, destination, 原本の開始桁, 原本の終了桁)`）/
        `ref_uses`（`(行番号, ラベル)`）/ `skipped`（`(行番号, 宣言外の形, 原文)`）

    位置は destination 自身の範囲であり、囲みの記号やラベルを含まない。**参照定義行でも
    パスの範囲だけを返す**（行全体を返すと、置換でラベル定義が消える）。

    `skipped` は層 1 で参照として成立しなかった形のために残す枠である。準拠する規定に
    到達している限り空になる。**解決規則を持たない形をここへ入れない**——それは層 2 の
    判定不能であり、`check_refs` が報告する（DES-081 §1.2）。
    """
    inline: list = []
    ref_defs: list = []
    ref_uses: list = []
    skipped: list = []
    for nline in ref_normalize.normalize(text, honor_fences=honor_fences).lines:
        line = nline.text
        for dest, start, end in _scan_inline(line):
            if start >= end:
                # 空の destination は位置を持たない（層 2 が判定不能として報告する）
                inline.append((nline.lineno, dest, None, None))
                continue
            raw_start, raw_end = nline.raw_span(start, end)
            inline.append((nline.lineno, dest, raw_start, raw_end))
        md = REF_DEF.match(line)
        if md:
            start, end = md.span(2)
            dest = md.group(2)
            # 山括弧囲みは中身が destination である。位置も中身に合わせる
            if dest.startswith("<") and dest.endswith(">"):
                start, end, dest = start + 1, end - 1, dest[1:-1]
            if start < end:
                raw_start, raw_end = nline.raw_span(start, end)
            else:
                raw_start, raw_end = None, None
            ref_defs.append(
                (nline.lineno, md.group(1).strip().lower(), dest, raw_start, raw_end)
            )
        for mu in REF_USE.finditer(line):
            label = (mu.group(2) or mu.group(1)).strip()
            if not label or _NOT_A_LABEL.search(label):
                continue
            ref_uses.append((nline.lineno, label.lower()))
    return {"inline": inline, "ref_defs": ref_defs, "ref_uses": ref_uses, "skipped": skipped}


def find_spec_refs(text: str, *, honor_fences: bool = True) -> list:
    """文書 ID の節参照 `DES-001 §3.4` を抽出する（REQ-023 FNC-002）。

    Returns:
        list: `(行番号, 文書 ID, 節番号)`
    """
    found: list = []
    for lineno, line in ref_normalize.normalize(text, honor_fences=honor_fences):
        for m in SPEC_REF.finditer(line):
            found.append((lineno, m.group(1), m.group(2)))
    return found


def heading_plain_text(title: str) -> str:
    """見出しの Markdown 原文を plain text へ落とす（DES-081 §5.2.1）。

    アンカーの変換に渡すのは**原文ではなく plain text** である。原文を渡すと
    リンクや実体参照を含む見出しで外部のレンダラとずれる。

    落とす記法: リンク・画像（表示テキストを残す）/ autolink（URL を残す）/
    コードスパン（中身を残す）/ 生の HTML タグ / 実体参照 / バックスラッシュ
    エスケープ。**強調記法は落とさない**——`*` は変換で結果的に消え、`_` は
    変換後も残る文字であるため、判定を誤ると `snake_case` の見出しを壊す。
    """
    s = title
    s = re.sub(r"!?\[((?:[^\[\]]|\\.)*)\]\([^)]*\)", r"\1", s)  # リンク・画像
    s = re.sub(r"!?\[((?:[^\[\]]|\\.)*)\]\[[^\]]*\]", r"\1", s)  # 参照リンクの使用
    s = AUTOLINK.sub(lambda m: m.group(0)[1:-1], s)  # autolink は URL を残す
    s = re.sub(r"(`+)(.+?)\1", r"\2", s)  # コードスパンは中身を残す
    s = re.sub(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^>]*)?/?>", "", s)  # 生の HTML タグ
    s = html.unescape(s)  # 実体参照
    s = re.sub(r"\\(.)", r"\1", s)  # バックスラッシュエスケープ
    return s


def slugify_heading(title: str, seen: dict | None = None) -> str:
    """見出しの plain text をアンカー文字列へ変換する（DES-081 §5.2.1）。

    正本は外部機構が持つ規則である（本設計書で新設していない）。連続ハイフンは
    圧縮せず、同一 slug の 2 回目以降に連番を付ける。生成した候補が既存の slug と
    衝突した場合はカウンタを進める。
    """
    s = unicodedata.normalize("NFC", title).strip().lower()
    s = s.replace(" ", "-")
    s = re.sub(r"[^\w\-]", "", s, flags=re.UNICODE)
    if seen is None:
        return s
    count = seen.get(s, 0)
    if count == 0:
        seen[s] = 1
        return s
    candidate = f"{s}-{count}"
    while candidate in seen:
        count += 1
        candidate = f"{s}-{count}"
    seen[s] = count + 1
    seen[candidate] = 1
    return candidate


def heading_slugs(text: str) -> set:
    """ATX 見出しのアンカー文字列の集合を返す。

    列挙するのは ATX 見出しだけである（外部機構の現在の実装と一致させる。
    DES-081 §5.2.1）。setext 見出し・コンテナ内の見出しは列挙範囲が未決であり、
    その有無は `has_unenumerated_heading_forms()` が別に答える。
    """
    heading = re.compile(r"^#{1,6}\s+(.*?)(?:\s+#+)?\s*$")
    seen: dict = {}
    out = set()
    for _, line in ref_normalize.normalize(text):
        h = heading.match(line)
        if h:
            out.add(slugify_heading(heading_plain_text(h.group(1)), seen))
    return out


def has_unenumerated_heading_forms(text: str) -> bool:
    """列挙範囲外の見出しが書かれうる形が 1 つでもあるかを返す（DES-081 §3.3c.1）。

    真であれば、アンカーが索引に当たらないことを参照の誤りと断定できない
    （列挙漏れの可能性を排除できない）。
    """
    open_fence = None
    prev_content = False
    container = False
    for raw in text.splitlines():
        line = raw.expandtabs(4)
        m = ref_normalize.FENCE.match(line)
        if m:
            char, run, info = m.group(2)[0], len(m.group(2)), m.group(3).strip()
            if open_fence is None:
                open_fence = (char, run)
            elif char == open_fence[0] and run >= open_fence[1] and not info:
                open_fence = None
            prev_content = False
            continue
        if open_fence is not None:
            continue
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if not stripped:
            prev_content = False
            container = False
            continue
        # setext 見出しの下線（段落の直後に限る）
        if prev_content and re.fullmatch(r"(?:=+|-+)", stripped):
            return True
        # コンテナ（リスト・引用）の中の ATX 見出し
        if ref_normalize._LIST_MARKER.match(stripped) \
                or ref_normalize._BLOCKQUOTE.match(line):
            container = True
        elif indent == 0:
            container = False
        if container and re.match(r"^#{1,6}\s", stripped):
            return True
        prev_content = True
    return False


def heading_section_numbers(text: str) -> set:
    """見出しの先頭にある節番号の集合を返す（節参照の突合に使う）。

    `## 3. 概要` → `3`、`### 3.1 モジュール一覧` → `3.1`、`### 5.1a ...` → `5.1a`。
    """
    heading = re.compile(r"^#{1,6}\s+(.*)$")
    secnum = re.compile(r"^(\d+(?:\.\d+)*[a-z]?)[.\s]")
    out = set()
    for _, line in ref_normalize.normalize(text):
        h = heading.match(line)
        if h:
            s = secnum.match(h.group(1).strip())
            if s:
                out.add(s.group(1))
    return out
