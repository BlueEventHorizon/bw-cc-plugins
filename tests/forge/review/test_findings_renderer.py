"""review.findings_renderer のテスト。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[3] / "plugins" / "forge" / "scripts"),
)
sys.modules.pop("review", None)

from review.findings_renderer import generate_plan_yaml, generate_review_md, summarize


class TestFindingsRenderer(unittest.TestCase):
    def test_generate_plan_yaml(self):
        yaml_text = generate_plan_yaml([
            {
                "id": 1,
                "severity": "critical",
                "title": "path: 問題",
                "status": "pending",
                "perspective": "logic",
            }
        ])

        self.assertIn("items:", yaml_text)
        self.assertIn('title: "path: 問題"', yaml_text)
        self.assertIn("perspective: logic", yaml_text)

    def test_generate_review_md_and_summary(self):
        findings = [
            {
                "id": 1,
                "severity": "critical",
                "title": "問題A",
                "location": "a.py:1",
                "perspective": "logic",
            },
            {"id": 2, "severity": "minor", "title": "改善B", "location": ""},
        ]

        md = generate_review_md(findings)
        self.assertIn("# 統合レビュー結果", md)
        self.assertIn("[logic]", md)
        self.assertIn("箇所: a.py:1", md)
        self.assertEqual(
            summarize(findings),
            {"total": 2, "critical": 1, "major": 0, "minor": 1},
        )


if __name__ == "__main__":
    unittest.main()
