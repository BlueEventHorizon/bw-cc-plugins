#!/usr/bin/env python3
"""ref_extract.py のテスト（REQ-023 FNC-002/FNC-004/FNC-005・DES-081 §6）。

本テストが固定するのは、実際の走査で取りこぼし・誤検出を起こした形である。
近似実装で壊れた箇所（4 連フェンス・二重バッククォート・参照リンク・CLI 引数の
誤認）を回帰として残す。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "plugins" / "forge" / "scripts" / "doc_reference"))

import ref_extract  # noqa: E402


class TestStripCodeSpans(unittest.TestCase):
    def test_single_backtick(self):
        self.assertEqual(ref_extract.strip_code_spans("a `x` b"), "a  b")

    def test_double_backtick_span_is_removed(self):
        """二重バッククォートも開始と同数で閉じる（近似実装が失敗した形）。"""
        line = "前 `` [x](nope.md) `` 後"
        self.assertNotIn("nope.md", ref_extract.strip_code_spans(line))

    def test_unclosed_run_is_kept(self):
        self.assertIn("`", ref_extract.strip_code_spans("a ` b"))

    def test_inner_shorter_run_does_not_close(self):
        """二重で開いた span は単一では閉じない。"""
        self.assertNotIn("keep", ref_extract.strip_code_spans("`` a ` keep `` z"))


class TestFences(unittest.TestCase):
    def test_four_backtick_fence_not_closed_by_three(self):
        """4 連で開いたフェンスは 3 連では閉じない（近似実装が失敗した形）。"""
        text = "````markdown\n```\n[x](inside.md)\n```\n````\n[y](outside.md)\n"
        got = [d for _, d in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["outside.md"])

    def test_tilde_fence(self):
        text = "~~~\n[x](inside.md)\n~~~\n[y](outside.md)\n"
        got = [d for _, d in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["outside.md"])

    def test_closing_fence_must_not_have_info_string(self):
        """info string を持つ行は閉じフェンスにならない。"""
        text = "```\n[x](a.md)\n```python\n[y](b.md)\n```\n[z](c.md)\n"
        got = [d for _, d in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["c.md"])

    def test_honor_fences_false_scans_everything(self):
        text = "```\n[x](inside.md)\n```\n"
        got = [d for _, d in ref_extract.extract_links(text, honor_fences=False)["inline"]]
        self.assertEqual(got, ["inside.md"])


class TestInlineLinks(unittest.TestCase):
    def test_image_and_link(self):
        got = [d for _, d in ref_extract.extract_links("![a](i.png) と [b](d.md)")["inline"]]
        self.assertEqual(got, ["i.png", "d.md"])

    def test_html_comment_excluded(self):
        text = "<!-- [x](commented.md) -->\n[y](real.md)\n"
        got = [d for _, d in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["real.md"])

    def test_angle_bracket_destination_is_reported_as_out_of_scope(self):
        """宣言外の形は黙って落とさず skipped で返す（NFR-001）。"""
        res = ref_extract.extract_links("[x](<p with space.md>)")
        self.assertEqual(res["inline"], [])
        self.assertEqual(len(res["skipped"]), 1)
        self.assertIn("山括弧囲み", res["skipped"][0][1])


class TestReferenceLinks(unittest.TestCase):
    def test_definition_and_use(self):
        text = "本文は [表示][lbl] を使う。\n\n[lbl]: ./target.md\n"
        res = ref_extract.extract_links(text)
        self.assertEqual([l for _, l in res["ref_uses"]], ["lbl"])
        self.assertEqual([(l, d) for _, l, d in res["ref_defs"]], [("lbl", "./target.md")])

    def test_cli_argument_list_is_not_a_reference_link(self):
        """`[feature] [--mode a|b]` を参照リンクと誤認しない（実データで出た誤検出）。"""
        text = "/forge:start-requirements [feature] [--mode interactive|reverse-engineering]"
        self.assertEqual(ref_extract.extract_links(text)["ref_uses"], [])

    def test_definition_inside_fence_is_ignored(self):
        text = "```\n[lbl]: ./x.md\n```\n"
        self.assertEqual(ref_extract.extract_links(text)["ref_defs"], [])


class TestSpecRefs(unittest.TestCase):
    def test_section_reference(self):
        self.assertEqual(
            ref_extract.find_spec_refs("詳細は DES-075 §6.1 が定める"),
            [(1, "DES-075", "6.1")],
        )

    def test_namespaced_id_is_not_split(self):
        """`COMMON-DES-001` から `DES-001` を切り出さない。"""
        self.assertEqual(
            [c for _, c, _ in ref_extract.find_spec_refs("COMMON-DES-001 §3.4")],
            ["COMMON-DES-001"],
        )

    def test_fence_excluded(self):
        self.assertEqual(ref_extract.find_spec_refs("```\nDES-075 §1\n```\n"), [])


class TestHeadingSectionNumbers(unittest.TestCase):
    def test_numbers_are_collected(self):
        text = "# T\n## 1. 概要\n### 3.1 一覧\n### 5.1a 例外\n#### 3.1.1 詳細\n## 用語\n"
        self.assertEqual(
            ref_extract.heading_section_numbers(text),
            {"1", "3.1", "5.1a", "3.1.1"},
        )

    def test_heading_inside_fence_ignored(self):
        self.assertEqual(ref_extract.heading_section_numbers("```\n## 9. x\n```\n"), set())


if __name__ == "__main__":
    unittest.main()
