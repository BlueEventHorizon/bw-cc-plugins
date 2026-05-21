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
        # priority 行がない旧体系互換: priority は None
        self.assertIsNone(findings[0]["priority"])
        self.assertIsNone(findings[1]["priority"])

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

    def test_extracts_priority_p1_p2_p3(self):
        """各 finding に priority 行 (P1/P2/P3) があれば抽出される (DES-028 §4.2)。"""
        content = """\
1. [critical] **ルール違反A**: 説明
   - 箇所: a.py:1
   - priority: P1
2. [major] **矛盾B**: 説明
   - 箇所: b.py:2
   - priority: P2
3. [minor] **複雑化C**: 説明
   - priority: P3
"""
        findings = extract_findings(content)

        self.assertEqual(len(findings), 3)
        self.assertEqual(findings[0]["priority"], "P1")
        self.assertEqual(findings[1]["priority"], "P2")
        self.assertEqual(findings[2]["priority"], "P3")

    def test_priority_absent_is_none(self):
        """priority 行がない finding は priority=None (旧体系互換)。"""
        content = """\
1. [critical] **致命的A**: 説明
   - 箇所: a.py:1
2. [major] **品質B**: 説明
"""
        findings = extract_findings(content)

        self.assertEqual(len(findings), 2)
        self.assertIsNone(findings[0]["priority"])
        self.assertIsNone(findings[1]["priority"])
        # severity は独立して保持される
        self.assertEqual(findings[0]["severity"], "critical")
        self.assertEqual(findings[1]["severity"], "major")

    def test_severity_and_priority_are_independent(self):
        """priority と severity は独立軸 (DES-028 §4.1 / REQ-004 FNC-407)。

        一方の値からもう一方を推定しない。例えば P1 が必ず critical とは限らない。
        """
        # P1 で minor、P3 で critical という「軸独立」のケース
        content = """\
1. [minor] **ルール違反だが軽微A**: 説明
   - priority: P1
2. [critical] **過剰複雑化B**: 説明
   - priority: P3
3. 🟡 **priority のみ未指定C**: 説明
"""
        findings = extract_findings(content)

        self.assertEqual(len(findings), 3)
        # 1件目: severity と priority は独立に共存
        self.assertEqual(findings[0]["severity"], "minor")
        self.assertEqual(findings[0]["priority"], "P1")
        # 2件目: 「P1 = critical」のような自動マッピングはしない
        self.assertEqual(findings[1]["severity"], "critical")
        self.assertEqual(findings[1]["priority"], "P3")
        # 3件目: severity だけ存在し priority は None (推定しない)
        self.assertEqual(findings[2]["severity"], "major")
        self.assertIsNone(findings[2]["priority"])

    def test_priority_case_insensitive_and_inline_form(self):
        """priority 行は大文字小文字非依存・先頭ハイフン有無を許容する。"""
        content = """\
1. [critical] **A**: 説明
priority: p1
2. [major] **B**: 説明
  - Priority: P2
"""
        findings = extract_findings(content)

        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0]["priority"], "P1")
        self.assertEqual(findings[1]["priority"], "P2")


if __name__ == "__main__":
    unittest.main()
