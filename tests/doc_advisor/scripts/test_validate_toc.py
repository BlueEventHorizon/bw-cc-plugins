#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_toc.py のユニットテスト。

テスト対象:
- title 欠損の ToC → 非ゼロ exit code
- 存在しないファイル参照の ToC → 非ゼロ exit code
- 正常な ToC → exit code 0
- root_dirs: [] 空配列で validate_toc.py がクラッシュしないこと

移行元:
- test_setup_upgrade.sh Test 27（validate_toc.py 異常入力）
- test_setup_upgrade.sh Test 28（root_dirs: [] 空配列）
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
VALIDATE_SCRIPT = os.path.join(SCRIPTS_DIR, 'validate_toc.py')


class TestValidateTocBase(unittest.TestCase):
    """テスト用の共通セットアップ"""

    def setUp(self):
        """一時ディレクトリとテスト用プロジェクト構造を作成"""
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = self.tmpdir

        # .git ディレクトリ作成
        os.makedirs(os.path.join(self.project_root, '.git'))

        # rules/ ディレクトリ作成
        os.makedirs(os.path.join(self.project_root, 'rules'), exist_ok=True)

        # ToC ディレクトリ作成
        self.toc_dir = os.path.join(
            self.project_root, '.claude', 'doc-advisor', 'toc', 'rules'
        )
        os.makedirs(self.toc_dir, exist_ok=True)

        # .doc_structure.yaml 作成
        self._write_doc_structure()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_doc_structure(self, content=None):
        """テスト用 .doc_structure.yaml を作成"""
        if content is None:
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

    def _write_toc(self, content, filename='rules_toc.yaml'):
        """ToC ファイルを作成"""
        toc_path = os.path.join(self.toc_dir, filename)
        with open(toc_path, 'w') as f:
            f.write(content)
        return toc_path

    def _run_validate(self, category='rules', toc_file=None):
        """validate_toc.py を subprocess で実行"""
        cmd = [sys.executable, VALIDATE_SCRIPT, '--category', category]
        if toc_file:
            cmd.extend(['--file', toc_file])
        env = os.environ.copy()
        env['CLAUDE_PROJECT_DIR'] = self.project_root
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=self.project_root, env=env
        )
        return result


class TestValidateTocAbnormalInput(TestValidateTocBase):
    """異常入力のテスト（Test 27 移行）"""

    def test_missing_required_fields(self):
        """title 欠損の ToC → 非ゼロ exit code"""
        toc_content = """\
docs:
  rules/test.md:
    purpose: "test purpose"
    content_details:
      - "detail 1"
    applicable_tasks:
      - "task 1"
"""
        # 参照先ファイルを作成（ファイル参照検査を通すため）
        test_file = os.path.join(self.project_root, 'rules', 'test.md')
        with open(test_file, 'w') as f:
            f.write('# Test\n\nContent.\n')

        toc_path = self._write_toc(toc_content)
        result = self._run_validate(toc_file=toc_path)

        self.assertNotEqual(result.returncode, 0,
                            f"title 欠損で exit 0 が返された。stdout: {result.stdout}")

    def test_nonexistent_file_reference(self):
        """存在しないファイル参照の ToC → 非ゼロ exit code"""
        toc_content = """\
docs:
  rules/nonexistent_file.md:
    title: "Ghost Document"
    purpose: "References a file that does not exist"
    doc_type: "rule"
    content_details:
      - "detail 1"
    applicable_tasks:
      - "task 1"
    keywords:
      - "test"
"""
        toc_path = self._write_toc(toc_content)
        result = self._run_validate(toc_file=toc_path)

        self.assertNotEqual(result.returncode, 0,
                            f"存在しないファイル参照で exit 0 が返された。stdout: {result.stdout}")

    def test_valid_toc(self):
        """正常な ToC → exit code 0"""
        # 参照先ファイルを作成
        test_file = os.path.join(self.project_root, 'rules', 'test.md')
        with open(test_file, 'w') as f:
            f.write('# Test Rule\n\nContent.\n')

        toc_content = """\
docs:
  rules/test.md:
    title: "Test Rule"
    purpose: "A test rule document"
    doc_type: "rule"
    content_details:
      - "contains test rules"
    applicable_tasks:
      - "testing"
    keywords:
      - "test"
      - "rule"
"""
        toc_path = self._write_toc(toc_content)
        result = self._run_validate(toc_file=toc_path)

        self.assertEqual(result.returncode, 0,
                         f"正常な ToC で非ゼロ exit code が返された。stdout: {result.stdout}")


class TestValidateTocEmptyRootDirs(TestValidateTocBase):
    """root_dirs: [] 空配列のテスト（Test 28 移行）"""

    def test_empty_root_dirs_rules_no_crash(self):
        """root_dirs: [] で validate_toc.py --category rules がクラッシュしないこと"""
        self._write_doc_structure("""\
# doc_structure_version: 3.0

rules:
  root_dirs: []
  doc_types_map: {}
  patterns:
    target_glob: "**/*.md"
    exclude: []

specs:
  root_dirs: []
  doc_types_map: {}
  patterns:
    target_glob: "**/*.md"
    exclude: []
""")

        result = self._run_validate(category='rules')

        # IndexError でクラッシュしていないことを確認
        combined_output = result.stdout + result.stderr
        self.assertNotIn('IndexError', combined_output,
                         "validate_toc.py が IndexError でクラッシュした")
        self.assertNotIn('Traceback', combined_output,
                         f"validate_toc.py が例外でクラッシュした: {combined_output}")

    def test_empty_root_dirs_specs_no_crash(self):
        """root_dirs: [] で validate_toc.py --category specs がクラッシュしないこと"""
        # specs 用の ToC ディレクトリも作成
        specs_toc_dir = os.path.join(
            self.project_root, '.claude', 'doc-advisor', 'toc', 'specs'
        )
        os.makedirs(specs_toc_dir, exist_ok=True)

        self._write_doc_structure("""\
# doc_structure_version: 3.0

rules:
  root_dirs: []
  doc_types_map: {}
  patterns:
    target_glob: "**/*.md"
    exclude: []

specs:
  root_dirs: []
  doc_types_map: {}
  patterns:
    target_glob: "**/*.md"
    exclude: []
""")

        result = self._run_validate(category='specs')

        combined_output = result.stdout + result.stderr
        self.assertNotIn('IndexError', combined_output,
                         "validate_toc.py が IndexError でクラッシュした")
        self.assertNotIn('Traceback', combined_output,
                         f"validate_toc.py が例外でクラッシュした: {combined_output}")


if __name__ == '__main__':
    unittest.main()
