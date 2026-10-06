#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""resolve_doc_structure.py のユニットテスト。"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# テスト対象モジュールの import
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'plugins', 'forge',
    'scripts', 'doc_structure'
))
import resolve_doc_structure as rds


# ---------------------------------------------------------------------------
# テスト用 YAML データ
# ---------------------------------------------------------------------------

BASIC_CONFIG = """\
# doc_structure_version: 3.0

rules:
  root_dirs:
    - docs/rules/
  doc_types_map:
    docs/rules/: rule
  toc_file: .claude/doc-advisor/toc/rules/rules_toc.yaml
  checksums_file: .claude/doc-advisor/toc/rules/.toc_checksums.yaml
  work_dir: .claude/doc-advisor/toc/rules/.toc_work/
  patterns:
    target_glob: "**/*.md"
    exclude: []
  output:
    header_comment: "Development documentation search index"
    metadata_name: "Development Document Search Index"

specs:
  root_dirs:
    - docs/specs/design/
    - docs/specs/plan/
  doc_types_map:
    docs/specs/design/: design
    docs/specs/plan/: plan
  toc_file: .claude/doc-advisor/toc/specs/specs_toc.yaml
  checksums_file: .claude/doc-advisor/toc/specs/.toc_checksums.yaml
  work_dir: .claude/doc-advisor/toc/specs/.toc_work/
  patterns:
    target_glob: "**/*.md"
    exclude: []
  output:
    header_comment: "Project specification document search index"
    metadata_name: "Project Specification Document Search Index"

common:
  parallel:
    max_workers: 5
    fallback_to_serial: true
"""

GLOB_CONFIG = """\
# doc_structure_version: 3.0

specs:
  root_dirs:
    - "docs/specs/*/design/"
    - "docs/specs/*/plan/"
    - "docs/specs/*/requirement/"
  doc_types_map:
    "docs/specs/*/design/": design
    "docs/specs/*/plan/": plan
    "docs/specs/*/requirement/": requirement
  patterns:
    target_glob: "**/*.md"
    exclude: []

rules:
  root_dirs:
    - docs/rules/
  doc_types_map:
    docs/rules/: rule
  patterns:
    target_glob: "**/*.md"
    exclude: []
"""

DOUBLESTAR_GLOB_CONFIG = """\
# doc_structure_version: 3.0

specs:
  root_dirs:
    - "docs/specs/**/design/"
    - "docs/specs/**/plan/"
    - "docs/specs/**/requirements/"
  doc_types_map:
    "docs/specs/**/design/": design
    "docs/specs/**/plan/": plan
    "docs/specs/**/requirements/": requirement
  patterns:
    target_glob: "**/*.md"
    exclude: []

rules:
  root_dirs:
    - docs/rules/
  doc_types_map:
    docs/rules/: rule
  patterns:
    target_glob: "**/*.md"
    exclude: []
"""

DOUBLESTAR_EXCLUDE_CONFIG = """\
specs:
  root_dirs:
    - "docs/specs/**/design/"
  doc_types_map:
    "docs/specs/**/design/": design
  patterns:
    target_glob: "**/*.md"
    exclude:
      - archived
"""

EXCLUDE_CONFIG = """\
specs:
  root_dirs:
    - "docs/specs/*/design/"
  doc_types_map:
    "docs/specs/*/design/": design
  patterns:
    target_glob: "**/*.md"
    exclude:
      - archived
      - _template
"""

MINIMAL_CONFIG = """\
rules:
  root_dirs:
    - rules/
  doc_types_map:
    rules/: rule
"""

NO_VERSION_CONFIG = """\
rules:
  root_dirs:
    - rules/
  doc_types_map:
    rules/: rule
"""


# ---------------------------------------------------------------------------
# テストヘルパー
# ---------------------------------------------------------------------------

def create_test_project(tmpdir, structure):
    """テスト用ディレクトリ構造を作成する。

    Args:
        tmpdir: 一時ディレクトリのパス
        structure: ファイルパスのリスト（ディレクトリは末尾 /）
    """
    for path in structure:
        full = os.path.join(tmpdir, path)
        if path.endswith('/'):
            os.makedirs(full, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, 'w') as f:
                f.write(f'# {os.path.basename(path)}\n')


# ===========================================================================
# テストクラス
# ===========================================================================

class TestGetVersion(unittest.TestCase):
    """バージョン検出のテスト"""

    def test_get_version_normal(self):
        self.assertEqual(rds.get_version(BASIC_CONFIG), '3.0')

    def test_get_version_none(self):
        self.assertIsNone(rds.get_version(NO_VERSION_CONFIG))

    def test_get_major_version(self):
        self.assertEqual(rds.get_major_version(BASIC_CONFIG), 3)

    def test_get_major_version_none(self):
        self.assertIsNone(rds.get_major_version(NO_VERSION_CONFIG))

    def test_get_version_different_versions(self):
        content = '# doc_structure_version: 3.1\nrules:\n  root_dirs:\n    - r/\n'
        self.assertEqual(rds.get_version(content), '3.1')
        self.assertEqual(rds.get_major_version(content), 3)


class TestNormalizePath(unittest.TestCase):
    """パス正規化のテスト"""

    def test_ascii_unchanged(self):
        self.assertEqual(rds.normalize_path('docs/rules/'), 'docs/rules/')

    def test_nfc_normalization(self):
        import unicodedata
        # NFD 形式の「プ」
        nfd = unicodedata.normalize('NFD', 'プラグイン')
        result = rds.normalize_path(nfd)
        self.assertEqual(result, unicodedata.normalize('NFC', 'プラグイン'))


class TestParseConfig(unittest.TestCase):
    """config.yaml パーサーのテスト"""

    def test_basic_structure(self):
        config = rds.parse_config(BASIC_CONFIG)
        self.assertIn('rules', config)
        self.assertIn('specs', config)
        self.assertIn('common', config)

    def test_root_dirs(self):
        config = rds.parse_config(BASIC_CONFIG)
        self.assertEqual(config['rules']['root_dirs'], ['docs/rules/'])
        self.assertEqual(
            config['specs']['root_dirs'],
            ['docs/specs/design/', 'docs/specs/plan/']
        )

    def test_doc_types_map(self):
        config = rds.parse_config(BASIC_CONFIG)
        self.assertEqual(config['rules']['doc_types_map'], {'docs/rules/': 'rule'})
        self.assertEqual(
            config['specs']['doc_types_map'],
            {'docs/specs/design/': 'design', 'docs/specs/plan/': 'plan'}
        )

    def test_glob_root_dirs(self):
        config = rds.parse_config(GLOB_CONFIG)
        self.assertEqual(
            config['specs']['root_dirs'],
            ['docs/specs/*/design/', 'docs/specs/*/plan/', 'docs/specs/*/requirement/']
        )

    def test_glob_doc_types_map(self):
        config = rds.parse_config(GLOB_CONFIG)
        dtm = config['specs']['doc_types_map']
        self.assertEqual(dtm['docs/specs/*/design/'], 'design')
        self.assertEqual(dtm['docs/specs/*/plan/'], 'plan')
        self.assertEqual(dtm['docs/specs/*/requirement/'], 'requirement')

    def test_patterns_exclude(self):
        config = rds.parse_config(EXCLUDE_CONFIG)
        self.assertEqual(
            config['specs']['patterns']['exclude'],
            ['archived', '_template']
        )

    def test_patterns_empty_exclude(self):
        config = rds.parse_config(BASIC_CONFIG)
        self.assertEqual(config['rules']['patterns']['exclude'], [])

    def test_scalar_values(self):
        config = rds.parse_config(BASIC_CONFIG)
        self.assertEqual(config['rules']['toc_file'],
                         '.claude/doc-advisor/toc/rules/rules_toc.yaml')

    def test_common_section(self):
        config = rds.parse_config(BASIC_CONFIG)
        self.assertEqual(config['common']['parallel']['max_workers'], 5)
        self.assertTrue(config['common']['parallel']['fallback_to_serial'])

    def test_inline_array(self):
        content = 'rules:\n  root_dirs: [a/, b/]\n  doc_types_map:\n    a/: rule\n'
        config = rds.parse_config(content)
        self.assertEqual(config['rules']['root_dirs'], ['a/', 'b/'])

    def test_minimal(self):
        config = rds.parse_config(MINIMAL_CONFIG)
        self.assertEqual(config['rules']['root_dirs'], ['rules/'])
        self.assertEqual(config['rules']['doc_types_map'], {'rules/': 'rule'})

    def test_comments_skipped(self):
        content = '# comment\nrules:\n  # inner comment\n  root_dirs:\n    - r/\n'
        config = rds.parse_config(content)
        self.assertEqual(config['rules']['root_dirs'], ['r/'])

    def test_empty_section(self):
        content = 'rules:\n  root_dirs:\n    - r/\nspecs:\n'
        config = rds.parse_config(content)
        self.assertIn('specs', config)

    def test_output_subsection(self):
        config = rds.parse_config(BASIC_CONFIG)
        self.assertEqual(
            config['rules']['output']['header_comment'],
            'Development documentation search index'
        )


class TestExpandGlobs(unittest.TestCase):
    """glob 展開のテスト"""

    def test_no_glob(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, 'docs', 'rules'))
            result = rds.expand_globs(['docs/rules/'], tmpdir)
            self.assertEqual(result, ['docs/rules/'])

    def test_glob_expansion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, [
                'docs/specs/auth/design/',
                'docs/specs/login/design/',
            ])
            result = rds.expand_globs(['docs/specs/*/design/'], tmpdir)
            self.assertEqual(len(result), 2)
            self.assertIn('docs/specs/auth/design/', result)
            self.assertIn('docs/specs/login/design/', result)

    def test_glob_no_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = rds.expand_globs(['docs/specs/*/design/'], tmpdir)
            # マッチなしの場合は元のリストを返す
            self.assertEqual(result, ['docs/specs/*/design/'])

    def test_mixed_glob_and_literal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, [
                'docs/rules/',
                'docs/specs/auth/design/',
            ])
            result = rds.expand_globs(
                ['docs/rules/', 'docs/specs/*/design/'], tmpdir
            )
            self.assertEqual(len(result), 2)
            self.assertIn('docs/rules/', result)
            self.assertIn('docs/specs/auth/design/', result)


class TestIsExcluded(unittest.TestCase):
    """exclude 判定のテスト"""

    def test_no_exclude(self):
        self.assertFalse(
            rds.is_excluded(Path('/root/docs/a.md'), Path('/root'), [])
        )

    def test_dir_name_match(self):
        self.assertTrue(
            rds.is_excluded(
                Path('/root/docs/archived/a.md'),
                Path('/root'),
                ['archived']
            )
        )

    def test_dir_name_no_match(self):
        self.assertFalse(
            rds.is_excluded(
                Path('/root/docs/active/a.md'),
                Path('/root'),
                ['archived']
            )
        )

    def test_filename_not_excluded(self):
        """ファイル名は exclude 対象外（ディレクトリ名のみ）"""
        self.assertFalse(
            rds.is_excluded(
                Path('/root/docs/archived.md'),
                Path('/root'),
                ['archived']
            )
        )

    def test_path_pattern(self):
        self.assertTrue(
            rds.is_excluded(
                Path('/root/docs/old/archive/a.md'),
                Path('/root'),
                ['old/archive']
            )
        )

    def test_multiple_patterns(self):
        self.assertTrue(
            rds.is_excluded(
                Path('/root/docs/_template/a.md'),
                Path('/root'),
                ['archived', '_template']
            )
        )


class TestCollectMdFiles(unittest.TestCase):
    """ファイル収集のテスト"""

    def test_collect_basic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, [
                'docs/rules/a.md',
                'docs/rules/b.md',
                'docs/rules/c.txt',
            ])
            result = rds.collect_md_files(
                os.path.join(tmpdir, 'docs/rules'), [], tmpdir
            )
            self.assertEqual(len(result), 2)
            self.assertTrue(all(f.endswith('.md') for f in result))

    def test_collect_with_exclude(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, [
                'docs/rules/a.md',
                'docs/rules/archived/b.md',
            ])
            result = rds.collect_md_files(
                os.path.join(tmpdir, 'docs/rules'), ['archived'], tmpdir
            )
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0], 'docs/rules/a.md')

    def test_collect_nonexistent_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = rds.collect_md_files(
                os.path.join(tmpdir, 'nonexistent'), [], tmpdir
            )
            self.assertEqual(result, [])

    def test_collect_recursive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, [
                'docs/rules/a.md',
                'docs/rules/sub/b.md',
                'docs/rules/sub/deep/c.md',
            ])
            result = rds.collect_md_files(
                os.path.join(tmpdir, 'docs/rules'), [], tmpdir
            )
            self.assertEqual(len(result), 3)


class TestInvertDocTypesMap(unittest.TestCase):
    """doc_types_map 逆引きのテスト"""

    def test_basic(self):
        dtm = {'docs/design/': 'design', 'docs/plan/': 'plan'}
        inverted = rds.invert_doc_types_map(dtm)
        self.assertEqual(inverted, {
            'design': ['docs/design/'],
            'plan': ['docs/plan/'],
        })

    def test_multiple_paths_same_type(self):
        dtm = {'a/': 'rule', 'b/': 'rule'}
        inverted = rds.invert_doc_types_map(dtm)
        self.assertEqual(len(inverted['rule']), 2)

    def test_empty(self):
        self.assertEqual(rds.invert_doc_types_map({}), {})


class TestMatchPathToDocType(unittest.TestCase):
    """パスから doc_type 判定のテスト"""

    def test_literal_match(self):
        dtm = {'docs/rules/': 'rule'}
        result = rds.match_path_to_doc_type('docs/rules/a.md', dtm, '/tmp')
        self.assertEqual(result, 'rule')

    def test_no_match(self):
        dtm = {'docs/rules/': 'rule'}
        result = rds.match_path_to_doc_type('src/main.py', dtm, '/tmp')
        self.assertIsNone(result)

    def test_glob_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, ['docs/specs/auth/design/'])
            dtm = {'docs/specs/*/design/': 'design'}
            result = rds.match_path_to_doc_type(
                'docs/specs/auth/design/a.md', dtm, tmpdir
            )
            self.assertEqual(result, 'design')


class TestDetectFeatures(unittest.TestCase):
    """Feature 検出のテスト"""

    def test_single_feature(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, [
                'docs/specs/forge/design/',
                'docs/specs/forge/plan/',
            ])
            config = rds.parse_config(GLOB_CONFIG)
            features = rds.detect_features(config, tmpdir)
            self.assertEqual(features, ['forge'])

    def test_multiple_features(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, [
                'docs/specs/auth/design/',
                'docs/specs/login/design/',
                'docs/specs/payment/plan/',
            ])
            config = rds.parse_config(GLOB_CONFIG)
            features = rds.detect_features(config, tmpdir)
            self.assertEqual(features, ['auth', 'login', 'payment'])

    def test_no_features(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = rds.parse_config(GLOB_CONFIG)
            features = rds.detect_features(config, tmpdir)
            self.assertEqual(features, [])

    def test_exclude_applied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, [
                'docs/specs/auth/design/',
                'docs/specs/archived/design/',
            ])
            config = rds.parse_config(EXCLUDE_CONFIG)
            features = rds.detect_features(config, tmpdir)
            self.assertEqual(features, ['auth'])

    def test_no_glob_no_features(self):
        """glob パターンのない設定では Feature は検出されない"""
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, ['docs/specs/design/'])
            config = rds.parse_config(BASIC_CONFIG)
            features = rds.detect_features(config, tmpdir)
            self.assertEqual(features, [])

    def test_doublestar_mixed_depth(self):
        """** パターンで1階層と2階層の混在から全 Feature を検出"""
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, [
                'docs/specs/forge/design/',
                'docs/specs/forge/review-PR/design/',
                'docs/specs/doc-advisor/design/',
                'docs/specs/doc-advisor/semantic-query/design/',
            ])
            config = rds.parse_config(DOUBLESTAR_GLOB_CONFIG)
            features = rds.detect_features(config, tmpdir)
            self.assertEqual(features, ['doc-advisor', 'forge'])

    def test_doublestar_dedup(self):
        """同一 Feature が複数深さに存在しても重複しない"""
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, [
                'docs/specs/forge/design/',
                'docs/specs/forge/plan/',
                'docs/specs/forge/review-PR/design/',
                'docs/specs/forge/review-PR/plan/',
            ])
            config = rds.parse_config(DOUBLESTAR_GLOB_CONFIG)
            features = rds.detect_features(config, tmpdir)
            self.assertEqual(features, ['forge'])

    def test_doublestar_exclude(self):
        """** パターンでも exclude が機能する"""
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, [
                'docs/specs/auth/design/',
                'docs/specs/archived/design/',
                'docs/specs/auth/sub/design/',
            ])
            config = rds.parse_config(DOUBLESTAR_EXCLUDE_CONFIG)
            features = rds.detect_features(config, tmpdir)
            self.assertEqual(features, ['auth'])


class TestExtractFeatureFromMatch(unittest.TestCase):
    """Feature 名抽出のテスト"""

    def test_basic(self):
        result = rds._extract_feature_from_match(
            'docs/specs/*/design', 'docs/specs/forge/design'
        )
        self.assertEqual(result, 'forge')

    def test_mismatch_length(self):
        result = rds._extract_feature_from_match(
            'docs/specs/*/design', 'docs/specs/forge/design/sub'
        )
        self.assertIsNone(result)

    def test_doublestar_single_depth(self):
        """** パターンで1階層マッチ"""
        result = rds._extract_feature_from_match(
            'docs/specs/**/design', 'docs/specs/forge/design'
        )
        self.assertEqual(result, 'forge')

    def test_doublestar_two_depth(self):
        """** パターンで2階層マッチ — 最初のセグメントが Feature"""
        result = rds._extract_feature_from_match(
            'docs/specs/**/design', 'docs/specs/forge/review-PR/design'
        )
        self.assertEqual(result, 'forge')

    def test_doublestar_two_depth_another(self):
        """** パターンで別の Feature の2階層マッチ"""
        result = rds._extract_feature_from_match(
            'docs/specs/**/design', 'docs/specs/doc-advisor/semantic-query/design'
        )
        self.assertEqual(result, 'doc-advisor')

    def test_doublestar_zero_capture(self):
        """** が0セグメントをキャプチャした場合は None"""
        result = rds._extract_feature_from_match(
            'docs/specs/**/design', 'docs/specs/design'
        )
        self.assertIsNone(result)

    def test_doublestar_multiple_rejected(self):
        """複数 ** を含むパターンは未対応で None"""
        result = rds._extract_feature_from_match(
            'docs/**/specs/**/design', 'docs/a/specs/b/design'
        )
        self.assertIsNone(result)

    def test_doublestar_prefix_star_priority(self):
        """prefix 内の * は ** より優先される"""
        result = rds._extract_feature_from_match(
            'docs/*/specs/**/design', 'docs/myproject/specs/forge/design'
        )
        self.assertEqual(result, 'myproject')

    def test_doublestar_suffix_star(self):
        """suffix 内の * が正しくマッチする"""
        result = rds._extract_feature_from_match(
            'docs/specs/**/*/design', 'docs/specs/forge/review-PR/design'
        )
        self.assertEqual(result, 'review-PR')

    def test_backward_compat_single_star(self):
        """従来の * パターンが変わらず動作する"""
        result = rds._extract_feature_from_match(
            'docs/specs/*/design', 'docs/specs/auth/design'
        )
        self.assertEqual(result, 'auth')

    def test_no_wildcard(self):
        """ワイルドカードなしのパターンは None"""
        result = rds._extract_feature_from_match(
            'docs/specs/design', 'docs/specs/design'
        )
        self.assertIsNone(result)


class TestResolveFiles(unittest.TestCase):
    """ファイル解決のテスト"""

    def test_basic_resolve(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, [
                'docs/rules/a.md',
                'docs/rules/b.md',
            ])
            config = rds.parse_config(BASIC_CONFIG)
            result = rds.resolve_files(config, 'rules', tmpdir)
            self.assertEqual(len(result), 2)

    def test_glob_resolve(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, [
                'docs/specs/auth/design/a.md',
                'docs/specs/login/design/b.md',
                'docs/specs/auth/plan/c.md',
            ])
            config = rds.parse_config(GLOB_CONFIG)
            result = rds.resolve_files(config, 'specs', tmpdir)
            self.assertEqual(len(result), 3)

    def test_deduplication(self):
        """同一ファイルが複数パスにマッチしても1回のみ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, ['docs/rules/a.md'])
            content = 'rules:\n  root_dirs:\n    - docs/rules/\n    - docs/rules/\n  doc_types_map:\n    docs/rules/: rule\n'
            config = rds.parse_config(content)
            result = rds.resolve_files(config, 'rules', tmpdir)
            self.assertEqual(len(result), 1)

    def test_empty_category(self):
        config = rds.parse_config(MINIMAL_CONFIG)
        result = rds.resolve_files(config, 'specs', '/tmp')
        self.assertEqual(result, [])


class TestResolveFilesByDocType(unittest.TestCase):
    """doc_type 別ファイル解決のテスト"""

    def test_basic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, [
                'docs/specs/design/a.md',
                'docs/specs/plan/b.md',
            ])
            config = rds.parse_config(BASIC_CONFIG)
            result = rds.resolve_files_by_doc_type(config, 'specs', 'design', tmpdir)
            self.assertEqual(len(result), 1)
            self.assertIn('docs/specs/design/a.md', result)

    def test_glob(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, [
                'docs/specs/auth/design/a.md',
                'docs/specs/login/design/b.md',
                'docs/specs/auth/plan/c.md',
            ])
            config = rds.parse_config(GLOB_CONFIG)
            result = rds.resolve_files_by_doc_type(config, 'specs', 'design', tmpdir)
            self.assertEqual(len(result), 2)
            self.assertTrue(all('design' in f for f in result))

    def test_nonexistent_type(self):
        config = rds.parse_config(BASIC_CONFIG)
        result = rds.resolve_files_by_doc_type(config, 'specs', 'api', '/tmp')
        self.assertEqual(result, [])


class TestLoadDocStructure(unittest.TestCase):
    """ファイル読み込みのテスト"""

    def test_load_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ds_path = os.path.join(tmpdir, '.doc_structure.yaml')
            with open(ds_path, 'w') as f:
                f.write(BASIC_CONFIG)
            config, content = rds.load_doc_structure(tmpdir)
            self.assertIn('rules', config)
            self.assertIn('doc_structure_version', content)

    def test_load_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(FileNotFoundError):
                rds.load_doc_structure(tmpdir)

    def test_load_custom_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom = os.path.join(tmpdir, 'custom.yaml')
            with open(custom, 'w') as f:
                f.write(MINIMAL_CONFIG)
            config, _ = rds.load_doc_structure(tmpdir, custom)
            self.assertIn('rules', config)


class TestFindProjectRoot(unittest.TestCase):
    """プロジェクトルート検出のテスト"""

    def test_with_explicit_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            real_tmpdir = os.path.realpath(tmpdir)
            result = rds.find_project_root(real_tmpdir)
            self.assertEqual(result, real_tmpdir)

    def test_without_args_returns_cwd(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            real_tmpdir = os.path.realpath(tmpdir)
            original_cwd = os.getcwd()
            try:
                os.chdir(real_tmpdir)
                result = rds.find_project_root()
                self.assertEqual(result, real_tmpdir)
            finally:
                os.chdir(original_cwd)

    def test_resolves_symlinks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            real_tmpdir = os.path.realpath(tmpdir)
            result = rds.find_project_root(tmpdir)
            self.assertEqual(result, real_tmpdir)


# ---------------------------------------------------------------------------
# テスト用 YAML データ（バリデーション用）
# ---------------------------------------------------------------------------

V1_CONFIG = """\
version: "1.0"

rules:
  - docs/rules/
specs:
  - docs/specs/
"""

V2_WITH_ROOT_DIRS_CONFIG = """\
# doc_structure_version: 2.0

rules:
  root_dirs:
    - docs/rules/
  doc_types_map:
    docs/rules/: rule

specs:
  root_dirs:
    - docs/specs/design/
  doc_types_map:
    docs/specs/design/: design
"""

NO_ROOT_DIRS_CONFIG = """\
# doc_structure_version: 3.0

rules:
  doc_types_map:
    docs/rules/: rule

specs:
  doc_types_map:
    docs/specs/design/: design
"""

EMPTY_ROOT_DIRS_CONFIG = """\
# doc_structure_version: 3.0

rules:
  root_dirs: []
  doc_types_map:
    docs/rules/: rule
"""


class TestValidateDocStructure(unittest.TestCase):
    """バリデーションのテスト"""

    def test_valid_v3(self):
        """v3 フォーマット → valid"""
        config = rds.parse_config(BASIC_CONFIG)
        result = rds.validate_doc_structure(config, BASIC_CONFIG)
        self.assertTrue(result['valid'])

    def test_missing_root_dirs(self):
        """root_dirs なし → invalid"""
        config = rds.parse_config(NO_ROOT_DIRS_CONFIG)
        result = rds.validate_doc_structure(config, NO_ROOT_DIRS_CONFIG)
        self.assertFalse(result['valid'])
        self.assertIn('root_dirs', result['error'])
        self.assertIn('suggestion', result)

    def test_v1_format(self):
        """v1 形式 → invalid（root_dirs が存在しない）"""
        config = rds.parse_config(V1_CONFIG)
        result = rds.validate_doc_structure(config, V1_CONFIG)
        self.assertFalse(result['valid'])
        self.assertIn('root_dirs', result['error'])

    def test_v1_format_with_comment_version(self):
        """v1 形式（コメントでバージョン明示）→ invalid + 旧フォーマットメッセージ"""
        content = "# doc_structure_version: 1.0\nrules:\n  - docs/rules/\n"
        config = rds.parse_config(content)
        result = rds.validate_doc_structure(config, content)
        self.assertFalse(result['valid'])
        self.assertIn('旧フォーマット', result['error'])
        self.assertIn('v1', result['error'])

    def test_v2_format_with_root_dirs(self):
        """v2 形式 + root_dirs あり → valid（警告付き）"""
        config = rds.parse_config(V2_WITH_ROOT_DIRS_CONFIG)
        result = rds.validate_doc_structure(config, V2_WITH_ROOT_DIRS_CONFIG)
        self.assertTrue(result['valid'])
        self.assertIn('version_warning', result)

    def test_no_version_with_root_dirs(self):
        """バージョンコメントなし + root_dirs あり → valid"""
        config = rds.parse_config(NO_VERSION_CONFIG)
        result = rds.validate_doc_structure(config, NO_VERSION_CONFIG)
        self.assertTrue(result['valid'])

    def test_no_version_no_root_dirs(self):
        """バージョンコメントなし + root_dirs なし → invalid"""
        content = "rules:\n  doc_types_map:\n    docs/: rule\n"
        config = rds.parse_config(content)
        result = rds.validate_doc_structure(config, content)
        self.assertFalse(result['valid'])
        self.assertIn('root_dirs', result['error'])

    def test_empty_root_dirs(self):
        """root_dirs が空配列 → valid（設定として正当）"""
        config = rds.parse_config(EMPTY_ROOT_DIRS_CONFIG)
        result = rds.validate_doc_structure(config, EMPTY_ROOT_DIRS_CONFIG)
        self.assertTrue(result['valid'])

    def test_cli_type_with_invalid(self):
        """--type all で旧フォーマット → exit(1) + error JSON"""
        import subprocess
        with tempfile.TemporaryDirectory() as tmpdir:
            ds_path = os.path.join(tmpdir, '.doc_structure.yaml')
            with open(ds_path, 'w') as f:
                f.write(V1_CONFIG)
            os.makedirs(os.path.join(tmpdir, '.git'))

            script = os.path.join(
                os.path.dirname(__file__), '..', '..', '..', 'plugins',
                'forge', 'scripts', 'doc_structure',
                'resolve_doc_structure.py'
            )
            proc = subprocess.run(
                [sys.executable, script, '--type', 'all',
                 '--project-root', tmpdir],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 1)
            data = json.loads(proc.stdout)
            self.assertEqual(data['status'], 'error')
            self.assertIn('suggestion', data)


# ---------------------------------------------------------------------------
# 置き場ディレクトリ・Feature の解決
# ---------------------------------------------------------------------------

DIR_OF_CONFIG = """\
# doc_structure_version: 3.0

rules:
  root_dirs:
    - docs/rules/
  doc_types_map:
    docs/rules/: rule

specs:
  root_dirs:
    - docs/specs/**/requirements/
    - docs/specs/**/design/
  doc_types_map:
    docs/specs/**/requirements/: requirement
    docs/specs/**/design/: design
"""

SINGLE_STAR_CONFIG = """\
# doc_structure_version: 3.0

specs:
  root_dirs:
    - docs/specs/*/design/
  doc_types_map:
    docs/specs/*/design/: design
"""

PARTIAL_WILDCARD_CONFIG = """\
# doc_structure_version: 3.0

specs:
  root_dirs:
    - docs/specs/feat-*/design/
  doc_types_map:
    docs/specs/feat-*/design/: design
"""


class TestResolveDocTypeDir(unittest.TestCase):
    """置き場ディレクトリの解決のテスト"""

    def setUp(self):
        self.config = rds.parse_config(DIR_OF_CONFIG)

    def test_with_feature_replaces_doublestar(self):
        result = rds.resolve_doc_type_dir(self.config, 'specs', 'design', 'forge')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['dir'], 'docs/specs/forge/design/')
        self.assertEqual(result['feature'], 'forge')
        self.assertTrue(result['feature_applied'])

    def test_with_sub_feature_path(self):
        """feature がスラッシュを含んでも、そのままの階層として置換する"""
        result = rds.resolve_doc_type_dir(
            self.config, 'specs', 'design', 'forge/review-PR'
        )
        self.assertEqual(result['dir'], 'docs/specs/forge/review-PR/design/')

    def test_without_feature_removes_doublestar(self):
        result = rds.resolve_doc_type_dir(self.config, 'specs', 'design')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['dir'], 'docs/specs/design/')
        self.assertIsNone(result['feature'])
        self.assertIsNone(result['feature_applied'])

    def test_requirement_without_feature(self):
        result = rds.resolve_doc_type_dir(self.config, 'specs', 'requirement')
        self.assertEqual(result['dir'], 'docs/specs/requirements/')

    def test_single_star(self):
        config = rds.parse_config(SINGLE_STAR_CONFIG)
        with_feature = rds.resolve_doc_type_dir(config, 'specs', 'design', 'auth')
        self.assertEqual(with_feature['dir'], 'docs/specs/auth/design/')

    def test_single_star_without_feature_is_error(self):
        """`*` は 1 セグメントに必ず当たる。feature なしの置き場はキーに含まれず、索引の対象外になる"""
        config = rds.parse_config(SINGLE_STAR_CONFIG)
        result = rds.resolve_doc_type_dir(config, 'specs', 'design')
        self.assertEqual(result['status'], 'error')
        self.assertIn('feature が必要', result['message'])

    def test_single_star_rejects_multi_level_feature(self):
        config = rds.parse_config(SINGLE_STAR_CONFIG)
        result = rds.resolve_doc_type_dir(config, 'specs', 'design', 'forge/review-PR')
        self.assertEqual(result['status'], 'error')

    def test_key_without_wildcard_is_the_key_itself(self):
        config = rds.parse_config(BASIC_CONFIG)
        result = rds.resolve_doc_type_dir(config, 'specs', 'design')
        self.assertEqual(result['dir'], 'docs/specs/design/')

    def test_key_without_wildcard_reports_feature_not_applied(self):
        """feature を置く場所が無いキーでは、feature が使われなかったことを示す"""
        config = rds.parse_config(BASIC_CONFIG)
        result = rds.resolve_doc_type_dir(config, 'specs', 'design', 'forge')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['dir'], 'docs/specs/design/')
        self.assertFalse(result['feature_applied'])

    def test_partial_segment_wildcard_is_error(self):
        """ワイルドカード以外の glob 文字を含むセグメントは、置き場を決められない"""
        config = rds.parse_config(PARTIAL_WILDCARD_CONFIG)
        result = rds.resolve_doc_type_dir(config, 'specs', 'design')
        self.assertEqual(result['status'], 'error')
        self.assertIn('feat-*', result['message'])

    def test_unknown_doc_type_is_error(self):
        result = rds.resolve_doc_type_dir(self.config, 'specs', 'api')
        self.assertEqual(result['status'], 'error')
        self.assertIn('api', result['message'])

    def test_invalid_feature_is_error(self):
        for bad in ('', '..', '../x', 'a/../b'):
            result = rds.resolve_doc_type_dir(self.config, 'specs', 'design', bad)
            self.assertEqual(result['status'], 'error', bad)


class TestFeatureOfPath(unittest.TestCase):
    """パスから doc_type と feature を求めるテスト"""

    def setUp(self):
        self.config = rds.parse_config(DIR_OF_CONFIG)
        self.root = '/project'

    def test_feature_directory(self):
        result = rds.feature_of_path(
            self.config, 'specs',
            'docs/specs/forge/requirements/REQ-001_x.md', self.root,
        )
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['doc_type'], 'requirement')
        self.assertEqual(result['feature'], 'forge')

    def test_top_level_directory_has_no_feature(self):
        """** が 0 階層に当たる置き場（トップのディレクトリ）は feature なし"""
        result = rds.feature_of_path(
            self.config, 'specs',
            'docs/specs/requirements/REQ-001_x.md', self.root,
        )
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['doc_type'], 'requirement')
        self.assertIsNone(result['feature'])

    def test_sub_feature_maps_to_first_segment(self):
        result = rds.feature_of_path(
            self.config, 'specs',
            'docs/specs/forge/review-PR/design/DES-001_x.md', self.root,
        )
        self.assertEqual(result['doc_type'], 'design')
        self.assertEqual(result['feature'], 'forge')

    def test_file_in_subdirectory_of_the_entry(self):
        result = rds.feature_of_path(
            self.config, 'specs',
            'docs/specs/forge/design/sub/DES-001_x.md', self.root,
        )
        self.assertEqual(result['doc_type'], 'design')
        self.assertEqual(result['feature'], 'forge')

    def test_absolute_path_inside_project(self):
        result = rds.feature_of_path(
            self.config, 'specs',
            '/project/docs/specs/forge/design/DES-001_x.md', self.root,
        )
        self.assertEqual(result['feature'], 'forge')
        self.assertEqual(result['path'], 'docs/specs/forge/design/DES-001_x.md')

    def test_directory_path_with_trailing_slash(self):
        result = rds.feature_of_path(
            self.config, 'specs', 'docs/specs/forge/design/', self.root,
        )
        self.assertEqual(result['doc_type'], 'design')
        self.assertEqual(result['feature'], 'forge')

    def test_single_star_key(self):
        config = rds.parse_config(SINGLE_STAR_CONFIG)
        result = rds.feature_of_path(
            config, 'specs', 'docs/specs/auth/design/a.md', self.root,
        )
        self.assertEqual(result['feature'], 'auth')

    def test_key_without_wildcard_has_no_feature(self):
        config = rds.parse_config(BASIC_CONFIG)
        result = rds.feature_of_path(
            config, 'specs', 'docs/specs/design/a.md', self.root,
        )
        self.assertEqual(result['status'], 'ok')
        self.assertIsNone(result['feature'])

    def test_no_matching_entry_is_error(self):
        result = rds.feature_of_path(
            self.config, 'specs', 'docs/other/x.md', self.root,
        )
        self.assertEqual(result['status'], 'error')

    def test_path_outside_project_is_error(self):
        result = rds.feature_of_path(
            self.config, 'specs', '/elsewhere/docs/specs/forge/design/a.md',
            self.root,
        )
        self.assertEqual(result['status'], 'error')
        self.assertIn('プロジェクトルートの外', result['message'])


# ---------------------------------------------------------------------------
# キーの書き方の網羅（性質のテスト）
# ---------------------------------------------------------------------------

# (キー, feature なしの置き場, feature=auth の置き場)。None はエラーになるべきもの
KEY_PATTERNS = [
    ('docs/specs/design/',        'docs/specs/design/', 'docs/specs/design/'),
    ('docs/specs/*/design/',      None,                 'docs/specs/auth/design/'),
    ('docs/specs/**/design/',     'docs/specs/design/', 'docs/specs/auth/design/'),
    ('docs/**/design/',           'docs/design/',       'docs/auth/design/'),
    ('**/design/',                'design/',            'auth/design/'),
    ('docs/specs/design/**/',     'docs/specs/design/', 'docs/specs/design/auth/'),
    ('docs/*/specs/design/',      None,                 'docs/auth/specs/design/'),
    ('docs/specs/**/*/design/',   None,                 None),
    ('docs/**/specs/**/design/',  'docs/specs/design/', None),
    ('docs/specs/feat-*/design/', None,                 None),
]


def _config_for_key(key):
    return rds.parse_config(
        '# doc_structure_version: 3.0\n'
        'specs:\n'
        '  root_dirs:\n'
        f'    - {key}\n'
        '  doc_types_map:\n'
        f'    {key}: design\n'
    )


class TestKeyPatternCoverage(unittest.TestCase):
    """キーの書き方ごとに、置き場と feature が一貫すること"""

    def test_dir_of_expected_for_every_pattern(self):
        for key, expected_none, expected_auth in KEY_PATTERNS:
            config = _config_for_key(key)
            without = rds.resolve_doc_type_dir(config, 'specs', 'design')
            with_auth = rds.resolve_doc_type_dir(config, 'specs', 'design', 'auth')
            if expected_none is None:
                self.assertEqual(without['status'], 'error', key)
            else:
                self.assertEqual(without['dir'], expected_none, key)
            if expected_auth is None:
                self.assertEqual(with_auth['status'], 'error', key)
            else:
                self.assertEqual(with_auth['dir'], expected_auth, key)

    def test_resolved_dir_is_always_covered_by_the_key(self):
        """求めた置き場は、必ずキー自身に含まれる（索引の対象外の場所を返さない）"""
        for key, _, _ in KEY_PATTERNS:
            config = _config_for_key(key)
            parts = rds._key_parts(key)
            for feature in (None, 'auth'):
                result = rds.resolve_doc_type_dir(config, 'specs', 'design', feature)
                if result['status'] != 'ok':
                    continue
                dir_parts = [p for p in result['dir'].split('/') if p]
                self.assertTrue(rds._segments_match(parts, dir_parts), (key, feature))

    def test_round_trip_feature_of_dir_of(self):
        """dir-of で求めた置き場のファイルから、同じ feature が求まる"""
        for key, expected_none, expected_auth in KEY_PATTERNS:
            config = _config_for_key(key)
            if expected_none is not None:
                located = rds.feature_of_path(
                    config, 'specs', expected_none + 'x.md', '/p')
                self.assertEqual(located['status'], 'ok', key)
                self.assertIsNone(located['feature'], key)
            if expected_auth is not None and 'auth' in expected_auth:
                located = rds.feature_of_path(
                    config, 'specs', expected_auth + 'x.md', '/p')
                feature_applied = rds.resolve_doc_type_dir(
                    config, 'specs', 'design', 'auth')['feature_applied']
                self.assertEqual(located['status'], 'ok', key)
                if feature_applied:
                    self.assertEqual(located['feature'], 'auth', key)

    def test_feature_of_never_silently_returns_none_for_unsupported_keys(self):
        """求められない書き方は、「feature なし」にせずエラーにする"""
        multi = _config_for_key('docs/**/specs/**/design/')
        result = rds.feature_of_path(multi, 'specs', 'docs/a/specs/b/design/x.md', '/p')
        self.assertEqual(result['status'], 'error')
        partial = _config_for_key('docs/specs/feat-*/design/')
        result = rds.feature_of_path(partial, 'specs', 'docs/specs/feat-a/design/x.md', '/p')
        self.assertEqual(result['status'], 'error')

    def test_multiple_doublestar_with_no_capture_is_no_feature(self):
        multi = _config_for_key('docs/**/specs/**/design/')
        result = rds.feature_of_path(multi, 'specs', 'docs/specs/design/x.md', '/p')
        self.assertEqual(result['status'], 'ok')
        self.assertIsNone(result['feature'])

    def test_multiple_entries_for_one_doc_type_is_error(self):
        config = rds.parse_config(
            '# doc_structure_version: 3.0\n'
            'specs:\n'
            '  root_dirs:\n'
            '    - docs/specs/**/design/\n'
            '    - docs/legacy/design/\n'
            '  doc_types_map:\n'
            '    docs/specs/**/design/: design\n'
            '    docs/legacy/design/: design\n'
        )
        result = rds.resolve_doc_type_dir(config, 'specs', 'design')
        self.assertEqual(result['status'], 'error')
        self.assertIn('複数のエントリ', result['message'])


class TestDecideFeature(unittest.TestCase):
    """feature の決定（引数 / パス / 既存ファイルの有無 / 尋ねる）"""

    def _run(self, files, **kwargs):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, files)
            config = rds.parse_config(DIR_OF_CONFIG)
            return rds.decide_feature(config, 'specs', 'design', tmpdir, **kwargs)

    def test_argument_is_used_as_is(self):
        result = self._run([], feature='forge')
        self.assertEqual(result['decision'], 'argument')
        self.assertEqual(result['feature'], 'forge')
        self.assertEqual(result['dir'], 'docs/specs/forge/design/')

    def test_argument_matching_source_path_is_used(self):
        result = self._run(
            [], feature='auth',
            source_path='docs/specs/auth/requirements/REQ-001_x.md')
        self.assertEqual(result['decision'], 'argument')
        self.assertEqual(result['feature'], 'auth')

    def test_argument_conflicting_with_source_path_asks(self):
        result = self._run(
            [], feature='forge',
            source_path='docs/specs/auth/requirements/REQ-001_x.md')
        self.assertEqual(result['decision'], 'ask')
        self.assertIn('食い違う', result['reason'])

    def test_argument_with_top_level_source_path_asks(self):
        """要件定義書がトップのディレクトリ（feature なし）なのに、feature が渡された"""
        result = self._run(
            [], feature='forge',
            source_path='docs/specs/requirements/REQ-001_x.md')
        self.assertEqual(result['decision'], 'ask')
        self.assertIn('食い違う', result['reason'])

    def test_sub_feature_argument_under_path_feature_is_consistent(self):
        result = self._run(
            [], feature='forge/review-PR',
            source_path='docs/specs/forge/review-PR/requirements/REQ-001_x.md')
        self.assertEqual(result['decision'], 'argument')

    def test_argument_with_unresolvable_source_path_is_used(self):
        result = self._run([], feature='forge', source_path='docs/other/x.md')
        self.assertEqual(result['decision'], 'argument')

    def test_argument_unused_by_key_is_not_a_conflict(self):
        """キーに feature を置く場所が無いとき、feature は使われないため食い違いにしない"""
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, [])
            config = rds.parse_config(BASIC_CONFIG)
            result = rds.decide_feature(
                config, 'specs', 'design', tmpdir, feature='forge',
                source_path='docs/specs/design/DES-001_x.md')
            self.assertEqual(result['decision'], 'argument')

    def test_source_path_in_feature_directory(self):
        result = self._run(
            [], source_path='docs/specs/auth/requirements/REQ-001_x.md')
        self.assertEqual(result['decision'], 'path')
        self.assertEqual(result['feature'], 'auth')
        self.assertEqual(result['dir'], 'docs/specs/auth/design/')

    def test_source_path_in_top_level_directory_means_no_feature(self):
        result = self._run(
            ['docs/specs/design/DES-001_x.md'],
            source_path='docs/specs/requirements/REQ-001_x.md')
        self.assertEqual(result['decision'], 'path')
        self.assertIsNone(result['feature'])
        self.assertEqual(result['dir'], 'docs/specs/design/')

    def test_unresolvable_source_path_asks(self):
        result = self._run([], source_path='docs/other/x.md')
        self.assertEqual(result['decision'], 'ask')
        self.assertIn('一致しません', result['reason'])

    def test_no_existing_files_is_complete_new(self):
        result = self._run([])
        self.assertEqual(result['decision'], 'no-existing')
        self.assertIsNone(result['feature'])
        self.assertEqual(result['dir'], 'docs/specs/design/')

    def test_existing_files_ask_with_features(self):
        result = self._run([
            'docs/specs/auth/design/a.md',
            'docs/specs/login/design/b.md',
        ])
        self.assertEqual(result['decision'], 'ask')
        self.assertEqual(result['existing_count'], 2)
        self.assertEqual(result['features'], ['auth', 'login'])

    def test_no_existing_but_key_requires_feature_asks(self):
        """`*` のキーは feature が必須。既存ファイルが無くても、feature なしは決められない"""
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, [])
            config = rds.parse_config(SINGLE_STAR_CONFIG)
            result = rds.decide_feature(config, 'specs', 'design', tmpdir)
            self.assertEqual(result['decision'], 'ask')
            self.assertIn('feature が必要', result['reason'])

    def test_unknown_doc_type_is_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = rds.parse_config(DIR_OF_CONFIG)
            result = rds.decide_feature(config, 'specs', 'api', tmpdir)
            self.assertEqual(result['status'], 'error')


class TestFindDoc(unittest.TestCase):
    """パス・ファイル名・ID から文書を探すテスト"""

    FILES = [
        'docs/specs/forge/requirements/REQ-003_skill_script.md',
        'docs/specs/secret-linter/requirements/REQ-032_secret-linter.md',
        'docs/specs/requirements/REQ-001_base.md',
    ]

    def _find(self, name):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, self.FILES)
            config = rds.parse_config(DIR_OF_CONFIG)
            return rds.find_doc(config, 'specs', 'requirement', name, tmpdir)

    def test_by_id(self):
        result = self._find('REQ-032')
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['matches'], [self.FILES[1]])

    def test_id_does_not_match_a_longer_number(self):
        """REQ-03 は REQ-032 にも REQ-003 にも当たらない"""
        self.assertEqual(self._find('REQ-03')['count'], 0)

    def test_by_file_name(self):
        for name in ('REQ-032_secret-linter.md', 'REQ-032_secret-linter'):
            self.assertEqual(self._find(name)['matches'], [self.FILES[1]], name)

    def test_by_full_path(self):
        result = self._find(self.FILES[2])
        self.assertEqual(result['matches'], [self.FILES[2]])

    def test_by_path_suffix(self):
        result = self._find('secret-linter/requirements/REQ-032_secret-linter.md')
        self.assertEqual(result['matches'], [self.FILES[1]])

    def test_not_found_is_zero_not_error(self):
        result = self._find('REQ-999')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['count'], 0)

    def test_same_id_in_two_places_returns_both(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_test_project(tmpdir, [
                'docs/specs/a/requirements/REQ-001_x.md',
                'docs/specs/b/requirements/REQ-001_y.md',
            ])
            config = rds.parse_config(DIR_OF_CONFIG)
            result = rds.find_doc(config, 'specs', 'requirement', 'REQ-001', tmpdir)
            self.assertEqual(result['count'], 2)

    def test_unknown_doc_type_is_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = rds.parse_config(DIR_OF_CONFIG)
            result = rds.find_doc(config, 'specs', 'api', 'x', tmpdir)
            self.assertEqual(result['status'], 'error')


class TestCliDirOfAndFeatureOf(unittest.TestCase):
    """--dir-of / --feature-of の CLI テスト（終了コードと JSON）"""

    SCRIPT = os.path.join(
        os.path.dirname(__file__), '..', '..', '..', 'plugins',
        'forge', 'scripts', 'doc_structure', 'resolve_doc_structure.py'
    )

    def _run(self, tmpdir, *args):
        import subprocess
        return subprocess.run(
            [sys.executable, self.SCRIPT, *args, '--project-root', tmpdir],
            capture_output=True, text=True,
        )

    def _project(self, tmpdir):
        with open(os.path.join(tmpdir, '.doc_structure.yaml'), 'w') as f:
            f.write(DIR_OF_CONFIG)
        os.makedirs(os.path.join(tmpdir, '.git'))

    def test_dir_of_with_feature(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._project(tmpdir)
            proc = self._run(tmpdir, '--dir-of', 'design', '--feature', 'forge')
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(json.loads(proc.stdout)['dir'], 'docs/specs/forge/design/')

    def test_dir_of_without_feature(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._project(tmpdir)
            proc = self._run(tmpdir, '--dir-of', 'requirement')
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(json.loads(proc.stdout)['dir'], 'docs/specs/requirements/')

    def test_dir_of_unknown_doc_type_exits_1(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._project(tmpdir)
            proc = self._run(tmpdir, '--dir-of', 'api')
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(json.loads(proc.stdout)['status'], 'error')

    def test_feature_of(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._project(tmpdir)
            proc = self._run(
                tmpdir, '--feature-of', 'docs/specs/forge/requirements/REQ-001_x.md'
            )
            self.assertEqual(proc.returncode, 0)
            data = json.loads(proc.stdout)
            self.assertEqual(data['feature'], 'forge')
            self.assertEqual(data['doc_type'], 'requirement')

    def test_feature_of_top_level_has_null_feature(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._project(tmpdir)
            proc = self._run(
                tmpdir, '--feature-of', 'docs/specs/requirements/REQ-001_x.md'
            )
            self.assertEqual(proc.returncode, 0)
            self.assertIsNone(json.loads(proc.stdout)['feature'])

    def test_feature_of_no_match_exits_1(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._project(tmpdir)
            proc = self._run(tmpdir, '--feature-of', 'docs/other/x.md')
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(json.loads(proc.stdout)['status'], 'error')

    def test_decide_feature_no_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._project(tmpdir)
            proc = self._run(tmpdir, '--decide-feature-for', 'design')
            self.assertEqual(proc.returncode, 0)
            data = json.loads(proc.stdout)
            self.assertEqual(data['decision'], 'no-existing')
            self.assertEqual(data['dir'], 'docs/specs/design/')

    def test_decide_feature_from_source_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._project(tmpdir)
            proc = self._run(
                tmpdir, '--decide-feature-for', 'design',
                '--source-path', 'docs/specs/forge/requirements/REQ-001_x.md')
            data = json.loads(proc.stdout)
            self.assertEqual(data['decision'], 'path')
            self.assertEqual(data['feature'], 'forge')

    def test_decide_feature_unknown_doc_type_exits_1(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._project(tmpdir)
            proc = self._run(tmpdir, '--decide-feature-for', 'api')
            self.assertEqual(proc.returncode, 1)

    def test_find_in(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._project(tmpdir)
            create_test_project(tmpdir, ['docs/specs/forge/requirements/REQ-001_x.md'])
            proc = self._run(tmpdir, '--find-in', 'requirement', '--name', 'REQ-001')
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(json.loads(proc.stdout)['count'], 1)

    def test_find_in_requires_name_exits_2(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._project(tmpdir)
            proc = self._run(tmpdir, '--find-in', 'requirement')
            self.assertEqual(proc.returncode, 2)

    def test_feature_option_without_dir_of_exits_2(self):
        """--feature は --dir-of と併用する。argparse の引数エラーは終了コード 2"""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._project(tmpdir)
            proc = self._run(tmpdir, '--type', 'specs', '--feature', 'forge')
            self.assertEqual(proc.returncode, 2)


MATCH_PATH_CONFIG = """\
# doc_structure_version: 3.0

rules:
  root_dirs:
    - docs/rules/
  doc_types_map:
    docs/rules/: rule
  patterns:
    target_glob: "**/*.md"
    exclude: []

specs:
  root_dirs:
    - "docs/specs/**/adr/"
    - "docs/specs/**/design/"
    - "docs/specs/**/plan/"
    - "docs/specs/**/requirements/"
  doc_types_map:
    "docs/specs/**/adr/": adr
    "docs/specs/**/design/": design
    "docs/specs/**/plan/": plan
    "docs/specs/**/requirements/": requirement
  patterns:
    target_glob: "**/*.md"
    exclude: [plan]
"""


class TestMatchPathCli(unittest.TestCase):
    """--match-path（DES-084 §6.8）。"""

    SCRIPT = os.path.join(
        os.path.dirname(__file__), '..', '..', '..', 'plugins',
        'forge', 'scripts', 'doc_structure', 'resolve_doc_structure.py'
    )

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        with open(os.path.join(self.root, '.doc_structure.yaml'), 'w') as f:
            f.write(MATCH_PATH_CONFIG)
        create_test_project(self.root, [
            'docs/specs/feat/adr/ADR-001.md',
            'docs/specs/feat/design/DES-001.md',
            'docs/specs/feat/plan/plan.md',
            'docs/specs/feat/requirements/REQ-001.md',
            'docs/specs/feat/notes/memo.md',
            'docs/rules/rule.md',
            'src/main.py',
        ])

    def _run(self, *args, root=None):
        import subprocess
        proc = subprocess.run(
            [sys.executable, self.SCRIPT, '--project-root', root or self.root, *args],
            capture_output=True, text=True,
        )
        return proc.returncode, proc.stdout

    def _match(self, path, *extra):
        code, out = self._run('--match-path', path, *extra)
        self.assertEqual(code, 0, out)
        return json.loads(out)

    def test_each_declared_doc_type(self):
        cases = {
            'docs/specs/feat/adr/ADR-001.md': 'adr',
            'docs/specs/feat/design/DES-001.md': 'design',
            'docs/specs/feat/plan/plan.md': 'plan',
            'docs/specs/feat/requirements/REQ-001.md': 'requirement',
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(self._match(path)['doc_type'], expected)

    def test_plan_is_returned_despite_exclude_plan(self):
        """exclude: [plan] でも計画書の種別が決まる（exclude は適用しない）。"""
        data = self._match('docs/specs/feat/plan/plan.md')
        self.assertEqual(data['doc_type'], 'plan')
        # 同じ設定でファイル収集からは plan が除外されている（exclude 自体は有効）
        config, _ = rds.load_doc_structure(self.root)
        self.assertEqual(rds.resolve_files_by_doc_type(config, 'specs', 'plan', self.root), [])

    def test_adr_is_returned_as_is(self):
        """adr を design へ読み替えない。"""
        self.assertEqual(self._match('docs/specs/feat/adr/ADR-001.md')['doc_type'], 'adr')

    def test_output_shape(self):
        data = self._match('docs/specs/feat/design/DES-001.md')
        self.assertEqual(data, {
            'status': 'ok',
            'category': 'specs',
            'path': 'docs/specs/feat/design/DES-001.md',
            'doc_type': 'design',
        })

    def test_absolute_path_is_made_relative(self):
        absolute = os.path.join(self.root, 'docs/specs/feat/design/DES-001.md')
        data = self._match(absolute)
        self.assertEqual(data['path'], 'docs/specs/feat/design/DES-001.md')
        self.assertEqual(data['doc_type'], 'design')

    def test_undeclared_path_is_null(self):
        for path in ('docs/specs/feat/notes/memo.md', 'src/main.py', 'docs/rules/rule.md'):
            with self.subTest(path=path):
                data = self._match(path)
                self.assertEqual(data['status'], 'ok')
                self.assertIsNone(data['doc_type'])

    def test_path_outside_project_root_is_null(self):
        with tempfile.TemporaryDirectory() as outside:
            create_test_project(outside, ['docs/specs/feat/design/DES-001.md'])
            data = self._match(os.path.join(outside, 'docs/specs/feat/design/DES-001.md'))
        self.assertIsNone(data['doc_type'])

    def test_relative_path_escaping_root_is_null(self):
        data = self._match('../docs/specs/feat/design/DES-001.md')
        self.assertIsNone(data['doc_type'])

    def test_category_rules(self):
        data = self._match('docs/rules/rule.md', '--category', 'rules')
        self.assertEqual(data['category'], 'rules')
        self.assertEqual(data['doc_type'], 'rule')

    def test_default_category_is_specs(self):
        data = self._match('docs/rules/rule.md')
        self.assertEqual(data['category'], 'specs')
        self.assertIsNone(data['doc_type'])

    def test_missing_doc_structure_is_error(self):
        with tempfile.TemporaryDirectory() as empty:
            code, out = self._run('--match-path', 'a.md', root=empty)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)['status'], 'error')

    def test_invalid_doc_structure_is_error(self):
        with tempfile.TemporaryDirectory() as bad:
            with open(os.path.join(bad, '.doc_structure.yaml'), 'w') as f:
                f.write(V1_CONFIG)
            code, out = self._run('--match-path', 'a.md', root=bad)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)['status'], 'error')

    def test_exclusive_with_existing_options(self):
        for other in (['--type', 'all'], ['--features'], ['--doc-type', 'design'], ['--version']):
            with self.subTest(other=other):
                code, _ = self._run('--match-path', 'a.md', *other)
                self.assertEqual(code, 2)

    def test_existing_options_still_work(self):
        code, out = self._run('--doc-type', 'design')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['files'], ['docs/specs/feat/design/DES-001.md'])


class TestToProjectRelativePath(unittest.TestCase):
    def test_relative_inside(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(rds.to_project_relative_path('a/b.md', root), 'a/b.md')

    def test_absolute_inside(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(
                rds.to_project_relative_path(os.path.join(root, 'a', 'b.md'), root), 'a/b.md')

    def test_outside_is_none(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(rds.to_project_relative_path('../x.md', root))
            self.assertIsNone(rds.to_project_relative_path('/etc/hosts', root))


if __name__ == '__main__':
    unittest.main()
