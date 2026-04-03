#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_code_index.py の CLI 統合テスト。

subprocess で CLI を実行するパターンで各モードを検証する。
DES-007 §6.4-6.5, §9.2-9.3 に基づく。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# テスト対象スクリプトのパス
SCRIPTS_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'plugins', 'doc-advisor', 'scripts'
))
CODE_INDEX_DIR = os.path.join(SCRIPTS_DIR, 'code_index')
BUILD_SCRIPT = os.path.join(CODE_INDEX_DIR, 'build_code_index.py')


class TestBuildCodeIndexBase(unittest.TestCase):
    """build_code_index.py テストの基底クラス。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_file(self, rel_path, content=''):
        """tmpdir 配下にファイルを作成する。"""
        abs_path = Path(self.tmpdir) / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding='utf-8')

    def _run_cli(self, args, stdin_data=None):
        """build_code_index.py を subprocess で実行する。"""
        cmd = [sys.executable, BUILD_SCRIPT] + args
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            input=stdin_data,
            cwd=CODE_INDEX_DIR,
            env={**os.environ, 'PYTHONPATH': SCRIPTS_DIR},
        )

    def _parse_output(self, proc):
        """stdout を JSON としてパースする。"""
        return json.loads(proc.stdout.strip())

    def _index_path(self):
        return Path(self.tmpdir) / '.claude' / 'doc-advisor' / 'code_index' / 'code_index.json'

    def _checksums_path(self):
        return Path(self.tmpdir) / '.claude' / 'doc-advisor' / 'code_index' / '.code_checksums.yaml'


# ===========================================================================
# --diff モード テスト
# ===========================================================================

class TestDiffMode(TestBuildCodeIndexBase):
    """--diff モードのテスト。"""

    def test_diff_fresh_empty_project(self):
        """ファイルなしのプロジェクトは fresh を返す"""
        proc = self._run_cli(['--diff', self.tmpdir])
        self.assertEqual(proc.returncode, 0, f'stderr: {proc.stderr}')
        result = self._parse_output(proc)
        self.assertEqual(result['status'], 'fresh')
        self.assertEqual(result['new'], [])
        self.assertEqual(result['modified'], [])
        self.assertEqual(result['deleted'], [])

    def test_diff_detects_new_files(self):
        """新規 Swift/Python ファイルを検出する"""
        self._make_file('src/app.swift', 'import Foundation\n')
        self._make_file('src/utils.py', 'print("hello")\n')

        proc = self._run_cli(['--diff', self.tmpdir])
        self.assertEqual(proc.returncode, 0, f'stderr: {proc.stderr}')
        result = self._parse_output(proc)
        self.assertEqual(result['status'], 'stale')
        self.assertIn('src/app.swift', result['new'])
        self.assertIn('src/utils.py', result['new'])
        self.assertEqual(result['modified'], [])
        self.assertEqual(result['deleted'], [])

    def test_diff_excludes_non_source_files(self):
        """対象外拡張子のファイルは検出されない"""
        self._make_file('src/readme.txt', 'readme\n')
        self._make_file('src/data.csv', 'a,b,c\n')

        proc = self._run_cli(['--diff', self.tmpdir])
        self.assertEqual(proc.returncode, 0, f'stderr: {proc.stderr}')
        result = self._parse_output(proc)
        self.assertEqual(result['status'], 'fresh')

    def test_diff_excludes_default_dirs(self):
        """除外ディレクトリのファイルは検出されない"""
        self._make_file('node_modules/pkg/index.js', 'module.exports = {}\n')
        self._make_file('.git/config', '[core]\n')
        self._make_file('__pycache__/mod.py', 'cached\n')

        proc = self._run_cli(['--diff', self.tmpdir])
        self.assertEqual(proc.returncode, 0, f'stderr: {proc.stderr}')
        result = self._parse_output(proc)
        self.assertEqual(result['status'], 'fresh')

    def test_diff_output_is_valid_json(self):
        """出力が有効な JSON である"""
        self._make_file('a.swift', 'let x = 1\n')
        proc = self._run_cli(['--diff', self.tmpdir])
        self.assertEqual(proc.returncode, 0)
        # JSONDecodeError が発生しなければ OK
        self._parse_output(proc)


# ===========================================================================
# --mcp-data モード テスト
# ===========================================================================

class TestMcpDataMode(TestBuildCodeIndexBase):
    """--mcp-data モードのテスト。"""

    def test_mcp_data_creates_index(self):
        """正常な subagent JSON でインデックスが作成される"""
        self._make_file('src/app.swift', 'import Foundation\nclass App {}\n')
        subagent_json = json.dumps({
            'src/app.swift': {
                'imports': ['Foundation'],
                'exports': [{'name': 'App', 'kind': 'Class'}],
                'sections': [],
            },
        })

        proc = self._run_cli(['--mcp-data', self.tmpdir], stdin_data=subagent_json)
        self.assertEqual(proc.returncode, 0, f'stderr: {proc.stderr}')
        result = self._parse_output(proc)
        self.assertEqual(result['status'], 'ok')
        self.assertIn('file_count', result)
        self.assertTrue(self._index_path().exists())
        self.assertTrue(self._checksums_path().exists())

    def test_mcp_data_index_content(self):
        """作成されたインデックスの内容が正しい"""
        self._make_file('src/app.swift', 'import Foundation\nclass App {}\n')
        subagent_json = json.dumps({
            'src/app.swift': {
                'imports': ['Foundation'],
                'exports': [{'name': 'App', 'kind': 'Class'}],
                'sections': ['Public API'],
            },
        })

        self._run_cli(['--mcp-data', self.tmpdir], stdin_data=subagent_json)

        with open(self._index_path(), 'r', encoding='utf-8') as f:
            index = json.load(f)

        self.assertIn('src/app.swift', index['entries'])
        entry = index['entries']['src/app.swift']
        self.assertEqual(entry['language'], 'swift')
        self.assertEqual(entry['lines'], 2)
        self.assertEqual(entry['imports'], ['Foundation'])
        self.assertEqual(entry['exports'], [{'name': 'App', 'kind': 'Class'}])

    def test_mcp_data_empty_json(self):
        """空の subagent JSON でもエラーにならない"""
        proc = self._run_cli(['--mcp-data', self.tmpdir], stdin_data='{}')
        self.assertEqual(proc.returncode, 0, f'stderr: {proc.stderr}')
        result = self._parse_output(proc)
        self.assertEqual(result['status'], 'ok')

    def test_mcp_data_invalid_json(self):
        """無効な JSON 入力はエラーを返す"""
        proc = self._run_cli(['--mcp-data', self.tmpdir], stdin_data='not json at all')
        self.assertNotEqual(proc.returncode, 0)
        result = self._parse_output(proc)
        self.assertEqual(result['status'], 'error')
        self.assertIn('Invalid JSON input', result['message'])

    def test_mcp_data_missing_imports_key(self):
        """imports キーが欠けている場合はエラー"""
        subagent_json = json.dumps({
            'src/app.swift': {
                'exports': [],
                'sections': [],
            },
        })
        proc = self._run_cli(['--mcp-data', self.tmpdir], stdin_data=subagent_json)
        self.assertNotEqual(proc.returncode, 0)
        result = self._parse_output(proc)
        self.assertEqual(result['status'], 'error')
        self.assertIn('imports', result['message'])

    def test_mcp_data_missing_exports_key(self):
        """exports キーが欠けている場合はエラー"""
        subagent_json = json.dumps({
            'src/app.swift': {
                'imports': [],
                'sections': [],
            },
        })
        proc = self._run_cli(['--mcp-data', self.tmpdir], stdin_data=subagent_json)
        self.assertNotEqual(proc.returncode, 0)
        result = self._parse_output(proc)
        self.assertEqual(result['status'], 'error')
        self.assertIn('exports', result['message'])

    def test_mcp_data_imports_not_list(self):
        """imports が list でない場合はエラー"""
        subagent_json = json.dumps({
            'src/app.swift': {
                'imports': 'Foundation',
                'exports': [],
            },
        })
        proc = self._run_cli(['--mcp-data', self.tmpdir], stdin_data=subagent_json)
        self.assertNotEqual(proc.returncode, 0)
        result = self._parse_output(proc)
        self.assertEqual(result['status'], 'error')
        self.assertIn('配列', result['message'])

    def test_mcp_data_exports_not_list(self):
        """exports が list でない場合はエラー"""
        subagent_json = json.dumps({
            'src/app.swift': {
                'imports': [],
                'exports': 'not a list',
            },
        })
        proc = self._run_cli(['--mcp-data', self.tmpdir], stdin_data=subagent_json)
        self.assertNotEqual(proc.returncode, 0)
        result = self._parse_output(proc)
        self.assertEqual(result['status'], 'error')
        self.assertIn('配列', result['message'])

    def test_mcp_data_statistics(self):
        """成功時の統計情報が正しい"""
        self._make_file('src/a.swift', 'import A\n')
        self._make_file('src/b.swift', 'import B\n')
        subagent_json = json.dumps({
            'src/a.swift': {'imports': ['A'], 'exports': [], 'sections': []},
            'src/b.swift': {'imports': ['B'], 'exports': [], 'sections': []},
        })

        proc = self._run_cli(['--mcp-data', self.tmpdir], stdin_data=subagent_json)
        self.assertEqual(proc.returncode, 0, f'stderr: {proc.stderr}')
        result = self._parse_output(proc)
        self.assertEqual(result['status'], 'ok')
        self.assertGreaterEqual(result['new'], 2)
        self.assertEqual(result['failed'], 0)


# ===========================================================================
# --check モード テスト
# ===========================================================================

class TestCheckMode(TestBuildCodeIndexBase):
    """--check モードのテスト。"""

    def _create_index(self, subagent_data=None):
        """ヘルパー: --mcp-data でインデックスを作成する。"""
        if subagent_data is None:
            subagent_data = {}
        stdin_data = json.dumps(subagent_data)
        proc = self._run_cli(['--mcp-data', self.tmpdir], stdin_data=stdin_data)
        self.assertEqual(proc.returncode, 0, f'stderr: {proc.stderr}')

    def test_check_fresh(self):
        """変更なしの場合は fresh を返す"""
        self._make_file('src/app.swift', 'import Foundation\n')
        self._create_index({
            'src/app.swift': {'imports': ['Foundation'], 'exports': [], 'sections': []},
        })

        proc = self._run_cli(['--check', self.tmpdir])
        self.assertEqual(proc.returncode, 0, f'stderr: {proc.stderr}')
        result = self._parse_output(proc)
        self.assertEqual(result['status'], 'fresh')

    def test_check_stale_new_file(self):
        """新規ファイル追加後は stale を返す"""
        self._create_index()

        # インデックス作成後にファイルを追加
        self._make_file('src/new.swift', 'let x = 1\n')

        proc = self._run_cli(['--check', self.tmpdir])
        self.assertEqual(proc.returncode, 0, f'stderr: {proc.stderr}')
        result = self._parse_output(proc)
        self.assertEqual(result['status'], 'stale')
        self.assertIn('new', result['reason'])

    def test_check_stale_modified_file(self):
        """ファイル変更後は stale を返す"""
        self._make_file('src/app.swift', 'import Foundation\n')
        self._create_index({
            'src/app.swift': {'imports': ['Foundation'], 'exports': [], 'sections': []},
        })

        # ファイル内容を変更
        self._make_file('src/app.swift', 'import Foundation\nimport UIKit\n')

        proc = self._run_cli(['--check', self.tmpdir])
        self.assertEqual(proc.returncode, 0, f'stderr: {proc.stderr}')
        result = self._parse_output(proc)
        self.assertEqual(result['status'], 'stale')
        self.assertIn('modified', result['reason'])

    def test_check_no_index_error(self):
        """インデックス未作成の場合はエラー"""
        proc = self._run_cli(['--check', self.tmpdir])
        self.assertNotEqual(proc.returncode, 0)
        result = self._parse_output(proc)
        self.assertEqual(result['status'], 'error')
        self.assertIn('Index not found', result['message'])

    def test_check_stale_reason_format(self):
        """stale の reason 文字列が正しいフォーマット"""
        self._create_index()
        self._make_file('src/a.swift', 'let a = 1\n')
        self._make_file('src/b.swift', 'let b = 2\n')

        proc = self._run_cli(['--check', self.tmpdir])
        self.assertEqual(proc.returncode, 0, f'stderr: {proc.stderr}')
        result = self._parse_output(proc)
        self.assertEqual(result['status'], 'stale')
        # "2 new" のようなフォーマット
        self.assertRegex(result['reason'], r'\d+ new')


# ===========================================================================
# 引数エラーテスト
# ===========================================================================

class TestCliArgErrors(TestBuildCodeIndexBase):
    """CLI 引数エラーのテスト。"""

    def test_no_args(self):
        """引数なしの場合は終了コード非0"""
        proc = self._run_cli([])
        self.assertNotEqual(proc.returncode, 0)

    def test_mutually_exclusive(self):
        """複数モードの同時指定は拒否される"""
        proc = self._run_cli(['--diff', self.tmpdir, '--check', self.tmpdir])
        self.assertNotEqual(proc.returncode, 0)


if __name__ == '__main__':
    unittest.main()
