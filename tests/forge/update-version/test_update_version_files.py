#!/usr/bin/env python3
"""
update_version_files.py のテスト

実行:
    python3 -m unittest tests.forge.update-version.test_update_version_files -v
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / 'plugins' / 'forge' / 'skills' / 'update-version' / 'scripts'
sys.path.insert(0, str(SCRIPTS_DIR))

from update_version_files import update_version_in_text


class TestSimpleReplace(unittest.TestCase):
    """シンプルな置換テスト"""

    def test_json_quoted(self):
        """JSON のクォート付きバージョン置換"""
        content = '{\n  "version": "999.88.7"\n}'
        result = update_version_in_text(content, "999.88.7", "999.88.8")
        self.assertIn('"999.88.8"', result)
        self.assertNotIn('"999.88.7"', result)

    def test_toml_unquoted(self):
        """TOML のバージョン置換"""
        content = '[package]\nversion = "999.88.7"\n'
        result = update_version_in_text(content, "999.88.7", "999.88.8")
        self.assertIn("999.88.8", result)

    def test_not_found(self):
        """バージョンが見つからない"""
        content = '{"version": "1.0.0"}'
        with self.assertRaises(ValueError):
            update_version_in_text(content, "999.88.7", "999.88.8")

    def test_first_occurrence_only(self):
        """最初の出現のみ置換"""
        content = '"version": "999.88.7"\n"other": "999.88.7"'
        result = update_version_in_text(content, "999.88.7", "999.88.8")
        self.assertEqual(result.count("999.88.8"), 1)
        self.assertEqual(result.count("999.88.7"), 1)

    def test_preserves_formatting(self):
        """JSON フォーマットを保持"""
        content = '{\n  "name": "forge",\n  "version": "999.88.7",\n  "author": "moons"\n}'
        result = update_version_in_text(content, "999.88.7", "999.88.8")
        self.assertIn('"name": "forge"', result)
        self.assertIn('"author": "moons"', result)
        self.assertIn('"999.88.8"', result)


class TestVersionPath(unittest.TestCase):
    """version_path 指定のテスト"""

    def test_top_level_version(self):
        """トップレベルの version フィールド"""
        content = '{\n  "version": "999.88.7"\n}'
        result = update_version_in_text(content, "999.88.7", "999.88.8", version_path="version")
        self.assertIn('"999.88.8"', result)

    def test_nested_path(self):
        """ネストパス package.version"""
        content = '{\n  "package": {\n    "version": "999.88.7"\n  }\n}'
        result = update_version_in_text(content, "999.88.7", "999.88.8", version_path="package.version")
        self.assertIn('"999.88.8"', result)

    def test_path_not_found(self):
        """パスが見つからない"""
        content = '{"name": "test"}'
        with self.assertRaises(ValueError):
            update_version_in_text(content, "999.88.7", "999.88.8", version_path="version")

    def test_path_prefix_version_not_corrupted(self):
        """境界: old=0.6.1 が "0.6.10" を前方一致で破壊しない（見つからず ValueError）"""
        content = '{\n  "version": "0.6.10"\n}'
        with self.assertRaises(ValueError):
            update_version_in_text(content, "0.6.1", "0.6.2", version_path="version")

    def test_path_exact_version_among_prefix(self):
        """境界: 同フィールドに 0.6.10 があっても old=0.6.10 は正しく更新される"""
        content = '{\n  "version": "0.6.10"\n}'
        result = update_version_in_text(content, "0.6.10", "0.6.11", version_path="version")
        self.assertIn('"0.6.11"', result)
        self.assertNotIn('"0.6.10"', result)

    def test_quoted_version_path_normalized(self):
        """Issue #115 提案2: 引用符込みの version_path でも一致する"""
        content = '{\n  "version": "999.88.7"\n}'
        # ダブルクォート込み
        result = update_version_in_text(content, "999.88.7", "999.88.8", version_path='"version"')
        self.assertIn('"999.88.8"', result)
        # シングルクォート込み + 前後空白
        result2 = update_version_in_text(content, "999.88.7", "999.88.8", version_path=" 'version' ")
        self.assertIn('"999.88.8"', result2)

    def test_quoted_nested_version_path_normalized(self):
        """Issue #115 提案2: 引用符込みのネスト version_path でも一致する"""
        content = '{\n  "metadata": {\n    "version": "999.88.7"\n  }\n}'
        result = update_version_in_text(
            content, "999.88.7", "999.88.8", version_path='"metadata.version"'
        )
        self.assertIn('"999.88.8"', result)


class TestChangelogHeader(unittest.TestCase):
    """Issue #115 提案3: version_path: changelog_header のテスト"""

    def test_keep_a_changelog_with_v(self):
        """## [vX.Y.Z] 形式: v と角括弧を保持して version を更新"""
        content = "# Changelog\n\n## [v0.6.9] - 2026-05-27\n\n- entry\n"
        result = update_version_in_text(
            content, "0.6.9", "0.6.10", version_path="changelog_header"
        )
        self.assertIn("## [v0.6.10] - 2026-05-27", result)
        self.assertNotIn("v0.6.9", result)

    def test_keep_a_changelog_no_v(self):
        """## [X.Y.Z] 形式（v なし）"""
        content = "## [0.6.9] - 2026-05-27\n\n- entry\n"
        result = update_version_in_text(
            content, "0.6.9", "0.6.10", version_path="changelog_header"
        )
        self.assertIn("## [0.6.10] - 2026-05-27", result)

    def test_simple_format(self):
        """## X.Y.Z - DATE 形式（simple, 角括弧なし）"""
        content = "# タイトル\n\n## 0.6.9 - 2026-05-27\n\n- entry\n"
        result = update_version_in_text(
            content, "0.6.9", "0.6.10", version_path="changelog_header"
        )
        self.assertIn("## 0.6.10 - 2026-05-27", result)

    def test_old_version_with_v_prefix(self):
        """old_version 側に v が付いていても一致する"""
        content = "## [v0.6.9] - 2026-05-27\n"
        result = update_version_in_text(
            content, "v0.6.9", "0.6.10", version_path="changelog_header"
        )
        self.assertIn("## [v0.6.10]", result)

    def test_only_first_header_updated(self):
        """最初の version 見出しのみ更新する"""
        content = "## [0.6.9] - new\n\n## [0.6.8] - old\n"
        result = update_version_in_text(
            content, "0.6.9", "0.6.10", version_path="changelog_header"
        )
        self.assertIn("## [0.6.10] - new", result)
        self.assertIn("## [0.6.8] - old", result)

    def test_header_not_found(self):
        """該当する version 見出しがない場合は ValueError"""
        content = "# Changelog\n\nno version header here\n"
        with self.assertRaises(ValueError):
            update_version_in_text(
                content, "0.6.9", "0.6.10", version_path="changelog_header"
            )

    def test_prefix_version_not_corrupted(self):
        """境界: old が別バージョンの前方一致部分（0.6.1 vs 0.6.10）を破壊しない"""
        content = "## [0.6.10] - new\n\n## [0.6.1] - old\n"
        result = update_version_in_text(
            content, "0.6.1", "0.6.2", version_path="changelog_header"
        )
        # 0.6.10 見出しは無傷で、0.6.1 見出しのみ 0.6.2 に更新される
        self.assertIn("## [0.6.10] - new", result)
        self.assertIn("## [0.6.2] - old", result)
        self.assertNotIn("0.6.20", result)


class TestFilterPattern(unittest.TestCase):
    """filter パターンのテスト"""

    def test_filter_match(self):
        """フィルタパターンにマッチするブロック内のみ置換"""
        content = '| **forge** | 999.88.7 | desc |\n| **anvil** | 888.77.6 | desc |'
        result = update_version_in_text(content, "999.88.7", "999.88.8", filter_pattern="**forge**")
        self.assertIn("999.88.8", result)
        self.assertIn("888.77.6", result)

    def test_filter_no_match(self):
        """フィルタパターンにマッチしない"""
        content = '| **anvil** | 888.77.6 | desc |'
        with self.assertRaises(ValueError):
            update_version_in_text(content, "999.88.7", "999.88.8", filter_pattern="**forge**")

    def test_filter_max_distance_exceeded(self):
        """max_distance 超過時はブロックがリセットされバージョン未発見エラー"""
        # filter 行から 11 行以上離れた位置にバージョンがある場合（max_distance=10）
        lines = ['| **forge** | header |']
        lines += ['filler line'] * 11
        lines += ['999.88.7']
        content = '\n'.join(lines)
        with self.assertRaises(ValueError):
            update_version_in_text(content, "999.88.7", "999.88.8", filter_pattern="**forge**")

    def test_filter_version_on_different_line(self):
        """filter 行とバージョン行が異なる行（JSON ブロック内探索パターン）"""
        content = (
            '{\n'
            '  "plugins": [\n'
            '    {\n'
            '      "name": "forge",\n'
            '      "description": "tools",\n'
            '      "version": "999.88.7"\n'
            '    }\n'
            '  ]\n'
            '}'
        )
        result = update_version_in_text(
            content, "999.88.7", "999.88.8", filter_pattern='"name": "forge"'
        )
        self.assertIn('"999.88.8"', result)
        self.assertNotIn('"999.88.7"', result)

    def test_filter_consecutive_blocks_first_no_version(self):
        """2つの filter ブロックが連続し、1つ目にはバージョンがない場合"""
        content = (
            '{\n'
            '  "name": "anvil",\n'
            '  "description": "other tool"\n'
            '},\n'
            '{\n'
            '  "name": "forge",\n'
            '  "version": "999.88.7"\n'
            '}'
        )
        result = update_version_in_text(
            content, "999.88.7", "999.88.8", filter_pattern='"name": "forge"'
        )
        self.assertIn('"999.88.8"', result)

    def test_filter_within_max_distance(self):
        """max_distance ちょうどの行数でバージョンが見つかる場合"""
        lines = ['| **forge** | header |']
        lines += ['filler line'] * 9  # 9行のフィラー（filter 行から10行目にバージョン）
        lines += ['999.88.7']
        content = '\n'.join(lines)
        result = update_version_in_text(
            content, "999.88.7", "999.88.8", filter_pattern="**forge**"
        )
        self.assertIn("999.88.8", result)


class TestVersionPathToml(unittest.TestCase):
    """TOML 形式の path モードテスト"""

    def test_toml_top_level_version(self):
        """TOML のトップレベル version フィールド"""
        content = '[package]\nname = "my-crate"\nversion = "999.88.7"\n'
        result = update_version_in_text(
            content, "999.88.7", "999.88.8", version_path="version"
        )
        self.assertIn('"999.88.8"', result)
        self.assertNotIn('999.88.7', result)

    def test_toml_preserves_surrounding(self):
        """TOML の version 置換で前後のフィールドが保持される"""
        content = '[package]\nname = "my-crate"\nversion = "999.88.7"\nedition = "2021"\n'
        result = update_version_in_text(
            content, "999.88.7", "999.88.8", version_path="version"
        )
        self.assertIn('name = "my-crate"', result)
        self.assertIn('edition = "2021"', result)
        self.assertIn('"999.88.8"', result)


class TestEmptyVersionValidation(unittest.TestCase):
    """空文字列バリデーションのテスト"""

    def test_empty_old_version(self):
        """old_version が空文字列の場合 ValueError"""
        with self.assertRaises(ValueError) as ctx:
            update_version_in_text('{"version": "1.0.0"}', "", "1.0.1")
        self.assertIn("old_version", str(ctx.exception))

    def test_empty_new_version(self):
        """new_version が空文字列の場合 ValueError"""
        with self.assertRaises(ValueError) as ctx:
            update_version_in_text('{"version": "1.0.0"}', "1.0.0", "")
        self.assertIn("new_version", str(ctx.exception))


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
        content = '{"version": "999.88.7"}'
        result = self._run(content, "999.88.7", "999.88.8")
        self.assertEqual(result.returncode, 0)
        self.assertIn('"999.88.8"', result.stdout)
        status = json.loads(result.stderr)
        self.assertEqual(status["status"], "ok")

    def test_not_found_cli(self):
        content = '{"version": "1.0.0"}'
        result = self._run(content, "999.88.7", "999.88.8")
        self.assertEqual(result.returncode, 1)

    def test_optional_pattern_not_found_cli(self):
        """--optional でパターン未マッチ時に exit 0 + status: skipped"""
        content = '| **anvil** | 888.77.6 | desc |'
        result = self._run(content, "999.88.7", "999.88.8", "--filter", "**forge**", "--optional")
        self.assertEqual(result.returncode, 0)
        # stdout は空（Write すべき内容がない）
        self.assertEqual(result.stdout, "")
        status = json.loads(result.stderr)
        self.assertEqual(status["status"], "skipped")

    def test_optional_not_set_pattern_not_found_cli(self):
        """--optional なしでパターン未マッチ時は従来通り exit 1"""
        content = '| **anvil** | 888.77.6 | desc |'
        result = self._run(content, "999.88.7", "999.88.8", "--filter", "**forge**")
        self.assertEqual(result.returncode, 1)

    def test_file_not_found_cli(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'update_version_files.py'),
             '/nonexistent.json', '999.88.7', '999.88.8'],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 1)

    def test_version_path_cli(self):
        content = '{"version": "999.88.7"}'
        result = self._run(content, "999.88.7", "999.88.8", "--version-path", "version")
        self.assertEqual(result.returncode, 0)
        self.assertIn('"999.88.8"', result.stdout)


if __name__ == '__main__':
    unittest.main()
