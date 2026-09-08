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
        """1 行に閉じた HTML コメント（CommonMark §4.6）。"""
        text = "<!-- [x](commented.md) -->\n[y](real.md)\n"
        got = [d for _, d in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["real.md"])

    def test_multiline_html_comment_excluded(self):
        """複数行にまたがる HTML コメントも終端まで 1 ブロック（CommonMark §4.6）。

        1 行の形だけを固定した試験は通るため、この形が欠けると覆いになる（DES-081 §6.1）。
        """
        text = "<!--\n[x](commented.md)\n-->\n[y](real.md)\n"
        got = [d for _, d in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["real.md"])

    def test_indented_code_block_is_not_a_link(self):
        """行頭 4 スペースはコードであり、中のリンクは解析しない（CommonMark §4.4）。"""
        text = "段落\n\n    [x](indented.md)\n\n[y](real.md)\n"
        got = [d for _, d in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["real.md"])

    def test_raw_html_anchor_is_not_a_link(self):
        """生の HTML は Markdown のリンクではない（CommonMark §6.6）。skipped にも入れない。"""
        res = ref_extract.extract_links('<a href="gone.md">x</a>\n[y](real.md)\n')
        self.assertEqual([d for _, d in res["inline"]], ["real.md"])
        self.assertEqual(res["skipped"], [])

    def test_angle_bracket_destination_is_a_link(self):
        """山括弧囲みは CommonMark §6.3 の正当な destination である。

        解決規則を持つかどうかは層 2 の事情であり、抽出段階で落とさない（DES-081 §1.3）。
        """
        res = ref_extract.extract_links("[x](<p with space.md>)")
        self.assertEqual([d for _, d in res["inline"]], ["p with space.md"])
        self.assertEqual(res["skipped"], [])

    def test_destination_with_title(self):
        """title 付き destination（CommonMark §6.3）。title は destination に含めない。"""
        got = [d for _, d in ref_extract.extract_links('[x](a.md "題")')["inline"]]
        self.assertEqual(got, ["a.md"])

    def test_destination_with_balanced_parens(self):
        """括弧を含む destination は釣り合っていれば destination の一部（CommonMark §6.3）。"""
        got = [d for _, d in ref_extract.extract_links("[x](a(b).md)")["inline"]]
        self.assertEqual(got, ["a(b).md"])

    def test_link_text_with_nested_brackets(self):
        """リンクテキストは釣り合った角括弧を含みうる（CommonMark §6.3）。"""
        got = [d for _, d in ref_extract.extract_links("[a [b] c](d.md)")["inline"]]
        self.assertEqual(got, ["d.md"])

    def test_autolink_is_extracted(self):
        """autolink は参照である（CommonMark §6.5）。層 2 で対象外になるのは別の話。"""
        got = [d for _, d in ref_extract.extract_links("<https://example.test/a>")["inline"]]
        self.assertEqual(got, ["https://example.test/a"])


class TestHtmlBlocks(unittest.TestCase):
    """CommonMark §4.6 は 7 type ある。コメント（type 2）だけでは足りない。"""

    def test_type6_block_tag_excluded(self):
        text = "<div>\n[x](gone.md)\n</div>\n\n[y](real.md)\n"
        got = [d for _, d in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["real.md"])

    def test_type1_pre_excluded(self):
        text = "<pre>\n[x](gone.md)\n</pre>\n\n[y](real.md)\n"
        got = [d for _, d in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["real.md"])

    def test_html_block_ends_at_blank_line(self):
        """type 6 は空行で閉じる。閉じた後のリンクは抽出する。"""
        text = "<div>\n[x](gone.md)\n\n[y](real.md)\n"
        got = [d for _, d in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["real.md"])


class TestIndentedCodeAndContainers(unittest.TestCase):
    """§4.4 の判定はコンテナ相対のインデントで決まる（§5）。除外し過ぎは見逃しになる。"""

    def test_list_continuation_paragraph_is_not_code(self):
        """リスト項目の継続段落はコードではない。抽出する。"""
        text = "- 項目\n\n    継続の [x](a.md)\n"
        got = [d for _, d in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["a.md"])

    def test_nested_list_item_is_not_code(self):
        text = "- 項目\n    - 入れ子の [x](a.md)\n"
        got = [d for _, d in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["a.md"])

    def test_code_block_inside_list_item_is_excluded(self):
        """コンテナ相対で 4 スペース以上ならコードである。"""
        text = "- 項目\n\n      [x](gone.md)\n\n[y](real.md)\n"
        got = [d for _, d in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["real.md"])

    def test_indented_line_cannot_interrupt_a_paragraph(self):
        """段落の直後の 4 スペース行はコードにならない（CommonMark §4.4）。"""
        text = "段落\n    継続の [x](a.md)\n"
        got = [d for _, d in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["a.md"])

    def test_block_quote_content_is_scanned(self):
        text = "> 引用の [x](a.md)\n"
        got = [d for _, d in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["a.md"])


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


class TestSlugifyHeading(unittest.TestCase):
    """アンカーの変換規則。正本は外部機構が持つ（DES-081 §5.2.1）。"""

    def test_number_and_japanese(self):
        self.assertEqual(ref_extract.slugify_heading("1. 全体方針"), "1-全体方針")

    def test_fullwidth_punctuation_is_removed(self):
        self.assertEqual(
            ref_extract.slugify_heading("Step 1: 対象ノードの特定（resolve）"),
            "step-1-対象ノードの特定resolve",
        )

    def test_consecutive_hyphens_are_not_collapsed(self):
        self.assertEqual(ref_extract.slugify_heading("A & B"), "a--b")

    def test_duplicates_get_a_counter(self):
        seen: dict = {}
        self.assertEqual(ref_extract.slugify_heading("概要", seen), "概要")
        self.assertEqual(ref_extract.slugify_heading("概要", seen), "概要-1")
        self.assertEqual(ref_extract.slugify_heading("概要", seen), "概要-2")

    def test_link_in_heading_uses_display_text(self):
        """slugify の入力は Markdown 原文ではなく plain text である（§5.2.1）。"""
        self.assertEqual(ref_extract.slugify_heading(
            ref_extract.heading_plain_text("[Alpha](docs/a.md)")), "alpha")

    def test_code_span_in_heading_keeps_content(self):
        self.assertEqual(ref_extract.slugify_heading(
            ref_extract.heading_plain_text("`type` の扱い")), "type-の扱い")

    def test_entity_reference_is_decoded(self):
        self.assertEqual(ref_extract.slugify_heading(
            ref_extract.heading_plain_text("A &amp; B")), "a--b")

    def test_heading_slugs_collects_atx_headings(self):
        text = "# T\n## 概要\n### 詳細な話\n"
        self.assertEqual(ref_extract.heading_slugs(text), {"t", "概要", "詳細な話"})


class TestUnenumeratedHeadingForms(unittest.TestCase):
    """列挙範囲が未決なので、範囲外の形が在るかだけを見る（DES-081 §3.3c.1）。"""

    def test_atx_only_document_has_none(self):
        self.assertFalse(ref_extract.has_unenumerated_heading_forms("# T\n## 概要\n本文\n"))

    def test_setext_heading_is_detected(self):
        self.assertTrue(ref_extract.has_unenumerated_heading_forms("見出し\n=====\n本文\n"))

    def test_heading_inside_list_is_detected(self):
        self.assertTrue(ref_extract.has_unenumerated_heading_forms("- 項目\n  ## 入れ子の見出し\n"))

    def test_setext_inside_fence_is_not_detected(self):
        self.assertFalse(ref_extract.has_unenumerated_heading_forms("```\n見出し\n=====\n```\n"))


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
