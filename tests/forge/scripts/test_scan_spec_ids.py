#!/usr/bin/env python3
"""
scan_spec_ids.py のテスト

git 操作を mock して、ブランチスキャン・ID 抽出・重複検出をテストする。
標準ライブラリのみ使用。

実行:
  python3 -m unittest tests.forge.scripts.test_scan_spec_ids -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, str(Path(__file__).resolve().parents[3]
                       / 'plugins' / 'forge' / 'skills'
                       / 'next-spec-id' / 'scripts'))

from scan_spec_ids import (
    _normalize_glob_to_prefix,
    _run_git,
    detect_base_branch,
    find_duplicates,
    get_scan_branches,
    get_specs_root_dirs,
    scan_ids_in_branch,
    scan_spec_ids,
)


class TestNormalizeGlobToPrefix(unittest.TestCase):
    """_normalize_glob_to_prefix のテスト"""

    def test_simple_path(self):
        self.assertEqual(_normalize_glob_to_prefix('specs/'), 'specs/')

    def test_single_glob(self):
        self.assertEqual(
            _normalize_glob_to_prefix('docs/specs/*/requirements/'),
            'docs/specs/',
        )

    def test_double_glob(self):
        self.assertEqual(
            _normalize_glob_to_prefix('docs/specs/**/design/'),
            'docs/specs/',
        )

    def test_glob_at_start(self):
        self.assertEqual(_normalize_glob_to_prefix('**/specs/'), '')

    def test_no_trailing_slash(self):
        self.assertEqual(
            _normalize_glob_to_prefix('docs/specs/**/design'),
            'docs/specs/',
        )


class TestFindDuplicates(unittest.TestCase):
    """find_duplicates のテスト"""

    def test_no_duplicates(self):
        entries = [
            ('SCR-001', 'main', 'specs/SCR-001_a.md'),
            ('SCR-002', 'main', 'specs/SCR-002_b.md'),
            ('SCR-003', 'feature/foo', 'specs/SCR-003_c.md'),
        ]
        self.assertEqual(find_duplicates(entries), [])

    def test_same_id_same_branch(self):
        entries = [
            ('SCR-001', 'main', 'specs/SCR-001_a.md'),
            ('SCR-001', 'main', 'specs/SCR-001_a.md'),
        ]
        self.assertEqual(find_duplicates(entries), [])

    def test_same_file_on_multiple_branches_is_not_duplicate(self):
        """同一履歴由来（同一パス）の ID が複数ブランチに見えるだけの
        ケースは duplicate として報告しない"""
        entries = [
            ('SCR-001', 'develop', 'specs/SCR-001_a.md'),
            ('SCR-001', 'feature/foo', 'specs/SCR-001_a.md'),
            ('SCR-001', 'origin/develop', 'specs/SCR-001_a.md'),
        ]
        self.assertEqual(find_duplicates(entries), [])

    def test_duplicate_across_branches(self):
        """異なるファイルが同じ ID を主張する場合は duplicate として報告する"""
        entries = [
            ('SCR-001', 'main', 'specs/SCR-001_a.md'),
            ('SCR-001', 'feature/foo', 'specs/SCR-001_x.md'),
            ('SCR-002', 'main', 'specs/SCR-002_b.md'),
        ]
        result = find_duplicates(entries)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['ids'], ['SCR-001'])
        self.assertIn('main', result[0]['branches'])
        self.assertIn('feature/foo', result[0]['branches'])
        self.assertEqual(
            result[0]['paths'],
            ['specs/SCR-001_a.md', 'specs/SCR-001_x.md'],
        )

    def test_multiple_duplicates(self):
        entries = [
            ('SCR-013', 'feature/a', 'specs/SCR-013_a.md'),
            ('SCR-013', 'origin/feature/b', 'specs/SCR-013_b.md'),
            ('SCR-014', 'feature/a', 'specs/SCR-014_a.md'),
            ('SCR-014', 'origin/feature/b', 'specs/SCR-014_b.md'),
        ]
        result = find_duplicates(entries)
        self.assertEqual(len(result), 2)
        ids = [id_value for duplicate in result for id_value in duplicate['ids']]
        self.assertIn('SCR-013', ids)
        self.assertIn('SCR-014', ids)

    def test_shared_numbering_detects_cross_prefix_collision(self):
        """共有採番モードでは ADR-032 と DES-032 を共有番号 032 の
        衝突として検出する"""
        entries = [
            ('ADR-032', 'develop', 'specs/design/ADR-032_foo.md'),
            ('DES-032', 'feature/x', 'specs/design/DES-032_bar.md'),
        ]
        result = find_duplicates(entries, shared_numbering=True)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['ids'], ['ADR-032', 'DES-032'])

    def test_shared_numbering_cross_prefix_not_collision_without_flag(self):
        """共有採番モードでなければ ADR-032 と DES-032 は独立した ID として扱う"""
        entries = [
            ('ADR-032', 'develop', 'specs/design/ADR-032_foo.md'),
            ('DES-032', 'feature/x', 'specs/design/DES-032_bar.md'),
        ]
        self.assertEqual(find_duplicates(entries), [])

    def test_shared_numbering_same_file_not_duplicate(self):
        """共有採番モードでも同一パス由来は duplicate にならない"""
        entries = [
            ('ADR-032', 'develop', 'specs/design/ADR-032_foo.md'),
            ('ADR-032', 'origin/develop', 'specs/design/ADR-032_foo.md'),
        ]
        self.assertEqual(find_duplicates(entries, shared_numbering=True), [])

    def test_zero_padding_variants_group_by_number(self):
        """番号は int 正規化して比較する（DES-032 と DES-32 は同じ番号の衝突）"""
        entries = [
            ('DES-032', 'develop', 'specs/design/DES-032_foo.md'),
            ('DES-32', 'feature/x', 'specs/design/DES-32_bar.md'),
        ]
        result = find_duplicates(entries)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['ids'], ['DES-032', 'DES-32'])

    def test_empty_input(self):
        self.assertEqual(find_duplicates([]), [])


class TestGetSpecsRootDirs(unittest.TestCase):
    """get_specs_root_dirs のテスト"""

    def test_fallback_when_no_doc_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = get_specs_root_dirs(tmpdir)
            self.assertEqual(result, ['specs/'])

    def test_reads_from_doc_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            doc_structure = os.path.join(tmpdir, '.doc_structure.yaml')
            with open(doc_structure, 'w') as f:
                f.write(
                    '# doc_structure_version: 4.0\n'
                    'specs:\n'
                    '  root_dirs:\n'
                    '    - "docs/specs/**/design/"\n'
                    '    - "docs/specs/**/requirements/"\n'
                )
            result = get_specs_root_dirs(tmpdir)
            self.assertEqual(len(result), 2)
            self.assertIn('docs/specs/**/design/', result)
            self.assertIn('docs/specs/**/requirements/', result)


class TestDetectBaseBranch(unittest.TestCase):
    """detect_base_branch のテスト"""

    @patch('scan_spec_ids.subprocess.run')
    def test_develop_local(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = detect_base_branch(cwd='/tmp')
        self.assertEqual(result, 'develop')

    @patch('scan_spec_ids.subprocess.run')
    def test_main_fallback(self, mock_run):
        def side_effect(args, **kwargs):
            ref = args[3] if len(args) > 3 else ''
            mock = MagicMock()
            if 'main' in ref and 'remotes' not in ref:
                mock.returncode = 0
            else:
                mock.returncode = 1
            return mock
        mock_run.side_effect = side_effect
        result = detect_base_branch(cwd='/tmp')
        self.assertEqual(result, 'main')


class TestGetScanBranches(unittest.TestCase):
    """get_scan_branches のテスト"""

    @patch('scan_spec_ids._run_git')
    def test_includes_branch_not_following_base(self, mock_git):
        """base に追従していない（is-ancestor が false になる）ブランチも
        スキャン対象に含まれることを確認する（再発防止）"""
        mock_git.return_value = (
            'develop\n'
            'feature/14-pyyaml-migration\n'
            'origin/develop\n'
            'origin/feature/14-pyyaml-migration'
        )
        result = get_scan_branches('develop', cwd='/tmp')
        self.assertIn('feature/14-pyyaml-migration', result)
        self.assertIn('origin/feature/14-pyyaml-migration', result)

    @patch('scan_spec_ids._run_git')
    def test_no_subprocess_filtering(self, mock_git):
        """is-ancestor によるフィルタは行わず、for-each-ref の出力をそのまま
        使うことを確認する（HEAD を含む行のみ除外）"""
        mock_git.return_value = (
            'develop\n'
            'feature/a\n'
            'feature/b\n'
            'HEAD -> origin/main'
        )
        result = get_scan_branches('develop', cwd='/tmp')
        self.assertEqual(
            sorted(result),
            sorted(['develop', 'feature/a', 'feature/b']),
        )

    @patch('scan_spec_ids._run_git')
    def test_empty_output_falls_back_to_base(self, mock_git):
        mock_git.return_value = ''
        result = get_scan_branches('develop', cwd='/tmp')
        self.assertEqual(result, ['develop'])


class TestScanIdsInBranch(unittest.TestCase):
    """scan_ids_in_branch のテスト"""

    @patch('scan_spec_ids._run_git')
    def test_extracts_ids(self, mock_git):
        mock_git.return_value = (
            'specs/requirements/SCR-001_user_list_spec.md\n'
            'specs/requirements/SCR-002_user_detail_spec.md\n'
            'specs/requirements/FNC-001_auth_spec.md\n'
            'specs/design/DES-001_user_list_design.md'
        )
        result = scan_ids_in_branch(
            'main', 'SCR', ['specs/'], cwd='/tmp'
        )
        self.assertEqual(len(result), 2)
        ids = [r[0] for r in result]
        self.assertIn('SCR-001', ids)
        self.assertIn('SCR-002', ids)

    @patch('scan_spec_ids._run_git')
    def test_no_matches(self, mock_git):
        mock_git.return_value = (
            'specs/requirements/FNC-001_auth_spec.md\n'
            'specs/design/DES-001_user_list_design.md'
        )
        result = scan_ids_in_branch(
            'main', 'SCR', ['specs/'], cwd='/tmp'
        )
        self.assertEqual(result, [])

    @patch('scan_spec_ids._run_git')
    def test_empty_branch(self, mock_git):
        mock_git.return_value = ''
        result = scan_ids_in_branch(
            'main', 'SCR', ['specs/'], cwd='/tmp'
        )
        self.assertEqual(result, [])

    @patch('scan_spec_ids._run_git')
    def test_glob_dirs_collapsed(self, mock_git):
        """異なる glob パターンが同じプレフィックスに集約される"""
        mock_git.return_value = (
            'docs/specs/auth/requirements/SCR-001_login_spec.md\n'
            'docs/specs/auth/design/DES-001_login_design.md'
        )
        result = scan_ids_in_branch(
            'main', 'SCR',
            ['docs/specs/**/requirements/', 'docs/specs/**/design/'],
            cwd='/tmp',
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], 'SCR-001')

    @patch('scan_spec_ids._run_git')
    def test_namespaced_prefix_not_extracted(self, mock_git):
        """COMMON-DES-001 のような別名前空間の ID を
        DES として誤抽出しない（部分文字列マッチの防止）"""
        mock_git.return_value = (
            'docs/specs/common/design/COMMON-DES-001_skill_base.md\n'
            'docs/specs/forge/design/DES-001_query_abstraction.md'
        )
        result = scan_ids_in_branch(
            'main', 'DES', ['docs/specs/'], cwd='/tmp'
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], 'DES-001')
        self.assertEqual(
            result[0][2], 'docs/specs/forge/design/DES-001_query_abstraction.md'
        )

    @patch('scan_spec_ids._run_git')
    def test_task_id_embedded_in_plan_json_content_is_detected(self, mock_git):
        """TASK は plan.json 本文へ埋め込まれるため、ファイル名に ID が
        現れなくても本文スキャンで検出できること（実際に TASK-012 が
        agenda_plan.json に存在するのに next_id として再び TASK-012 が
        返された事故の回帰防止）。"""
        def fake_git(*args, **kwargs):
            if args[0] == 'ls-tree':
                return 'docs/specs/x/plan/x_plan.json'
            if args[0] == 'show':
                return '{"tasks": [{"task_id": "TASK-005", "title": "..."}]}'
            return ''
        mock_git.side_effect = fake_git

        result = scan_ids_in_branch('main', 'TASK', ['docs/specs/'], cwd='/tmp')
        ids = [r[0] for r in result]
        self.assertIn('TASK-005', ids)

    @patch('scan_spec_ids._run_git')
    def test_plan_json_content_not_scanned_for_non_task_prefix(self, mock_git):
        """plan.json は design_id/requirement_ids 等で他プレフィックスの ID を
        参照として含むが、これは定義ではないため duplicate として誤検出しない
        こと（DES/REQ プレフィックスでは本文スキャンを行わない）。"""
        def fake_git(*args, **kwargs):
            if args[0] == 'ls-tree':
                return 'docs/specs/x/plan/x_plan.json'
            if args[0] == 'show':
                return '{"tasks": [{"design_id": "DES-005"}]}'
            return ''
        mock_git.side_effect = fake_git

        result = scan_ids_in_branch('main', 'DES', ['docs/specs/'], cwd='/tmp')
        self.assertEqual(result, [])

    @patch('scan_spec_ids._run_git')
    def test_tasks_directory_artifact_is_excluded(self, mock_git):
        """`tasks/{TASK-ID}.json` は build_task_context.py が plan.json から
        都度再生成する一時アーティファクト（正本の複製）であり、ファイル名に
        ID を含んでいてもスキャン対象に含めないこと（正本と同じ ID を
        duplicate として誤検出しないため）。"""
        mock_git.return_value = 'docs/specs/x/plan/tasks/TASK-006.json'

        result = scan_ids_in_branch('main', 'TASK', ['docs/specs/'], cwd='/tmp')
        self.assertEqual(result, [])

    @patch('scan_spec_ids._run_git')
    def test_zero_padded_ids(self, mock_git):
        mock_git.return_value = (
            'specs/SCR-001_a.md\n'
            'specs/SCR-015_b.md\n'
            'specs/SCR-100_c.md'
        )
        result = scan_ids_in_branch(
            'main', 'SCR', ['specs/'], cwd='/tmp'
        )
        self.assertEqual(len(result), 3)
        ids = sorted([r[0] for r in result])
        self.assertEqual(ids, ['SCR-001', 'SCR-015', 'SCR-100'])


class TestScanSpecIds(unittest.TestCase):
    """scan_spec_ids 統合テスト（git 操作を mock）"""

    @patch('scan_spec_ids.get_scan_branches')
    @patch('scan_spec_ids.detect_base_branch')
    @patch('scan_spec_ids._run_git')
    @patch('scan_spec_ids.get_specs_root_dirs')
    def test_basic_flow(self, mock_dirs, mock_git, mock_base, mock_branches):
        mock_dirs.return_value = ['specs/']
        mock_base.return_value = 'main'
        mock_branches.return_value = ['main', 'feature/foo']

        def git_side_effect(*args, cwd=None):
            if args[0] == 'fetch':
                return ''
            if args[0] == 'ls-tree':
                branch = args[3]
                if branch == 'main':
                    return (
                        'specs/SCR-001_a.md\n'
                        'specs/SCR-002_b.md\n'
                        'specs/SCR-003_c.md'
                    )
                elif branch == 'feature/foo':
                    return (
                        'specs/SCR-001_a.md\n'
                        'specs/SCR-004_d.md'
                    )
            return ''
        mock_git.side_effect = git_side_effect

        result = scan_spec_ids('SCR', '/tmp/project', cwd='/tmp/project')

        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['next_id'], 'SCR-005')
        self.assertEqual(result['prefix'], 'SCR')
        self.assertEqual(result['max_number'], 4)
        self.assertEqual(result['base_branch'], 'main')
        self.assertEqual(result['branches_scanned'], 2)
        self.assertEqual(result['ids_found'], 4)

    @patch('scan_spec_ids.get_scan_branches')
    @patch('scan_spec_ids.detect_base_branch')
    @patch('scan_spec_ids._run_git')
    @patch('scan_spec_ids.get_specs_root_dirs')
    def test_fetch_uses_prune(self, mock_dirs, mock_git, mock_base, mock_branches):
        """レビュー指摘: 全ブランチ無条件スキャン方式では、削除済み
        remote branch の stale ref が残ると存在しないブランチの高番 ID が
        永久に next_id を押し上げてしまうため、fetch は --prune 必須"""
        mock_dirs.return_value = ['specs/']
        mock_base.return_value = 'main'
        mock_branches.return_value = ['main']
        mock_git.return_value = ''

        scan_spec_ids('SCR', '/tmp/project', cwd='/tmp/project')

        fetch_calls = [
            call for call in mock_git.call_args_list
            if call.args and call.args[0] == 'fetch'
        ]
        self.assertEqual(len(fetch_calls), 1)
        self.assertIn('--prune', fetch_calls[0].args)

    @patch('scan_spec_ids.get_scan_branches')
    @patch('scan_spec_ids.detect_base_branch')
    @patch('scan_spec_ids._run_git')
    @patch('scan_spec_ids.get_specs_root_dirs')
    def test_detects_duplicates(self, mock_dirs, mock_git, mock_base,
                                mock_branches):
        mock_dirs.return_value = ['specs/']
        mock_base.return_value = 'develop'
        mock_branches.return_value = ['develop', 'feature/a', 'feature/b']

        def git_side_effect(*args, cwd=None):
            if args[0] == 'fetch':
                return ''
            if args[0] == 'ls-tree':
                branch = args[3]
                if branch == 'develop':
                    return 'specs/SCR-001_a.md\nspecs/SCR-002_b.md'
                elif branch == 'feature/a':
                    return 'specs/SCR-003_c.md'
                elif branch == 'feature/b':
                    return 'specs/SCR-003_d.md'
            return ''
        mock_git.side_effect = git_side_effect

        result = scan_spec_ids('SCR', '/tmp/project', cwd='/tmp/project')

        self.assertEqual(result['next_id'], 'SCR-004')
        self.assertEqual(len(result['duplicates']), 1)
        self.assertEqual(result['duplicates'][0]['ids'], ['SCR-003'])
        self.assertIn('feature/a', result['duplicates'][0]['branches'])
        self.assertIn('feature/b', result['duplicates'][0]['branches'])

    @patch('scan_spec_ids.get_scan_branches')
    @patch('scan_spec_ids.detect_base_branch')
    @patch('scan_spec_ids._run_git')
    @patch('scan_spec_ids.get_specs_root_dirs')
    def test_no_existing_ids(self, mock_dirs, mock_git, mock_base,
                             mock_branches):
        mock_dirs.return_value = ['specs/']
        mock_base.return_value = 'main'
        mock_branches.return_value = ['main']
        mock_git.return_value = ''

        result = scan_spec_ids('SCR', '/tmp/project', cwd='/tmp/project')

        self.assertEqual(result['next_id'], 'SCR-001')
        self.assertEqual(result['max_number'], 0)
        self.assertEqual(result['ids_found'], 0)

    @patch('scan_spec_ids.get_scan_branches')
    @patch('scan_spec_ids.detect_base_branch')
    @patch('scan_spec_ids._run_git')
    @patch('scan_spec_ids.get_specs_root_dirs')
    def test_custom_prefix(self, mock_dirs, mock_git, mock_base,
                           mock_branches):
        mock_dirs.return_value = ['specs/']
        mock_base.return_value = 'main'
        mock_branches.return_value = ['main']

        def git_side_effect(*args, cwd=None):
            if args[0] == 'ls-tree':
                return (
                    'specs/CUSTOM-001_a.md\n'
                    'specs/CUSTOM-002_b.md\n'
                    'specs/SCR-001_c.md'
                )
            return ''
        mock_git.side_effect = git_side_effect

        result = scan_spec_ids('CUSTOM', '/tmp/project', cwd='/tmp/project')

        self.assertEqual(result['next_id'], 'CUSTOM-003')
        self.assertEqual(result['prefix'], 'CUSTOM')
        self.assertEqual(result['max_number'], 2)
        self.assertEqual(result['ids_found'], 2)

    @patch('scan_spec_ids.get_scan_branches')
    @patch('scan_spec_ids.detect_base_branch')
    @patch('scan_spec_ids._run_git')
    @patch('scan_spec_ids.get_specs_root_dirs')
    def test_high_numbers(self, mock_dirs, mock_git, mock_base,
                          mock_branches):
        """3桁以上の番号も正しく処理する"""
        mock_dirs.return_value = ['specs/']
        mock_base.return_value = 'main'
        mock_branches.return_value = ['main']

        def git_side_effect(*args, cwd=None):
            if args[0] == 'ls-tree':
                return 'specs/SCR-100_a.md\nspecs/SCR-099_b.md'
            return ''
        mock_git.side_effect = git_side_effect

        result = scan_spec_ids('SCR', '/tmp/project', cwd='/tmp/project')

        self.assertEqual(result['next_id'], 'SCR-101')
        self.assertEqual(result['max_number'], 100)


class TestSharePrefixes(unittest.TestCase):
    """share_prefixes（通し番号共有）のテスト。"""

    @patch('scan_spec_ids.get_scan_branches')
    @patch('scan_spec_ids.detect_base_branch')
    @patch('scan_spec_ids._run_git')
    @patch('scan_spec_ids.get_specs_root_dirs')
    def test_share_prefixes_uses_cross_prefix_max(self, mock_dirs, mock_git,
                                                   mock_base, mock_branches):
        """ADR-032 と DES-031 併存時、share_prefixes=['ADR','DES'] で DES の次番が 033 になる"""
        mock_dirs.return_value = ['specs/design/']
        mock_base.return_value = 'develop'
        mock_branches.return_value = ['develop']

        def git_side_effect(*args, cwd=None):
            if args[0] == 'ls-tree':
                return (
                    'specs/design/ADR-032_foo.md\n'
                    'specs/design/DES-031_bar.md'
                )
            return ''
        mock_git.side_effect = git_side_effect

        result = scan_spec_ids(
            'DES', '/tmp/project', cwd='/tmp/project',
            share_prefixes=['ADR', 'DES'],
        )

        self.assertEqual(result['next_id'], 'DES-033')
        self.assertEqual(result['max_number'], 32)
        self.assertEqual(result['shared_with'], ['ADR'])

    @patch('scan_spec_ids.get_scan_branches')
    @patch('scan_spec_ids.detect_base_branch')
    @patch('scan_spec_ids._run_git')
    @patch('scan_spec_ids.get_specs_root_dirs')
    def test_share_prefixes_for_adr_side(self, mock_dirs, mock_git,
                                          mock_base, mock_branches):
        """ADR 側も同じ横断最大値を参照して次番を算出する"""
        mock_dirs.return_value = ['specs/design/']
        mock_base.return_value = 'develop'
        mock_branches.return_value = ['develop']

        def git_side_effect(*args, cwd=None):
            if args[0] == 'ls-tree':
                return (
                    'specs/design/ADR-032_foo.md\n'
                    'specs/design/DES-031_bar.md'
                )
            return ''
        mock_git.side_effect = git_side_effect

        result = scan_spec_ids(
            'ADR', '/tmp/project', cwd='/tmp/project',
            share_prefixes=['ADR', 'DES'],
        )

        self.assertEqual(result['next_id'], 'ADR-033')
        self.assertEqual(result['max_number'], 32)
        self.assertEqual(result['shared_with'], ['DES'])

    @patch('scan_spec_ids.get_scan_branches')
    @patch('scan_spec_ids.detect_base_branch')
    @patch('scan_spec_ids._run_git')
    @patch('scan_spec_ids.get_specs_root_dirs')
    def test_share_prefixes_detects_shared_number_collision(
        self, mock_dirs, mock_git, mock_base, mock_branches
    ):
        """受け入れ基準: ADR-032_foo.md と DES-032_bar.md がある場合、
        --share-prefixes ADR,DES で共有番号衝突が検出される"""
        mock_dirs.return_value = ['specs/design/']
        mock_base.return_value = 'develop'
        mock_branches.return_value = ['develop']

        def git_side_effect(*args, cwd=None):
            if args[0] == 'ls-tree':
                return (
                    'specs/design/ADR-032_foo.md\n'
                    'specs/design/DES-032_bar.md'
                )
            return ''
        mock_git.side_effect = git_side_effect

        result = scan_spec_ids(
            'DES', '/tmp/project', cwd='/tmp/project',
            share_prefixes=['ADR', 'DES'],
        )

        self.assertEqual(len(result['duplicates']), 1)
        self.assertEqual(result['duplicates'][0]['ids'], ['ADR-032', 'DES-032'])

    @patch('scan_spec_ids.get_scan_branches')
    @patch('scan_spec_ids.detect_base_branch')
    @patch('scan_spec_ids._run_git')
    @patch('scan_spec_ids.get_specs_root_dirs')
    def test_share_prefixes_same_history_ids_not_reported(
        self, mock_dirs, mock_git, mock_base, mock_branches
    ):
        """受け入れ基準: develop と current branch に同一ファイル由来で
        存在する既存 ID は duplicate 警告にならない"""
        mock_dirs.return_value = ['specs/design/']
        mock_base.return_value = 'develop'
        mock_branches.return_value = ['develop', 'feature/work', 'origin/develop']

        def git_side_effect(*args, cwd=None):
            if args[0] == 'ls-tree':
                # 全ブランチに同一パスで存在（同一履歴由来）
                return (
                    'specs/design/ADR-032_foo.md\n'
                    'specs/design/DES-031_bar.md'
                )
            return ''
        mock_git.side_effect = git_side_effect

        result = scan_spec_ids(
            'DES', '/tmp/project', cwd='/tmp/project',
            share_prefixes=['ADR', 'DES'],
        )

        self.assertEqual(result['duplicates'], [])
        self.assertEqual(result['next_id'], 'DES-033')

    @patch('scan_spec_ids.get_scan_branches')
    @patch('scan_spec_ids.detect_base_branch')
    @patch('scan_spec_ids._run_git')
    @patch('scan_spec_ids.get_specs_root_dirs')
    def test_without_share_prefixes_is_independent(self, mock_dirs, mock_git,
                                                     mock_base, mock_branches):
        """share_prefixes 未指定時は従来通り prefix 単位で独立採番される（後方互換）"""
        mock_dirs.return_value = ['specs/design/']
        mock_base.return_value = 'develop'
        mock_branches.return_value = ['develop']

        def git_side_effect(*args, cwd=None):
            if args[0] == 'ls-tree':
                return (
                    'specs/design/ADR-032_foo.md\n'
                    'specs/design/DES-031_bar.md'
                )
            return ''
        mock_git.side_effect = git_side_effect

        result = scan_spec_ids('DES', '/tmp/project', cwd='/tmp/project')

        self.assertEqual(result['next_id'], 'DES-032')
        self.assertNotIn('shared_with', result)

    @patch('scan_spec_ids.get_scan_branches')
    @patch('scan_spec_ids.detect_base_branch')
    @patch('scan_spec_ids._run_git')
    @patch('scan_spec_ids.get_specs_root_dirs')
    def test_share_prefixes_containing_only_self_is_noop(
        self, mock_dirs, mock_git, mock_base, mock_branches
    ):
        """share_prefixes に自分自身の prefix のみを渡しても独立採番と同じ結果になる"""
        mock_dirs.return_value = ['specs/design/']
        mock_base.return_value = 'develop'
        mock_branches.return_value = ['develop']

        def git_side_effect(*args, cwd=None):
            if args[0] == 'ls-tree':
                return 'specs/design/DES-031_bar.md'
            return ''
        mock_git.side_effect = git_side_effect

        result = scan_spec_ids(
            'DES', '/tmp/project', cwd='/tmp/project',
            share_prefixes=['DES'],
        )

        self.assertEqual(result['next_id'], 'DES-032')


class TestCLISharePrefixes(unittest.TestCase):
    """CLI 経由の --share-prefixes オプションのテスト。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        subprocess.run(['git', 'init', '-b', 'main'], cwd=self.tmpdir,
                        check=True, capture_output=True)
        subprocess.run(['git', 'config', 'user.email', 'test@example.com'],
                        cwd=self.tmpdir, check=True, capture_output=True)
        subprocess.run(['git', 'config', 'user.name', 'Test'],
                        cwd=self.tmpdir, check=True, capture_output=True)
        # ユーザーのグローバル設定（gpg 署名等）に依存しない
        subprocess.run(['git', 'config', 'commit.gpgsign', 'false'],
                        cwd=self.tmpdir, check=True, capture_output=True)
        specs_dir = self.tmpdir / 'specs'
        specs_dir.mkdir()
        (specs_dir / 'ADR-032_foo.md').write_text('# ADR-032\n', encoding='utf-8')
        (specs_dir / 'DES-031_bar.md').write_text('# DES-031\n', encoding='utf-8')
        subprocess.run(['git', 'add', '.'], cwd=self.tmpdir,
                        check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'init'], cwd=self.tmpdir,
                        check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cli_share_prefixes(self):
        script = str(Path(__file__).resolve().parents[3]
                     / 'plugins' / 'forge' / 'skills'
                     / 'next-spec-id' / 'scripts' / 'scan_spec_ids.py')
        result = subprocess.run(
            [sys.executable, script, 'DES',
             '--project-root', str(self.tmpdir),
             '--share-prefixes', 'ADR,DES'],
            cwd=self.tmpdir, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['next_id'], 'DES-033')
        self.assertEqual(data['shared_with'], ['ADR'])

    def test_cli_without_share_prefixes(self):
        """--share-prefixes 未指定時は従来通りの CLI 出力（後方互換）"""
        script = str(Path(__file__).resolve().parents[3]
                     / 'plugins' / 'forge' / 'skills'
                     / 'next-spec-id' / 'scripts' / 'scan_spec_ids.py')
        result = subprocess.run(
            [sys.executable, script, 'DES', '--project-root', str(self.tmpdir)],
            cwd=self.tmpdir, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['next_id'], 'DES-032')
        self.assertNotIn('shared_with', data)


if __name__ == '__main__':
    unittest.main()
