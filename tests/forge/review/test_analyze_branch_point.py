#!/usr/bin/env python3
"""
analyze_branch_point.py のテスト（REQ-013 FNC-1312）

一時 git リポジトリを実際に作成し、分岐構造を作り分けて実挙動を検証する
（`test_resolve_targets.py` の方式を踏襲）。

実行:
  python3 -m unittest tests.forge.review.test_analyze_branch_point -v
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "skills" / "review" / "scripts" / "analyze_branch_point.py"
)

_spec = importlib.util.spec_from_file_location("forge_analyze_branch_point", _SCRIPT_PATH)
analyze_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(analyze_mod)


def _git(args, cwd):
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    )
    return result.stdout


def _init_repo(project_root: Path, initial_branch: str = "main"):
    _git(["init", "-b", initial_branch], project_root)
    _git(["config", "user.email", "test@example.com"], project_root)
    _git(["config", "user.name", "Test User"], project_root)
    _git(["config", "commit.gpgSign", "false"], project_root)


def _commit(project_root: Path, rel_path: str, content: str, message: str):
    path = project_root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(["add", "-A"], project_root)
    _git(["commit", "-m", message], project_root)


def _branch_names(result: dict) -> list[str]:
    return [c["branch"] for c in result["candidates"]]


class BranchPointInferenceTest(unittest.TestCase):
    """分岐点の実測に基づく候補の並び（FNC-1312 の中核）。"""

    def test_feature_branched_from_feature_is_ranked_above_develop(self):
        """feature から派生したブランチは、develop より派生元 feature を上位に置く。

        既知名の優先順位（develop → main → master）だけで決めると、この
        ケースで誤って develop を base と判定する。それを防ぐのが本スクリプト。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root, initial_branch="main")
            _commit(project_root, "base.txt", "base\n", "initial")

            _git(["checkout", "-b", "develop"], project_root)
            _commit(project_root, "d.txt", "d\n", "develop commit")

            # develop から feature/parent を切り、コミットを積む
            _git(["checkout", "-b", "feature/parent"], project_root)
            _commit(project_root, "p.txt", "p\n", "parent commit 1")
            _commit(project_root, "p2.txt", "p2\n", "parent commit 2")

            # feature/parent から feature/child を切る
            _git(["checkout", "-b", "feature/child"], project_root)
            _commit(project_root, "c.txt", "c\n", "child commit")

            result = analyze_mod.analyze(project_root)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["target_branch"], "feature/child")

        names = _branch_names(result)
        self.assertEqual(names[0], "feature/parent")
        self.assertLess(names.index("feature/parent"), names.index("develop"))
        self.assertLess(names.index("develop"), names.index("main"))

    def test_ahead_reflects_commits_since_branch_point(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root, initial_branch="main")
            _commit(project_root, "base.txt", "base\n", "initial")

            _git(["checkout", "-b", "feature/x"], project_root)
            _commit(project_root, "a.txt", "a\n", "c1")
            _commit(project_root, "b.txt", "b\n", "c2")
            _commit(project_root, "c.txt", "c\n", "c3")

            result = analyze_mod.analyze(project_root)

        main_entry = next(c for c in result["candidates"] if c["branch"] == "main")
        self.assertEqual(main_entry["ahead"], 3)
        self.assertEqual(main_entry["behind"], 0)

    def test_behind_reflects_commits_on_candidate_side(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root, initial_branch="main")
            _commit(project_root, "base.txt", "base\n", "initial")

            _git(["checkout", "-b", "feature/x"], project_root)
            _commit(project_root, "a.txt", "a\n", "feature commit")

            # base 側だけを進める
            _git(["checkout", "main"], project_root)
            _commit(project_root, "m.txt", "m\n", "main commit 1")
            _commit(project_root, "m2.txt", "m2\n", "main commit 2")
            _git(["checkout", "feature/x"], project_root)

            result = analyze_mod.analyze(project_root)

        main_entry = next(c for c in result["candidates"] if c["branch"] == "main")
        self.assertEqual(main_entry["ahead"], 1)
        self.assertEqual(main_entry["behind"], 2)

    def test_target_branch_itself_is_not_a_candidate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root, initial_branch="main")
            _commit(project_root, "base.txt", "base\n", "initial")
            _git(["checkout", "-b", "feature/x"], project_root)
            _commit(project_root, "a.txt", "a\n", "c1")

            result = analyze_mod.analyze(project_root)

        self.assertNotIn("feature/x", _branch_names(result))


class ConfiguredBaseTest(unittest.TestCase):
    """`.git_information.yaml` の値は参考情報であり、採用権限を持たない。"""

    def test_configured_base_is_reported_but_does_not_outrank_closer_branch(self):
        """設定値があっても、分岐点がより近い候補を追い越さない。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root, initial_branch="main")
            _commit(project_root, "base.txt", "base\n", "initial")

            _git(["checkout", "-b", "develop"], project_root)
            _commit(project_root, "d.txt", "d\n", "develop commit")

            _git(["checkout", "-b", "feature/parent"], project_root)
            _commit(project_root, "p.txt", "p\n", "parent commit")

            _git(["checkout", "-b", "feature/child"], project_root)
            _commit(project_root, "c.txt", "c\n", "child commit")

            (project_root / ".git_information.yaml").write_text(
                "default_base_branch: develop\n", encoding="utf-8"
            )

            result = analyze_mod.analyze(project_root)

        self.assertEqual(result["configured_base"], "develop")
        names = _branch_names(result)
        self.assertEqual(names[0], "feature/parent")

        develop_entry = next(c for c in result["candidates"] if c["branch"] == "develop")
        self.assertTrue(develop_entry["is_configured"])

    def test_configured_base_wins_only_among_ties(self):
        """分岐点が同一で並ぶ候補のうち、設定値を先頭にする。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root, initial_branch="main")
            _commit(project_root, "base.txt", "base\n", "initial")

            # 同一コミットから develop と zzz-other を作る（分岐点が並ぶ）
            _git(["branch", "develop"], project_root)
            _git(["branch", "aaa-other"], project_root)

            _git(["checkout", "-b", "feature/x"], project_root)
            _commit(project_root, "a.txt", "a\n", "c1")

            (project_root / ".git_information.yaml").write_text(
                "default_base_branch: develop\n", encoding="utf-8"
            )

            result = analyze_mod.analyze(project_root)

        candidates = result["candidates"]
        tied = [c for c in candidates if c["ahead"] == candidates[0]["ahead"]]
        # 名前順なら aaa-other が先。設定値の develop が先頭に来ることを確認する
        self.assertGreater(len(tied), 1)
        self.assertEqual(candidates[0]["branch"], "develop")

    def test_no_config_file_yields_null_configured_base(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root, initial_branch="main")
            _commit(project_root, "base.txt", "base\n", "initial")
            _git(["checkout", "-b", "feature/x"], project_root)
            _commit(project_root, "a.txt", "a\n", "c1")

            result = analyze_mod.analyze(project_root)

        self.assertIsNone(result["configured_base"])
        self.assertTrue(all(not c["is_configured"] for c in result["candidates"]))


class RemoteTrackingTest(unittest.TestCase):
    """ローカルに無い base は origin/<name> として解決する。"""

    def test_remote_only_branch_is_resolved_with_origin_prefix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            origin = root / "origin"
            clone = root / "clone"
            origin.mkdir()

            _init_repo(origin, initial_branch="develop")
            _commit(origin, "base.txt", "base\n", "initial")

            subprocess.run(
                ["git", "clone", str(origin), str(clone)],
                capture_output=True, text=True, check=True,
            )
            _git(["config", "user.email", "test@example.com"], clone)
            _git(["config", "user.name", "Test User"], clone)
            _git(["config", "commit.gpgSign", "false"], clone)

            _git(["checkout", "-b", "feature/x"], clone)
            _commit(clone, "a.txt", "a\n", "c1")
            # ローカルの develop を消し、remote-tracking のみにする
            _git(["branch", "-D", "develop"], clone)

            result = analyze_mod.analyze(clone)

        develop_entry = next(
            (c for c in result["candidates"] if c["branch"] == "develop"), None
        )
        self.assertIsNotNone(develop_entry)
        self.assertEqual(develop_entry["ref"], "origin/develop")


class ErrorAndCliTest(unittest.TestCase):
    def test_non_git_directory_is_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = analyze_mod.analyze(Path(tmpdir))

        self.assertEqual(result["status"], "error")
        self.assertIn("git", result["error"])

    def test_detached_head_reports_null_target_branch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root, initial_branch="main")
            _commit(project_root, "base.txt", "base\n", "initial")
            _commit(project_root, "a.txt", "a\n", "c1")
            sha = _git(["rev-parse", "HEAD~1"], project_root).strip()
            _git(["checkout", sha], project_root)

            result = analyze_mod.analyze(project_root)

        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["target_branch"])

    def test_cli_outputs_single_json_line_with_exit_code_0(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root, initial_branch="main")
            _commit(project_root, "base.txt", "base\n", "initial")
            _git(["checkout", "-b", "feature/x"], project_root)
            _commit(project_root, "a.txt", "a\n", "c1")

            proc = subprocess.run(
                [sys.executable, str(_SCRIPT_PATH), "--project-root", str(project_root)],
                capture_output=True, text=True,
            )

        self.assertEqual(proc.returncode, 0)
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["target_branch"], "feature/x")


if __name__ == "__main__":
    unittest.main()
