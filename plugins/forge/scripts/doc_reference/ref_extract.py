#!/usr/bin/env python3
"""文書・コードから参照を抽出する（REQ-023 FNC-002 / FNC-004 / FNC-005・DES-081 §3.1）。

本モジュールの責務は**抽出だけ**である。参照先が実在するかの判定（索引の構築と突合）は
持たない（DES-081 §3.1 の責務分離。実在の範囲は FNC-003 が索引側に課す制約であり、
参照でないものの除外は FNC-004 が抽出側に課す制約で、別の場所に効く）。

**対応する形を宣言し、宣言外は `skipped` として返す**（REQ-023 NFR-001。黙って落とさない）。

対応する形:

- インラインリンク `[表示名](パス)` / 画像 `![alt](パス)`
- 参照リンクの定義行 `[ラベル]: パス` と使用 `[表示名][ラベル]`
- 文書 ID の節参照 `DES-001 §3.4`（`find_spec_refs()`）
- 除外: コードフェンス（3 個以上、`` ` `` / `~`。**開始と同じ文字・同じ個数以上でのみ閉じる**）、
  コードスパン（**開始の連続バッククォート数と同数で閉じる**）、HTML コメント

宣言外（`skipped` として報告し、判定しない）:

- 山括弧囲みの destination `[x](<path with space.md>)`
- 括弧を含む destination・タイトル付き destination
- エスケープされた角括弧・4 スペースインデントのコードブロック・HTML の `<a href>`

フェンスとコードスパンの規則を近似で実装すると、取りこぼしと誤検出の両方が出る
（4 連フェンスの中の 3 連で誤って閉じる／二重バッククォート内の例示を本物の参照として拾う）。
規則どおりに実装することが、そのまま NFR-001 の両方向を守ることになる。
"""

from __future__ import annotations

import re

# 行頭 0〜3 スペース + 3 個以上の同一フェンス文字 + info string
FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
INLINE_LINK = re.compile(r"!?\[(?:[^\[\]]|\\.)*\]\(\s*(<[^>]*>|[^\s)]*)")
REF_DEF = re.compile(r"^ {0,3}\[((?:[^\[\]]|\\.)+)\]:\s*(<[^>]*>|\S+)")
REF_USE = re.compile(r"!?\[((?:[^\[\]]|\\.)*)\]\[((?:[^\[\]]|\\.)*)\]")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
SPEC_REF = re.compile(
    r"(?<![A-Za-z0-9-])((?:[A-Z]+-)*[A-Z]+-\d+)\s*§\s*(\d+(?:\.\d+)*[a-z]?)"
)
# CLI 引数の並び（`[feature] [--mode a|b]`）を参照リンクの使用と誤認しないための除外。
# 参照リンクのラベルに `|` や先頭 `-` は現れない。
_NOT_A_LABEL = re.compile(r"[|]|^-")


def strip_code_spans(line: str) -> str:
    """コードスパンを除去する。開始の連続バッククォート数と同数の並びで閉じる。

    二重バッククォート（`` `code` `` の形）も同じ規則で扱える。閉じが見つからない
    並びはそのまま残す（CommonMark と同じ扱い）。
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


def _iter_body_lines(text: str, honor_fences: bool):
    """フェンス内を飛ばしながら (行番号, コードスパン除去後の行) を返す。"""
    open_fence = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        if honor_fences:
            m = FENCE.match(raw)
            if m:
                char, run, info = m.group(2)[0], len(m.group(2)), m.group(3).strip()
                if open_fence is None:
                    open_fence = (char, run)
                    continue
                # 閉じるのは同じ文字・同じ個数以上・info string なしのときだけ
                if char == open_fence[0] and run >= open_fence[1] and not info:
                    open_fence = None
                    continue
            if open_fence is not None:
                continue
        yield lineno, strip_code_spans(HTML_COMMENT.sub("", raw))


def extract_links(text: str, *, honor_fences: bool = True) -> dict:
    """リンク参照を抽出する。

    Returns:
        dict: `inline`（`(行番号, destination)`）/ `ref_defs`（`(行番号, ラベル, destination)`）
        / `ref_uses`（`(行番号, ラベル)`）/ `skipped`（`(行番号, 宣言外の形, 原文)`）
    """
    inline: list = []
    ref_defs: list = []
    ref_uses: list = []
    skipped: list = []
    for lineno, line in _iter_body_lines(text, honor_fences):
        for m in INLINE_LINK.finditer(line):
            dest = m.group(1)
            if dest.startswith("<"):
                skipped.append((lineno, "山括弧囲み destination", dest))
            else:
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
