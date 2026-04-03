#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""core.py のユニットテスト。

DES-007 §3.1-3.3, §5.4, §6.2-6.3 に基づく
ファイルスキャン・差分検出・インデックス構築をテストする。
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# テスト対象モジュールの import
SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'plugins', 'doc-advisor', 'scripts'
)
sys.path.insert(0, os.path.abspath(SCRIPTS_DIR))

from code_index.core import (
    DEFAULT_EXCLUDE_DIRS,
    DEFAULT_EXTENSION_MAP,
    SCHEMA_VERSION,
    detect_changes,
    detect_language,
    load_index,
    merge_subagent_results,
    scan_files,
    write_checksums,
    write_index,
)


# ===========================================================================
# scan_files テスト
# ===========================================================================

class TestScanFiles(unittest.TestCase):
    """scan_files() のテスト。tmpdir にファイルを作成して検証する。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # テスト用ファイルを作成
        self._make_file('src/app.swift', 'import Foundation\n')
        self._make_file('src/utils.py', 'print("hello")\n')
        self._make_file('src/readme.txt', 'readme\n')
        self._make_file('node_modules/pkg/index.js', 'module.exports = {}\n')
        self._make_file('__pycache__/cache.pyc', 'cache\n')
        self._make_file('.git/config', '[core]\n')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_file(self, rel_path, content=''):
        abs_path = Path(self.tmpdir) / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding='utf-8')

    def test_scans_matching_extensions(self):
        """対象拡張子のファイルのみ返す"""
        result = scan_files(self.tmpdir, extensions={'.swift', '.py'})
        self.assertIn('src/app.swift', result)
        self.assertIn('src/utils.py', result)
        self.assertNotIn('src/readme.txt', result)

    def test_excludes_default_dirs(self):
        """デフォルト除外ディレクトリのファイルを除外する"""
        result = scan_files(self.tmpdir, extensions={'.js', '.swift', '.py'})
        # node_modules, __pycache__, .git は除外される
        for path in result:
            for excl in ('node_modules', '__pycache__', '.git'):
                self.assertNotIn(excl, path)

    def test_custom_exclude_dirs(self):
        """カスタム除外ディレクトリを指定できる"""
        result = scan_files(
            self.tmpdir,
            extensions={'.swift'},
            exclude_dirs={'src'},
        )
        self.assertEqual(result, [])

    def test_returns_sorted_list(self):
        """結果がソートされている"""
        self._make_file('z.swift', '')
        self._make_file('a.swift', '')
        result = scan_files(self.tmpdir, extensions={'.swift'})
        self.assertEqual(result, sorted(result))

    def test_empty_directory(self):
        """ファイルが存在しないディレクトリでは空リスト"""
        empty_dir = tempfile.mkdtemp()
        try:
            result = scan_files(empty_dir, extensions={'.swift'})
            self.assertEqual(result, [])
        finally:
            shutil.rmtree(empty_dir, ignore_errors=True)


# ===========================================================================
# detect_language テスト
# ===========================================================================

class TestDetectLanguage(unittest.TestCase):
    """detect_language() のテスト。拡張子→言語判定を検証する。"""

    def test_all_default_extensions(self):
        """デフォルトマップの全拡張子を検証"""
        expected = {
            '.swift': 'swift',
            '.py': 'python',
            '.ts': 'typescript',
            '.js': 'javascript',
            '.kt': 'kotlin',
            '.java': 'java',
            '.go': 'go',
            '.rs': 'rust',
        }
        for ext, lang in expected.items():
            result = detect_language(f'src/file{ext}')
            self.assertEqual(result, lang, f'{ext} should map to {lang}')

    def test_unknown_extension(self):
        """未対応拡張子は 'unknown' を返す"""
        self.assertEqual(detect_language('file.txt'), 'unknown')
        self.assertEqual(detect_language('file.md'), 'unknown')
        self.assertEqual(detect_language('file.c'), 'unknown')

    def test_custom_extension_map(self):
        """カスタムマップを指定できる"""
        custom = {'.c': 'c', '.h': 'c-header'}
        self.assertEqual(detect_language('main.c', custom), 'c')
        self.assertEqual(detect_language('main.h', custom), 'c-header')
        self.assertEqual(detect_language('main.py', custom), 'unknown')

    def test_case_insensitive_extension(self):
        """拡張子の大文字小文字を区別しない"""
        self.assertEqual(detect_language('FILE.Swift'), 'swift')
        self.assertEqual(detect_language('FILE.PY'), 'python')


# ===========================================================================
# detect_changes テスト
# ===========================================================================

class TestDetectChanges(unittest.TestCase):
    """detect_changes() のテスト。4 パターンの変更検出を検証する。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.checksums_path = Path(self.tmpdir) / '.code_checksums.yaml'

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_file(self, rel_path, content='hello'):
        abs_path = Path(self.tmpdir) / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding='utf-8')

    def test_all_new(self):
        """チェックサム未存在時は全ファイルが new"""
        self._make_file('a.swift', 'aaa')
        self._make_file('b.swift', 'bbb')
        result = detect_changes(self.tmpdir, ['a.swift', 'b.swift'], self.checksums_path)
        self.assertEqual(sorted(result['new']), ['a.swift', 'b.swift'])
        self.assertEqual(result['modified'], [])
        self.assertEqual(result['deleted'], [])
        self.assertEqual(result['unchanged'], [])

    def test_unchanged(self):
        """ファイル内容が同一なら unchanged"""
        self._make_file('a.swift', 'content')
        # まずチェックサムを作成
        from toc_utils import calculate_file_hash
        h = calculate_file_hash(Path(self.tmpdir) / 'a.swift')
        write_checksums({'a.swift': h}, self.checksums_path)

        result = detect_changes(self.tmpdir, ['a.swift'], self.checksums_path)
        self.assertEqual(result['unchanged'], ['a.swift'])
        self.assertEqual(result['new'], [])
        self.assertEqual(result['modified'], [])

    def test_modified(self):
        """ファイル内容が変更されたら modified"""
        self._make_file('a.swift', 'old_content')
        from toc_utils import calculate_file_hash
        h = calculate_file_hash(Path(self.tmpdir) / 'a.swift')
        write_checksums({'a.swift': h}, self.checksums_path)

        # ファイル内容を変更
        self._make_file('a.swift', 'new_content')
        result = detect_changes(self.tmpdir, ['a.swift'], self.checksums_path)
        self.assertEqual(result['modified'], ['a.swift'])

    def test_deleted(self):
        """前回チェックサムにあるがスキャン結果にないファイルは deleted"""
        write_checksums({'old_file.swift': 'abc123'}, self.checksums_path)

        result = detect_changes(self.tmpdir, [], self.checksums_path)
        self.assertEqual(result['deleted'], ['old_file.swift'])

    def test_mixed_changes(self):
        """new / modified / deleted / unchanged の混在"""
        self._make_file('new.swift', 'new')
        self._make_file('mod.swift', 'modified_content')
        self._make_file('same.swift', 'same')

        from toc_utils import calculate_file_hash
        h_same = calculate_file_hash(Path(self.tmpdir) / 'same.swift')
        write_checksums({
            'mod.swift': 'old_hash',
            'same.swift': h_same,
            'gone.swift': 'hash_of_gone',
        }, self.checksums_path)

        files = ['new.swift', 'mod.swift', 'same.swift']
        result = detect_changes(self.tmpdir, files, self.checksums_path)
        self.assertEqual(result['new'], ['new.swift'])
        self.assertEqual(result['modified'], ['mod.swift'])
        self.assertEqual(result['deleted'], ['gone.swift'])
        self.assertEqual(result['unchanged'], ['same.swift'])

    def test_current_checksums_returned(self):
        """current_checksums が結果に含まれる"""
        self._make_file('a.swift', 'aaa')
        result = detect_changes(self.tmpdir, ['a.swift'], self.checksums_path)
        self.assertIn('a.swift', result['current_checksums'])
        self.assertIsInstance(result['current_checksums']['a.swift'], str)


# ===========================================================================
# merge_subagent_results テスト
# ===========================================================================

class TestMergeSubagentResults(unittest.TestCase):
    """merge_subagent_results() のテスト。subagent JSON 統合を検証する。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._make_file('src/app.swift', 'import Foundation\nclass App {}\n')
        self._make_file('src/util.py', 'def helper():\n    pass\n')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_file(self, rel_path, content=''):
        abs_path = Path(self.tmpdir) / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding='utf-8')

    def test_basic_merge(self):
        """subagent 結果を新規インデックスに統合できる"""
        subagent = {
            'src/app.swift': {
                'imports': ['Foundation'],
                'exports': [{'name': 'App', 'kind': 'Class'}],
                'sections': [],
            },
        }
        result = merge_subagent_results({}, subagent, self.tmpdir)
        entry = result['entries']['src/app.swift']
        self.assertEqual(entry['language'], 'swift')
        self.assertEqual(entry['lines'], 2)
        self.assertEqual(entry['imports'], ['Foundation'])
        self.assertEqual(entry['exports'], [{'name': 'App', 'kind': 'Class'}])

    def test_lines_counted(self):
        """行数がファイルから計算される"""
        subagent = {
            'src/util.py': {
                'imports': [],
                'exports': [],
                'sections': [],
            },
        }
        result = merge_subagent_results({}, subagent, self.tmpdir)
        self.assertEqual(result['entries']['src/util.py']['lines'], 2)

    def test_deleted_files_removed(self):
        """deleted ファイルがインデックスから除去される"""
        existing = {
            'entries': {
                'old.swift': {'language': 'swift', 'lines': 10, 'imports': [], 'exports': [], 'sections': []},
                'keep.swift': {'language': 'swift', 'lines': 5, 'imports': [], 'exports': [], 'sections': []},
            }
        }
        result = merge_subagent_results(existing, {}, self.tmpdir, deleted_files=['old.swift'])
        self.assertNotIn('old.swift', result['entries'])
        self.assertIn('keep.swift', result['entries'])

    def test_existing_entry_updated(self):
        """既存エントリが上書き更新される"""
        existing = {
            'entries': {
                'src/app.swift': {
                    'language': 'swift', 'lines': 1,
                    'imports': ['OldModule'],
                    'exports': [], 'sections': [],
                },
            }
        }
        subagent = {
            'src/app.swift': {
                'imports': ['Foundation', 'NewModule'],
                'exports': [{'name': 'App', 'kind': 'Class'}],
                'sections': ['Public API'],
            },
        }
        result = merge_subagent_results(existing, subagent, self.tmpdir)
        entry = result['entries']['src/app.swift']
        self.assertEqual(entry['imports'], ['Foundation', 'NewModule'])
        self.assertEqual(entry['sections'], ['Public API'])

    def test_language_detection_in_merge(self):
        """統合時に拡張子から言語が判定される"""
        self._make_file('lib/mod.rs', 'fn main() {}\n')
        subagent = {
            'lib/mod.rs': {'imports': [], 'exports': [], 'sections': []},
        }
        result = merge_subagent_results({}, subagent, self.tmpdir)
        self.assertEqual(result['entries']['lib/mod.rs']['language'], 'rust')


# ===========================================================================
# write_index / load_index テスト
# ===========================================================================

class TestWriteAndLoadIndex(unittest.TestCase):
    """write_index() / load_index() のテスト。

    アトミック書き込みとスキーマバージョン検証を検証する。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.index_path = Path(self.tmpdir) / 'code_index.json'

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_and_load_roundtrip(self):
        """書き込み→読み込みのラウンドトリップ"""
        index_data = {
            'entries': {
                'src/app.swift': {
                    'language': 'swift',
                    'lines': 10,
                    'imports': ['Foundation'],
                    'exports': [{'name': 'App', 'kind': 'Class'}],
                    'sections': [],
                },
            }
        }
        write_index(index_data, self.index_path)
        loaded = load_index(self.index_path)

        self.assertEqual(loaded['metadata']['schema_version'], SCHEMA_VERSION)
        self.assertEqual(loaded['metadata']['file_count'], 1)
        self.assertEqual(loaded['metadata']['languages'], {'swift': 1})
        self.assertIn('src/app.swift', loaded['entries'])
        self.assertEqual(loaded['entries']['src/app.swift']['lines'], 10)

    def test_schema_version_mismatch_raises(self):
        """スキーマバージョン不一致で ValueError が発生する"""
        bad_index = {
            'metadata': {'schema_version': '2.0'},
            'entries': {},
        }
        self.index_path.write_text(json.dumps(bad_index), encoding='utf-8')
        with self.assertRaises(ValueError) as ctx:
            load_index(self.index_path)
        self.assertIn('--full', str(ctx.exception))

    def test_missing_schema_version_raises(self):
        """schema_version がない場合も ValueError"""
        bad_index = {'metadata': {}, 'entries': {}}
        self.index_path.write_text(json.dumps(bad_index), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_index(self.index_path)

    def test_file_not_found(self):
        """ファイルが存在しない場合は FileNotFoundError"""
        with self.assertRaises(FileNotFoundError):
            load_index(Path(self.tmpdir) / 'nonexistent.json')

    def test_atomic_write_creates_parent_dirs(self):
        """親ディレクトリが自動作成される"""
        nested_path = Path(self.tmpdir) / 'sub' / 'dir' / 'index.json'
        write_index({'entries': {}}, nested_path)
        self.assertTrue(nested_path.exists())

    def test_metadata_languages_count(self):
        """metadata.languages が正しくカウントされる"""
        index_data = {
            'entries': {
                'a.swift': {'language': 'swift', 'lines': 1, 'imports': [], 'exports': [], 'sections': []},
                'b.swift': {'language': 'swift', 'lines': 2, 'imports': [], 'exports': [], 'sections': []},
                'c.py': {'language': 'python', 'lines': 3, 'imports': [], 'exports': [], 'sections': []},
            }
        }
        write_index(index_data, self.index_path)
        loaded = load_index(self.index_path)
        self.assertEqual(loaded['metadata']['languages'], {'swift': 2, 'python': 1})
        self.assertEqual(loaded['metadata']['file_count'], 3)


# ===========================================================================
# write_checksums テスト
# ===========================================================================

class TestWriteChecksums(unittest.TestCase):
    """write_checksums() のテスト。チェックサム永続化を検証する。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.checksums_path = Path(self.tmpdir) / '.code_checksums.yaml'

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_and_reload(self):
        """書き込んだチェックサムを load_checksums で読み戻せる"""
        from toc_utils import load_checksums
        checksums = {
            'src/app.swift': 'abc123',
            'src/util.py': 'def456',
        }
        result = write_checksums(checksums, self.checksums_path)
        self.assertTrue(result)

        loaded = load_checksums(self.checksums_path)
        self.assertEqual(loaded, checksums)

    def test_creates_parent_dirs(self):
        """親ディレクトリが自動作成される"""
        nested = Path(self.tmpdir) / 'sub' / '.code_checksums.yaml'
        result = write_checksums({'a': 'b'}, nested)
        self.assertTrue(result)
        self.assertTrue(nested.exists())


if __name__ == '__main__':
    unittest.main()
