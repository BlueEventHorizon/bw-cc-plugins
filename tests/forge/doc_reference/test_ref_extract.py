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


class TestFences(unittest.TestCase):
    def test_four_backtick_fence_not_closed_by_three(self):
        """4 連で開いたフェンスは 3 連では閉じない（近似実装が失敗した形）。"""
        text = "````markdown\n```\n[x](inside.md)\n```\n````\n[y](outside.md)\n"
        got = [d for _, d, *_rest in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["outside.md"])

    def test_tilde_fence(self):
        text = "~~~\n[x](inside.md)\n~~~\n[y](outside.md)\n"
        got = [d for _, d, *_rest in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["outside.md"])

    def test_closing_fence_must_not_have_info_string(self):
        """info string を持つ行は閉じフェンスにならない。"""
        text = "```\n[x](a.md)\n```python\n[y](b.md)\n```\n[z](c.md)\n"
        got = [d for _, d, *_rest in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["c.md"])

    def test_honor_fences_false_scans_everything(self):
        text = "```\n[x](inside.md)\n```\n"
        got = [d for _, d, *_rest in ref_extract.extract_links(text, honor_fences=False)["inline"]]
        self.assertEqual(got, ["inside.md"])


class TestInlineLinks(unittest.TestCase):
    def test_image_and_link(self):
        got = [d for _, d, *_rest in ref_extract.extract_links("![a](i.png) と [b](d.md)")["inline"]]
        self.assertEqual(got, ["i.png", "d.md"])

    def test_html_comment_excluded(self):
        """1 行に閉じた HTML コメント（CommonMark §4.6）。"""
        text = "<!-- [x](commented.md) -->\n[y](real.md)\n"
        got = [d for _, d, *_rest in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["real.md"])

    def test_multiline_html_comment_excluded(self):
        """複数行にまたがる HTML コメントも終端まで 1 ブロック（CommonMark §4.6）。

        1 行の形だけを固定した試験は通るため、この形が欠けると覆いになる（DES-081 §6.1）。
        """
        text = "<!--\n[x](commented.md)\n-->\n[y](real.md)\n"
        got = [d for _, d, *_rest in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["real.md"])

    def test_indented_code_block_is_not_a_link(self):
        """行頭 4 スペースはコードであり、中のリンクは解析しない（CommonMark §4.4）。"""
        text = "段落\n\n    [x](indented.md)\n\n[y](real.md)\n"
        got = [d for _, d, *_rest in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["real.md"])

    def test_raw_html_anchor_is_not_a_link(self):
        """生の HTML は Markdown のリンクではない（CommonMark §6.6）。skipped にも入れない。"""
        res = ref_extract.extract_links('<a href="gone.md">x</a>\n[y](real.md)\n')
        self.assertEqual([d for _, d, *_rest in res["inline"]], ["real.md"])
        self.assertEqual(res["skipped"], [])

    def test_angle_bracket_destination_is_a_link(self):
        """山括弧囲みは CommonMark §6.3 の正当な destination である。

        解決規則を持つかどうかは層 2 の事情であり、抽出段階で落とさない（DES-081 §1.3）。
        """
        res = ref_extract.extract_links("[x](<p with space.md>)")
        self.assertEqual([d for _, d, *_rest in res["inline"]], ["p with space.md"])
        self.assertEqual(res["skipped"], [])

    def test_destination_with_title(self):
        """title 付き destination（CommonMark §6.3）。title は destination に含めない。"""
        got = [d for _, d, *_rest in ref_extract.extract_links('[x](a.md "題")')["inline"]]
        self.assertEqual(got, ["a.md"])

    def test_destination_with_balanced_parens(self):
        """括弧を含む destination は釣り合っていれば destination の一部（CommonMark §6.3）。"""
        got = [d for _, d, *_rest in ref_extract.extract_links("[x](a(b).md)")["inline"]]
        self.assertEqual(got, ["a(b).md"])

    def test_link_text_with_nested_brackets(self):
        """リンクテキストは釣り合った角括弧を含みうる（CommonMark §6.3）。"""
        got = [d for _, d, *_rest in ref_extract.extract_links("[a [b] c](d.md)")["inline"]]
        self.assertEqual(got, ["d.md"])

    def test_autolink_is_extracted(self):
        """autolink は参照である（CommonMark §6.5）。層 2 で対象外になるのは別の話。"""
        got = [d for _, d, *_rest in ref_extract.extract_links("<https://example.test/a>")["inline"]]
        self.assertEqual(got, ["https://example.test/a"])


class TestNestingInsideLinkTextAndAltText(unittest.TestCase):
    """入れ子の扱いはリンクと画像で逆である（CommonMark §6.4）。

    | 外側 | 内側 | 期待 |
    | ---- | ---- | ---- |
    | リンク | 画像 | 両方（`[![alt](src)](href)`。`README.md:3` に実在） |
    | リンク | リンク | 内側だけ。**外側はリンクにならない** |
    | 画像 | 何でも | 外側だけ。alt は平文へ潰れる |

    素朴に再帰すると 2 行目と 3 行目で誤検出になる（実装時に用例 518 / 519 / 520 /
    574 / 575 を退行させた）。
    """

    def _dests(self, text):
        return [d for _, d, *_rest in ref_extract.extract_links(text)["inline"]]

    def test_image_inside_link_text_yields_both(self):
        """`README.md:3` のバッジと同じ形。内側の `src` を取りこぼしていた。"""
        self.assertEqual(self._dests("[![moon](moon.jpg)](/uri)"), ["/uri", "moon.jpg"])

    def test_link_inside_link_text_invalidates_the_outer_link(self):
        self.assertEqual(self._dests("[foo [bar](/uri)](/other)"), ["/uri"])

    def test_link_nested_deeper_still_invalidates_the_outer_link(self):
        self.assertEqual(
            self._dests("[foo *[bar [baz](/uri)](/mid)*](/outer)"), ["/uri"])

    def test_image_alt_is_flattened_so_inner_links_do_not_appear(self):
        self.assertEqual(self._dests("![foo [bar](/url)](/url2)"), ["/url2"])

    def test_image_alt_is_flattened_for_nested_images_too(self):
        self.assertEqual(self._dests("![foo ![bar](/url)](/url2)"), ["/url2"])


class TestHtmlBlocks(unittest.TestCase):
    """CommonMark §4.6 は 7 type ある。コメント（type 2）だけでは足りない。"""

    def test_type6_block_tag_excluded(self):
        text = "<div>\n[x](gone.md)\n</div>\n\n[y](real.md)\n"
        got = [d for _, d, *_rest in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["real.md"])

    def test_type1_pre_excluded(self):
        text = "<pre>\n[x](gone.md)\n</pre>\n\n[y](real.md)\n"
        got = [d for _, d, *_rest in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["real.md"])

    def test_html_block_ends_at_blank_line(self):
        """type 6 は空行で閉じる。閉じた後のリンクは抽出する。"""
        text = "<div>\n[x](gone.md)\n\n[y](real.md)\n"
        got = [d for _, d, *_rest in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["real.md"])


class TestIndentedCodeAndContainers(unittest.TestCase):
    """§4.4 の判定はコンテナ相対のインデントで決まる（§5）。除外し過ぎは見逃しになる。"""

    def test_list_continuation_paragraph_is_not_code(self):
        """リスト項目の継続段落はコードではない。抽出する。"""
        text = "- 項目\n\n    継続の [x](a.md)\n"
        got = [d for _, d, *_rest in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["a.md"])

    def test_nested_list_item_is_not_code(self):
        text = "- 項目\n    - 入れ子の [x](a.md)\n"
        got = [d for _, d, *_rest in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["a.md"])

    def test_code_block_inside_list_item_is_excluded(self):
        """コンテナ相対で 4 スペース以上ならコードである。"""
        text = "- 項目\n\n      [x](gone.md)\n\n[y](real.md)\n"
        got = [d for _, d, *_rest in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["real.md"])

    def test_indented_line_cannot_interrupt_a_paragraph(self):
        """段落の直後の 4 スペース行はコードにならない（CommonMark §4.4）。"""
        text = "段落\n    継続の [x](a.md)\n"
        got = [d for _, d, *_rest in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["a.md"])

    def test_block_quote_content_is_scanned(self):
        text = "> 引用の [x](a.md)\n"
        got = [d for _, d, *_rest in ref_extract.extract_links(text)["inline"]]
        self.assertEqual(got, ["a.md"])


class TestReferenceLinks(unittest.TestCase):
    def test_definition_and_use(self):
        text = "本文は [表示][lbl] を使う。\n\n[lbl]: ./target.md\n"
        res = ref_extract.extract_links(text)
        self.assertEqual([l for _, l in res["ref_uses"]], ["lbl"])
        self.assertEqual([(l, d) for _, l, d, *_rest in res["ref_defs"]], [("lbl", "./target.md")])

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


class TestReferenceDefinitionValidity(unittest.TestCase):
    """定義の形をしていても定義でない行がある（CommonMark §4.7）。

    拾うと**誤検出**になる。地の文の一部を参照切れとして報告し、`fix_refs` が
    書き換える経路まで届くため、見逃しより害が大きい。
    """

    def _defs(self, text):
        return [d for _lineno, _label, d, *_rest in ref_extract.extract_links(text)["ref_defs"]]

    def test_trailing_junk_after_the_title_is_not_a_definition(self):
        self.assertEqual(self._defs('[foo]: /url "title" ok\n'), [])

    def test_title_must_be_separated_by_whitespace(self):
        self.assertEqual(self._defs("[foo]: <bar>(baz)\n"), [])

    def test_a_definition_cannot_interrupt_a_paragraph(self):
        self.assertEqual(self._defs("Foo\n[bar]: /baz\n"), [])

    def test_a_definition_may_follow_a_heading(self):
        """見出しは段落ではないので、直後の定義は成立する。"""
        self.assertEqual(self._defs("# H\n[bar]: /baz\n"), ["/baz"])

    def test_definitions_may_follow_each_other(self):
        self.assertEqual(self._defs("[a]: /1\n[b]: /2\n"), ["/1", "/2"])

    def test_a_title_on_its_own_line_does_not_block_the_next_definition(self):
        """回帰: title の行を段落とみなす実装はここで落ちた（用例 217）。"""
        self.assertEqual(
            self._defs('[foo]: /foo-url "foo"\n[bar]: /bar-url\n  "bar"\n[baz]: /baz-url\n'),
            ["/foo-url", "/bar-url", "/baz-url"])

    def test_an_unterminated_title_is_still_a_definition(self):
        """回帰: 閉じない title を不正とする実装はここで落ちた（用例 196）。"""
        self.assertEqual(self._defs("[foo]: /url '\ntitle\n'\n"), ["/url"])

    def test_an_escaped_quote_inside_a_title_is_allowed(self):
        self.assertEqual(self._defs('[foo]: /url "foo\\"bar"\n'), ["/url"])


class TestRawHtmlBindsTighterThanLinks(unittest.TestCase):
    """生 HTML と autolink はリンクより強く結び付く（CommonMark §6.6）。

    タグの属性値には `]` を書ける。リンクテキストの走査がタグを読み飛ばさないと、
    属性値の一部を destination として拾う（用例 524 / 526 / 536）。

    **前処理で潰す形では直せない。** 一律にマスクすると `[a](<b>c)` `![foo](<url>)`
    の山括弧 destination まで消える（実測で用例 494 / 580 が退行した）。
    """

    def _dests(self, text):
        return [d for _, d, *_rest in ref_extract.extract_links(text)["inline"]]

    def test_bracket_inside_an_html_attribute_does_not_close_the_link(self):
        self.assertEqual(self._dests('[foo <bar attr="](baz)">'), [])

    def test_reference_bracket_inside_an_html_attribute_is_not_a_link(self):
        self.assertEqual(self._dests('[foo <bar attr="][ref]">'), [])

    def test_angle_bracket_destination_survives(self):
        """回帰: 生 HTML を前処理でマスクした実装はここで落ちた。"""
        self.assertEqual(self._dests("![foo](<url>)"), ["url"])

    def test_html_inside_link_text_does_not_break_a_real_link(self):
        self.assertEqual(self._dests("[a <b>bold</b> c](y.md)"), ["y.md"])

    def test_autolink_is_not_mistaken_for_an_html_tag(self):
        self.assertEqual(self._dests("<https://example.com/x.md>"), ["https://example.com/x.md"])


class TestHeadingSlugsUseTheOriginalText(unittest.TestCase):
    """見出し文はマスク前の原本から取る（外部機構との一致。DES-081 §5.2.1）。

    `heading_slugs` は見出しかどうかを正規化後の行で判定するが、**材料は原本**である。
    正規化はコードスパンを同じ長さのマスクへ潰すため、正規化後の行を渡すと中身が
    消える。実測では、この取り違えで 218 ファイル中 41 ファイルの slug が外部機構と
    食い違っていた（`` `subagent_type` `` を含む見出しなど）。

    コードスパンの中身は literal であり、取り出した後に HTML タグの除去・実体参照・
    バックスラッシュの規則を掛けてはならない。掛けると `` `<script src>` `` が
    タグとみなされて消える。
    """

    def test_code_span_content_is_kept(self):
        self.assertEqual(
            ref_extract.heading_slugs("## 3. `subagent_type` の値域 [MANDATORY]\n"),
            {"3-subagent_type-の値域-mandatory"})

    def test_html_like_code_span_is_not_stripped_as_a_tag(self):
        self.assertEqual(
            ref_extract.heading_slugs("### 4.1 技術的根拠: `<script src>` タグの動的差し替え\n"),
            {"41-技術的根拠-script-src-タグの動的差し替え"})

    def test_two_code_spans_in_one_heading(self):
        self.assertEqual(
            ref_extract.heading_slugs("### `hug` を使えばいいのに `<N>` で固定する\n"),
            {"hug-を使えばいいのに-n-で固定する"})

    def test_real_html_tag_outside_a_code_span_is_still_stripped(self):
        self.assertEqual(ref_extract.heading_slugs("## <b>Foo</b> bar\n"), {"foo-bar"})

    def test_heading_inside_an_unclosed_html_comment_is_not_a_heading(self):
        """HTML コメントは空行では終わらず `-->` の行まで続く（CommonMark §4.6 type 2）。

        `.github/PULL_REQUEST_TEMPLATE.md` に実在した形。
        """
        text = "<!--\n\n| a |\n\n## 備考\n\n-->\n\n## 実在\n"
        self.assertEqual(ref_extract.heading_slugs(text), {"実在"})


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
