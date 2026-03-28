#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""create_pending_yaml.py のユニットテスト。

テスト対象:
- --full モード（pending YAML 生成）
- --check モード（staleness check）
- 空ディレクトリの処理

移行元: test_setup_upgrade.sh の create_pending 関連テスト
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# テスト対象スクリプトのパス
SCRIPTS_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'plugins', 'doc-advisor', 'scripts'
))
CREATE_PENDING_SCRIPT = os.path.join(SCRIPTS_DIR, 'create_pending_yaml.py')


class TestCreatePendingBase(unittest.TestCase):
    """テスト用の共通セットアップ"""

    def setUp(self):
        """一時ディレクトリとテスト用プロジェクト構造を作成"""
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = self.tmpdir

        # .git ディレクトリ作成（get_project_root() が認識するため）
        os.makedirs(os.path.join(self.project_root, '.git'))

        # .doc_structure.yaml 作成
        self._write_doc_structure()

        # ToC ディレクトリ作成
        self.toc_dir = os.path.join(
            self.project_root, '.claude', 'doc-advisor', 'toc', 'rules'
        )
        os.makedirs(self.toc_dir, exist_ok=True)

    def tearDown(self):
        """一時ディレクトリを削除"""
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_doc_structure(self):
        """テスト用 .doc_structure.yaml を作成"""
        content = """\
# doc_structure_version: 3.0

rules:
  root_dirs:
    - rules/
  doc_types_map:
    rules/: rule
  patterns:
    target_glob: "**/*.md"
    exclude: []

specs:
  root_dirs:
    - specs/
  doc_types_map:
    specs/: spec
  patterns:
    target_glob: "**/*.md"
    exclude: []
"""
        with open(os.path.join(self.project_root, '.doc_structure.yaml'), 'w') as f:
            f.write(content)

    def _create_rule_file(self, rel_path, content='# Test Rule\n\nThis is a test rule document.\n'):
        """rules/ 配下にテスト用 .md ファイルを作成"""
        full_path = os.path.join(self.project_root, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w') as f:
            f.write(content)
        return full_path

    def _run_create_pending(self, *extra_args, category='rules'):
        """create_pending_yaml.py を subprocess で実行"""
        cmd = [
            sys.executable, CREATE_PENDING_SCRIPT,
            '--category', category,
        ] + list(extra_args)
        env = os.environ.copy()
        env['CLAUDE_PROJECT_DIR'] = self.project_root
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=self.project_root, env=env
        )
        return result


class TestCreatePendingFull(TestCreatePendingBase):
    """--full モードのテスト"""

    def test_full_mode_creates_pending_yamls(self):
        """--full モードで pending YAML が生成されること"""
        self._create_rule_file('rules/test_rule.md')
        self._create_rule_file('rules/sub/nested_rule.md')

        result = self._run_create_pending('--full')

        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        self.assertIn('Created 2 pending YAMLs', result.stdout)

        # .toc_work ディレクトリが作成されていること
        work_dir = os.path.join(self.toc_dir, '.toc_work')
        self.assertTrue(os.path.isdir(work_dir), f".toc_work が作成されていない: {work_dir}")

        # YAML ファイルが存在すること（ハッシュベースのファイル名）
        yaml_files = [f for f in os.listdir(work_dir) if f.endswith('.yaml') and not f.startswith('.')]
        self.assertEqual(len(yaml_files), 2, f"期待: 2件、実際: {yaml_files}")

    def test_full_mode_skips_empty_files(self):
        """--full モードで空ファイルがスキップされること"""
        self._create_rule_file('rules/empty.md', content='')
        self._create_rule_file('rules/headers_only.md', content='# Header Only\n\n## Sub Header\n')
        self._create_rule_file('rules/valid.md', content='# Valid\n\nSome content here.\n')

        result = self._run_create_pending('--full')

        self.assertEqual(result.returncode, 0)
        self.assertIn('Created 1 pending YAMLs', result.stdout)
        self.assertIn('Skipped', result.stdout)

    def test_full_mode_pending_yaml_content(self):
        """生成された pending YAML の内容が正しいこと"""
        self._create_rule_file('rules/test.md')

        result = self._run_create_pending('--full')
        self.assertEqual(result.returncode, 0)

        # pending YAML の中身を確認
        work_dir = os.path.join(self.toc_dir, '.toc_work')
        yaml_files = [f for f in os.listdir(work_dir) if f.endswith('.yaml') and not f.startswith('.')]
        self.assertEqual(len(yaml_files), 1)

        with open(os.path.join(work_dir, yaml_files[0]), 'r') as f:
            content = f.read()

        self.assertIn('source_file: rules/test.md', content)
        self.assertIn('doc_type: rule', content)
        self.assertIn('status: pending', content)


class TestCreatePendingCheck(TestCreatePendingBase):
    """--check モード（staleness check）のテスト"""

    def test_check_mode_no_toc_file(self):
        """ToC ファイルが存在しない場合の --check モード"""
        self._create_rule_file('rules/test.md')

        result = self._run_create_pending('--check')

        self.assertEqual(result.returncode, 0)
        self.assertIn('WARNING: ToC not found', result.stdout)

    def test_check_mode_stale_detection(self):
        """変更があった場合に WARNING が出力されること"""
        # まず full モードで ToC 生成環境を構築
        self._create_rule_file('rules/test.md')
        self._run_create_pending('--full')

        # checksums ファイルを作成（空の checksums で新規ファイルとして検出させる）
        checksums_file = os.path.join(self.toc_dir, '.toc_checksums.yaml')
        with open(checksums_file, 'w') as f:
            f.write('checksums:\n')

        # rules_toc.yaml を作成（--check が ToC 存在確認するため）
        toc_file = os.path.join(self.toc_dir, 'rules_toc.yaml')
        with open(toc_file, 'w') as f:
            f.write('docs:\n  rules/test.md:\n    title: "Test"\n')

        result = self._run_create_pending('--check')

        self.assertEqual(result.returncode, 0)
        self.assertIn('WARNING: ToC may be stale', result.stdout)
        self.assertIn('1 new', result.stdout)


class TestCreatePendingEmptyDir(TestCreatePendingBase):
    """空ディレクトリの処理テスト"""

    def test_empty_root_dir(self):
        """root_dirs に指定されたディレクトリが空の場合"""
        os.makedirs(os.path.join(self.project_root, 'rules'), exist_ok=True)

        result = self._run_create_pending('--full')

        self.assertEqual(result.returncode, 0)
        self.assertIn('Created 0 pending YAMLs', result.stdout)

    def test_nonexistent_root_dir(self):
        """root_dirs に指定されたディレクトリが存在しない場合"""
        # rules/ ディレクトリを作成しない

        result = self._run_create_pending('--full')

        self.assertEqual(result.returncode, 0)
        self.assertIn('Warning:', result.stdout)


if __name__ == '__main__':
    unittest.main()
