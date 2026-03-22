#!/usr/bin/env python3
"""list_forge_docs.py のテスト"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# テスト対象のスクリプトをインポート
SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent.parent / \
    'plugins' / 'forge' / 'skills' / 'clean-rules' / 'scripts'
sys.path.insert(0, str(SCRIPT_DIR))

from list_forge_docs import (
    extract_metadata,
    list_forge_docs,
    INTERNAL_DOCS,
    SUFFIX_TO_CONTENT_TYPE,
)


class _TempDirTestCase(unittest.TestCase):
    """一時ディレクトリを使うテストの基底クラス"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name, content):
        """一時ディレクトリにファイルを書き出す"""
        path = os.path.join(self.tmpdir, name)
        Path(path).write_text(content, encoding='utf-8')
        return path


class TestExtractMetadata(unittest.TestCase):
    """extract_metadata のテスト"""

    def test_basic_metadata(self):
        """タイトルとトピックを正しく抽出する"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False,
                                          encoding='utf-8') as f:
            f.write('# テストタイトル\n\n## セクション1\n\nテキスト\n\n## セクション2\n')
            f.flush()
            result = extract_metadata(f.name)
        os.unlink(f.name)

        self.assertEqual(result['title'], 'テストタイトル')
        self.assertEqual(result['topics'], ['セクション1', 'セクション2'])

    def test_mandatory_tag_removed(self):
        """[MANDATORY] タグがトピックから除去される"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False,
                                          encoding='utf-8') as f:
            f.write('# タイトル\n\n## ルール [MANDATORY]\n')
            f.flush()
            result = extract_metadata(f.name)
        os.unlink(f.name)

        self.assertEqual(result['topics'], ['ルール'])

    def test_h3_not_included(self):
        """### 見出しはトピックに含まれない"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False,
                                          encoding='utf-8') as f:
            f.write('# タイトル\n\n## H2\n\n### H3\n')
            f.flush()
            result = extract_metadata(f.name)
        os.unlink(f.name)

        self.assertEqual(result['topics'], ['H2'])

    def test_content_type_format(self):
        """_format.md のファイルは content_type: format"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='_format.md', delete=False,
                                          encoding='utf-8') as f:
            f.write('# フォーマット定義\n')
            f.flush()
            result = extract_metadata(f.name)
        os.unlink(f.name)

        self.assertEqual(result['content_type'], 'format')

    def test_content_type_constraint(self):
        """_criteria_spec.md のファイルは content_type: constraint"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='_criteria_spec.md', delete=False,
                                          encoding='utf-8') as f:
            f.write('# レビュー観点\n')
            f.flush()
            result = extract_metadata(f.name)
        os.unlink(f.name)

        self.assertEqual(result['content_type'], 'constraint')

    def test_content_type_principles_spec(self):
        """_principles_spec.md のファイルは content_type: constraint"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='_principles_spec.md', delete=False,
                                          encoding='utf-8') as f:
            f.write('# 設計原則\n')
            f.flush()
            result = extract_metadata(f.name)
        os.unlink(f.name)

        self.assertEqual(result['content_type'], 'constraint')

    def test_content_type_spec(self):
        """_spec.md のファイルは content_type: reference"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='_spec.md', delete=False,
                                          encoding='utf-8') as f:
            f.write('# 仕様定義\n')
            f.flush()
            result = extract_metadata(f.name)
        os.unlink(f.name)

        self.assertEqual(result['content_type'], 'reference')

    def test_content_type_unknown(self):
        """サフィックスに一致しないファイルは content_type: unknown"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False,
                                          encoding='utf-8') as f:
            f.write('# テスト\n')
            f.flush()
            result = extract_metadata(f.name)
        os.unlink(f.name)

        self.assertEqual(result['content_type'], 'unknown')

    def test_nonexistent_file(self):
        """存在しないファイルは None を返す"""
        result = extract_metadata('/nonexistent/path.md')
        self.assertIsNone(result)

    def test_no_title(self):
        """# 行がないファイルのタイトルは空文字"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False,
                                          encoding='utf-8') as f:
            f.write('## セクションのみ\n')
            f.flush()
            result = extract_metadata(f.name)
        os.unlink(f.name)

        self.assertEqual(result['title'], '')
        self.assertEqual(result['topics'], ['セクションのみ'])

    def test_empty_file(self):
        """空ファイルはタイトル空・トピック空"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False,
                                          encoding='utf-8') as f:
            f.write('')
            f.flush()
            result = extract_metadata(f.name)
        os.unlink(f.name)

        self.assertEqual(result['title'], '')
        self.assertEqual(result['topics'], [])

    def test_multiple_tags_removed(self):
        """[CRITICAL] や [IMPORTANT] タグもトピックから除去される"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False,
                                          encoding='utf-8') as f:
            f.write('# タイトル\n\n## セキュリティ [CRITICAL]\n\n## 注意事項 [IMPORTANT]\n')
            f.flush()
            result = extract_metadata(f.name)
        os.unlink(f.name)

        self.assertEqual(result['topics'], ['セキュリティ', '注意事項'])


class TestListForgeDocs(_TempDirTestCase):
    """list_forge_docs のテスト"""

    def test_basic_listing(self):
        """docs ディレクトリ内の .md ファイルを一覧する"""
        self._write('review_criteria_spec.md', '# レビュー観点\n\n## コードレビュー\n')
        self._write('design_format.md', '# 設計書フォーマット\n\n## 必須セクション\n')

        result = list_forge_docs(self.tmpdir)

        self.assertEqual(result['status'], 'ok')
        self.assertEqual(len(result['docs']), 2)

    def test_sorted_output(self):
        """ファイルはアルファベット順にソートされる"""
        self._write('z_spec.md', '# Z\n')
        self._write('a_format.md', '# A\n')

        result = list_forge_docs(self.tmpdir)

        self.assertEqual(result['docs'][0]['path'], 'a_format.md')
        self.assertEqual(result['docs'][1]['path'], 'z_spec.md')

    def test_internal_flag(self):
        """内部仕様ファイルには internal: true が設定される"""
        self._write('session_format.md', '# セッション仕様\n')
        self._write('review_criteria_spec.md', '# レビュー観点\n')

        result = list_forge_docs(self.tmpdir)

        internal_doc = next(d for d in result['docs'] if d['path'] == 'session_format.md')
        external_doc = next(d for d in result['docs'] if d['path'] == 'review_criteria_spec.md')

        self.assertTrue(internal_doc['internal'])
        self.assertFalse(external_doc['internal'])

    def test_all_internal_docs(self):
        """INTERNAL_DOCS に定義された全ファイルが internal: true"""
        for name in INTERNAL_DOCS:
            self._write(name, f'# {name}\n')

        result = list_forge_docs(self.tmpdir)

        for doc in result['docs']:
            self.assertTrue(doc['internal'],
                            f'{doc["path"]} should be internal')

    def test_full_path_included(self):
        """full_path が絶対パスで含まれる"""
        self._write('test_spec.md', '# テスト\n')

        result = list_forge_docs(self.tmpdir)

        self.assertTrue(os.path.isabs(result['docs'][0]['full_path']))

    def test_nonexistent_directory(self):
        """存在しないディレクトリは error を返す"""
        result = list_forge_docs('/nonexistent/dir')

        self.assertEqual(result['status'], 'error')
        self.assertIn('ディレクトリが存在しません', result['error'])

    def test_empty_directory(self):
        """空のディレクトリは空リストを返す"""
        result = list_forge_docs(self.tmpdir)

        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['docs'], [])

    def test_non_md_files_ignored(self):
        """.md 以外のファイルは無視される"""
        self._write('readme.txt', '# テスト\n')
        self._write('script.py', '# テスト\n')
        self._write('valid_spec.md', '# 有効\n')

        result = list_forge_docs(self.tmpdir)

        self.assertEqual(len(result['docs']), 1)
        self.assertEqual(result['docs'][0]['path'], 'valid_spec.md')

    def test_metadata_fields(self):
        """各ドキュメントに必要なフィールドが含まれる"""
        self._write('review_criteria_spec.md',
                     '# レビュー観点\n\n## コードレビュー\n\n## 設計レビュー\n')

        result = list_forge_docs(self.tmpdir)
        doc = result['docs'][0]

        self.assertIn('path', doc)
        self.assertIn('full_path', doc)
        self.assertIn('title', doc)
        self.assertIn('topics', doc)
        self.assertIn('content_type', doc)
        self.assertIn('internal', doc)

        self.assertEqual(doc['title'], 'レビュー観点')
        self.assertEqual(doc['topics'], ['コードレビュー', '設計レビュー'])
        self.assertEqual(doc['content_type'], 'constraint')
        self.assertFalse(doc['internal'])


class TestCLI(_TempDirTestCase):
    """CLI インターフェースのテスト"""

    def test_cli_output(self):
        """CLI 実行で JSON が出力される"""
        self._write('test_format.md', '# テスト\n')

        import subprocess
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / 'list_forge_docs.py'), self.tmpdir],
            capture_output=True, text=True
        )

        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data['status'], 'ok')

    def test_cli_error_exit_code(self):
        """存在しないディレクトリで exit code 1"""
        import subprocess
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / 'list_forge_docs.py'), '/nonexistent'],
            capture_output=True, text=True
        )

        self.assertEqual(result.returncode, 1)


class TestContentTypePriority(unittest.TestCase):
    """content_type のサフィックスマッチング優先順位テスト"""

    def test_principles_spec_over_spec(self):
        """_principles_spec.md は _spec.md より優先される"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='_principles_spec.md',
                                          delete=False, encoding='utf-8') as f:
            f.write('# 原則\n')
            f.flush()
            result = extract_metadata(f.name)
        os.unlink(f.name)

        # _principles_spec.md → constraint（_spec.md → reference ではない）
        self.assertEqual(result['content_type'], 'constraint')

    def test_criteria_spec_over_spec(self):
        """_criteria_spec.md は _spec.md より優先される"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='_criteria_spec.md',
                                          delete=False, encoding='utf-8') as f:
            f.write('# 基準\n')
            f.flush()
            result = extract_metadata(f.name)
        os.unlink(f.name)

        self.assertEqual(result['content_type'], 'constraint')


if __name__ == '__main__':
    unittest.main()
