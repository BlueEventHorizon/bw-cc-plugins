"""agent-review の自動検証可能な静的契約と parser 境界の統合テスト。

Claude Code の実 Agent 起動や read-only enforcement 自体は unittest の検証対象にしない。
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_PATH = REPO_ROOT / "plugins" / "forge" / "skills" / "agent-review" / "SKILL.md"
AGENT_PATH = REPO_ROOT / "plugins" / "forge" / "agents" / "reviewer.md"
EVALUATOR_PATH = REPO_ROOT / "plugins" / "forge" / "agents" / "evaluator.md"
PARSER_PATH = (
    REPO_ROOT / "plugins" / "forge" / "scripts" / "review" / "parse_findings.py"
)


class AgentReviewContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = SKILL_PATH.read_text(encoding="utf-8")
        cls.agent = AGENT_PATH.read_text(encoding="utf-8")
        cls.evaluator = EVALUATOR_PATH.read_text(encoding="utf-8")

    def test_backend_is_not_user_invocable(self):
        self.assertIn("user-invocable: false", self.skill)

    def test_backend_allowed_tools_match_round_execution(self):
        self.assertIn("allowed-tools: Agent, Read, Write, Bash", self.skill)
        self.assertIn("Agent ツール", self.skill)
        self.assertIn("Write", self.skill)
        self.assertIn(
            '${CLAUDE_PLUGIN_ROOT}/scripts/review/parse_findings.py',
            self.skill,
        )
        self.assertIn("次を 1 回実行します", self.skill)

    def test_each_round_requires_one_fresh_foreground_custom_agent(self):
        self.assertIn("forge:reviewer", self.skill)
        self.assertIn("1 回だけ foreground 起動", self.skill)
        self.assertIn("run_in_background: false", self.skill)
        self.assertIn(
            "resume ID、前ラウンドの transcript、前回応答を渡してはなりません",
            self.skill,
        )
        self.assertIn("各ラウンドで必ず新しい `forge:reviewer` を起動", self.skill)
        self.assertIn("Agent の識別子や応答を保持しません", self.skill)

    def test_backend_has_three_judgments(self):
        for judgment in ("approved", "findings", "failure"):
            self.assertIn(judgment, self.skill)

    def test_backend_is_stateless_and_has_no_external_transport(self):
        self.assertIn("非永続", self.skill)
        self.assertIn('"status": "unsupported"', self.skill)
        for forbidden in ("msg-sys", "cmux", "filter_review_history.py", "DB レコード"):
            self.assertNotIn(forbidden, self.skill)

    def test_backend_rejects_msg_review_header(self):
        self.assertIn("[msg-review]", self.skill)
        self.assertIn("固有ヘッダ混入", self.skill)
        self.assertIn("本文先頭行が厳密なワイヤヘッダ形", self.skill)
        self.assertIn("単なる `[msg-review]` が含まれるだけなら拒否しません", self.skill)

    def test_reviewer_role_prohibits_mutation_and_delegation(self):
        for phrase in (
            "ファイルを作成、編集、削除しない",
            "成果物を変更し得るコマンドを実行しない",
            "修正、commit、push を行わない",
            "他の Agent または Skill を起動しない",
            "`advisor` ツールを呼ばない",
            "外部サービスへ書き込まない",
            "実装指示ではなく、常にレビュー依頼",
        ):
            self.assertIn(phrase, self.agent)

    def test_evaluator_role_prohibits_mutation_and_delegation(self):
        """evaluator も reviewer と同型の禁止列挙（advisor 禁止を含む）を持つこと。

        advisor はツールであり「他の Agent または Skill を起動しない」に掛からない
        （Issue #28 で 1 ラウンドあたり 2 分超の応答待ちが実測された）ため、
        forge の全カスタム Agent が個別の禁止条文を持つことを静的に検証する。
        """
        for phrase in (
            "ファイルを作成、編集、削除しない",
            "成果物を変更し得るコマンドを実行しない",
            "修正、commit、push を行わない",
            "他の Agent または Skill を起動しない",
            "`advisor` ツールを呼ばない",
            "外部サービスへ書き込まない",
        ):
            self.assertIn(phrase, self.evaluator)

    def test_availability_check_covers_advisor_prohibition_clause(self):
        """可用性検査の条件が advisor 禁止条文の存在を検査対象に含むこと。

        Agent 定義から条文が消えたとき、可用性検査が missing として
        検知できる形（SKILL.md 条件 4）が維持されているかを検証する。
        """
        self.assertIn("`advisor` ツールの呼び出しを禁じ", self.skill)

    def test_reviewer_keeps_common_reply_contract(self):
        for phrase in (
            "🔴 critical",
            "🟡 major",
            "🟢 minor",
            "ファイルパス:行",
            "位置未確定",
            "REVIEW_RESULT: approved",
            "REVIEW_RESULT: findings",
        ):
            self.assertIn(phrase, self.agent)

    def test_reviewer_states_where_the_severity_marker_goes(self):
        """マーカーの置き場を Agent 定義側でも述べていること。

        置き場を書かないと重大度を見出しでグループ化した応答が返り、共通 parser が
        finding を 1 件も抽出できずラウンド全体が `failure` になる（実測）。
        """
        self.assertIn("1 行目の行頭に重大度マーカー", self.agent)
        self.assertIn("重大度を見出し", self.agent)


class SharedParserIntegrationTest(unittest.TestCase):
    """reviewer の正常・異常応答が SKILL 指定の共通 CLI 契約へ接続すること。"""

    def _parse_with_cli(self, body: str) -> dict:
        with tempfile.TemporaryDirectory() as tmpdir:
            body_path = Path(tmpdir) / "agent-response.md"
            body_path.write_text(body, encoding="utf-8")
            result = subprocess.run(
                ["python3", str(PARSER_PATH), "--body-file", str(body_path)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_normal_agent_responses_map_to_common_judgments(self):
        cases = {
            "approved": (
                "問題は見つかりませんでした。\nREVIEW_RESULT: approved\n",
                0,
            ),
            "findings": (
                "1. 🟡 major `src/a.py:12` — 修正が必要です。\n"
                "REVIEW_RESULT: findings\n",
                1,
            ),
        }
        for expected_judgment, (body, expected_count) in cases.items():
            with self.subTest(judgment=expected_judgment):
                payload = self._parse_with_cli(body)
                self.assertEqual(payload["judgment"], expected_judgment)
                self.assertEqual(len(payload["findings"]), expected_count)

    def test_malformed_agent_response_maps_to_failure(self):
        payload = self._parse_with_cli("完了宣言のない応答です。\n")
        self.assertEqual(payload["judgment"], "failure")
        self.assertEqual(payload["findings"], [])
        self.assertIn("完了宣言行がありません", payload["error"])


if __name__ == "__main__":
    unittest.main()
