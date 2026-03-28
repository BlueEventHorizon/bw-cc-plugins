#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLAUDE_PLUGIN_ROOT / CLAUDE_PROJECT_DIR 環境変数テスト。

get_project_root() の3段階フォールバック検証:
1. CLAUDE_PROJECT_DIR 設定時: そのパスを返す
2. CLAUDE_PROJECT_DIR 未設定 + CWD にプロジェクト: CWD 遡り探索で見つかる
3. CLAUDE_PROJECT_DIR 未設定 + CWD に .git/.claude なし: RuntimeError
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# テスト対象モジュールの import
SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'plugins', 'doc-advisor', 'scripts'
)
sys.path.insert(0, os.path.abspath(SCRIPTS_DIR))

import toc_utils


class TestGetProjectRootStage1(unittest.TestCase):
    """Stage 1: CLAUDE_PROJECT_DIR 設定時のテスト"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmpdir, '.git'))

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_claude_project_dir_set(self):
        """CLAUDE_PROJECT_DIR 設定時はそのパスを返す"""
        with patch.dict(os.environ, {'CLAUDE_PROJECT_DIR': self.tmpdir}):
            result = toc_utils.get_project_root()
        self.assertEqual(result, Path(self.tmpdir))

    def test_claude_project_dir_empty_string_fallback(self):
        """CLAUDE_PROJECT_DIR が空文字列 → Stage 2 にフォールバック"""
        project_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(project_dir, '.git'))
        try:
            with patch.dict(os.environ, {'CLAUDE_PROJECT_DIR': ''}):
                with patch.object(Path, 'cwd', return_value=Path(project_dir)):
                    result = toc_utils.get_project_root()
            # Stage 2 のCWD遡り探索で見つかる
            self.assertEqual(result, Path(project_dir).resolve())
        finally:
            shutil.rmtree(project_dir)

    def test_claude_project_dir_nonexistent_path_fallback(self):
        """CLAUDE_PROJECT_DIR が存在しないパス → Stage 2 にフォールバック"""
        project_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(project_dir, '.git'))
        try:
            nonexistent = os.path.join(self.tmpdir, 'nonexistent_path_xyz')
            with patch.dict(os.environ, {'CLAUDE_PROJECT_DIR': nonexistent}):
                with patch.object(Path, 'cwd', return_value=Path(project_dir)):
                    result = toc_utils.get_project_root()
            self.assertEqual(result, Path(project_dir).resolve())
        finally:
            shutil.rmtree(project_dir)


class TestGetProjectRootStage2(unittest.TestCase):
    """Stage 2: CWD 遡り探索のテスト"""

    def test_cwd_with_git_dir(self):
        """CWD に .git がある場合、そのディレクトリを返す"""
        tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmpdir, '.git'))
        try:
            with patch.dict(os.environ, {}, clear=False):
                # CLAUDE_PROJECT_DIR を確実に未設定にする
                os.environ.pop('CLAUDE_PROJECT_DIR', None)
                with patch.object(Path, 'cwd', return_value=Path(tmpdir)):
                    result = toc_utils.get_project_root()
            self.assertEqual(result, Path(tmpdir).resolve())
        finally:
            shutil.rmtree(tmpdir)

    def test_cwd_with_claude_dir(self):
        """CWD に .claude がある場合、そのディレクトリを返す"""
        tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmpdir, '.claude'))
        try:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop('CLAUDE_PROJECT_DIR', None)
                with patch.object(Path, 'cwd', return_value=Path(tmpdir)):
                    result = toc_utils.get_project_root()
            self.assertEqual(result, Path(tmpdir).resolve())
        finally:
            shutil.rmtree(tmpdir)

    def test_cwd_subdirectory_finds_parent(self):
        """CWD がサブディレクトリの場合、親を遡って見つける"""
        tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmpdir, '.git'))
        subdir = os.path.join(tmpdir, 'src', 'deep')
        os.makedirs(subdir)
        try:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop('CLAUDE_PROJECT_DIR', None)
                with patch.object(Path, 'cwd', return_value=Path(subdir)):
                    result = toc_utils.get_project_root()
            self.assertEqual(result, Path(tmpdir).resolve())
        finally:
            shutil.rmtree(tmpdir)


class TestGetProjectRootStage3(unittest.TestCase):
    """Stage 3: プロジェクトルートが見つからない場合のテスト"""

    def test_no_project_markers_raises_error(self):
        """CWD に .git/.claude なし + CLAUDE_PROJECT_DIR 未設定 → RuntimeError"""
        tmpdir = tempfile.mkdtemp()
        try:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop('CLAUDE_PROJECT_DIR', None)
                with patch.object(Path, 'cwd', return_value=Path(tmpdir)):
                    with self.assertRaises(RuntimeError) as ctx:
                        toc_utils.get_project_root()
            self.assertIn('Project root not found', str(ctx.exception))
        finally:
            shutil.rmtree(tmpdir)


class TestFindConfigFile(unittest.TestCase):
    """find_config_file() のテスト"""

    def test_finds_doc_structure(self):
        """.doc_structure.yaml がプロジェクトルートに存在する場合"""
        tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmpdir, '.git'))
        ds_path = os.path.join(tmpdir, '.doc_structure.yaml')
        with open(ds_path, 'w') as f:
            f.write('rules:\n  root_dirs:\n    - rules/\n')
        try:
            with patch.dict(os.environ, {'CLAUDE_PROJECT_DIR': tmpdir}):
                result = toc_utils.find_config_file()
            self.assertEqual(result, Path(tmpdir) / '.doc_structure.yaml')
        finally:
            shutil.rmtree(tmpdir)

    def test_not_found_raises_error(self):
        """.doc_structure.yaml が存在しない場合は FileNotFoundError"""
        tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmpdir, '.git'))
        try:
            with patch.dict(os.environ, {'CLAUDE_PROJECT_DIR': tmpdir}):
                with self.assertRaises(FileNotFoundError):
                    toc_utils.find_config_file()
        finally:
            shutil.rmtree(tmpdir)


if __name__ == '__main__':
    unittest.main()
