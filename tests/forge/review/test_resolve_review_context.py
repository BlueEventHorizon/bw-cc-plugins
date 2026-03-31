#!/usr/bin/env python3
"""
resolve_review_context.py のテスト

.doc_structure.yaml形式の .doc_structure.yaml を使用した種別判定、
Feature 検出、exclude 判定をテストする。
標準ライブラリのみ使用。

実行:
  python3 -m unittest tests.forge.review.test_resolve_review_context -v
"""

import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

# テスト対象モジュールへのパスを追加
sys.path.insert(0, str(Path(__file__).resolve().parents[3]
                       / 'plugins' / 'forge' / 'skills' / 'review' / 'scripts'))

from resolve_review_context import (
    parse_doc_structure,
    _is_excluded,
    _get_all_excludes,
    _doc_type_to_review_type,
    detect_type_from_doc_structure,
    detect_type_from_path,
    detect_type_from_dir,
    detect_features_from_doc_structure,
    get_rules_paths,
    get_specs_paths_by_type,
    _detect_generic_type,
    find_feature_subdirs,
    find_target_files,
)


# ---------------------------------------------------------------------------
# テスト用 .doc_structure.yamlテンプレート
# ---------------------------------------------------------------------------

CONFIG_WITH_EXCLUDE = """\
# doc_structure_version: 3.0

rules:
  root_dirs:
    - rules/
  doc_types_map:
    rules/: rule
  checksums_file: .claude/doc-advisor/indexes/rules/.index_checksums.yaml
  patterns:
    target_glob: "**/*.md"
    exclude: []
  output:
    header_comment: "Development documentation search index for query-rules skill"
    metadata_name: "Development Documentation Search Index"

specs:
  root_dirs:
    - "specs/*/requirements/"
    - "specs/*/design/"
  doc_types_map:
    "specs/*/requirements/": requirement
    "specs/*/design/": design
  checksums_file: .claude/doc-advisor/indexes/specs/.index_checksums.yaml
  patterns:
    target_glob: "**/*.md"
    exclude:
      - archived
      - _template
  output:
    header_comment: "Project specification document search index for query-specs skill"
    metadata_name: "Project Specification Document Search Index"

common:
  parallel:
    max_workers: 5
    fallback_to_serial: true
"""

CONFIG_NO_EXCLUDE = """\
# doc_structure_version: 3.0

rules:
  root_dirs:
    - rules/
  doc_types_map:
    rules/: rule
  checksums_file: .claude/doc-advisor/indexes/rules/.index_checksums.yaml
  patterns:
    target_glob: "**/*.md"
    exclude: []
  output:
    header_comment: "Development documentation search index for query-rules skill"
    metadata_name: "Development Documentation Search Index"

specs:
  root_dirs:
    - "specs/*/requirements/"
    - specs/design/
  doc_types_map:
    "specs/*/requirements/": requirement
    specs/design/: design
  checksums_file: .claude/doc-advisor/indexes/specs/.index_checksums.yaml
  patterns:
    target_glob: "**/*.md"
    exclude: []
  output:
    header_comment: "Project specification document search index for query-specs skill"
    metadata_name: "Project Specification Document Search Index"

common:
  parallel:
    max_workers: 5
    fallback_to_serial: true
"""

CONFIG_FLAT = """\
# doc_structure_version: 3.0

rules:
  root_dirs:
    - rules/
  doc_types_map:
    rules/: rule
  checksums_file: .claude/doc-advisor/indexes/rules/.index_checksums.yaml
  patterns:
    target_glob: "**/*.md"
    exclude: []
  output:
    header_comment: "Development documentation search index for query-rules skill"
    metadata_name: "Development Documentation Search Index"

specs:
  root_dirs:
    - specs/requirements/
    - specs/design/
    - specs/plan/
  doc_types_map:
    specs/requirements/: requirement
    specs/design/: design
    specs/plan/: plan
  checksums_file: .claude/doc-advisor/indexes/specs/.index_checksums.yaml
  patterns:
    target_glob: "**/*.md"
    exclude: []
  output:
    header_comment: "Project specification document search index for query-specs skill"
    metadata_name: "Project Specification Document Search Index"

common:
  parallel:
    max_workers: 5
    fallback_to_serial: true
"""

CONFIG_MIXED_EXCLUDE = """\
# doc_structure_version: 3.0

rules:
  root_dirs:
    - rules/
  doc_types_map:
    rules/: rule
  checksums_file: .claude/doc-advisor/indexes/rules/.index_checksums.yaml
  patterns:
    target_glob: "**/*.md"
    exclude:
      - deprecated
  output:
    header_comment: "Development documentation search index for query-rules skill"
    metadata_name: "Development Documentation Search Index"

specs:
  root_dirs:
    - "specs/*/requirements/"
    - "modules/*/requirements/"
    - "specs/*/design/"
  doc_types_map:
    "specs/*/requirements/": requirement
    "modules/*/requirements/": requirement
    "specs/*/design/": design
  checksums_file: .claude/doc-advisor/indexes/specs/.index_checksums.yaml
  patterns:
    target_glob: "**/*.md"
    exclude:
      - archived
      - _template
      - deprecated
  output:
    header_comment: "Project specification document search index for query-specs skill"
    metadata_name: "Project Specification Document Search Index"

common:
  parallel:
    max_workers: 5
    fallback_to_serial: true
"""


class _YamlFileTestCase(unittest.TestCase):
    """YAML ファイルを tmpdir に書き出すヘルパー付きの基底クラス"""

    def setUp(self):
        self.tmpdir = Path(os.path.realpath(tempfile.mkdtemp()))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_yaml(self, content, filename='.doc_structure.yaml'):
        path = self.tmpdir / filename
        path.write_text(content, encoding='utf-8')
        return path

    def _load_config(self, content):
        """.doc_structure.yaml形式を書き出してパースする"""
        self._write_yaml(content)
        return parse_doc_structure(self.tmpdir)


# =========================================================================
# 1. パーサーテスト（parse_doc_structure 経由）
# =========================================================================

class TestParseDocStructure(_YamlFileTestCase):
    """parse_doc_structure のテスト"""

    def test_config_with_exclude(self):
        """exclude 付き config をパースできる"""
        ds = self._load_config(CONFIG_WITH_EXCLUDE)
        self.assertIsNotNone(ds)
        self.assertIn('specs', ds)
        self.assertIn('rules', ds)

    def test_specs_root_dirs(self):
        """specs の root_dirs が正しくパースされる"""
        ds = self._load_config(CONFIG_WITH_EXCLUDE)
        root_dirs = ds['specs']['root_dirs']
        self.assertIn('specs/*/requirements/', root_dirs)
        self.assertIn('specs/*/design/', root_dirs)

    def test_specs_doc_types_map(self):
        """specs の doc_types_map が正しくパースされる"""
        ds = self._load_config(CONFIG_WITH_EXCLUDE)
        dtm = ds['specs']['doc_types_map']
        self.assertEqual(dtm['specs/*/requirements/'], 'requirement')
        self.assertEqual(dtm['specs/*/design/'], 'design')

    def test_specs_exclude(self):
        """specs の patterns.exclude が正しくパースされる"""
        ds = self._load_config(CONFIG_WITH_EXCLUDE)
        exclude = ds['specs']['patterns']['exclude']
        self.assertIn('archived', exclude)
        self.assertIn('_template', exclude)

    def test_rules_root_dirs(self):
        """rules の root_dirs が正しくパースされる"""
        ds = self._load_config(CONFIG_WITH_EXCLUDE)
        self.assertEqual(ds['rules']['root_dirs'], ['rules/'])

    def test_no_exclude(self):
        """exclude が空の config が正しくパースされる"""
        ds = self._load_config(CONFIG_NO_EXCLUDE)
        exclude = ds['specs']['patterns']['exclude']
        self.assertEqual(exclude, [])

    def test_flat_structure(self):
        """フラット構造の config をパース"""
        ds = self._load_config(CONFIG_FLAT)
        self.assertIn('specs/plan/', ds['specs']['root_dirs'])
        self.assertEqual(ds['specs']['doc_types_map']['specs/plan/'], 'plan')

    def test_nonexistent_returns_none(self):
        """存在しないディレクトリではパースが None を返す"""
        result = parse_doc_structure(self.tmpdir / 'nonexistent')
        self.assertIsNone(result)


# =========================================================================
# 2. Exclude 判定テスト
# =========================================================================

class TestIsExcluded(unittest.TestCase):
    """_is_excluded のテスト"""

    def test_excluded_component(self):
        self.assertTrue(
            _is_excluded('specs/archived/requirements/req.md',
                         ['archived', '_template']))

    def test_excluded_template(self):
        self.assertTrue(
            _is_excluded('specs/_template/requirements/req.md',
                         ['archived', '_template']))

    def test_not_excluded(self):
        self.assertFalse(
            _is_excluded('specs/login/requirements/req.md',
                         ['archived', '_template']))

    def test_empty_list(self):
        self.assertFalse(
            _is_excluded('specs/archived/requirements/req.md', []))

    def test_none_list(self):
        self.assertFalse(
            _is_excluded('specs/archived/requirements/req.md', None))

    def test_deep_nested_excluded(self):
        """パスの深い位置にある exclude 名もマッチする"""
        self.assertTrue(
            _is_excluded('a/b/c/archived/d/e.md', ['archived']))

    def test_partial_name_not_excluded(self):
        """部分一致はマッチしない（archived_v2 != archived）"""
        self.assertFalse(
            _is_excluded('specs/archived_v2/requirements/req.md',
                         ['archived']))

    def test_backslash_path(self):
        """Windows パス区切りもサポート"""
        self.assertTrue(
            _is_excluded('specs\\archived\\requirements\\req.md',
                         ['archived']))


class TestGetAllExcludes(_YamlFileTestCase):
    """_get_all_excludes のテスト"""

    def test_specs_excludes(self):
        ds = self._load_config(CONFIG_WITH_EXCLUDE)
        excludes = _get_all_excludes(ds, 'specs')
        self.assertEqual(excludes, {'archived', '_template'})

    def test_rules_no_excludes(self):
        ds = self._load_config(CONFIG_WITH_EXCLUDE)
        excludes = _get_all_excludes(ds, 'rules')
        self.assertEqual(excludes, set())

    def test_rules_with_excludes(self):
        ds = self._load_config(CONFIG_MIXED_EXCLUDE)
        excludes = _get_all_excludes(ds, 'rules')
        self.assertEqual(excludes, {'deprecated'})

    def test_none_doc_structure(self):
        excludes = _get_all_excludes(None, 'specs')
        self.assertEqual(excludes, set())


# =========================================================================
# 3. 種別判定テスト
# =========================================================================

class TestDocTypeToReviewType(unittest.TestCase):
    """_doc_type_to_review_type のテスト"""

    def test_requirement(self):
        self.assertEqual(_doc_type_to_review_type('requirement'), 'requirement')

    def test_design(self):
        self.assertEqual(_doc_type_to_review_type('design'), 'design')

    def test_plan(self):
        self.assertEqual(_doc_type_to_review_type('plan'), 'plan')

    def test_unknown(self):
        self.assertEqual(_doc_type_to_review_type('unknown'), 'generic')

    def test_rule(self):
        self.assertEqual(_doc_type_to_review_type('rule'), 'generic')


class TestDetectTypeFromDocStructure(_YamlFileTestCase):
    """detect_type_from_doc_structure のテスト"""

    def _get_ds(self, config_content=CONFIG_WITH_EXCLUDE):
        return self._load_config(config_content)

    def _setup_dirs(self):
        """テスト用のディレクトリ構造を作成"""
        for d in ['specs/login/requirements', 'specs/login/design', 'rules']:
            (self.tmpdir / d).mkdir(parents=True, exist_ok=True)

    def test_normal_path_requirement(self):
        self._setup_dirs()
        ds = self._get_ds()
        self.assertEqual(
            detect_type_from_doc_structure(
                'specs/login/requirements/req.md', ds, self.tmpdir),
            'requirement')

    def test_normal_path_design(self):
        self._setup_dirs()
        ds = self._get_ds()
        self.assertEqual(
            detect_type_from_doc_structure(
                'specs/login/design/design.md', ds, self.tmpdir),
            'design')

    def test_rules_path(self):
        """rules にマッチするパスは generic を返す"""
        self._setup_dirs()
        ds = self._get_ds()
        self.assertEqual(
            detect_type_from_doc_structure('rules/coding.md', ds, self.tmpdir),
            'generic')

    def test_none_doc_structure(self):
        self.assertIsNone(
            detect_type_from_doc_structure('specs/login/requirements/req.md', None, self.tmpdir))


class TestDetectGenericType(_YamlFileTestCase):
    """_detect_generic_type のテスト"""

    def _get_ds(self, config_content=CONFIG_MIXED_EXCLUDE):
        return self._load_config(config_content)

    def test_rules_path(self):
        ds = self._get_ds(CONFIG_WITH_EXCLUDE)
        self.assertEqual(_detect_generic_type('rules/coding.md', ds), 'generic')

    def test_rules_excluded(self):
        """rules に exclude があるとき、除外パスは generic にならない"""
        ds = self._get_ds(CONFIG_MIXED_EXCLUDE)
        self.assertIsNone(
            _detect_generic_type('rules/deprecated/old_rule.md', ds))

    def test_rules_not_excluded(self):
        ds = self._get_ds(CONFIG_MIXED_EXCLUDE)
        self.assertEqual(
            _detect_generic_type('rules/coding/style.md', ds), 'generic')

    def test_skills_path(self):
        self.assertEqual(
            _detect_generic_type('.claude/skills/my-skill/SKILL.md'), 'generic')

    def test_root_readme(self):
        self.assertEqual(_detect_generic_type('README.md'), 'generic')

    def test_nested_readme(self):
        """ルート以外の README.md は generic にならない"""
        self.assertIsNone(_detect_generic_type('docs/README.md'))

    def test_no_doc_structure(self):
        """doc_structure なしでもデフォルト rules/ でマッチ"""
        self.assertEqual(_detect_generic_type('rules/coding.md'), 'generic')


class TestGetRulesAndSpecsPaths(_YamlFileTestCase):
    """get_rules_paths / get_specs_paths_by_type のテスト"""

    def test_get_rules_paths(self):
        ds = self._load_config(CONFIG_FLAT)
        self.assertEqual(get_rules_paths(ds), ['rules/'])

    def test_get_rules_paths_none(self):
        self.assertEqual(get_rules_paths(None), [])

    def test_get_specs_paths_requirement(self):
        ds = self._load_config(CONFIG_FLAT)
        self.assertEqual(get_specs_paths_by_type(ds, 'requirement'),
                         ['specs/requirements/'])

    def test_get_specs_paths_design(self):
        ds = self._load_config(CONFIG_FLAT)
        self.assertEqual(get_specs_paths_by_type(ds, 'design'),
                         ['specs/design/'])

    def test_get_specs_paths_none(self):
        self.assertEqual(get_specs_paths_by_type(None, 'requirement'), [])


# =========================================================================
# 4. Feature 検出テスト（ファイルシステム必要）
# =========================================================================

class TestDetectFeaturesFromDocStructure(_YamlFileTestCase):
    """detect_features_from_doc_structure のテスト"""

    def _setup_feature_dirs(self, feature_names, excluded_names=None):
        """テスト用のディレクトリ構造を作成"""
        for name in feature_names:
            (self.tmpdir / 'specs' / name / 'requirements').mkdir(parents=True)
            (self.tmpdir / 'specs' / name / 'requirements' / 'req.md').touch()
        for name in (excluded_names or []):
            (self.tmpdir / 'specs' / name / 'requirements').mkdir(parents=True)
            (self.tmpdir / 'specs' / name / 'requirements' / 'req.md').touch()

    def _make_config(self, exclude=None):
        """.doc_structure.yaml形式の config dict を作成"""
        config = {
            'specs': {
                'root_dirs': ['specs/*/requirements/'],
                'doc_types_map': {'specs/*/requirements/': 'requirement'},
                'patterns': {
                    'target_glob': '**/*.md',
                    'exclude': exclude or [],
                },
            },
            'rules': {
                'root_dirs': [],
                'doc_types_map': {},
                'patterns': {'target_glob': '**/*.md', 'exclude': []},
            },
        }
        return config

    def test_features_detected(self):
        self._setup_feature_dirs(['login', 'auth'])
        ds = self._make_config()
        features = detect_features_from_doc_structure(self.tmpdir, ds)
        self.assertEqual(sorted(features), ['auth', 'login'])

    def test_excluded_features_not_detected(self):
        """exclude に含まれるディレクトリは Feature に現れない"""
        self._setup_feature_dirs(['login', 'auth'], ['archived', '_template'])
        ds = self._make_config(exclude=['archived', '_template'])
        features = detect_features_from_doc_structure(self.tmpdir, ds)
        self.assertEqual(sorted(features), ['auth', 'login'])
        self.assertNotIn('archived', features)
        self.assertNotIn('_template', features)

    def test_no_exclude_includes_all(self):
        """exclude なしなら全ディレクトリが Feature に含まれる"""
        self._setup_feature_dirs(['login', 'archived'])
        ds = self._make_config()
        features = detect_features_from_doc_structure(self.tmpdir, ds)
        self.assertIn('archived', features)
        self.assertIn('login', features)

    def test_none_doc_structure(self):
        features = detect_features_from_doc_structure(self.tmpdir, None)
        self.assertEqual(features, [])

    def test_no_glob_pattern(self):
        """glob なしのパスからは Feature を検出しない"""
        (self.tmpdir / 'specs' / 'requirements').mkdir(parents=True)
        ds = {
            'specs': {
                'root_dirs': ['specs/requirements/'],
                'doc_types_map': {'specs/requirements/': 'requirement'},
                'patterns': {'target_glob': '**/*.md', 'exclude': []},
            },
            'rules': {
                'root_dirs': [],
                'doc_types_map': {},
                'patterns': {'target_glob': '**/*.md', 'exclude': []},
            },
        }
        features = detect_features_from_doc_structure(self.tmpdir, ds)
        self.assertEqual(features, [])


# =========================================================================
# 5. Feature 解決テスト（ファイルシステム必要）
# =========================================================================

class TestFindFeatureSubdirs(_YamlFileTestCase):
    """find_feature_subdirs のテスト"""

    def _setup_feature(self, feature, subdirs):
        for sub in subdirs:
            d = self.tmpdir / 'specs' / feature / sub
            d.mkdir(parents=True, exist_ok=True)
            (d / 'doc.md').touch()

    def _make_config(self, doc_types, exclude=None):
        """doc_types: {'requirements': 'requirement', 'design': 'design'} 形式"""
        root_dirs = [f'specs/*/{k}/' for k in doc_types]
        dtm = {f'specs/*/{k}/': v for k, v in doc_types.items()}
        return {
            'specs': {
                'root_dirs': root_dirs,
                'doc_types_map': dtm,
                'patterns': {
                    'target_glob': '**/*.md',
                    'exclude': exclude or [],
                },
            },
            'rules': {
                'root_dirs': [],
                'doc_types_map': {},
                'patterns': {'target_glob': '**/*.md', 'exclude': []},
            },
        }

    def test_feature_with_requirement(self):
        self._setup_feature('login', ['requirements'])
        ds = self._make_config({'requirements': 'requirement'})
        types = find_feature_subdirs(self.tmpdir, ds, 'login')
        self.assertEqual(types, ['requirement'])

    def test_excluded_feature_returns_empty(self):
        """exclude に含まれる Feature 名は結果に含まれない"""
        self._setup_feature('archived', ['requirements'])
        ds = self._make_config({'requirements': 'requirement'}, exclude=['archived'])
        types = find_feature_subdirs(self.tmpdir, ds, 'archived')
        self.assertEqual(types, [])

    def test_none_doc_structure(self):
        self.assertEqual(find_feature_subdirs(self.tmpdir, None, 'login'), [])


class TestFindTargetFiles(_YamlFileTestCase):
    """find_target_files のテスト"""

    def _setup_feature_files(self, feature, subdir, filenames):
        d = self.tmpdir / 'specs' / feature / subdir
        d.mkdir(parents=True, exist_ok=True)
        for name in filenames:
            (d / name).touch()

    def _make_config(self, doc_types, exclude=None):
        root_dirs = [f'specs/*/{k}/' for k in doc_types]
        dtm = {f'specs/*/{k}/': v for k, v in doc_types.items()}
        return {
            'specs': {
                'root_dirs': root_dirs,
                'doc_types_map': dtm,
                'patterns': {
                    'target_glob': '**/*.md',
                    'exclude': exclude or [],
                },
            },
            'rules': {
                'root_dirs': [],
                'doc_types_map': {},
                'patterns': {'target_glob': '**/*.md', 'exclude': []},
            },
        }

    def test_find_files(self):
        self._setup_feature_files('login', 'requirements', ['req1.md', 'req2.md'])
        ds = self._make_config({'requirements': 'requirement'})
        files = find_target_files(self.tmpdir, ds, 'login', 'requirement')
        self.assertEqual(len(files), 2)
        self.assertTrue(all('login/requirements' in f for f in files))

    def test_excluded_files_filtered(self):
        """exclude パスに含まれるファイルはフィルタされる"""
        self._setup_feature_files('archived', 'requirements', ['req.md'])
        self._setup_feature_files('login', 'requirements', ['req.md'])
        ds = self._make_config({'requirements': 'requirement'}, exclude=['archived'])
        files = find_target_files(self.tmpdir, ds, 'login', 'requirement')
        self.assertEqual(len(files), 1)
        self.assertIn('login', files[0])

    def test_none_doc_structure(self):
        self.assertEqual(find_target_files(self.tmpdir, None, 'login', 'requirement'), [])


# =========================================================================
# 6. 種別判定の統合テスト
# =========================================================================

class TestDetectTypeFromPath(_YamlFileTestCase):
    """detect_type_from_path の統合テスト"""

    def _get_ds(self, config_content=CONFIG_WITH_EXCLUDE):
        return self._load_config(config_content)

    def _setup_dirs(self):
        for d in ['specs/login/requirements', 'specs/login/design', 'rules']:
            (self.tmpdir / d).mkdir(parents=True, exist_ok=True)

    def test_code_by_extension(self):
        ds = self._get_ds()
        self.assertEqual(
            detect_type_from_path('src/main.swift', ds, self.tmpdir), 'code')

    def test_python_code(self):
        ds = self._get_ds()
        self.assertEqual(
            detect_type_from_path('scripts/tool.py', ds, self.tmpdir), 'code')

    def test_requirement_from_doc_structure(self):
        self._setup_dirs()
        ds = self._get_ds()
        self.assertEqual(
            detect_type_from_path(
                'specs/login/requirements/req.md', ds, self.tmpdir),
            'requirement')

    def test_generic_from_skills(self):
        ds = self._get_ds()
        self.assertEqual(
            detect_type_from_path(
                '.claude/skills/my-skill/SKILL.md', ds, self.tmpdir),
            'generic')


class TestDetectTypeFromDir(_YamlFileTestCase):
    """detect_type_from_dir のテスト"""

    def _make_empty_config(self):
        return {
            'specs': {
                'root_dirs': [],
                'doc_types_map': {},
                'patterns': {'target_glob': '**/*.md', 'exclude': []},
            },
            'rules': {
                'root_dirs': [],
                'doc_types_map': {},
                'patterns': {'target_glob': '**/*.md', 'exclude': []},
            },
        }

    def test_code_dir(self):
        src = self.tmpdir / 'src'
        src.mkdir()
        (src / 'main.swift').touch()
        ds = self._make_empty_config()
        review_type, files = detect_type_from_dir('src', ds, self.tmpdir)
        self.assertEqual(review_type, 'code')
        self.assertTrue(len(files) > 0)

    def test_mixed_code_and_md(self):
        """コード + md 混在ディレクトリは code を返す"""
        src = self.tmpdir / 'src'
        src.mkdir()
        (src / 'main.py').touch()
        (src / 'README.md').touch()
        ds = self._make_empty_config()
        review_type, files = detect_type_from_dir('src', ds, self.tmpdir)
        self.assertEqual(review_type, 'code')

    def test_empty_dir(self):
        empty = self.tmpdir / 'empty'
        empty.mkdir()
        ds = self._make_empty_config()
        review_type, files = detect_type_from_dir('empty', ds, self.tmpdir)
        self.assertIsNone(review_type)
        self.assertEqual(files, [])

    def test_nonexistent_dir(self):
        ds = self._make_empty_config()
        review_type, files = detect_type_from_dir('nonexistent', ds, self.tmpdir)
        self.assertIsNone(review_type)
        self.assertEqual(files, [])


if __name__ == '__main__':
    unittest.main()
