#!/usr/bin/env python3
"""monitor/session_adapter.py の単体テスト。"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

MONITOR_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "plugins", "forge", "scripts", "monitor",
)
sys.path.insert(0, os.path.abspath(MONITOR_DIR))

from session_adapter import (  # noqa: E402
    REFS_FILES,
    SESSION_FILES,
    build_monitor_session,
    read_markdown_file,
    read_session_file,
    read_yaml_file,
)


def _write_file(directory, filename, content):
    path = os.path.join(directory, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Path(path).write_text(content, encoding="utf-8")
    return path


class TestReadHelpers(unittest.TestCase):
    """個別ファイル読み取り helper のテスト。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_read_yaml_file_missing_returns_none(self):
        self.assertIsNone(read_yaml_file(os.path.join(self.tmpdir, "missing.yaml")))

    def test_read_yaml_file_empty_returns_dict(self):
        path = _write_file(self.tmpdir, "empty.yaml", "")
        self.assertEqual(read_yaml_file(path), {})

    def test_read_yaml_file_comment_only_returns_dict(self):
        path = _write_file(self.tmpdir, "comments.yaml", "# comment\n# another\n")
        self.assertEqual(read_yaml_file(path), {})

    def test_read_yaml_file_reads_flat_yaml(self):
        path = _write_file(self.tmpdir, "session.yaml", "skill: review\n")
        self.assertEqual(read_yaml_file(path)["skill"], "review")

    def test_read_yaml_file_reads_nested_review_refs(self):
        path = _write_file(self.tmpdir, "refs.yaml", """\
target_files:
  - plugins/forge/skills/review/SKILL.md
reference_docs:
  - path: docs/rules/skill_authoring_notes.md
perspectives:
  - name: correctness
    criteria_path: review/docs/review_criteria_code.md
    section: "正確性 (Logic)"
    output_path: review_correctness.md
related_code:
  - path: plugins/forge/skills/reviewer/SKILL.md
    reason: "同種 AI 専用スキルの frontmatter 参考"
    lines: "1-30"
""")
        result = read_yaml_file(path)
        self.assertEqual(result["target_files"][0], "plugins/forge/skills/review/SKILL.md")
        self.assertEqual(result["reference_docs"][0]["path"], "docs/rules/skill_authoring_notes.md")
        self.assertEqual(result["perspectives"][0]["name"], "correctness")
        self.assertEqual(result["perspectives"][0]["section"], "正確性 (Logic)")
        self.assertEqual(result["related_code"][0]["lines"], "1-30")

    def test_read_markdown_file_missing_returns_none(self):
        self.assertIsNone(read_markdown_file(os.path.join(self.tmpdir, "missing.md")))

    def test_read_markdown_file_reads_text(self):
        path = _write_file(self.tmpdir, "review.md", "# Review\n")
        self.assertEqual(read_markdown_file(path), "# Review\n")

    def test_read_session_file_missing_entry(self):
        entry = read_session_file(self.tmpdir, "session.yaml")
        self.assertFalse(entry["exists"])
        self.assertIsNone(entry["content"])


class TestBuildMonitorSession(unittest.TestCase):
    """build_monitor_session() のテスト。"""

    def setUp(self):
        self.session_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.session_dir, ignore_errors=True)

    def test_empty_dir_preserves_legacy_keys(self):
        result = build_monitor_session(self.session_dir, "review")
        self.assertEqual(result["session_dir"], self.session_dir)
        self.assertEqual(result["skill"], "review")
        self.assertIn("files", result)
        self.assertIn("refs", result)
        self.assertIn("refs_yaml", result)
        self.assertIn("derived", result)
        for name in SESSION_FILES:
            self.assertIn(name, result["files"])
            self.assertFalse(result["files"][name]["exists"])
        for name in REFS_FILES:
            self.assertIn(name, result["refs"])
            self.assertFalse(result["refs"][name]["exists"])

    def test_reads_session_yaml_and_derives_phase(self):
        _write_file(self.session_dir, "session.yaml", """\
skill: start-plan
status: in_progress
phase: context_ready
phase_status: completed
focus: "参照情報を収集済み"
waiting_type: none
waiting_reason: "should clear"
active_artifact: refs/rules.yaml
""")
        result = build_monitor_session(self.session_dir)
        self.assertEqual(result["skill"], "start-plan")
        self.assertTrue(result["files"]["session.yaml"]["exists"])
        self.assertEqual(result["derived"]["phase"], "context_ready")
        self.assertEqual(result["derived"]["phase_status"], "completed")
        self.assertEqual(result["derived"]["focus"], "参照情報を収集済み")
        self.assertEqual(result["derived"]["waiting"]["type"], "none")
        self.assertEqual(result["derived"]["waiting"]["reason"], "")
        self.assertEqual(result["derived"]["active_artifact"], "refs/rules.yaml")

    def test_reads_review_files(self):
        _write_file(self.session_dir, "review.md", "# 統合レビュー結果\n")
        result = build_monitor_session(self.session_dir, "review")
        self.assertTrue(result["files"]["review.md"]["exists"])
        self.assertIn("統合レビュー結果", result["files"]["review.md"]["content"])

    def test_reads_refs_yaml(self):
        _write_file(self.session_dir, "refs.yaml", "target_files:\n  - foo.py\n")
        result = build_monitor_session(self.session_dir, "review")
        self.assertTrue(result["refs_yaml"]["exists"])
        self.assertEqual(result["refs_yaml"]["content"]["target_files"], ["foo.py"])

    def test_reads_refs_dir(self):
        _write_file(self.session_dir, "refs/specs.yaml", """\
source: direct_search
documents:
  - path: docs/specs/foo.md
    reason: related
""")
        result = build_monitor_session(self.session_dir, "start-plan")
        self.assertTrue(result["refs"]["specs.yaml"]["exists"])
        docs = result["refs"]["specs.yaml"]["content"]["documents"]
        self.assertEqual(docs[0]["path"], "docs/specs/foo.md")

    def test_counts_plan_items(self):
        _write_file(self.session_dir, "plan.yaml", """\
items:
  - id: 1
    status: pending
  - id: 2
    status: fixed
  - id: 3
    status: needs_review
""")
        result = build_monitor_session(self.session_dir, "review")
        counts = result["derived"]["review_counts"]
        self.assertEqual(counts["total"], 3)
        self.assertEqual(counts["pending"], 1)
        self.assertEqual(counts["fixed"], 1)
        self.assertEqual(counts["needs_review"], 1)

    def test_plan_yaml_missing_counts_zero(self):
        result = build_monitor_session(self.session_dir, "review")
        counts = result["derived"]["review_counts"]
        self.assertEqual(counts["total"], 0)
        self.assertEqual(counts["pending"], 0)


if __name__ == "__main__":
    unittest.main()
