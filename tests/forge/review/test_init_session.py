#!/usr/bin/env python3
"""review/scripts/init_session.py のテスト。

後処理撤去後の wrapper は session.yaml を一切触らず、session_manager.py init に
透過するだけの薄いラッパーである（DES-024 §2.3 / DES-028 §4.1）。
本テストは subprocess を mock し、組み立てられる引数（透過内容）を検証する:

  - 位置引数 (review_type / engine / auto_count) → session_manager の init flags
  - --current-cycle 0 のハードコード
  - --files (空白 / カンマ区切り) を **常に** session_manager に透過する
    （カンマ分割・session.yaml への保存は session_manager 側の責務。
     その内容検証は tests/forge/scripts/test_session_manager.py が担う）
  - --section は完全撤廃。argparse が "unrecognized arguments" として reject する
"""

import sys
import unittest

from tests.forge.wrapper_helpers import (
    SESSION_MANAGER,
    assert_exit_code_transparent,
    assert_init_session_command,
    assert_low_level,
    assert_transparent_subprocess_kwargs,
    command_from_mock,
    invoke_with_mocked_run,
    load_wrapper,
    wrapper_path,
)
from unittest import mock

EXPECTED_SKILL = 'review'
WRAPPER_PATH = wrapper_path(EXPECTED_SKILL, "init_session.py")


class TestInitSessionWrapper(unittest.TestCase):
    """位置引数 + --files の解析と session_manager 透過を検証する。"""

    def setUp(self):
        self.wrapper = load_wrapper(WRAPPER_PATH, '_init_session_review')

    def _cmd(self, argv):
        """wrapper を mock 実行し、session_manager へ渡す引数列を返す。"""
        rc, mock_run = invoke_with_mocked_run(self.wrapper, argv=argv)
        self.assertEqual(rc, 0)
        return command_from_mock(mock_run)

    # ------------------------------------------------------------------
    # 基本: hardcode 値 / 透過契約
    # ------------------------------------------------------------------

    def test_skill_hardcoded(self):
        self.assertEqual(self.wrapper.SKILL, EXPECTED_SKILL)

    def test_low_level_path_points_session_manager(self):
        assert_low_level(self, self.wrapper, SESSION_MANAGER)

    def test_positional_args_mapped_to_flags(self):
        cmd = self._cmd(['init_session.py', 'code', 'codex', '3'])
        assert_init_session_command(
            self,
            cmd,
            EXPECTED_SKILL,
            {
                '--review-type': 'code',
                '--engine': 'codex',
                '--auto-count': '3',
                '--current-cycle': '0',
            },
        )

    def test_exit_code_transparent(self):
        assert_exit_code_transparent(
            self,
            self.wrapper,
            lambda: ['init_session.py', 'code', 'codex', '3'],
        )

    def test_subprocess_transparent(self):
        """capture せず exit/stdout/stderr を透過する（DES-024 §2.3）。"""
        _rc, mock_run = invoke_with_mocked_run(
            self.wrapper, argv=['init_session.py', 'code', 'codex', '3']
        )
        assert_transparent_subprocess_kwargs(self, mock_run)

    # ------------------------------------------------------------------
    # --files の透過（内容検証は session_manager テストに委譲）
    # ------------------------------------------------------------------

    def test_files_always_passed_even_when_unspecified(self):
        """--files 未指定でも空の --files を末尾に透過する（files: [] 記録のため）。"""
        cmd = self._cmd(['init_session.py', 'code', 'codex', '3'])
        self.assertIn('--files', cmd)
        # 末尾に置き、後続値が無い（空 list として session_manager が解釈する）
        self.assertEqual(cmd[-1], '--files')

    def test_files_single_value_passed_through(self):
        cmd = self._cmd(
            ['init_session.py', 'design', 'codex', '0', '--files', 'docs/a.md']
        )
        idx = cmd.index('--files')
        self.assertEqual(cmd[idx + 1:], ['docs/a.md'])

    def test_files_multiple_space_separated_passed_through(self):
        cmd = self._cmd(
            ['init_session.py', 'design', 'codex', '0',
             '--files', 'docs/a.md', 'docs/b.md']
        )
        idx = cmd.index('--files')
        self.assertEqual(cmd[idx + 1:], ['docs/a.md', 'docs/b.md'])

    def test_files_comma_passed_through_unsplit(self):
        """カンマ区切りは分割せずそのまま透過する（分割は session_manager の責務）。"""
        cmd = self._cmd(
            ['init_session.py', 'design', 'codex', '0', '--files', 'docs/a.md,docs/b.md']
        )
        idx = cmd.index('--files')
        self.assertEqual(cmd[idx + 1:], ['docs/a.md,docs/b.md'])

    # ------------------------------------------------------------------
    # --section の完全撤廃
    # ------------------------------------------------------------------

    def test_section_flag_rejected(self):
        """--section は DES-028 で完全撤廃。argparse が SystemExit で reject する。"""
        with mock.patch.object(sys, "argv",
                               ['init_session.py', 'code', 'codex', '3',
                                '--section', '4.1']):
            with mock.patch.object(self.wrapper.subprocess, "run") as mock_run:
                with self.assertRaises(SystemExit) as ctx:
                    self.wrapper.main()
                # session_manager は呼ばれてはならない
                mock_run.assert_not_called()
        # argparse の unrecognized-args は exit code 2
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
