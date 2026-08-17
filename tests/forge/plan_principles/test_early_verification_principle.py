#!/usr/bin/env python3
"""早期検証規範（forge-early-verification）の静的テキスト契約テスト。

`strategy_formulation_spec.md` Step 4 と `plan_principles_spec.md`「タスクグループ」節・
重大度カタログに追記された早期検証規範が、将来の文書改訂でサイレントに消失・改変されて
いないことを検査する回帰テスト。

`test_plan_json_contract.py` / `test_forge_toc_freshness.py` と同型の静的検査
（実ファイル Read + アサーション）であり、規範の意味的妥当性ではなく
キー文言の存在のみを検査する。

実行:
  python3 -m unittest tests.forge.plan_principles.test_early_verification_principle -v
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]

STRATEGY_FORMULATION_SPEC = (
    REPO_ROOT / "plugins" / "forge" / "docs" / "strategy_formulation_spec.md"
)
PLAN_PRINCIPLES_SPEC = REPO_ROOT / "plugins" / "forge" / "docs" / "plan_principles_spec.md"
START_PLAN_SKILL = REPO_ROOT / "plugins" / "forge" / "skills" / "start-plan" / "SKILL.md"

# plan_principles_spec.md がタスク粒度・グループサイズを定量的上限から定性的基準
# （「1つの Agent 実行で完結する単位」）へ改めた際、計画を実際に生成する
# start-plan/SKILL.md 側の記述が追随しておらず、生成側とレビュー側で判断基準が
# 乖離する回帰が起きた（レビュー時に発覚）。同種の数値ハードコード
# 再導入をどちらの文書についても検出するため、フォーマット済み文字列
# （全角/半角ゆらぎ）を含めて禁止パターンとして固定する。
FORBIDDEN_QUANTITATIVE_GRANULARITY_PATTERNS = [
    re.compile(r"最大\s*10\s*タスク"),
    re.compile(r"2\s*[〜~〜]\s*3\s*(つの)?ファイル"),
]


class TestStrategyFormulationSpecStep4EarlyVerification(unittest.TestCase):
    """strategy_formulation_spec.md Step 4「フェーズ分割の原則」の早期検証指示を検査"""

    def setUp(self) -> None:
        self.assertTrue(
            STRATEGY_FORMULATION_SPEC.exists(), f"missing: {STRATEGY_FORMULATION_SPEC}"
        )
        self.text = STRATEGY_FORMULATION_SPEC.read_text(encoding="utf-8")

    def test_step4_section_exists(self) -> None:
        self.assertIn(
            "### Step 4: フェーズ分割",
            self.text,
            "strategy_formulation_spec.md に Step 4「フェーズ分割」節が見当たらない",
        )

    def test_phase_division_principles_section_exists(self) -> None:
        self.assertIn(
            "**フェーズ分割の原則**:",
            self.text,
            "strategy_formulation_spec.md に「フェーズ分割の原則」見出しが見当たらない",
        )

    def test_step4_instructs_early_verification_for_structural_relocation_tasks(self) -> None:
        """構造移設・新規モジュール作成タスク群の早期検証指示が存在すること"""
        step4_start = self.text.find("### Step 4: フェーズ分割")
        step5_start = self.text.find("### Step 5:")
        self.assertGreater(step4_start, -1)
        self.assertGreater(step5_start, step4_start)
        step4_text = self.text[step4_start:step5_start]

        for keyword in ("構造移設", "新規モジュール作成", "最小の動作確認可能な単位"):
            with self.subTest(keyword=keyword):
                self.assertIn(
                    keyword,
                    step4_text,
                    f"Step 4「フェーズ分割の原則」に早期検証指示のキーワード '{keyword}' が無い",
                )

        self.assertIn(
            "検証を先送りしない",
            step4_text,
            "Step 4「フェーズ分割の原則」に「検証を先送りしない」旨の指示が無い",
        )


class TestPlanPrinciplesSpecTaskGroupSection(unittest.TestCase):
    """plan_principles_spec.md「タスクグループ」節の用語定義・妥当性条件を検査"""

    def setUp(self) -> None:
        self.assertTrue(PLAN_PRINCIPLES_SPEC.exists(), f"missing: {PLAN_PRINCIPLES_SPEC}")
        self.text = PLAN_PRINCIPLES_SPEC.read_text(encoding="utf-8")

    def _extract_task_group_section(self) -> str:
        start = self.text.find("## タスクグループ")
        self.assertGreater(start, -1, "「タスクグループ」節の見出しが見当たらない")
        end = self.text.find("\n## ", start + 1)
        self.assertGreater(end, start, "「タスクグループ」節の終端（次の見出し）が見当たらない")
        return self.text[start:end]

    def test_task_group_section_defines_minimum_verifiable_unit_term(self) -> None:
        section = self._extract_task_group_section()
        self.assertIn(
            "最小の動作確認可能な単位",
            section,
            "「タスクグループ」節に「最小の動作確認可能な単位」の用語定義が無い",
        )
        for keyword in ("構造移設", "新規モジュール作成", "単体で動作確認"):
            with self.subTest(keyword=keyword):
                self.assertIn(
                    keyword,
                    section,
                    f"「タスクグループ」節の用語定義に '{keyword}' が含まれていない",
                )

    def test_task_group_section_has_validity_condition(self) -> None:
        section = self._extract_task_group_section()
        self.assertIn(
            "妥当性条件",
            section,
            "「タスクグループ」節に妥当性条件の記述が無い",
        )
        self.assertIn(
            "build_check: skip",
            section,
            "「タスクグループ」節の妥当性条件に `build_check: skip` の言及が無い",
        )
        self.assertIn(
            "build_check: on_group_complete",
            section,
            "「タスクグループ」節の妥当性条件に `build_check: on_group_complete` の言及が無い",
        )


class TestPlanPrinciplesSpecSeverityCatalogNewViolationPattern(unittest.TestCase):
    """重大度カタログ「タスクグループ」表に早期検証欠如の違反パターン行が存在することを検査"""

    def setUp(self) -> None:
        self.assertTrue(PLAN_PRINCIPLES_SPEC.exists(), f"missing: {PLAN_PRINCIPLES_SPEC}")
        self.text = PLAN_PRINCIPLES_SPEC.read_text(encoding="utf-8")

    def _extract_severity_catalog_task_group_table(self) -> str:
        catalog_start = self.text.find("## 重大度カタログ")
        self.assertGreater(catalog_start, -1, "「重大度カタログ」節の見出しが見当たらない")
        table_start = self.text.find("### タスクグループ", catalog_start)
        self.assertGreater(
            table_start, -1, "重大度カタログ内に「タスクグループ」表の見出しが見当たらない"
        )
        table_end = self.text.find("\n### ", table_start + 1)
        self.assertGreater(table_end, table_start, "「タスクグループ」表の終端が見当たらない")
        return self.text[table_start:table_end]

    def test_severity_catalog_has_early_verification_violation_row(self) -> None:
        table = self._extract_severity_catalog_task_group_table()

        self.assertIn(
            "最小の動作確認可能な単位",
            table,
            "重大度カタログ「タスクグループ」表に早期検証欠如の新パターン行が無い",
        )

        # 新パターン行を先に特定し、以降の検査はすべて同一行に対して行う
        # （表全体に対する検査だと、他行に同じ語が存在すれば対象行の欠落を検出できない）
        pattern_row = None
        for line in table.splitlines():
            if "最小の動作確認可能な単位" in line and line.strip().startswith("|"):
                pattern_row = line
                break
        self.assertIsNotNone(
            pattern_row, "早期検証欠如の新パターン行がテーブル行として見当たらない"
        )
        self.assertIn(
            "skip",
            pattern_row,
            f"早期検証欠如の新パターン行に `skip` の言及が無い: {pattern_row!r}",
        )
        self.assertIn(
            "🟡",
            pattern_row,
            f"早期検証欠如の新パターン行に重大度マーカー（🟡）が無い: {pattern_row!r}",
        )

    def test_severity_catalog_preserves_existing_task_group_patterns(self) -> None:
        """既存3パターンと矛盾・重複なく共存していることを回帰的に確認"""
        table = self._extract_severity_catalog_task_group_table()
        existing_patterns = [
            re.compile(r"build_check:\s*per_task"),
            re.compile(r"グループサイズ"),
            re.compile(r"グループ最終タスク"),
        ]
        for pattern in existing_patterns:
            with self.subTest(pattern=pattern.pattern):
                self.assertIsNotNone(
                    pattern.search(table),
                    f"重大度カタログ「タスクグループ」表から既存パターン '{pattern.pattern}' が失われている",
                )


class TestTaskGranularityWordingConsistencyAcrossGenerationAndReview(unittest.TestCase):
    """タスク粒度・グループサイズの定性化 (plan_principles_spec.md) が
    計画生成側 (start-plan/SKILL.md) にも及んでいることを検査する回帰テスト。

    plan_principles_spec.md 側だけを修正して start-plan/SKILL.md 側の
    定量的上限（「最大10タスク」「2〜3ファイル」）を残したまま放置すると、
    同一のタスクグループを生成側は「分割必須」、レビュー側は「Agent の
    能力次第で許容」と判断しうる不整合が生じる。この乖離は
    「グループサイズ」という語の存在確認だけでは検出できないため、
    禁止された定量表現そのものの不在を両文書について直接検査する。
    """

    def test_plan_principles_spec_has_no_quantitative_granularity_limits(self) -> None:
        self.assertTrue(PLAN_PRINCIPLES_SPEC.exists(), f"missing: {PLAN_PRINCIPLES_SPEC}")
        text = PLAN_PRINCIPLES_SPEC.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_QUANTITATIVE_GRANULARITY_PATTERNS:
            with self.subTest(pattern=pattern.pattern):
                match = pattern.search(text)
                self.assertIsNone(
                    match,
                    "plan_principles_spec.md に定量的な粒度上限が再導入されている: "
                    f"{pattern.pattern!r} -> {match.group(0) if match else None!r}",
                )

    def test_start_plan_skill_has_no_quantitative_granularity_limits(self) -> None:
        """generation 側 (start-plan/SKILL.md) が review 側の定性基準から乖離していないこと"""
        self.assertTrue(START_PLAN_SKILL.exists(), f"missing: {START_PLAN_SKILL}")
        text = START_PLAN_SKILL.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_QUANTITATIVE_GRANULARITY_PATTERNS:
            with self.subTest(pattern=pattern.pattern):
                match = pattern.search(text)
                self.assertIsNone(
                    match,
                    "start-plan/SKILL.md に定量的な粒度上限が残存している"
                    "（plan_principles_spec.md の定性化に追随していない）: "
                    f"{pattern.pattern!r} -> {match.group(0) if match else None!r}",
                )

    def test_start_plan_skill_uses_qualitative_group_completeness_wording(self) -> None:
        """定性基準への置換が消失（単なる削除）ではなく実際に反映されていること"""
        self.assertTrue(START_PLAN_SKILL.exists(), f"missing: {START_PLAN_SKILL}")
        text = START_PLAN_SKILL.read_text(encoding="utf-8")
        self.assertIn(
            "1つの Agent 実行で完結する",
            text,
            "start-plan/SKILL.md に定性的なタスク/グループ粒度基準の文言が無い",
        )


if __name__ == "__main__":
    unittest.main()
