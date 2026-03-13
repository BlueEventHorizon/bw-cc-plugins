#!/usr/bin/env python3
"""
resolve_doc_references.py のテスト

.doc_structure.yaml の行ベースパース・パス解決・CLI 動作をテストする。
標準ライブラリのみ使用。

実行:
  python3 -m unittest tests.forge.scripts.test_resolve_doc_references -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# テスト対象モジュールへのパスを追加
sys.path.insert(0, str(Path(__file__).resolve().parents[3]
                       / 'plugins' / 'forge' / 'scripts'))

from resolve_doc_references import (
    _collect_md_files,
    _is_excluded,
    _parse_inline_array,
    find_project_root,
    parse_doc_structure,
    resolve_paths,
    resolve_references,
)


# ---------------------------------------------------------------------------
# テスト基底クラス
# ---------------------------------------------------------------------------

class _FsTestCase(unittest.TestCase):
    """ファイルシステムを使うテストの基底クラス。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_file(self, rel_path, content=''):
        """テスト用ファイルを作成する。"""
        p = self.tmpdir / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding='utf-8')
        return p

    def _write_doc_structure(self, content):
        """.doc_structure.yaml を tmpdir に作成する。"""
        return self._write_file('.doc_structure.yaml', content)


# =========================================================================
# 1. ユーティリティ関数のテスト
# =========================================================================

class TestParseInlineArray(unittest.TestCase):
    """_parse_inline_array のテスト。"""

    def test_single_item(self):
        self.assertEqual(_parse_inline_array('[docs/rules/]'), ['docs/rules/'])

    def test_multiple_items(self):
        result = _parse_inline_array('[docs/rules/, docs/specs/]')
        self.assertEqual(result, ['docs/rules/', 'docs/specs/'])

    def test_quoted_items(self):
        result = _parse_inline_array('["specs/*/requirements/", "docs/"]')
        self.assertEqual(result, ['specs/*/requirements/', 'docs/'])

    def test_empty_array(self):
        result = _parse_inline_array('[]')
        self.assertEqual(result, [])


class TestIsExcluded(unittest.TestCase):
    """_is_excluded のテスト。"""

    def test_excluded_component(self):
        self.assertTrue(_is_excluded('specs/archived/req.md', ['archived']))

    def test_not_excluded(self):
        self.assertFalse(_is_excluded('specs/login/req.md', ['archived']))

    def test_multiple_excludes(self):
        self.assertTrue(_is_excluded('specs/_template/req.md', ['archived', '_template']))

    def test_empty_excludes(self):
        self.assertFalse(_is_excluded('specs/archived/req.md', []))

    def test_partial_name_not_excluded(self):
        """部分一致ではなくコンポーネント完全一致のみ除外される。"""
        self.assertFalse(_is_excluded('specs/archived_data/req.md', ['archived']))


# =========================================================================
# 2. parse_doc_structure のテスト
# =========================================================================

class TestParseDocStructure(_FsTestCase):
    """parse_doc_structure のテスト。"""

    def test_basic_flat_structure(self):
        """フラット構造の基本パース。"""
        self._write_doc_structure("""\
version: "1.0"

specs:
  requirement:
    paths: [specs/requirements/]
    description: "要件定義書"

rules:
  rule:
    paths: [docs/rules/]
""")
        result = parse_doc_structure(str(self.tmpdir / '.doc_structure.yaml'))
        self.assertIn('requirement', result['specs'])
        self.assertEqual(result['specs']['requirement']['paths'], ['specs/requirements/'])
        self.assertIn('rule', result['rules'])
        self.assertEqual(result['rules']['rule']['paths'], ['docs/rules/'])

    def test_glob_paths(self):
        """glob パターンを含むパスのパース。"""
        self._write_doc_structure("""\
version: "1.0"

specs:
  requirement:
    paths: ["specs/*/requirements/"]
    exclude: ["archived", "_template"]
""")
        result = parse_doc_structure(str(self.tmpdir / '.doc_structure.yaml'))
        self.assertEqual(result['specs']['requirement']['paths'], ['specs/*/requirements/'])
        self.assertEqual(result['specs']['requirement']['exclude'], ['archived', '_template'])

    def test_multiple_paths(self):
        """複数パスのリスト形式パース。"""
        self._write_doc_structure("""\
version: "1.0"

specs:
  requirement:
    paths:
      - specs/requirements/
      - modules/requirements/
""")
        result = parse_doc_structure(str(self.tmpdir / '.doc_structure.yaml'))
        self.assertEqual(
            result['specs']['requirement']['paths'],
            ['specs/requirements/', 'modules/requirements/'],
        )

    def test_multiple_doc_types(self):
        """複数 doc_type のパース。"""
        self._write_doc_structure("""\
version: "1.0"

specs:
  requirement:
    paths: [specs/requirements/]
  design:
    paths: [specs/design/]
  plan:
    paths: [specs/plan/]

rules:
  rule:
    paths: [rules/]
  workflow:
    paths: [rules/workflow/]
""")
        result = parse_doc_structure(str(self.tmpdir / '.doc_structure.yaml'))
        self.assertIn('requirement', result['specs'])
        self.assertIn('design', result['specs'])
        self.assertIn('plan', result['specs'])
        self.assertIn('rule', result['rules'])
        self.assertIn('workflow', result['rules'])

    def test_file_not_found(self):
        """.doc_structure.yaml が存在しない場合に FileNotFoundError を送出する。"""
        with self.assertRaises(FileNotFoundError) as ctx:
            parse_doc_structure('/nonexistent/.doc_structure.yaml')
        self.assertIn('.doc_structure.yaml', str(ctx.exception))

    def test_comments_ignored(self):
        """コメント行が無視される。"""
        self._write_doc_structure("""\
# このファイルは .doc_structure.yaml のテストです
version: "1.0"

# specs セクション
specs:
  requirement:
    # 要件定義書のパス
    paths: [specs/requirements/]
""")
        result = parse_doc_structure(str(self.tmpdir / '.doc_structure.yaml'))
        self.assertEqual(result['specs']['requirement']['paths'], ['specs/requirements/'])

    def test_empty_specs_rules(self):
        """specs / rules のどちらかが存在しない場合も正常動作する。"""
        self._write_doc_structure("""\
version: "1.0"

rules:
  rule:
    paths: [docs/rules/]
""")
        result = parse_doc_structure(str(self.tmpdir / '.doc_structure.yaml'))
        self.assertEqual(result['specs'], {})
        self.assertIn('rule', result['rules'])


# =========================================================================
# 3. resolve_paths のテスト
# =========================================================================

class TestResolvePaths(_FsTestCase):
    """resolve_paths のテスト。"""

    def test_literal_directory_path(self):
        """リテラルディレクトリパスから .md ファイルを収集する。"""
        self._write_file('docs/rules/coding.md', '# コーディング規約')
        self._write_file('docs/rules/naming.md', '# 命名規則')
        self._write_file('docs/rules/readme.txt', 'テキストファイル')  # .md 以外は除外

        category_data = {
            'rule': {'paths': ['docs/rules'], 'exclude': []},
        }
        result = resolve_paths(str(self.tmpdir), category_data)
        self.assertIn('docs/rules/coding.md', result)
        self.assertIn('docs/rules/naming.md', result)
        self.assertNotIn('docs/rules/readme.txt', result)

    def test_glob_pattern_expansion(self):
        """glob パターンが正しく展開される。"""
        self._write_file('specs/login/requirements/req.md', '# ログイン要件')
        self._write_file('specs/payment/requirements/req.md', '# 支払い要件')

        category_data = {
            'requirement': {'paths': ['specs/*/requirements'], 'exclude': []},
        }
        result = resolve_paths(str(self.tmpdir), category_data)
        self.assertIn('specs/login/requirements/req.md', result)
        self.assertIn('specs/payment/requirements/req.md', result)

    def test_exclude_applied(self):
        """exclude に指定したディレクトリコンポーネントが除外される。"""
        self._write_file('specs/login/requirements/req.md', '# ログイン要件')
        self._write_file('specs/archived/requirements/old.md', '# 旧仕様')
        self._write_file('specs/_template/requirements/tmpl.md', '# テンプレート')

        category_data = {
            'requirement': {
                'paths': ['specs/*/requirements'],
                'exclude': ['archived', '_template'],
            },
        }
        result = resolve_paths(str(self.tmpdir), category_data)
        self.assertIn('specs/login/requirements/req.md', result)
        self.assertNotIn('specs/archived/requirements/old.md', result)
        self.assertNotIn('specs/_template/requirements/tmpl.md', result)

    def test_nonexistent_path_skipped(self):
        """存在しないパスはエラーなくスキップされる。"""
        category_data = {
            'rule': {'paths': ['nonexistent/path'], 'exclude': []},
        }
        result = resolve_paths(str(self.tmpdir), category_data)
        self.assertEqual(result, [])

    def test_no_duplicate(self):
        """同一ファイルが複数 doc_type にマッチしても重複しない。"""
        self._write_file('docs/shared/common.md', '# 共通文書')

        category_data = {
            'rule': {'paths': ['docs/shared'], 'exclude': []},
            'workflow': {'paths': ['docs/shared'], 'exclude': []},
        }
        result = resolve_paths(str(self.tmpdir), category_data)
        self.assertEqual(result.count('docs/shared/common.md'), 1)

    def test_recursive_glob(self):
        """** を含む glob パターンで再帰展開される。"""
        self._write_file('specs/requirements/req.md', '# 要件')
        self._write_file('specs/design/design.md', '# 設計')

        category_data = {
            'spec': {'paths': ['specs/**/*.md'], 'exclude': []},
        }
        result = resolve_paths(str(self.tmpdir), category_data)
        self.assertIn('specs/requirements/req.md', result)
        self.assertIn('specs/design/design.md', result)


# =========================================================================
# 4. resolve_references のテスト
# =========================================================================

class TestResolveReferences(_FsTestCase):
    """resolve_references のテスト（統合テスト）。"""

    def test_rules_category(self):
        """--type rules で rules カテゴリのファイルが解決される。"""
        self._write_file('docs/rules/coding.md', '# コーディング規約')
        self._write_doc_structure("""\
version: "1.0"

rules:
  rule:
    paths: [docs/rules]

specs:
  requirement:
    paths: [specs/]
""")
        result = resolve_references('rules', str(self.tmpdir))
        self.assertEqual(result['status'], 'resolved')
        self.assertIn('rules', result)
        self.assertNotIn('specs', result)
        self.assertIn('docs/rules/coding.md', result['rules'])

    def test_specs_category(self):
        """--type specs で specs カテゴリのファイルが解決される。"""
        self._write_file('specs/requirements/req.md', '# 要件定義書')
        self._write_doc_structure("""\
version: "1.0"

specs:
  requirement:
    paths: [specs/requirements]

rules:
  rule:
    paths: [docs/rules]
""")
        result = resolve_references('specs', str(self.tmpdir))
        self.assertEqual(result['status'], 'resolved')
        self.assertIn('specs', result)
        self.assertNotIn('rules', result)
        self.assertIn('specs/requirements/req.md', result['specs'])

    def test_all_category(self):
        """--type all で rules / specs 両方が解決される。"""
        self._write_file('docs/rules/coding.md', '# コーディング規約')
        self._write_file('specs/requirements/req.md', '# 要件定義書')
        self._write_doc_structure("""\
version: "1.0"

specs:
  requirement:
    paths: [specs/requirements]

rules:
  rule:
    paths: [docs/rules]
""")
        result = resolve_references('all', str(self.tmpdir))
        self.assertEqual(result['status'], 'resolved')
        self.assertIn('rules', result)
        self.assertIn('specs', result)
        self.assertIn('docs/rules/coding.md', result['rules'])
        self.assertIn('specs/requirements/req.md', result['specs'])

    def test_missing_doc_structure(self):
        """.doc_structure.yaml が存在しない場合に status: error を返す。"""
        result = resolve_references('all', str(self.tmpdir))
        self.assertEqual(result['status'], 'error')
        self.assertIn('message', result)
        self.assertIn('.doc_structure.yaml', result['message'])

    def test_project_root_in_result(self):
        """結果に project_root が含まれる。"""
        self._write_doc_structure("version: \"1.0\"\n")
        result = resolve_references('all', str(self.tmpdir))
        self.assertEqual(result['status'], 'resolved')
        self.assertEqual(result['project_root'], str(self.tmpdir))

    def test_glob_pattern_with_exclude(self):
        """glob パターン + exclude の組み合わせが正しく動作する。"""
        self._write_file('specs/login/requirements/req.md', '# ログイン要件')
        self._write_file('specs/archived/requirements/old.md', '# 旧仕様')
        self._write_doc_structure("""\
version: "1.0"

specs:
  requirement:
    paths: ["specs/*/requirements"]
    exclude: ["archived"]
""")
        result = resolve_references('specs', str(self.tmpdir))
        self.assertEqual(result['status'], 'resolved')
        self.assertIn('specs/login/requirements/req.md', result['specs'])
        self.assertNotIn('specs/archived/requirements/old.md', result['specs'])

    def test_custom_doc_structure_path(self):
        """--doc-structure オプションで任意のパスを指定できる。"""
        self._write_file('docs/rules/rule.md', '# ルール')
        custom_yaml = self.tmpdir / 'custom_structure.yaml'
        custom_yaml.write_text("""\
version: "1.0"

rules:
  rule:
    paths: [docs/rules]
""", encoding='utf-8')

        result = resolve_references(
            'rules',
            str(self.tmpdir),
            doc_structure_path=str(custom_yaml),
        )
        self.assertEqual(result['status'], 'resolved')
        self.assertIn('docs/rules/rule.md', result['rules'])


# =========================================================================
# 5. find_project_root のテスト
# =========================================================================

class TestFindProjectRoot(_FsTestCase):
    """find_project_root のテスト。"""

    def test_finds_git_root(self):
        """.git ディレクトリが存在するルートを検出する。"""
        (self.tmpdir / '.git').mkdir()
        subdir = self.tmpdir / 'src' / 'lib'
        subdir.mkdir(parents=True)

        result = find_project_root(str(subdir))
        # macOS では /var → /private/var のシンボリックリンクがあるため resolve() で比較する
        self.assertEqual(
            Path(result).resolve(),
            self.tmpdir.resolve(),
        )

    def test_returns_start_if_no_git(self):
        """.git が見つからない場合は start_path を返す。"""
        subdir = self.tmpdir / 'no_git_here'
        subdir.mkdir()

        result = find_project_root(str(subdir))
        self.assertEqual(result, str(subdir.resolve()))


# =========================================================================
# 6. CLI 統合テスト
# =========================================================================

class TestCLI(_FsTestCase):
    """subprocess で CLI を呼び出すテスト。"""

    SCRIPT = str(Path(__file__).resolve().parents[3]
                 / 'plugins' / 'forge' / 'scripts' / 'resolve_doc_references.py')

    def _run(self, *cli_args):
        """スクリプトを subprocess で実行して結果を返す。"""
        return subprocess.run(
            [sys.executable, self.SCRIPT] + list(cli_args),
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
        )

    def _make_project(self):
        """テスト用プロジェクト構造を作成する。"""
        self._write_file('docs/rules/coding.md', '# コーディング規約')
        self._write_file('specs/requirements/req.md', '# 要件定義書')
        self._write_doc_structure("""\
version: "1.0"

specs:
  requirement:
    paths: [specs/requirements]

rules:
  rule:
    paths: [docs/rules]
""")

    def test_type_rules(self):
        """--type rules で rules のみが返る。"""
        self._make_project()
        r = self._run('--type', 'rules', '--project-root', str(self.tmpdir))
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data['status'], 'resolved')
        self.assertIn('rules', data)
        self.assertNotIn('specs', data)
        self.assertIn('docs/rules/coding.md', data['rules'])

    def test_type_specs(self):
        """--type specs で specs のみが返る。"""
        self._make_project()
        r = self._run('--type', 'specs', '--project-root', str(self.tmpdir))
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data['status'], 'resolved')
        self.assertIn('specs', data)
        self.assertNotIn('rules', data)
        self.assertIn('specs/requirements/req.md', data['specs'])

    def test_type_all(self):
        """--type all で rules / specs 両方が返る。"""
        self._make_project()
        r = self._run('--type', 'all', '--project-root', str(self.tmpdir))
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data['status'], 'resolved')
        self.assertIn('rules', data)
        self.assertIn('specs', data)

    def test_error_no_doc_structure(self):
        """.doc_structure.yaml がない場合に status: error かつ exit code 1。"""
        r = self._run('--type', 'all', '--project-root', str(self.tmpdir))
        self.assertEqual(r.returncode, 1)
        data = json.loads(r.stdout)
        self.assertEqual(data['status'], 'error')
        self.assertIn('.doc_structure.yaml', data['message'])

    def test_custom_doc_structure_path(self):
        """--doc-structure で任意パスを指定できる。"""
        self._write_file('docs/rules/rule.md', '# ルール')
        custom_yaml = self.tmpdir / 'custom.yaml'
        custom_yaml.write_text("""\
version: "1.0"

rules:
  rule:
    paths: [docs/rules]
""", encoding='utf-8')

        r = self._run(
            '--type', 'rules',
            '--project-root', str(self.tmpdir),
            '--doc-structure', str(custom_yaml),
        )
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data['status'], 'resolved')
        self.assertIn('docs/rules/rule.md', data['rules'])

    def test_output_is_valid_json(self):
        """出力が常に有効な JSON である。"""
        r = self._run('--type', 'all', '--project-root', str(self.tmpdir))
        # エラー時でも JSON として解析できること
        try:
            json.loads(r.stdout)
        except json.JSONDecodeError:
            self.fail('出力が有効な JSON ではありません')

    def test_missing_type_arg(self):
        """--type を省略すると exit code != 0 になる。"""
        r = self._run('--project-root', str(self.tmpdir))
        self.assertNotEqual(r.returncode, 0)


if __name__ == '__main__':
    unittest.main()
