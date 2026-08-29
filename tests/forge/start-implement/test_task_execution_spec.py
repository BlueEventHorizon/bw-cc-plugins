#!/usr/bin/env python3
"""task_execution_spec.md の Executor Pre-Mortem 契約テスト。"""

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = (
    REPO_ROOT
    / "plugins"
    / "forge"
    / "skills"
    / "start-implement"
    / "docs"
    / "task_execution_spec.md"
)
START_IMPLEMENT_PATH = (
    REPO_ROOT / "plugins" / "forge" / "skills" / "start-implement" / "SKILL.md"
)
TEMPLATE_PATH = (
    REPO_ROOT
    / "plugins"
    / "forge"
    / "skills"
    / "start-implement"
    / "templates"
    / "executor_result.json"
)


class ExecutorPreMortemContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SPEC_PATH.read_text(encoding="utf-8")
        cls.start_implement = START_IMPLEMENT_PATH.read_text(encoding="utf-8")
        cls.template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))

    def test_pre_mortem_runs_after_context_gathering_and_before_implementation(self):
        code_check = self.text.index("### 2.2 既存コード確認")
        pre_mortem = self.text.index("### 2.3 Pre-Mortem（事前失敗分析）")
        implementation = self.text.index("## Step 3: 実装")
        self.assertLess(code_check, pre_mortem)
        self.assertLess(pre_mortem, implementation)

    def test_pre_mortem_contract_is_complete(self):
        required_phrases = (
            "失敗に至る具体的な原因を最大 5 件",
            "文書・コード・依存関係に基づく根拠",
            "各原因を防ぐ具体的な回避策",
            "指定した Step 4 の検証要件の範囲内へ反映",
            "一般論・仮定を水増ししない",
            "回避策を理由にスコープ境界を広げない",
            "回避策を理由に検証要件を追加・変更しない",
            "指定が `スキップ` の検証を実行せず",
            "戦略書に記載済みのリスクをそのまま転記しない",
            "Pre-Mortem の全内容を完了報告へ転記しない",
        )
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_completion_check_and_report_preserve_pre_mortem_results(self):
        self.assertIn(
            "Pre-Mortem の回避策を実装、または指定済み検証の範囲内へ反映した",
            self.text,
        )
        self.assertEqual(self.template["pre_mortem"]["actualized_risks"], [])
        self.assertEqual(self.template["pre_mortem"]["implementation_adjustments"], [])

    def test_executor_output_contract_is_json_for_single_and_parallel_runs(self):
        self.assertIn(
            "単一実行・並列実行を問わず、オーケストレーターから受領した result template",
            self.text,
        )
        self.assertIn(
            "単一実行・並列実行を問わず、実行ガイド Step 5 の JSON だけ",
            self.start_implement,
        )
        result_contract = self.start_implement.split(
            "### 4.5 executor の結果受領",
            maxsplit=1,
        )[1].split("\n---", maxsplit=1)[0]
        self.assertNotIn("#### 単一タスク実行時", result_contract)
        self.assertNotIn("#### 複数タスク並列実行時", result_contract)
        self.assertNotIn("```json", self.text)
        self.assertIn(
            "${CLAUDE_SKILL_DIR}/templates/executor_result.json",
            self.start_implement,
        )

    def test_orchestrator_preserves_pre_mortem_fields(self):
        self.assertIn(
            "`verification` / `pre_mortem` / `notes`",
            self.start_implement,
        )
        self.assertIn(
            "追加フィールドを削除して最小スキーマへ変換しない",
            self.start_implement,
        )

    def test_producer_and_consumer_use_fixed_local_entries(self):
        self.assertIn(
            "${CLAUDE_SKILL_DIR}/scripts/validate_executor_result.py",
            self.start_implement,
        )
        self.assertIn(
            "${CLAUDE_SKILL_DIR}/scripts/receive_executor_result.py",
            self.start_implement,
        )
        self.assertIn("producer validator", self.text)
        self.assertIn("オーケストレーターから受領した producer validator パス", self.text)
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", self.text)
        self.assertIn("Write から同じ手順をもう 1 回だけ実行する", self.text)
        self.assertIn("内容を AI が解釈する前に consumer wrapper", self.start_implement)
        self.assertNotIn("--failure-on-error", self.start_implement)
        self.assertIn("--input-file", self.text)
        self.assertIn("--input-file", self.start_implement)
        self.assertIn("--expected-build", self.text)
        self.assertIn("--expected-build", self.start_implement)
        self.assertIn("--expected-tests", self.text)
        self.assertIn("--expected-tests", self.start_implement)
        self.assertNotIn("<<'JSON'", self.text)
        self.assertNotIn("<<'JSON'", self.start_implement)


if __name__ == "__main__":
    unittest.main()
