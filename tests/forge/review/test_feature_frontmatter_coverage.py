#!/usr/bin/env python3
"""回帰防止テスト: 追加 feature 文書の frontmatter カバレッジ一貫性 (Issue #118)。

Issue #118 の背景: 追加 feature 文書 (既存 spec への差分として新規作成する要件定義書・
設計書・計画書) に必須の frontmatter が、生成時にも `/forge:review` でも取りこぼされた。
原因は「追加開発サポートが start-requirements に閉じ、定義 (format) / 検証 (criteria) の
各層へ伝播していない構造的非対称」だった。

本テストは提案 A (検証層) + C (定義層) の実装が後退しないことを静的に検証する:

- C 定義層: 3 format が各 type を定義し、additive_development_spec.md §6 が全種別を集約する
- A 検証層 (severity): 3 つの重大度カタログ (requirement_format / design_principles /
  plan_principles) に「追加 feature 文書の frontmatter 欠如 = 🟡 major」が存在する
- A 検証層 (criteria): 3 criteria の §2 が frontmatter 照合を参照し、design criteria の
  §1 SSOT参照が design_format.md を参照する (requirement/plan との非対称の解消)
- FNC-402 不退行: 編集した 3 criteria は severity (🔴/🟡/🟢) を一切宣言しない

実行:
  python3 -m unittest tests.forge.review.test_feature_frontmatter_coverage -v
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FORGE_DOCS = REPO_ROOT / "plugins" / "forge" / "docs"
CRITERIA_DIR = REPO_ROOT / "plugins" / "forge" / "skills" / "review" / "docs"
SKILLS_DIR = REPO_ROOT / "plugins" / "forge" / "skills"

# 追加 feature 文書の frontmatter type マーカー (生成経路を問わず検出対象)
FRONTMATTER_TYPES = {
    "requirement": "type: temporary-feature-requirement",
    "design": "type: temporary-feature-design",
    "plan": "type: temporary-feature-plan",
}


def _read(path: Path) -> str:
    if not path.is_file():
        raise unittest.SkipTest(f"必須ファイルが存在しない: {path}")
    return path.read_text(encoding="utf-8")


class TestDefinitionLayer(unittest.TestCase):
    """提案 C: frontmatter 定義の対称化 + 集約 SoT。"""

    def test_each_format_defines_its_frontmatter_type(self):
        """requirement/design/plan の各 format が自種別の type を定義していること。"""
        files = {
            "requirement": FORGE_DOCS / "requirement_format.md",
            "design": FORGE_DOCS / "design_format.md",
            "plan": FORGE_DOCS / "plan_format.md",
        }
        for kind, path in files.items():
            with self.subTest(kind=kind):
                content = _read(path)
                self.assertIn(
                    FRONTMATTER_TYPES[kind],
                    content,
                    f"{path.name} に '{FRONTMATTER_TYPES[kind]}' の定義がない "
                    "(Issue #118 提案 C の非対称性除去に反する)",
                )

    def test_additive_spec_aggregates_all_types(self):
        """additive_development_spec.md が全 3 種別の frontmatter を集約していること (集約 SoT)。"""
        content = _read(FORGE_DOCS / "additive_development_spec.md")
        for kind, marker in FRONTMATTER_TYPES.items():
            with self.subTest(kind=kind):
                self.assertIn(
                    marker,
                    content,
                    f"additive_development_spec.md に '{marker}' がない "
                    "(§6 集約 SoT が全種別を網羅していない)",
                )

    def test_additive_spec_has_aggregation_section(self):
        """集約 SoT 節 (§6) の見出しが存在すること。"""
        content = _read(FORGE_DOCS / "additive_development_spec.md")
        self.assertIn(
            "frontmatter 定義一覧",
            content,
            "additive_development_spec.md に集約 SoT 節 (§6 frontmatter 定義一覧) がない",
        )


class TestSeverityCatalogLayer(unittest.TestCase):
    """提案 A (severity): 重大度カタログに frontmatter 欠如項目が存在すること。"""

    def test_requirement_format_has_severity_catalog(self):
        """requirement_format.md に重大度カタログ節と frontmatter 欠如項目があること。

        criteria_requirement は requirement_format.md を「規範本体 + 重大度カタログ」と
        宣言しているため、カタログ節の実在は criteria の宣言との整合に必要。
        """
        content = _read(FORGE_DOCS / "requirement_format.md")
        self.assertIn(
            "## 重大度カタログ",
            content,
            "requirement_format.md に重大度カタログ節がない (criteria の宣言と不整合)",
        )
        self.assertIn(
            "temporary-feature-requirement",
            content,
            "requirement_format.md 重大度カタログに frontmatter 欠如項目がない",
        )

    def test_design_principles_catalog_has_frontmatter_entry(self):
        """design_principles_spec.md 重大度カタログに frontmatter 欠如項目があること。"""
        content = _read(FORGE_DOCS / "design_principles_spec.md")
        self.assertIn("temporary-feature-design", content)
        self.assertIn(
            "frontmatter 欠如",
            content,
            "design_principles_spec.md に追加 feature frontmatter 欠如のカタログ項目がない",
        )

    def test_plan_principles_catalog_has_frontmatter_entry(self):
        """plan_principles_spec.md 重大度カタログに frontmatter マーカー欠如項目があること。"""
        content = _read(FORGE_DOCS / "plan_principles_spec.md")
        self.assertIn("temporary-feature-plan", content)
        self.assertIn(
            "マーカーコメント欠如",
            content,
            "plan_principles_spec.md に追加 feature frontmatter マーカー欠如の項目がない",
        )


class TestCriteriaLayer(unittest.TestCase):
    """提案 A (criteria): §2 が frontmatter 照合を参照し、severity は宣言しない。"""

    EDITED_CRITERIA = {
        "requirement": CRITERIA_DIR / "review_criteria_requirement.md",
        "design": CRITERIA_DIR / "review_criteria_design.md",
        "plan": CRITERIA_DIR / "review_criteria_plan.md",
    }

    def test_criteria_reference_frontmatter_check(self):
        """3 criteria が「追加 feature 文書の frontmatter 必須」照合ステップを持つこと。"""
        for kind, path in self.EDITED_CRITERIA.items():
            with self.subTest(kind=kind):
                content = _read(path)
                self.assertIn(
                    "追加 feature 文書の frontmatter 必須",
                    content,
                    f"{path.name} の §2 に frontmatter 照合ステップがない",
                )
                # 判定基準として additive_development_spec.md §1 を指していること
                self.assertIn(
                    "additive_development_spec.md",
                    content,
                    f"{path.name} が判定基準 (additive_development_spec.md §1) を参照していない",
                )

    def test_design_criteria_references_design_format(self):
        """design criteria の §1 SSOT参照が design_format.md を参照していること。

        requirement/plan criteria は対応 format を P1 で参照済みだが design criteria だけ
        欠落していた (Issue #118 が指摘した非対称の一部)。これを是正したことを検証する。
        """
        content = _read(self.EDITED_CRITERIA["design"])
        self.assertIn(
            "design_format.md",
            content,
            "review_criteria_design.md が design_format.md を参照していない "
            "(requirement/plan との非対称が残存)",
        )

    def test_edited_criteria_declare_no_severity(self):
        """編集した 3 criteria は severity 絵文字 (🔴/🟡/🟢) を一切宣言しないこと (FNC-402)。

        severity の SoT は principles の重大度カタログのみ。frontmatter 照合ステップを
        criteria に追加した際、誤って severity を直書きする退行を防ぐ。
        """
        for kind, path in self.EDITED_CRITERIA.items():
            with self.subTest(kind=kind):
                content = _read(path)
                for emoji in ("🔴", "🟡", "🟢"):
                    self.assertNotIn(
                        emoji,
                        content,
                        f"{path.name} に severity 絵文字 '{emoji}' が混入 "
                        "(FNC-402: criteria は severity を宣言しない)",
                    )


class TestGenerationLayer(unittest.TestCase):
    """提案 B: start-design / start-plan が追加開発分岐と frontmatter 付与を持つこと。

    生成層の非対称 (追加開発サポートが start-requirements のみに存在) を解消したことを
    検証する。SKILL.md はテキスト規約のため本リポジトリではユニットテスト対象外だが、
    Issue #118 の構造的欠陥 (生成層の伝播漏れ) の回帰を静的に検知する目的で文字列検証する。
    """

    GEN_SKILLS = {
        "start-requirements": (
            SKILLS_DIR / "start-requirements" / "SKILL.md",
            "type: temporary-feature-requirement",
        ),
        "start-design": (
            SKILLS_DIR / "start-design" / "SKILL.md",
            "type: temporary-feature-design",
        ),
        "start-plan": (
            SKILLS_DIR / "start-plan" / "SKILL.md",
            "type: temporary-feature-plan",
        ),
    }

    def test_skills_have_add_flag(self):
        """3 生成 SKILL が --add（追加開発）分岐を持つこと。"""
        for name, (path, _marker) in self.GEN_SKILLS.items():
            with self.subTest(skill=name):
                content = _read(path)
                self.assertIn(
                    "--add",
                    content,
                    f"{name}/SKILL.md に追加開発フラグ --add がない (生成層の非対称が残存)",
                )

    def test_skills_reference_frontmatter_type(self):
        """3 生成 SKILL が自種別の frontmatter type を付与指示していること。"""
        for name, (path, marker) in self.GEN_SKILLS.items():
            with self.subTest(skill=name):
                content = _read(path)
                self.assertIn(
                    marker,
                    content,
                    f"{name}/SKILL.md が '{marker}' の付与を指示していない",
                )

    def test_skills_reference_additive_spec(self):
        """start-design / start-plan が additive_development_spec.md を参照していること。"""
        for name in ("start-design", "start-plan"):
            with self.subTest(skill=name):
                content = _read(self.GEN_SKILLS[name][0])
                self.assertIn(
                    "additive_development_spec.md",
                    content,
                    f"{name}/SKILL.md が additive_development_spec.md を参照していない",
                )


if __name__ == "__main__":
    unittest.main()
