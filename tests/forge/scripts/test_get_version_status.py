#!/usr/bin/env python3
"""
get_version_status.py のテスト

YAML パーサー、バージョン取得、バンプ分類をテストする。
標準ライブラリのみ使用。

実行:
  python3 -m unittest tests.forge.scripts.test_get_version_status -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# テスト対象モジュールへのパスを追加
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "plugins" / "forge" / "scripts"))

from get_version_status import (
    _parse_version_config_yaml,
    get_version_from_json_content,
    get_version_from_text_content,
    get_version_from_changelog_header,
    extract_version_from_content,
    resolve_version_path,
    classify_bump,
    _pattern_to_regex,
    match_any_pattern,
)

_TEST_TEMP_BASE = Path(__file__).parent / ".temp"


class TestParseVersionConfigYaml(unittest.TestCase):
    """_parse_version_config_yaml のテスト"""

    def test_parse_single_target(self):
        """単一 target を正しくパースできる"""
        yaml = """
targets:
  - name: forge
    version_file: plugins/forge/.claude-plugin/plugin.json
    version_path: version
"""
        result = _parse_version_config_yaml(yaml)
        self.assertEqual(len(result["targets"]), 1)
        target = result["targets"][0]
        self.assertEqual(target["name"], "forge")
        self.assertEqual(target["version_file"], "plugins/forge/.claude-plugin/plugin.json")
        self.assertEqual(target["version_path"], "version")

    def test_parse_multiple_targets(self):
        """複数 target を正しくパースできる"""
        yaml = """
targets:
  - name: marketplace
    version_file: .claude-plugin/marketplace.json
    version_path: metadata.version
  - name: forge
    version_file: plugins/forge/.claude-plugin/plugin.json
    version_path: version
  - name: anvil
    version_file: plugins/anvil/.claude-plugin/plugin.json
    version_path: version
"""
        result = _parse_version_config_yaml(yaml)
        names = [t["name"] for t in result["targets"]]
        self.assertEqual(names, ["marketplace", "forge", "anvil"])

    def test_parse_sync_files(self):
        """sync_files を正しくパースできる"""
        yaml = """
targets:
  - name: forge
    version_file: plugins/forge/.claude-plugin/plugin.json
    version_path: version
    sync_files:
      - path: README.md
        filter: '| **forge**'
      - path: README_en.md
        filter: '| **forge**'
        optional: true
"""
        # 上記 YAML の sync_files 内 indent 確認:
        # sync_files: (indent 4), - path: (indent 6), filter: (indent 8)
        result = _parse_version_config_yaml(yaml)
        target = result["targets"][0]
        self.assertEqual(len(target["sync_files"]), 2)
        self.assertEqual(target["sync_files"][0]["path"], "README.md")
        self.assertEqual(target["sync_files"][1]["path"], "README_en.md")
        self.assertEqual(target["sync_files"][1]["optional"], "true")

    def test_parse_changelog_section(self):
        """changelog セクションを正しくパースできる"""
        yaml = """
targets:
  - name: forge
    version_file: plugins/forge/.claude-plugin/plugin.json
    version_path: version

changelog:
  file: CHANGELOG.md
  format: keep-a-changelog
"""
        result = _parse_version_config_yaml(yaml)
        self.assertEqual(result["changelog"]["file"], "CHANGELOG.md")
        self.assertEqual(result["changelog"]["format"], "keep-a-changelog")

    def test_parse_git_section(self):
        """git セクションを正しくパースできる"""
        yaml = """
targets:
  - name: forge
    version_file: plugins/forge/.claude-plugin/plugin.json
    version_path: version

git:
  auto_commit: true
  auto_tag: false
"""
        result = _parse_version_config_yaml(yaml)
        self.assertEqual(result["git"]["auto_commit"], "true")
        self.assertEqual(result["git"]["auto_tag"], "false")

    def test_parse_skips_comments(self):
        """コメント行をスキップする"""
        yaml = """
# version_config_version: 1.0

targets:
  # これはコメント
  - name: forge
    version_file: plugins/forge/.claude-plugin/plugin.json
    version_path: version
"""
        result = _parse_version_config_yaml(yaml)
        self.assertEqual(len(result["targets"]), 1)
        self.assertEqual(result["targets"][0]["name"], "forge")

    def test_parse_empty_yaml(self):
        """空の YAML で空の結果を返す"""
        result = _parse_version_config_yaml("")
        self.assertEqual(result["targets"], [])
        self.assertEqual(result["changelog"], {})
        self.assertEqual(result["git"], {})

    def test_parse_target_without_version_path(self):
        """version_path がない target も name/version_file を取得できる"""
        yaml = """
targets:
  - name: sample
    version_file: plugins/sample/.claude-plugin/plugin.json
"""
        result = _parse_version_config_yaml(yaml)
        target = result["targets"][0]
        self.assertEqual(target["name"], "sample")
        self.assertNotIn("version_path", target)


class TestResolveVersionPath(unittest.TestCase):
    """resolve_version_path のテスト"""

    def test_simple_key(self):
        """単純なキーでバージョンを取得できる"""
        data = {"version": "1.2.3"}
        self.assertEqual(resolve_version_path(data, "version"), "1.2.3")

    def test_nested_key(self):
        """ドット区切りのネストしたキーでバージョンを取得できる"""
        data = {"metadata": {"version": "0.1.5"}}
        self.assertEqual(resolve_version_path(data, "metadata.version"), "0.1.5")

    def test_missing_key(self):
        """存在しないキーで None を返す"""
        data = {"version": "1.0.0"}
        self.assertIsNone(resolve_version_path(data, "metadata.version"))

    def test_missing_nested_key(self):
        """中間キーが存在しない場合に None を返す"""
        data = {}
        self.assertIsNone(resolve_version_path(data, "a.b.c"))


class TestGetVersionFromJsonContent(unittest.TestCase):
    """get_version_from_json_content のテスト"""

    def test_simple_version(self):
        """単純な JSON からバージョンを取得できる"""
        content = json.dumps({"version": "0.0.29"})
        result = get_version_from_json_content(content, "version")
        self.assertEqual(result, "0.0.29")

    def test_nested_version(self):
        """ネストした JSON からバージョンを取得できる"""
        content = json.dumps({"metadata": {"version": "0.1.1"}})
        result = get_version_from_json_content(content, "metadata.version")
        self.assertEqual(result, "0.1.1")

    def test_invalid_json(self):
        """不正な JSON で None を返す"""
        result = get_version_from_json_content("not json", "version")
        self.assertIsNone(result)

    def test_empty_string(self):
        """空文字列で None を返す"""
        result = get_version_from_json_content("", "version")
        self.assertIsNone(result)


class TestTextAndChangelogExtraction(unittest.TestCase):
    """Issue #115 提案3・4: 非 JSON / CHANGELOG からの version 抽出"""

    def test_text_swift_constant(self):
        """Swift 定数 let version = "1.2.3" から抽出できる"""
        content = 'let version = "1.2.3"\n'
        self.assertEqual(get_version_from_text_content(content, "version"), "1.2.3")

    def test_text_toml(self):
        """TOML version = "1.2.3" から抽出できる"""
        content = '[package]\nversion = "0.6.9"\n'
        self.assertEqual(get_version_from_text_content(content, "version"), "0.6.9")

    def test_text_nested_field_uses_last_key(self):
        """ネストパスは最終キー名で照合する"""
        content = 'appVersion: 2.0.1\n'
        self.assertEqual(get_version_from_text_content(content, "meta.appVersion"), "2.0.1")

    def test_text_not_found(self):
        content = "no version anywhere\n"
        self.assertIsNone(get_version_from_text_content(content, "version"))

    def test_text_skips_comment_line(self):
        """コメント行の version: X.Y.Z を誤抽出せず、定義行から抽出する"""
        content = '// minimum supported version: 9.9.9\nlet version = "1.2.3"\n'
        self.assertEqual(get_version_from_text_content(content, "version"), "1.2.3")

    def test_text_skips_hash_comment(self):
        """# コメントもスキップする"""
        content = "# old version: 0.0.1\nversion = '2.0.0'\n"
        self.assertEqual(get_version_from_text_content(content, "version"), "2.0.0")

    def test_changelog_header_keep_a_changelog(self):
        content = "# Changelog\n\n## [0.6.9] - 2026-05-27\n"
        self.assertEqual(get_version_from_changelog_header(content), "0.6.9")

    def test_changelog_header_with_v(self):
        content = "## [v0.6.9] - 2026-05-27\n"
        self.assertEqual(get_version_from_changelog_header(content), "v0.6.9")

    def test_changelog_header_simple(self):
        content = "# タイトル\n\n## 0.6.9 - 2026-05-27\n"
        self.assertEqual(get_version_from_changelog_header(content), "0.6.9")

    def test_changelog_header_returns_first_of_many(self):
        """複数 version 見出しがある場合は最初（最新）を返す"""
        content = "## [0.6.10] - new\n\n## [0.6.9] - old\n"
        self.assertEqual(get_version_from_changelog_header(content), "0.6.10")

    def test_extract_dispatches_changelog_header(self):
        content = "## [0.6.9] - 2026-05-27\n"
        self.assertEqual(
            extract_version_from_content(content, "changelog_header"), "0.6.9"
        )

    def test_extract_json_first_then_text(self):
        """JSON で取れればそれを使い、取れなければテキストにフォールバック"""
        self.assertEqual(
            extract_version_from_content('{"version": "1.0.0"}', "version"), "1.0.0"
        )
        self.assertEqual(
            extract_version_from_content('let version = "2.0.0"', "version"), "2.0.0"
        )

    def test_extract_quoted_version_path_normalized(self):
        """Issue #115 提案2: 引用符込み version_path でも抽出できる"""
        self.assertEqual(
            extract_version_from_content('{"version": "1.0.0"}', '"version"'), "1.0.0"
        )

    def test_extract_none_content(self):
        self.assertIsNone(extract_version_from_content(None, "version"))


class TestClassifyBump(unittest.TestCase):
    """classify_bump のテスト"""

    def test_same_version(self):
        self.assertEqual(classify_bump("1.0.0", "1.0.0"), "same")

    def test_patch_bump(self):
        self.assertEqual(classify_bump("0.0.1", "0.0.2"), "patch")

    def test_minor_bump(self):
        self.assertEqual(classify_bump("0.0.9", "0.1.0"), "minor")

    def test_major_bump(self):
        self.assertEqual(classify_bump("0.9.9", "1.0.0"), "major")

    def test_downgrade(self):
        self.assertEqual(classify_bump("1.0.0", "0.9.9"), "downgrade")

    def test_none_base(self):
        """base が None のとき unknown を返す"""
        self.assertEqual(classify_bump(None, "1.0.0"), "unknown")

    def test_none_current(self):
        """current が None のとき unknown を返す"""
        self.assertEqual(classify_bump("1.0.0", None), "unknown")

    def test_v_prefix_allowed(self):
        """Issue #115 提案3: 先頭 v を許容して比較する"""
        self.assertEqual(classify_bump("v1.0.0", "v1.0.1"), "patch")
        self.assertEqual(classify_bump("0.6.9", "v0.6.10"), "patch")

    def test_invalid_semver(self):
        """semver 形式でないとき unknown を返す"""
        self.assertEqual(classify_bump("abc", "1.0.1"), "unknown")
        self.assertEqual(classify_bump("1.0", "1.0.1"), "unknown")

    def test_minor_bump_with_patch_reset(self):
        """minor バンプで patch がリセットされたバージョン"""
        self.assertEqual(classify_bump("0.1.4", "0.1.5"), "patch")
        self.assertEqual(classify_bump("0.1.4", "0.2.0"), "minor")


class TestScopeParsing(unittest.TestCase):
    """target 内の scope / exclude リストのパース"""

    def test_parse_scope_and_exclude(self):
        yaml = """
targets:
  - name: forge
    version_file: plugins/forge/.claude-plugin/plugin.json
    version_path: version
    scope:
      - plugins/forge/**
      - shared/forge/*.py
    exclude:
      - plugins/forge/**/*.md
    sync_files:
      - path: README.md
        filter: '| **forge**'
"""
        result = _parse_version_config_yaml(yaml)
        target = result["targets"][0]
        self.assertEqual(target["scope"], ["plugins/forge/**", "shared/forge/*.py"])
        self.assertEqual(target["exclude"], ["plugins/forge/**/*.md"])
        self.assertEqual(target["sync_files"][0]["path"], "README.md")

    def test_default_empty_scope(self):
        """scope を持たない target は空リスト"""
        yaml = """
targets:
  - name: anvil
    version_file: plugins/anvil/.claude-plugin/plugin.json
    version_path: version
"""
        target = _parse_version_config_yaml(yaml)["targets"][0]
        self.assertEqual(target.get("scope"), [])
        self.assertEqual(target.get("exclude"), [])


class TestGlobMatch(unittest.TestCase):
    """_pattern_to_regex / match_any_pattern のテスト"""

    def test_double_star_matches_nested(self):
        rx = _pattern_to_regex("plugins/forge/**")
        self.assertTrue(rx.match("plugins/forge/skills/x/SKILL.md"))
        self.assertTrue(rx.match("plugins/forge/"))
        self.assertFalse(rx.match("plugins/anvil/x"))

    def test_single_star_does_not_cross_slash(self):
        rx = _pattern_to_regex("plugins/*/SKILL.md")
        self.assertTrue(rx.match("plugins/forge/SKILL.md"))
        self.assertFalse(rx.match("plugins/forge/skills/SKILL.md"))

    def test_match_any_with_exclude(self):
        self.assertTrue(match_any_pattern("plugins/forge/a.py", ["plugins/forge/**"]))
        self.assertFalse(match_any_pattern("plugins/anvil/a.py", ["plugins/forge/**"]))

    def test_match_empty_patterns(self):
        self.assertFalse(match_any_pattern("x", []))


def _run_main_with_mocks(project_root, mock_git_show, mock_branch="feature/test",
                         mock_exists=None, mock_changed_files=None):
    """main() をモックありで実行し、JSON 出力を返すヘルパー。

    file_exists_on_branch（git cat-file -e）もモックする。既定では
    mock_git_show が内容を返す（None でない）= base に存在する、と解釈する。
    存在するが version 抽出できないケースを検証する場合は mock_exists を明示する。
    """
    import io
    import sys
    from contextlib import redirect_stdout
    from get_version_status import main as _main

    if mock_exists is None:
        def mock_exists(branch, path):
            return mock_git_show(branch, path) is not None

    if mock_changed_files is None:
        mock_changed_files = []

    buf = io.StringIO()
    saved_argv = sys.argv
    try:
        sys.argv = ["get_version_status.py"]
        with patch("get_version_status.find_project_root", return_value=project_root), \
             patch("get_version_status.get_file_content_from_branch", side_effect=mock_git_show), \
             patch("get_version_status.file_exists_on_branch", side_effect=mock_exists), \
             patch("get_version_status.get_changed_files", return_value=mock_changed_files), \
             patch("get_version_status.get_current_branch", return_value=mock_branch):
            with redirect_stdout(buf):
                _main()
    finally:
        sys.argv = saved_argv

    return json.loads(buf.getvalue())


class TestMainIntegration(unittest.TestCase):
    """main() の統合テスト（ファイルシステム + git show をモック）"""

    def setUp(self):
        _TEST_TEMP_BASE.mkdir(parents=True, exist_ok=True)
        self.tmpdir = Path(tempfile.mkdtemp(dir=_TEST_TEMP_BASE))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_plugin_json(self, version: str, path: str) -> Path:
        """テスト用 plugin.json を作成する"""
        full_path = self.tmpdir / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(json.dumps({"version": version}), encoding="utf-8")
        return full_path

    def _write_config(self, content: str):
        """テスト用 .version-config.yaml を書き込む"""
        (self.tmpdir / ".version-config.yaml").write_text(content, encoding="utf-8")

    def test_changed_target_detected(self):
        """main branch より current が上がっている target を検出できる"""
        self._make_plugin_json("0.0.2", "plugins/forge/.claude-plugin/plugin.json")
        self._write_config(
            "targets:\n"
            "  - name: forge\n"
            "    version_file: plugins/forge/.claude-plugin/plugin.json\n"
            "    version_path: version\n"
        )

        output = _run_main_with_mocks(
            self.tmpdir,
            lambda branch, path: json.dumps({"version": "0.0.1"}),
        )

        self.assertEqual(output["status"], "ok")
        self.assertEqual(len(output["targets"]), 1)
        target = output["targets"][0]
        self.assertEqual(target["name"], "forge")
        self.assertEqual(target["base"], "0.0.1")
        self.assertEqual(target["current"], "0.0.2")
        self.assertTrue(target["changed"])
        self.assertEqual(target["bump_type"], "patch")

    def test_unchanged_target(self):
        """main と同じバージョンの target は changed=False"""
        self._make_plugin_json("0.0.1", "plugins/forge/.claude-plugin/plugin.json")
        self._write_config(
            "targets:\n"
            "  - name: forge\n"
            "    version_file: plugins/forge/.claude-plugin/plugin.json\n"
            "    version_path: version\n"
        )

        output = _run_main_with_mocks(
            self.tmpdir,
            lambda branch, path: json.dumps({"version": "0.0.1"}),
        )

        target = output["targets"][0]
        self.assertFalse(target["changed"])
        self.assertNotIn("bump_type", target)

    def test_new_target_not_on_base(self):
        """base ブランチに存在しない target に note が付く"""
        self._make_plugin_json("0.0.1", "plugins/doc-advisor/.claude-plugin/plugin.json")
        self._write_config(
            "targets:\n"
            "  - name: doc-advisor\n"
            "    version_file: plugins/doc-advisor/.claude-plugin/plugin.json\n"
            "    version_path: version\n"
        )

        # base ブランチにはファイルが存在しない
        output = _run_main_with_mocks(
            self.tmpdir,
            lambda branch, path: None,
        )

        target = output["targets"][0]
        self.assertFalse(target["changed"])
        self.assertIn("note", target)

    def test_non_json_base_file_not_misjudged_as_new(self):
        """Issue #115 提案4: base に存在する非 JSON ファイルを「新規」と誤判定しない。

        Swift 定数ファイルは JSON パースできないが、base に存在し version を抽出
        できれば changed 判定され、note(新規追加) は付かない。
        """
        swift_path = "Sources/Constants.swift"
        full = self.tmpdir / swift_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text('let version = "0.6.10"\n', encoding="utf-8")
        self._write_config(
            "targets:\n"
            "  - name: app\n"
            f"    version_file: {swift_path}\n"
            "    version_path: version\n"
        )

        # base には旧バージョンの Swift ファイルが存在する
        output = _run_main_with_mocks(
            self.tmpdir,
            lambda branch, path: 'let version = "0.6.9"\n',
            mock_exists=lambda branch, path: True,
        )

        target = output["targets"][0]
        self.assertEqual(target["base"], "0.6.9")
        self.assertEqual(target["current"], "0.6.10")
        self.assertTrue(target["changed"])
        self.assertNotIn("note", target)

    def test_existing_but_unextractable_gets_distinct_note(self):
        """base に存在するが version 抽出不可の場合は「新規追加」ではない note が付く"""
        path = "Sources/Constants.swift"
        full = self.tmpdir / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text('let version = "0.6.10"\n', encoding="utf-8")
        self._write_config(
            "targets:\n"
            "  - name: app\n"
            f"    version_file: {path}\n"
            "    version_path: version\n"
        )

        # 存在はするが version を抽出できない内容
        output = _run_main_with_mocks(
            self.tmpdir,
            lambda branch, path: "// no version here\n",
            mock_exists=lambda branch, path: True,
        )

        target = output["targets"][0]
        self.assertIsNone(target["base"])
        self.assertFalse(target["changed"])
        self.assertIn("note", target)
        self.assertNotIn("新規追加", target["note"])

    def test_changelog_header_target(self):
        """Issue #115 提案3: version_path: changelog_header で CHANGELOG から比較できる"""
        (self.tmpdir / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [0.6.10] - 2026-05-27\n\n- x\n", encoding="utf-8"
        )
        self._write_config(
            "targets:\n"
            "  - name: app\n"
            "    version_file: CHANGELOG.md\n"
            "    version_path: changelog_header\n"
        )

        output = _run_main_with_mocks(
            self.tmpdir,
            lambda branch, path: "# Changelog\n\n## [0.6.9] - 2026-05-20\n",
            mock_exists=lambda branch, path: True,
        )

        target = output["targets"][0]
        self.assertEqual(target["base"], "0.6.9")
        self.assertEqual(target["current"], "0.6.10")
        self.assertTrue(target["changed"])
        self.assertEqual(target["bump_type"], "patch")

    def test_marketplace_needs_bump(self):
        """プラグインが更新されているが marketplace が変わっていない場合に marketplace_needs_bump=true"""
        (self.tmpdir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        (self.tmpdir / ".claude-plugin" / "marketplace.json").write_text(
            json.dumps({"metadata": {"version": "0.1.0"}}), encoding="utf-8"
        )
        self._make_plugin_json("0.0.2", "plugins/forge/.claude-plugin/plugin.json")
        self._write_config(
            "targets:\n"
            "  - name: marketplace\n"
            "    version_file: .claude-plugin/marketplace.json\n"
            "    version_path: metadata.version\n"
            "  - name: forge\n"
            "    version_file: plugins/forge/.claude-plugin/plugin.json\n"
            "    version_path: version\n"
        )

        def mock_git_show(branch, path):
            if "marketplace" in path:
                return json.dumps({"metadata": {"version": "0.1.0"}})
            return json.dumps({"version": "0.0.1"})

        output = _run_main_with_mocks(self.tmpdir, mock_git_show)

        self.assertFalse(output["summary"]["marketplace_bumped"])
        self.assertTrue(output["summary"]["marketplace_needs_bump"])

    def test_marketplace_bumped_no_need(self):
        """marketplace も更新されている場合に marketplace_needs_bump=false"""
        (self.tmpdir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        (self.tmpdir / ".claude-plugin" / "marketplace.json").write_text(
            json.dumps({"metadata": {"version": "0.1.1"}}), encoding="utf-8"
        )
        self._make_plugin_json("0.0.2", "plugins/forge/.claude-plugin/plugin.json")
        self._write_config(
            "targets:\n"
            "  - name: marketplace\n"
            "    version_file: .claude-plugin/marketplace.json\n"
            "    version_path: metadata.version\n"
            "  - name: forge\n"
            "    version_file: plugins/forge/.claude-plugin/plugin.json\n"
            "    version_path: version\n"
        )

        def mock_git_show(branch, path):
            if "marketplace" in path:
                return json.dumps({"metadata": {"version": "0.1.0"}})
            return json.dumps({"version": "0.0.1"})

        output = _run_main_with_mocks(self.tmpdir, mock_git_show)

        self.assertTrue(output["summary"]["marketplace_bumped"])
        self.assertFalse(output["summary"]["marketplace_needs_bump"])


class TestNeedsBumpDetection(unittest.TestCase):
    """scope + 変更ファイルから needs_bump を算出する main() の動作"""

    def setUp(self):
        _TEST_TEMP_BASE.mkdir(parents=True, exist_ok=True)
        self.tmpdir = Path(tempfile.mkdtemp(dir=_TEST_TEMP_BASE))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _setup_two_plugins(self):
        for name in ("forge", "anvil"):
            p = self.tmpdir / f"plugins/{name}/.claude-plugin/plugin.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"version": "0.1.0"}), encoding="utf-8")
        (self.tmpdir / ".version-config.yaml").write_text(
            "targets:\n"
            "  - name: forge\n"
            "    version_file: plugins/forge/.claude-plugin/plugin.json\n"
            "    version_path: version\n"
            "    scope:\n"
            "      - plugins/forge/**\n"
            "  - name: anvil\n"
            "    version_file: plugins/anvil/.claude-plugin/plugin.json\n"
            "    version_path: version\n"
            "    scope:\n"
            "      - plugins/anvil/**\n",
            encoding="utf-8",
        )

    def test_needs_bump_detects_only_scoped_changes(self):
        """変更ファイルが scope に一致した target のみ needs_bump に入る"""
        self._setup_two_plugins()
        output = _run_main_with_mocks(
            self.tmpdir,
            lambda b, p: json.dumps({"version": "0.1.0"}),
            mock_changed_files=["plugins/forge/skills/foo.py"],
        )
        forge = next(t for t in output["targets"] if t["name"] == "forge")
        anvil = next(t for t in output["targets"] if t["name"] == "anvil")
        self.assertTrue(forge["files_changed"])
        self.assertEqual(forge["changed_file_count"], 1)
        self.assertFalse(anvil["files_changed"])
        self.assertEqual(output["summary"]["needs_bump"], ["forge"])

    def test_needs_bump_excludes_already_bumped(self):
        """既に bump 済み (changed=True) の target は needs_bump から除外する"""
        self._setup_two_plugins()
        # forge は既に 0.2.0 にバンプ済み（main は 0.1.0）
        (self.tmpdir / "plugins/forge/.claude-plugin/plugin.json").write_text(
            json.dumps({"version": "0.2.0"}), encoding="utf-8"
        )
        output = _run_main_with_mocks(
            self.tmpdir,
            lambda b, p: json.dumps({"version": "0.1.0"}),
            mock_changed_files=["plugins/forge/skills/foo.py"],
        )
        forge = next(t for t in output["targets"] if t["name"] == "forge")
        self.assertTrue(forge["changed"])
        self.assertTrue(forge["files_changed"])
        # 変更はあるが既に bump されているので候補ではない
        self.assertEqual(output["summary"]["needs_bump"], [])

    def test_needs_bump_empty_when_no_changes(self):
        self._setup_two_plugins()
        output = _run_main_with_mocks(
            self.tmpdir,
            lambda b, p: json.dumps({"version": "0.1.0"}),
            mock_changed_files=[],
        )
        self.assertEqual(output["summary"]["needs_bump"], [])

    def test_target_without_scope_never_auto_detected(self):
        """scope を持たない target は files_changed=false（自動検出対象外）"""
        p = self.tmpdir / "plugins/forge/.claude-plugin/plugin.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"version": "0.1.0"}), encoding="utf-8")
        (self.tmpdir / ".version-config.yaml").write_text(
            "targets:\n"
            "  - name: forge\n"
            "    version_file: plugins/forge/.claude-plugin/plugin.json\n"
            "    version_path: version\n",
            encoding="utf-8",
        )
        output = _run_main_with_mocks(
            self.tmpdir,
            lambda b, p: json.dumps({"version": "0.1.0"}),
            mock_changed_files=["plugins/forge/skills/foo.py"],
        )
        forge = output["targets"][0]
        self.assertFalse(forge["files_changed"])
        self.assertEqual(output["summary"]["needs_bump"], [])

    def test_exclude_filters_out_matched_files(self):
        """exclude に一致したファイルは files_changed のカウントに含まれない"""
        p = self.tmpdir / "plugins/forge/.claude-plugin/plugin.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"version": "0.1.0"}), encoding="utf-8")
        (self.tmpdir / ".version-config.yaml").write_text(
            "targets:\n"
            "  - name: forge\n"
            "    version_file: plugins/forge/.claude-plugin/plugin.json\n"
            "    version_path: version\n"
            "    scope:\n"
            "      - plugins/forge/**\n"
            "    exclude:\n"
            "      - plugins/forge/**/*.md\n",
            encoding="utf-8",
        )
        output = _run_main_with_mocks(
            self.tmpdir,
            lambda b, p: json.dumps({"version": "0.1.0"}),
            mock_changed_files=[
                "plugins/forge/skills/foo.py",
                "plugins/forge/docs/x.md",
            ],
        )
        forge = output["targets"][0]
        self.assertEqual(forge["changed_file_count"], 1)


if __name__ == "__main__":
    unittest.main()
