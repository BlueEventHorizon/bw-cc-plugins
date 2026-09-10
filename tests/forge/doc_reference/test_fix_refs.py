#!/usr/bin/env python3
"""fix_refs.py のテスト（索引で決まる修復だけを対象とする）。

**試験は実装の前に書き、実装が無い状態で落ちることを確かめる**（DES-081 §6.1 と同じ趣旨）。

対象は「索引が答えを持っている」修復に限る。

| 種別              | 索引が持つもの                     | 決まるか               |
| ----------------- | ---------------------------------- | ---------------------- |
| `moved_link`      | `names`（basename → 実在パス一覧） | 候補 1 件なら決まる    |
| `missing_anchor`  | 参照先の見出し slug 集合           | 候補 1 件なら決まる    |
| `missing_section` | **持っていない**（現在の節だけ）   | **決まらない**         |

`missing_section` が決まらないのは、旧節番号から現節番号への対応をどの索引も保持しないためで
ある。対応を知っているのは節を動かした当人だけであり、後から呼ばれた主体は推測しかできない。
推測で張り替えると、参照は解決するのに指し先が誤っている状態（検査が「正しい」と保証する嘘）
になるため、**決まらないものを決めない**ことを試験で固定する。
"""

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[3] / "plugins" / "forge" / "scripts" / "doc_reference"
sys.path.insert(0, str(_SCRIPTS))

import fix_refs  # noqa: E402


class TestDetermineMovedLink(unittest.TestCase):
    """パスが解決せず、その名前を持つ文書が実在する場合（`moved_link`）。"""

    def test_single_candidate_is_rewritten_relative_to_the_referrer(self):
        """候補が 1 件なら、参照元からの相対パスへ書き換える。"""
        self.assertEqual(
            fix_refs.determine_moved_link(
                "docs/specs/a/design/DES-001_x_design.md",
                "../../old/y.md",
                ["docs/specs/b/design/y.md"],
            ),
            "../../b/design/y.md",
        )

    def test_anchor_is_preserved(self):
        """位置指定は参照元の意図であり、パスの修正で落とさない。"""
        self.assertEqual(
            fix_refs.determine_moved_link(
                "docs/a/b.md", "../old/y.md#見出し", ["docs/c/y.md"]
            ),
            "../c/y.md#見出し",
        )

    def test_two_candidates_are_not_determined(self):
        """どれが正しいかは参照元の意図に依存する（NFR-001）。"""
        self.assertIsNone(
            fix_refs.determine_moved_link(
                "docs/a/b.md", "../old/y.md", ["docs/c/y.md", "docs/d/y.md"]
            )
        )

    def test_no_candidate_is_not_determined(self):
        """名前ごと実在しない（`broken_link`）ものは修復の対象ではない。"""
        self.assertIsNone(
            fix_refs.determine_moved_link("docs/a/b.md", "../old/y.md", [])
        )

    def test_same_directory_candidate_has_no_parent_segments(self):
        self.assertEqual(
            fix_refs.determine_moved_link(
                "docs/a/b.md", "sub/y.md", ["docs/a/y.md"]
            ),
            "y.md",
        )


class TestAnchorIsNeverDetermined(unittest.TestCase):
    """アンカーの置換先は決めない（DES-081 §3.3.1: 完全一致で引き、探索しない）。

    見出し索引は完全一致で引く。`missing_anchor` はその完全一致が外れた所見であり、
    そこから先へ進むには探索が要る。探索は候補が 1 件に絞れても指し先が正しいことを
    意味しないため、決めてはならない。
    """

    def test_prefix_match_is_not_used(self):
        """前方一致で 1 件に絞れても決めない。"""
        self.assertIsNone(
            fix_refs.determine_anchor(
                "共用コンポーネントの変更禁止",
                {"実装ポリシー", "共用コンポーネントの変更禁止-最重要"},
            )
        )

    def test_deleted_heading_with_a_similar_sibling_is_not_rewritten(self):
        """`## 実装` を削除した文書で `#実装` を `実装-手順` へ繋がない。

        候補が一意に決まっても、参照先は削除されており指し先が別の節になる。
        探索を持ち込むと生じる誤接続の回帰。
        """
        self.assertIsNone(fix_refs.determine_anchor("実装", {"実装-手順"}))

    def test_no_candidate_is_not_determined(self):
        self.assertIsNone(
            fix_refs.determine_anchor("存在しない見出し", {"実装ポリシー"})
        )


class TestSectionIsNeverDetermined(unittest.TestCase):
    """節番号は索引が対応を持たないため、決めてはならない。"""

    def test_missing_section_is_not_determined_even_with_one_section_left(self):
        """現在の節が 1 つしか無くても、そこへ張り替えてよい根拠にはならない。"""
        self.assertIsNone(
            fix_refs.determine_section("DES-045 §3.5", {"3.1"})
        )

    def test_missing_section_is_not_determined_for_adjacent_number(self):
        """番号の近さを対応の根拠にしない（§3.5 が消えた先は §3.4 とは限らない）。"""
        self.assertIsNone(
            fix_refs.determine_section("DES-081 §3.5", {"3.1", "3.2", "3.3", "3.4"})
        )


class TestFindingDispatch(unittest.TestCase):
    """所見 1 件を受けて、決まる書き換えだけを返す。"""

    def _finding(self, **kw):
        base = {"kind": "moved_link", "file": "docs/a/b.md", "line": 3,
                "ref": "../old/y.md", "reason": ""}
        base.update(kw)
        return base

    def test_moved_link_with_one_candidate_yields_rewrite(self):
        rewrite = fix_refs.determine_rewrite(
            self._finding(candidates=["docs/c/y.md"]), slugs=None
        )
        self.assertEqual(
            rewrite,
            {"file": "docs/a/b.md", "line": 3, "old": "../old/y.md", "new": "../c/y.md"},
        )

    def test_undetermined_kinds_yield_none(self):
        """意図に依存する種別・判定していない種別は決めない。"""
        for kind in ("broken_link", "missing_doc", "ambiguous", "undecidable",
                     "missing_label", "missing_section", "missing_anchor"):
            with self.subTest(kind=kind):
                self.assertIsNone(
                    fix_refs.determine_rewrite(self._finding(kind=kind), slugs=None)
                )

    def test_missing_anchor_is_not_rewritten_even_with_slugs(self):
        """所見が `slugs` を持っていても決めない。

        `slugs` は利用者へ候補を示すための材料であり、置換の根拠ではない
        （DES-081 §3.3.1: 完全一致で引き、探索しない）。
        """
        self.assertIsNone(fix_refs.determine_rewrite(self._finding(
            kind="missing_anchor",
            ref="../c/y.md#見出し",
            target="docs/c/y.md",
            slugs=["見出し-最重要", "別の見出し"],
        )))

    def test_explicit_slugs_argument_does_not_enable_rewriting(self):
        self.assertIsNone(fix_refs.determine_rewrite(
            self._finding(kind="missing_anchor", ref="#見出し"),
            slugs=["見出し-最重要"],
        ))


class TestSeamWithCheckRefs(unittest.TestCase):
    """`check_refs` が出した所見をそのまま `fix_refs` へ渡せること。

    **手書きの所見を経由させない。** 両モジュールを別々に試験すると、片方が出さない
    情報をもう片方が要求していても双方の試験が通る。実際にそれが起き、`check_refs` が
    見出し集合を報告に載せていなかったために `missing_anchor` が一度も置換されなかった。
    この試験は 2 つの出力契約が噛み合っていることだけを見る。
    """

    def setUp(self):
        sys.path.insert(0, str(_SCRIPTS))
        import check_refs
        import ref_index
        self.check_refs = check_refs
        paths = ["docs/a.md", "docs/moved/target.md"]
        self.indexes = {
            "files": set(paths),
            "names": ref_index.build_name_index(paths),
            "codes": ref_index.build_code_index([]),
        }
        self.caches = {
            "sections": {},
            "heading_lookup": lambda p: ({"見出し-最重要"}, False) if p == "docs/a.md" else None,
        }

    def _findings(self, path, text):
        return self.check_refs.check_file(
            path, text, self.indexes, dict(self.caches), is_markdown=True)["findings"]

    def test_moved_link_finding_feeds_determine_rewrite(self):
        findings = self._findings("docs/b.md", "[x](old/target.md)")
        self.assertEqual([f["kind"] for f in findings], ["moved_link"])
        rewrite = fix_refs.determine_rewrite(findings[0])
        self.assertIsNotNone(rewrite, "check_refs の所見から置換先が導けていない")
        self.assertEqual(rewrite["new"], "moved/target.md")

    def test_missing_anchor_finding_carries_candidates_but_is_not_rewritten(self):
        """所見は候補（`slugs`）を運ぶが、置換先は返らない。

        `slugs` は利用者へ示す材料である。運んでいること自体は契約なので確認するが、
        それが置換の根拠に転じていないことを同時に固定する。
        """
        findings = self._findings("docs/b.md", "[x](a.md#見出し)")
        self.assertEqual([f["kind"] for f in findings], ["missing_anchor"])
        self.assertEqual(findings[0]["slugs"], ["見出し-最重要"])
        self.assertIsNone(fix_refs.determine_rewrite(findings[0]))


if __name__ == "__main__":
    unittest.main()
