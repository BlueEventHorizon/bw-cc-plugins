#!/usr/bin/env python3
"""executor と オーケストレーターの契約が 2 文書間で食い違わないことを検査する。

`task_execution_spec.md`（executor が読む実行ガイド）と `start-implement/SKILL.md`
（起動・受領を行う側）は、同じ契約の両端を別々に記述している。片方だけを直すと、
executor が返す形と受領側が期待する形がずれたまま実行される。

各テストは守っている対象を docstring に記す。文言の維持が目的ではないため、
契約そのものを変える改訂では本テストも同時に直す。
"""

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
        """Pre-Mortem が「既存コード確認の後・実装の前」に置かれていること。

        この順序が Pre-Mortem の成立条件である。既存コードを見る前に行えば根拠を
        持たない一般論になり、実装を始めた後に行えば書いたものを正当化する分析になる。

        検査は節見出しの出現順で行う。節名を変える改訂では、本テストの見出し文字列も
        同時に直す（守っているのは順序であり、見出しの文言ではない）。
        """
        code_check = self.text.index("### 2.2 既存コード確認")
        pre_mortem = self.text.index("### 2.3 Pre-Mortem（事前失敗分析）")
        implementation = self.text.index("## Step 3: 実装")
        self.assertLess(code_check, pre_mortem)
        self.assertLess(pre_mortem, implementation)

    def test_pre_mortem_contract_is_complete(self):
        """Pre-Mortem が executor に課す制約が spec から欠落していないこと。

        列挙する各句は、いずれも executor の逸脱を抑えるために置かれた制約である。
        前半 4 句は Pre-Mortem の成果物の要件（件数上限・根拠・回避策・反映先）、
        後半 6 句は逸脱の禁止（水増し・スコープ拡大・検証要件の改変・スキップ指定の
        無視・戦略書の転記・完了報告の肥大）にあたる。

        句を消す・言い換える改訂を行うときは、当該制約が不要になったのかを判断した
        うえで本テストも同時に直す。文言の維持自体が目的ではない。
        """
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
        """Pre-Mortem の結果が完了確認まで残り、結果 JSON に受け皿があること。

        Pre-Mortem は実装前に行うため、成果が実装へ反映されたかを完了時に確認しないと
        分析しただけで終わる。spec の完了確認に反映の確認があること、および結果
        テンプレート `executor_result.json` に `pre_mortem` の 2 フィールドが
        存在することを検査する（テンプレートに無ければ executor は報告先を持たない）。
        """
        self.assertIn(
            "Pre-Mortem の回避策を実装、または指定済み検証の範囲内へ反映した",
            self.text,
        )
        self.assertEqual(self.template["pre_mortem"]["actualized_risks"], [])
        self.assertEqual(self.template["pre_mortem"]["implementation_adjustments"], [])

    def test_executor_output_contract_is_json_for_single_and_parallel_runs(self):
        """executor の出力契約が単一実行・並列実行で分岐していないこと。

        かつて SKILL 側が実行形態ごとに別の出力形式を定めており、受領側が形態を
        見分けて解釈する必要があった。現在は形態を問わず result template の JSON
        だけを返す 1 本の契約である。

        `assertNotIn` は分岐の再導入を検出する:

        - `#### 単一タスク実行時` / `#### 複数タスク並列実行時` — 結果受領の節に
          形態別の見出しが戻れば、契約が再び 2 本になる
        - `` ```json `` が spec に無いこと — JSON の実体はテンプレートファイルが持つ。
          spec に写すと真実源が 2 つになり、片方だけ古くなる
        """
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
        """オーケストレーターが executor の結果を最小スキーマへ切り詰めないこと。

        後続処理が使うのは `task_id` / `status` / `files_modified` / `summary` /
        `error` だが、`verification` / `pre_mortem` / `notes` はタスク結果の報告と
        エラー対応で読まれる。不要に見えて捨てると、Pre-Mortem の成果と検証の実施
        状況が executor から先へ届かなくなる。
        """
        self.assertIn(
            "`verification` / `pre_mortem` / `notes`",
            self.start_implement,
        )
        self.assertIn(
            "追加フィールドを削除して最小スキーマへ変換しない",
            self.start_implement,
        )

    def test_producer_and_consumer_use_fixed_local_entries(self):
        """結果 JSON の受け渡しが、固定の script と入力ファイル経由であること。

        executor が返す JSON は AI が解釈する前に検証を通す。producer（executor 側）と
        consumer（オーケストレーター側）が同じ CLI 契約を指していなければ、片方だけ
        直したときに検証が素通りする。そのため引数名は spec と SKILL の**両方**に
        あることを検査する。

        `assertNotIn` はそれぞれ別の事故を防ぐ:

        - `${CLAUDE_PLUGIN_ROOT}` — 本 spec は `${CLAUDE_SKILL_DIR}/docs/` 経由で
          executor が読む。スキル外を指すプレースホルダが混じると解決先が変わる
        - `<<'JSON'` — JSON を heredoc でシェルへ埋め込む方式の再導入。引用の扱いで
          内容が壊れるため、Write でファイルへ書いて `--input-file` で渡す
        - `--failure-on-error` — エラー時の方針を CLI フラグとして呼び出し側に
          選ばせる形への後退。現在この方針は wrapper が固定で持つ（producer は
          訂正可能なエラー、consumer は FAILURE 確定）。フラグにすると呼び出しごとに
          変えられてしまい、両者の役割の違いが失われる
        """
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
