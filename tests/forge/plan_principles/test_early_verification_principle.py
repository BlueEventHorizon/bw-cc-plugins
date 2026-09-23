#!/usr/bin/env python3
"""タスク粒度の基準が、規範文書と生成側 SKILL の間で乖離していないことを検査する回帰テスト。

検査するのは 2 文書間の不一致であり、規範文書に特定の文言が存在するかではない
（文言の存在は規範の存在を意味せず、否定形に書き換えても通るため検証として成立しない）。

実行:
  python3 -m unittest tests.forge.plan_principles.test_early_verification_principle -v
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]

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
