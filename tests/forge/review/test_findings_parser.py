"""review.findings_parser のテスト。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[3] / "plugins" / "forge" / "scripts"),
)
sys.modules.pop("review", None)

from review.findings_parser import extract_findings, extract_perspective_from_filename


class TestFindingsParser(unittest.TestCase):
    def test_extracts_ascii_and_emoji_severities(self):
        content = """\
1. [critical] **致命的A**: 説明
   - 箇所: a.py:1
2. 🟡 **品質B**: 説明
"""
        findings = extract_findings(content)

        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0]["severity"], "critical")
        self.assertEqual(findings[0]["title"], "致命的A")
        self.assertEqual(findings[0]["location"], "a.py:1")
        self.assertEqual(findings[1]["severity"], "major")

    def test_section_heading_fallback(self):
        content = """\
### 🟢改善提案

1. **改善A**: 説明
"""
        findings = extract_findings(content)
        self.assertEqual(findings[0]["severity"], "minor")

    def test_extract_perspective_from_filename(self):
        self.assertEqual(
            extract_perspective_from_filename("review_project-rules.md"),
            "project-rules",
        )
        self.assertEqual(extract_perspective_from_filename("review.md"), "")


if __name__ == "__main__":
    unittest.main()
