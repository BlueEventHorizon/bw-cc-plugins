#!/usr/bin/env python3
"""
update_version_files.py のテスト

実行:
    python3 -m unittest tests.forge.bump.test_update_version_files -v
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / 'plugins' / 'forge' / 'skills' / 'bump' / 'scripts'
sys.path.insert(0, str(SCRIPTS_DIR))

from update_version_files import update_version_in_text


class TestSimpleReplace(unittest.TestCase):
    """シンプルな置換テスト"""

    def test_json_quoted(self):
        """JSON のクォート付きバージョン置換"""
        content = '{\n  "version": "0.0.19"\n}'
        result = update_version_in_text(content, "0.0.19", "0.0.20")
        self.assertIn('"0.0.20"', result)
        self.assertNotIn('"0.0.19"', result)

    def test_toml_unquoted(self):
        """TOML のバージョン置換"""
        content = '[package]\nversion = "0.0.19"\n'
        result = update_version_in_text(content, "0.0.19", "0.0.20")
        self.assertIn("0.0.20", result)

    def test_not_found(self):
        """バージョンが見つからない"""
        content = '{"version": "1.0.0"}'
        with self.assertRaises(ValueError):
            update_version_in_text(content, "0.0.19", "0.0.20")

    def test_first_occurrence_only(self):
        """最初の出現のみ置換"""
        content = '"version": "0.0.19"\n"other": "0.0.19"'
        result = update_version_in_text(content, "0.0.19", "0.0.20")
        self.assertEqual(result.count("0.0.20"), 1)
        self.assertEqual(result.count("0.0.19"), 1)

    def test_preserves_formatting(self):
        """JSON フォーマットを保持"""
        content = '{\n  "name": "forge",\n  "version": "0.0.19",\n  "author": "moons"\n}'
        result = update_version_in_text(content, "0.0.19", "0.0.20")
        self.assertIn('"name": "forge"', result)
        self.assertIn('"author": "moons"', result)
        self.assertIn('"0.0.20"', result)


class TestVersionPath(unittest.TestCase):
    """version_path 指定のテスト"""

    def test_top_level_version(self):
        """トップレベルの version フィールド"""
        content = '{\n  "version": "0.0.19"\n}'
        result = update_version_in_text(content, "0.0.19", "0.0.20", version_path="version")
        self.assertIn('"0.0.20"', result)

    def test_nested_path(self):
        """ネストパス package.version"""
        content = '{\n  "package": {\n    "version": "0.0.19"\n  }\n}'
        result = update_version_in_text(content, "0.0.19", "0.0.20", version_path="package.version")
        self.assertIn('"0.0.20"', result)

    def test_path_not_found(self):
        """パスが見つからない"""
        content = '{"name": "test"}'
        with self.assertRaises(ValueError):
            update_version_in_text(content, "0.0.19", "0.0.20", version_path="version")


class TestFilterPattern(unittest.TestCase):
    """filter パターンのテスト"""

    def test_filter_match(self):
        """フィルタパターンにマッチするブロック内のみ置換"""
        content = '| **forge** | 0.0.19 | desc |\n| **anvil** | 0.0.4 | desc |'
        result = update_version_in_text(content, "0.0.19", "0.0.20", filter_pattern="**forge**")
        self.assertIn("0.0.20", result)
        self.assertIn("0.0.4", result)

    def test_filter_no_match(self):
        """フィルタパターンにマッチしない"""
        content = '| **anvil** | 0.0.4 | desc |'
        with self.assertRaises(ValueError):
            update_version_in_text(content, "0.0.19", "0.0.20", filter_pattern="**forge**")


class TestCLI(unittest.TestCase):
    """CLI インターフェースのテスト"""

    def _run(self, content, *args):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            f.write(content)
            f.flush()
            tmp_path = f.name

        try:
            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / 'update_version_files.py'), tmp_path] + list(args),
                capture_output=True, text=True, timeout=10,
            )
            return result
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_basic_cli(self):
        content = '{"version": "0.0.19"}'
        result = self._run(content, "0.0.19", "0.0.20")
        self.assertEqual(result.returncode, 0)
        self.assertIn('"0.0.20"', result.stdout)
        status = json.loads(result.stderr)
        self.assertEqual(status["status"], "ok")

    def test_not_found_cli(self):
        content = '{"version": "1.0.0"}'
        result = self._run(content, "0.0.19", "0.0.20")
        self.assertEqual(result.returncode, 1)

    def test_file_not_found_cli(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'update_version_files.py'),
             '/nonexistent.json', '0.0.19', '0.0.20'],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 1)

    def test_version_path_cli(self):
        content = '{"version": "0.0.19"}'
        result = self._run(content, "0.0.19", "0.0.20", "--version-path", "version")
        self.assertEqual(result.returncode, 0)
        self.assertIn('"0.0.20"', result.stdout)


if __name__ == '__main__':
    unittest.main()
