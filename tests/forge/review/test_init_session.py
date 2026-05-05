#!/usr/bin/env python3
"""review/scripts/init_session.py の薄い wrapper テスト。"""

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

EXPECTED_SKILL = 'review'
WRAPPER_PATH = wrapper_path(EXPECTED_SKILL, "init_session.py")


class TestInitSessionWrapper(unittest.TestCase):
    """位置引数 {review_type} {engine} {auto_count} を init flags に変換する。"""

    def setUp(self):
        self.wrapper = load_wrapper(WRAPPER_PATH, '_init_session_review')

    def test_skill_hardcoded(self):
        self.assertEqual(self.wrapper.SKILL, EXPECTED_SKILL)

    def test_low_level_path_points_session_manager(self):
        assert_low_level(self, self.wrapper, SESSION_MANAGER)

    def test_positional_args_mapped_to_flags(self):
        rc, mock_run = invoke_with_mocked_run(self.wrapper, argv=['init_session.py', 'code', 'codex', '3'])
        self.assertEqual(rc, 0)
        assert_init_session_command(
            self,
            command_from_mock(mock_run),
            EXPECTED_SKILL,
            {'--review-type': 'code', '--engine': 'codex', '--auto-count': '3', '--current-cycle': '0'},
        )
        assert_transparent_subprocess_kwargs(self, mock_run)

    def test_exit_code_transparent(self):
        assert_exit_code_transparent(self, self.wrapper, lambda: ['init_session.py', 'code', 'codex', '3'])


if __name__ == "__main__":
    unittest.main()
