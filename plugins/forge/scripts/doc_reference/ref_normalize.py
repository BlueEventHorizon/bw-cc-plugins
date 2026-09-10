#!/usr/bin/env python3
"""文書を参照として読める形へ正規化し、原本への位置写像を返す（DES-081 §3.1a）。

**参照として読まない範囲の除去を、この 1 段にまとめる。** 抽出・突合・置換は正規化された
テキストだけを見る。変形が抽出の途中へ散らばると、「いまこの桁は原本のどこか」を答えられる
モジュールが存在しなくなり、置換が位置を使えなくなる。

**正規化は長さを保存する。** 参照として読まない範囲は削除せず、同じ長さの伏字へ置き換える。
削除すると以降の桁が原本とずれ、置換が文字列一致に落ちる——それは一意でないキーによる探索で
あり、参照切れより有害な誤接続を作る（DES-081 §3.3.1・REQ-023 FNC-013）。

タブの展開だけは長さが変わるため、その分を位置写像が吸収する。**タブは異常ではない**。
CommonMark がブロック構造を決める文脈でタブ幅 4 として振る舞うと定めており、正当な入力である。

伏せる対象（いずれも CommonMark が「参照として解釈しない」と定める範囲）:

- フェンスコードブロック・インデントコードブロック・コードスパン
- HTML ブロック（7 type すべて）・HTML コメント

空白へ置き換える対象（構造の記号であって内容ではないもの）:

- 引用符 `>` の接頭辞・リストマーカー

**バックスラッシュエスケープは伏せない。** エスケープされた文字は destination の内容にも
なり得る（`[a](foo\\(bar\\).md)` は `foo(bar).md` を指す）ため、伏せると正しい参照を壊す。
エスケープの解釈は抽出側のパーサが行う。

`honor_fences=False` は参照元が Markdown でない場合（実装コード・テスト）に渡す。この場合
ブロック構造を解釈せず、タブも展開しない（コードのインデントをインデントコードブロックと
解釈すると、コメント中の節参照が丸ごと落ちる。REQ-023 FNC-005 の見逃し）。
"""

from __future__ import annotations

import re

#: 参照として読まない範囲を伏せる文字。リンク記法・文書 ID のいずれにも現れない
MASK = "\x00"

TAB_WIDTH = 4

# 行頭 0〜3 スペース + 3 個以上の同一フェンス文字 + info string
FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
_BLOCKQUOTE = re.compile(r"^ {0,3}> ?")
_LIST_MARKER = re.compile(r"^([-*+]|\d{1,9}[.)])([ \t]+|$)")
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


class NormalizedLine:
    """1 行分の正規化結果。

    Attributes:
        lineno: 原本の行番号（1 始まり）
        text: 正規化後の行
        cols: `text` の桁 → 原本の行内位置（0 始まり）。単調非減少
    """

    __slots__ = ("lineno", "text", "cols")

    def __init__(self, lineno: int, text: str, cols: list):
        self.lineno = lineno
        self.text = text
        self.cols = cols

    def raw_span(self, start: int, end: int):
        """正規化上の範囲 `[start, end)` を原本の行内範囲へ写す（DES-081 §3.1a.1）。

        写像は単調非減少なので、返る範囲は必ず連続する。`end` が行末を超える呼び出しは
        呼び出し側の誤りであり、そのまま例外にする（黙って丸めると誤った範囲を書き換える）。
        """
        if start < 0 or end > len(self.cols) or start >= end:
            raise ValueError(f"範囲が行の外にある: [{start}, {end}) / 行長 {len(self.cols)}")
        return self.cols[start], self.cols[end - 1] + 1


class Normalized:
    """文書全体の正規化結果。

    原本の行と 1 対 1 で対応する（正規化は行を増やさず減らさない）。
    """

    __slots__ = ("lines", "raw_lines")

    def __init__(self, lines: list, raw_lines: list):
        self.lines = lines
        self.raw_lines = raw_lines

    def __iter__(self):
        """`(行番号, 正規化後の行)` を返す。位置を要さない利用のための形。"""
        for line in self.lines:
            yield line.lineno, line.text


def _expand_tabs(raw: str):
    """タブを展開し、`(展開後の行, 桁 → 原本の行内位置)` を返す。

    展開後の連続する桁は、すべて元のタブ 1 文字を指す（DES-081 §3.1a.1）。
    """
    out: list = []
    cols: list = []
    for i, ch in enumerate(raw):
        if ch == "\t":
            width = TAB_WIDTH - (len(out) % TAB_WIDTH)
            out.extend(" " * width)
            cols.extend([i] * width)
            continue
        out.append(ch)
        cols.append(i)
    return "".join(out), cols


def _mask_range(chars: list, start: int, end: int, fill: str = MASK) -> None:
    """`chars[start:end]` を `fill` で埋める（長さを変えない）。"""
    for i in range(start, min(end, len(chars))):
        chars[i] = fill


def _mask_code_spans(chars: list) -> None:
    """コードスパンを伏せる。開始の連続バッククォート数と同数の並びで閉じる。

    二重バッククォート（`` `code` `` の形）も同じ規則で扱える。閉じが見つからない並びは
    そのまま残す（CommonMark §6.1 と同じ扱い）。
    """
    i, n = 0, len(chars)
    while i < n:
        if chars[i] != "`":
            i += 1
            continue
        j = i
        while j < n and chars[j] == "`":
            j += 1
        run = j - i
        k, closed = j, -1
        while k < n:
            if chars[k] == "`":
                m = k
                while m < n and chars[m] == "`":
                    m += 1
                if m - k == run:
                    closed = m
                    break
                k = m
            else:
                k += 1
        if closed > 0:
            _mask_range(chars, i, closed)
            i = closed
            continue
        i = j


def _html_block_end(stripped: str, in_paragraph: bool):
    """HTML ブロックの開始条件に当たれば、その終端条件を返す（CommonMark §4.6 の 7 type）。"""
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


def normalize(text: str, *, honor_fences: bool = True) -> Normalized:
    """文書を正規化し、原本への位置写像を添えて返す（DES-081 §3.1a.2）。

    ブロック構造の状態（フェンスの開閉・HTML ブロックの継続・インデントコードブロック・
    コンテナの内容インデント）を持ちながら、先頭から 1 度走査する。構造判定と伏字を同じ
    パスで行うのは、構造判定にタブ展開後の桁が必要であり、伏字の範囲もその桁で決まるため
    である。

    **閉じないまま文書が終わったフェンス・HTML ブロックは、開いた時点から末尾までを伏せる**
    （CommonMark が未閉のフェンスを文書末で閉じるものとして扱うのと同じ）。状態を持ち越す
    ことで自然にそうなる。
    """
    raw_lines = text.splitlines()
    lines: list = []

    if not honor_fences:
        # ブロック構造を解釈しない。タブも展開しない（桁は原本と一致する）
        for lineno, raw in enumerate(raw_lines, 1):
            chars = list(raw)
            _mask_code_spans(chars)
            lines.append(NormalizedLine(lineno, "".join(chars), list(range(len(raw)))))
        return Normalized(lines, raw_lines)

    open_fence = None
    html_end = None
    in_inline_comment = False
    in_indented_code = False
    container_indent = 0
    prev_blank = True
    in_paragraph = False

    for lineno, raw in enumerate(raw_lines, 1):
        expanded, cols = _expand_tabs(raw)
        chars = list(expanded)

        def emit(masked_all: bool = False):
            if masked_all:
                _mask_range(chars, 0, len(chars))
            lines.append(NormalizedLine(lineno, "".join(chars), cols))

        # 引用符の接頭辞は構造の記号であって内容ではない。空白へ落とす
        pos = 0
        while True:
            m = _BLOCKQUOTE.match(expanded, pos)
            if not m:
                break
            _mask_range(chars, m.start(), m.end(), " ")
            pos = m.end()
        line = " " * pos + expanded[pos:]
        blank = not line.strip()

        # 継続中の HTML ブロック（CommonMark §4.6）
        if html_end is not None:
            if html_end is _ENDS_AT_BLANK:
                if blank:
                    html_end = None
                    prev_blank, in_paragraph = True, False
            elif html_end.search(line):
                html_end = None
            emit(masked_all=True)
            continue

        # 継続中のフェンス（同 §4.5）
        if open_fence is not None:
            m = FENCE.match(line)
            if m:
                char, run, info = m.group(2)[0], len(m.group(2)), m.group(3).strip()
                if char == open_fence[0] and run >= open_fence[1] and not info:
                    open_fence = None
            prev_blank = False
            emit(masked_all=True)
            continue

        # 行をまたぐインラインコメント（行頭で始まらないため HTML ブロックにならない）
        if in_inline_comment:
            end = line.find("-->")
            if end < 0:
                emit(masked_all=True)
                continue
            _mask_range(chars, 0, end + 3)
            line = " " * (end + 3) + line[end + 3:]
            in_inline_comment = False
            blank = not line.strip()

        if blank:
            # インデントコードブロックは空行では閉じない（同 §4.4）
            prev_blank, in_paragraph = True, False
            emit()
            continue

        indent = len(line) - len(line.lstrip(" "))
        if indent < container_indent:
            container_indent = indent
        stripped = line[indent:]
        rel = indent - container_indent

        if in_indented_code:
            if rel >= 4:
                prev_blank = False
                emit(masked_all=True)
                continue
            in_indented_code = False

        m = FENCE.match(line)
        if m and rel < 4:
            open_fence = (m.group(2)[0], len(m.group(2)))
            prev_blank, in_paragraph = False, False
            emit(masked_all=True)
            continue

        # インデントコードブロックは段落を中断できない（同 §4.4）
        if rel >= 4 and prev_blank and not in_paragraph:
            in_indented_code = True
            prev_blank = False
            emit(masked_all=True)
            continue

        if rel < 4:
            end = _html_block_end(stripped, in_paragraph)
            if end is not None:
                html_end = None if (end is not _ENDS_AT_BLANK and end.search(stripped)) else end
                prev_blank, in_paragraph = False, False
                emit(masked_all=True)
                continue

        # コンテナの内容インデントを更新する（同 §5）。マーカーは空白へ落とす
        lm = _LIST_MARKER.match(stripped)
        if lm and rel < 4:
            container_indent = indent + len(lm.group(0))
            _mask_range(chars, indent, container_indent, " ")

        # 1 行で閉じないインラインコメントを検出し、以降を持ち越す
        for cm in re.finditer(r"<!--.*?-->", "".join(chars), re.S):
            _mask_range(chars, cm.start(), cm.end())
        start = "".join(chars).find("<!--")
        if start >= 0:
            _mask_range(chars, start, len(chars))
            in_inline_comment = True

        _mask_code_spans(chars)

        prev_blank = False
        in_paragraph = not (
            stripped.startswith("#") or bool(lm) or bool(_THEMATIC_BREAK.match(stripped))
        )
        emit()

    return Normalized(lines, raw_lines)
