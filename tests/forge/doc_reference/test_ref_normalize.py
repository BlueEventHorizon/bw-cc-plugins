#!/usr/bin/env python3
"""ref_normalize.py のテスト（DES-081 §3.1a・§6.2）。

**位置の往復が壊れていないことに置換の正しさが乗る。** 正規化テキストの桁を位置写像で
戻したとき原本の同じ文字を指さなければ、置換は別の場所を書き換える。長さの保存と往復を
最初に固定する。

コードスパンの回帰（二重バッククォート・未閉の並び）は、前処理が伏せる範囲の判定として
ここに残す。近似実装が失敗した形である。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[3] / "plugins" / "forge" / "scripts" / "doc_reference")
)

import ref_normalize  # noqa: E402

MASK = ref_normalize.MASK


def _line(text, lineno=1, **kw):
    return ref_normalize.normalize(text, **kw).lines[lineno - 1]


class TestLengthIsPreserved(unittest.TestCase):
    """伏せた範囲の長さが変わらないこと（DES-081 §3.1a）。"""

    def test_code_span_keeps_the_line_length(self):
        raw = "前 `[x](nope.md)` 後"
        got = _line(raw)
        self.assertEqual(len(got.text), len(raw))
        self.assertEqual(len(got.cols), len(raw))

    def test_masked_range_holds_no_reference(self):
        got = _line("前 `[x](nope.md)` 後")
        self.assertNotIn("nope.md", got.text)

    def test_double_backtick_span_is_masked(self):
        """二重バッククォートも開始と同数で閉じる（近似実装が失敗した形）。"""
        got = _line("前 `` [x](nope.md) `` 後")
        self.assertNotIn("nope.md", got.text)

    def test_unclosed_run_is_kept(self):
        self.assertIn("`", _line("a ` b").text)

    def test_inner_shorter_run_does_not_close(self):
        """二重で開いた span は単一では閉じない。"""
        self.assertNotIn("keep", _line("`` a ` keep `` z").text)

    def test_fence_body_is_masked_without_dropping_the_line(self):
        norm = ref_normalize.normalize("```\n[x](a.md)\n```\n")
        self.assertEqual(len(norm.lines), 3)
        self.assertNotIn("a.md", norm.lines[1].text)
        self.assertEqual(len(norm.lines[1].text), len("[x](a.md)"))


class TestPositionMapRoundTrip(unittest.TestCase):
    """正規化上の桁を戻すと原本の同じ文字を指すこと（DES-081 §3.1a.1）。"""

    def _assert_round_trip(self, raw):
        norm = ref_normalize.normalize(raw)
        for line in norm.lines:
            source = norm.raw_lines[line.lineno - 1]
            self.assertEqual(len(line.cols), len(line.text))
            for i, ch in enumerate(line.text):
                col = line.cols[i]
                self.assertLess(col, len(source))
                if ch not in (MASK, " "):
                    self.assertEqual(source[col], ch, f"桁 {i} が原本を指していない")

    def test_plain_line(self):
        self._assert_round_trip("本文 [a](x.md) と [b](y.md)\n")

    def test_line_with_tabs(self):
        """タブがある行でも原本の桁を返すこと。タブは異常な入力ではない。"""
        self._assert_round_trip("本文\t[a](x.md) と\t[b](y.md)\n")

    def test_leading_tab_makes_an_indented_code_block(self):
        """行頭のタブは 4 桁のインデントであり、CommonMark ではコードブロックになる。

        参照として読まないのが正しい（旧実装と同じ判定）。タブの扱いは CommonMark が
        定めるものであり、本機構が独自に決めない。
        """
        self.assertNotIn("x.md", _line("\t[a](x.md)").text)

    def test_blockquote_and_list(self):
        self._assert_round_trip("> - 引用の中の [a](x.md)\n")

    def test_span_of_a_destination_points_at_the_original(self):
        raw = "本文\t[a](old/target.md)"
        line = _line(raw)
        start = line.text.index("old/target.md")
        raw_start, raw_end = line.raw_span(start, start + len("old/target.md"))
        self.assertEqual(raw[raw_start:raw_end], "old/target.md")

    def test_range_outside_the_line_is_rejected(self):
        """範囲外の要求を黙って丸めない（丸めると誤った範囲を書き換える）。"""
        line = _line("短い行")
        with self.assertRaises(ValueError):
            line.raw_span(0, 999)


class TestNonMarkdownInput(unittest.TestCase):
    """`honor_fences=False` はブロック構造を解釈せず、桁が原本と一致すること。"""

    def test_indented_code_is_not_assumed(self):
        raw = "    # DES-081 §3.1 を参照\n"
        got = _line(raw, honor_fences=False)
        self.assertIn("DES-081", got.text)
        self.assertEqual(got.cols, list(range(len(raw.rstrip("\n")))))


if __name__ == "__main__":
    unittest.main()
