#!/usr/bin/env python3
"""ref_index.py / check_refs.py のテスト（REQ-023・DES-081 §6）。"""

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[3] / "plugins" / "forge" / "scripts" / "doc_reference"
sys.path.insert(0, str(_SCRIPTS))

import check_refs  # noqa: E402
import ref_index  # noqa: E402

_INDEX_DIRS = ["docs/specs/**/design/", "docs/specs/**/requirements/"]


class TestBuildCodeIndex(unittest.TestCase):
    def test_code_is_taken_from_filename_head(self):
        idx = ref_index.build_code_index(
            ["docs/specs/x/design/DES-075_a_design.md"])
        self.assertEqual(idx["codes"], {"DES-075": "docs/specs/x/design/DES-075_a_design.md"})

    def test_namespaced_code_is_not_split(self):
        idx = ref_index.build_code_index(
            ["docs/specs/x/design/COMMON-DES-001_a.md"])
        self.assertEqual(list(idx["codes"]), ["COMMON-DES-001"])

    def test_same_code_in_two_paths_becomes_ambiguous(self):
        """一意に決まらないものを決まったことにしない（NFR-001）。"""
        idx = ref_index.build_code_index(
            ["docs/specs/a/design/DES-001_x.md", "docs/specs/b/design/DES-001_y.md"])
        self.assertNotIn("DES-001", idx["codes"])
        self.assertIn("DES-001", idx["ambiguous"])


class TestBuildNameIndex(unittest.TestCase):
    """名前索引はファイル索引と別に持つ（DES-081 §3.3）。"""

    def test_name_maps_to_paths(self):
        idx = ref_index.build_name_index(["docs/a/x.md", "docs/b/y.md"])
        self.assertEqual(idx["x.md"], ["docs/a/x.md"])

    def test_same_name_in_two_paths_keeps_both(self):
        idx = ref_index.build_name_index(["docs/a/README.md", "docs/b/README.md"])
        self.assertEqual(idx["README.md"], ["docs/a/README.md", "docs/b/README.md"])


class TestNormpath(unittest.TestCase):
    def test_parent_traversal(self):
        self.assertEqual(check_refs._normpath("a/b/../c.md"), "a/c.md")

    def test_escape_above_root_is_kept(self):
        self.assertEqual(check_refs._normpath("../x.md"), "../x.md")


class TestCheckFile(unittest.TestCase):
    def setUp(self):
        self.paths = ["docs/a.md", "docs/moved/target.md",
                      "docs/specs/x/design/DES-075_a_design.md"]
        self.file_index = set(self.paths)
        self.indexes = {
            "files": self.file_index,
            "names": ref_index.build_name_index(self.paths),
            "codes": ref_index.build_code_index(
                ["docs/specs/x/design/DES-075_a_design.md"]),
        }
        self.sections = {"docs/specs/x/design/DES-075_a_design.md": {"1", "6.1"}}
        # 走査範囲内の文書だけが見出しを引ける（DES-081 §3.3c）
        self.headings = {"docs/a.md": ({"見出し"}, False)}

    def _lookup(self, path):
        return self.headings.get(path)

    def _all(self, path, text, is_markdown=True):
        return check_refs.check_file(
            path, text, self.indexes,
            {"sections": dict(self.sections), "heading_lookup": self._lookup},
            is_markdown=is_markdown)

    def _run(self, path, text, is_markdown=True):
        return self._all(path, text, is_markdown)["findings"]

    def test_resolved_link_yields_nothing(self):
        self.assertEqual(self._run("docs/b.md", "[x](a.md)"), [])

    def test_broken_link(self):
        got = self._run("docs/b.md", "[x](nope.md)")
        self.assertEqual([f["kind"] for f in got], ["broken_link"])

    def test_missing_section(self):
        got = self._run("docs/b.md", "詳細は DES-075 §9.9 が定める")
        self.assertEqual([f["kind"] for f in got], ["missing_section"])

    def test_existing_section_ok(self):
        self.assertEqual(self._run("docs/b.md", "DES-075 §6.1 参照"), [])

    def test_missing_doc(self):
        got = self._run("docs/b.md", "DES-999 §1 参照")
        self.assertEqual([f["kind"] for f in got], ["missing_doc"])

    def test_missing_label(self):
        got = self._run("docs/b.md", "本文 [表示][undefined] を使う")
        self.assertEqual([f["kind"] for f in got], ["missing_label"])

    def test_angle_bracket_destination_is_resolved_not_dropped(self):
        """山括弧囲みは層 1 で正当なリンクであり、解決は層 2 が行う（DES-081 §1.3）。

        抽出段階で対象外へ落とす形は採らない。空白を含む相対パスも解決対象であり、
        実在しなければ参照切れとして報告する。
        """
        got = self._run("docs/b.md", "[x](<p q.md>)")
        self.assertEqual([f["kind"] for f in got], ["broken_link"])

    def test_moved_link_when_the_name_exists_elsewhere(self):
        """名前の不在と配置の不一致を区別する（FNC-011）。"""
        got = self._run("docs/b.md", "[x](target.md)")
        self.assertEqual([f["kind"] for f in got], ["moved_link"])
        self.assertEqual(got[0]["candidates"], ["docs/moved/target.md"])

    def test_broken_link_when_the_name_is_absent(self):
        got = self._run("docs/b.md", "[x](nowhere.md)")
        self.assertEqual([f["kind"] for f in got], ["broken_link"])

    def test_same_document_anchor_is_resolved(self):
        got = self._run("docs/b.md", "# 見出し\n\n[x](#見出し)\n")
        self.assertEqual(got, [])

    def test_missing_anchor_in_the_same_document(self):
        got = self._run("docs/b.md", "# 見出し\n\n[x](#無い見出し)\n")
        self.assertEqual([f["kind"] for f in got], ["missing_anchor"])

    def test_anchor_is_undecidable_when_unenumerated_forms_exist(self):
        """setext 見出しがある文書では、列挙漏れの可能性を排除できない（§3.3c.1）。"""
        got = self._run("docs/b.md", "見出し\n=====\n\n[x](#無い見出し)\n")
        self.assertEqual([f["kind"] for f in got], ["undecidable"])

    def test_other_document_anchor_is_resolved(self):
        got = self._run("docs/b.md", "[x](a.md#見出し)")
        self.assertEqual(got, [])

    def test_other_document_anchor_missing(self):
        got = self._run("docs/b.md", "[x](a.md#無い)")
        self.assertEqual([f["kind"] for f in got], ["missing_anchor"])

    def test_other_document_anchor_outside_the_scanned_range(self):
        """走査範囲外の文書は見出し索引を持たないため判定不能（§3.3c）。"""
        got = self._run("docs/b.md", "[x](moved/target.md#見出し)")
        self.assertEqual([f["kind"] for f in got], ["undecidable"])

    def test_anchor_is_not_checked_when_the_path_is_broken(self):
        """パスが解決しなければアンカーは見に行かない（§3.3c）。"""
        got = self._run("docs/b.md", "[x](nowhere.md#見出し)")
        self.assertEqual([f["kind"] for f in got], ["broken_link"])

    def test_variable_expansion_is_undecidable(self):
        """解決規則を持たない形は黙って捨てず判定不能として報告する（NFR-001）。"""
        got = self._run("docs/b.md", "[x](${CLAUDE_PLUGIN_ROOT}/docs/a.md)")
        self.assertEqual([f["kind"] for f in got], ["undecidable"])

    def test_absolute_path_is_undecidable(self):
        got = self._run("docs/b.md", "[x](/etc/a.md)")
        self.assertEqual([f["kind"] for f in got], ["undecidable"])

    def test_external_url_is_counted_out_of_scope_not_a_finding(self):
        """対象外は所見ではなく別の欄で数える（FNC-012）。"""
        res = self._all("docs/b.md", "[x](https://example.test/a) と <https://example.test/b>")
        self.assertEqual(res["findings"], [])
        self.assertEqual(len(res["out_of_scope"]), 2)
        self.assertEqual({o["reason"] for o in res["out_of_scope"]}, {"external"})

    def test_non_markdown_target_is_resolved_not_dropped(self):
        """`.md` 以外の参照先も解決する（黙って捨てない）。"""
        got = self._run("docs/b.md", "[x](run.sh)")
        self.assertEqual([f["kind"] for f in got], ["broken_link"])

    def test_link_syntax_not_applied_to_non_markdown(self):
        """実装コードの添字アクセスを参照リンクと誤認しない（実測 387 件の誤検出の回帰）。"""
        code = 'value = data["a"]["b"]\nother = cfg["x"]["y"]\n'
        self.assertEqual(self._run("plugins/forge/scripts/x.py", code, is_markdown=False), [])

    def test_spec_ref_is_extracted_from_non_markdown(self):
        """実装コードのコメントにある節参照は種別を問わず拾う（FNC-005）。"""
        got = self._run("plugins/forge/scripts/x.py", "# DES-075 §9.9 に従う", is_markdown=False)
        self.assertEqual([f["kind"] for f in got], ["missing_section"])


class TestRunIntegration(unittest.TestCase):
    def test_run_on_repository_reports_status_ok(self):
        """実リポジトリで走り、既定値で補わず結果を返すこと（NFR-004）。

        対象に追跡下のパスを選ぶ。未追跡ファイルは索引にも走査対象にも入らない
        （DES-081 §3.2）ため、未 commit の文書を対象にすると `scanned` が 0 になる。
        """
        result = check_refs.run(["docs/rules/"], _INDEX_DIRS, index_exclude=["plan"])
        self.assertEqual(result["status"], "ok")
        self.assertGreater(result["scanned"], 0)
        self.assertIsInstance(result["findings"], list)

    def test_error_when_not_a_git_repository(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            result = check_refs.run(["docs/"], _INDEX_DIRS, project_root=d)
        self.assertEqual(result["status"], "error")


class TestMultipleDirs(unittest.TestCase):
    """`prepare_advisor_index.py` は category ごとに複数の root_dirs を返す。

    2 つの category（specs / rules）の応答を連結して渡すため、**受け取る側は
    ディレクトリの列を扱えなければならない**（1 つ目だけを見る実装では、
    もう一方の category の文書が母集団から落ちる）。
    """

    def test_select_covers_every_given_dir(self):
        paths = ["docs/a/x.md", "docs/b/y.md", "docs/c/z.md"]
        got = check_refs._select(paths, ["docs/a/", "docs/b/"], [], ".")
        self.assertEqual(got, ["docs/a/x.md", "docs/b/y.md"])

    def test_select_expands_globs_alongside_plain_dirs(self):
        """glob と素のディレクトリが混在しても両方効くこと。"""
        got = check_refs._select(
            ["docs/rules/r.md", "docs/specs/forge/design/DES-001_x.md"],
            ["docs/rules/", "docs/specs/**/design/"],
            [],
            ".",
        )
        self.assertEqual(
            got, ["docs/rules/r.md", "docs/specs/forge/design/DES-001_x.md"])

    def test_run_accepts_index_dirs_from_two_categories(self):
        """specs と rules の root_dirs を連結して渡せること。"""
        result = check_refs.run(
            ["docs/rules/"], _INDEX_DIRS + ["docs/rules/"], index_exclude=["plan"])
        self.assertEqual(result["status"], "ok")
        self.assertGreater(result["indexed"], 0)


if __name__ == "__main__":
    unittest.main()
