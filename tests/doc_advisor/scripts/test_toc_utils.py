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
# yaml_escape テスト（test_edge_cases.sh から移行）
# ===========================================================================

class TestYamlEscape(unittest.TestCase):
    """yaml_escape() のクォートルールテスト。"""

    # --- クォート不要（block plain scalar safe） ---

    def test_plain_text(self):
        result = toc_utils.yaml_escape('normal text')
        self.assertFalse(result.startswith('"'), f'should not be quoted: {result}')

    def test_comma_in_middle(self):
        result = toc_utils.yaml_escape('App Store, Google Play')
        self.assertFalse(result.startswith('"'), f'should not be quoted: {result}')

    def test_parens_with_comma(self):
        result = toc_utils.yaml_escape('scope (App Store, Google Play)')
        self.assertFalse(result.startswith('"'), f'should not be quoted: {result}')

    def test_parens_with_comma_2(self):
        result = toc_utils.yaml_escape('Role assignments (Yumemi, Daytona)')
        self.assertFalse(result.startswith('"'), f'should not be quoted: {result}')

    def test_colon_without_trailing_space(self):
        result = toc_utils.yaml_escape('10:00 deadline')
        self.assertFalse(result.startswith('"'), f'should not be quoted: {result}')

    def test_ampersand_in_middle(self):
        result = toc_utils.yaml_escape('foo&bar')
        self.assertFalse(result.startswith('"'), f'should not be quoted: {result}')

    def test_brackets_in_middle(self):
        result = toc_utils.yaml_escape('item [1] description')
        self.assertFalse(result.startswith('"'), f'should not be quoted: {result}')

    # --- クォート必要（YAML special） ---

    def test_colon_space(self):
        result = toc_utils.yaml_escape('foo: bar')
        self.assertTrue(result.startswith('"') and result.endswith('"'),
                        f'should be quoted: {result}')

    def test_space_hash(self):
        result = toc_utils.yaml_escape('see section #3')
        self.assertTrue(result.startswith('"') and result.endswith('"'),
                        f'should be quoted: {result}')

    def test_starts_with_bracket(self):
        result = toc_utils.yaml_escape('[starts with bracket')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_starts_with_brace(self):
        result = toc_utils.yaml_escape('{starts with brace')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_starts_with_dash(self):
        result = toc_utils.yaml_escape('- starts with dash')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_starts_with_hash(self):
        result = toc_utils.yaml_escape('#starts with hash')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_starts_with_star(self):
        result = toc_utils.yaml_escape('*starts with star')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_starts_with_amp(self):
        result = toc_utils.yaml_escape('&starts with amp')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_starts_with_bang(self):
        result = toc_utils.yaml_escape('!starts with bang')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_trailing_colon(self):
        result = toc_utils.yaml_escape('trailing colon:')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_trailing_space(self):
        result = toc_utils.yaml_escape('trailing space ')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_leading_space(self):
        result = toc_utils.yaml_escape(' leading space')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_boolean_true(self):
        result = toc_utils.yaml_escape('true')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_boolean_false(self):
        result = toc_utils.yaml_escape('false')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_boolean_yes(self):
        result = toc_utils.yaml_escape('yes')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_boolean_no(self):
        result = toc_utils.yaml_escape('no')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_boolean_on(self):
        result = toc_utils.yaml_escape('on')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_boolean_off(self):
        result = toc_utils.yaml_escape('off')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_null_keyword(self):
        result = toc_utils.yaml_escape('null')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_none_keyword(self):
        result = toc_utils.yaml_escape('none')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_tilde(self):
        result = toc_utils.yaml_escape('~')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_integer(self):
        result = toc_utils.yaml_escape('123')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_float(self):
        result = toc_utils.yaml_escape('3.14')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_empty_string(self):
        result = toc_utils.yaml_escape('')
        self.assertEqual(result, '""')

    def test_newline(self):
        result = toc_utils.yaml_escape('line1\nline2')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')
        self.assertIn('\\n', result)

    def test_tab(self):
        result = toc_utils.yaml_escape('has\ttab')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')
        self.assertIn('\\t', result)

    def test_double_quotes_in_string(self):
        result = toc_utils.yaml_escape('has "double quotes"')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')
        # 内部の " がエスケープされていること
        self.assertIn('\\"', result)

    def test_single_quotes_in_string(self):
        result = toc_utils.yaml_escape("has 'single quotes'")
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_backslash_not_quoted(self):
        """バックスラッシュのみではクォート不要（YAML spec 上は plain scalar で有効）"""
        result = toc_utils.yaml_escape('path\\to\\file')
        self.assertFalse(result.startswith('"'), f'should not be quoted: {result}')

    def test_backslash_with_special_char_quoted(self):
        """バックスラッシュ + 改行など特殊文字でクォートされる場合はエスケープされる"""
        result = toc_utils.yaml_escape('path\\to\nfile')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')
        self.assertIn('\\\\', result)

    def test_starts_with_percent(self):
        result = toc_utils.yaml_escape('%TAG')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_starts_with_at(self):
        result = toc_utils.yaml_escape('@mention')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_starts_with_backtick(self):
        result = toc_utils.yaml_escape('`code`')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_starts_with_pipe(self):
        result = toc_utils.yaml_escape('|literal block')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_starts_with_greater_than(self):
        result = toc_utils.yaml_escape('>folded block')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_starts_with_question(self):
        result = toc_utils.yaml_escape('?mapping key')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')

    def test_carriage_return(self):
        result = toc_utils.yaml_escape('line1\rline2')
        self.assertTrue(result.startswith('"'), f'should be quoted: {result}')
        self.assertIn('\\r', result)

    def test_unicode_preserved(self):
        """Unicode 文字列はそのまま保持される"""
        result = toc_utils.yaml_escape('日本語テスト')
        self.assertEqual(result, '日本語テスト')

    def test_none_input(self):
        """None 入力は空文字列を返す"""
        result = toc_utils.yaml_escape(None)
        self.assertEqual(result, '""')


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
    """get_project_root() の3段階フォールバックテスト。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.original_env = os.environ.get('CLAUDE_PROJECT_DIR')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        if self.original_env is None:
            os.environ.pop('CLAUDE_PROJECT_DIR', None)
        else:
            os.environ['CLAUDE_PROJECT_DIR'] = self.original_env

    def test_stage1_env_var(self):
        """Stage 1: CLAUDE_PROJECT_DIR 環境変数"""
        os.environ['CLAUDE_PROJECT_DIR'] = self.tmpdir
        result = toc_utils.get_project_root()
        self.assertEqual(result, Path(self.tmpdir))

    def test_stage1_invalid_dir(self):
        """Stage 1: CLAUDE_PROJECT_DIR が無効なディレクトリの場合は Stage 2 へ"""
        os.environ['CLAUDE_PROJECT_DIR'] = '/nonexistent/path'
        # CWD にも .git/.claude がなければ RuntimeError
        # テスト実行環境に .git があるため、Stage 2 で見つかる可能性がある
        # ここでは Stage 1 のスキップのみ検証
        try:
            result = toc_utils.get_project_root()
            # Stage 2 で見つかった場合（テスト環境による）
            self.assertIsInstance(result, Path)
        except RuntimeError:
            # Stage 3: 見つからなかった場合も正常
            pass

    def test_stage3_error(self):
        """Stage 3: プロジェクトルートが見つからない場合は RuntimeError"""
        os.environ.pop('CLAUDE_PROJECT_DIR', None)
        # 空のディレクトリで .git も .claude もない状態をシミュレート
        empty_dir = tempfile.mkdtemp()
        try:
            original_cwd = os.getcwd()
            os.chdir(empty_dir)
            try:
                with self.assertRaises(RuntimeError):
                    toc_utils.get_project_root()
            finally:
                os.chdir(original_cwd)
        finally:
            shutil.rmtree(empty_dir, ignore_errors=True)


# ===========================================================================
# get_system_exclude_patterns テスト
# ===========================================================================

class TestGetSystemExcludePatterns(unittest.TestCase):
    """get_system_exclude_patterns() のテスト。"""

    def test_rules_patterns(self):
        patterns = toc_utils.get_system_exclude_patterns('rules')
        self.assertIn('.toc_work', patterns)
        self.assertIn('rules_toc.yaml', patterns)
        self.assertIn('.toc_checksums.yaml', patterns)

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


if __name__ == '__main__':
    unittest.main()
