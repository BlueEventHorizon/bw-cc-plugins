#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""toc_utils.py のユニットテスト。

bash テスト test_should_exclude.sh, test_edge_cases.sh (yaml_escape) から移行。
"""

import os
import sys
import tempfile
import shutil
import unicodedata
import unittest
from pathlib import Path

# テスト対象モジュールの import
SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'plugins', 'doc-advisor', 'scripts'
)
sys.path.insert(0, os.path.abspath(SCRIPTS_DIR))

import toc_utils


# ---------------------------------------------------------------------------
# テスト用 .doc_structure.yaml
# ---------------------------------------------------------------------------

BASIC_DOC_STRUCTURE = """\
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

CUSTOM_DOC_STRUCTURE = """\
# doc_structure_version: 3.0

rules:
  root_dirs:
    - docs/rules/
  doc_types_map:
    docs/rules/: rule
  patterns:
    target_glob: "**/*.md"
    exclude:
      - draft

specs:
  root_dirs:
    - docs/specs/design/
    - docs/specs/plan/
  doc_types_map:
    docs/specs/design/: design
    docs/specs/plan/: plan
  patterns:
    target_glob: "**/*.md"
    exclude: []
"""


# ===========================================================================
# should_exclude テスト（test_should_exclude.sh から移行）
# ===========================================================================

class TestShouldExclude(unittest.TestCase):
    """should_exclude() のディレクトリマッチングテスト。"""

    def test_plan_directory_excluded(self):
        """plan ディレクトリは除外される"""
        root = Path('/project/specs')
        fp = Path('/project/specs/plan/roadmap.md')
        self.assertTrue(toc_utils.should_exclude(fp, root, ['plan']))

    def test_nested_plan_directory_excluded(self):
        """ネストされた plan ディレクトリは除外される"""
        root = Path('/project/specs')
        fp = Path('/project/specs/main/plan/item.md')
        self.assertTrue(toc_utils.should_exclude(fp, root, ['plan']))

    def test_planning_md_not_excluded_by_plan(self):
        """planning.md は 'plan' パターンで除外されない"""
        root = Path('/project/specs')
        fp = Path('/project/specs/main/requirements/planning.md')
        self.assertFalse(toc_utils.should_exclude(fp, root, ['plan']))

    def test_deployment_plan_md_not_excluded(self):
        """deployment_plan.md は 'plan' パターンで除外されない"""
        root = Path('/project/specs')
        fp = Path('/project/specs/main/design/deployment_plan.md')
        self.assertFalse(toc_utils.should_exclude(fp, root, ['plan']))

    def test_project_plan_v2_not_excluded(self):
        """project_plan_v2.md は 'plan' パターンで除外されない"""
        root = Path('/project/specs')
        fp = Path('/project/specs/main/requirements/project_plan_v2.md')
        self.assertFalse(toc_utils.should_exclude(fp, root, ['plan']))

    def test_slash_pattern_archive(self):
        """パスに /archive/ を含む場合は除外（先頭末尾の / は除去される）"""
        root = Path('/project/specs')
        fp = Path('/project/specs/archive/old/doc.md')
        self.assertTrue(toc_utils.should_exclude(fp, root, ['/archive/']))

    def test_archived_md_not_excluded_by_archive_slash(self):
        """archived.md は '/archive/' パターンで除外されない"""
        root = Path('/project/specs')
        fp = Path('/project/specs/main/requirements/archived.md')
        self.assertFalse(toc_utils.should_exclude(fp, root, ['/archive/']))

    def test_multiple_patterns_plan(self):
        """複数パターン: plan ディレクトリのファイルが除外される"""
        root = Path('/project/specs')
        fp = Path('/project/specs/plan/item.md')
        self.assertTrue(toc_utils.should_exclude(fp, root, ['plan', 'draft']))

    def test_multiple_patterns_draft(self):
        """複数パターン: draft ディレクトリのファイルが除外される"""
        root = Path('/project/specs')
        fp = Path('/project/specs/draft/item.md')
        self.assertTrue(toc_utils.should_exclude(fp, root, ['plan', 'draft']))

    def test_multiple_patterns_normal_file(self):
        """複数パターン: 通常ファイルは除外されない"""
        root = Path('/project/specs')
        fp = Path('/project/specs/main/requirements/auth.md')
        self.assertFalse(toc_utils.should_exclude(fp, root, ['plan', 'draft']))

    def test_empty_patterns(self):
        """空パターンは何も除外しない"""
        root = Path('/project/specs')
        fp = Path('/project/specs/main/requirements/auth.md')
        self.assertFalse(toc_utils.should_exclude(fp, root, []))

    def test_deeply_nested_plan(self):
        """深くネストされた plan ディレクトリ"""
        root = Path('/project/specs')
        fp = Path('/project/specs/a/b/c/plan/d/file.md')
        self.assertTrue(toc_utils.should_exclude(fp, root, ['plan']))

    def test_deeply_nested_planning_not_excluded(self):
        """深くネストされた planning ディレクトリは 'plan' にマッチしない"""
        root = Path('/project/specs')
        fp = Path('/project/specs/a/b/c/planning/d/file.md')
        self.assertFalse(toc_utils.should_exclude(fp, root, ['plan']))


# ===========================================================================
# normalize_path テスト
# ===========================================================================

class TestNormalizePath(unittest.TestCase):
    """normalize_path() の NFC 正規化テスト。"""

    def test_ascii_unchanged(self):
        self.assertEqual(toc_utils.normalize_path('docs/rules/'), 'docs/rules/')

    def test_nfc_normalization(self):
        """NFD 形式が NFC に正規化される"""
        nfd = unicodedata.normalize('NFD', 'プラグイン')
        result = toc_utils.normalize_path(nfd)
        expected = unicodedata.normalize('NFC', 'プラグイン')
        self.assertEqual(result, expected)

    def test_already_nfc(self):
        """NFC 形式はそのまま"""
        nfc = unicodedata.normalize('NFC', 'テスト')
        result = toc_utils.normalize_path(nfc)
        self.assertEqual(result, nfc)

    def test_path_object(self):
        """Path オブジェクトも文字列に変換して処理"""
        result = toc_utils.normalize_path(Path('docs/rules'))
        self.assertEqual(result, 'docs/rules')


# ===========================================================================
# load_config テスト
# ===========================================================================

class TestLoadConfig(unittest.TestCase):
    """load_config() のデフォルトマージテスト。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.original_env = {}
        for key in ('CLAUDE_PROJECT_DIR', 'CLAUDE_PLUGIN_ROOT'):
            self.original_env[key] = os.environ.get(key)
        os.environ['CLAUDE_PROJECT_DIR'] = self.tmpdir

        # .doc_structure.yaml 作成
        with open(os.path.join(self.tmpdir, '.doc_structure.yaml'), 'w') as f:
            f.write(BASIC_DOC_STRUCTURE)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        for key, val in self.original_env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val

    def test_load_config_returns_dict(self):
        """load_config() は辞書を返す"""
        config = toc_utils.load_config()
        self.assertIsInstance(config, dict)

    def test_load_config_has_rules_and_specs(self):
        """rules と specs セクションが含まれる"""
        config = toc_utils.load_config()
        self.assertIn('rules', config)
        self.assertIn('specs', config)

    def test_load_config_category_filter(self):
        """category 指定で該当セクションのみ返す"""
        config = toc_utils.load_config(category='rules')
        self.assertIn('root_dirs', config)
        self.assertNotIn('rules', config)  # トップレベルキーではなくセクション内容

    def test_load_config_defaults_merged(self):
        """デフォルト値（toc_file 等）がマージされる"""
        config = toc_utils.load_config(category='rules')
        self.assertIn('toc_file', config)
        self.assertIn('checksums_file', config)

    def test_load_config_user_override(self):
        """ユーザー定義の root_dirs がデフォルトを上書き"""
        config = toc_utils.load_config(category='rules')
        self.assertEqual(config['root_dirs'], ['rules/'])

    def test_load_config_no_file(self):
        """.doc_structure.yaml がない場合はデフォルトを返す"""
        os.remove(os.path.join(self.tmpdir, '.doc_structure.yaml'))
        config = toc_utils.load_config(category='rules')
        self.assertIn('root_dirs', config)

    def test_load_config_custom_exclude(self):
        """カスタム .doc_structure.yaml の exclude が反映される"""
        with open(os.path.join(self.tmpdir, '.doc_structure.yaml'), 'w') as f:
            f.write(CUSTOM_DOC_STRUCTURE)
        config = toc_utils.load_config(category='rules')
        self.assertIn('draft', config.get('patterns', {}).get('exclude', []))


# ===========================================================================
# get_project_root テスト
# ===========================================================================

class TestGetProjectRoot(unittest.TestCase):
    """get_project_root() のテスト。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.original_env = os.environ.get('CLAUDE_PROJECT_DIR')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        if self.original_env is None:
            os.environ.pop('CLAUDE_PROJECT_DIR', None)
        else:
            os.environ['CLAUDE_PROJECT_DIR'] = self.original_env

    def test_env_var(self):
        """CLAUDE_PROJECT_DIR set → returns that path"""
        os.environ['CLAUDE_PROJECT_DIR'] = self.tmpdir
        result = toc_utils.get_project_root()
        self.assertEqual(result, Path(self.tmpdir))

    def test_invalid_env_falls_back_to_cwd(self):
        """CLAUDE_PROJECT_DIR invalid → falls back to cwd"""
        os.environ['CLAUDE_PROJECT_DIR'] = '/nonexistent/path'
        original_cwd = os.getcwd()
        try:
            os.chdir(self.tmpdir)
            result = toc_utils.get_project_root()
            self.assertEqual(result, Path(self.tmpdir).resolve())
        finally:
            os.chdir(original_cwd)

    def test_no_env_returns_cwd(self):
        """No CLAUDE_PROJECT_DIR → returns cwd"""
        os.environ.pop('CLAUDE_PROJECT_DIR', None)
        original_cwd = os.getcwd()
        try:
            os.chdir(self.tmpdir)
            result = toc_utils.get_project_root()
            self.assertEqual(result, Path(self.tmpdir).resolve())
        finally:
            os.chdir(original_cwd)


# ===========================================================================
# get_system_exclude_patterns テスト
# ===========================================================================

class TestGetSystemExcludePatterns(unittest.TestCase):
    """get_system_exclude_patterns() のテスト。"""

    def test_rules_patterns(self):
        patterns = toc_utils.get_system_exclude_patterns('rules')
        self.assertIn('.toc_work', patterns)
        self.assertIn('rules_toc.yaml', patterns)
        self.assertIn('.index_checksums.yaml', patterns)

    def test_specs_patterns(self):
        patterns = toc_utils.get_system_exclude_patterns('specs')
        self.assertIn('.toc_work', patterns)
        self.assertIn('specs_toc.yaml', patterns)

    def test_unknown_category(self):
        patterns = toc_utils.get_system_exclude_patterns('unknown')
        self.assertEqual(patterns, [])

    def test_returns_copy(self):
        """元のリストが変更されないこと"""
        p1 = toc_utils.get_system_exclude_patterns('rules')
        p1.append('extra')
        p2 = toc_utils.get_system_exclude_patterns('rules')
        self.assertNotIn('extra', p2)


# ===========================================================================
# expand_doc_types_map テスト
# ===========================================================================

class TestExpandDocTypesMap(unittest.TestCase):
    """expand_doc_types_map() unit tests."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_map(self):
        """Empty map returns empty dict."""
        result = toc_utils.expand_doc_types_map({}, Path(self.tmpdir))
        self.assertEqual(result, {})

    def test_no_glob_key_passthrough(self):
        """Non-glob key is passed through unchanged."""
        doc_map = {'docs/rules/': 'rule'}
        result = toc_utils.expand_doc_types_map(doc_map, Path(self.tmpdir))
        self.assertEqual(result, {'docs/rules/': 'rule'})

    def test_glob_match_expands(self):
        """Glob key expands to matching directories with correct doc_type."""
        # Create dirs: specs/app1/design/, specs/app2/design/
        for name in ('app1', 'app2'):
            (Path(self.tmpdir) / 'specs' / name / 'design').mkdir(parents=True)
        doc_map = {'specs/*/design/': 'design'}
        result = toc_utils.expand_doc_types_map(doc_map, Path(self.tmpdir))
        self.assertIn('specs/app1/design/', result)
        self.assertIn('specs/app2/design/', result)
        self.assertEqual(result['specs/app1/design/'], 'design')
        self.assertEqual(result['specs/app2/design/'], 'design')

    def test_glob_no_match_excluded(self):
        """Glob key with no matches produces no entries."""
        doc_map = {'nonexistent/*/foo/': 'bar'}
        result = toc_utils.expand_doc_types_map(doc_map, Path(self.tmpdir))
        self.assertEqual(result, {})

    def test_mixed_glob_and_non_glob(self):
        """Mix of glob and non-glob keys are both handled correctly."""
        (Path(self.tmpdir) / 'specs' / 'core' / 'plan').mkdir(parents=True)
        doc_map = {
            'docs/rules/': 'rule',
            'specs/*/plan/': 'plan',
        }
        result = toc_utils.expand_doc_types_map(doc_map, Path(self.tmpdir))
        self.assertEqual(result['docs/rules/'], 'rule')
        self.assertIn('specs/core/plan/', result)
        self.assertEqual(result['specs/core/plan/'], 'plan')

    def test_multiple_glob_matches_same_doc_type(self):
        """Multiple glob matches all receive the same doc_type."""
        for name in ('alpha', 'beta', 'gamma'):
            (Path(self.tmpdir) / 'modules' / name).mkdir(parents=True)
        doc_map = {'modules/*/': 'module'}
        result = toc_utils.expand_doc_types_map(doc_map, Path(self.tmpdir))
        self.assertEqual(len(result), 3)
        for key, doc_type in result.items():
            self.assertEqual(doc_type, 'module')


if __name__ == '__main__':
    unittest.main()
