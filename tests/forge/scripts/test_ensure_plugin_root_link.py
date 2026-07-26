#!/usr/bin/env python3
"""ensure_plugin_root_link.py のテスト。

実行:
  python3 -m unittest tests.forge.scripts.test_ensure_plugin_root_link -v
"""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "scripts" / "ensure_plugin_root_link.py"
)

_spec = importlib.util.spec_from_file_location("ensure_plugin_root_link", _SCRIPT_PATH)
ensure_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ensure_mod)


def _init_repo(tmpdir: str) -> Path:
    project_root = Path(tmpdir)
    subprocess.run(["git", "init", "-q"], cwd=tmpdir, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmpdir, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmpdir, check=True)
    return project_root


class EnsureGitignoreEntryTest(unittest.TestCase):
    def test_adds_entry_when_gitignore_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            result = ensure_mod._ensure_gitignore_entry(project_root, ".claude/forge-docs", "comment")

            self.assertEqual(result["status"], "added")
            content = (project_root / ".gitignore").read_text(encoding="utf-8")
            self.assertIn(".claude/forge-docs", content.splitlines())

    def test_already_present_is_idempotent_and_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            ensure_mod._ensure_gitignore_entry(project_root, ".claude/forge-docs", "comment")
            result = ensure_mod._ensure_gitignore_entry(project_root, ".claude/forge-docs", "comment")

            self.assertEqual(result["status"], "already_present")
            content = (project_root / ".gitignore").read_text(encoding="utf-8")
            self.assertEqual(content.count(".claude/forge-docs"), 1)


class EnsureSymlinkTest(unittest.TestCase):
    def test_creates_symlink_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as plugin_docs_dir:
            project_root = _init_repo(tmpdir)
            result = ensure_mod._ensure_symlink(project_root, Path(plugin_docs_dir), "forge-docs")

            self.assertEqual(result["status"], "created")
            link = project_root / ".claude" / "forge-docs"
            self.assertTrue(link.is_symlink())
            self.assertEqual(str(link.resolve()), str(Path(plugin_docs_dir).resolve()))

    def test_unchanged_when_symlink_already_correct(self):
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as plugin_docs_dir:
            project_root = _init_repo(tmpdir)
            ensure_mod._ensure_symlink(project_root, Path(plugin_docs_dir), "forge-docs")
            result = ensure_mod._ensure_symlink(project_root, Path(plugin_docs_dir), "forge-docs")

            self.assertEqual(result["status"], "unchanged")

    def test_repairs_symlink_pointing_elsewhere(self):
        """プラグイン再インストール等で実体パスが変わった場合に追随する（本機能の主目的）。"""
        with tempfile.TemporaryDirectory() as tmpdir, \
             tempfile.TemporaryDirectory() as old_docs_dir, \
             tempfile.TemporaryDirectory() as new_docs_dir:
            project_root = _init_repo(tmpdir)
            ensure_mod._ensure_symlink(project_root, Path(old_docs_dir), "forge-docs")
            result = ensure_mod._ensure_symlink(project_root, Path(new_docs_dir), "forge-docs")

            self.assertEqual(result["status"], "repaired")
            link = project_root / ".claude" / "forge-docs"
            self.assertEqual(str(link.resolve()), str(Path(new_docs_dir).resolve()))

    def test_repairs_dangling_symlink(self):
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as docs_parent:
            project_root = _init_repo(tmpdir)
            vanished_target = Path(docs_parent) / "vanished_version"
            vanished_target.mkdir()
            ensure_mod._ensure_symlink(project_root, vanished_target, "forge-docs")
            vanished_target.rmdir()

            new_target = Path(docs_parent) / "new_version"
            new_target.mkdir()
            result = ensure_mod._ensure_symlink(project_root, new_target, "forge-docs")

            self.assertEqual(result["status"], "repaired")

    def test_conflict_when_real_directory_exists_instead_of_symlink(self):
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as plugin_docs_dir:
            project_root = _init_repo(tmpdir)
            real_dir = project_root / ".claude" / "forge-docs"
            real_dir.mkdir(parents=True)
            (real_dir / "important_human_file.txt").write_text("do not delete", encoding="utf-8")

            result = ensure_mod._ensure_symlink(project_root, Path(plugin_docs_dir), "forge-docs")

            self.assertEqual(result["status"], "conflict")
            self.assertTrue((real_dir / "important_human_file.txt").is_file())

    def test_multiple_link_names_coexist(self):
        """複数プラグイン（forge-docs / anvil-docs 等）の symlink が .claude/ 配下で共存できる。"""
        with tempfile.TemporaryDirectory() as tmpdir, \
             tempfile.TemporaryDirectory() as forge_docs_dir, \
             tempfile.TemporaryDirectory() as anvil_docs_dir:
            project_root = _init_repo(tmpdir)
            ensure_mod._ensure_symlink(project_root, Path(forge_docs_dir), "forge-docs")
            ensure_mod._ensure_symlink(project_root, Path(anvil_docs_dir), "anvil-docs")

            claude_dir = project_root / ".claude"
            self.assertEqual(str((claude_dir / "forge-docs").resolve()), str(Path(forge_docs_dir).resolve()))
            self.assertEqual(str((claude_dir / "anvil-docs").resolve()), str(Path(anvil_docs_dir).resolve()))


class EnsureEndToEndTest(unittest.TestCase):
    def test_ensure_creates_working_symlink_and_gitignore(self):
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as plugin_docs_dir:
            project_root = _init_repo(tmpdir)
            (Path(plugin_docs_dir) / "marker.txt").write_text("hello", encoding="utf-8")

            result = ensure_mod.ensure(str(project_root), plugin_docs_dir, "forge-docs")

            self.assertEqual(result["symlink"]["status"], "created")
            self.assertEqual(result["gitignore"]["status"], "added")
            linked_marker = project_root / ".claude" / "forge-docs" / "marker.txt"
            self.assertEqual(linked_marker.read_text(encoding="utf-8"), "hello")

    def test_idempotent_second_run_reports_unchanged(self):
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as plugin_docs_dir:
            project_root = _init_repo(tmpdir)
            ensure_mod.ensure(str(project_root), plugin_docs_dir, "forge-docs")
            result = ensure_mod.ensure(str(project_root), plugin_docs_dir, "forge-docs")

            self.assertEqual(result["symlink"]["status"], "unchanged")
            self.assertEqual(result["gitignore"]["status"], "already_present")


class MainTest(unittest.TestCase):
    def test_cli_outputs_single_json(self):
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as plugin_docs_dir:
            project_root = _init_repo(tmpdir)
            result = subprocess.run(
                [
                    "python3", str(_SCRIPT_PATH),
                    "--project-root", str(project_root),
                    "--plugin-root", plugin_docs_dir,
                    "--link-name", "forge-docs",
                ],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["symlink"]["status"], "created")
            self.assertEqual(payload["gitignore"]["status"], "added")

    def test_cli_never_fails_even_with_bad_project_root(self):
        """SessionStart フックは fail-open が必須（利便性機能でセッション開始を阻害しない）。"""
        result = subprocess.run(
            [
                "python3", str(_SCRIPT_PATH),
                "--project-root", "/nonexistent/path/xyz",
                "--plugin-root", "/nonexistent/plugin/xyz",
                "--link-name", "forge-docs",
            ],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        json.loads(result.stdout)  # 例外を投げず JSON が出力されること


if __name__ == "__main__":
    unittest.main()
