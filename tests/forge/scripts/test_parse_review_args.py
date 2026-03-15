#!/usr/bin/env python3
"""
parse_review_args.py のテスト

実行:
    python3 -m unittest tests.forge.scripts.test_parse_review_args -v
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / 'plugins' / 'forge' / 'scripts'
sys.path.insert(0, str(SCRIPTS_DIR))

from parse_review_args import parse_review_args


class TestParseReviewArgs(unittest.TestCase):
    """parse_review_args のテスト"""

    def test_type_only(self):
        """種別のみ"""
        result = parse_review_args("code")
        self.assertEqual(result["review_type"], "code")
        self.assertEqual(result["targets"], [])
        self.assertEqual(result["engine"], "codex")
        self.assertEqual(result["auto_count"], 0)
        self.assertFalse(result["auto_critical"])

    def test_type_with_target(self):
        """種別 + 対象"""
        result = parse_review_args("code src/")
        self.assertEqual(result["review_type"], "code")
        self.assertEqual(result["targets"], ["src/"])

    def test_type_with_multiple_targets(self):
        """種別 + 複数対象"""
        result = parse_review_args("code src/ tests/")
        self.assertEqual(result["targets"], ["src/", "tests/"])

    def test_all_types(self):
        """全種別が受け付けられる"""
        for t in ('requirement', 'design', 'code', 'plan', 'generic'):
            result = parse_review_args(t)
            self.assertEqual(result["review_type"], t)

    def test_type_case_insensitive(self):
        """種別は大文字小文字を区別しない"""
        result = parse_review_args("Code")
        self.assertEqual(result["review_type"], "code")

    def test_auto_without_count(self):
        """--auto（カウントなし → 1）"""
        result = parse_review_args("code src/ --auto")
        self.assertEqual(result["auto_count"], 1)
        self.assertFalse(result["auto_critical"])

    def test_auto_with_count(self):
        """--auto N"""
        result = parse_review_args("code src/ --auto 3")
        self.assertEqual(result["auto_count"], 3)

    def test_auto_critical(self):
        """--auto-critical"""
        result = parse_review_args("code src/ --auto-critical")
        self.assertEqual(result["auto_count"], 1)
        self.assertTrue(result["auto_critical"])

    def test_claude_engine(self):
        """--claude"""
        result = parse_review_args("code src/ --claude")
        self.assertEqual(result["engine"], "claude")

    def test_codex_engine(self):
        """--codex（明示指定）"""
        result = parse_review_args("code src/ --codex")
        self.assertEqual(result["engine"], "codex")

    def test_combined_flags(self):
        """複合フラグ"""
        result = parse_review_args("design specs/ --claude --auto 2")
        self.assertEqual(result["review_type"], "design")
        self.assertEqual(result["targets"], ["specs/"])
        self.assertEqual(result["engine"], "claude")
        self.assertEqual(result["auto_count"], 2)

    def test_flags_before_target(self):
        """フラグが対象の前に来るケース"""
        result = parse_review_args("code --claude src/")
        self.assertEqual(result["engine"], "claude")
        self.assertEqual(result["targets"], ["src/"])

    def test_invalid_type(self):
        """不正な種別"""
        with self.assertRaises(ValueError):
            parse_review_args("invalid src/")

    def test_empty_args(self):
        """空の引数"""
        with self.assertRaises(ValueError):
            parse_review_args("")

    def test_whitespace_only(self):
        """空白のみ"""
        with self.assertRaises(ValueError):
            parse_review_args("   ")

    def test_feature_name_as_target(self):
        """Feature 名が対象"""
        result = parse_review_args("requirement login")
        self.assertEqual(result["targets"], ["login"])

    def test_file_path_as_target(self):
        """ファイルパスが対象"""
        result = parse_review_args("design specs/login/design/login_design.md")
        self.assertEqual(result["targets"], ["specs/login/design/login_design.md"])


class TestCLI(unittest.TestCase):
    """CLI インターフェースのテスト"""

    def _run(self, *args):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'parse_review_args.py')] + list(args),
            capture_output=True, text=True, timeout=10,
        )
        return result

    def test_basic_cli(self):
        result = self._run("code", "src/")
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["review_type"], "code")

    def test_auto_cli(self):
        result = self._run("code", "src/", "--auto", "3")
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["auto_count"], 3)

    def test_invalid_cli(self):
        result = self._run("invalid")
        self.assertEqual(result.returncode, 1)

    def test_no_args_cli(self):
        result = self._run()
        self.assertEqual(result.returncode, 1)


if __name__ == '__main__':
    unittest.main()
