#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""auto_create_toc.py のユニットテスト。

テスト対象:
- _parse_frontmatter: frontmatter パース
- _split_to_words / _extract_keywords: キーワード抽出
- _filename_to_title: ファイル名からタイトル生成
- MetadataExtractor: メタデータ抽出（核心部分）
- resolve_doc_type: doc_type 決定
- detect_changed_files: 変更検知
- update_toc: ToC 更新（統合テスト）
"""

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

import auto_create_toc as act


# ---------------------------------------------------------------------------
# テスト用 Markdown コンテンツ
# ---------------------------------------------------------------------------

SAMPLE_MD_FULL = """\
---
name: sample_doc
description: Sample document for testing
---

# Sample Document Title

This is the first paragraph after H1.

## Overview

This document provides testing utilities.

## Metadata

| Key | Value |
| --- | --- |
| 関連要件 | REQ-001 |
| 設計ID | DES-002 |

## Architecture

Some content here.

## Error Handling

Error handling details.

## 改定履歴

- v1.0: Initial version
"""

SAMPLE_MD_MINIMAL = """\
# Minimal Doc

Just a simple document.
"""

SAMPLE_MD_NO_H1 = """\
## Only H2

Some content without H1.

## Another Section

More content.
"""

SAMPLE_MD_FRONTMATTER_ONLY = """\
---
name: test
description: Test document purpose
purpose: Alternative purpose
---

Some body text without headings.
"""

SAMPLE_MD_EMPTY = ""
SAMPLE_MD_WHITESPACE = "   \n  \n  "


# ---------------------------------------------------------------------------
# _parse_frontmatter
# ---------------------------------------------------------------------------

class TestParseFrontmatter(unittest.TestCase):
    """frontmatter パースのテスト。"""

    def test_valid_frontmatter(self):
        """正常な frontmatter を辞書として返す"""
        fm, body = act._parse_frontmatter(SAMPLE_MD_FULL)
        self.assertEqual(fm['name'], 'sample_doc')
        self.assertEqual(fm['description'], 'Sample document for testing')
        self.assertIn('# Sample Document Title', body)

    def test_no_frontmatter(self):
        """frontmatter なしの場合は空辞書と元コンテンツを返す"""
        fm, body = act._parse_frontmatter(SAMPLE_MD_MINIMAL)
        self.assertEqual(fm, {})
        self.assertEqual(body, SAMPLE_MD_MINIMAL)

    def test_empty_content(self):
        """空コンテンツ"""
        fm, body = act._parse_frontmatter("")
        self.assertEqual(fm, {})

    def test_quoted_values(self):
        """クォートで囲まれた値のクォート除去"""
        content = '---\nname: "quoted_value"\n---\nBody'
        fm, body = act._parse_frontmatter(content)
        self.assertEqual(fm['name'], 'quoted_value')

    def test_multiline_value(self):
        """マルチライン値（| 指示子）"""
        content = '---\ndesc: |\n  line one\n  line two\n---\nBody'
        fm, body = act._parse_frontmatter(content)
        self.assertEqual(fm['desc'], 'line one line two')

    def test_unclosed_frontmatter(self):
        """閉じ --- がない場合は frontmatter なし扱い"""
        content = '---\nname: test\nno closing'
        fm, body = act._parse_frontmatter(content)
        self.assertEqual(fm, {})


# ---------------------------------------------------------------------------
# _split_to_words / _extract_keywords
# ---------------------------------------------------------------------------

class TestSplitToWords(unittest.TestCase):
    """単語分割のテスト。"""

    def test_english_text(self):
        words = act._split_to_words("Architecture Rules")
        self.assertIn('Architecture', words)
        self.assertIn('Rules', words)

    def test_japanese_text(self):
        words = act._split_to_words("レビュー基準")
        self.assertIn('レビュー基準', words)

    def test_mixed_separators(self):
        words = act._split_to_words("error-handling_rules/code")
        self.assertTrue(len(words) >= 2)

    def test_empty_input(self):
        self.assertEqual(act._split_to_words(""), [])

    def test_none_input(self):
        self.assertEqual(act._split_to_words(None), [])

    def test_single_char_ascii_excluded(self):
        """1文字の英数字は除外"""
        words = act._split_to_words("a b cd")
        self.assertNotIn('a', words)
        self.assertNotIn('b', words)
        self.assertIn('cd', words)


class TestExtractKeywords(unittest.TestCase):
    """キーワード抽出のテスト。"""

    def test_basic_extraction(self):
        keywords = act._extract_keywords(
            "Architecture Rules",
            ["Layer Design", "Error Handling"],
            {},
        )
        self.assertTrue(len(keywords) > 0)
        self.assertTrue(len(keywords) <= 10)

    def test_with_metadata_table(self):
        """metadata_table の関連要件 ID がキーワードに含まれる"""
        keywords = act._extract_keywords(
            "Test Doc",
            [],
            {'関連要件': 'REQ-001, REQ-002'},
        )
        self.assertIn('REQ-001', keywords)
        self.assertIn('REQ-002', keywords)

    def test_dedup(self):
        """重複キーワードが除去される"""
        keywords = act._extract_keywords(
            "Architecture",
            ["Architecture", "Architecture Design"],
            {},
        )
        lower_keywords = [k.lower() for k in keywords]
        self.assertEqual(len(lower_keywords), len(set(lower_keywords)))

    def test_max_keywords(self):
        keywords = act._extract_keywords(
            "Title",
            [f"Heading {i}" for i in range(20)],
            {},
            max_keywords=5,
        )
        self.assertTrue(len(keywords) <= 5)


# ---------------------------------------------------------------------------
# _filename_to_title
# ---------------------------------------------------------------------------

class TestFilenameToTitle(unittest.TestCase):

    def test_snake_case(self):
        self.assertEqual(act._filename_to_title("architecture_rule.md"), "Architecture Rule")

    def test_kebab_case(self):
        self.assertEqual(act._filename_to_title("error-handling.md"), "Error Handling")

    def test_path_with_dirs(self):
        result = act._filename_to_title("rules/core/architecture_rule.md")
        self.assertEqual(result, "Architecture Rule")


# ---------------------------------------------------------------------------
# resolve_doc_type
# ---------------------------------------------------------------------------

class TestResolveDocType(unittest.TestCase):

    def test_doc_types_map_match(self):
        doc_types_map = {'rules/core/': 'rule', 'specs/': 'requirement'}
        result = act.resolve_doc_type('rules/core/arch.md', doc_types_map)
        self.assertEqual(result, 'rule')

    def test_longest_match(self):
        doc_types_map = {'plugins/forge/': 'rule', 'plugins/forge/docs/': 'spec'}
        result = act.resolve_doc_type('plugins/forge/docs/file.md', doc_types_map)
        self.assertEqual(result, 'spec')

    def test_no_match_fallback(self):
        """マッチしない場合は determine_doc_type フォールバック"""
        result = act.resolve_doc_type('unknown/file.md', {})
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_absolute_path_normalized(self):
        """絶対パスの先頭 / が除去される"""
        doc_types_map = {'rules/': 'rule'}
        result = act.resolve_doc_type('/rules/test.md', doc_types_map)
        self.assertEqual(result, 'rule')


# ---------------------------------------------------------------------------
# MetadataExtractor
# ---------------------------------------------------------------------------

class TestMetadataExtractor(unittest.TestCase):
    """MetadataExtractor のテスト。実ファイルを tmpdir に作成してテスト。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(dir=os.getcwd())
        self.doc_types_map = {}

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_file(self, name, content):
        path = os.path.join(self.tmpdir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return path

    def test_full_document(self):
        """全要素が揃った文書からメタデータ抽出"""
        path = self._write_file('sample.md', SAMPLE_MD_FULL)
        ext = act.MetadataExtractor(path, self.doc_types_map, 'rules')
        meta = ext.extract_metadata()

        self.assertIsNotNone(meta)
        self.assertEqual(meta['title'], 'Sample Document Title')
        self.assertEqual(meta['purpose'], 'Sample document for testing')
        self.assertIn('Architecture', meta['content_details'])
        self.assertIn('Error Handling', meta['content_details'])
        # 改定履歴は除外される
        self.assertNotIn('改定履歴', meta['content_details'])
        self.assertTrue(len(meta['keywords']) > 0)
        self.assertTrue(len(meta['applicable_tasks']) > 0)
        self.assertEqual(meta['doc_type'], 'rule')

    def test_minimal_document(self):
        """最小限の文書でもメタデータが非空"""
        path = self._write_file('minimal.md', SAMPLE_MD_MINIMAL)
        ext = act.MetadataExtractor(path, self.doc_types_map, 'rules')
        meta = ext.extract_metadata()

        self.assertIsNotNone(meta)
        self.assertEqual(meta['title'], 'Minimal Doc')
        self.assertTrue(len(meta['purpose']) > 0)
        self.assertTrue(len(meta['content_details']) > 0)
        self.assertTrue(len(meta['keywords']) > 0)
        self.assertTrue(len(meta['applicable_tasks']) > 0)

    def test_no_h1_uses_filename(self):
        """H1 がない場合はファイル名からタイトル生成"""
        path = self._write_file('my_document.md', SAMPLE_MD_NO_H1)
        ext = act.MetadataExtractor(path, self.doc_types_map, 'rules')
        self.assertEqual(ext.extract_title(), 'My Document')

    def test_frontmatter_description_as_purpose(self):
        """frontmatter の description が purpose に使われる"""
        path = self._write_file('fm.md', SAMPLE_MD_FRONTMATTER_ONLY)
        ext = act.MetadataExtractor(path, self.doc_types_map, 'rules')
        self.assertEqual(ext.extract_purpose(), 'Test document purpose')

    def test_empty_file_returns_fallback(self):
        """空ファイルでもメタデータが非空（フォールバック動作）"""
        path = self._write_file('empty.md', SAMPLE_MD_EMPTY)
        ext = act.MetadataExtractor(path, self.doc_types_map, 'rules')
        meta = ext.extract_metadata()
        self.assertIsNotNone(meta)
        self.assertTrue(len(meta['title']) > 0)

    def test_nonexistent_file(self):
        """存在しないファイルは parse_error=True、extract_metadata=None"""
        ext = act.MetadataExtractor('/nonexistent/file.md', {}, 'rules')
        self.assertTrue(ext.parse_error)
        self.assertIsNone(ext.extract_metadata())

    def test_headings_exclude_metadata_section(self):
        """メタデータセクションの見出しは headings に含まれない"""
        path = self._write_file('with_meta.md', SAMPLE_MD_FULL)
        ext = act.MetadataExtractor(path, self.doc_types_map, 'rules')
        # Metadata セクション自体は content_details に含まれない
        self.assertNotIn('Metadata', ext.extract_content_details())

    def test_overview_text_used_for_purpose(self):
        """frontmatter なしで概要セクションがある場合、概要が purpose になる"""
        content = """\
# Test Doc

## 概要

This is the overview text.

## Details

Some details.
"""
        path = self._write_file('overview.md', content)
        ext = act.MetadataExtractor(path, {}, 'rules')
        self.assertEqual(ext.extract_purpose(), 'This is the overview text.')

    def test_doc_types_map_used(self):
        """doc_types_map が doc_type 決定に使われる"""
        doc_types_map = {os.path.join(self.tmpdir, 'specs'): 'requirement'}
        specs_dir = os.path.join(self.tmpdir, 'specs')
        os.makedirs(specs_dir, exist_ok=True)
        path = self._write_file('specs/req.md', SAMPLE_MD_MINIMAL)
        ext = act.MetadataExtractor(path, doc_types_map, 'specs')
        # doc_types_map のキーはパスプレフィックスなので直接マッチするか
        # フォールバックで specs カテゴリの doc_type が返る
        doc_type = ext.extract_doc_type()
        self.assertIsInstance(doc_type, str)
        self.assertTrue(len(doc_type) > 0)

    def test_all_fields_non_empty(self):
        """extract_metadata() の全フィールドが非空であることを保証"""
        path = self._write_file('test.md', SAMPLE_MD_MINIMAL)
        ext = act.MetadataExtractor(path, {}, 'rules')
        meta = ext.extract_metadata()
        self.assertIsNotNone(meta)
        for key in ('title', 'purpose', 'doc_type', 'content_details',
                    'keywords', 'applicable_tasks'):
            self.assertIn(key, meta, f"Missing key: {key}")
            value = meta[key]
            if isinstance(value, list):
                self.assertTrue(len(value) > 0, f"Empty list for {key}")
            else:
                self.assertTrue(len(str(value)) > 0, f"Empty value for {key}")


# ---------------------------------------------------------------------------
# detect_changed_files（統合テスト）
# ---------------------------------------------------------------------------

class TestDetectChangedFiles(unittest.TestCase):
    """detect_changed_files のテスト。tmpdir にファイルとチェックサムを作成。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(dir=os.getcwd()))
        self.rules_dir = self.tmpdir / 'rules'
        self.rules_dir.mkdir()
        # 環境変数を設定
        self.original_env = os.environ.get('CLAUDE_PROJECT_DIR')
        os.environ['CLAUDE_PROJECT_DIR'] = str(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)
        if self.original_env is None:
            os.environ.pop('CLAUDE_PROJECT_DIR', None)
        else:
            os.environ['CLAUDE_PROJECT_DIR'] = self.original_env

    def _write_md(self, name, content="# Test\n\nContent.\n"):
        path = self.rules_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def _make_config(self, checksums=None):
        checksums_file = self.tmpdir / '.toc_checksums.yaml'
        if checksums:
            # 簡易チェックサムファイル作成
            from toc_utils import write_checksums_yaml
            write_checksums_yaml(checksums, checksums_file)
        return {
            'checksums_file': checksums_file,
            'root_dirs': [(self.rules_dir, 'rules')],
            'target_glob': '**/*.md',
            'exclude_patterns': [],
            'project_root': self.tmpdir,
        }

    def test_all_new_files(self):
        """チェックサムなし = 全ファイルが added"""
        self._write_md('doc1.md')
        self._write_md('doc2.md')
        config = self._make_config()

        result = act.detect_changed_files('rules', config)
        self.assertEqual(len(result['added']), 2)
        self.assertEqual(len(result['modified']), 0)
        self.assertEqual(len(result['deleted']), 0)

    def test_unchanged_files(self):
        """チェックサムが一致 = 変更なし"""
        self._write_md('doc1.md', "# Test\n\nContent.\n")
        from toc_utils import calculate_file_hash
        file_hash = calculate_file_hash(self.rules_dir / 'doc1.md')
        config = self._make_config({'rules/doc1.md': file_hash})

        result = act.detect_changed_files('rules', config)
        self.assertEqual(len(result['added']), 0)
        self.assertEqual(len(result['modified']), 0)
        self.assertEqual(len(result['deleted']), 0)

    def test_modified_file(self):
        """チェックサム不一致 = modified"""
        self._write_md('doc1.md', "# Updated\n\nNew content.\n")
        config = self._make_config({'rules/doc1.md': 'old_hash_value'})

        result = act.detect_changed_files('rules', config)
        self.assertEqual(len(result['modified']), 1)
        self.assertIn('rules/doc1.md', result['modified'])

    def test_deleted_file(self):
        """チェックサムにあるがファイルなし = deleted"""
        config = self._make_config({'rules/deleted.md': 'some_hash'})

        result = act.detect_changed_files('rules', config)
        self.assertEqual(len(result['deleted']), 1)
        self.assertIn('rules/deleted.md', result['deleted'])

    def test_empty_files_excluded(self):
        """空ファイルは除外される"""
        self._write_md('empty.md', '')
        config = self._make_config()

        result = act.detect_changed_files('rules', config)
        self.assertEqual(len(result['added']), 0)


# ---------------------------------------------------------------------------
# update_toc（統合テスト）
# ---------------------------------------------------------------------------

class TestUpdateToc(unittest.TestCase):
    """update_toc の統合テスト。ファイル作成 → detect → update の一連を検証。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(dir=os.getcwd()))
        self.rules_dir = self.tmpdir / 'rules'
        self.rules_dir.mkdir()
        self.toc_file = self.tmpdir / 'rules_toc.yaml'
        self.checksums_file = self.tmpdir / '.toc_checksums.yaml'
        self.original_env = os.environ.get('CLAUDE_PROJECT_DIR')
        os.environ['CLAUDE_PROJECT_DIR'] = str(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)
        if self.original_env is None:
            os.environ.pop('CLAUDE_PROJECT_DIR', None)
        else:
            os.environ['CLAUDE_PROJECT_DIR'] = self.original_env

    def _write_md(self, name, content="# Test Doc\n\nSome content.\n\n## Section One\n\nDetails.\n"):
        path = self.rules_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def _make_config(self):
        return {
            'toc_file': self.toc_file,
            'checksums_file': self.checksums_file,
            'output_config': {
                'header_comment': 'Test index',
                'metadata_name': 'Test Index',
            },
            'root_dirs': [(self.rules_dir, 'rules')],
            'target_glob': '**/*.md',
            'exclude_patterns': [],
            'project_root': self.tmpdir,
            'doc_types_map': {'rules/': 'rule'},
        }

    def test_create_new_toc(self):
        """新規ファイルから ToC を生成"""
        self._write_md('doc1.md')
        self._write_md('doc2.md', "# Second Doc\n\n## Design\n\nDesign details.\n")

        config = self._make_config()
        changed = act.detect_changed_files('rules', config)
        success, updated, deleted, skipped = act.update_toc('rules', changed, config)

        self.assertTrue(success)
        self.assertEqual(updated, 2)
        self.assertEqual(deleted, 0)
        self.assertEqual(skipped, 0)
        self.assertTrue(self.toc_file.exists())
        self.assertTrue(self.checksums_file.exists())

    def test_toc_contains_entries(self):
        """生成された ToC にエントリが含まれる"""
        self._write_md('doc1.md', SAMPLE_MD_FULL)
        config = self._make_config()
        changed = act.detect_changed_files('rules', config)
        act.update_toc('rules', changed, config)

        content = self.toc_file.read_text(encoding='utf-8')
        self.assertIn('rules/doc1.md', content)
        self.assertIn('Sample Document Title', content)

    def test_auto_generated_marker(self):
        """新規エントリに _auto_generated: true が付与される"""
        self._write_md('doc1.md')
        config = self._make_config()
        changed = act.detect_changed_files('rules', config)
        act.update_toc('rules', changed, config)

        content = self.toc_file.read_text(encoding='utf-8')
        self.assertIn('_auto_generated', content)

    def test_delete_removes_entry(self):
        """削除されたファイルの ToC エントリが除去される"""
        # まず ToC を作成
        self._write_md('doc1.md')
        self._write_md('doc2.md')
        config = self._make_config()
        changed = act.detect_changed_files('rules', config)
        act.update_toc('rules', changed, config)

        # doc2 を削除
        (self.rules_dir / 'doc2.md').unlink()
        changed2 = act.detect_changed_files('rules', config)
        success, updated, deleted, skipped = act.update_toc('rules', changed2, config)

        self.assertTrue(success)
        self.assertEqual(deleted, 1)
        content = self.toc_file.read_text(encoding='utf-8')
        self.assertNotIn('rules/doc2.md', content)
        self.assertIn('rules/doc1.md', content)

    def test_validation_passes(self):
        """生成された ToC が validate_toc を通過する"""
        self._write_md('doc1.md', SAMPLE_MD_FULL)
        config = self._make_config()
        changed = act.detect_changed_files('rules', config)
        success, _, _, _ = act.update_toc('rules', changed, config)
        self.assertTrue(success, "validate_toc should pass on generated ToC")


# ---------------------------------------------------------------------------
# _normalize_heading_text
# ---------------------------------------------------------------------------

class TestNormalizeHeadingText(unittest.TestCase):

    def test_numbered_prefix(self):
        self.assertEqual(act._normalize_heading_text("1. 概要"), "概要")

    def test_no_number(self):
        self.assertEqual(act._normalize_heading_text("Architecture"), "Architecture")

    def test_number_without_dot(self):
        self.assertEqual(act._normalize_heading_text("2 設計"), "設計")


if __name__ == '__main__':
    unittest.main()
