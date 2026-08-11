"""inspect_stage_state.py の単体テスト（anvil:commit Phase 3）。

`git status --porcelain -z` の分解を固定する。とくに次は行ベースの手動パースで取り違える形であり、
テストで固定しないと静かに壊れる。

- 空白・非 ASCII を含むパス（`-z` を使わないと quote 表記になる）
- rename / copy（`R` / `C` は 1 エントリに元パスと新パスの 2 フィールドを持つ）
- ステージ済み・未ステージ・未追跡の混在
- index と作業ツリーの食い違い（`MM` / `AM`。2 文字表記にしか現れない）
"""

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "anvil" / "skills" / "commit" / "scripts" / "inspect_stage_state.py"
)

_spec = importlib.util.spec_from_file_location("anvil_inspect_stage_state", _SCRIPT_PATH)
inspect_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inspect_mod)


def _porcelain(*entries: str) -> str:
    """NUL 区切りの porcelain 出力を組み立てる（各エントリは末尾に NUL）。"""
    return "".join(e + "\0" for e in entries)


class TrackedAndUntrackedTest(unittest.TestCase):
    def test_staged_and_unstaged_are_both_tracked(self):
        out = _porcelain("M  docs/a.md", " M docs/b.md")
        result = inspect_mod.inspect(out)
        self.assertEqual(result["tracked_paths"], ["docs/a.md", "docs/b.md"])

    def test_untracked_is_separated(self):
        out = _porcelain("?? docs/new.md", " M docs/rules/foo.md")
        result = inspect_mod.inspect(out)
        self.assertEqual(result["untracked_paths"], ["docs/new.md"])
        self.assertEqual(result["tracked_paths"], ["docs/rules/foo.md"])

    def test_generated_index_is_not_special_cased(self):
        """ToC 除外は撤回済み。生成物も追跡済みの変更として同じく扱う。"""
        out = _porcelain(" M .claude/.doc-advisor/toc/rules-abc/toc.yaml", " M docs/a.md")
        result = inspect_mod.inspect(out)
        self.assertEqual(
            result["tracked_paths"],
            [".claude/.doc-advisor/toc/rules-abc/toc.yaml", "docs/a.md"],
        )

    def test_path_with_spaces_and_non_ascii(self):
        out = _porcelain(" M docs/仕様 と 設計.md")
        result = inspect_mod.inspect(out)
        self.assertEqual(result["tracked_paths"], ["docs/仕様 と 設計.md"])

    def test_rename_uses_new_path_and_skips_old(self):
        out = _porcelain("R  docs/new.md", "docs/old.md", " M docs/other.md")
        result = inspect_mod.inspect(out)
        self.assertEqual(result["tracked_paths"], ["docs/new.md", "docs/other.md"])

    def test_copy_status_also_skips_source_field(self):
        out = _porcelain("C  docs/copy.md", "docs/src.md")
        result = inspect_mod.inspect(out)
        self.assertEqual(result["tracked_paths"], ["docs/copy.md"])

    def test_rename_marker_in_either_column_skips_source(self):
        """2 列のどちらに R / C が出ても元パスをエントリと誤読しない。

        片方の列しか見ない実装への退行は静かに起きる（壊れたパスが tracked_paths に混ざる）。
        """
        for status in (" R", " C", "MR"):
            with self.subTest(status=status):
                out = _porcelain(f"{status} docs/new.md", "docs/old.md")
                result = inspect_mod.inspect(out)
                self.assertEqual(result["tracked_paths"], ["docs/new.md"])

    def test_empty_output(self):
        result = inspect_mod.inspect("")
        self.assertEqual(result["tracked_paths"], [])
        self.assertEqual(result["untracked_paths"], [])
        self.assertEqual(result["stale_staged_paths"], [])

    def test_paths_are_sorted(self):
        out = _porcelain(" M docs/z.md", " M docs/a.md")
        result = inspect_mod.inspect(out)
        self.assertEqual(result["tracked_paths"], ["docs/a.md", "docs/z.md"])


class StaleStagedTest(unittest.TestCase):
    """index の内容が作業ツリーと食い違う状態の検出。

    この検出が無いと「ステージ済みがあるからそのまま commit」で古い内容が入る。
    commit 後にしか差分が現れないため、気付くのは常に手遅れになる。
    """

    def test_modified_after_staging_is_stale(self):
        out = _porcelain("MM README.md")
        result = inspect_mod.inspect(out)
        self.assertEqual(result["stale_staged_paths"], ["README.md"])

    def test_added_then_modified_is_stale(self):
        out = _porcelain("AM plugins/forge/skills/consult/SKILL.md")
        result = inspect_mod.inspect(out)
        self.assertEqual(
            result["stale_staged_paths"], ["plugins/forge/skills/consult/SKILL.md"]
        )

    def test_staged_only_is_not_stale(self):
        out = _porcelain("M  docs/rules/foo.md", "A  docs/new.md")
        result = inspect_mod.inspect(out)
        self.assertEqual(result["stale_staged_paths"], [])

    def test_unstaged_only_is_not_stale(self):
        out = _porcelain(" M docs/rules/foo.md")
        result = inspect_mod.inspect(out)
        self.assertEqual(result["stale_staged_paths"], [])

    def test_untracked_is_not_stale(self):
        out = _porcelain("?? docs/new.md")
        result = inspect_mod.inspect(out)
        self.assertEqual(result["stale_staged_paths"], [])

    def test_conflict_is_not_reported_as_stale(self):
        """衝突（`UU` 等）は別の状態であり、ステージし直しでは解決しない。"""
        out = _porcelain("UU docs/rules/foo.md")
        result = inspect_mod.inspect(out)
        self.assertEqual(result["stale_staged_paths"], [])

    def test_renamed_then_modified_uses_new_path(self):
        out = _porcelain("RM docs/new.md", "docs/old.md")
        result = inspect_mod.inspect(out)
        self.assertEqual(result["stale_staged_paths"], ["docs/new.md"])


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
            {"tracked_paths", "untracked_paths", "stale_staged_paths"},
        )


if __name__ == "__main__":
    unittest.main()
