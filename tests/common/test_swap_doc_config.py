#!/usr/bin/env python3
"""
swap_doc_config.py のユニットテスト

store / restore によるバックアップと復元を検証する。
実際のプロジェクトファイルには触れず、一時ディレクトリ内で動作する。

実行:
  python3 -m unittest tests.common.test_swap_doc_config -v
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / ".claude" / "skills" / "update-forge-toc" / "scripts"
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "update-forge-toc"


def _run_swap(args, project_root, skill_dir_override=None):
    """Run swap_doc_config logic in-process with captured stdout."""
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        import importlib
        mod = importlib.import_module("swap_doc_config")
        importlib.reload(mod)

        original_skill_dir = mod.SKILL_DIR
        original_backup_dir = mod.BACKUP_DIR
        original_forge_doc = mod.FORGE_DOC_STRUCTURE

        effective_skill_dir = skill_dir_override or skill_dir_override or original_skill_dir
        mod.SKILL_DIR = effective_skill_dir
        mod.BACKUP_DIR = effective_skill_dir / ".backup"
        mod.FORGE_DOC_STRUCTURE = effective_skill_dir / "forge_doc_structure.yaml"

        from io import StringIO
        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        try:
            with patch("swap_doc_config.get_project_root", return_value=project_root):
                if "--store" in args:
                    force = "--force" in args
                    exit_code = mod.store(project_root, force=force)
                elif "--restore" in args:
                    exit_code = mod.restore(project_root)
                else:
                    exit_code = 1
        finally:
            sys.stdout = old_stdout
            mod.SKILL_DIR = original_skill_dir
            mod.BACKUP_DIR = original_backup_dir
            mod.FORGE_DOC_STRUCTURE = original_forge_doc

        output = captured.getvalue()
        return exit_code, json.loads(output) if output.strip() else {}
    finally:
        sys.path.pop(0)
        if "swap_doc_config" in sys.modules:
            del sys.modules["swap_doc_config"]


class TestSwapDocConfig(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.project_root = self.tmpdir / "project"
        self.project_root.mkdir()

        self.skill_dir = self.tmpdir / "skill"
        self.skill_dir.mkdir()
        (self.skill_dir / "scripts").mkdir()

        shutil.copy2(
            SKILL_DIR / "forge_doc_structure.yaml",
            self.skill_dir / "forge_doc_structure.yaml",
        )

        self.doc_structure = self.project_root / ".doc_structure.yaml"
        self.doc_structure.write_text("original: true\n", encoding="utf-8")

        toc_dir = self.project_root / ".claude" / "doc-advisor" / "toc" / "rules"
        toc_dir.mkdir(parents=True)
        (toc_dir / "rules_toc.yaml").write_text("metadata:\n  name: original\n", encoding="utf-8")
        (toc_dir / ".toc_checksums.yaml").write_text("checksums: {}\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_store_creates_backup_and_replaces_doc_structure(self):
        code, result = _run_swap(["--store"], self.project_root, self.skill_dir)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["action"], "store")
        self.assertIn(".doc_structure.yaml", result["backed_up"])

        backup_dir = self.skill_dir / ".backup"
        self.assertTrue(backup_dir.exists())
        self.assertTrue((backup_dir / ".doc_structure.yaml").exists())
        self.assertTrue((backup_dir / ".claude" / "doc-advisor" / "toc" / "rules" / "rules_toc.yaml").exists())
        self.assertTrue((backup_dir / ".claude" / "doc-advisor" / "toc" / "rules" / ".toc_checksums.yaml").exists())

        replaced = self.doc_structure.read_text(encoding="utf-8")
        self.assertIn("plugins/forge/docs/", replaced)
        self.assertNotIn("original: true", replaced)

    def test_store_rejects_double_store(self):
        _run_swap(["--store"], self.project_root, self.skill_dir)
        code, result = _run_swap(["--store"], self.project_root, self.skill_dir)
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "error")
        self.assertIn("Backup already exists", result["message"])

    def test_store_force_overwrites_backup(self):
        _run_swap(["--store"], self.project_root, self.skill_dir)

        self.doc_structure.write_text("second: true\n", encoding="utf-8")

        code, result = _run_swap(["--store", "--force"], self.project_root, self.skill_dir)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "ok")

        backup_content = (self.skill_dir / ".backup" / ".doc_structure.yaml").read_text(encoding="utf-8")
        self.assertIn("second: true", backup_content)

    def test_restore_recovers_original_files(self):
        original_content = self.doc_structure.read_text(encoding="utf-8")
        _run_swap(["--store"], self.project_root, self.skill_dir)

        code, result = _run_swap(["--restore"], self.project_root, self.skill_dir)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["action"], "restore")

        restored = self.doc_structure.read_text(encoding="utf-8")
        self.assertEqual(restored, original_content)

        self.assertFalse((self.skill_dir / ".backup").exists())

    def test_restore_without_backup_fails(self):
        code, result = _run_swap(["--restore"], self.project_root, self.skill_dir)
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "error")
        self.assertIn("No backup found", result["message"])

    def test_store_handles_missing_optional_files(self):
        (self.project_root / ".claude" / "doc-advisor" / "toc" / "rules" / ".toc_checksums.yaml").unlink()

        code, result = _run_swap(["--store"], self.project_root, self.skill_dir)
        self.assertEqual(code, 0)
        self.assertNotIn(".claude/doc-advisor/toc/rules/.toc_checksums.yaml", result["backed_up"])

    def test_roundtrip_preserves_all_files(self):
        toc_path = self.project_root / ".claude" / "doc-advisor" / "toc" / "rules" / "rules_toc.yaml"
        checksum_path = self.project_root / ".claude" / "doc-advisor" / "toc" / "rules" / ".toc_checksums.yaml"

        originals = {
            ".doc_structure.yaml": self.doc_structure.read_text(encoding="utf-8"),
            "rules_toc.yaml": toc_path.read_text(encoding="utf-8"),
            ".toc_checksums.yaml": checksum_path.read_text(encoding="utf-8"),
        }

        _run_swap(["--store"], self.project_root, self.skill_dir)
        _run_swap(["--restore"], self.project_root, self.skill_dir)

        self.assertEqual(self.doc_structure.read_text(encoding="utf-8"), originals[".doc_structure.yaml"])
        self.assertEqual(toc_path.read_text(encoding="utf-8"), originals["rules_toc.yaml"])
        self.assertEqual(checksum_path.read_text(encoding="utf-8"), originals[".toc_checksums.yaml"])


if __name__ == "__main__":
    unittest.main()
