#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""split_doc_sections.py のユニットテスト。

テスト対象:
- split_sections(): ## 見出しによるセクション分割
- collect_sections(): 複数ファイルからのセクション収集
- main(): CLI 実行時の JSON 出力フォーマット

外部 API（Embedding 等）は使用しないため、モックは不要。
"""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = str(
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "skills" / "clean-rules" / "scripts"
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from split_doc_sections import (
    collect_sections,
    split_sections,
)


# ---------------------------------------------------------------------------
# split_sections テスト
# ---------------------------------------------------------------------------

class TestSplitSections(unittest.TestCase):
    """## 見出しによるセクション分割のテスト。"""

    def test_basic_split(self):
        """基本的な ## 見出しで分割される"""
        content = """# Title

Introduction text.

## Section A

Content A.

## Section B

Content B.
"""
        sections = split_sections(content, filepath="test.md")
        self.assertEqual(len(sections), 3)
        self.assertIn("test.md", sections[0]["heading"])
        self.assertEqual(sections[1]["heading"], "## Section A")
        self.assertEqual(sections[2]["heading"], "## Section B")

    def test_no_sections(self):
        """## 見出しがないファイルは全体を1セクションとして返す"""
        content = "Just plain text without any headings."
        sections = split_sections(content, filepath="plain.md")
        self.assertEqual(len(sections), 1)
        self.assertIn("plain.md", sections[0]["heading"])
        self.assertEqual(sections[0]["text"], "Just plain text without any headings.")

    def test_subsections_not_split(self):
        """### 以下の見出しでは分割しない"""
        content = """## Main Section

### Subsection 1

Text 1.

### Subsection 2

Text 2.
"""
        sections = split_sections(content)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["heading"], "## Main Section")
        self.assertIn("### Subsection 1", sections[0]["text"])

    def test_empty_content(self):
        """空文字列の場合は空リストを返す"""
        sections = split_sections("")
        self.assertEqual(sections, [])

    def test_whitespace_only(self):
        """空白のみの場合は空リストを返す"""
        sections = split_sections("   \n\n  ")
        self.assertEqual(sections, [])

    def test_line_numbers(self):
        """セクションの開始行番号が正しい"""
        content = """Line 1
Line 2

## Section at Line 4

Content.

## Section at Line 8

More content.
"""
        sections = split_sections(content)
        self.assertEqual(sections[0]["line"], 1)
        self.assertEqual(sections[1]["line"], 4)
        self.assertEqual(sections[2]["line"], 8)

    def test_frontmatter_handling(self):
        """YAML frontmatter がある場合もヘッダーセクションに含まれる"""
        content = """---
name: test
---

# Title

Intro.

## Section A

Content.
"""
        sections = split_sections(content, filepath="fm.md")
        self.assertEqual(len(sections), 2)
        self.assertIn("---", sections[0]["text"])

    def test_code_fence_heading_not_split(self):
        """コードフェンス内の ## は見出しとして扱わない"""
        content = """## Section A

以下はコード例:

```bash
## これはコードコメント
echo hello
```

## Section B

本文。
"""
        sections = split_sections(content, filepath="code.md")
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0]["heading"], "## Section A")
        self.assertEqual(sections[1]["heading"], "## Section B")
        self.assertIn("## これはコードコメント", sections[0]["text"])

    def test_tilde_fence_heading_not_split(self):
        """~~~ フェンス内の ## も見出しとして扱わない"""
        content = """## Section

~~~python
## comment
x = 1
~~~

trailing text.
"""
        sections = split_sections(content)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["heading"], "## Section")
        self.assertIn("## comment", sections[0]["text"])


# ---------------------------------------------------------------------------
# collect_sections テスト
# ---------------------------------------------------------------------------

class TestCollectSections(unittest.TestCase):
    """ファイルからのセクション収集テスト。"""

    def test_collect_from_files(self):
        """複数ファイルからセクションを収集する"""
        with tempfile.TemporaryDirectory() as tmpdir:
            f1 = Path(tmpdir) / "a.md"
            f1.write_text("## Sec A\n\nContent A.\n", encoding="utf-8")
            f2 = Path(tmpdir) / "b.md"
            f2.write_text("## Sec B\n\nContent B.\n\n## Sec C\n\nContent C.\n",
                          encoding="utf-8")

            sections, warnings = collect_sections([str(f1), str(f2)])
            self.assertEqual(len(sections), 3)
            self.assertEqual(sections[0]["heading"], "## Sec A")
            self.assertEqual(sections[0]["file"], str(f1))
            self.assertEqual(warnings, [])

    def test_missing_file_skipped(self):
        """存在しないファイルはスキップされ warnings に記録される"""
        sections, warnings = collect_sections(["/nonexistent/file.md"])
        self.assertEqual(sections, [])
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["file"], "/nonexistent/file.md")
        self.assertIn("error", warnings[0])


# ---------------------------------------------------------------------------
# main() 統合テスト
# ---------------------------------------------------------------------------

class TestMainOutput(unittest.TestCase):
    """main() の JSON 出力フォーマットテスト。"""

    def _run_main(self, project_files, forge_files):
        """main() を実行して stdout の JSON を返す。"""
        from split_doc_sections import main

        args = ["prog",
                "--project-rules"] + project_files + [
                "--forge-docs"] + forge_files

        captured = io.StringIO()
        with patch("sys.argv", args), \
             patch("sys.stdout", captured):
            try:
                main()
            except SystemExit:
                pass

        output = captured.getvalue()
        return json.loads(output) if output.strip() else None

    def test_output_has_required_fields(self):
        """JSON 出力に必須フィールドが含まれる"""
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "rule.md"
            p.write_text("## Sec\n\nContent.\n", encoding="utf-8")
            f = Path(tmpdir) / "forge.md"
            f.write_text("## Forge\n\nContent.\n", encoding="utf-8")

            result = self._run_main([str(p)], [str(f)])
            self.assertIsNotNone(result)
            self.assertEqual(result["status"], "ok")
            self.assertIn("project_sections", result)
            self.assertIn("forge_sections", result)
            self.assertIn("project_section_count", result)
            self.assertIn("forge_section_count", result)
            self.assertIn("warnings", result)
            self.assertEqual(result["warnings"], [])

    def test_sections_have_structure(self):
        """各セクションが file / heading / text / line を持つ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "rule.md"
            p.write_text("## Naming\n\nUse snake_case.\n", encoding="utf-8")
            f = Path(tmpdir) / "forge.md"
            f.write_text("## Format\n\nUse the template.\n", encoding="utf-8")

            result = self._run_main([str(p)], [str(f)])
            self.assertEqual(result["project_section_count"], 1)
            self.assertEqual(result["forge_section_count"], 1)

            sec = result["project_sections"][0]
            for key in ("file", "heading", "text", "line"):
                self.assertIn(key, sec)
            self.assertEqual(sec["heading"], "## Naming")
            self.assertEqual(result["forge_sections"][0]["heading"], "## Format")


if __name__ == "__main__":
    unittest.main()
