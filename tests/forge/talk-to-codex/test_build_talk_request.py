#!/usr/bin/env python3
"""
build_talk_request.py のテスト

`tests/forge/msg-review/test_build_review_request.py` のパターン（importlib 直接
ロードで `build_body()` を単体テスト、`main()` は subprocess 経由の CLI 統合テスト）
を踏襲する。

実行:
  python3 -m unittest tests.forge.talk-to-codex.test_build_talk_request -v
"""

import importlib.util
import re
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "skills" / "talk-to-codex" / "scripts" / "build_talk_request.py"
)

_spec = importlib.util.spec_from_file_location("talk_to_codex_build_talk_request", _SCRIPT_PATH)
build_talk_request = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_talk_request)


def _run_cli(argv):
    result = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH)] + argv,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


class BuildBodyTest(unittest.TestCase):
    def test_header_is_first_line(self):
        body = build_talk_request.build_body("こんにちは", "topic-abc")
        self.assertEqual(body.splitlines()[0], "[msg-talk] topic_id=topic-abc")

    def test_message_follows_header_with_blank_line(self):
        body = build_talk_request.build_body("自由記述の相談内容", "topic-abc")
        self.assertEqual(body, "[msg-talk] topic_id=topic-abc\n\n自由記述の相談内容\n")

    def test_header_matches_thread_filter_regex_contract(self):
        """thread_filter.py 側の header_regex がこの本文の1行目から topic_id を
        取り出せることを確認する（実装間の契約が壊れていないことの回帰）。
        """
        body = build_talk_request.build_body("hi", "abc-123")
        match = re.search(build_talk_request.TOPIC_ID_HEADER_RE_TEMPLATE, body.splitlines()[0])
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "abc-123")

    def test_rejects_topic_id_with_newline(self):
        with self.assertRaises(ValueError):
            build_talk_request.build_body("hi", "bad\nid")

    def test_rejects_topic_id_containing_space(self):
        """実 Codex レビューで発見の回帰: 空白のみ拒否していなかった場合、
        `topic_id=topic 1` は header_regex の `(\\S+)` が空白手前で切り詰められ、
        継続会話のスレッド判定が静かに失敗する。
        """
        with self.assertRaises(ValueError):
            build_talk_request.build_body("hi", "topic 1")

    def test_rejects_topic_id_containing_tab(self):
        with self.assertRaises(ValueError):
            build_talk_request.build_body("hi", "topic\t1")

    def test_rejects_empty_topic_id(self):
        with self.assertRaises(ValueError):
            build_talk_request.build_body("hi", "")

    def test_multiline_message_preserved_as_is(self):
        body = build_talk_request.build_body("1行目\n2行目", "topic-xyz")
        self.assertEqual(body, "[msg-talk] topic_id=topic-xyz\n\n1行目\n2行目\n")


class MainCliTest(unittest.TestCase):
    def test_generates_new_topic_id_when_omitted(self):
        exit_code, stdout, _ = _run_cli(["--message", "テストメッセージ"])
        self.assertEqual(exit_code, 0)
        first_line = stdout.splitlines()[0]
        match = re.match(r"^\[msg-talk\] topic_id=(\S+)$", first_line)
        self.assertIsNotNone(match)
        # uuid4().hex は 32桁の16進文字列
        self.assertTrue(re.fullmatch(r"[0-9a-f]{32}", match.group(1)))

    def test_uses_given_topic_id_when_provided(self):
        fixed_id = uuid.uuid4().hex
        exit_code, stdout, _ = _run_cli(["--message", "続きの相談です", "--topic-id", fixed_id])
        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.splitlines()[0], f"[msg-talk] topic_id={fixed_id}")

    def test_topic_id_with_space_returns_exit_code_1(self):
        exit_code, stdout, stderr = _run_cli(
            ["--message", "続きの相談です", "--topic-id", "topic 1"]
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")

    def test_empty_message_returns_exit_code_1(self):
        exit_code, stdout, stderr = _run_cli(["--message", "   "])
        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("空です", stderr)

    def test_missing_message_argument_returns_nonzero(self):
        result = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH)],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
