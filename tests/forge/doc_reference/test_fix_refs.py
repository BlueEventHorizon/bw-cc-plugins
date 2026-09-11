#!/usr/bin/env python3
"""fix_refs.py のテスト（索引で決まる修復だけを対象とする）。

**試験は実装の前に書き、実装が無い状態で落ちることを確かめる**（DES-081 §6.1 と同じ趣旨）。

対象は「索引が答えを持っている」修復に限る。

| 種別              | 索引が完全一致で答えるもの             | 決まるか            |
| ----------------- | -------------------------------------- | ------------------- |
| `moved_link`      | `names`（basename → 実在パス一覧）     | 候補 1 件なら決まる |
| `missing_anchor`  | 見出し集合（完全一致は既に外れている） | **決まらない**      |
| `missing_section` | **持っていない**（現在の節だけ）       | **決まらない**      |

`missing_anchor` が決まらないのは、見出し索引を完全一致で引くためである（DES-081 §3.3.1）。
完全一致が外れたという所見なので、書かれた文字列はその時点でキーではない。そこから別のキーを
探すのは探索であり、候補が 1 件に絞れても指し先が正しいことを意味しない。

`missing_section` が決まらないのは、旧節番号から現節番号への対応をどの索引も保持しないためで
ある。対応を知っているのは節を動かした当人だけであり、後から呼ばれた主体は推測しかできない。

いずれも、推測で張り替えると参照は解決するのに指し先が誤っている状態（検査が「正しい」と
保証する嘘）になるため、**決まらないものを決めない**ことを試験で固定する。
"""

import sys
import tempfile
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

    **判定は `determine_rewrite` 越しに行う。** 「決めない」ことを専用の関数として
    置くと、その関数のためだけの試験ができて本番経路を通らない。
    """

    def _anchor_finding(self, ref, slugs):
        return {"kind": "missing_anchor", "file": "docs/a/b.md", "line": 3,
                "ref": ref, "target": "docs/c/y.md", "slugs": sorted(slugs),
                "reason": ""}

    def test_prefix_match_is_not_used(self):
        """前方一致で 1 件に絞れても決めない。"""
        self.assertIsNone(fix_refs.determine_rewrite(self._anchor_finding(
            "../c/y.md#共用コンポーネントの変更禁止",
            {"実装ポリシー", "共用コンポーネントの変更禁止-最重要"},
        )))

    def test_deleted_heading_with_a_similar_sibling_is_not_rewritten(self):
        """`## 実装` を削除した文書で `#実装` を `実装-手順` へ繋がない。

        候補が一意に決まっても、参照先は削除されており指し先が別の節になる。
        探索を持ち込むと生じる誤接続の回帰（DES-081 §6.2 が名指しする素材）。
        """
        self.assertIsNone(
            fix_refs.determine_rewrite(self._anchor_finding("../c/y.md#実装", {"実装-手順"}))
        )

    def test_no_candidate_is_not_determined(self):
        self.assertIsNone(fix_refs.determine_rewrite(
            self._anchor_finding("../c/y.md#存在しない見出し", {"実装ポリシー"})
        ))


class TestSectionIsNeverDetermined(unittest.TestCase):
    """節番号は索引が対応を持たないため、決めてはならない。"""

    def _section_finding(self, ref):
        return {"kind": "missing_section", "file": "docs/a/b.md", "line": 3,
                "ref": ref, "reason": ""}

    def test_missing_section_is_not_determined_even_with_one_section_left(self):
        """現在の節が 1 つしか無くても、そこへ張り替えてよい根拠にはならない。"""
        self.assertIsNone(
            fix_refs.determine_rewrite(self._section_finding("DES-045 §3.5"))
        )

    def test_missing_section_is_not_determined_for_adjacent_number(self):
        """番号の近さを対応の根拠にしない（§3.5 が消えた先は §3.4 とは限らない）。"""
        self.assertIsNone(
            fix_refs.determine_rewrite(self._section_finding("DES-081 §3.5"))
        )


class TestFindingDispatch(unittest.TestCase):
    """所見 1 件を受けて、決まる書き換えだけを返す。"""

    def _finding(self, **kw):
        base = {"kind": "moved_link", "file": "docs/a/b.md", "line": 3,
                "ref": "../old/y.md", "dest": "../old/y.md",
                "col_start": 10, "col_end": 21, "replaceable": True, "reason": ""}
        base.update(kw)
        return base

    def test_moved_link_with_one_candidate_yields_rewrite(self):
        rewrite = fix_refs.determine_rewrite(self._finding(candidates=["docs/c/y.md"]))
        self.assertEqual(
            rewrite,
            {"file": "docs/a/b.md", "line": 3, "col_start": 10, "col_end": 21,
             "old": "../old/y.md", "new": "../c/y.md"},
        )

    def test_undetermined_kinds_yield_none(self):
        """意図に依存する種別・判定していない種別は決めない。"""
        for kind in ("broken_link", "missing_doc", "ambiguous", "undecidable",
                     "missing_label", "missing_section", "missing_anchor"):
            with self.subTest(kind=kind):
                self.assertIsNone(fix_refs.determine_rewrite(self._finding(kind=kind)))

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

    def test_finding_without_a_position_is_not_rewritten(self):
        """位置を持たない所見は置換しない。

        位置が無ければ差し替える範囲が決まらず、文字列を探すことになる。探索は
        禁じられているため（DES-081 §3.3.1）、置換せず報告に残す。
        """
        for missing in ("col_start", "col_end", "dest"):
            with self.subTest(missing=missing):
                finding = self._finding(candidates=["docs/c/y.md"])
                finding[missing] = None
                self.assertIsNone(fix_refs.determine_rewrite(finding))


class TestSeamWithCheckRefs(unittest.TestCase):
    """`check_refs` が出した所見をそのまま `fix_refs` へ渡せること。

    **手書きの所見を経由させない。** 両モジュールを別々に試験すると、片方が出さない
    情報をもう片方が要求していても双方の試験が通る。実際にそれが起き、`check_refs` が
    置換対象そのもの（`dest` と位置）を報告に載せていなかったために、参照定義行の置換で
    ラベル定義が消える欠陥が両者の試験をすり抜けた。この試験は 2 つの出力契約が噛み合って
    いることだけを見る。
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

    def test_reference_definition_line_is_rewritten_without_losing_the_label(self):
        """参照定義行（`[label]: パス`）の置換でラベルが消えないこと。

        定義行の所見の `ref` はラベルを含む行全体である（利用者へ見せる表示）。
        これを置換対象にすると、置換後の行が `パス` だけになり、その文書の
        `[表示][label]` がすべて参照先を失う。置換の対象は `dest` である。

        **本番経路（`apply_rewrites`）を通す。** 文字列一致で検証すると、桁の記録が
        壊れていても通る（設計が禁じた手段で確かめることになる。DES-081 §3.3.1）。
        """
        text = "本文で [x][lbl] を使う。\n\n[lbl]: old/target.md\n"
        findings = self._findings("docs/b.md", text)
        self.assertEqual([f["kind"] for f in findings], ["moved_link"])
        rewrite = fix_refs.determine_rewrite(findings[0])
        self.assertIsNotNone(rewrite, "check_refs の所見から置換先が導けていない")
        self.assertEqual(rewrite["old"], "old/target.md")
        self.assertEqual(rewrite["new"], "moved/target.md")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "docs" / "b.md").write_text(text, encoding="utf-8")
            got = fix_refs.apply_rewrites([rewrite], project_root=str(root))
            self.assertEqual(got["errors"], [])
            self.assertEqual((root / "docs" / "b.md").read_text(encoding="utf-8"),
                             "本文で [x][lbl] を使う。\n\n[lbl]: moved/target.md\n")

    def test_escaped_destination_is_not_rewritten(self):
        """エスケープを含む destination は置換しない（表記の付け直しを要するため）。

        置換するのは、原本のその範囲の文字列が `dest` と一致する所見だけである
        （REQ-023 §3.2: 表記の決定は本機構が判定しない）。判定は抽出側が行うため、
        書き戻し側の照合が外れることは「検査後にファイルが変わった」だけを意味する。
        """
        findings = self._findings("docs/b.md", r"[x](old/target\(1\).md)")
        self.assertEqual([f["kind"] for f in findings], ["broken_link"])

        # 同名が実在する形（moved_link）でも、エスケープがあれば置換先を返さない
        finding = {"kind": "moved_link", "file": "docs/b.md", "line": 1,
                   "ref": r"old/t\(1\).md", "dest": "old/t(1).md",
                   "col_start": 4, "col_end": 21, "replaceable": False,
                   "candidates": ["docs/moved/t(1).md"], "reason": ""}
        self.assertIsNone(fix_refs.determine_rewrite(finding))
        finding["replaceable"] = True
        self.assertIsNotNone(fix_refs.determine_rewrite(finding),
                             "一致する形では置換先が返ること（対照）")

    def test_missing_anchor_finding_carries_candidates_but_is_not_rewritten(self):
        """所見は候補（`slugs`）を運ぶが、置換先は返らない。

        `slugs` は利用者へ示す材料である。運んでいること自体は契約なので確認するが、
        それが置換の根拠に転じていないことを同時に固定する。
        """
        findings = self._findings("docs/b.md", "[x](a.md#見出し)")
        self.assertEqual([f["kind"] for f in findings], ["missing_anchor"])
        self.assertEqual(findings[0]["slugs"], ["見出し-最重要"])
        self.assertIsNone(fix_refs.determine_rewrite(findings[0]))


class TestApplyRewrites(unittest.TestCase):
    """記録された範囲だけを差し替えて書き戻すこと（DES-081 §4.3.2）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _rewrite(self, line, col_start, old, new, rel="docs/b.md"):
        return {"file": rel, "line": line, "col_start": col_start,
                "col_end": col_start + len(old), "old": old, "new": new}

    def test_only_the_recorded_range_changes(self):
        """同一行で接尾辞が一致する別の参照を巻き込まないこと。

        文字列一致に退行すると、`old/t.md` の置換が `../old/t.md` にも当たって
        指し先を変える（参照切れより有害な誤接続）。
        """
        path = self._write("docs/b.md", "[a](old/t.md) と [b](../old/t.md)\n")
        got = fix_refs.apply_rewrites(
            [self._rewrite(1, 4, "old/t.md", "moved/t.md")], project_root=str(self.root))
        self.assertEqual(got["errors"], [])
        self.assertEqual(path.read_text(encoding="utf-8"),
                         "[a](moved/t.md) と [b](../old/t.md)\n")

    def test_two_rewrites_on_the_same_line_both_land(self):
        """同一行に 2 件決まったとき、両方が正しく当たること。

        前から当てる実装では、1 件目で長さが変わった分だけ 2 件目の桁がずれて落ちる。
        """
        path = self._write("docs/b.md", "[a](x/t.md) と [b](y/t.md)\n")
        got = fix_refs.apply_rewrites([
            self._rewrite(1, 4, "x/t.md", "moved/one/t.md"),
            self._rewrite(1, 18, "y/t.md", "moved/two/t.md"),
        ], project_root=str(self.root))
        self.assertEqual(got["errors"], [])
        self.assertEqual(len(got["applied"]), 2)
        self.assertEqual(path.read_text(encoding="utf-8"),
                         "[a](moved/one/t.md) と [b](moved/two/t.md)\n")

    def test_multiple_lines_in_one_file(self):
        path = self._write("docs/b.md", "[a](x/t.md)\n\n[lbl]: y/t.md\n")
        got = fix_refs.apply_rewrites([
            self._rewrite(1, 4, "x/t.md", "moved/t.md"),
            self._rewrite(3, 7, "y/t.md", "moved/t.md"),
        ], project_root=str(self.root))
        self.assertEqual(got["errors"], [])
        self.assertEqual(path.read_text(encoding="utf-8"),
                         "[a](moved/t.md)\n\n[lbl]: moved/t.md\n")

    def test_content_changed_since_the_check_is_not_guessed(self):
        """記録された位置の内容が変わっていたら、探し直さずに報告する。

        探し直すことは走査であり、走査のたびに結果が変わりうる操作を書き込みの途中へ
        挟むことになる（DES-081 §4.3.2）。
        """
        path = self._write("docs/b.md", "[a](別の内容.md)\n")
        got = fix_refs.apply_rewrites(
            [self._rewrite(1, 4, "x/t.md", "moved/t.md")], project_root=str(self.root))
        self.assertEqual(got["applied"], [])
        self.assertEqual(len(got["errors"]), 1)
        self.assertEqual(path.read_text(encoding="utf-8"), "[a](別の内容.md)\n")

    def test_no_rewrite_leaves_the_file_untouched(self):
        path = self._write("docs/b.md", "[a](x/t.md)\n")
        before = path.stat().st_mtime_ns
        got = fix_refs.apply_rewrites([], project_root=str(self.root))
        self.assertEqual(got, {"applied": [], "errors": []})
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_trailing_newline_is_preserved(self):
        """末尾改行の有無を変えないこと（無関係な差分を作らない）。"""
        path = self._write("docs/b.md", "[a](x/t.md)")
        fix_refs.apply_rewrites(
            [self._rewrite(1, 4, "x/t.md", "moved/t.md")], project_root=str(self.root))
        self.assertEqual(path.read_text(encoding="utf-8"), "[a](moved/t.md)")

    def test_crlf_is_preserved_including_untouched_lines(self):
        """CRLF を変えないこと。**触っていない行の行末も変えない。**

        既定の universal newlines で読むと、読み込み時に CRLF が LF へ落ち、書き戻しで
        確定する。置換範囲と無関係な全行の行末が変わり、置換は「記録された範囲だけの
        差し替え」でなくなる（DES-081 §4.3.2）。本機構は配布物であり、CRLF の作業ツリーを
        持つ利用プロジェクトで起きる。
        """
        path = self.root / "docs" / "b.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"- item\r\n[a](x/t.md)\r\n")
        got = fix_refs.apply_rewrites(
            [self._rewrite(2, 4, "x/t.md", "moved/t.md")], project_root=str(self.root))
        self.assertEqual(got["errors"], [])
        self.assertEqual(path.read_bytes(), b"- item\r\n[a](moved/t.md)\r\n")

    def test_mixed_line_endings_are_preserved(self):
        """行末が混在していても、それぞれの行の行末を保つこと。"""
        path = self.root / "docs" / "b.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"crlf\r\n[a](x/t.md)\nlf\r\n")
        fix_refs.apply_rewrites(
            [self._rewrite(2, 4, "x/t.md", "moved/t.md")], project_root=str(self.root))
        self.assertEqual(path.read_bytes(), b"crlf\r\n[a](moved/t.md)\nlf\r\n")

    def test_overlapping_ranges_are_not_applied(self):
        """範囲が重なる書き換えは当てない（テキスト編集の不変条件）。

        重なったまま当てると 1 件目の差し替えが 2 件目の範囲を壊す。順序（後ろから
        当てる）はこの不変条件を満たす手段であって、不変条件そのものではない。
        """
        path = self._write("docs/b.md", "[a](x/t.md)\n")
        got = fix_refs.apply_rewrites([
            self._rewrite(1, 4, "x/t.md", "moved/t.md"),
            {"file": "docs/b.md", "line": 1, "col_start": 6, "col_end": 10,
             "old": "t.md", "new": "u.md"},
        ], project_root=str(self.root))
        self.assertEqual(got["applied"], [])
        self.assertEqual(len(got["errors"]), 1)
        self.assertIn("重なって", got["errors"][0]["reason"])
        self.assertEqual(path.read_text(encoding="utf-8"), "[a](x/t.md)\n")


if __name__ == "__main__":
    unittest.main()
