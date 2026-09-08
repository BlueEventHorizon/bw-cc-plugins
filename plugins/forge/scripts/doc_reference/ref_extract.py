#!/usr/bin/env python3
"""文書・コードから参照を抽出する（REQ-023 FNC-002 / FNC-004 / FNC-005・DES-081 §3.1）。

本モジュールの責務は**抽出だけ**である。参照先が実在するかの判定（索引の構築と突合）は
持たない（DES-081 §3.1 の責務分離）。

扱うのは層 1（この記述は参照か）だけである。何が参照かの正本は CommonMark であり、
準拠する規定は DES-081 §3.4 が列挙する。**解決規則を持つかどうかは層 2 の事情であり、
抽出段階で落とさない**（DES-081 §1.3）。

参照として抽出する形:

- インラインリンク `[表示名](destination)` / 画像 `![alt](destination)`（§6.3 / §6.4）。
  destination は素の形・山括弧囲み・title 付き・釣り合った括弧を含む形のいずれでもよい
- autolink `<https://...>`（§6.5）
- 参照リンクの定義行 `[ラベル]: パス` と使用 `[表示名][ラベル]`（§4.7）
- 文書 ID の節参照 `DES-001 §3.4`（`find_spec_refs()`。CommonMark の範囲外）

参照として解析しない範囲（いずれも CommonMark が定める）:

- フェンスコードブロック（§4.5）・インデントコードブロック（§4.4）・コードスパン（§6.1）
- HTML ブロック（§4.6）。**7 type すべて**を終端まで 1 ブロックとして扱う
- 生の HTML（§6.6）。`<a href="...">` は Markdown のリンクではない

**インデントコードブロックの判定はコンテナ相対である**（§5）。リスト項目の継続段落を
コードと見なすと本物の参照を落とす（見逃し）ため、コンテナの内容インデントを追う。

規則を近似で実装すると、取りこぼしと誤検出の両方が出る（4 連フェンスの中の 3 連で誤って
閉じる／二重バッククォート内の例示を本物の参照として拾う／リストの継続段落をコードと
見なす）。規則どおりに実装することが、そのまま NFR-001 の両方向を守ることになる。

`honor_fences=False` は参照元が Markdown でない場合（実装コード・テスト）に渡す。
このときブロック構造の解釈をすべて行わない——コードのインデントをインデント
コードブロックと解釈すると、コメント中の節参照が丸ごと落ちる（FNC-005 の見逃し）。
"""

from __future__ import annotations

import html
import re
import unicodedata

# 行頭 0〜3 スペース + 3 個以上の同一フェンス文字 + info string
FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
REF_DEF = re.compile(r"^ {0,3}\[((?:[^\[\]]|\\.)+)\]:\s*(<[^>]*>|\S+)")
REF_USE = re.compile(r"!?\[((?:[^\[\]]|\\.)*)\]\[((?:[^\[\]]|\\.)*)\]")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
SPEC_REF = re.compile(
    r"(?<![A-Za-z0-9-])((?:[A-Z]+-)*[A-Z]+-\d+)\s*§\s*(\d+(?:\.\d+)*[a-z]?)"
)
# CLI 引数の並び（`[feature] [--mode a|b]`）を参照リンクの使用と誤認しないための除外。
# 参照リンクのラベルに `|` や先頭 `-` は現れない。
_NOT_A_LABEL = re.compile(r"[|]|^-")

# §6.5 Autolinks: scheme は英字始まり 2〜32 文字、内側に空白と山括弧を含まない
AUTOLINK = re.compile(r"<[A-Za-z][A-Za-z0-9+.\-]{1,31}:[^<>\x00-\x20]*>")

_LIST_MARKER = re.compile(r"^([-*+]|\d{1,9}[.)])([ \t]+|$)")
_BLOCKQUOTE = re.compile(r"^ {0,3}> ?")
_THEMATIC_BREAK = re.compile(r"^(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$")

# §4.6 HTML blocks type 6 のタグ名（CommonMark が列挙する集合）
_BLOCK_TAGS = (
    "address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|"
    "details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|"
    "h1|h2|h3|h4|h5|h6|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|"
    "noframes|ol|optgroup|option|p|param|search|section|summary|table|tbody|td|tfoot|th|"
    "thead|title|tr|track|ul"
)
_T1_START = re.compile(r"^<(?:script|pre|style|textarea)(?:[ \t>]|$)", re.I)
_T1_END = re.compile(r"</(?:script|pre|style|textarea)>", re.I)
_T2_END = re.compile(r"-->")
_T3_END = re.compile(r"\?>")
_T4_START = re.compile(r"^<![A-Za-z]")
_T4_END = re.compile(r">")
_T5_END = re.compile(r"\]\]>")
_T6_START = re.compile(r"^</?(?:" + _BLOCK_TAGS + r")(?:[ \t]|/?>|$)", re.I)
_ATTR = r"[^\s\"'=<>`]+(?:\s*=\s*(?:[^\s\"'=<>`]+|'[^']*'|\"[^\"]*\"))?"
_T7_START = re.compile(
    r"^(?:<[A-Za-z][A-Za-z0-9-]*(?:\s+" + _ATTR + r")*\s*/?>|</[A-Za-z][A-Za-z0-9-]*\s*>)[ \t]*$"
)

# HTML ブロックが空行で閉じることを表す番兵（終端が正規表現で表せない type 6 / 7 用）
_ENDS_AT_BLANK = "blank"


def strip_code_spans(line: str) -> str:
    """コードスパンを除去する。開始の連続バッククォート数と同数の並びで閉じる。

    二重バッククォート（`` `code` `` の形）も同じ規則で扱える。閉じが見つからない
    並びはそのまま残す（CommonMark §6.1 と同じ扱い）。
    """
    out: list[str] = []
    i, n = 0, len(line)
    while i < n:
        if line[i] == "`":
            j = i
            while j < n and line[j] == "`":
                j += 1
            run = j - i
            k, closed = j, -1
            while k < n:
                if line[k] == "`":
                    m = k
                    while m < n and line[m] == "`":
                        m += 1
                    if m - k == run:
                        closed = m
                        break
                    k = m
                else:
                    k += 1
            if closed > 0:
                i = closed
                continue
            out.append(line[i:j])
            i = j
            continue
        out.append(line[i])
        i += 1
    return "".join(out)


def _html_block_end(stripped: str, in_paragraph: bool):
    """HTML ブロックの開始条件に当たれば、その終端条件を返す（§4.6 の 7 type）。"""
    if _T1_START.match(stripped):
        return _T1_END
    if stripped.startswith("<!--"):
        return _T2_END
    if stripped.startswith("<?"):
        return _T3_END
    if stripped.startswith("<![CDATA["):
        return _T5_END
    if _T4_START.match(stripped):
        return _T4_END
    if _T6_START.match(stripped):
        return _ENDS_AT_BLANK
    # type 7 だけは段落を中断できない
    if not in_paragraph and _T7_START.match(stripped):
        return _ENDS_AT_BLANK
    return None


def _iter_body_lines(text: str, honor_fences: bool):
    """参照として解析される行だけを (行番号, コードスパン除去後の行) で返す。

    `honor_fences` が偽のときはブロック構造を解釈せず、全行をそのまま返す。
    """
    open_fence = None
    html_end = None
    in_inline_comment = False
    in_indented_code = False
    container_indent = 0
    prev_blank = True
    in_paragraph = False

    for lineno, raw in enumerate(text.splitlines(), 1):
        if not honor_fences:
            yield lineno, strip_code_spans(raw)
            continue

        line = raw.expandtabs(4)
        while True:
            m = _BLOCKQUOTE.match(line)
            if not m:
                break
            line = line[m.end():]
        blank = not line.strip()

        # 継続中の HTML ブロック（§4.6）
        if html_end is not None:
            if html_end is _ENDS_AT_BLANK:
                if blank:
                    html_end = None
                    prev_blank, in_paragraph = True, False
            elif html_end.search(line):
                html_end = None
            continue

        # 継続中のフェンス（§4.5）
        if open_fence is not None:
            m = FENCE.match(line)
            if m:
                char, run, info = m.group(2)[0], len(m.group(2)), m.group(3).strip()
                if char == open_fence[0] and run >= open_fence[1] and not info:
                    open_fence = None
            prev_blank = False
            continue

        # 行をまたぐインラインコメント（行頭で始まらないため HTML ブロックにならない）
        if in_inline_comment:
            end = line.find("-->")
            if end < 0:
                continue
            line = line[end + 3:]
            in_inline_comment = False
            blank = not line.strip()

        if blank:
            # インデントコードブロックは空行では閉じない（§4.4）
            prev_blank, in_paragraph = True, False
            continue

        indent = len(line) - len(line.lstrip(" "))
        if indent < container_indent:
            container_indent = indent
        stripped = line[indent:]
        rel = indent - container_indent

        if in_indented_code:
            if rel >= 4:
                prev_blank = False
                continue
            in_indented_code = False

        m = FENCE.match(line)
        if m and rel < 4:
            open_fence = (m.group(2)[0], len(m.group(2)))
            prev_blank, in_paragraph = False, False
            continue

        # インデントコードブロックは段落を中断できない（§4.4）
        if rel >= 4 and prev_blank and not in_paragraph:
            in_indented_code = True
            prev_blank = False
            continue

        if rel < 4:
            end = _html_block_end(stripped, in_paragraph)
            if end is not None:
                html_end = None if (end is not _ENDS_AT_BLANK and end.search(stripped)) else end
                prev_blank, in_paragraph = False, False
                continue

        # コンテナの内容インデントを更新する（§5）
        lm = _LIST_MARKER.match(stripped)
        if lm and rel < 4:
            container_indent = indent + len(lm.group(0))
            line = " " * container_indent + stripped[lm.end():]

        # 1 行で閉じないインラインコメントを検出し、以降を持ち越す
        line = HTML_COMMENT.sub("", line)
        start = line.find("<!--")
        if start >= 0:
            line = line[:start]
            in_inline_comment = True

        prev_blank = False
        in_paragraph = not (
            stripped.startswith("#") or bool(lm) or bool(_THEMATIC_BREAK.match(stripped))
        )
        yield lineno, strip_code_spans(line)


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
        `(destination, 閉じ括弧の次の位置)`。リンクとして成立しない場合は `None`。
    """
    n, j = len(s), i + 1
    while j < n and s[j] in " \t":
        j += 1
    if j < n and s[j] == "<":
        buf, k = [], j + 1
        while k < n and s[k] not in "><":
            if s[k] == "\\" and k + 1 < n:
                buf.append(s[k + 1])
                k += 2
                continue
            buf.append(s[k])
            k += 1
        if k >= n or s[k] != ">":
            return None
        dest, j = "".join(buf), k + 1
    else:
        buf, depth, k = [], 0, j
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
        dest, j = "".join(buf), k
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
        return dest, j + 1
    return None


def _scan_inline(line: str) -> list:
    """インラインリンク・画像・autolink の destination を出現順に返す。"""
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
                out.append(m.group(0)[1:-1])
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
                    dest, end = parsed
                    out.append(dest)
                    i = end
                    continue
            i = b + 1
            continue
        i += 1
    return out


def extract_links(text: str, *, honor_fences: bool = True) -> dict:
    """リンク参照を抽出する。

    Returns:
        dict: `inline`（`(行番号, destination)`）/ `ref_defs`（`(行番号, ラベル, destination)`）
        / `ref_uses`（`(行番号, ラベル)`）/ `skipped`（`(行番号, 宣言外の形, 原文)`）

    `skipped` は層 1 で参照として成立しなかった形のために残す枠である。§3.4 が列挙した
    規定に到達している限り空になる。**解決規則を持たない形をここへ入れない**——それは
    層 2 の判定不能であり、`check_refs` が報告する（DES-081 §1.2）。
    """
    inline: list = []
    ref_defs: list = []
    ref_uses: list = []
    skipped: list = []
    for lineno, line in _iter_body_lines(text, honor_fences):
        for dest in _scan_inline(line):
            inline.append((lineno, dest))
        md = REF_DEF.match(line)
        if md:
            ref_defs.append((lineno, md.group(1).strip().lower(), md.group(2).strip("<>")))
        for mu in REF_USE.finditer(line):
            label = (mu.group(2) or mu.group(1)).strip()
            if not label or _NOT_A_LABEL.search(label):
                continue
            ref_uses.append((lineno, label.lower()))
    return {"inline": inline, "ref_defs": ref_defs, "ref_uses": ref_uses, "skipped": skipped}


def find_spec_refs(text: str, *, honor_fences: bool = True) -> list:
    """文書 ID の節参照 `DES-001 §3.4` を抽出する（REQ-023 FNC-002）。

    Returns:
        list: `(行番号, 文書 ID, 節番号)`
    """
    found: list = []
    for lineno, line in _iter_body_lines(text, honor_fences):
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
    for _, line in _iter_body_lines(text, True):
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
        m = FENCE.match(line)
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
        if _LIST_MARKER.match(stripped) or _BLOCKQUOTE.match(line):
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
    for _, line in _iter_body_lines(text, True):
        h = heading.match(line)
        if h:
            s = secnum.match(h.group(1).strip())
            if s:
                out.add(s.group(1))
    return out
