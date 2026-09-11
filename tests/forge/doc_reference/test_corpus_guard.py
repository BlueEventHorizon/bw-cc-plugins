#!/usr/bin/env python3
"""未追随の形が本リポジトリの文書へ混入していないことを守る。

`ref_extract` は CommonMark の部分集合を実装しており、追随していない形が残っている
（`test_commonmark_conformance.py` の `KNOWN_DIFFERENCES`）。それらを実装しないと
決めた根拠は **本リポジトリの文書に出現しない**ことであって、正しいからではない。

**根拠は腐る。** 誰かが該当する形を書いた時点で、機構は誤検出または見逃しを起こす。
本テストはその混入を commit の時点で失敗として知らせる。「起きたら直す」を人の
注意に委ねず、CI に持たせるためにある。

失敗したときの選択肢は 2 つある。**書き方を変えて避ける**か、**その形を実装して
除外を外す**か。どちらを選ぶかは、その形を書いた人が決める。

検出器そのものが壊れていれば 0 件は無意味なので、`DetectorSelfTest` が各検出器を
既知の入力で発火させる。
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins" / "forge" / "scripts" / "doc_reference"))

import ref_normalize  # noqa: E402

#: 走査から外すもの。索引・キャッシュ・第三者のファイル
_EXCLUDED = ("/node_modules/", "/.git/", ".claude/doc-advisor/", ".claude/doc-db/")

_DEFN = re.compile(r"^ {0,3}\[(?:[^\[\]]|\\.)+\]:(.*)$")
_INDENTED_DEFN = re.compile(r"^ {1,3}\[(?:[^\[\]]|\\.)+\]:")
_CONTAINER_DEFN = re.compile(r"^ *(?:>|[-*+]|\d+[.)])\s+\[(?:[^\[\]]|\\.)+\]:")
_UNCLOSED_INLINE = re.compile(r"\]\([^)]*$")
_INLINE_DEST = re.compile(r"\]\(([^)]*)\)")
_ENTITY = re.compile(r"&[a-zA-Z][a-zA-Z0-9]*;|&#\d+;|&#[xX][0-9a-fA-F]+;")
_AUTOLINK = re.compile(r"<[a-zA-Z][a-zA-Z0-9+.-]*:[^ <>]*>")
_TITLE = re.compile(r"""^\s+(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|\((?:[^)\\]|\\.)*\))\s*$""")

#: CommonMark §2.4 がエスケープ対象とする ASCII 記号
_ESCAPABLE = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")

#: 検出する形と、実装していないことで起きる症状（`KNOWN_DIFFERENCES` の用例番号）
FORMS = {
    "inline の destination が行をまたぐ": "見逃し（用例 510）",
    "参照定義の destination が次の行にある": "見逃し（用例 193 / 195 / 198 / 541）",
    "参照定義の title がその行で閉じない": "誤検出（用例 197。空行をまたぐと定義でなくなる）",
    "コンテナの中の参照定義": "誤検出（用例 317）",
    "destination の中の実体参照": "誤検出（用例 32 / 33 / 503。解決せず文字どおり引く）",
    "destination の中のバックスラッシュ": "誤検出（用例 23 / 202 / 502。解決の可否が規格と違う）",
    "autolink と code span / 生 HTML の交錯": "双方（用例 346）",
}


def detect(raw_text: str, path: str = "x.md") -> dict:
    """未追随の形を探し、`{形: [場所, ...]}` を返す。"""
    found: dict = {}

    def hit(form, where):
        found.setdefault(form, []).append(where)

    normalized = list(ref_normalize.normalize(raw_text))
    raw_lines = raw_text.splitlines()
    for index, (lineno, line) in enumerate(normalized):
        raw = raw_lines[lineno - 1] if lineno - 1 < len(raw_lines) else ""

        if _UNCLOSED_INLINE.search(line):
            hit("inline の destination が行をまたぐ", f"{path}:{lineno}")

        for m in _INLINE_DEST.finditer(line):
            dest = m.group(1)
            if _ENTITY.search(dest):
                hit("destination の中の実体参照", f"{path}:{lineno} {dest!r}")
            if any(e.group(1) not in _ESCAPABLE for e in re.finditer(r"\\(.)", dest)):
                hit("destination の中のバックスラッシュ", f"{path}:{lineno} {dest!r}")

        # **交錯そのものを原本で見る。** 正規化はコードスパンを先に潰し、その範囲に
        # autolink の閉じ山括弧が含まれると autolink が見えなくなる（用例 346）。
        # また「同じ行に autolink とコードスパンがある」だけでは交錯ではないので、
        # autolink の内側にバッククォートがある場合に限る。
        for m in _AUTOLINK.finditer(raw):
            if "`" in m.group(0):
                hit("autolink と code span / 生 HTML の交錯", f"{path}:{lineno} {m.group(0)!r}")

        # 参照定義は**マスク前の行**で見る。正規化はコンテナのマーカーを空白へ
        # 落とすため、正規化後の行では `- [a]: /x` と `  [a]: /x` の区別が付かない
        if _CONTAINER_DEFN.match(raw) or _INDENTED_DEFN.match(raw):
            hit("コンテナの中の参照定義", f"{path}:{lineno}")
            continue
        d = _DEFN.match(line)
        if not d:
            continue
        rest = d.group(1)
        if not rest.strip():
            hit("参照定義の destination が次の行にある", f"{path}:{lineno}")
            continue
        after = rest.strip().split(None, 1)
        if len(after) == 2 and not _TITLE.match(" " + after[1]):
            hit("参照定義の title がその行で閉じない", f"{path}:{lineno} {after[1]!r}")
    return found


def markdown_files():
    for path in sorted(ROOT.rglob("*.md")):
        rel = str(path.relative_to(ROOT))
        if any(x in f"/{rel}" for x in _EXCLUDED):
            continue
        yield rel, path


class DetectorSelfTest(unittest.TestCase):
    """検出器が実際に発火することを確かめる。**0 件の報告はこれが無いと意味を持たない。**"""

    SAMPLES = {
        "inline の destination が行をまたぐ": '[link](   /uri\n  "title"  )\n',
        "参照定義の destination が次の行にある": "[foo]:\n/url\n\n[foo]\n",
        "参照定義の title がその行で閉じない": "[foo]: /url 'title\n",
        "コンテナの中の参照定義": "- a\n\n  [ref]: /url\n",
        "destination の中の実体参照": "[foo](/f&ouml;&ouml;.md)\n",
        "destination の中のバックスラッシュ": "[link](foo\\bar.md)\n",
        "autolink と code span / 生 HTML の交錯": "<https://foo.bar.`baz>`\n",
    }

    def test_every_form_has_a_sample(self):
        self.assertEqual(sorted(self.SAMPLES), sorted(FORMS))

    def test_each_detector_fires(self):
        for form, sample in self.SAMPLES.items():
            with self.subTest(form=form):
                self.assertIn(form, detect(sample))

    def test_ordinary_markdown_is_not_flagged(self):
        text = ("# 見出し\n\n本文と [表示名](docs/rules/foo.md) と `code`。\n\n"
                '[ref]: ../design/DES-001_x.md "題"\n\n- 箇条書きの [中](a.md)\n')
        self.assertEqual(detect(text), {})


class CorpusGuardTest(unittest.TestCase):
    def test_no_unsupported_form_is_written_in_this_repository(self):
        found: dict = {}
        for rel, path in markdown_files():
            for form, places in detect(path.read_text(encoding="utf-8"), rel).items():
                found.setdefault(form, []).extend(places)
        detail = "\n".join(
            f"  {form}（{FORMS[form]}）\n" + "\n".join(f"    {p}" for p in places)
            for form, places in sorted(found.items()))
        self.assertEqual(
            found, {},
            "本機構が追随していない形が書かれています。書き方を変えて避けるか、"
            f"その形を実装して除外を外してください:\n{detail}")

    def test_the_corpus_is_not_empty(self):
        """走査対象が消えていない（0 ファイルなら上のテストは何も守らない）。"""
        self.assertGreater(len(list(markdown_files())), 100)


if __name__ == "__main__":
    unittest.main()
