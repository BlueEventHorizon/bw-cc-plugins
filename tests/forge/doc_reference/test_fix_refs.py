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


class TestDetermineAnchor(unittest.TestCase):
    """参照先は実在するが、アンカーが実在しない場合（`missing_anchor`）。

    書かれたアンカーが真の slug の**前方一致**になる形（見出し末尾のタグが落ちている等）を
    決まる場合として扱う。
    """

    def test_unique_prefix_match_is_rewritten(self):
        self.assertEqual(
            fix_refs.determine_anchor(
                "共用コンポーネントの変更禁止",
                {"実装ポリシー", "共用コンポーネントの変更禁止-最重要"},
            ),
            "共用コンポーネントの変更禁止-最重要",
        )

    def test_two_prefix_matches_are_not_determined(self):
        self.assertIsNone(
            fix_refs.determine_anchor("design", {"design-notes", "design-review"})
        )

    def test_no_match_is_not_determined(self):
        self.assertIsNone(
            fix_refs.determine_anchor("存在しない見出し", {"実装ポリシー"})
        )

    def test_exact_match_needs_no_rewrite(self):
        """実在するアンカーは所見にならない。修復対象として渡っても書き換えない。"""
        self.assertIsNone(
            fix_refs.determine_anchor("実装ポリシー", {"実装ポリシー"})
        )

    def test_partial_word_is_not_a_prefix_match(self):
        """区切り（`-`）を伴わない部分一致は前方一致として扱わない。"""
        self.assertIsNone(
            fix_refs.determine_anchor("design", {"designer"})
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
                     "missing_label", "missing_section"):
            with self.subTest(kind=kind):
                self.assertIsNone(
                    fix_refs.determine_rewrite(self._finding(kind=kind), slugs=None)
                )


if __name__ == "__main__":
    unittest.main()
