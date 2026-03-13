#!/usr/bin/env python3
"""
generate_report.py のテスト

YAML パーサー、review.md パーサー、HTML 生成をテストする。
標準ライブラリのみ使用。

実行:
  python3 -m pytest tests/forge/show_report/test_generate_report.py -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# テスト対象モジュールへのパスを追加
sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parents[3]
        / "plugins"
        / "forge"
        / "skills"
        / "show-report"
    ),
)

from generate_report import (
    _coerce_value,
    _parse_flow_array,
    _strip_quotes,
    build_report_data,
    generate_html,
    parse_review_md,
    parse_session_yaml,
)


# ---------------------------------------------------------------------------
# _strip_quotes
# ---------------------------------------------------------------------------
class TestStripQuotes(unittest.TestCase):
    def test_double_quotes(self):
        self.assertEqual(_strip_quotes('"hello"'), "hello")

    def test_single_quotes(self):
        self.assertEqual(_strip_quotes("'hello'"), "hello")

    def test_no_quotes(self):
        self.assertEqual(_strip_quotes("hello"), "hello")

    def test_empty_string(self):
        self.assertEqual(_strip_quotes(""), "")

    def test_mismatched_quotes(self):
        self.assertEqual(_strip_quotes('"hello\''), "\"hello'")


# ---------------------------------------------------------------------------
# _coerce_value
# ---------------------------------------------------------------------------
class TestCoerceValue(unittest.TestCase):
    def test_integer(self):
        self.assertEqual(_coerce_value("42"), 42)

    def test_boolean_true(self):
        self.assertIs(_coerce_value("true"), True)

    def test_boolean_false(self):
        self.assertIs(_coerce_value("false"), False)

    def test_string(self):
        self.assertEqual(_coerce_value("hello"), "hello")

    def test_empty_string(self):
        self.assertEqual(_coerce_value(""), "")

    def test_quoted_string(self):
        self.assertEqual(_coerce_value('"2026-03-13T14:30:00Z"'), "2026-03-13T14:30:00Z")

    def test_zero(self):
        self.assertEqual(_coerce_value("0"), 0)


# ---------------------------------------------------------------------------
# _parse_flow_array
# ---------------------------------------------------------------------------
class TestParseFlowArray(unittest.TestCase):
    def test_empty_array(self):
        self.assertEqual(_parse_flow_array("[]"), [])

    def test_simple_values(self):
        self.assertEqual(_parse_flow_array("[a, b, c]"), ["a", "b", "c"])

    def test_quoted_values(self):
        self.assertEqual(_parse_flow_array('["a", "b"]'), ["a", "b"])

    def test_single_element(self):
        self.assertEqual(_parse_flow_array("[foo]"), ["foo"])

    def test_spaces(self):
        self.assertEqual(_parse_flow_array("[  a ,  b  ]"), ["a", "b"])


# ---------------------------------------------------------------------------
# parse_session_yaml — フラット key-value
# ---------------------------------------------------------------------------
class TestParseSessionYamlFlat(unittest.TestCase):
    def test_session_yaml(self):
        text = """\
review_type: code
engine: codex
auto_count: 0
current_cycle: 1
started_at: "2026-03-13T14:30:00Z"
last_updated: "2026-03-13T15:00:00Z"
status: in_progress
"""
        result = parse_session_yaml(text)
        self.assertEqual(result["review_type"], "code")
        self.assertEqual(result["engine"], "codex")
        self.assertEqual(result["auto_count"], 0)
        self.assertEqual(result["current_cycle"], 1)
        self.assertEqual(result["started_at"], "2026-03-13T14:30:00Z")
        self.assertEqual(result["status"], "in_progress")

    def test_comments_ignored(self):
        text = """\
# コメント
key: value
# もう一つのコメント
"""
        result = parse_session_yaml(text)
        self.assertEqual(result, {"key": "value"})

    def test_empty_lines_ignored(self):
        text = """\
key1: val1

key2: val2
"""
        result = parse_session_yaml(text)
        self.assertEqual(result, {"key1": "val1", "key2": "val2"})


# ---------------------------------------------------------------------------
# parse_session_yaml — 文字列リスト
# ---------------------------------------------------------------------------
class TestParseSessionYamlStringList(unittest.TestCase):
    def test_simple_list(self):
        text = """\
target_files:
  - path/to/file1.md
  - path/to/file2.md
"""
        result = parse_session_yaml(text)
        self.assertEqual(result["target_files"], ["path/to/file1.md", "path/to/file2.md"])

    def test_flow_array(self):
        text = """\
files_modified: []
"""
        result = parse_session_yaml(text)
        self.assertEqual(result["files_modified"], [])


# ---------------------------------------------------------------------------
# parse_session_yaml — オブジェクトリスト
# ---------------------------------------------------------------------------
class TestParseSessionYamlObjectList(unittest.TestCase):
    def test_evaluation_items(self):
        text = """\
cycle: 1
items:
  - id: 1
    severity: critical
    title: "問題タイトル"
    recommendation: fix
    auto_fixable: true
    reason: "判定理由"
  - id: 2
    severity: major
    title: "別の問題"
    recommendation: skip
    reason: "理由"
"""
        result = parse_session_yaml(text)
        self.assertEqual(result["cycle"], 1)
        self.assertEqual(len(result["items"]), 2)

        item1 = result["items"][0]
        self.assertEqual(item1["id"], 1)
        self.assertEqual(item1["severity"], "critical")
        self.assertEqual(item1["title"], "問題タイトル")
        self.assertEqual(item1["recommendation"], "fix")
        self.assertIs(item1["auto_fixable"], True)

        item2 = result["items"][1]
        self.assertEqual(item2["id"], 2)
        self.assertEqual(item2["recommendation"], "skip")


# ---------------------------------------------------------------------------
# parse_session_yaml — オブジェクト内の子リスト
# ---------------------------------------------------------------------------
class TestParseSessionYamlSubList(unittest.TestCase):
    def test_files_modified_block_list(self):
        text = """\
items:
  - id: 1
    severity: critical
    title: "問題"
    status: fixed
    files_modified:
      - path/to/file1.md
      - path/to/file2.md
    skip_reason: ""
  - id: 2
    severity: major
    title: "別の問題"
    status: pending
    files_modified: []
    skip_reason: ""
"""
        result = parse_session_yaml(text)
        self.assertEqual(len(result["items"]), 2)

        item1 = result["items"][0]
        self.assertEqual(item1["files_modified"], ["path/to/file1.md", "path/to/file2.md"])
        self.assertEqual(item1["skip_reason"], "")

        item2 = result["items"][1]
        self.assertEqual(item2["files_modified"], [])

    def test_flow_array_in_object(self):
        text = """\
items:
  - id: 1
    title: "問題"
    files_modified: [a.md, b.md]
"""
        result = parse_session_yaml(text)
        self.assertEqual(result["items"][0]["files_modified"], ["a.md", "b.md"])


# ---------------------------------------------------------------------------
# parse_session_yaml — refs.yaml（混在パターン）
# ---------------------------------------------------------------------------
class TestParseSessionYamlRefs(unittest.TestCase):
    def test_refs_yaml(self):
        text = """\
target_files:
  - plugins/forge/skills/review/SKILL.md
  - plugins/forge/skills/reviewer/SKILL.md

reference_docs:
  - path: docs/rules/skill_authoring_notes.md
  - path: plugins/forge/defaults/review_criteria.md

review_criteria_path: plugins/forge/defaults/review_criteria.md

related_code:
  - path: plugins/forge/skills/reviewer/SKILL.md
    reason: 同種 AI 専用スキルの frontmatter 参考
    lines: "1-30"
  - path: plugins/forge/skills/evaluator/SKILL.md
    reason: 同種 AI 専用スキルの frontmatter 参考
"""
        result = parse_session_yaml(text)
        self.assertEqual(
            result["target_files"],
            ["plugins/forge/skills/review/SKILL.md", "plugins/forge/skills/reviewer/SKILL.md"],
        )
        self.assertEqual(len(result["reference_docs"]), 2)
        self.assertEqual(result["reference_docs"][0]["path"], "docs/rules/skill_authoring_notes.md")
        self.assertEqual(result["review_criteria_path"], "plugins/forge/defaults/review_criteria.md")
        self.assertEqual(len(result["related_code"]), 2)
        self.assertEqual(result["related_code"][0]["lines"], "1-30")
        self.assertEqual(result["related_code"][1]["reason"], "同種 AI 専用スキルの frontmatter 参考")


# ---------------------------------------------------------------------------
# parse_review_md
# ---------------------------------------------------------------------------
class TestParseReviewMd(unittest.TestCase):
    def test_basic_extraction(self):
        text = """\
### 🔴致命的問題

1. **Actor 隔離違反**: 説明
   - 箇所: App/ViewModel/FooViewModel.swift:42-58
   - 修正案: 修正提案

### 🟡品質問題

1. **frontmatter 不足**: 説明
   - 箇所: plugins/forge/skills/review/SKILL.md:1-5
"""
        result = parse_review_md(text)
        self.assertIn("Actor 隔離違反", result)
        self.assertEqual(
            result["Actor 隔離違反"]["location"],
            "App/ViewModel/FooViewModel.swift:42-58",
        )
        self.assertIn("frontmatter 不足", result)
        self.assertEqual(
            result["frontmatter 不足"]["location"],
            "plugins/forge/skills/review/SKILL.md:1-5",
        )

    def test_no_location(self):
        text = """\
1. **問題名**: 説明だけで箇所なし
"""
        result = parse_review_md(text)
        self.assertIn("問題名", result)
        self.assertEqual(result["問題名"]["location"], "")

    def test_section_name_only(self):
        """箇所がセクション名のみ（ファイルパスでない）場合は空文字"""
        text = """\
1. **問題名**: 説明
   - 箇所: セッション管理セクション
"""
        result = parse_review_md(text)
        self.assertEqual(result["問題名"]["location"], "")

    def test_location_without_line(self):
        text = """\
1. **問題名**: 説明
   - 箇所: path/to/file.md
"""
        result = parse_review_md(text)
        self.assertEqual(result["問題名"]["location"], "path/to/file.md")


# ---------------------------------------------------------------------------
# build_report_data + generate_html（統合テスト）
# ---------------------------------------------------------------------------
class TestBuildReportData(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # session.yaml
        Path(self.tmpdir, "session.yaml").write_text(
            'review_type: code\nengine: codex\nauto_count: 0\n'
            'current_cycle: 1\nstarted_at: "2026-03-13T14:30:00Z"\n'
            'last_updated: "2026-03-13T15:00:00Z"\nstatus: in_progress\n',
            encoding="utf-8",
        )
        # plan.yaml
        Path(self.tmpdir, "plan.yaml").write_text(
            'items:\n'
            '  - id: 1\n    severity: critical\n    title: "テスト問題"\n'
            '    status: fixed\n    fixed_at: "2026-03-13T14:45:00Z"\n'
            '    files_modified:\n      - app/main.py\n    skip_reason: ""\n',
            encoding="utf-8",
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_build_minimal(self):
        """session.yaml + plan.yaml のみで正常動作"""
        data = build_report_data(self.tmpdir, "/test/project")
        self.assertEqual(data["session"]["review_type"], "code")
        self.assertEqual(len(data["plan"]["items"]), 1)
        self.assertEqual(data["plan"]["items"][0]["status"], "fixed")
        self.assertEqual(data["project_root"], "/test/project")
        self.assertIsNone(data["evaluation"])
        self.assertIsNone(data["refs"])

    def test_build_with_review_md(self):
        """review.md ありで箇所が抽出される"""
        Path(self.tmpdir, "review.md").write_text(
            '### 🔴致命的問題\n\n'
            '1. **テスト問題**: 説明\n'
            '   - 箇所: app/main.py:10\n',
            encoding="utf-8",
        )
        data = build_report_data(self.tmpdir, "/test/project")
        self.assertEqual(data["locations"].get("1"), "app/main.py:10")

    def test_build_with_all_files(self):
        """全ファイル揃っている場合"""
        Path(self.tmpdir, "review.md").write_text(
            '1. **テスト問題**: 説明\n   - 箇所: app/main.py:10\n',
            encoding="utf-8",
        )
        Path(self.tmpdir, "evaluation.yaml").write_text(
            'cycle: 1\nitems:\n  - id: 1\n    severity: critical\n'
            '    title: "テスト問題"\n    recommendation: fix\n'
            '    auto_fixable: true\n    reason: "理由"\n',
            encoding="utf-8",
        )
        Path(self.tmpdir, "refs.yaml").write_text(
            'target_files:\n  - app/main.py\nreference_docs:\n'
            '  - path: docs/rules.md\nreview_criteria_path: criteria.md\n',
            encoding="utf-8",
        )
        data = build_report_data(self.tmpdir, "/test/project")
        self.assertIsNotNone(data["evaluation"])
        self.assertEqual(data["evaluation"]["items"][0]["recommendation"], "fix")
        self.assertIsNotNone(data["refs"])
        self.assertEqual(data["refs"]["target_files"], ["app/main.py"])


class TestGenerateHtml(unittest.TestCase):
    def test_html_contains_embedded_data(self):
        """生成された HTML に EMBEDDED_DATA が含まれる"""
        data = {
            "session": {"review_type": "code", "engine": "codex"},
            "plan": {"items": []},
            "evaluation": None,
            "refs": None,
            "locations": {},
            "project_root": "/test",
            "generated_at": "2026-03-13T00:00:00Z",
        }
        html = generate_html(data)
        self.assertIn("const EMBEDDED_DATA =", html)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("vscode://file/", html)

    def test_html_does_not_contain_placeholder(self):
        """プレースホルダーが置換済み"""
        data = {
            "session": {}, "plan": {"items": []},
            "evaluation": None, "refs": None,
            "locations": {}, "project_root": "/test",
            "generated_at": "",
        }
        html = generate_html(data)
        self.assertNotIn("/*__EMBEDDED_DATA__*/", html)

    def test_html_has_auto_refresh(self):
        data = {
            "session": {}, "plan": {"items": []},
            "evaluation": None, "refs": None,
            "locations": {}, "project_root": "/test",
            "generated_at": "",
        }
        html = generate_html(data)
        self.assertIn('http-equiv="refresh"', html)

    def test_html_has_dark_mode(self):
        data = {
            "session": {}, "plan": {"items": []},
            "evaluation": None, "refs": None,
            "locations": {}, "project_root": "/test",
            "generated_at": "",
        }
        html = generate_html(data)
        self.assertIn("prefers-color-scheme: dark", html)


# ---------------------------------------------------------------------------
# 統合テスト: ファイル書き込みまで
# ---------------------------------------------------------------------------
class TestEndToEnd(unittest.TestCase):
    def test_full_pipeline(self):
        """セッションデータからHTML生成までの全パイプライン"""
        tmpdir = tempfile.mkdtemp()
        try:
            Path(tmpdir, "session.yaml").write_text(
                'review_type: design\nengine: claude\nauto_count: 2\n'
                'current_cycle: 1\nstarted_at: "2026-03-13T10:00:00Z"\n'
                'last_updated: "2026-03-13T11:00:00Z"\nstatus: in_progress\n',
                encoding="utf-8",
            )
            Path(tmpdir, "plan.yaml").write_text(
                'items:\n'
                '  - id: 1\n    severity: critical\n    title: "A問題"\n'
                '    status: fixed\n    fixed_at: "2026-03-13T10:30:00Z"\n'
                '    files_modified:\n      - docs/design.md\n    skip_reason: ""\n'
                '  - id: 2\n    severity: minor\n    title: "B問題"\n'
                '    status: pending\n    fixed_at: ""\n'
                '    files_modified: []\n    skip_reason: ""\n',
                encoding="utf-8",
            )
            Path(tmpdir, "review.md").write_text(
                '### 🔴致命的問題\n\n'
                '1. **A問題**: 説明A\n   - 箇所: docs/design.md:5\n\n'
                '### 🟢改善提案\n\n'
                '1. **B問題**: 説明B\n   - 箇所: docs/design.md:20\n',
                encoding="utf-8",
            )
            Path(tmpdir, "evaluation.yaml").write_text(
                'cycle: 1\nitems:\n'
                '  - id: 1\n    severity: critical\n    title: "A問題"\n'
                '    recommendation: fix\n    auto_fixable: false\n    reason: "理由A"\n'
                '  - id: 2\n    severity: minor\n    title: "B問題"\n'
                '    recommendation: skip\n    reason: "理由B"\n',
                encoding="utf-8",
            )
            Path(tmpdir, "refs.yaml").write_text(
                'target_files:\n  - docs/design.md\n'
                'reference_docs:\n  - path: docs/rules.md\n'
                'review_criteria_path: criteria.md\n',
                encoding="utf-8",
            )

            data = build_report_data(tmpdir, "/test/project")
            html = generate_html(data)

            output_path = Path(tmpdir, "report.html")
            output_path.write_text(html, encoding="utf-8")

            self.assertTrue(output_path.exists())
            content = output_path.read_text(encoding="utf-8")

            # データが正しく埋め込まれている
            self.assertIn('"review_type": "design"', content)
            self.assertIn('"A問題"', content)
            self.assertIn('"B問題"', content)
            # locations が抽出されている
            self.assertIn("docs/design.md:5", content)
            self.assertIn("docs/design.md:20", content)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
