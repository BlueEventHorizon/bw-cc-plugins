#!/usr/bin/env python3
"""ref_index.py / check_refs.py のテスト（REQ-023・DES-081 §6）。"""

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[3] / "plugins" / "forge" / "scripts" / "doc_reference"
sys.path.insert(0, str(_SCRIPTS))

import check_refs  # noqa: E402
import ref_index  # noqa: E402

_INDEX = r".*"  # build_code_index に渡すパターン（パス列は呼び出し側が絞る）
_INDEX_DIRS = ["docs/specs/**/design/", "docs/specs/**/requirements/"]


class TestBuildCodeIndex(unittest.TestCase):
    def test_code_is_taken_from_filename_head(self):
        idx = ref_index.build_code_index(
            ["docs/specs/x/design/DES-075_a_design.md"], _INDEX)
        self.assertEqual(idx["codes"], {"DES-075": "docs/specs/x/design/DES-075_a_design.md"})

    def test_namespaced_code_is_not_split(self):
        idx = ref_index.build_code_index(
            ["docs/specs/x/design/COMMON-DES-001_a.md"], _INDEX)
        self.assertEqual(list(idx["codes"]), ["COMMON-DES-001"])

    def test_same_code_in_two_paths_becomes_ambiguous(self):
        """一意に決まらないものを決まったことにしない（NFR-001）。"""
        idx = ref_index.build_code_index(
            ["docs/specs/a/design/DES-001_x.md", "docs/specs/b/design/DES-001_y.md"], _INDEX)
        self.assertNotIn("DES-001", idx["codes"])
        self.assertIn("DES-001", idx["ambiguous"])

    def test_include_pattern_filters(self):
        """`include_pattern` に該当しないパスは索引へ入らない。"""
        idx = ref_index.build_code_index(
            ["plugins/forge/docs/DES-999_x.md"], r"^docs/specs/")
        self.assertEqual(idx["codes"], {})


class TestNormpath(unittest.TestCase):
    def test_parent_traversal(self):
        self.assertEqual(check_refs._normpath("a/b/../c.md"), "a/c.md")

    def test_escape_above_root_is_kept(self):
        self.assertEqual(check_refs._normpath("../x.md"), "../x.md")


class TestCheckFile(unittest.TestCase):
    def setUp(self):
        self.file_index = {"docs/a.md", "docs/specs/x/design/DES-075_a_design.md"}
        self.code_index = ref_index.build_code_index(
            ["docs/specs/x/design/DES-075_a_design.md"], _INDEX)
        self.sections = {"docs/specs/x/design/DES-075_a_design.md": {"1", "6.1"}}

    def _run(self, path, text, is_markdown=True):
        return check_refs.check_file(path, text, self.file_index, self.code_index,
                                     dict(self.sections), is_markdown=is_markdown)

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

    def test_out_of_scope_is_reported(self):
        got = self._run("docs/b.md", "[x](<p q.md>)")
        self.assertEqual([f["kind"] for f in got], ["out_of_scope"])

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


if __name__ == "__main__":
    unittest.main()
