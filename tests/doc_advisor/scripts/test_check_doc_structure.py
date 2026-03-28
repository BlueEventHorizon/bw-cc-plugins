#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_doc_structure.sh のユニットテスト。

テスト対象:
- root_dirs 設定あり → 出力なし（exit 0）
- カテゴリ別チェック（rules/specs）
- .doc_structure.yaml 不在 → ACTION REQUIRED 出力

移行元: test_setup_upgrade.sh Test 25
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

# テスト対象スクリプトのパス
SCRIPTS_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'plugins', 'doc-advisor', 'scripts'
))
CHECK_SCRIPT = os.path.join(SCRIPTS_DIR, 'check_doc_structure.sh')


class TestCheckDocStructureBase(unittest.TestCase):
    """テスト用の共通セットアップ"""

    def setUp(self):
        """一時ディレクトリとテスト用プロジェクト構造を作成"""
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = self.tmpdir

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_doc_structure(self, content):
        """テスト用 .doc_structure.yaml を作成"""
        with open(os.path.join(self.project_root, '.doc_structure.yaml'), 'w') as f:
            f.write(content)

    def _run_check(self, category=None):
        """check_doc_structure.sh を subprocess で実行"""
        cmd = ['bash', CHECK_SCRIPT]
        if category:
            cmd.append(category)
        env = os.environ.copy()
        env['CLAUDE_PROJECT_DIR'] = self.project_root
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=self.project_root, env=env
        )
        return result


class TestCheckDocStructureConfigured(TestCheckDocStructureBase):
    """root_dirs 設定ありのテスト（Test 25 Case 1, 2）"""

    FULL_CONFIG = """\
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

    def test_no_output_when_configured_no_category(self):
        """root_dirs 設定あり（カテゴリ引数なし）→ 出力なし、exit 0"""
        self._write_doc_structure(self.FULL_CONFIG)

        result = self._run_check()

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), '',
                         f"出力が空でない: {result.stdout}")

    def test_no_output_for_rules_category(self):
        """rules カテゴリ指定 → 出力なし"""
        self._write_doc_structure(self.FULL_CONFIG)

        result = self._run_check(category='rules')

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), '')

    def test_no_output_for_specs_category(self):
        """specs カテゴリ指定 → 出力なし"""
        self._write_doc_structure(self.FULL_CONFIG)

        result = self._run_check(category='specs')

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), '')


class TestCheckDocStructureMissing(TestCheckDocStructureBase):
    """設定不在のテスト（Test 25 Case 3, 4）"""

    def test_action_required_when_no_doc_structure(self):
        """.doc_structure.yaml 不在 → ACTION REQUIRED 出力"""
        # .doc_structure.yaml を作成しない
        result = self._run_check(category='rules')

        self.assertEqual(result.returncode, 0)
        self.assertIn('ACTION REQUIRED', result.stdout,
                       f"ACTION REQUIRED が出力されていない: {result.stdout}")

    def test_action_required_when_no_doc_structure_no_category(self):
        """.doc_structure.yaml 不在（カテゴリ引数なし）→ ACTION REQUIRED 出力"""
        result = self._run_check()

        self.assertEqual(result.returncode, 0)
        self.assertIn('ACTION REQUIRED', result.stdout)


class TestCheckDocStructureCrossCategory(TestCheckDocStructureBase):
    """カテゴリ別チェック（片方のみ設定）のテスト（Test 25 Case 4）"""

    RULES_ONLY_CONFIG = """\
# doc_structure_version: 3.0

rules:
  root_dirs:
    - rules/
  doc_types_map:
    rules/: rule
  patterns:
    target_glob: "**/*.md"
    exclude: []
"""

    def test_rules_ok_when_only_rules_configured(self):
        """rules のみ設定 → rules チェックは出力なし"""
        self._write_doc_structure(self.RULES_ONLY_CONFIG)

        result = self._run_check(category='rules')

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), '')

    def test_specs_action_required_when_only_rules_configured(self):
        """rules のみ設定 → specs チェックは ACTION REQUIRED"""
        self._write_doc_structure(self.RULES_ONLY_CONFIG)

        result = self._run_check(category='specs')

        self.assertEqual(result.returncode, 0)
        self.assertIn('ACTION REQUIRED', result.stdout,
                       f"specs の ACTION REQUIRED が出力されていない: {result.stdout}")
        self.assertIn('specs', result.stdout,
                       f"specs カテゴリ名が出力に含まれていない: {result.stdout}")


if __name__ == '__main__':
    unittest.main()
