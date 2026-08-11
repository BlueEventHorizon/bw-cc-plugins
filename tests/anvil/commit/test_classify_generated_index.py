"""classify_generated_index.py の単体テスト（anvil:commit Phase 3）。

`git status --porcelain -z` の分解を固定する。とくに次は行ベースの手動パースで取り違える形であり、
テストで固定しないと静かに壊れる。

- 空白・非 ASCII を含むパス（`-z` を使わないと quote 表記になる）
- rename / copy（`R` / `C` は 1 エントリに元パスと新パスの 2 フィールドを持つ）
- ステージ済み・未ステージ・未追跡の混在
"""

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "anvil" / "skills" / "commit" / "scripts" / "classify_generated_index.py"
)

_spec = importlib.util.spec_from_file_location("anvil_classify_generated_index", _SCRIPT_PATH)
classify_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(classify_mod)

TOC = classify_mod.TOC_PATH_PREFIX


def _porcelain(*entries: str) -> str:
    """NUL 区切りの porcelain 出力を組み立てる（各エントリは末尾に NUL）。"""
    return "".join(e + "\0" for e in entries)


class ClassifyTest(unittest.TestCase):
    def test_toc_and_other_are_separated(self):
        out = _porcelain(f" M {TOC}rules-abc/toc.yaml", " M docs/rules/foo.md")
        result = classify_mod.classify(out)
        self.assertEqual(result["toc_paths"], [f"{TOC}rules-abc/toc.yaml"])
        self.assertEqual(result["other_paths"], ["docs/rules/foo.md"])

    def test_staged_and_unstaged_are_both_included(self):
        out = _porcelain(f"M  {TOC}a/toc.yaml", f" M {TOC}b/toc.yaml")
        result = classify_mod.classify(out)
        self.assertEqual(len(result["toc_paths"]), 2)

    def test_untracked_is_separated(self):
        out = _porcelain("?? docs/new.md", " M docs/rules/foo.md")
        result = classify_mod.classify(out)
        self.assertEqual(result["untracked_paths"], ["docs/new.md"])
        self.assertEqual(result["other_paths"], ["docs/rules/foo.md"])

    def test_untracked_toc_is_not_counted_as_tracked_toc(self):
        """未追跡の ToC は `git add -u` の対象外なので、追跡済み ToC と混ぜない。"""
        out = _porcelain(f"?? {TOC}new/toc.yaml")
        result = classify_mod.classify(out)
        self.assertEqual(result["toc_paths"], [])
        self.assertEqual(result["untracked_paths"], [f"{TOC}new/toc.yaml"])

    def test_path_with_spaces_and_non_ascii(self):
        out = _porcelain(" M docs/rules/日本語 の ファイル.md")
        result = classify_mod.classify(out)
        self.assertEqual(result["other_paths"], ["docs/rules/日本語 の ファイル.md"])

    def test_rename_uses_new_path_and_skips_old(self):
        """rename は「元パス」フィールドを 1 つ従える。新しいパスだけを採用する。"""
        out = _porcelain("R  docs/rules/new.md", "docs/rules/old.md", " M docs/other.md")
        result = classify_mod.classify(out)
        self.assertEqual(result["other_paths"], ["docs/other.md", "docs/rules/new.md"])
        self.assertNotIn("docs/rules/old.md", result["other_paths"])

    def test_renamed_toc_is_classified_as_toc(self):
        out = _porcelain(f"R  {TOC}b/toc.yaml", f"{TOC}a/toc.yaml")
        result = classify_mod.classify(out)
        self.assertEqual(result["toc_paths"], [f"{TOC}b/toc.yaml"])

    def test_copy_status_also_skips_source_field(self):
        out = _porcelain("C  docs/copy.md", "docs/src.md")
        result = classify_mod.classify(out)
        self.assertEqual(result["other_paths"], ["docs/copy.md"])

    def test_rename_marker_in_worktree_column_also_skips_source(self):
        """status の 2 列目に `R` / `C` が来ても元パスを消費すること。

        実測では porcelain v1 の rename 検出は index 側でのみ行われ、未ステージの rename は
        削除 + 未追跡として現れるため 2 列目に `R` は出ない。しかし片方の列しか見ない実装は、
        git の出力が変わったときに元パスをエントリと誤読して壊れたパスを混ぜる。
        誤読は静かに起きるため、両列を見ることをテストで固定する。
        """
        for status in (" R", " C", "MR"):
            with self.subTest(status=status):
                out = _porcelain(f"{status} docs/new.md", "docs/old.md")
                result = classify_mod.classify(out)
                self.assertEqual(result["other_paths"], ["docs/new.md"])
                self.assertNotIn("docs/old.md", result["other_paths"])

    def test_empty_output(self):
        result = classify_mod.classify("")
        self.assertEqual(result["toc_paths"], [])
        self.assertEqual(result["other_paths"], [])
        self.assertEqual(result["untracked_paths"], [])
        self.assertEqual(result["stale_staged_paths"], [])

    def test_paths_are_sorted(self):
        out = _porcelain(" M docs/z.md", " M docs/a.md")
        result = classify_mod.classify(out)
        self.assertEqual(result["other_paths"], ["docs/a.md", "docs/z.md"])


class StaleStagedTest(unittest.TestCase):
    """index の内容が作業ツリーと食い違う状態の検出。

    この検出が無いと「ステージ済みがあるからそのまま commit」で古い内容が入る。
    commit 後にしか差分が現れないため、気付くのは常に手遅れになる。
    """

    def test_modified_after_staging_is_stale(self):
        out = _porcelain("MM README.md")
        result = classify_mod.classify(out)
        self.assertEqual(result["stale_staged_paths"], ["README.md"])

    def test_added_then_modified_is_stale(self):
        out = _porcelain("AM plugins/forge/skills/consult/SKILL.md")
        result = classify_mod.classify(out)
        self.assertEqual(
            result["stale_staged_paths"], ["plugins/forge/skills/consult/SKILL.md"]
        )

    def test_staged_only_is_not_stale(self):
        out = _porcelain("M  docs/rules/foo.md", "A  docs/new.md")
        result = classify_mod.classify(out)
        self.assertEqual(result["stale_staged_paths"], [])

    def test_unstaged_only_is_not_stale(self):
        out = _porcelain(" M docs/rules/foo.md")
        result = classify_mod.classify(out)
        self.assertEqual(result["stale_staged_paths"], [])

    def test_untracked_is_not_stale(self):
        out = _porcelain("?? docs/new.md")
        result = classify_mod.classify(out)
        self.assertEqual(result["stale_staged_paths"], [])

    def test_conflict_is_not_reported_as_stale(self):
        """衝突（`UU` 等）は別の状態であり、ステージし直しでは解決しない。"""
        out = _porcelain("UU docs/rules/foo.md")
        result = classify_mod.classify(out)
        self.assertEqual(result["stale_staged_paths"], [])

    def test_stale_toc_is_also_reported(self):
        """ToC でも古いステージは検出する（分類とは独立した軸である）。"""
        out = _porcelain(f"MM {TOC}rules-abc/toc.yaml")
        result = classify_mod.classify(out)
        self.assertEqual(result["toc_paths"], [f"{TOC}rules-abc/toc.yaml"])
        self.assertEqual(result["stale_staged_paths"], [f"{TOC}rules-abc/toc.yaml"])

    def test_renamed_then_modified_uses_new_path(self):
        out = _porcelain("RM docs/new.md", "docs/old.md")
        result = classify_mod.classify(out)
        self.assertEqual(result["stale_staged_paths"], ["docs/new.md"])


class PrefixTest(unittest.TestCase):
    def test_prefix_points_at_doc_advisor_toc(self):
        """判定に使う定数が 1 つであること（分類基準を散らさない）。"""
        self.assertEqual(TOC, ".claude/.doc-advisor/toc/")

    def test_similar_but_different_path_is_not_toc(self):
        out = _porcelain(" M .claude/.doc-advisor/guidance/vocabulary.md")
        result = classify_mod.classify(out)
        self.assertEqual(result["toc_paths"], [])
        self.assertEqual(len(result["other_paths"]), 1)


class CliTest(unittest.TestCase):
    def test_cli_outputs_expected_keys_and_exits_zero(self):
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH)],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[3]),
        )
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(
            set(payload.keys()),
            {
                "branch",
                "toc_paths",
                "other_paths",
                "untracked_paths",
                "stale_staged_paths",
            },
        )


if __name__ == "__main__":
    unittest.main()
